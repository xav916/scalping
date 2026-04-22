"""Journal des rejections de signaux auto-exec.

Chaque fois qu'un setup éligible (score ≥ seuil, etc.) est bloqué avant
l'exécution MT5 — que ce soit par un garde-fou local (market hours, SL
trop serré, kill-switch...) ou par le bridge (rc=10016, 429 max positions,
timeout...) — on enregistre une ligne.

Sert à la carte RejectionsCard du cockpit pour visualiser d'où viennent
les ordres perdus.
"""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


# Codes de raison canoniques. Un seul par rejection pour simplifier la viz.
# - kill_switch : coupure manuelle ou par perte journalière atteinte
# - event_blackout : fenêtre +/-15min autour d'un event high-impact
# - simulated_data : fallback price_service (bug historique, fix 69df7f1)
# - verdict_blocker : blockers durs du verdict (VIX, holiday, etc.)
# - market_closed : pair fermée (weekends, daily break métal, etc.)
# - sl_too_close : distance SL inférieure au seuil MIN_SL_DISTANCE_PCT
# - below_confidence : score < MT5_BRIDGE_MIN_CONFIDENCE
# - asset_class_blocked : broker actuel ne supporte pas cette classe
# - bridge_max_positions : bridge renvoie 429 (max_open_positions)
# - bridge_invalid_stops : bridge renvoie erreur rc=10016
# - bridge_error : autre erreur bridge (status ≠ 200)
# - bridge_timeout : bridge injoignable (PC éteint, Tailscale down)

REASON_LABELS_FR = {
    "kill_switch": "Kill switch actif",
    "event_blackout": "Blackout event macro",
    "simulated_data": "Données simulées",
    "verdict_blocker": "Verdict bloqué",
    "market_closed": "Marché fermé",
    "sl_too_close": "SL trop serré",
    "below_confidence": "Confiance < seuil",
    "asset_class_blocked": "Classe d'actif bloquée",
    "bridge_max_positions": "Cap positions bridge",
    "bridge_invalid_stops": "Bridge : stops invalides",
    "bridge_error": "Bridge : erreur autre",
    "bridge_timeout": "Bridge injoignable",
}


def _db_path() -> str:
    from backend.services.trade_log_service import _DB_PATH
    return str(_DB_PATH)


def _ensure_schema() -> None:
    with sqlite3.connect(_db_path()) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS signal_rejections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                pair TEXT,
                direction TEXT,
                confidence REAL,
                reason_code TEXT NOT NULL,
                details TEXT
            )
        """)
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_sr_created ON signal_rejections(created_at)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_sr_reason ON signal_rejections(reason_code)"
        )


def record_rejection(
    pair: str | None,
    direction: str | None,
    confidence: float | None,
    reason_code: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Enregistre une ligne dans `signal_rejections`. Best-effort : toute
    erreur DB est silencieusement avalée pour ne pas planter le pipeline."""
    try:
        _ensure_schema()
        with sqlite3.connect(_db_path()) as c:
            c.execute(
                """
                INSERT INTO signal_rejections
                    (created_at, pair, direction, confidence, reason_code, details)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    pair,
                    direction,
                    confidence,
                    reason_code,
                    json.dumps(details) if details else None,
                ),
            )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("record_rejection failed (silencé)")


def get_rejections(since: str, until: str) -> dict[str, Any]:
    """Agrège les rejections pour la RejectionsCard.

    Retourne :
        {
          "total": int,
          "by_reason": [{reason_code, label_fr, count, top_pair}, ...],
          "by_hour_utc": [{hour: 0..23, count}, ...],  # 24 entrées exactes
          "by_reason_hour": [[reason_code, hour, count], ...],  # pour heatmap
          "since": str,
          "until": str,
        }
    """
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            """
            SELECT created_at, pair, reason_code
              FROM signal_rejections
             WHERE created_at >= ? AND created_at <= ?
            """,
            (since, until),
        ).fetchall()

    by_reason: dict[str, dict[str, Any]] = {}
    by_hour_count: dict[int, int] = {h: 0 for h in range(24)}
    by_reason_hour: dict[tuple[str, int], int] = {}

    for r in rows:
        reason = r["reason_code"]
        pair = r["pair"] or "UNKNOWN"
        try:
            hour = int(r["created_at"][11:13])
        except (ValueError, IndexError):
            hour = 0

        entry = by_reason.setdefault(reason, {"count": 0, "pairs": {}})
        entry["count"] += 1
        entry["pairs"][pair] = entry["pairs"].get(pair, 0) + 1

        by_hour_count[hour] = by_hour_count.get(hour, 0) + 1
        key = (reason, hour)
        by_reason_hour[key] = by_reason_hour.get(key, 0) + 1

    by_reason_list = []
    for reason, v in sorted(by_reason.items(), key=lambda kv: -kv[1]["count"]):
        top_pair = max(v["pairs"].items(), key=lambda kv: kv[1])[0] if v["pairs"] else None
        by_reason_list.append({
            "reason_code": reason,
            "label_fr": REASON_LABELS_FR.get(reason, reason),
            "count": v["count"],
            "pairs": v["pairs"],
            "top_pair": top_pair,
        })

    return {
        "total": len(rows),
        "by_reason": by_reason_list,
        "by_hour_utc": [{"hour": h, "count": c} for h, c in sorted(by_hour_count.items())],
        "by_reason_hour": [
            {"reason_code": r, "hour": h, "count": c}
            for (r, h), c in by_reason_hour.items()
        ],
        "since": since,
        "until": until,
    }
