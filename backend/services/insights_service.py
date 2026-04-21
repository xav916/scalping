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


def get_equity_curve(since_iso: str | None = None) -> dict[str, Any]:
    """Série temporelle du PnL cumulé, trade par trade (chronologique).

    Format retourné : liste de points {closed_at, pnl, cumulative_pnl, trade_num}.
    Permet de tracer une equity curve côté UI (sparkline ou chart complet).
    """
    sql = (
        "SELECT closed_at, pnl, pair, direction "
        "FROM personal_trades "
        "WHERE is_auto=1 AND status='CLOSED' AND pnl IS NOT NULL "
        "AND closed_at IS NOT NULL"
    )
    params: list[Any] = []
    if since_iso:
        sql += " AND closed_at >= ?"
        params.append(since_iso)
    sql += " ORDER BY closed_at ASC"

    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        rows = [dict(r) for r in c.execute(sql, params).fetchall()]

    if not rows:
        return {"points": [], "total_trades": 0, "final_pnl": 0, "since": since_iso}

    points = []
    cumulative = 0.0
    for i, r in enumerate(rows):
        pnl = float(r.get("pnl") or 0)
        cumulative += pnl
        points.append({
            "closed_at": r.get("closed_at"),
            "pnl": round(pnl, 2),
            "cumulative_pnl": round(cumulative, 2),
            "trade_num": i + 1,
            "pair": r.get("pair"),
            "direction": r.get("direction"),
        })

    return {
        "points": points,
        "total_trades": len(points),
        "final_pnl": round(cumulative, 2),
        "since": since_iso,
    }


def _period_window(period: str) -> tuple[str, str]:
    """Calcule la fenêtre [since, until] en ISO UTC pour une période.
    
    Périodes supportées :
    - 'day'   : depuis 00:00 UTC aujourd'hui
    - 'week'  : depuis lundi 00:00 UTC de la semaine en cours
    - 'month' : depuis le 1er du mois 00:00 UTC
    - 'year'  : depuis le 1er janvier 00:00 UTC
    - 'all'   : depuis POST_FIX_CUTOFF (pipeline fiabilisé)
    """
    from datetime import datetime, timezone, timedelta
    
    now = datetime.now(timezone.utc)
    until = now.isoformat()
    
    if period == "day":
        since_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        days_since_monday = now.weekday()
        since_dt = (now - timedelta(days=days_since_monday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif period == "month":
        since_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif period == "year":
        since_dt = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:  # 'all'
        # POST_FIX_CUTOFF hardcodé ici pour éviter de dépendre du front
        return ("2026-04-20T21:14:00+00:00", until)
    
    return (since_dt.isoformat(), until)


def get_period_stats(period: str = "day") -> dict:
    """Métriques consolidées pour une période : PnL, win rate, profit factor,
    expectancy, max drawdown, best/worst trade, durée moyenne, distribution
    close_reason.
    
    Source : personal_trades WHERE status='CLOSED' AND is_auto=1 AND closed_at in [since, until].
    """
    from config.settings import TRADING_CAPITAL
    
    since, until = _period_window(period)
    
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        trades_rows = c.execute(
            """
            SELECT pair, direction, pnl, created_at, closed_at, close_reason, size_lot
              FROM personal_trades
             WHERE status = 'CLOSED'
               AND is_auto = 1
               AND pnl IS NOT NULL
               AND closed_at >= ?
               AND closed_at <= ?
             ORDER BY closed_at ASC
            """,
            (since, until),
        ).fetchall()
        
        # Trades encore ouverts au moment du calcul (pour afficher capital engagé)
        open_rows = c.execute(
            """
            SELECT pair, entry_price, stop_loss, size_lot
              FROM personal_trades
             WHERE status = 'OPEN' AND is_auto = 1
            """
        ).fetchall()
    
    trades = [dict(r) for r in trades_rows]
    opens = [dict(r) for r in open_rows]
    
    # Capital à risque instantané (somme de |entry - SL| * units * size)
    def _units(pair: str) -> float:
        base = pair.split("/")[0].upper() if "/" in pair else pair.upper()
        if base in {"XAU", "XAG", "XPT", "XPD"}:
            return 100.0
        return 100_000.0
    
    capital_at_risk = 0.0
    for o in opens:
        sl = o.get("stop_loss")
        if sl is None:
            continue
        units = _units(o["pair"]) * (o.get("size_lot") or 0)
        capital_at_risk += abs(o["entry_price"] - sl) * units
    
    if not trades:
        return {
            "period": period,
            "from": since,
            "to": until,
            "pnl": 0.0,
            "pnl_pct": 0.0,
            "capital": TRADING_CAPITAL,
            "capital_at_risk_now": round(capital_at_risk, 2),
            "n_trades": 0,
            "n_wins": 0,
            "n_losses": 0,
            "win_rate": 0.0,
            "avg_pnl_per_trade": 0.0,
            "profit_factor": None,
            "expectancy": 0.0,
            "max_drawdown": 0.0,
            "best_trade": None,
            "worst_trade": None,
            "avg_duration_min": None,
            "close_reasons": {},
            "n_open": len(opens),
        }
    
    pnls = [float(t["pnl"] or 0) for t in trades]
    total_pnl = sum(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else None
    
    # Max drawdown : perte max cumulée depuis un sommet de la courbe d'équité
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cumulative += p
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    
    # Best/worst trade
    best = max(trades, key=lambda t: t["pnl"])
    worst = min(trades, key=lambda t: t["pnl"])
    
    # Durée moyenne
    from datetime import datetime
    durations = []
    for t in trades:
        try:
            start = datetime.fromisoformat(t["created_at"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(t["closed_at"].replace("Z", "+00:00"))
            durations.append((end - start).total_seconds() / 60)
        except Exception:
            pass
    avg_duration = round(sum(durations) / len(durations), 1) if durations else None
    
    # Distribution close_reason
    reasons: dict[str, int] = {}
    for t in trades:
        r = t.get("close_reason") or "UNKNOWN"
        reasons[r] = reasons.get(r, 0) + 1
    
    n_trades = len(trades)
    win_rate = len(wins) / n_trades if n_trades else 0.0
    expectancy = total_pnl / n_trades if n_trades else 0.0
    
    return {
        "period": period,
        "from": since,
        "to": until,
        "pnl": round(total_pnl, 2),
        "pnl_pct": round(total_pnl / TRADING_CAPITAL * 100, 2) if TRADING_CAPITAL else 0.0,
        "capital": TRADING_CAPITAL,
        "capital_at_risk_now": round(capital_at_risk, 2),
        "n_trades": n_trades,
        "n_wins": len(wins),
        "n_losses": len(losses),
        "win_rate": round(win_rate, 3),
        "avg_pnl_per_trade": round(total_pnl / n_trades, 2) if n_trades else 0.0,
        "profit_factor": profit_factor,
        "expectancy": round(expectancy, 2),
        "max_drawdown": round(-max_dd, 2),  # stocké négatif pour l'affichage
        "best_trade": {
            "pair": best["pair"],
            "direction": best["direction"],
            "pnl": round(float(best["pnl"]), 2),
            "closed_at": best["closed_at"],
        },
        "worst_trade": {
            "pair": worst["pair"],
            "direction": worst["direction"],
            "pnl": round(float(worst["pnl"]), 2),
            "closed_at": worst["closed_at"],
        },
        "avg_duration_min": avg_duration,
        "close_reasons": reasons,
        "n_open": len(opens),
    }
