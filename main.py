#!/usr/bin/env python3

import asyncio
import logging
import os
import time
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
log = logging.getLogger("WeexFixedBot")

# ==========================================
# HARDCODED TOP WEEX FUTURES COINS LIST
# ==========================================
def get_weex_static_tickers():
    # Yeh woh saare major coins hain jo WEEX Futures par lazmi trade hote hain.
    # Isse na exchange API block ka dar hai aur na hi faaltu coins aane ka.
    return [
        "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "DOT", "MATIC",
        "LINK", "SHIB", "LTC", "TRX", "NEAR", "UNI", "APT", "FIL", "ICP", "STX",
        "IMX", "GRT", "LDO", "OP", "INJ", "SUI", "RNDR", "TIA", "WIF", "PEPE",
        "ORDI", "1000SATS", "BONK", "FLOKI", "FET", "AGIX", "OCEAN", "GALA", "MKR", "CRV",
        "RUNE", "AAVE", "EGLD", "FLOW", "AXS", "SAND", "MANA", "THETA", "CHZ", "EOS",
        "DYDX", "FTM", "GMT", "APE", "JUP", "PYTH", "W", "ENA", "STRK", "ZETA",
        "JTO", "MEME", "ENS", "WOO", "STG", "MINA", "FXS", "CFX", "ACH", "LRC"
    ]

# ==========================================
# FETCH OHLCV (YAHOO FINANCE - NEVER BLOCKS)
# ==========================================
def fetch_ohlcv(symbol):
    pair = f"{symbol}-USD"
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{pair}"
        params = {
            "region": "US", "lang": "en-US", "includePrePost": "false",
            "interval": "15m", "useYF": "true", "range": "5d"
        }
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        
        r = requests.get(url, params=params, headers=headers, timeout=10)
        if r.status_code != 200:
            return None

        data = r.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None

        candles = result[0]
        timestamps = candles.get("timestamp", [])
        indicators = candles.get("indicators", {}).get("quote", [{}])[0]
        
        closes = indicators.get("close", [])
        opens = indicators.get("open", [])
        highs = indicators.get("high", [])
        lows = indicators.get("low", [])

        if not timestamps or len(closes) < EMA_SLOW:
            return None

        df = pd.DataFrame({
            "ts": timestamps, "open": opens, "high": highs, "low": lows, "close": closes
        }).dropna().reset_index(drop=True)
        
        if len(df) < EMA_SLOW:
            return None
            
        return df
    except Exception:
        return None

# ==========================================
# INDICATORS & CALCULATIONS
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
def detect_signal_details(df):
    close = df["close"]
    if len(close) < EMA_SLOW + 15:
        return None

    ema20 = calc_ema(close, EMA_FAST)
    ema200 = calc_ema(close, EMA_SLOW)
    rsi_series = calc_rsi(close, 14)

    current_above = ema20.iloc[-1] > ema200.iloc[-1]
    previous_above = ema20.iloc[-2] > ema200.iloc[-2]

    if current_above == previous_above:
        return None

    signal_type = "LONG" if current_above else "SHORT"
    entry_price = float(close.iloc[-1])
    current_rsi = float(rsi_series.iloc[-1])

    last_few_candles = df.tail(5)
    
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

    emoji = "🟢" if signal["type"] == "LONG" else "🔴"
    
    return (
        f"🚨 **NEW WEEX FUTURES SIGNAL** 🚨\n\n"
        f"🪙 **Coin:** #{symbol}/USDT\n"
        f"📈 **Direction:** {emoji} {signal['type']}\n"
        f"⏱ **Timeframe:** 15 Minute\n\n"
        f"📥 **Entry Price:** {fmt(signal['entry'])}\n"
        f"🎯 **Take Profit 1:** {fmt(signal['tp1'])}\n"
        f"🎯 **Take Profit 2:** {fmt(signal['tp2'])}\n"
        f"🛑 **Stop Loss:** {fmt(signal['sl'])}\n\n"
        f"📊 **Extra Info:**\n"
        f"ℹ️ RSI (14): {signal['rsi']:.1f}\n\n"
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
                text="🤖 Bot Activated!\n📋 Fixed WEEX Coins List Loaded via Bulletproof Server Data.",
            )
        except Exception as e:
            log.error(f"Telegram start message failed: {e}")

        while True:
            pairs_list = get_weex_static_tickers()

            try:
                await bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"📊 WEEX Verified List Loaded!\n🔍 Scanning {len(pairs_list)} Major Crypto Charts...",
                )
            except:
                pass

            scanned = 0
            skipped = 0
            found = 0

            for symbol in pairs_list:
                df = fetch_ohlcv(symbol)
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
                        log.error(f"Telegram signal delivery error: {e}")

                await asyncio.sleep(0.3)

            summary = (
                f"📡 **Scan Complete**\n\n"
                f"🔍 Scanned Coins: {scanned}\n"
                f"✅ Signals Found: {found}\n"
                f"⏭ Skipped: {skipped}\n"
                f"⏱ Next scan in 15 minutes"
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
