"""Binance perpetual funding rates → feature ML.

Funding rates Binance Futures sont publiées toutes les 8h. Sign et magnitude
sont des proxies pour le sentiment retail / positioning :
- funding élevé positif (>0.05%) = beaucoup de longs → trade contrarien favorise les shorts
- funding négatif (<-0.02%) = excès de shorts → contrarien favorise les longs

API publique gratuite, pas d'auth.
Cache 30 min en DB (macro.db).

Usage :
    from backend.services import binance_funding_service as bf
    rate = bf.get_funding_rate("BTC/USD")  # retourne dict {rate, last_update, is_fresh}
    # rate = 0.0001 = 0.01% (typique). > 0 = longs paient shorts.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Mapping pair Scalping → symbole Binance Perp
_PAIR_TO_BINANCE: dict[str, str] = {
    "BTC/USD": "BTCUSDT",
    "ETH/USD": "ETHUSDT",
    "SOL/USD": "SOLUSDT",
    "ADA/USD": "ADAUSDT",
    "XRP/USD": "XRPUSDT",
    "LTC/USD": "LTCUSDT",
    "BCH/USD": "BCHUSDT",
    "DOT/USD": "DOTUSDT",
    "DOGE/USD": "DOGEUSDT",
}

_API_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
_CACHE_TTL_SEC = 30 * 60  # 30 min
_DB_PATH = "/app/data/macro.db"


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS binance_funding (
            symbol TEXT PRIMARY KEY,
            funding_rate REAL NOT NULL,
            funding_time TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        )
    """)
    con.commit()


def _fetch_binance(symbol: str) -> dict[str, Any] | None:
    """Call Binance API. Returns dict or None on error."""
    try:
        url = f"{_API_URL}?symbol={symbol}&limit=1"
        req = urllib.request.Request(url, headers={"User-Agent": "scalping-radar/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
            if isinstance(data, list) and data:
                return {
                    "symbol": symbol,
                    "rate": float(data[0]["fundingRate"]),
                    "time": int(data[0]["fundingTime"]),  # epoch ms
                }
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, KeyError) as e:
        logger.warning(f"binance_funding fetch {symbol} failed: {e}")
    return None


def refresh_all() -> dict[str, int]:
    """Fetch funding for ALL mapped pairs. Returns stats."""
    n_ok = 0
    n_fail = 0
    con = sqlite3.connect(_DB_PATH)
    _ensure_schema(con)
    now = datetime.now(timezone.utc).isoformat()
    for pair, sym in _PAIR_TO_BINANCE.items():
        data = _fetch_binance(sym)
        if not data:
            n_fail += 1
            continue
        funding_iso = datetime.fromtimestamp(data["time"] / 1000, timezone.utc).isoformat()
        con.execute(
            "INSERT OR REPLACE INTO binance_funding (symbol, funding_rate, funding_time, fetched_at) VALUES (?, ?, ?, ?)",
            (sym, data["rate"], funding_iso, now),
        )
        n_ok += 1
    con.commit()
    con.close()
    logger.info(f"binance_funding refresh: {n_ok} ok, {n_fail} fail")
    return {"ok": n_ok, "fail": n_fail}


def get_funding_rate(pair: str) -> dict[str, Any]:
    """Retourne le funding rate actuel pour cette pair.

    Returns dict :
        - rate : funding rate (float, 0.0001 = 0.01%)
        - funding_time : timestamp dernière publication Binance
        - fetched_at : quand on a fetché
        - is_fresh : True si fetched_at < 30 min
        - available : True si on a une valeur, False si pair non-crypto ou cache miss

    Ne fait PAS de fetch synchrone. Utilise uniquement le cache DB.
    Le refresh est fait par le scheduler (cron 30 min).
    """
    sym = _PAIR_TO_BINANCE.get(pair)
    if not sym:
        return {"available": False, "reason": "pair non mappée"}
    try:
        con = sqlite3.connect(_DB_PATH)
        con.row_factory = sqlite3.Row
        r = con.execute(
            "SELECT funding_rate, funding_time, fetched_at FROM binance_funding WHERE symbol=?",
            (sym,),
        ).fetchone()
        con.close()
        if not r:
            return {"available": False, "reason": "pas encore fetched"}
        fetched_at = datetime.fromisoformat(r["fetched_at"])
        age_sec = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        return {
            "available": True,
            "rate": r["funding_rate"],
            "funding_time": r["funding_time"],
            "fetched_at": r["fetched_at"],
            "is_fresh": age_sec < _CACHE_TTL_SEC,
            "age_sec": age_sec,
        }
    except Exception as e:
        logger.warning(f"binance_funding get_funding_rate {pair}: {e}")
        return {"available": False, "reason": f"db error: {e}"}


def get_features_for_setup(pair: str) -> dict[str, float]:
    """Extrait les features dérivées du funding rate pour le ML.

    Returns dict de features (0 si data indispo) :
        - funding_rate : valeur brute (0.0001 = 0.01% standard)
        - funding_extreme_positive : 1 si > 0.05% (longs surchargés)
        - funding_extreme_negative : 1 si < -0.02% (shorts surchargés)
        - funding_available : 1 si on a la data
    """
    d = get_funding_rate(pair)
    if not d.get("available") or not d.get("is_fresh"):
        return {
            "funding_rate": 0.0,
            "funding_extreme_positive": 0,
            "funding_extreme_negative": 0,
            "funding_available": 0,
        }
    rate = d["rate"]
    return {
        "funding_rate": rate,
        "funding_extreme_positive": 1 if rate > 0.0005 else 0,
        "funding_extreme_negative": 1 if rate < -0.0002 else 0,
        "funding_available": 1,
    }
