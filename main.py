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
CANDLE_LIMIT = 250

# Data Fetching ke liye Binance use karenge kyunki yeh Railway ko block nahi karta
BINANCE_BASE = "https://api.binance.com"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("EMABot")

# ==========================================
# MANUAL COINS LIST
# ==========================================
MANUAL_PAIRS = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "DOT", "MATIC",
    "LINK", "UNI", "LTC", "ATOM", "TRX", "BCH", "NEAR", "FIL", "APT", "ARB",
    "OP", "INJ", "SUI", "TIA", "SEI", "ORDI", "SHIB", "GALA", "FTM", "RUNE", 
    "IMX", "GRT", "LDO", "STX", "ICP", "FET"
]

# ==========================================
# FETCH OHLCV (NOW USING BINANCE)
# ==========================================
def fetch_ohlcv(symbol):
    pair = f"{symbol}USDT"
    try:
        # Binance Kline API endpoint
        r = requests.get(
            f"{BINANCE_BASE}/api/v3/klines",
            params={
                "symbol": pair,
                "interval": "15m",
                "limit": str(CANDLE_LIMIT),
            },
            timeout=15,
        )
        
        if r.status_code != 200:
            log.error(f"Binance error for {pair}: Status {r.status_code}")
            return None

        raw = r.json()
        if not raw or len(raw) < EMA_SLOW:
            return None

        # Binance format ko DataFrame mein convert kar rahe hain
        df = pd.DataFrame(
            raw,
            columns=[
                "ts", "open", "high", "low", "close", "volume", 
                "close_time", "asset_volume", "trades", "taker_base", "taker_quote", "ignore"
            ]
        )

        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        return df

    except Exception as e:
        log.error(f"{pair} fetch error: {e}")
        return None

# ==========================================
# INDICATORS & SIGNAL DETECTION
# ==========================================
def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def detect_signal(df):
    close = df["close"]
    if len(close) < EMA_SLOW + 5:
        return None

    ema20 = calc_ema(close, EMA_FAST)
    ema200 = calc_ema(close, EMA_SLOW)

    current_above = ema20.iloc[-1] > ema200.iloc[-1]
    previous_above = ema20.iloc[-2] > ema200.iloc[-2]

    if current_above == previous_above:
        return None

    return "LONG" if current_above else "SHORT"

# ==========================================
# TELEGRAM MESSAGE
# ==========================================
def build_message(symbol, signal):
    now = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    return (
        f"🚨 SIGNAL DETECTED\n\n"
        f"🪙 Coin: {symbol}/USDT\n"
        f"📈 Type: {signal}\n"
        f"🕒 Time: {now}"
    )

# ==========================================
# MAIN BOT LOOP
# ==========================================
async def run_bot():
    request = HTTPXRequest(connection_pool_size=15)
    bot = Bot(token=BOT_TOKEN, request=request)

    async with bot:
        try:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=f"🤖 Bot Started Successfully!\n📊 Scanning {len(MANUAL_PAIRS)} Top Coins via Binance Data.",
            )
        except Exception as e:
            log.error(f"Telegram start message failed: {e}")

        while True:
            scanned = 0
            skipped = 0
            found = 0

            for symbol in MANUAL_PAIRS:
                df = fetch_ohlcv(symbol)
                if df is None:
                    skipped += 1
                    continue

                scanned += 1
                signal = detect_signal(df)

                if signal:
                    found += 1
                    try:
                        await bot.send_message(
                            chat_id=CHAT_ID,
                            text=build_message(symbol, signal),
                        )
                    except Exception as e:
                        log.error(f"Telegram signal delivery error: {e}")

                await asyncio.sleep(0.2)

            summary = (
                f"📡 Scan Complete\n\n"
                f"🔍 Scanned: {scanned} coins\n"
                f"✅ Signals Found: {found}\n"
                f"⏭ Skipped/Error: {skipped}\n"
                f"⏱ Next scan in 15 minutes"
            )
            try:
                await bot.send_message(chat_id=CHAT_ID, text=summary)
            except Exception as e:
                log.error(f"Summary delivery error: {e}")
                
            await asyncio.sleep(INTERVAL_MINUTES * 60)

if __name__ == "__main__":
    if "APNA" in BOT_TOKEN or not BOT_TOKEN:
        log.error("Set valid BOT_TOKEN first")
        raise SystemExit

    if "APNA" in CHAT_ID or not CHAT_ID:
        log.error("Set valid CHAT_ID first")
        raise SystemExit

    asyncio.run(run_bot())
