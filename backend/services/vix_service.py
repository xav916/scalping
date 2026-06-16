"""VIX (CBOE Volatility Index) → feature ML.

VIX = thermomètre stress equity US. Drive SPX à 90 % en corrélation négative.
Au-dessus de 25-30 : régime risk-off, favorise shorts equity + cryptos.
En-dessous de 15 : complaisance, favorise mean-reversion.

Source : Stooq (CSV public, pas d'auth) — fallback Yahoo Finance.
Cache 5 min en macro.db.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_TTL_SEC = 5 * 60  # 5 min
_DB_PATH = "/app/data/macro.db"
_STOOQ_URL = "https://stooq.com/q/?s=^vix&i=d&l=2"  # last 2 daily candles CSV
_YAHOO_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/^VIX"
    "?interval=1d&range=5d"
)


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS vix_snapshot (
            id INTEGER PRIMARY KEY,
            value REAL NOT NULL,
            change_pct REAL,
            source TEXT,
            fetched_at TEXT NOT NULL
        )
    """)
    # Garde uniquement le dernier
    con.commit()


def _fetch_yahoo() -> dict[str, Any] | None:
    try:
        req = urllib.request.Request(
            _YAHOO_URL,
            headers={"User-Agent": "Mozilla/5.0 scalping-radar/1.0"},
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        result = data["chart"]["result"][0]
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
        if len(closes) < 2:
            return None
        current = closes[-1]
        prev = closes[-2]
        change_pct = (current - prev) / prev * 100 if prev else 0
        return {"value": current, "change_pct": change_pct, "source": "yahoo"}
    except Exception as e:
        logger.warning(f"vix yahoo fetch failed: {e}")
        return None


def refresh() -> dict[str, Any] | None:
    """Fetch VIX + persist. Returns the new snapshot or None on fail."""
    data = _fetch_yahoo()
    if not data:
        logger.warning("vix refresh: all sources failed")
        return None
    con = sqlite3.connect(_DB_PATH)
    _ensure_schema(con)
    now = datetime.now(timezone.utc).isoformat()
    # On garde uniquement le dernier point pour simplifier
    con.execute("DELETE FROM vix_snapshot")
    con.execute(
        "INSERT INTO vix_snapshot (value, change_pct, source, fetched_at) VALUES (?, ?, ?, ?)",
        (data["value"], data["change_pct"], data["source"], now),
    )
    con.commit()
    con.close()
    logger.info(
        f"vix refresh: {data['value']:.2f} ({data['change_pct']:+.1f}%) src={data['source']}"
    )
    return data


def get_current() -> dict[str, Any]:
    """Lit le cache (sans fetch). Retourne dict avec available flag."""
    try:
        con = sqlite3.connect(_DB_PATH)
        con.row_factory = sqlite3.Row
        r = con.execute(
            "SELECT value, change_pct, fetched_at FROM vix_snapshot ORDER BY id DESC LIMIT 1"
        ).fetchone()
        con.close()
        if not r:
            return {"available": False, "reason": "no data"}
        fetched_at = datetime.fromisoformat(r["fetched_at"])
        age_sec = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        return {
            "available": True,
            "value": r["value"],
            "change_pct": r["change_pct"],
            "fetched_at": r["fetched_at"],
            "age_sec": age_sec,
            "is_fresh": age_sec < _CACHE_TTL_SEC,
        }
    except Exception as e:
        logger.warning(f"vix get_current: {e}")
        return {"available": False, "reason": str(e)}


def get_features() -> dict[str, float]:
    """Features VIX pour le ML (utilisables sur tous les actifs).

    Buckets :
    - vix_low (<15)       : complaisance, mean-reversion favorable
    - vix_medium (15-25)  : normal
    - vix_high (25-35)    : stress modéré, risk-off
    - vix_extreme (>35)   : panique, mouvements amplifiés
    """
    d = get_current()
    if not d.get("available") or not d.get("is_fresh"):
        return {
            "vix_value": 0.0, "vix_change_pct": 0.0,
            "vix_low": 0, "vix_medium": 0, "vix_high": 0, "vix_extreme": 0,
            "vix_available": 0,
        }
    v = d["value"]
    return {
        "vix_value": v,
        "vix_change_pct": d.get("change_pct") or 0.0,
        "vix_low": 1 if v < 15 else 0,
        "vix_medium": 1 if 15 <= v < 25 else 0,
        "vix_high": 1 if 25 <= v < 35 else 0,
        "vix_extreme": 1 if v >= 35 else 0,
        "vix_available": 1,
    }
