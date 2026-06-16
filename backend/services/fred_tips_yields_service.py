"""FRED Real Yields TIPS 10Y → feature ML métaux (XAU/XAG).

Real yields (Treasury Inflation-Protected Securities 10 ans) corrèlent à
-85 % avec l'or. Quand les real yields montent → l'or perd attrait (yieldless
asset). Quand ils baissent → or attractif.

Source : FRED CSV public (St. Louis Fed), no auth nécessaire.
URL : https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10

Mise à jour : daily, en fin de session NY (~22h UTC).
Cache 12h.
"""
from __future__ import annotations

import csv
import io
import logging
import sqlite3
import urllib.request
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10"
_DB_PATH = "/app/data/macro.db"


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS fred_tips_yields (
            id INTEGER PRIMARY KEY,
            yield_pct REAL NOT NULL,
            prev_yield_pct REAL,
            delta_bp REAL,
            period TEXT,
            fetched_at TEXT NOT NULL
        )
    """)
    con.commit()


def refresh() -> dict[str, Any] | None:
    try:
        req = urllib.request.Request(_CSV_URL, headers={"User-Agent": "scalping-radar/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            text = r.read().decode("utf-8")
        rows = list(csv.reader(io.StringIO(text)))
        # 1ere ligne = header, suivantes = (date, value). Garde uniquement valeurs numériques.
        data = [(r[0], r[1]) for r in rows[1:] if len(r) >= 2 and r[1] not in (".", "")]
        if len(data) < 2:
            return None
        latest_period, latest_val = data[-1]
        prev_period, prev_val = data[-2]
        y = float(latest_val)
        py = float(prev_val)
        delta_bp = (y - py) * 100  # convert pct points → basis points
        con = sqlite3.connect(_DB_PATH)
        _ensure_schema(con)
        con.execute("DELETE FROM fred_tips_yields")
        con.execute(
            "INSERT INTO fred_tips_yields (yield_pct, prev_yield_pct, delta_bp, period, fetched_at) VALUES (?, ?, ?, ?, ?)",
            (y, py, delta_bp, latest_period, datetime.now(timezone.utc).isoformat()),
        )
        con.commit()
        con.close()
        logger.info(
            f"fred_tips_yields refresh: {y:.3f}% (delta {delta_bp:+.1f}bp vs {prev_period})"
        )
        return {"yield_pct": y, "delta_bp": delta_bp, "period": latest_period}
    except Exception as e:
        logger.warning(f"fred_tips_yields refresh failed: {e}")
        return None


def get_features(pair: str) -> dict[str, float]:
    """Pertinent surtout pour XAU/USD et XAG/USD (or et argent)."""
    is_metal = any(k in pair.upper() for k in ("XAU", "XAG", "XPT", "XPD"))
    if not is_metal:
        return {
            "tips_yield": 0, "tips_delta_bp": 0,
            "tips_high_yield": 0, "tips_low_yield": 0, "tips_available": 0,
        }
    try:
        con = sqlite3.connect(_DB_PATH)
        con.row_factory = sqlite3.Row
        r = con.execute(
            "SELECT yield_pct, delta_bp, fetched_at FROM fred_tips_yields ORDER BY id DESC LIMIT 1"
        ).fetchone()
        con.close()
        if not r:
            return {"tips_yield": 0, "tips_delta_bp": 0,
                    "tips_high_yield": 0, "tips_low_yield": 0, "tips_available": 0}
        y = r["yield_pct"]
        return {
            "tips_yield": y,
            "tips_delta_bp": r["delta_bp"] or 0,
            "tips_high_yield": 1 if y > 2.0 else 0,  # bearish or
            "tips_low_yield": 1 if y < 0.5 else 0,   # bullish or
            "tips_available": 1,
        }
    except Exception as e:
        logger.warning(f"fred_tips_yields get_features: {e}")
        return {"tips_yield": 0, "tips_delta_bp": 0,
                "tips_high_yield": 0, "tips_low_yield": 0, "tips_available": 0}
