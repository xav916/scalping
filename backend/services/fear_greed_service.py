"""CNN Fear & Greed Index : indicateur synthetique de sentiment marche.

CNN publie un indice 0-100 compose de 7 sous-indicateurs :
- Market momentum (S&P vs MA125)
- Stock price strength (nouveaux highs/lows NYSE)
- Stock price breadth (advance/decline)
- Put/Call ratio (options)
- Market volatility (VIX)
- Safe haven demand (stocks vs bonds 20j)
- Junk bond demand (yield spread HY vs IG)

Interpretation :
- 0-25   : extreme_fear   (opportunité contrarienne bull potentielle)
- 25-45  : fear
- 45-55  : neutral
- 55-75  : greed
- 75-100 : extreme_greed  (sommet probable, contrarien bear)

Endpoint public utilisé par le site CNN (pas d'auth, pas de rate limit
documenté — on reste raisonnable : 1 fetch / jour suffit). Si CNN change
l'endpoint, le service tombe gracieusement (None).

Integration : le snapshot actuel est affiche dans le cockpit.
**Pas encore branche** au sizing (eviter de sur-opt sans donnees
validees).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


CNN_ENDPOINT = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

# Thresholds CNN officiels pour le labelling.
_THRESHOLDS = [
    (25, "extreme_fear"),
    (45, "fear"),
    (55, "neutral"),
    (75, "greed"),
    (100, "extreme_greed"),
]


def _db_path() -> Path:
    from backend.services.trade_log_service import _DB_PATH
    return _DB_PATH


@contextmanager
def _conn():
    conn = sqlite3.connect(str(_db_path()), isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _init_schema() -> None:
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS fear_greed_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at TEXT NOT NULL,
                value REAL NOT NULL,
                classification TEXT NOT NULL,
                raw TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_fg_recorded
                ON fear_greed_snapshots(recorded_at);
        """)


def classify(value: float) -> str:
    """Map une valeur 0-100 vers un label CNN officiel."""
    for threshold, label in _THRESHOLDS:
        if value < threshold:
            return label
    return "extreme_greed"


async def fetch_latest() -> dict | None:
    """Pull CNN + stocke le snapshot. Retourne None en cas d'echec reseau
    ou parsing. Best-effort pour ne jamais casser le scheduler."""
    headers = {
        # CNN renvoie 403 sans User-Agent "humain".
        "User-Agent": (
            "Mozilla/5.0 (compatible; ScalpingRadar/1.0; contact via github)"
        ),
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(CNN_ENDPOINT, headers=headers)
            if r.status_code != 200:
                logger.warning(f"fear_greed: CNN {r.status_code}")
                return None
            data = r.json()
    except Exception as e:
        logger.warning(f"fear_greed: fetch failed: {e}")
        return None

    # La payload CNN change de schema de temps en temps — on cherche
    # defensivement les champs habituels.
    try:
        value = float(data["fear_and_greed"]["score"])
    except Exception:
        logger.warning("fear_greed: unexpected payload structure")
        return None

    label = classify(value)
    snap = {
        "value": round(value, 1),
        "classification": label,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        _init_schema()
        with _conn() as c:
            c.execute(
                "INSERT INTO fear_greed_snapshots "
                "(recorded_at, value, classification, raw) VALUES (?, ?, ?, ?)",
                (snap["recorded_at"], snap["value"], label, json.dumps(data)[:2000]),
            )
    except Exception as e:
        logger.warning(f"fear_greed: store failed: {e}")

    return snap


def get_current() -> dict | None:
    """Dernier snapshot connu en base (sans refetch)."""
    try:
        _init_schema()
        with _conn() as c:
            row = c.execute(
                "SELECT recorded_at, value, classification "
                "FROM fear_greed_snapshots "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
    except Exception as e:
        logger.debug(f"fear_greed: get_current failed: {e}")
        return None
    if not row:
        return None
    return {
        "recorded_at": row["recorded_at"],
        "value": row["value"],
        "classification": row["classification"],
    }


def is_extreme() -> bool:
    """Raccourci pour les alertes : current in (extreme_fear, extreme_greed)."""
    current = get_current()
    if not current:
        return False
    return current["classification"] in ("extreme_fear", "extreme_greed")
