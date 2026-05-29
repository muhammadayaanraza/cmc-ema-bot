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

SCAN_INTERVAL_MIN = 15
FAST_PERIOD = 9
SLOW_PERIOD = 50

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CryptoCompareEngine")

# ==========================================================
# 1. FIXED TOP 80+ HIGH VOLUME TRADING COINS (STRICT NO DROP)
# ==========================================================
def load_market_tickers():
    return [
        "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", 
        "LINK", "DOT", "MATIC", "SHIB", "LTC", "TRX", "NEAR", "FIL",
        "BCH", "UNI", "ICP", "STX", "APT", "SUI", "OP", "ARB",
        "INJ", "TIA", "IMX", "ORDI", "WIF", "PEPE", "BONK", "FLOKI",
        "JUP", "PYTH", "DYM", "STRK", "PENDLE", "FET", "GALA", "FTM",
        "LDO", "MKR", "CRV", "AAVE", "COMP", "YFI", "RUNE", "EGLD",
        "THETA", "ENJ", "SAND", "MANA", "AXS", "CHZ", "ZIL", "ONE",
        "HOT", "ANKR", "GRT", "WAVES", "SNX", "NEO", "QTUM", "EOS",
        "IOTA", "XMR", "DASH", "ZEC", "ETC", "KAVA", "BAND", "RLC",
        "BLZ", "TRB", "STORJ", "MINA", "FLOW", "WOO", "ENS", "LRC",
        "PEOPLE", "WLD", "ARKM", "GMT"
    ]

# ==========================================================
# 2. ANTI-BLOCK DATA FETCHING (CRYPTOCOMPARE OPEN NODE)
# ==========================================================
def extract_candles(symbol):
    try:
        # Yeh endpoint Railway IPs ko bilkul block nahi karta
        url = "https://min-api.cryptocompare.com/data/v2/histominute"
        query_params = {
            "fsym": symbol.upper().strip(),
            "tsym": "USDT",
            "limit": "100",
            "aggregate": "15"  # 15 Minute timeframe candles
        }
        
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, params=query_params, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return None
            
        json_payload = response.json()
        if json_payload.get("Response") != "Success":
            return None
            
        raw_candles = json_payload.get("Data", {}).get("Data", [])
        if not raw_candles or len(raw_candles) < SLOW_PERIOD:
            return None
            
        candles_clean = []
        for c in raw_candles:
            candles_clean.append([
                c["time"], float(c["open"]), float(c["high"]), 
                float(c["low"]), float(c["close"]), float(c["volumeto"])
            ])
            
        dataset = pd.DataFrame(candles_clean, columns=["ts", "open", "high", "low", "close", "volume"])
        return dataset
    except Exception as e:
        logger.error(f"Error fetching {symbol}: {e}")
        return None

# ==========================================
# MATHEMATICAL INDICATORS
# ==========================================
def compute_ema(data_series, window):
    return data_series.ewm(span=window, adjust=False).mean()

def compute_rsi(data_series, window=14):
    change = data_series.diff()
    up_move = (change.where(change > 0, 0)).rolling(window=window).mean()
    down_move = (-change.where(change < 0, 0)).rolling(window=window).mean()
    relative_strength = up_move / (down_move + 1e-9)
    return 100 - (100 / (1 + relative_strength))

# ==========================================
# SIGNAL SYSTEM
# ==========================================
def analyze_market_trends(df):
    close_prices = df["close"]
    
    fast_ema = compute_ema(close_prices, FAST_PERIOD)
    slow_ema = compute_ema(close_prices, SLOW_PERIOD)
    rsi_vals = compute_rsi(close_prices, 14)

    is_bullish = fast_ema.iloc[-1] > slow_ema.iloc[-1]
    was_bullish = fast_ema.iloc[-2] > slow_ema.iloc[-2]

    if is_bullish == was_bullish:
        return None

    trade_type = "LONG" if is_bullish else "SHORT"
    entry_val = float(close_prices.iloc[-1])
    rsi_val = float(rsi_vals.iloc[-1])

    if trade_type == "LONG":
        if not (50.0 <= rsi_val <= 70.0):
            return None
    else:
        if not (30.0 <= rsi_val <= 50.0):
            return None

    recent_history = df.tail(4)
    if trade_type == "LONG":
        sl_val = float(recent_history["low"].min()) * 0.996
        risk_amount = entry_val - sl_val
        if risk_amount <= 0: risk_amount = entry_val * 0.008
        tp1_val = entry_val + (risk_amount * 1.3)
        tp2_val = entry_val + (risk_amount * 2.3)
    else:
        sl_val = float(recent_history["high"].max()) * 1.004
        risk_amount = sl_val - entry_val
        if risk_amount <= 0: risk_amount = entry_val * 0.008
        tp1_val = entry_val - (risk_amount * 1.3)
        tp2_val = entry_val - (risk_amount * 2.3)

    return {
        "direction": trade_type, "entry": entry_val, "sl": sl_val,
        "tp1": tp1_val, "tp2": tp2_val, "rsi": rsi_val
    }

# ==========================================
# MESSAGE GENERATOR
# ==========================================
def format_alert_message(symbol, signal_data):
    gmt_now = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    
    def price_format(n):
        if n >= 100: return f"{n:.2f}"
        if n >= 1: return f"{n:.4f}"
        return f"{n:.6f}"

    arrow = "🟢" if signal_data["direction"] == "LONG" else "🔴"
    
    return (
        f"🚨 **CONFIRMED FUTURES SIGNAL (9/50 EMA)** 🚨\n\n"
        f"🪙 **Coin:** #{symbol.upper()}/USDT\n"
        f"📈 **Direction:** {arrow} {signal_data['direction']}\n"
        f"⏱ **Timeframe:** 15 Minute\n\n"
        f"📥 **Entry Price:** {price_format(signal_data['entry'])}\n"
        f"🎯 **Take Profit 1:** {price_format(signal_data['tp1'])}\n"
        f"🎯 **Take Profit 2:** {price_format(signal_data['tp2'])}\n"
        f"🛑 **Stop Loss:** {price_format(signal_data['sl'])}\n\n"
        f"📊 **Filters:**\n"
        f"✅ RSI (14) Confirmed: {signal_data['rsi']:.1f}\n\n"
        f"🕒 _Generated at: {gmt_now}_"
    )

# ==========================================
# MAIN LIFECYCLE LOOP
# ==========================================
async def core_execution():
    network_request = HTTPXRequest(connection_pool_size=30)
    telegram_bot = Bot(token=BOT_TOKEN, request=network_request)

    async with telegram_bot:
        try:
            await telegram_bot.send_message(
                chat_id=CHAT_ID,
                text="🤖 WEEX Anti-Block Engine V8 Live!\n⚡ Shifting data source to Open-Node Architecture.",
            )
        except Exception as e:
            logger.error(f"Startup notification failed: {e}")

        while True:
            target_markets = load_market_tickers()

            try:
                await telegram_bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"🔄 Cloud Nodes Synchronized!\n🔍 Scanning exactly {len(target_markets)} High-Volume Coins...",
                )
            except:
                pass

            scanned_count = 0
            skipped_count = 0
            signals_found = 0

            for coin_symbol in target_markets:
                dataframe = extract_candles(coin_symbol)
                if dataframe is None:
                    skipped_count += 1
                    continue

                scanned_count += 1
                active_signal = analyze_market_trends(dataframe)

                if active_signal:
                    signals_found += 1
                    try:
                        await telegram_bot.send_message(
                            chat_id=CHAT_ID,
                            text=format_alert_message(coin_symbol, active_signal),
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        logger.error(f"Telegram alert error: {e}")

                # Safe request spacing
                await asyncio.sleep(0.1)

            final_report = (
                f"📡 **Scan Complete Successfully**\n\n"
                f"🔍 Total Scanned: {scanned_count} Coins\n"
                f"✅ Safe Signals Found: {signals_found}\n"
                f"⏭ Skipped due to API load: {skipped_count}\n"
                f"⏱ Next loop in 15 minutes"
            )
            try:
                await telegram_bot.send_message(chat_id=CHAT_ID, text=final_report, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Report dispatch error: {e}")
                
            await asyncio.sleep(SCAN_INTERVAL_MIN * 60)

if __name__ == "__main__":
    if "APNA" in BOT_TOKEN or not BOT_TOKEN:
        raise SystemExit
    if "APNA" in CHAT_ID or not CHAT_ID:
        raise SystemExit

    asyncio.run(core_execution())
