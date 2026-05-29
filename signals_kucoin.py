"""
signals_kucoin.py — Crypto Trading Bot (KuCoin Edition)
Level 3.1: Clean signal format (Entry/TP/SL only)
"""

import os
import time
import logging
import requests
import pandas as pd
from datetime import datetime, timezone

import tracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("kucoin")

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

KUCOIN_BASE      = "https://api.kucoin.com/api/v1"

MAX_PRICE        = 1.0
MIN_VOLUME       = 1_000_000
SCAN_INTERVAL    = 60 * 30
QUOTE_ASSET      = "USDT"
MAX_COINS        = 80
EXCHANGE_TAG     = "KUCOIN"
WORKSHEET_NAME   = os.getenv("WORKSHEET", "KuCoin Signals")

HEADERS = {
    "User-Agent": "CryptoSignalsBot-KuCoin/3.1",
    "Accept": "application/json",
}


def send_telegram(message: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram env vars missing")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        return r.ok
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False


def safe_get(url, params=None, max_retries=3):
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=15)
            if r.status_code == 429:
                wait = 5 * (attempt + 1)
                log.warning(f"[429] wait {wait}s")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                log.error(f"Request failed: {e}")
                return None
            time.sleep(2)
    return None


def fetch_coin_universe():
    payload = safe_get(f"{KUCOIN_BASE}/market/allTickers")
    if not payload or payload.get("code") != "200000":
        log.error(f"KuCoin allTickers bad response: {payload and payload.get('code')}")
        return []

    tickers = payload.get("data", {}).get("ticker", []) or []
    coins = []
    for t in tickers:
        symbol = t.get("symbol", "")
        if not symbol.endswith(f"-{QUOTE_ASSET}"):
            continue
        try:
            price      = float(t.get("last") or 0)
            volume     = float(t.get("volValue") or 0)
            change_24h = float(t.get("changeRate") or 0) * 100
        except (TypeError, ValueError):
            continue
        if 0 < price < MAX_PRICE and volume > MIN_VOLUME:
            base = symbol.split("-")[0]
            coins.append({
                "symbol":     base,
                "pair":       symbol,
                "price":      price,
                "volume":     volume,
                "change_24h": change_24h,
            })

    coins.sort(key=lambda c: c["volume"], reverse=True)
    coins = coins[:MAX_COINS]
    log.info(f"Universe: {len(coins)} {QUOTE_ASSET} pairs on KuCoin after filters")
    return coins


_KUCOIN_INTERVAL = {
    "1h": "1hour",
    "4h": "4hour",
}


def fetch_klines(pair, interval, limit=250):
    k_interval = _KUCOIN_INTERVAL.get(interval, interval)
    payload = safe_get(
        f"{KUCOIN_BASE}/market/candles",
        params={"type": k_interval, "symbol": pair},
    )
    if not payload or payload.get("code") != "200000":
        return None
    rows = payload.get("data", []) or []
    if not rows:
        return None

    df = pd.DataFrame(rows, columns=["time", "open", "close", "high", "low", "volume", "turnover"])
    df = df.iloc[::-1].reset_index(drop=True)
    df["open"]  = df["open"].astype(float)
    df["high"]  = df["high"].astype(float)
    df["low"]   = df["low"].astype(float)
    df["close"] = df["close"].astype(float)
    if len(df) > limit:
        df = df.tail(limit).reset_index(drop=True)
    return df


def get_current_price(symbol):
    pair = symbol.upper() + "-" + QUOTE_ASSET
    payload = safe_get(
        f"{KUCOIN_BASE}/market/orderbook/level1",
        params={"symbol": pair},
    )
    if not payload or payload.get("code") != "200000":
        return None
    try:
        return float(payload.get("data", {}).get("price"))
    except (TypeError, ValueError):
        return None


def ema(series, length):
    return series.ewm(span=length, adjust=False).mean()


def atr(df, length=14):
    high  = df["high"]
    low   = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return float(tr.tail(length).mean())


def fresh_cross(ema_fast, ema_slow):
    if len(ema_fast) < 2:
        return None
    prev = ema_fast.iloc[-2] - ema_slow.iloc[-2]
    curr = ema_fast.iloc[-1] - ema_slow.iloc[-1]
    if prev <= 0 < curr:
        return "BUY"
    if prev >= 0 > curr:
        return "SELL"
    return None


def analyze(coin):
    pair = coin["pair"]

    df_4h = fetch_klines(pair, "4h", limit=250)
    df_1h = fetch_klines(pair, "1h", limit=100)

    if df_4h is None or df_1h is None or len(df_4h) < 200 or len(df_1h) < 50:
        return None

    ema200_4h = ema(df_4h["close"], 200).iloc[-1]
    price     = float(df_1h["close"].iloc[-1])
    trend_up  = price > ema200_4h
    trend_dn  = price < ema200_4h

    ema20_1h = ema(df_1h["close"], 20)
    ema50_1h = ema(df_1h["close"], 50)
    cross = fresh_cross(ema20_1h, ema50_1h)
    if cross is None:
        return None

    if cross == "BUY" and not trend_up:
        return None
    if cross == "SELL" and not trend_dn:
        return None

    atr_val = atr(df_1h, 14)
    if atr_val <= 0:
        return None

    sl_mult, tp1_mult, tp2_mult = 1.5, 1.5, 3.0
    if cross == "BUY":
        sl  = price - sl_mult  * atr_val
        tp1 = price + tp1_mult * atr_val
        tp2 = price + tp2_mult * atr_val
    else:
        sl  = price + sl_mult  * atr_val
        tp1 = price - tp1_mult * atr_val
        tp2 = price - tp2_mult * atr_val

    risk   = abs(price - sl)
    reward = abs(tp2  - price)
    rr     = f"1 : {round(reward / risk, 1)}" if risk > 0 else "N/A"

    return {
        "exchange":     EXCHANGE_TAG,
        "symbol":       coin["symbol"],
        "pair_display": f"{coin['symbol']}/{QUOTE_ASSET}",
        "price":        price,
        "signal_type":  cross,
        "confidence":   "HIGH",
        "volume":       coin["volume"],
        "change_24h":   coin["change_24h"],
        "ema20":        float(ema20_1h.iloc[-1]),
        "ema50":        float(ema50_1h.iloc[-1]),
        "ema200":       float(ema200_4h),
        "atr":          atr_val,
        "tp1":          tp1,
        "tp2":          tp2,
        "sl":           sl,
        "rr":           rr,
    }


def fmt_price(p):
    if p >= 1:
        return f"{p:.4f}"
    if p >= 0.01:
        return f"{p:.5f}"
    return f"{p:.8f}".rstrip("0").rstrip(".") or f"{p:.8f}"


def fmt_volume(v):
    if v >= 1_000_000_000:
        return f"${v / 1_000_000_000:.1f}B"
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v / 1_000:.1f}K"
    return f"${v:,.0f}"


def format_signal(sig, idx, logged):
    is_buy = sig["signal_type"] == "BUY"
    emoji  = "🟢" if is_buy else "🔴"
    action = "BUY" if is_buy else "SELL"
    change_sign = "+" if sig["change_24h"] >= 0 else ""

    return (
        f"{emoji} <b>[{EXCHANGE_TAG}] #{idx} {sig['pair_display']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f" Action : <b>{action}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f" Entry  : <code>${fmt_price(sig['price'])}</code>\n"
        f" TP1    : <code>${fmt_price(sig['tp1'])}</code>\n"
        f" TP2    : <code>${fmt_price(sig['tp2'])}</code>\n"
        f" SL     : <code>${fmt_price(sig['sl'])}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f" Volume : <code>{fmt_volume(sig['volume'])}</code>\n"
        f" 24h    : <code>{change_sign}{sig['change_24h']:.2f}%</code>"
    )


def format_scan_summary(scanned, signals_found):
    now = datetime.now(timezone.utc).strftime("%d %b %Y  %H:%M")
    if signals_found == 0:
        body = "✅ Koi HIGH signal nahi mila"
    elif signals_found == 1:
        body = "🎯 <b>1 HIGH signal</b> mila (upar dekho)"
    else:
        body = f"🎯 <b>{signals_found} HIGH signals</b> mile (upar dekho)"

    next_min = SCAN_INTERVAL // 60
    return (
        f"📊 <b>[{EXCHANGE_TAG}] SCAN COMPLETE</b>\n"
        f"  {now} UTC\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"  {body}\n"
        f"  🔍 {scanned} coins scan kiye\n"
        f"  ⏰ Agla scan {next_min} min mein..."
    )


def format_close_event(ev):
    event = ev.get("event", "")
    symbol = ev.get("symbol", "")
    entry = ev.get("entry", 0.0)
    exit_p = ev.get("exit_price", 0.0)
    pnl = ev.get("pnl", 0.0)
    pnl_sign = "+" if pnl >= 0 else ""

    if event == "TP2 HIT":
        emoji, headline = "✅", "TP2 HIT — CLOSED"
    elif event == "SL HIT":
        emoji, headline = "🛑", "SL HIT — CLOSED"
    elif event == "TP1 HIT":
        emoji, headline = "🎯", "TP1 HIT"
    else:
        emoji, headline = "ℹ️", event

    return (
        f"{emoji} <b>[{EXCHANGE_TAG}] {headline}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f" Pair  : <b>{symbol}/{QUOTE_ASSET}</b>\n"
        f" Entry : <code>${fmt_price(entry)}</code>\n"
        f" Now   : <code>${fmt_price(exit_p)}</code>\n"
        f" P&L   : <code>{pnl_sign}{pnl:.2f}%</code>"
    )


def scan_once():
    universe = fetch_coin_universe()

    if not universe:
        log.warning("Empty universe — skipping scan")
        send_telegram(
            f"⚠️ <b>[{EXCHANGE_TAG}] SCAN SKIPPED</b>\n"
            "KuCoin se data nahi mila. Agla scan 30 min mein..."
        )
        return

    events = tracker.update_open_trades(get_current_price, ws_name=WORKSHEET_NAME)
    for ev in events:
        try:
            send_telegram(format_close_event(ev))
            time.sleep(1)
        except Exception as e:
            log.error(f"Failed to send close event: {e}")

    new_signals = 0
    for i, coin in enumerate(universe, start=1):
        try:
            sig = analyze(coin)
            if sig:
                new_signals += 1
                logged = tracker.log_signal(sig, ws_name=WORKSHEET_NAME)
                send_telegram(format_signal(sig, new_signals, logged))
                time.sleep(2)
        except Exception as e:
            log.error(f"analyze({coin['symbol']}) failed: {e}")

        time.sleep(0.25)

        if i % 25 == 0:
            log.info(f"Progress: {i}/{len(universe)} coins scanned")

    log.info(f"Scan complete — {new_signals} new HIGH signal(s) out of {len(universe)} coins")
    send_telegram(format_scan_summary(len(universe), new_signals))


def main():
    log.info(f"🚀 KuCoin Bot starting — sheet tab: '{WORKSHEET_NAME}'")

    if tracker.healthcheck(ws_name=WORKSHEET_NAME):
        send_telegram(
            f"✅ <b>[{EXCHANGE_TAG}] Bot Online</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "📡 KuCoin API connected\n"
            f"📊 Google Sheet: '{WORKSHEET_NAME}' tab\n"
            f"⏰ Scan every {SCAN_INTERVAL // 60} min"
        )
    else:
        send_telegram(f"⚠️ [{EXCHANGE_TAG}] Bot online — Sheets healthcheck FAILED")

    while True:
        try:
            scan_once()
        except Exception as e:
            log.error(f"Scan loop error: {e}")
            send_telegram(f"⚠️ [{EXCHANGE_TAG}] Scan error: {e}")
        log.info(f"Sleeping {SCAN_INTERVAL}s ...")
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
