"""
tracker.py — Level 3 Signal Tracker
Google Sheets integration with strict TP/SL close logic.

Status flow:
    OPEN     → trade still active
    TP1 HIT  → trade reached TP1 (still open, waiting for TP2 or SL)
    TP2 HIT  → trade closed at TP2 (win)
    SL HIT   → trade closed at SL (loss)
"""

import os
import json
import logging
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEET_ID   = os.getenv("GOOGLE_SHEET_ID")
CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

DEFAULT_WORKSHEET = os.getenv("WORKSHEET", "Signals")

HEADERS = [
    "Timestamp (UTC)",     # A
    "Exchange",            # B
    "Symbol",              # C
    "Entry Price",         # D
    "Signal",              # E
    "Confidence",          # F
    "Volume (USD)",        # G
    "24h Change %",        # H
    "TP1",                 # I
    "TP2",                 # J
    "SL",                  # K
    "R:R",                 # L
    "EMA20",               # M
    "EMA50",               # N
    "EMA200",              # O
    "Status",              # P
    "Current Price",       # Q
    "P&L %",               # R
    "Closed At (UTC)",     # S
    "Final P&L %",         # T
]

log = logging.getLogger("tracker")


# ---------------------------------------------------------------------------
# CONNECTION
# ---------------------------------------------------------------------------

_client = None
_worksheets = {}


def _connect(ws_name: str = None):
    global _client

    if ws_name is None:
        ws_name = DEFAULT_WORKSHEET

    if ws_name in _worksheets:
        return _worksheets[ws_name]

    if not CREDS_JSON or not SHEET_ID:
        raise RuntimeError(
            "Missing env vars: GOOGLE_CREDENTIALS_JSON and/or GOOGLE_SHEET_ID"
        )

    if _client is None:
        info = json.loads(CREDS_JSON)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        _client = gspread.authorize(creds)

    sh = _client.open_by_key(SHEET_ID)

    try:
        ws = sh.worksheet(ws_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=ws_name, rows=1000, cols=25)

    first_row = ws.row_values(1)
    if first_row != HEADERS:
        ws.update("A1", [HEADERS])
        last_col = chr(ord("A") + len(HEADERS) - 1)
        ws.format(
            f"A1:{last_col}1",
            {
                "textFormat": {"bold": True},
                "backgroundColor": {"red": 0.13, "green": 0.16, "blue": 0.22},
                "horizontalAlignment": "CENTER",
            },
        )

    _worksheets[ws_name] = ws
    log.info(f"[TRACKER] Connected to Google Sheet tab '{ws_name}' ✅")
    return ws


# ---------------------------------------------------------------------------
# LOG NEW SIGNAL
# ---------------------------------------------------------------------------

def log_signal(signal: dict, ws_name: str = None) -> bool:
    try:
        ws = _connect(ws_name)

        row = [
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            signal.get("exchange", ""),
            signal.get("symbol", ""),
            float(signal.get("price", 0)),
            signal.get("signal_type", ""),
            signal.get("confidence", "HIGH"),
            float(signal.get("volume", 0)),
            float(signal.get("change_24h", 0)),
            float(signal.get("tp1", 0)),
            float(signal.get("tp2", 0)),
            float(signal.get("sl", 0)),
            signal.get("rr", ""),
            float(signal.get("ema20", 0)),
            float(signal.get("ema50", 0)),
            float(signal.get("ema200", 0)),
            "OPEN",
            float(signal.get("price", 0)),
            0.0,
            "",
            "",
        ]

        ws.append_row(row, value_input_option="USER_ENTERED")
        log.info(f"[TRACKER] Logged {signal.get('symbol')} @ {signal.get('price')} to '{ws.title}'")
        return True

    except Exception as e:
        log.error(f"[TRACKER] log_signal failed: {e}")
        return False


# ---------------------------------------------------------------------------
# UPDATE OPEN TRADES + AUTO-CLOSE
# ---------------------------------------------------------------------------

def update_open_trades(price_lookup, ws_name: str = None) -> list:
    """
    For every active row (OPEN or TP1 HIT):
      - Refresh Current Price + live P&L
      - Detect TP1 / TP2 / SL hit
      - Return list of close events for Telegram notifications
    """
    events = []
    try:
        ws = _connect(ws_name)
        rows = ws.get_all_records()
        if not rows:
            return events

        updates = []
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        ACTIVE = {"OPEN", "TP1 HIT"}

        for idx, r in enumerate(rows, start=2):
            status = (r.get("Status") or "").strip()
            if status not in ACTIVE:
                continue

            symbol      = r.get("Symbol", "")
            signal_type = (r.get("Signal") or "").upper()
            try:
                entry = float(r.get("Entry Price") or 0)
                tp1   = float(r.get("TP1") or 0)
                tp2   = float(r.get("TP2") or 0)
                sl    = float(r.get("SL")  or 0)
            except (TypeError, ValueError):
                continue
            if entry <= 0:
                continue

            current = None
            try:
                current = price_lookup(symbol)
            except Exception as e:
                log.warning(f"[TRACKER] price lookup failed for {symbol}: {e}")
            if not current:
                continue

            if signal_type == "BUY":
                pnl = ((current - entry) / entry) * 100
            elif signal_type == "SELL":
                pnl = ((entry - current) / entry) * 100
            else:
                pnl = 0.0

            new_status = status
            closed_at  = r.get("Closed At (UTC)", "")
            final_pnl  = r.get("Final P&L %", "")

            if signal_type == "BUY":
                hit_sl  = sl  > 0 and current <= sl
                hit_tp2 = tp2 > 0 and current >= tp2
                hit_tp1 = tp1 > 0 and current >= tp1
            else:
                hit_sl  = sl  > 0 and current >= sl
                hit_tp2 = tp2 > 0 and current <= tp2
                hit_tp1 = tp1 > 0 and current <= tp1

            if hit_sl and status != "SL HIT":
                new_status = "SL HIT"
                closed_at  = now_utc
                final_pnl  = round(pnl, 2)
                events.append({
                    "symbol": symbol, "signal_type": signal_type,
                    "entry": entry, "exit_price": current,
                    "event": "SL HIT", "pnl": pnl,
                    "opened_at": r.get("Timestamp (UTC)", ""),
                })
            elif hit_tp2 and status != "TP2 HIT":
                new_status = "TP2 HIT"
                closed_at  = now_utc
                final_pnl  = round(pnl, 2)
                events.append({
                    "symbol": symbol, "signal_type": signal_type,
                    "entry": entry, "exit_price": current,
                    "event": "TP2 HIT", "pnl": pnl,
                    "opened_at": r.get("Timestamp (UTC)", ""),
                })
            elif hit_tp1 and status == "OPEN":
                new_status = "TP1 HIT"
                events.append({
                    "symbol": symbol, "signal_type": signal_type,
                    "entry": entry, "exit_price": current,
                    "event": "TP1 HIT", "pnl": pnl,
                    "opened_at": r.get("Timestamp (UTC)", ""),
                })

            updates.append({
                "range": f"P{idx}:T{idx}",
                "values": [[
                    new_status,
                    round(current, 8),
                    round(pnl, 2),
                    closed_at,
                    final_pnl,
                ]],
            })

        if updates:
            ws.batch_update(updates, value_input_option="USER_ENTERED")
            log.info(f"[TRACKER] Updated {len(updates)} active trade(s) in '{ws.title}'")
            if events:
                log.info(f"[TRACKER] {len(events)} status change event(s)")

        return events

    except Exception as e:
        log.error(f"[TRACKER] update_open_trades failed: {e}")
        return events


def healthcheck(ws_name: str = None) -> bool:
    try:
        _connect(ws_name)
        return True
    except Exception as e:
        log.error(f"[TRACKER] Healthcheck failed: {e}")
        return False
