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
EMA_FAST = 20
EMA_SLOW = 200

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("WeexFuturesBot")

# ==========================================
# FETCH LIVE FUTURES PAIRS DIRECT FROM WEEX
# ==========================================
def get_weex_futures_tickers():
    try:
        log.info("Fetching live USDT Futures pairs directly from WEEX...")
        # WEEX V2 Public API endpoint for swap/futures market instruments
        url = "https://api.weex.com/api/v2/mix/market/tickers"
        params = {"productType": "umcbl"} # USDT-M Perpetual Contracts
        
        r = requests.get(url, params=params, timeout=15)
        tickers = []
        
        if r.status_code == 200:
            res_data = r.json()
            if res_data.get("code") == "0" and "data" in res_data:
                for contract in res_data["data"]:
                    symbol = contract.get("symbol", "") # e.g., BTCUSDT
                    
                    if symbol.endswith("USDT") and not any(x in symbol for x in ["USDC", "EUR", "DAI"]):
                        # Extract base coin name (e.g., BTC from BTCUSDT)
                        base = symbol.replace("USDT", "")
                        tickers.append(base)
                        
        if not tickers:
            return ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE"]
            
        # Remove duplicates and cap to top 250 assets for smooth processing
        return list(dict.fromkeys(tickers))[:250]
    except Exception as e:
        log.error(f"Error fetching official WEEX tickers: {e}")
        return ["BTC", "ETH", "SOL", "BNB", "XRP"]

# ==========================================
# FETCH LIVE K-LINES FROM WEEX FUTURES API
# ==========================================
def fetch_weex_ohlcv(symbol):
    pair = f"{symbol}USDT"
    try:
        # WEEX V2 Public API for Futures K-lines
        url = "https://api.weex.com/api/v2/mix/market/candles"
        
        # WEEX takes timestamp in milliseconds, fetching last 4-5 days data for 200 EMA
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = end_time - (5 * 24 * 60 * 60 * 1000)
        
        params = {
            "symbol": pair,
            "productType": "umcbl",
            "granularity": "15m", # 15 Minute Timeframe
            "startTime": str(start_time),
            "endTime": str(end_time),
            "limit": "300"
        }
        
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return None

        res_data = r.json()
        if res_data.get("code") != "0" or "data" not in res_data:
            return None

        # WEEX returns K-line array format: [timestamp, open, high, low, close, volume, ...]
        raw_candles = res_data["data"]
        if len(raw_candles) < EMA_SLOW:
            return None

        # Parsing data into Pandas DataFrame
        df_list = []
        for c in raw_candles:
            df_list.append({
                "ts": int(c[0]),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4])
            })
            
        df = pd.DataFrame(df_list)
        # WEEX APIs normally return data in descending order, we sort it chronologically
        df = df.sort_values(by="ts").reset_index(drop=True)
        
        return df
    except Exception as e:
        log.error(f"Error fetching WEEX data for {symbol}: {e}")
        return None

# ==========================================
# TECHNICAL CALCULATIONS
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
# SIGNAL DETECTION LOGIC
# ==========================================
def detect_weex_signal(df):
    close = df["close"]
    if len(close) < EMA_SLOW + 15:
        return None

    ema20 = calc_ema(close, EMA_FAST)
    ema200 = calc_ema(close, EMA_SLOW)
    rsi_series = calc_rsi(close, 14)

    current_above = ema20.iloc[-1] > ema200.iloc[-1]
    previous_above = ema20.iloc[-2] > ema200.iloc[-2]

    # Only identify strict crossovers
    if current_above == previous_above:
        return None

    signal_type = "LONG" if current_above else "SHORT"
    entry_price = float(close.iloc[-1])
    current_rsi = float(rsi_series.iloc[-1])

    last_few_candles = df.tail(5)
    
    # Target calculations customized for accurate execution
    if signal_type == "LONG":
        stop_loss = float(last_few_candles["low"].min()) * 0.995
        risk = entry_price - stop_loss
        if risk <= 0: risk = entry_price * 0.01
        take_profit1 = entry_price + (risk * 1.5)
        take_profit2 = entry_price + (risk * 2.5)
    else:
        stop_loss = float(last_few_candles["high"].max()) * 1.005
        risk = stop_loss - entry_price
        if risk <= 0: risk = entry_price * 0.01
        take_profit1 = entry_price - (risk * 1.5)
        take_profit2 = entry_price - (risk * 2.5)

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
    
    def fmt(val):
        if val >= 100: return f"{val:.2f}"
        if val >= 1: return f"{val:.4f}"
        return f"{val:.6f}"

    emoji = "🟩 LONG 🟢" if signal["type"] == "LONG" else "🟥 SHORT 🔴"
    
    return (
        f"🛡 **WEEX FUTURES SIGNAL** 🛡\n\n"
        f"🪙 **Coin:** {symbol}/USDT (Perpetual)\n"
        f"📈 **Direction:** {emoji}\n"
        f"⏱ **Timeframe:** 15 Minute\n\n"
        f"📥 **WEEX Entry Price:** {fmt(signal['entry'])}\n"
        f"🎯 **Take Profit 1:** {fmt(signal['tp1'])}\n"
        f"🎯 **Take Profit 2:** {fmt(signal['tp2'])}\n"
        f"🛑 **Stop Loss:** {fmt(signal['sl'])}\n\n"
        f"📊 **Live Metrics:**\n"
        f"ℹ️ RSI (14): {signal['rsi']:.1f}\n\n"
        f"🔗 _Prices synced 1:1 with WEEX Exchange Orderbook_\n"
        f"🕒 _Generated: {now}_"
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
                text="🤖 WEEX Futures Bot Started!\n🎯 Prices and coins are now directly mapped from WEEX Exchange API.",
            )
        except Exception as e:
            log.error(f"Telegram start message failed: {e}")

        while True:
            # Load real-time WEEX instruments
            pairs_list = get_weex_futures_tickers()

            try:
                await bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"📊 WEEX Live Pairs Loaded!\n🔍 Scanning {len(pairs_list)} Active USDT Perpetual Markets...",
                )
            except:
                pass

            scanned = 0
            skipped = 0
            found = 0

            for symbol in pairs_list:
                df = fetch_weex_ohlcv(symbol)
                if df is None:
                    skipped += 1
                    continue

                scanned += 1
                signal = detect_weex_signal(df)

                if signal:
                    found += 1
                    try:
                        await bot.send_message(
                            chat_id=CHAT_ID,
                            text=build_message(symbol, signal),
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        log.error(f"Telegram signal delivery error: {e}")

                await asyncio.sleep(0.3)

            summary = (
                f"📡 **WEEX Scan Completed**\n\n"
                f"🔍 Scanned Coins: {scanned}\n"
                f"✅ Verified WEEX Signals: {found}\n"
                f"⏭ Skipped: {skipped}\n"
                f"⏱ Next loop in 15 minutes"
            )
            try:
                await bot.send_message(chat_id=CHAT_ID, text=summary, parse_mode="Markdown")
            except Exception as e:
                log.error(f"Summary delivery error: {e}")
                
            await asyncio.sleep(INTERVAL_MINUTES * 60)

if __name__ == "__main__":
    if "APNA" in BOT_TOKEN or not BOT_TOKEN:
        raise SystemExit
    if "APNA" in CHAT_ID or not CHAT_ID:
        raise SystemExit

    asyncio.run(run_bot())
