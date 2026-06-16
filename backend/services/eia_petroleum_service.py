"""EIA Weekly Petroleum Status → feature ML WTI.

Le mercredi à 10h30 ET (= 14h30/15h30 UTC selon DST) l'EIA publie le rapport
hebdo : crude oil stocks, gasoline stocks, distillate stocks.

Effet typique sur WTI :
- Stocks crude EN HAUSSE (build) ≈ baisse demande → bearish WTI
- Stocks crude EN BAISSE (draw) ≈ forte demande → bullish WTI
- Surprise vs consensus = mouvement +/-1% sur les minutes qui suivent

Source : EIA OpenData v2 (free API key signup required).
Sans clé : on a quand même la feature `is_eia_window` qui marque la
plage horaire à risque (Wed 14:00-16:30 UTC).

Cache 6h en macro.db (les data sont hebdo, refresh généreux suffit).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_TTL_SEC = 6 * 3600  # 6 heures
_DB_PATH = "/app/data/macro.db"
_API_URL = "https://api.eia.gov/v2/seriesid/{series_id}?api_key={key}&length=2&sort[0][column]=period&sort[0][direction]=desc"

# Series EIA : Crude oil stocks (excluding SPR) + Gasoline stocks
_SERIES = {
    "crude": "PET.WCESTUS1.W",       # Weekly Ending Stocks of Crude Oil
    "gasoline": "PET.WGFSTUS1.W",    # Weekly Ending Stocks of Gasoline
}


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS eia_petroleum (
            series TEXT PRIMARY KEY,
            value REAL NOT NULL,
            prev_value REAL,
            delta REAL,
            period TEXT,
            fetched_at TEXT NOT NULL
        )
    """)
    con.commit()


def _fetch_series(series_id: str, api_key: str) -> dict[str, Any] | None:
    try:
        url = _API_URL.format(series_id=series_id, key=api_key)
        req = urllib.request.Request(url, headers={"User-Agent": "scalping-radar/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        series = data.get("response", {}).get("data", [])
        if len(series) < 2:
            return None
        latest = series[0]
        prev = series[1]
        val = float(latest["value"])
        prev_val = float(prev["value"])
        return {
            "value": val,
            "prev_value": prev_val,
            "delta": val - prev_val,
            "period": latest["period"],
        }
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, KeyError, IndexError) as e:
        logger.warning(f"eia fetch {series_id} failed: {e}")
        return None


def refresh_all() -> dict[str, int]:
    """Fetch tous les séries EIA. No-op si pas de clé API.

    Pour activer : créer une clé gratuite sur https://www.eia.gov/opendata/register.php
    puis EIA_API_KEY=xxx dans .env EC2 + restart.
    """
    api_key = os.getenv("EIA_API_KEY", "").strip()
    if not api_key:
        logger.info("eia refresh: EIA_API_KEY non configuré, skip")
        return {"ok": 0, "fail": 0, "reason": "no_key"}
    n_ok, n_fail = 0, 0
    con = sqlite3.connect(_DB_PATH)
    _ensure_schema(con)
    now = datetime.now(timezone.utc).isoformat()
    for short, series_id in _SERIES.items():
        d = _fetch_series(series_id, api_key)
        if not d:
            n_fail += 1
            continue
        con.execute(
            "INSERT OR REPLACE INTO eia_petroleum (series, value, prev_value, delta, period, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
            (short, d["value"], d["prev_value"], d["delta"], d["period"], now),
        )
        n_ok += 1
    con.commit()
    con.close()
    logger.info(f"eia refresh: {n_ok} ok, {n_fail} fail")
    return {"ok": n_ok, "fail": n_fail}


def get_petroleum() -> dict[str, Any]:
    """Retourne dict avec dernier crude/gasoline + delta hebdo."""
    out: dict[str, Any] = {"available": False}
    try:
        con = sqlite3.connect(_DB_PATH)
        con.row_factory = sqlite3.Row
        for short in _SERIES.keys():
            r = con.execute(
                "SELECT value, prev_value, delta, period, fetched_at FROM eia_petroleum WHERE series=?",
                (short,),
            ).fetchone()
            if not r:
                continue
            out[short] = {
                "value": r["value"],
                "prev_value": r["prev_value"],
                "delta": r["delta"],
                "period": r["period"],
                "fetched_at": r["fetched_at"],
            }
            out["available"] = True
        con.close()
    except Exception as e:
        logger.warning(f"eia get_petroleum: {e}")
    return out


def is_eia_window(dt: datetime | None = None) -> bool:
    """True si on est dans la plage horaire EIA (Mer 14:00-16:30 UTC).

    Plage volontairement large pour absorber le shift DST + la queue
    immédiate du report.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.weekday() != 2:  # Wednesday
        return False
    minutes = dt.hour * 60 + dt.minute
    return 14 * 60 <= minutes <= 16 * 60 + 30


def get_features(pair: str) -> dict[str, float]:
    """Features EIA pour le ML (pertinentes uniquement pour WTI/USD)."""
    is_wti = pair in ("WTI/USD", "BRENT/USD")
    in_window = is_eia_window()
    base = {
        "eia_is_wti": 1 if is_wti else 0,
        "eia_in_wednesday_window": 1 if in_window else 0,
        "eia_wti_in_window": 1 if (is_wti and in_window) else 0,
    }
    if not is_wti:
        # Pour les non-WTI on retourne juste les flags
        base.update({
            "eia_crude_delta_pct": 0.0,
            "eia_gasoline_delta_pct": 0.0,
            "eia_crude_build": 0,
            "eia_crude_draw": 0,
            "eia_available": 0,
        })
        return base
    pet = get_petroleum()
    crude = pet.get("crude") or {}
    gasoline = pet.get("gasoline") or {}
    crude_val = crude.get("value") or 0
    crude_delta = crude.get("delta") or 0
    crude_delta_pct = (crude_delta / crude_val * 100) if crude_val else 0
    gas_val = gasoline.get("value") or 0
    gas_delta = gasoline.get("delta") or 0
    gas_delta_pct = (gas_delta / gas_val * 100) if gas_val else 0
    base.update({
        "eia_crude_delta_pct": crude_delta_pct,
        "eia_gasoline_delta_pct": gas_delta_pct,
        "eia_crude_build": 1 if crude_delta > 0 else 0,  # bearish WTI
        "eia_crude_draw": 1 if crude_delta < 0 else 0,   # bullish WTI
        "eia_available": 1 if pet.get("available") else 0,
    })
    return base
