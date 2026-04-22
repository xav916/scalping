"""Analytics : breakdowns du win rate par features pour piloter le modele.

Joint les trois tables :
- `signals` (backtest.db) : features du signal emis
- `trades`  (backtest.db) : outcome theorique (WIN_TP1/WIN_TP2/LOSS/OPEN)
- `personal_trades` (trades.db) : execution reelle + PnL

L'idee : repondre vite aux questions "quelles features correlent avec le
succes ?" → oriente les filtres a ajouter, les instruments a retirer, les
heures a eviter.

Toutes les fonctions retournent du JSON pret pour le frontend / un
notebook Jupyter. Aucun calcul lourd : tout tient en quelques requetes
SQL GROUP BY, executees a la demande (pas de caching prematuré — si les
datasets explosent, on verra).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


# Buckets de confiance : tranches de 10 pour rester lisible.
_CONFIDENCE_BUCKETS = [(0, 50), (50, 60), (60, 70), (70, 80), (80, 90), (90, 100)]


def _bt_db() -> Path:
    from backend.services.backtest_service import _DB_PATH
    return _DB_PATH


def _trades_db() -> Path:
    from backend.services.trade_log_service import _DB_PATH
    return _DB_PATH


def _row_factory(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row


def _rate(wins: int, losses: int) -> float:
    total = wins + losses
    return round(wins / total * 100, 1) if total else 0.0


def _safe_stats(win_by: dict, loss_by: dict) -> list[dict]:
    """Fusionne deux dicts {key: count} en lignes {key, wins, losses, total, win_rate_pct}.
    Utilise les cles de l'union pour ne rien perdre."""
    keys = sorted(set(win_by) | set(loss_by))
    rows = []
    for k in keys:
        w = win_by.get(k, 0)
        l = loss_by.get(k, 0)
        if w + l == 0:
            continue
        rows.append({
            "key": k,
            "wins": w,
            "losses": l,
            "total": w + l,
            "win_rate_pct": _rate(w, l),
        })
    return rows


def _is_win(outcome: str) -> bool:
    return outcome in ("WIN_TP1", "WIN_TP2")


def _is_loss(outcome: str) -> bool:
    return outcome == "LOSS"


# Exclusion systématique des trades dont le signal source était marqué
# is_simulated=1 (bug prix fantôme d'avant 2026-04-20, cf. commit 69df7f1).
# LEFT JOIN tolérant : on garde les trades qui n'ont pas de signal matché
# (rare edge case), on exclut uniquement ceux explicitement flagués.
_SIMULATED_FILTER_JOIN = """
    LEFT JOIN signals s_simfilter
      ON s_simfilter.pair = t.pair
      AND s_simfilter.direction = t.direction
      AND ABS(s_simfilter.entry_price - t.entry_price) < 0.0001 * t.entry_price
      AND ABS(strftime('%s', s_simfilter.emitted_at) - strftime('%s', t.emitted_at)) < 300
"""
_SIMULATED_FILTER_WHERE = (
    " AND (s_simfilter.is_simulated IS NULL OR s_simfilter.is_simulated = 0)"
)


def _theoretical_breakdown_by(column_expr: str, extra_join: str = "") -> list[dict]:
    """Breakdown du win rate theorique (issue du backtest `trades` table).

    `column_expr` est l'expression SQL qui donne la cle (ex: 'pair',
    "strftime('%H', emitted_at)", etc.). `extra_join` est un LEFT JOIN
    optionnel si on veut enrichir avec les features de `signals`.

    Exclut systematiquement les trades fantomes (signal is_simulated=1).
    """
    query = f"""
        SELECT {column_expr} AS k,
               SUM(CASE WHEN outcome IN ('WIN_TP1','WIN_TP2') THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) AS losses
          FROM trades t
          {_SIMULATED_FILTER_JOIN}
          {extra_join}
         WHERE outcome IN ('WIN_TP1','WIN_TP2','LOSS')
         {_SIMULATED_FILTER_WHERE}
         GROUP BY {column_expr}
         HAVING wins + losses > 0
         ORDER BY wins + losses DESC
    """
    with sqlite3.connect(_bt_db()) as c:
        _row_factory(c)
        rows = c.execute(query).fetchall()
    return [
        {
            "key": r["k"],
            "wins": r["wins"],
            "losses": r["losses"],
            "total": r["wins"] + r["losses"],
            "win_rate_pct": _rate(r["wins"], r["losses"]),
        }
        for r in rows
    ]


def _by_hour() -> list[dict]:
    """Win rate par heure UTC (0-23). Detecte les creux intraday."""
    return _theoretical_breakdown_by("strftime('%H', t.emitted_at)")


def _by_pair() -> list[dict]:
    return _theoretical_breakdown_by("t.pair")


def _by_pattern() -> list[dict]:
    return _theoretical_breakdown_by("t.pattern")


def _by_confidence_bucket() -> list[dict]:
    """Win rate par tranche de confiance_score. Repond a :
    'la confiance est-elle calibree ?' (un score eleve devrait = un win
    rate eleve). Si c'est plat, le scoring n'a pas de signal.

    Exclut les trades fantomes via JOIN signals.is_simulated = 0.
    """
    with sqlite3.connect(_bt_db()) as c:
        _row_factory(c)
        rows = c.execute(
            f"""
            SELECT t.confidence_score AS confidence_score, t.outcome AS outcome
              FROM trades t
              {_SIMULATED_FILTER_JOIN}
             WHERE t.outcome IN ('WIN_TP1','WIN_TP2','LOSS')
               AND t.confidence_score IS NOT NULL
               {_SIMULATED_FILTER_WHERE}
            """
        ).fetchall()

    wins: dict[str, int] = {}
    losses: dict[str, int] = {}
    for r in rows:
        score = r["confidence_score"] or 0
        bucket_label: str | None = None
        for lo, hi in _CONFIDENCE_BUCKETS:
            if lo <= score < hi or (hi == 100 and score == 100):
                bucket_label = f"{lo}-{hi}"
                break
        if bucket_label is None:
            continue
        if _is_win(r["outcome"]):
            wins[bucket_label] = wins.get(bucket_label, 0) + 1
        elif _is_loss(r["outcome"]):
            losses[bucket_label] = losses.get(bucket_label, 0) + 1

    return _safe_stats(wins, losses)


def _by_asset_class() -> list[dict]:
    """Breakdown par asset_class (forex/metal/crypto/index/energy).
    Necessite un JOIN sur signals (trades n'a pas ce champ). Reutilise
    l'alias s_simfilter pose par _SIMULATED_FILTER_JOIN — meme ligne signal,
    pas de JOIN supplementaire."""
    return _theoretical_breakdown_by(
        "COALESCE(s_simfilter.asset_class, 'unknown')",
    )


def _by_risk_regime() -> list[dict]:
    """Breakdown par risk_regime macro (risk_on / risk_off / neutral).
    Le regime est stocke en JSON dans signals.macro_context ; on lit
    toutes les lignes et on regroupe en Python (nb modeste de trades →
    pas de pression perf)."""
    # Note : on réutilise le JOIN de _SIMULATED_FILTER_JOIN (alias s_simfilter)
    # pour lire AUSSI is_simulated et macro_context depuis la même ligne signal
    # — évite un deuxième JOIN redondant.
    with sqlite3.connect(_bt_db()) as c:
        _row_factory(c)
        rows = c.execute(
            f"""
            SELECT s_simfilter.macro_context AS macro_context, t.outcome AS outcome
              FROM trades t
              {_SIMULATED_FILTER_JOIN}
             WHERE t.outcome IN ('WIN_TP1','WIN_TP2','LOSS')
               {_SIMULATED_FILTER_WHERE}
            """
        ).fetchall()

    wins: dict[str, int] = {}
    losses: dict[str, int] = {}
    for r in rows:
        regime = "unknown"
        if r["macro_context"]:
            try:
                regime = json.loads(r["macro_context"]).get("risk_regime") or "unknown"
            except Exception:
                regime = "unknown"
        if _is_win(r["outcome"]):
            wins[regime] = wins.get(regime, 0) + 1
        elif _is_loss(r["outcome"]):
            losses[regime] = losses.get(regime, 0) + 1
    return _safe_stats(wins, losses)


def _execution_quality() -> dict:
    """Qualite d'execution : slippage moyen, distribution des close_reason.
    Reponses : 'les pertes viennent du signal ou du broker ?' et 'combien
    de fois on touche TP2 vs TP1 vs SL ?'."""
    with sqlite3.connect(_trades_db()) as c:
        _row_factory(c)
        slippage_stats = c.execute(
            """
            SELECT pair,
                   COUNT(*) AS n,
                   AVG(slippage_pips) AS avg_slippage,
                   MIN(slippage_pips) AS min_slippage,
                   MAX(slippage_pips) AS max_slippage
              FROM personal_trades
             WHERE slippage_pips IS NOT NULL
             GROUP BY pair
            """
        ).fetchall()
        close_reasons = c.execute(
            """
            SELECT close_reason, COUNT(*) AS n, AVG(pnl) AS avg_pnl
              FROM personal_trades
             WHERE status = 'CLOSED' AND close_reason IS NOT NULL
             GROUP BY close_reason
             ORDER BY n DESC
            """
        ).fetchall()
        total_closed = c.execute(
            "SELECT COUNT(*) FROM personal_trades WHERE status = 'CLOSED'"
        ).fetchone()[0]

    return {
        "total_closed_trades": total_closed,
        "slippage_by_pair": [
            {
                "pair": r["pair"],
                "n": r["n"],
                "avg_pips": round(r["avg_slippage"] or 0, 2),
                "min_pips": round(r["min_slippage"] or 0, 2),
                "max_pips": round(r["max_slippage"] or 0, 2),
            }
            for r in slippage_stats
        ],
        "close_reason_distribution": [
            {
                "reason": r["close_reason"],
                "count": r["n"],
                "pct": round(r["n"] / total_closed * 100, 1) if total_closed else 0.0,
                "avg_pnl": round(r["avg_pnl"] or 0, 2),
            }
            for r in close_reasons
        ],
    }


def _signal_volume() -> dict:
    """Volume de signaux : combien le radar genere-t-il par jour ?
    Utile pour detecter des regressions (baisse brutale = bug/data down)."""
    with sqlite3.connect(_bt_db()) as c:
        _row_factory(c)
        by_day = c.execute(
            """
            SELECT substr(emitted_at, 1, 10) AS day, COUNT(*) AS n
              FROM signals
             GROUP BY day
             ORDER BY day DESC
             LIMIT 30
            """
        ).fetchall()
        total = c.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        taken = c.execute(
            "SELECT COUNT(*) FROM signals WHERE verdict_action = 'TAKE'"
        ).fetchone()[0]
        skipped = c.execute(
            "SELECT COUNT(*) FROM signals WHERE verdict_action = 'SKIP'"
        ).fetchone()[0]

    return {
        "total_signals": total,
        "verdict_take": taken,
        "verdict_skip": skipped,
        "take_ratio_pct": round(taken / total * 100, 1) if total else 0.0,
        "last_30_days": [
            {"day": r["day"], "count": r["n"]} for r in by_day
        ],
    }


import time as _time
from concurrent.futures import ThreadPoolExecutor as _Executor

# Cache TTL global : les stats ne changent qu'au rythme des closures auto
# (1-2/h post-fix). 60s de staleness est acceptable pour une page analytics
# consultative (pas pour de l'auto-exec).
_ANALYTICS_CACHE: dict[str, object] = {"data": None, "ts": 0.0}
_ANALYTICS_CACHE_TTL_SEC = 60.0


def _build_analytics_uncached() -> dict:
    """Exécute les 8 breakdowns en parallèle (ThreadPool de 4). Les queries
    SQL sqlite3 libèrent le GIL → vraie parallélisation. Wall time réduit
    du sum des durées (2150ms) au max individuel (750ms, by_pair)."""
    tasks = {
        "by_pair": _by_pair,
        "by_hour_utc": _by_hour,
        "by_pattern": _by_pattern,
        "by_confidence_bucket": _by_confidence_bucket,
        "by_asset_class": _by_asset_class,
        "by_risk_regime": _by_risk_regime,
        "execution_quality": _execution_quality,
        "signal_volume": _signal_volume,
    }
    out: dict[str, object] = {}
    with _Executor(max_workers=4) as pool:
        futures = {key: pool.submit(fn) for key, fn in tasks.items()}
        for key, fut in futures.items():
            out[key] = fut.result()
    return out


def build_analytics() -> dict:
    """Point d'entree unique : retourne toutes les breakdowns en un payload.
    Cache in-memory 60s — les 8 queries coûtent ~1.4s avec 2500+ trades."""
    now = _time.time()
    cached = _ANALYTICS_CACHE["data"]
    cached_ts = float(_ANALYTICS_CACHE["ts"])
    if cached is not None and (now - cached_ts) < _ANALYTICS_CACHE_TTL_SEC:
        return cached  # type: ignore[return-value]
    try:
        result = _build_analytics_uncached()
        _ANALYTICS_CACHE["data"] = result
        _ANALYTICS_CACHE["ts"] = now
        return result
    except Exception as e:
        logger.warning(f"analytics: build_analytics a echoue: {e}", exc_info=True)
        return {"error": str(e)[:200]}


def invalidate_analytics_cache() -> None:
    """Vide le cache. À appeler explicitement si une mutation critique
    (ex: backfill trade) doit forcer un refresh. Non utilisé en auto :
    le TTL suffit pour l'usage actuel (read-only consultation)."""
    _ANALYTICS_CACHE["data"] = None
    _ANALYTICS_CACHE["ts"] = 0.0
