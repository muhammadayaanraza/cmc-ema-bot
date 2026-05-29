#!/usr/bin/env python3
"""
Bybit EMA 20/200 Crossover — Telegram Signal Bot
Data: Bybit public API | 300+ pairs
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
    print(f"\n❌ pip install python-telegram-bot requests pandas numpy httpx\n")
    raise SystemExit(1)

# ══════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════
BOT_TOKEN        = os.getenv("BOT_TOKEN", "APNA_BOT_TOKEN_YAHAN")
CHAT_ID          = os.getenv("CHAT_ID",   "APNA_CHAT_ID_YAHAN")
INTERVAL_MINUTES = 15
EMA_FAST         = 20
EMA_SLOW         = 200
ATR_PERIOD       = 14
CANDLE_LIMIT     = 250
LOG_FILE         = "ema_bot.log"
STATE_FILE       = "bot_state.json"

# ══════════════════════════════════════════════
#  300+ BYBIT USDT PAIRS
# ══════════════════════════════════════════════
PAIRS = [
    # Major
    "BTC","ETH","BNB","XRP","SOL","ADA","DOGE","TRX","LTC","BCH",
    # DeFi
    "AVAX","DOT","LINK","UNI","ATOM","NEAR","APT","SUI","INJ","FET",
    "GRT","AAVE","MKR","COMP","SNX","CRV","BAL","YFI","SUSHI","1INCH",
    "CAKE","ALPHA","BADGER","BNT","DYDX","PERP","TRIBE",
    # Layer 2
    "ARB","OP","IMX","STRK","BLUR","MANTA","ZK","METIS","BOBA","SKL",
    "CELR","LRC","OMG","CTSI","IDEX",
    # Meme
    "SHIB","PEPE","FLOKI","BONK","WIF","BOME","NEIRO","DOGS","MEW",
    "MEME","TURBO","ELON","SAMO","LEASH",
    # Gaming / NFT
    "AXS","SAND","MANA","ENJ","GALA","ILV","ALICE","SUPER","CHZ",
    "FLOW","LOOKS","MAGIC","TLM","SLP","YGG","GUILD","UFO","WAXP",
    "HERO","SKILL","MOBOX","RFOX","FEVR",
    # Infrastructure
    "FIL","AR","STORJ","ANKR","ONE","ZIL","OCEAN","RLC","GNO",
    "NMR","OXT","API3","BAND","DIA","TRB","UMA","REQ","PHA",
    # Layer 1
    "TON","HBAR","VET","EOS","XLM","ALGO","THETA","KAVA","ROSE","CELO",
    "NEO","IOTA","QTUM","ICX","ONT","WAVES","ZEN","SC","DCR","DGB",
    "RVN","FIRO","BTG","BTT","WIN","JST","SUN",
    # Privacy
    "XMR","ZEC","DASH","SCRT","BEAM","GRIN",
    # Exchange tokens
    "CRO","KCS","HT","GT","MX","WOO","NEXO",
    # AI / Data
    "RENDER","TAO","WLD","AGIX","ORAI","ARKM","HOOK","PHB","CTXC",
    # Interoperability
    "KSM","ACA","ASTR","MOVR","CFG",
    # RWA / New 2024-2025
    "ONDO","POLYX","CFX","ACE","PIXEL","PORTAL","ALT","JUP","W",
    "TNSR","SAGA","REZ","BB","NOT","IO","ZRO","LISTA","ZETA","OMNI",
    "ETHFI","EIGEN","CATI","HMSTR","MAJOR","HYPE","ME","VANA","MOVE",
    "USUAL","ACT","PNUT","KAIA","LUMIA","MOCA","NYAN","PENGU","AIXBT",
    "VIRTUAL","AI16Z","GRIFFAIN","FARTCOIN","ZEREBRO","SWARMS","PIPPIN",
    "BANANAS31","COOKIE","GRIFT","ANON","BUZZ","KEKIUS","TRUMP","MELANIA",
    "VINE","TROLL","BIO","SONIC","ANIME","KAITO","GPS","TST","LAYER",
    "BERA","IP","RED","INITIA","KERNEL","SIGN","WAL","HAEDAL","PARTI",
    # Older alts
    "BAT","HOT","REN","ZRX","OGN","LOOM","FOR","KEY","DOCK","BLZ",
    "TROY","PERL","DUSK","WIN","COS","TFUEL","TOMO","IRIS","MBL","COTI",
    "STPT","WRX","LTO","MFT","DATA","HARD","BEL","WING","AVA","UTK",
    "FUN","NULS","ARDR","WAN","POWR","SYS","TNT","GVT","MOD","TNB",
    "PIVX","MTH","STMX","VITE","COCOS","PERL","TKO","BTTC",
]

# Remove duplicates while preserving order
PAIRS = list(dict.fromkeys(PAIRS))

# ══════════════════════════════════════════════
#  LOGGING
# ══════════════════════════════════════════════
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

# ══════════════════════════════════════════════
#  BYBIT OHLCV
# ══════════════════════════════════════════════
BYBIT_BASE = "https://api.bybit.com"

def fetch_ohlcv(symbol: str) -> pd.DataFrame | None:
    pair = f"{symbol}USDT"
    try:
        r = requests.get(
            f"{BYBIT_BASE}/v5/market/kline",
            params={"category":"linear","symbol":pair,"interval":"15","limit":CANDLE_LIMIT},
            timeout=15,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        if data.get("retCode") != 0:
            return None
        raw = data["result"]["list"]
        if not raw or len(raw) < EMA_SLOW + 10:
            return None
        raw = list(reversed(raw))
        df  = pd.DataFrame(raw, columns=["ts","open","high","low","close","vol","turnover"])
        for col in ["open","high","low","close","vol"]:
            df[col] = df[col].astype(float)
        df["ts"] = pd.to_datetime(df["ts"].astype(float), unit="ms", utc=True)
        return df[["ts","open","high","low","close","vol"]].reset_index(drop=True)
    except Exception as e:
        log.debug(f"[{symbol}] fetch error: {e}")
        return None

# ══════════════════════════════════════════════
#  INDICATORS
# ══════════════════════════════════════════════
def calc_ema(s, p): return s.ewm(span=p, adjust=False).mean()

def calc_atr(df):
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"]-df["low"],(df["high"]-pc).abs(),(df["low"]-pc).abs()],axis=1).max(axis=1)
    return float(tr.ewm(span=ATR_PERIOD, adjust=False).mean().iloc[-1])

def calc_rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(span=p,adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(span=p,adjust=False).mean()
    return round(float(100 - 100/(1 + g/l.replace(0,np.nan)).iloc[-1]), 1)

def calc_strength(e20, e200, closes):
    gap = abs(e20-e200)/e200*100
    mom = abs((closes.iloc[-1]-closes.iloc[-6])/closes.iloc[-6]*100)
    return round(min(99.1, 74+gap*12+mom*1.8), 1)

# ══════════════════════════════════════════════
#  SIGNAL DETECTION
# ══════════════════════════════════════════════
def detect_signal(df):
    closes = df["close"]
    e20  = calc_ema(closes, EMA_FAST)
    e200 = calc_ema(closes, EMA_SLOW)
    n, p = len(df)-1, len(df)-2
    curr = e20.iloc[n] > e200.iloc[n]
    prev = e20.iloc[p] > e200.iloc[p]
    if curr == prev: return None
    price   = float(closes.iloc[n])
    atr_val = calc_atr(df)
    base = {
        "entry":price,"ema20":float(e20.iloc[n]),"ema200":float(e200.iloc[n]),
        "atr":atr_val,"rsi":calc_rsi(closes),
        "strength":calc_strength(float(e20.iloc[n]),float(e200.iloc[n]),closes),
        "candle_time":str(df["ts"].iloc[n]),
    }
    if curr:
        return {**base,"type":"LONG","sl":price-atr_val*1.5,
                "tp1":price+atr_val*2,"tp2":price+atr_val*4,"tp3":price+atr_val*6}
    else:
        return {**base,"type":"SHORT","sl":price+atr_val*1.5,
                "tp1":price-atr_val*2,"tp2":price-atr_val*4,"tp3":price-atr_val*6}

# ══════════════════════════════════════════════
#  FORMATTER
# ══════════════════════════════════════════════
def fp(v):
    if v is None or (isinstance(v,float) and np.isnan(v)): return "N/A"
    if   abs(v)<0.000001: return f"{v:.10f}"
    elif abs(v)<0.0001:   return f"{v:.8f}"
    elif abs(v)<0.01:     return f"{v:.6f}"
    elif abs(v)<1:        return f"{v:.5f}"
    elif abs(v)<100:      return f"{v:.3f}"
    else:                 return f"{v:,.2f}"

# ══════════════════════════════════════════════
#  MESSAGES
# ══════════════════════════════════════════════
def build_signal_msg(symbol, sig):
    now     = datetime.now(timezone.utc).strftime("%d %b %Y  %H:%M UTC")
    is_long = sig["type"]=="LONG"
    emoji   = "🟢" if is_long else "🔴"
    direct  = "📈 *LONG  — BUY*" if is_long else "📉 *SHORT — SELL*"
    cross   = "EMA20 crossed ABOVE EMA200 *(Bullish)*" if is_long else "EMA20 crossed BELOW EMA200 *(Bearish)*"
    rsi     = sig.get("rsi",50)
    rsi_lbl = f"{rsi} ⚠️ Overbought" if rsi>70 else (f"{rsi} ⚠️ Oversold" if rsi<30 else f"{rsi} ✅ Neutral")
    pct     = sig["strength"]
    bar     = "█"*round(pct/10) + "░"*(10-round(pct/10))
    return (
        f"{emoji} *BYBIT — {symbol}/USDT*\n"
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

def build_summary_msg(scanned, found, skipped):
    now = datetime.now(timezone.utc).strftime("%d %b %Y  %H:%M UTC")
    return (
        f"📡 *Scan Complete — {now}*\n"
        f"──────────────────────────\n"
        f"🔍 Scanned : `{scanned}` coins\n"
        f"✅ Signals : `{found}` crossovers found\n"
        f"⏭ Skipped : `{skipped}` (not on Bybit)\n"
        f"⏱ Next scan in `{INTERVAL_MINUTES}` minutes..."
    )

# ══════════════════════════════════════════════
#  STATE
# ══════════════════════════════════════════════
def load_state():
    if Path(STATE_FILE).exists():
        try: return json.loads(Path(STATE_FILE).read_text())
        except: pass
    return {}

def save_state(state):
    Path(STATE_FILE).write_text(json.dumps(state, indent=2))

def signal_key(symbol, sig):
    return f"{symbol}_{sig['type']}_{sig['candle_time']}"

# ══════════════════════════════════════════════
#  MAIN LOOP
# ══════════════════════════════════════════════
async def run_bot():
    request = HTTPXRequest(connection_pool_size=8)
    bot     = Bot(token=BOT_TOKEN, request=request)
    state   = load_state()

    await bot.send_message(
        chat_id=CHAT_ID,
        text=(
            f"🤖 *Bybit EMA Signal Bot — Started!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 *Source    :* Bybit (No API key needed)\n"
            f"🪙 *Coins     :* {len(PAIRS)} pairs\n"
            f"⏱ *Interval  :* Every `{INTERVAL_MINUTES}` minutes\n"
            f"📐 *Strategy  :* EMA {EMA_FAST} × EMA {EMA_SLOW} Crossover\n"
            f"🕯 *Timeframe :* 15M Candles\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏳ First scan starting..."
        ),
        parse_mode=ParseMode.MARKDOWN,
    )
    log.info(f"Bot started. {len(PAIRS)} pairs every {INTERVAL_MINUTES}min.")

    while True:
        cycle_start   = time.time()
        signals_found = 0
        skipped       = 0

        for symbol in PAIRS:
            try:
                df = fetch_ohlcv(symbol)
                if df is None:
                    skipped += 1
                    await asyncio.sleep(0.1)
                    continue

                sig = detect_signal(df)
                if sig is None:
                    continue

                key = signal_key(symbol, sig)
                if key in state:
                    continue

                msg = build_signal_msg(symbol, sig)
                await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)
                state[key] = True
                save_state(state)
                signals_found += 1
                log.info(f"✅ {symbol} → {sig['type']} @ ${fp(sig['entry'])} str={sig['strength']}%")
                await asyncio.sleep(0.5)

            except TelegramError as te:
                log.error(f"Telegram [{symbol}]: {te}")
                await asyncio.sleep(2)
            except Exception as e:
                log.warning(f"[{symbol}] {e}")
                skipped += 1

        scanned = len(PAIRS) - skipped
        try:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=build_summary_msg(scanned, signals_found, skipped),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

        if len(state) > 1000:
            keys  = list(state.keys())
            state = {k: state[k] for k in keys[-1000:]}
            save_state(state)

        elapsed = time.time() - cycle_start
        wait    = max(10, INTERVAL_MINUTES*60 - elapsed)
        log.info(f"Done: {scanned} scanned, {signals_found} signals. Next in {wait:.0f}s.")
        await asyncio.sleep(wait)

# ══════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════
if __name__ == "__main__":
    errors = []
    if not BOT_TOKEN or "APNA" in BOT_TOKEN: errors.append("BOT_TOKEN set nahi!")
    if not CHAT_ID   or "APNA" in CHAT_ID  : errors.append("CHAT_ID set nahi!")
    if errors:
        for e in errors: print(f"❌ {e}")
        raise SystemExit(1)
    log.info("="*50)
    log.info(f"Bybit EMA Bot | {len(PAIRS)} pairs | Every {INTERVAL_MINUTES}min")
    log.info("="*50)
    asyncio.run(run_bot())
