#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║   Binance EMA 20/200 Crossover — Telegram Signal Bot                ║
║   Data: Binance public API (free, no key needed)                    ║
║   Signals: Telegram pe har 15 minute baad                           ║
╚══════════════════════════════════════════════════════════════════════╝

SETUP:
  1. pip install python-telegram-bot requests pandas numpy
  2. BOT_TOKEN aur CHAT_ID fill karein
  3. python cmc_ema_bot_fixed.py
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
    import pandas as pd
    import numpy as np
    from telegram import Bot
    from telegram.constants import ParseMode
    from telegram.error import TelegramError
    from telegram.request import HTTPXRequest
except ImportError as e:
    print(f"\n❌ Missing library: {e}")
    print("   Run: pip install python-telegram-bot requests pandas numpy httpx\n")
    raise SystemExit(1)

# ═════════════════════════════════════════════════════════════════════
#  ✏️  CONFIGURATION
# ═════════════════════════════════════════════════════════════════════

BOT_TOKEN = os.getenv("BOT_TOKEN", "APNA_BOT_TOKEN_YAHAN")
CHAT_ID   = os.getenv("CHAT_ID",   "APNA_CHAT_ID_YAHAN")

INTERVAL_MINUTES = 15
EMA_FAST         = 20
EMA_SLOW         = 200
ATR_PERIOD       = 14
CANDLE_INTERVAL  = "15m"
CANDLE_LIMIT     = 250

# ═════════════════════════════════════════════════════════════════════
#  Binance ke top popular USDT pairs — 100 coins
# ═════════════════════════════════════════════════════════════════════

BINANCE_PAIRS = [
    # Major
    "BTC","ETH","BNB","XRP","SOL","ADA","DOGE","TRX","LTC","BCH",
    # DeFi / Layer1
    "AVAX","DOT","LINK","UNI","ATOM","NEAR","APT","SUI","SEI","INJ",
    "FET","GRT","AAVE","MKR","COMP","SNX","CRV","BAL","YFI","SUSHI",
    # Layer 2
    "MATIC","ARB","OP","IMX","STRK","MANTA","ZK","BLUR",
    # Meme
    "SHIB","PEPE","FLOKI","BONK","WIF","BOME","DOGS","NEIRO",
    # Gaming / Metaverse
    "AXS","SAND","MANA","ENJ","GALA","ILV","ALICE","SUPER",
    # Infrastructure
    "FIL","AR","STORJ","ANKR","ONE","ZIL","CELR","SKL",
    # Exchange tokens
    "OKB","KCS","HT","CRO","GT","MX",
    # Others top coins
    "TON","HBAR","VET","EOS","XLM","ALGO","FLOW","THETA",
    "KAVA","ROSE","CELO","ZEC","DASH","XMR","ETC","NEO",
    "IOTA","BAT","CHZ","HOT","REN","BAND","ONT","QTUM",
    "WAVES","ICX","ZRX","OXT","NMR","OCEAN","RLC","GNO",
]

BINANCE_BASE = "https://api.binance.com/api/v3"
LOG_FILE     = "ema_bot.log"
STATE_FILE   = "bot_state.json"

# ═════════════════════════════════════════════════════════════════════
#  LOGGING
# ═════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("EMABot")

# ═════════════════════════════════════════════════════════════════════
#  BINANCE OHLCV
# ═════════════════════════════════════════════════════════════════════

def fetch_ohlcv(symbol: str) -> pd.DataFrame | None:
    pair = f"{symbol}USDT"
    try:
        r = requests.get(
            f"{BINANCE_BASE}/klines",
            params={"symbol": pair, "interval": CANDLE_INTERVAL, "limit": CANDLE_LIMIT},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        raw = r.json()
        if not raw or len(raw) < EMA_SLOW + 10:
            return None
        df = pd.DataFrame(raw, columns=[
            "ts","open","high","low","close","vol",
            "cts","qvol","trades","tbvol","tqvol","_"
        ])
        for col in ["open","high","low","close","vol"]:
            df[col] = df[col].astype(float)
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        return df[["ts","open","high","low","close","vol"]].reset_index(drop=True)
    except Exception as e:
        log.debug(f"[{symbol}] fetch error: {e}")
        return None

# ═════════════════════════════════════════════════════════════════════
#  INDICATORS
# ═════════════════════════════════════════════════════════════════════

def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def calc_atr(df: pd.DataFrame) -> float:
    pc = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - pc).abs(),
        (df["low"]  - pc).abs(),
    ], axis=1).max(axis=1)
    return float(tr.ewm(span=ATR_PERIOD, adjust=False).mean().iloc[-1])

def calc_rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(span=period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(span=period, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = 100 - 100 / (1 + rs.iloc[-1])
    return round(float(rsi), 1)

def calc_strength(e20, e200, closes: pd.Series) -> float:
    gap = abs(e20 - e200) / e200 * 100
    mom = abs((closes.iloc[-1] - closes.iloc[-6]) / closes.iloc[-6] * 100)
    return round(min(99.1, 74 + gap * 12 + mom * 1.8), 1)

# ═════════════════════════════════════════════════════════════════════
#  SIGNAL DETECTION
# ═════════════════════════════════════════════════════════════════════

def detect_signal(df: pd.DataFrame) -> dict | None:
    closes = df["close"]
    e20  = calc_ema(closes, EMA_FAST)
    e200 = calc_ema(closes, EMA_SLOW)
    n, p = len(df) - 1, len(df) - 2

    curr_above = e20.iloc[n] > e200.iloc[n]
    prev_above = e20.iloc[p] > e200.iloc[p]

    if curr_above == prev_above:
        return None

    price    = float(closes.iloc[n])
    atr_val  = calc_atr(df)
    rsi_val  = calc_rsi(closes)
    strength = calc_strength(float(e20.iloc[n]), float(e200.iloc[n]), closes)

    if curr_above:
        return {
            "type": "LONG",
            "entry": price,
            "sl"  : price - atr_val * 1.5,
            "tp1" : price + atr_val * 2.0,
            "tp2" : price + atr_val * 4.0,
            "tp3" : price + atr_val * 6.0,
            "ema20": float(e20.iloc[n]),
            "ema200": float(e200.iloc[n]),
            "atr": atr_val, "rsi": rsi_val, "strength": strength,
            "candle_time": str(df["ts"].iloc[n]),
        }
    else:
        return {
            "type": "SHORT",
            "entry": price,
            "sl"  : price + atr_val * 1.5,
            "tp1" : price - atr_val * 2.0,
            "tp2" : price - atr_val * 4.0,
            "tp3" : price - atr_val * 6.0,
            "ema20": float(e20.iloc[n]),
            "ema200": float(e200.iloc[n]),
            "atr": atr_val, "rsi": rsi_val, "strength": strength,
            "candle_time": str(df["ts"].iloc[n]),
        }

# ═════════════════════════════════════════════════════════════════════
#  FORMATTER
# ═════════════════════════════════════════════════════════════════════

def fp(v: float) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)): return "N/A"
    if   abs(v) < 0.000001: return f"{v:.10f}"
    elif abs(v) < 0.0001  : return f"{v:.8f}"
    elif abs(v) < 0.01    : return f"{v:.6f}"
    elif abs(v) < 1       : return f"{v:.5f}"
    elif abs(v) < 100     : return f"{v:.3f}"
    else                  : return f"{v:,.2f}"

# ═════════════════════════════════════════════════════════════════════
#  TELEGRAM MESSAGES
# ═════════════════════════════════════════════════════════════════════

def build_signal_msg(symbol: str, sig: dict) -> str:
    now     = datetime.now(timezone.utc).strftime("%d %b %Y  %H:%M UTC")
    is_long = sig["type"] == "LONG"
    emoji   = "🟢" if is_long else "🔴"
    direct  = "📈 *LONG  — BUY*"  if is_long else "📉 *SHORT — SELL*"
    cross   = "EMA20 crossed ABOVE EMA200 *(Bullish)*" if is_long else "EMA20 crossed BELOW EMA200 *(Bearish)*"
    rsi     = sig.get("rsi", 50)
    rsi_lbl = f"{rsi} ⚠️ Overbought" if rsi > 70 else (f"{rsi} ⚠️ Oversold" if rsi < 30 else f"{rsi} ✅ Neutral")
    pct     = sig["strength"]
    bar     = "█" * round(pct / 10) + "░" * (10 - round(pct / 10))

    return (
        f"{emoji} *BINANCE — {symbol}/USDT*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{direct}\n"
        f"🔀 {cross}\n"
        f"🕐 *Time     :* `{now}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 *Entry    :* `$ {fp(sig['entry'])}`\n"
        f"🛑 *Stop Loss:* `$ {fp(sig['sl'])}`\n"
        f"🎯 *TP 1     :* `$ {fp(sig['tp1'])}`\n"
        f"🎯 *TP 2     :* `$ {fp(sig['tp2'])}`\n"
        f"🎯 *TP 3     :* `$ {fp(sig['tp3'])}`\n"
        f"⚖️ *R:R Ratio:* `1 : 2 / 4 / 6`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📶 *EMA 20   :* `$ {fp(sig['ema20'])}`\n"
        f"📶 *EMA 200  :* `$ {fp(sig['ema200'])}`\n"
        f"📏 *ATR (14) :* `$ {fp(sig['atr'])}`\n"
        f"📊 *RSI (14) :* `{rsi_lbl}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💪 *Strength :* `{bar}` {pct}%\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ _Sirf educational. Apna analysis zaroor karein._"
    )

def build_summary_msg(scanned: int, found: int, skipped: int) -> str:
    now = datetime.now(timezone.utc).strftime("%d %b %Y  %H:%M UTC")
    return (
        f"📡 *Scan Complete — {now}*\n"
        f"──────────────────────────\n"
        f"🔍 Scanned : `{scanned}` coins\n"
        f"✅ Signals : `{found}` crossovers found\n"
        f"⏭ Skipped : `{skipped}` (not listed on Binance)\n"
        f"⏱ Next scan in `{INTERVAL_MINUTES}` minutes..."
    )

# ═════════════════════════════════════════════════════════════════════
#  STATE
# ═════════════════════════════════════════════════════════════════════

def load_state() -> dict:
    if Path(STATE_FILE).exists():
        try:
            return json.loads(Path(STATE_FILE).read_text())
        except Exception:
            pass
    return {}

def save_state(state: dict):
    Path(STATE_FILE).write_text(json.dumps(state, indent=2))

def signal_key(symbol: str, sig: dict) -> str:
    return f"{symbol}_{sig['type']}_{sig['candle_time']}"

# ═════════════════════════════════════════════════════════════════════
#  MAIN LOOP
# ═════════════════════════════════════════════════════════════════════

async def run_bot():
    request = HTTPXRequest(connection_pool_size=8)
    bot     = Bot(token=BOT_TOKEN, request=request)
    state   = load_state()

    start_msg = (
        f"🤖 *Binance EMA Signal Bot — Started!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 *Source    :* Binance (No API key needed)\n"
        f"🪙 *Coins     :* {len(BINANCE_PAIRS)} pairs\n"
        f"⏱ *Interval  :* Every `{INTERVAL_MINUTES}` minutes\n"
        f"📐 *Strategy  :* EMA {EMA_FAST} × EMA {EMA_SLOW} Crossover\n"
        f"🕯 *Timeframe :* {CANDLE_INTERVAL.upper()} Candles\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ First scan starting..."
    )
    await bot.send_message(chat_id=CHAT_ID, text=start_msg, parse_mode=ParseMode.MARKDOWN)
    log.info(f"Bot started. Scanning {len(BINANCE_PAIRS)} Binance pairs every {INTERVAL_MINUTES} min.")

    while True:
        cycle_start   = time.time()
        signals_found = 0
        skipped       = 0

        for symbol in BINANCE_PAIRS:
            try:
                df = fetch_ohlcv(symbol)
                if df is None:
                    skipped += 1
                    await asyncio.sleep(0.05)
                    continue

                sig = detect_signal(df)
                if sig is None:
                    continue

                key = signal_key(symbol, sig)
                if key in state:
                    continue

                msg = build_signal_msg(symbol, sig)
                await bot.send_message(
                    chat_id=CHAT_ID,
                    text=msg,
                    parse_mode=ParseMode.MARKDOWN,
                )
                state[key] = True
                save_state(state)
                signals_found += 1
                log.info(f"✅ {symbol}/USDT → {sig['type']} @ ${fp(sig['entry'])} strength={sig['strength']}%")
                await asyncio.sleep(0.5)

            except TelegramError as te:
                log.error(f"Telegram error [{symbol}]: {te}")
                await asyncio.sleep(2)
            except Exception as e:
                log.warning(f"[{symbol}] Error: {e}")
                skipped += 1

        scanned = len(BINANCE_PAIRS) - skipped
        try:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=build_summary_msg(scanned, signals_found, skipped),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

        if len(state) > 500:
            keys  = list(state.keys())
            state = {k: state[k] for k in keys[-500:]}
            save_state(state)

        elapsed = time.time() - cycle_start
        wait    = max(10, INTERVAL_MINUTES * 60 - elapsed)
        log.info(f"Cycle: {scanned} scanned, {signals_found} signals, {skipped} skipped. Next in {wait:.0f}s.")
        await asyncio.sleep(wait)

# ═════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    errors = []
    if not BOT_TOKEN or "APNA" in BOT_TOKEN : errors.append("BOT_TOKEN set nahi kiya!")
    if not CHAT_ID   or "APNA" in CHAT_ID   : errors.append("CHAT_ID set nahi kiya!")

    if errors:
        print("\n" + "─"*45)
        print("❌  CONFIGURATION ERROR:")
        for e in errors:
            print(f"    • {e}")
        print("─"*45 + "\n")
        raise SystemExit(1)

    log.info("="*50)
    log.info("  Binance EMA Signal Bot | Starting...")
    log.info(f"  {len(BINANCE_PAIRS)} pairs | EMA {EMA_FAST}/{EMA_SLOW} | {CANDLE_INTERVAL.upper()} | Every {INTERVAL_MINUTES}min")
    log.info("="*50)

    asyncio.run(run_bot())
