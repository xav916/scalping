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
    """Métriques consolidées pour une période preset : PnL, win rate, profit
    factor, expectancy, max drawdown, best/worst trade, durée moyenne,
    distribution close_reason.

    Wrapper : calcule (since, until) depuis le preset, délègue à
    `_compute_stats_for_range`. Backward compat : même schéma de réponse.

    Source : personal_trades WHERE status='CLOSED' AND is_auto=1 AND
    closed_at in [since, until].
    """
    since, until = _period_window(period)
    return _compute_stats_for_range(since, until, period_label=period)


def get_period_stats_range(since: str, until: str) -> dict:
    """Même chose que `get_period_stats` mais avec un range custom arbitraire
    passé par l'API. `period` dans la réponse = 'custom'."""
    return _compute_stats_for_range(since, until, period_label="custom")


def _compute_stats_for_range(since: str, until: str, period_label: str) -> dict:
    """Fonction pure : calcule tous les KPIs pour le range `[since, until]`.

    Ne dépend ni du wall-clock ni d'un preset — juste des bornes ISO UTC.
    """
    from config.settings import TRADING_CAPITAL

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
            "period": period_label,
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
        "period": period_label,
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


# ─── Capital à risque au cours du temps (ExposureTimelineCard) ────────────


def _pair_units(pair: str) -> float:
    """Unités par lot pour calculer le capital à risque en monnaie.

    Forex standard = 100k unités de devise base. Métaux XAU/XAG = 100 oz.
    Valeurs approximatives pour la conversion en € (suffit pour une viz).
    """
    base = pair.split("/")[0].upper() if "/" in pair else pair.upper()
    if base in {"XAU", "XAG", "XPT", "XPD"}:
        return 100.0
    return 100_000.0


def get_exposure_timeseries(since: str, until: str, granularity: str = "auto") -> dict[str, Any]:
    """Capital à risque et nombre de positions ouvertes snapshotés à la fin
    de chaque bucket temporel.

    Calcul dérivé de `personal_trades` (is_auto=1) : une position est
    considérée ouverte au temps t si `created_at <= t` ET
    `(closed_at IS NULL OR closed_at > t)`. Le capital à risque à t est
    la somme des |entry - stop_loss| × size_lot × units(pair).

    Retourne :
        {
          "points": [{bucket_time, capital_at_risk, n_open}, ...],
          "granularity_used": str,
          "since": ..., "until": ...,
        }
    """
    if granularity == "auto":
        granularity = _resolve_auto_granularity(since, until)
    if granularity not in _GRANULARITIES:
        raise ValueError(f"granularity invalide: {granularity}")
    # Même garde-fou 5min que pnl-buckets
    if granularity == "5min":
        span_hours = (_parse_iso(until) - _parse_iso(since)).total_seconds() / 3600
        if span_hours > 24:
            raise ValueError("5min granularity limitée à une plage de 24h maximum")

    # Charge tous les trades qui pouvaient être ouverts à un moment dans [since, until]
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            """
            SELECT pair, entry_price, stop_loss, size_lot, created_at, closed_at
              FROM personal_trades
             WHERE is_auto = 1
               AND created_at <= ?
               AND (closed_at IS NULL OR closed_at >= ?)
            """,
            (until, since),
        ).fetchall()
    trades = [dict(r) for r in rows]

    # Pré-calcule le capital à risque par trade (indépendant du temps)
    for t in trades:
        entry = t.get("entry_price") or 0
        sl = t.get("stop_loss") or 0
        lot = t.get("size_lot") or 0
        t["_risk_money"] = abs(entry - sl) * lot * _pair_units(t.get("pair") or "")

    # Itère les buckets
    start_key = _bucket_key(since, granularity)
    end_key = _bucket_key(until, granularity)

    points: list[dict[str, Any]] = []
    current = start_key
    for _ in range(5001):
        _, bucket_end_iso = _bucket_bounds(current, granularity)
        open_at_risk = 0.0
        n_open = 0
        for t in trades:
            created = t.get("created_at") or ""
            closed = t.get("closed_at")
            if created and created <= bucket_end_iso and (not closed or closed > bucket_end_iso):
                open_at_risk += t["_risk_money"]
                n_open += 1
        points.append({
            "bucket_time": bucket_end_iso,
            "capital_at_risk": round(open_at_risk, 2),
            "n_open": n_open,
        })
        if current == end_key:
            break
        current = _next_bucket_key(current, granularity)
    else:
        raise ValueError(f"Trop de buckets (> 5000) pour granularity={granularity}")

    peak = max((p["capital_at_risk"] for p in points), default=0.0)
    avg = sum(p["capital_at_risk"] for p in points) / len(points) if points else 0.0
    max_open = max((p["n_open"] for p in points), default=0)

    return {
        "points": points,
        "granularity_used": granularity,
        "peak_at_risk": round(peak, 2),
        "avg_at_risk": round(avg, 2),
        "max_open": max_open,
        "since": since,
        "until": until,
    }


# ─── PnL buckets (graph carte Performance) ────────────────────────────────

_GRANULARITIES = ("5min", "hour", "day", "month")


def _parse_iso(s: str):
    """Parse une ISO 8601 UTC tolérante (accepte 'Z' ou '+00:00')."""
    from datetime import datetime
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _resolve_auto_granularity(since_iso: str, until_iso: str) -> str:
    """Règles span-based identiques au frontend.
    - span ≤ 36h → hour
    - 36h < span ≤ 93j → day
    - span > 93j → month
    """
    since_dt = _parse_iso(since_iso)
    until_dt = _parse_iso(until_iso)
    span_hours = (until_dt - since_dt).total_seconds() / 3600
    if span_hours <= 36:
        return "hour"
    span_days = span_hours / 24
    if span_days <= 93:
        return "day"
    return "month"


def _bucket_key(iso_dt: str, granularity: str) -> str:
    """Clé canonique d'un bucket pour une date ISO."""
    dt = _parse_iso(iso_dt)
    if granularity == "month":
        return dt.strftime("%Y-%m")
    if granularity == "day":
        return dt.strftime("%Y-%m-%d")
    if granularity == "hour":
        return dt.strftime("%Y-%m-%dT%H")
    if granularity == "5min":
        floored = (dt.minute // 5) * 5
        return dt.strftime("%Y-%m-%dT%H:") + f"{floored:02d}"
    raise ValueError(f"granularity inconnue: {granularity}")


def _bucket_bounds(key: str, granularity: str) -> tuple[str, str]:
    """Retourne (start_iso, end_iso) pour un bucket key."""
    from datetime import datetime, timezone, timedelta

    if granularity == "month":
        year, month = int(key[:4]), int(key[5:7])
        start = datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Premier du mois suivant − 1 seconde
        if month == 12:
            next_month = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        else:
            next_month = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        end = next_month - timedelta(seconds=1)
    elif granularity == "day":
        dt = datetime.fromisoformat(key).replace(tzinfo=timezone.utc)
        start = dt
        end = dt + timedelta(days=1) - timedelta(seconds=1)
    elif granularity == "hour":
        dt = datetime.fromisoformat(key + ":00:00").replace(tzinfo=timezone.utc)
        start = dt
        end = dt + timedelta(hours=1) - timedelta(seconds=1)
    elif granularity == "5min":
        dt = datetime.fromisoformat(key + ":00").replace(tzinfo=timezone.utc)
        start = dt
        end = dt + timedelta(minutes=5) - timedelta(seconds=1)
    else:
        raise ValueError(f"granularity inconnue: {granularity}")

    return (start.isoformat(), end.isoformat())


def _next_bucket_key(key: str, granularity: str) -> str:
    """Clé du bucket suivant (pour itérer et remplir les trous)."""
    from datetime import datetime, timezone, timedelta

    if granularity == "month":
        year, month = int(key[:4]), int(key[5:7])
        if month == 12:
            return f"{year + 1}-01"
        return f"{year}-{month + 1:02d}"
    if granularity == "day":
        dt = datetime.fromisoformat(key)
        nxt = dt + timedelta(days=1)
        return nxt.strftime("%Y-%m-%d")
    if granularity == "hour":
        dt = datetime.fromisoformat(key + ":00:00")
        nxt = dt + timedelta(hours=1)
        return nxt.strftime("%Y-%m-%dT%H")
    if granularity == "5min":
        dt = datetime.fromisoformat(key + ":00")
        nxt = dt + timedelta(minutes=5)
        floored = (nxt.minute // 5) * 5
        return nxt.strftime("%Y-%m-%dT%H:") + f"{floored:02d}"
    raise ValueError(f"granularity inconnue: {granularity}")


def get_pnl_buckets(since: str, until: str, granularity: str = "auto") -> dict:
    """Série temporelle du PnL bucketisée pour le graph de la carte Performance.

    Args:
        since: borne inférieure ISO UTC (incluse).
        until: borne supérieure ISO UTC (incluse).
        granularity: '5min'|'hour'|'day'|'month'|'auto'. Si 'auto', résolu par
            span (règles identiques au frontend).

    Garde-fous :
        - '5min' avec span > 24h → ValueError('span trop large pour 5min').

    Retourne :
        {
          "buckets": [{bucket_start, bucket_end, pnl, cumulative_pnl, n_trades}, ...],
          "granularity_used": "day",
          "total_trades": 22,
          "final_pnl": 187.42,
          "since": "...",
          "until": "...",
        }
    """
    if granularity == "auto":
        granularity = _resolve_auto_granularity(since, until)
    if granularity not in _GRANULARITIES:
        raise ValueError(f"granularity invalide: {granularity}")

    # Garde-fou 5min : trop de buckets si plage > 24h (288 buckets/jour × N jours)
    if granularity == "5min":
        span_hours = (_parse_iso(until) - _parse_iso(since)).total_seconds() / 3600
        if span_hours > 24:
            raise ValueError("5min granularity limitée à une plage de 24h maximum")

    # Récupère tous les trades CLOSED dans le range
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            """
            SELECT closed_at, pnl
              FROM personal_trades
             WHERE is_auto = 1
               AND status = 'CLOSED'
               AND pnl IS NOT NULL
               AND closed_at IS NOT NULL
               AND closed_at >= ?
               AND closed_at <= ?
             ORDER BY closed_at ASC
            """,
            (since, until),
        ).fetchall()

    trades = [dict(r) for r in rows]

    # Agrège par bucket key
    per_bucket: dict[str, dict] = {}
    for t in trades:
        key = _bucket_key(t["closed_at"], granularity)
        entry = per_bucket.setdefault(key, {"pnl": 0.0, "n_trades": 0})
        entry["pnl"] += float(t["pnl"] or 0)
        entry["n_trades"] += 1

    # Itère de since à until par pas de granularité pour remplir les trous
    start_key = _bucket_key(since, granularity)
    end_key = _bucket_key(until, granularity)

    buckets: list[dict] = []
    cumulative = 0.0
    current = start_key
    # Safety cap : max 5000 buckets pour éviter runaway
    for _ in range(5001):
        bucket_start, bucket_end = _bucket_bounds(current, granularity)
        entry = per_bucket.get(current, {"pnl": 0.0, "n_trades": 0})
        cumulative += entry["pnl"]
        buckets.append({
            "bucket_start": bucket_start,
            "bucket_end": bucket_end,
            "pnl": round(entry["pnl"], 2),
            "cumulative_pnl": round(cumulative, 2),
            "n_trades": entry["n_trades"],
        })
        if current == end_key:
            break
        current = _next_bucket_key(current, granularity)
    else:
        # Boucle terminée sans break — safety cap dépassé
        raise ValueError(f"Trop de buckets générés (> 5000) pour granularity={granularity}")

    total_trades = sum(b["n_trades"] for b in buckets)
    final_pnl = buckets[-1]["cumulative_pnl"] if buckets else 0.0

    return {
        "buckets": buckets,
        "granularity_used": granularity,
        "total_trades": total_trades,
        "final_pnl": final_pnl,
        "since": since,
        "until": until,
    }
