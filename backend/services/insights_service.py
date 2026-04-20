"""Service d'analyse de performance des trades auto.

Agrège `personal_trades` (is_auto=1, status='CLOSED', pnl NOT NULL) pour
éclairer les décisions pending :
- Remontée de MT5_BRIDGE_MIN_CONFIDENCE (bucket by_score_bucket)
- Activation de MACRO_VETO_ENABLED (bucket by_macro_risk_regime)
- Tuning stratégie (pattern/direction/asset_class/session)
"""

import json
import sqlite3
from typing import Any


_SCORE_BUCKETS = [
    (0, 55, "0-55"),
    (55, 65, "55-65"),
    (65, 75, "65-75"),
    (75, 85, "75-85"),
    (85, 101, "85-100"),
]

_SESSIONS_UTC = [
    (22, 7, "Sydney"),
    (0, 9, "Tokyo"),
    (8, 17, "London"),
    (13, 22, "New York"),
]


def _db_path() -> str:
    from backend.services.trade_log_service import _DB_PATH
    return str(_DB_PATH)


def _pair_asset_class(pair: str) -> str:
    """Dérive l'asset class depuis la paire (réplique de config.settings
    mais sans dépendance pour éviter un cycle d'import)."""
    from config.settings import asset_class_for
    return asset_class_for(pair)


def _session_for_hour(hour_utc: int) -> str:
    """Retourne la session principale pour une heure UTC donnée.
    Simplifié : une seule session (la plus active) — overlap London/NY
    rangé dans London pour lisibilité."""
    if 13 <= hour_utc < 17:
        return "London/NY overlap"
    if 8 <= hour_utc < 13:
        return "London"
    if 17 <= hour_utc < 22:
        return "New York"
    if 0 <= hour_utc < 8:
        return "Tokyo"
    return "Sydney"


def _score_bucket(score: float | None) -> str | None:
    if score is None:
        return None
    for lo, hi, label in _SCORE_BUCKETS:
        if lo <= score < hi:
            return label
    return None


def _aggregate(rows: list[dict[str, Any]], key_func) -> list[dict[str, Any]]:
    """Groupe les trades par clé et calcule les stats."""
    groups: dict[str, list[dict]] = {}
    for r in rows:
        key = key_func(r)
        if key is None:
            continue
        groups.setdefault(key, []).append(r)

    out = []
    for key, trades in groups.items():
        n = len(trades)
        wins = sum(1 for t in trades if (t.get("pnl") or 0) > 0)
        pnls = [t.get("pnl") or 0 for t in trades]
        total = sum(pnls)
        avg = total / n if n else 0
        out.append({
            "bucket": key,
            "count": n,
            "wins": wins,
            "win_rate": round(wins / n, 3) if n else 0,
            "total_pnl": round(total, 2),
            "avg_pnl": round(avg, 2),
        })
    out.sort(key=lambda x: x["bucket"])
    return out


def get_performance(since_iso: str | None = None) -> dict[str, Any]:
    """Retourne un snapshot agrégé pour analyse.

    Args:
        since_iso: filtre created_at >= cette date ISO (défaut: tout).
    """
    sql = (
        "SELECT pair, direction, signal_confidence, pnl, created_at, closed_at, "
        "exit_price, entry_price, context_macro "
        "FROM personal_trades "
        "WHERE is_auto=1 AND status='CLOSED' AND pnl IS NOT NULL"
    )
    params: list[Any] = []
    if since_iso:
        sql += " AND created_at >= ?"
        params.append(since_iso)

    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        rows = [dict(r) for r in c.execute(sql, params).fetchall()]

    if not rows:
        return {
            "total_trades": 0,
            "message": "pas de trades CLOSED à analyser pour cette période",
            "since": since_iso,
        }

    # Enrichir chaque ligne avec les dimensions dérivées
    for r in rows:
        r["asset_class"] = _pair_asset_class(r.get("pair") or "")
        r["score_bucket"] = _score_bucket(r.get("signal_confidence"))
        try:
            created = r.get("created_at") or ""
            hour = int(created[11:13]) if len(created) >= 13 else 0
            r["session"] = _session_for_hour(hour)
        except (ValueError, IndexError):
            r["session"] = None
        try:
            ctx = json.loads(r.get("context_macro") or "{}")
            r["risk_regime"] = ctx.get("risk_regime")
        except (json.JSONDecodeError, TypeError):
            r["risk_regime"] = None

    # Global stats
    n = len(rows)
    wins = sum(1 for r in rows if (r.get("pnl") or 0) > 0)
    total_pnl = sum(r.get("pnl") or 0 for r in rows)
    losses_pnl = sum(min(0, r.get("pnl") or 0) for r in rows)

    return {
        "total_trades": n,
        "win_rate": round(wins / n, 3) if n else 0,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(total_pnl / n, 2) if n else 0,
        "total_losses": round(losses_pnl, 2),
        "since": since_iso,
        "by_score_bucket": _aggregate(rows, lambda r: r.get("score_bucket")),
        "by_asset_class": _aggregate(rows, lambda r: r.get("asset_class")),
        "by_direction": _aggregate(rows, lambda r: r.get("direction")),
        "by_risk_regime": _aggregate(rows, lambda r: r.get("risk_regime")),
        "by_session": _aggregate(rows, lambda r: r.get("session")),
        "by_pair": _aggregate(rows, lambda r: r.get("pair")),
    }
