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

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("EMABot")

# ==========================================
# AUTOMATIC TOP 500 COINS FETCH
# ==========================================
def get_top_500_tickers():
    try:
        log.info("Fetching Top 500 Cryptos from Coingecko...")
        # CryptoCompare ya CoinGecko ki public API se top 500 coins uthana
        url = "https://min-api.cryptocompare.com/data/top/mktcapfull"
        
        tickers = []
        # 100-100 karke batches mein top 500 tak list banana (Aapki requirement ke mutabik)
        for page in range(0, 5):
            params = {"limit": "100", "tsym": "USD", "page": str(page)}
            r = requests.get(url, params=params, timeout=15)
            if r.status_code == 200:
                data = r.json()
                for coin in data.get("Data", []):
                    info = coin.get("CoinInfo", {})
                    name = info.get("Name")
                    # Stable coins aur fiat ko skip karna taaki galat signals na aayein
                    if name and name not in ["USDT", "USDC", "FDUSD", "DAI", "EUR", "GBP"]:
                        tickers.append(name)
            await asyncio.sleep(0.1)
            
        # Agar API fail ho toh backup list kaam karegi
        if not tickers:
            return ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "DOT", "MATIC"]
            
        # Duplicate remove karna aur unique top 500 return karna
        return list(dict.fromkeys(tickers))[:500]
    except Exception as e:
        log.error(f"Error fetching top 500 list: {e}")
        return ["BTC", "ETH", "SOL", "BNB", "XRP"]

# ==========================================
# FETCH OHLCV (USING YAHOO FINANCE)
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
    request = HTTPXRequest(connection_pool_size=30)
    bot = Bot(token=BOT_TOKEN, request=request)

    async with bot:
        try:
            await bot.send_message(
                chat_id=CHAT_ID,
                text="🤖 Bot Starting up...\n🔄 Loading Top 500 Crypto Coins List dynamically...",
            )
        except Exception as e:
            log.error(f"Telegram start message failed: {e}")

        while True:
            # Har scan se pehle market cap ke mutabik top 500 naye list refresh hogi
            try:
                url = "https://min-api.cryptocompare.com/data/top/mktcapfull"
                pairs_list = []
                for page in range(0, 5):
                    r = requests.get(url, params={"limit": "100", "tsym": "USD", "page": str(page)}, timeout=15)
                    if r.status_code == 200:
                        for coin in r.json().get("Data", []):
                            name = coin.get("CoinInfo", {}).get("Name")
                            if name and name not in ["USDT", "USDC", "FDUSD", "DAI", "EUR", "BUSD"]:
                                pairs_list.append(name)
                    await asyncio.sleep(0.1)
                pairs_list = list(dict.fromkeys(pairs_list))[:500]
            except:
                pairs_list = ["BTC", "ETH", "SOL"]

            try:
                await bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"📊 Dynamic List Loaded!\n🔍 Scanning current Top {len(pairs_list)} Coins in the market.",
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

                # Rate limiting se bachne ke liye thoda delay (Maha-Zaroori hai 500 coins ke liye)
                await asyncio.sleep(0.3)

            summary = (
                f"📡 Scan Complete (Top 500 Cycle)\n\n"
                f"🔍 Successfully Scanned: {scanned} coins\n"
                f"✅ Signals Found: {found}\n"
                f"⏭ Skipped/No Data: {skipped}\n"
                f"⏱ Next scan in 15 minutes"
            )
            try:
                await bot.send_message(chat_id=CHAT_ID, text=summary)
            except Exception as e:
                log.error(f"Summary delivery error: {e}")
                
            await asyncio.sleep(INTERVAL_MINUTES * 60)

if __name__ == "__main__":
    if "APNA" in BOT_TOKEN or not BOT_TOKEN:
        raise SystemExit
    if "APNA" in CHAT_ID or not CHAT_ID:
        raise SystemExit

    asyncio.run(run_bot())
