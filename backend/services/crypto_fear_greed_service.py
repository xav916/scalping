"""Alternative.me Crypto Fear & Greed Index → feature ML cryptos.

Distinct du CNN F&G (qui couvre actions US). Source dédiée crypto :
https://alternative.me/crypto/fear-and-greed-index/

Composite 0-100 quotidien :
- 0-25  : Extreme Fear → souvent fond, contrarien long
- 25-49 : Fear
- 50-74 : Greed
- 75-100: Extreme Greed → top probable, contrarien short

Source : api.alternative.me, gratuit, no auth. Mise à jour quotidienne.
Cache 1h en macro.db (refresh généreux suffit).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import urllib.request
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_API_URL = "https://api.alternative.me/fng/?limit=1"
_DB_PATH = "/app/data/macro.db"


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS crypto_fear_greed (
            id INTEGER PRIMARY KEY,
            value INTEGER NOT NULL,
            classification TEXT,
            fetched_at TEXT NOT NULL
        )
    """)
    con.commit()


def refresh() -> dict[str, Any] | None:
    try:
        req = urllib.request.Request(_API_URL, headers={"User-Agent": "scalping-radar/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read())
        latest = d["data"][0]
        val = int(latest["value"])
        classif = latest["value_classification"]
        con = sqlite3.connect(_DB_PATH)
        _ensure_schema(con)
        con.execute("DELETE FROM crypto_fear_greed")
        con.execute(
            "INSERT INTO crypto_fear_greed (value, classification, fetched_at) VALUES (?, ?, ?)",
            (val, classif, datetime.now(timezone.utc).isoformat()),
        )
        con.commit()
        con.close()
        logger.info(f"crypto F&G refresh: {val} ({classif})")
        return {"value": val, "classification": classif}
    except Exception as e:
        logger.warning(f"crypto F&G refresh failed: {e}")
        return None


def get_features(pair: str) -> dict[str, float]:
    is_crypto = any(k in pair.upper() for k in ("BTC", "ETH", "SOL", "ADA", "XRP", "LTC", "BCH", "DOT", "DOGE"))
    if not is_crypto:
        return {
            "cfg_value": 0, "cfg_extreme_fear": 0, "cfg_fear": 0,
            "cfg_greed": 0, "cfg_extreme_greed": 0, "cfg_available": 0,
        }
    try:
        con = sqlite3.connect(_DB_PATH)
        con.row_factory = sqlite3.Row
        r = con.execute(
            "SELECT value, fetched_at FROM crypto_fear_greed ORDER BY id DESC LIMIT 1"
        ).fetchone()
        con.close()
        if not r:
            return {"cfg_value": 0, "cfg_extreme_fear": 0, "cfg_fear": 0,
                    "cfg_greed": 0, "cfg_extreme_greed": 0, "cfg_available": 0}
        v = r["value"]
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(r["fetched_at"])).total_seconds()
        if age > 172800:  # >2 jours
            return {"cfg_value": 0, "cfg_extreme_fear": 0, "cfg_fear": 0,
                    "cfg_greed": 0, "cfg_extreme_greed": 0, "cfg_available": 0}
        return {
            "cfg_value": v,
            "cfg_extreme_fear": 1 if v < 25 else 0,
            "cfg_fear": 1 if 25 <= v < 50 else 0,
            "cfg_greed": 1 if 50 <= v < 75 else 0,
            "cfg_extreme_greed": 1 if v >= 75 else 0,
            "cfg_available": 1,
        }
    except Exception as e:
        logger.warning(f"crypto F&G get_features: {e}")
        return {"cfg_value": 0, "cfg_extreme_fear": 0, "cfg_fear": 0,
                "cfg_greed": 0, "cfg_extreme_greed": 0, "cfg_available": 0}
