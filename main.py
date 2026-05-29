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
CANDLE_LIMIT = 250

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("HighConfBot")

# ==========================================
# AUTOMATIC TOP 300 COINS FETCH
# ==========================================
def get_top_300_tickers():
    try:
        log.info("Fetching Top 300 Cryptos from CryptoCompare...")
        url = "https://min-api.cryptocompare.com/data/top/mktcapfull"
        
        tickers = []
        for page in range(0, 3):
            params = {"limit": "100", "tsym": "USD", "page": str(page)}
            r = requests.get(url, params=params, timeout=15)
            if r.status_code == 200:
                data = r.json()
                for coin in data.get("Data", []):
                    info = coin.get("CoinInfo", {})
                    name = info.get("Name")
                    if name and name not in ["USDT", "USDC", "FDUSD", "DAI", "EUR", "GBP", "BUSD"]:
                        tickers.append(name)
            time.sleep(0.1)
            
        if not tickers:
            return ["BTC", "ETH", "SOL", "BNB", "XRP"]
            
        return list(dict.fromkeys(tickers))[:300]
    except Exception as e:
        log.error(f"Error fetching top 300 list: {e}")
        return ["BTC", "ETH", "SOL"]

# ==========================================
# FETCH OHLCV WITH VOLUME DATA
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
        volumes = indicators.get("volume", [])

        if not timestamps or len(closes) < EMA_SLOW:
            return None

        df = pd.DataFrame({
            "ts": timestamps, "open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes
        }).dropna().reset_index(drop=True)
        
        if len(df) < EMA_SLOW:
            return None
            
        return df
    except Exception:
        return None

# ==========================================
# TECHNICAL INDICATORS CALCULATIONS
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
# HIGH CONFIDENCE SIGNAL DETECTION WITH FILTERS
# ==========================================
def detect_high_confidence_signal(df):
    close = df["close"]
    volume = df["volume"]
    
    if len(close) < EMA_SLOW + 15:
        return None

    # Indicators calculate karna
    ema20 = calc_ema(close, EMA_FAST)
    ema200 = calc_ema(close, EMA_SLOW)
    rsi = calc_rsi(close, 14)

    current_above = ema20.iloc[-1] > ema200.iloc[-1]
    previous_above = ema20.iloc[-2] > ema200.iloc[-2]

    # Rule 1: Crossover hona zaroori hai
    if current_above == previous_above:
        return None

    # Rule 2: HIGH VOLUME FILTER (Current volume pichle 20 candles ke average volume se kam se kam 1.5x zyada ho)
    avg_volume = volume.iloc[-21:-1].mean()
    if volume.iloc[-1] < (avg_volume * 1.5):
        return None # Volume low hai toh skip

    # Rule 3: EMA GAP FILTER (Fakeout se bachne ke liye dono lines mein kam se kam 0.25% ka gap ho)
    price_gap_pct = abs(ema20.iloc[-1] - ema200.iloc[-1]) / ema200.iloc[-1] * 100
    if price_gap_pct < 0.25:
        return None # Gap kam hai toh skip

    signal_type = "LONG" if current_above else "SHORT"
    current_rsi = rsi.iloc[-1]

    # Rule 4: RSI MOMENTUM FILTER
    if signal_type == "LONG" and (current_rsi < 50 or current_rsi > 70):
        return None # RSI perfect zone mein nahi hai
    if signal_type == "SHORT" and (current_rsi > 50 or current_rsi < 30):
        return None

    # Agar saari conditions pass ho jayein, tabhi trade generate hogi
    entry_price = float(close.iloc[-1])
    last_few_candles = df.tail(5)
    
    if signal_type == "LONG":
        stop_loss = float(last_few_candles["low"].min()) * 0.996
        risk = entry_price - stop_loss
        if risk <= 0: risk = entry_price * 0.01
        take_profit1 = entry_price + (risk * 1.5)
        take_profit2 = entry_price + (risk * 2.5)
    else:
        stop_loss = float(last_few_candles["high"].max()) * 1.004
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
        "rsi": current_rsi,
        "gap": price_gap_pct
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

    emoji = "🔥 LONG (Strong Bullish Breakout) 🟢" if signal["type"] == "LONG" else "💥 SHORT (Strong Bearish Breakdown) 🔴"
    
    return (
        f"🌟 **HIGH CONFIDENCE SIGNAL** 🌟\n\n"
        f"🪙 **Coin:** #{symbol}/USDT\n"
        f"📈 **Setup:** {emoji}\n"
        f"⏱ **Timeframe:** 15 Minute\n\n"
        f"📥 **Entry Price:** {fmt(signal['entry'])}\n"
        f"🎯 **Take Profit 1:** {fmt(signal['tp1'])}\n"
        f"🎯 **Take Profit 2:** {fmt(signal['tp2'])}\n"
        f"🛑 **Stop Loss:** {fmt(signal['sl'])}\n\n"
        f"📊 **Metrics for Confidence:**\n"
        f"🔹 RSI: {signal['rsi']:.1f}\n"
        f"🔹 EMA Separation Gap: {signal['gap']:.2f}%\n"
        f"⚡ _Volume Spike: Confirmed (High)_ \n\n"
        f"🕒 _Time: {now}_"
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
                text="🤖 High-Confidence Bot Online!\n🔍 Filtering Top 300 Coins for High Volume & RSI Confirmation...",
            )
        except Exception as e:
            log.error(f"Telegram start message failed: {e}")

        while True:
            pairs_list = get_top_300_tickers()

            try:
                await bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"📊 Top 300 List Loaded!\n⚡ Scanning for High Volume + RSI Breakouts.",
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
                signal = detect_high_confidence_signal(df)

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
                f"📡 **Filter Scan Complete**\n\n"
                f"🔍 Total Analyzed: {scanned} coins\n"
                f"🔥 High-Conf Signals: {found}\n"
                f"⏭ Filtered Out/No Data: {skipped}\n"
                f"⏱ Next premium scan in 15 minutes"
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
