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

BYBIT_BASE = "https://api.bytick.com"

# Railway bypass karne ke liye generic browser headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("EMABot")

# ==========================================
# GET LIVE BYBIT USDT PAIRS
# ==========================================
def get_bybit_pairs():
    try:
        r = requests.get(
            f"{BYBIT_BASE}/v5/market/instruments-info",
            params={"category": "linear", "limit": 1000},
            headers=HEADERS,
            timeout=20,
        )
        
        if r.status_code != 200:
            log.error(f"Bybit IP Blocked or Server Error. Status Code: {r.status_code}")
            return []

        data = r.json()

        if data.get("retCode") != 0:
            log.error(f"Bybit pair fetch failed: {data}")
            return []

        pairs = []
        for item in data.get("result", {}).get("list", []):
            symbol = item.get("symbol")
            if symbol and symbol.endswith("USDT"):
                pairs.append(symbol.replace("USDT", ""))

        log.info(f"Loaded {len(pairs)} Bybit pairs")
        return pairs

    except Exception as e:
        log.error(f"Pair fetch error: {e}")
        return []

PAIRS = get_bybit_pairs()

# ==========================================
# FETCH OHLCV
# ==========================================
def fetch_ohlcv(symbol):
    pair = f"{symbol}USDT"
    try:
        r = requests.get(
            f"{BYBIT_BASE}/v5/market/kline",
            params={
                "category": "linear",
                "symbol": pair,
                "interval": "15",
                "limit": str(CANDLE_LIMIT),
            },
            headers=HEADERS,
            timeout=20,
        )
        
        if r.status_code != 200:
            return None

        data = r.json()

        if data.get("retCode") != 0:
            return None

        raw = data.get("result", {}).get("list", [])
        if not raw or len(raw) < EMA_SLOW:
            return None

        raw.reverse() 

        df = pd.DataFrame(
            raw,
            columns=["ts", "open", "high", "low", "close", "volume", "turnover"]
        )

        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        return df

    except Exception as e:
        log.error(f"{pair} error: {e}")
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
    if not PAIRS:
        log.error("No Bybit pairs loaded. Exiting.")
        return

    request = HTTPXRequest(connection_pool_size=15)
    bot = Bot(token=BOT_TOKEN, request=request)

    async with bot:
        try:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=f"🤖 Bot Started\n📊 Scanning {len(PAIRS)} Bybit pairs every 15 minutes",
            )
        except Exception as e:
            log.error(f"Telegram start message failed: {e}")

        while True:
            scanned = 0
            skipped = 0
            found = 0

            for symbol in PAIRS[:300]:
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

                await asyncio.sleep(0.1)

            summary = (
                f"📡 Scan Complete\n\n"
                f"🔍 Scanned: {scanned}\n"
                f"✅ Signals Found: {found}\n"
                f"⏭ Skipped: {skipped}\n"
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
