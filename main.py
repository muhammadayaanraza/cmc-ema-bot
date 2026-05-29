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
logger = logging.getLogger("EngineV6_Fixed")

# ==========================================================
# 1. MARKET TICKERS FETCH (FORCE UPPERCASE)
# ==========================================================
def load_market_tickers():
    hardcoded_pairs = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", 
        "LINKUSDT", "DOTUSDT", "MATICUSDT", "SHIBUSDT", "LTCUSDT", "TRXUSDT", "NEARUSDT", "FILUSDT",
        "BCHUSDT", "UNIUSDT", "ICPUSDT", "STXUSDT", "APTUSDT", "SUIUSDT", "OPUSDT", "ARBUSDT",
        "INJUSDT", "TIAUSDT", "IMXUSDT", "ORDIUSDT", "WIFUSDT", "PEPEUSDT", "BONKUSDT", "FLOKIUSDT",
        "JUPUSDT", "PYTHUSDT", "DYMUSDT", "STRKUSDT", "PENDLEUSDT", "FETUSDT", "GALAUSDT", "FTMUSDT"
    ]
    
    try:
        logger.info("Connecting to live ticker endpoint...")
        api_url = "https://fapi.binance.com/fapi/v1/ticker/price"
        res = requests.get(api_url, timeout=10)
        
        if res.status_code == 200:
            raw_data = res.json()
            fresh_list = []
            for item in raw_data:
                symbol_name = item.get("symbol", "")
                if symbol_name:
                    symbol_name = symbol_name.upper().strip() # Force Strict Uppercase
                    if symbol_name.endswith("USDT"):
                        if not any(bad in symbol_name for bad in ["USDC", "BUSD", "EUR"]):
                            fresh_list.append(symbol_name)
            
            if len(fresh_list) > 10:
                logger.info(f"Successfully loaded {len(fresh_list)} real uppercase coins.")
                return list(dict.fromkeys(fresh_list))
                
        return hardcoded_pairs
    except Exception as e:
        logger.error(f"Fallback active: {e}")
        return hardcoded_pairs

# ==========================================================
# 2. BULLETPROOF CANDLESTICK FETCH (STRICT UPPERCASE)
# ==========================================================
def extract_candles(symbol_ticker):
    try:
        # Ticker ko bilkul capitalize karke bhej rahe hain taaki Binance reject na kare
        clean_symbol = str(symbol_ticker).upper().strip()
        
        endpoint = "https://fapi.binance.com/fapi/v1/klines"
        query_params = {"symbol": clean_symbol, "interval": "15m", "limit": "100"}
        
        response = requests.get(endpoint, params=query_params, timeout=8)
        if response.status_code != 200:
            logger.warning(f"Binance rejected symbol {clean_symbol} with status {response.status_code}")
            return None
            
        json_payload = response.json()
        if not json_payload or len(json_payload) < SLOW_PERIOD:
            return None
            
        # Sirf pehle 6 columns target kar rahe hain jo technical analysis ke liye chahiye
        candles_clean = []
        for c in json_payload:
            candles_clean.append([c[0], c[1], c[2], c[3], c[4], c[5]])
            
        dataset = pd.DataFrame(candles_clean, columns=["ts", "open", "high", "low", "close", "volume"])
        
        dataset["open"] = dataset["open"].astype(float)
        dataset["high"] = dataset["high"].astype(float)
        dataset["low"] = dataset["low"].astype(float)
        dataset["close"] = dataset["close"].astype(float)
        
        return dataset
    except Exception as e:
        logger.error(f"Error fetching candles for {symbol_ticker}: {e}")
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

    # RSI Strict Filter
    if trade_type == "LONG":
        if not (50.0 <= rsi_val <= 70.0):
            return None
    else:
        if not (30.0 <= rsi_val <= 50.0):
            return None

    # Risk Control
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
    clean_name = symbol.replace("USDT", "")
    
    def price_format(n):
        if n >= 100: return f"{n:.2f}"
        if n >= 1: return f"{n:.4f}"
        return f"{n:.6f}"

    arrow = "🟢" if signal_data["direction"] == "LONG" else "🔴"
    
    return (
        f"🚨 **CONFIRMED FUTURES SIGNAL (9/50 EMA)** 🚨\n\n"
        f"🪙 **Coin:** #{clean_name}/USDT\n"
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
                text="🤖 WEEX Native Core Engine V6 Online!\n⚡ Strict formatting active. Scanning live matrix.",
            )
        except Exception as e:
            logger.error(f"Startup notification failed: {e}")

        while True:
            target_markets = load_market_tickers()

            try:
                await telegram_bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"🔄 Live Market Synchronized!\n🔍 Scanning {len(target_markets)} High-Volume Coins...",
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

                await asyncio.sleep(0.05)

            final_report = (
                f"📡 **Scan Complete Successfully**\n\n"
                f"🔍 Total Scanned: {scanned_count} Coins\n"
                f"✅ Safe Signals Found: {signals_found}\n"
                f"⏭ Skipped: {skipped_count}\n"
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
