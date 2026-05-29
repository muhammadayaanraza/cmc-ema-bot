#!/usr/bin/env python3

import asyncio
import logging
import os
from datetime import datetime, timezone

import requests
import pandas as pd
from telegram import Bot
from telegram.request import HTTPXRequest

# ======================
# CONFIG
# ======================
BOT_TOKEN = os.getenv("BOT_TOKEN", "APNA_BOT_TOKEN_YAHAN")
CHAT_ID = os.getenv("CHAT_ID", "APNA_CHAT_ID_YAHAN")

INTERVAL_MINUTES = 15
EMA_FAST = 9
EMA_SLOW = 50

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("PureFuturesBot")

# ==========================================================
# 1. FETCH ALL FUTURES COINS FROM BINANCE
# ==========================================================
def get_futures_tickers():
    try:
        log.info("Fetching active futures symbols...")
        url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
        r = requests.get(url, timeout=10)
        
        tickers = []
        if r.status_code == 200:
            data = r.json()
            for market in data.get("symbols", []):
                if market.get("quoteAsset") == "USDT" and market.get("status") == "TRADING":
                    symbol = market.get("symbol") # E.g., "BTCUSDT"
                    base = market.get("baseAsset")
                    if base not in ["USDT", "USDC", "DAI", "BUSD"]:
                        tickers.append(symbol)
                        
        if not tickers:
            return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
            
        return list(dict.fromkeys(tickers))
    except Exception as e:
        log.error(f"Error fetching tickers: {e}")
        return ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

# ==========================================================
# 2. FETCH OHLCV DIRECTLY FROM BINANCE FUTURES (BULLETPROOF)
# ==========================================================
def fetch_futures_ohlcv(symbol):
    try:
        # 15m timeframe ke liye Binance Futures API se 100 candles mangwana
        url = "https://fapi.binance.com/fapi/v1/klines"
        params = {"symbol": symbol, "interval": "15m", "limit": "100"}
        
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return None
            
        data = r.json()
        if not data or len(data) < EMA_SLOW:
            return None
            
        # Standard DataFrame banana
        df = pd.DataFrame(data, columns=[
            "ts", "open", "high", "low", "close", "volume", 
            "close_time", "asset_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"
        ])
        
        # Numbers ko float mein convert karna
        df["open"] = df["open"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["close"] = df["close"].astype(float)
        
        return df
    except Exception:
        return None

# ==========================================
# TECHNICAL INDICATORS
# ==========================================
def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))

# ==========================================
# SIGNAL DETECTION WITH RSI FILTERS
# ==========================================
def detect_signal_details(df):
    close = df["close"]
    
    ema9 = calc_ema(close, EMA_FAST)
    ema50 = calc_ema(close, EMA_SLOW)
    rsi_series = calc_rsi(close, 14)

    current_above = ema9.iloc[-1] > ema50.iloc[-1]
    previous_above = ema9.iloc[-2] > ema50.iloc[-2]

    # Crossover Code
    if current_above == previous_above:
        return None

    signal_type = "LONG" if current_above else "SHORT"
    entry_price = float(close.iloc[-1])
    current_rsi = float(rsi_series.iloc[-1])

    # Strict RSI Filter Rules
    if signal_type == "LONG":
        if not (50.0 <= current_rsi <= 70.0):
            return None
    else:
        if not (30.0 <= current_rsi <= 50.0):
            return None

    # Risk Management Settings
    last_few_candles = df.tail(4)
    if signal_type == "LONG":
        stop_loss = float(last_few_candles["low"].min()) * 0.996
        risk = entry_price - stop_loss
        if risk <= 0: risk = entry_price * 0.008
        take_profit1 = entry_price + (risk * 1.3)
        take_profit2 = entry_price + (risk * 2.3)
    else:
        stop_loss = float(last_few_candles["high"].max()) * 1.004
        risk = stop_loss - entry_price
        if risk <= 0: risk = entry_price * 0.008
        take_profit1 = entry_price - (risk * 1.3)
        take_profit2 = entry_price - (risk * 2.3)

    return {
        "type": signal_type,
        "entry": entry_price,
        "sl": stop_loss,
        "tp1": take_profit1,
        "tp2": take_profit2,
        "rsi": current_rsi
    }

# ==========================================
# TELEGRAM MESSAGE BUILDER
# ==========================================
def build_message(symbol, signal):
    now = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    clean_symbol = symbol.replace("USDT", "")
    
    def fmt(val):
        if val >= 100: return f"{val:.2f}"
        if val >= 1: return f"{val:.4f}"
        return f"{val:.6f}"

    emoji = "🟢" if signal["type"] == "LONG" else "🔴"
    
    return (
        f"🚨 **CONFIRMED FUTURES SIGNAL (9/50 EMA)** 🚨\n\n"
        f"🪙 **Coin:** #{clean_symbol}/USDT\n"
        f"📈 **Direction:** {emoji} {signal['type']}\n"
        f"⏱ **Timeframe:** 15 Minute\n\n"
        f"📥 **Entry Price:** {fmt(signal['entry'])}\n"
        f"🎯 **Take Profit 1:** {fmt(signal['tp1'])}\n"
        f"🎯 **Take Profit 2:** {fmt(signal['tp2'])}\n"
        f"🛑 **Stop Loss:** {fmt(signal['sl'])}\n\n"
        f"📊 **Filters:**\n"
        f"✅ RSI (14) Confirmed: {signal['rsi']:.1f}\n\n"
        f"🕒 _Generated at: {now}_"
    )

# ==========================================
# MAIN BOT LOOP
# ==========================================
async def run_bot():
    request = HTTPXRequest(connection_pool_size=30)
    bot = Bot(token=BOT_TOKEN, request=request)

    async with bot:
        try:
            await bot.send_message(
                chat_id=CHAT_ID,
                text="🤖 WEEX/Binance Full-Scale Futures Bot Online!\n⚡ 9/50 EMA + RSI Filters Active on 100% of Altcoins.",
            )
        except Exception as e:
            log.error(f"Telegram connection error: {e}")

        while True:
            pairs_list = get_futures_tickers()

            try:
                await bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"🔄 Full Futures Market Loaded!\n🔍 Scanning {len(pairs_list)} Coins via Native Backend...",
                )
            except:
                pass

            scanned = 0
            skipped = 0
            found = 0

            for symbol in pairs_list:
                df = fetch_futures_ohlcv(symbol)
                if df is None:
                    skipped += 1
                    continue

                scanned += 1
                signal = detect_signal_details(df)

                if signal:
                    found += 1
                    try:
                        await bot.send_message(
                            chat_id=CHAT_ID,
                            text=build_message(symbol, signal),
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        log.error(f"Telegram send fail: {e}")

                # Chota delay taaki smooth scanning ho
                await asyncio.sleep(0.05)

            summary = (
                f"📡 **Scan Complete**\n\n"
                f"🔍 Total Scanned: {scanned} coins\n"
                f"✅ Safe Signals Found: {found}\n"
                f"⏭ Skipped/Invalid: {skipped}\n"
                f"⏱ Next massive scan in 15 minutes"
            )
            try:
                await bot.send_message(chat_id=CHAT_ID, text=summary, parse_mode="Markdown")
            except Exception as e:
                log.error(f"Summary send fail: {e}")
                
            await asyncio.sleep(INTERVAL_MINUTES * 60)

if __name__ == "__main__":
    if "APNA" in BOT_TOKEN or not BOT_TOKEN:
        raise SystemExit
    if "APNA" in CHAT_ID or not CHAT_ID:
        raise SystemExit

    asyncio.run(run_bot())
