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

BYBIT_BASE = "https://api.bybit.com"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("EMABot")


# ======================
# GET PAIRS (FIXED)
# ======================
def get_bybit_pairs():
    try:
        r = requests.get(
            f"{BYBIT_BASE}/v5/market/instruments-info",
            params={"category": "linear"},
            timeout=20,
        )

        data = r.json()

        if data.get("retCode") != 0:
            print("Bybit error:", data)
            return []

        pairs = []

        for item in data.get("result", {}).get("list", []):
            symbol = item.get("symbol")
            if symbol and symbol.endswith("USDT"):
                pairs.append(symbol.replace("USDT", ""))

        print(f"Loaded pairs: {len(pairs)}")
        print("Sample:", pairs[:10])

        return pairs

    except Exception as e:
        print("Pair fetch error:", e)
        return []


PAIRS = get_bybit_pairs()


# ======================
# FETCH CANDLES (FIXED)
# ======================
def fetch_ohlcv(symbol):
    pair = f"{symbol}USDT"

    try:
        r = requests.get(
            f"{BYBIT_BASE}/v5/market/kline",
            params={
                "category": "linear",
                "symbol": pair,
                "interval": "15",
                "limit": CANDLE_LIMIT,
            },
            timeout=20,
        )

        data = r.json()

        if data.get("retCode") != 0:
            return None

        raw = data.get("result", {}).get("list", [])

        if not raw or len(raw) < EMA_SLOW:
            return None

        raw.reverse()

        df = pd.DataFrame(
            raw,
            columns=["ts", "open", "high", "low", "close", "volume", "turnover"],
        )

        df["close"] = df["close"].astype(float)

        return df

    except Exception as e:
        print(f"{pair} fetch error:", e)
        return None


# ======================
# EMA SIGNAL
# ======================
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def detect_signal(df):
    close = df["close"]

    ema_fast = ema(close, EMA_FAST)
    ema_slow = ema(close, EMA_SLOW)

    if len(df) < EMA_SLOW + 5:
        return None

    current = ema_fast.iloc[-1] > ema_slow.iloc[-1]
    previous = ema_fast.iloc[-2] > ema_slow.iloc[-2]

    if current == previous:
        return None

    return "LONG" if current else "SHORT"


# ======================
# MESSAGE
# ======================
def build_message(symbol, signal):
    now = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")

    return (
        f"🚨 SIGNAL DETECTED\n\n"
        f"🪙 Coin: {symbol}/USDT\n"
        f"📈 Type: {signal}\n"
        f"🕒 Time: {now}"
    )


# ======================
# BOT LOOP
# ======================
async def run_bot():

    if not PAIRS:
        print("❌ No pairs loaded. API issue.")
        return

    request = HTTPXRequest(connection_pool_size=20)
    bot = Bot(token=BOT_TOKEN, request=request)

    await bot.send_message(
        chat_id=CHAT_ID,
        text=f"🤖 Bot Started\n📊 Monitoring {len(PAIRS)} pairs",
    )

    while True:

        scanned = 0
        skipped = 0
        found = 0

        for symbol in PAIRS[:200]:

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
                    print("Telegram error:", e)

            await asyncio.sleep(0.05)

        print(f"Scanned={scanned} Found={found} Skipped={skipped}")

        await bot.send_message(
            chat_id=CHAT_ID,
            text=(
                f"📡 Scan Complete\n\n"
                f"🔍 Scanned: {scanned}\n"
                f"⏭ Skipped: {skipped}\n"
                f"✅ Signals: {found}\n"
                f"⏱ Next scan in {INTERVAL_MINUTES} min"
            ),
        )

        await asyncio.sleep(INTERVAL_MINUTES * 60)


# ======================
# START
# ======================
if __name__ == "__main__":

    if "APNA" in BOT_TOKEN:
        print("❌ BOT_TOKEN missing")
        raise SystemExit

    if "APNA" in CHAT_ID:
        print("❌ CHAT_ID missing")
        raise SystemExit

    asyncio.run(run_bot())
log = logging.getLogger("EMABot")


# ==========================================
# GET LIVE BYBIT USDT PAIRS
# ==========================================
def get_bybit_pairs():
    try:
        r = requests.get(
            f"{BYBIT_BASE}/v5/market/instruments-info",
            params={"category": "linear", "limit": 1000},
            timeout=20,
        )

        data = r.json()

        if data.get("retCode") != 0:
            print("Bybit pair fetch failed:", data)
            return []

        pairs = []

        for item in data["result"]["list"]:
            symbol = item["symbol"]

            if symbol.endswith("USDT"):
                pairs.append(symbol.replace("USDT", ""))

        print(f"Loaded {len(pairs)} Bybit pairs")
        return pairs

    except Exception as e:
        print("Pair fetch error:", e)
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
                "limit": CANDLE_LIMIT,
            },
            timeout=20,
        )

        data = r.json()

        if data.get("retCode") != 0:
            return None

        raw = data["result"]["list"]

        if not raw or len(raw) < EMA_SLOW:
            return None

        raw.reverse()

        df = pd.DataFrame(
            raw,
            columns=[
                "ts",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "turnover",
            ],
        )

        for col in ["open", "high", "low", "close"]:
            df[col] = df[col].astype(float)

        return df

    except Exception as e:
        print(f"{pair} error:", e)
        return None


# ==========================================
# INDICATORS
# ==========================================
def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def detect_signal(df):
    close = df["close"]

    ema20 = calc_ema(close, EMA_FAST)
    ema200 = calc_ema(close, EMA_SLOW)

    current = ema20.iloc[-1] > ema200.iloc[-1]
    previous = ema20.iloc[-2] > ema200.iloc[-2]

    if current == previous:
        return None

    if current:
        return "LONG"

    return "SHORT"


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
# MAIN BOT
# ==========================================
async def run_bot():

    if not PAIRS:
        print("No Bybit pairs loaded.")
        return

    request = HTTPXRequest(connection_pool_size=10)
    bot = Bot(token=BOT_TOKEN, request=request)

    await bot.send_message(
        chat_id=CHAT_ID,
        text=f"🤖 Bot Started\n📊 Scanning {len(PAIRS)} Bybit pairs every 15 minutes",
    )

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
                    print("Telegram error:", e)

            await asyncio.sleep(0.1)

        summary = (
            f"📡 Scan Complete\n\n"
            f"🔍 Scanned: {scanned}\n"
            f"✅ Signals: {found}\n"
            f"⏭ Skipped: {skipped}\n"
            f"⏱ Next scan in 15 minutes"
        )

        await bot.send_message(chat_id=CHAT_ID, text=summary)

        await asyncio.sleep(INTERVAL_MINUTES * 60)


if __name__ == "__main__":

    if "APNA" in BOT_TOKEN:
        print("Set BOT_TOKEN first")
        raise SystemExit

    if "APNA" in CHAT_ID:
        print("Set CHAT_ID first")
        raise SystemExit

    asyncio.run(run_bot())
