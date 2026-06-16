"""Binance Long/Short Account Ratio → feature ML cryptos.

Binance expose le ratio de comptes long vs short sur ses contrats perp.
Indicateur de positionning retail. Au-dessus de 2.0 = excès de longs
(contrarien = favorable shorts). En-dessous de 0.7 = excès de shorts
(contrarien = favorable longs).

Source : Binance Futures public API, no auth.
Mise à jour toutes les 5 min côté Binance. Cache 15 min ici.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import urllib.request
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_API_URL = (
    "https://fapi.binance.com/futures/data/topLongShortAccountRatio"
    "?symbol={symbol}&period=5m&limit=1"
)
_DB_PATH = "/app/data/macro.db"

# Pairs supportées
_PAIR_TO_BINANCE: dict[str, str] = {
    "BTC/USD": "BTCUSDT",
    "ETH/USD": "ETHUSDT",
    "SOL/USD": "SOLUSDT",
    "ADA/USD": "ADAUSDT",
    "XRP/USD": "XRPUSDT",
    "LTC/USD": "LTCUSDT",
    "BCH/USD": "BCHUSDT",
    "DOT/USD": "DOTUSDT",
}


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS binance_lsr (
            symbol TEXT PRIMARY KEY,
            long_short_ratio REAL,
            long_account REAL,
            short_account REAL,
            fetched_at TEXT NOT NULL
        )
    """)
    con.commit()


def _fetch_one(symbol: str) -> dict[str, Any] | None:
    try:
        url = _API_URL.format(symbol=symbol)
        req = urllib.request.Request(url, headers={"User-Agent": "scalping-radar/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        if not data:
            return None
        latest = data[0]
        return {
            "ratio": float(latest["longShortRatio"]),
            "long": float(latest["longAccount"]),
            "short": float(latest["shortAccount"]),
        }
    except Exception as e:
        logger.warning(f"binance LSR fetch {symbol} failed: {e}")
        return None


def refresh_all() -> dict[str, int]:
    n_ok, n_fail = 0, 0
    con = sqlite3.connect(_DB_PATH)
    _ensure_schema(con)
    now = datetime.now(timezone.utc).isoformat()
    for pair, sym in _PAIR_TO_BINANCE.items():
        d = _fetch_one(sym)
        if not d:
            n_fail += 1
            continue
        con.execute(
            "INSERT OR REPLACE INTO binance_lsr (symbol, long_short_ratio, long_account, short_account, fetched_at) VALUES (?, ?, ?, ?, ?)",
            (sym, d["ratio"], d["long"], d["short"], now),
        )
        n_ok += 1
    con.commit()
    con.close()
    logger.info(f"binance_lsr refresh: {n_ok} ok, {n_fail} fail")
    return {"ok": n_ok, "fail": n_fail}


def get_features(pair: str) -> dict[str, float]:
    sym = _PAIR_TO_BINANCE.get(pair)
    if not sym:
        return {
            "lsr_ratio": 0, "lsr_long_pct": 0, "lsr_short_pct": 0,
            "lsr_excess_long": 0, "lsr_excess_short": 0, "lsr_available": 0,
        }
    try:
        con = sqlite3.connect(_DB_PATH)
        con.row_factory = sqlite3.Row
        r = con.execute(
            "SELECT long_short_ratio, long_account, short_account, fetched_at FROM binance_lsr WHERE symbol=?",
            (sym,),
        ).fetchone()
        con.close()
        if not r:
            return {"lsr_ratio": 0, "lsr_long_pct": 0, "lsr_short_pct": 0,
                    "lsr_excess_long": 0, "lsr_excess_short": 0, "lsr_available": 0}
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(r["fetched_at"])).total_seconds()
        if age > 1800:  # >30 min
            return {"lsr_ratio": 0, "lsr_long_pct": 0, "lsr_short_pct": 0,
                    "lsr_excess_long": 0, "lsr_excess_short": 0, "lsr_available": 0}
        ratio = r["long_short_ratio"] or 0
        return {
            "lsr_ratio": ratio,
            "lsr_long_pct": r["long_account"] or 0,
            "lsr_short_pct": r["short_account"] or 0,
            "lsr_excess_long": 1 if ratio > 2.0 else 0,
            "lsr_excess_short": 1 if ratio < 0.7 else 0,
            "lsr_available": 1,
        }
    except Exception as e:
        logger.warning(f"binance_lsr get_features: {e}")
        return {"lsr_ratio": 0, "lsr_long_pct": 0, "lsr_short_pct": 0,
                "lsr_excess_long": 0, "lsr_excess_short": 0, "lsr_available": 0}
