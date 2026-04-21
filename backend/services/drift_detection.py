"""Detection de drift : quand un pattern ou une paire commence a
sous-performer par rapport a sa baseline historique.

Principe minimaliste (on fait du volume avant de raffiner) :
- On compare la fenetre recente (7 derniers jours) a la baseline
  (tous les jours precedents).
- Pour chaque cle (pair ou pattern), si le win rate recent baisse
  de plus de `DRIFT_THRESHOLD_PCT` points vs la baseline ET qu'on
  a au moins `MIN_RECENT_TRADES` trades sur la fenetre → flag drift.
- On ignore les cles avec peu de trades (bruit statistique).

Limites connues :
- Pas de test statistique (chi-2, bootstrap). Un seuil dur sur %
  peut flagger des faux positifs si l'echantillon est petit. C'est
  pour ca que `MIN_RECENT_TRADES = 10` par defaut — on accepte de
  rater quelques drifts plutot que de spammer le user.
- On se base sur les `trades` du backtest (outcome theorique), pas
  les `personal_trades` (outcome reel) — cela donne une vue plus
  complete au prix de ne pas refleter le slippage reel.

Le frontend peut afficher le resultat de `find_drifts()` en
bandeau "Instruments en regression" / "Patterns qui faiblissent".
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

DRIFT_THRESHOLD_PCT = 15.0  # Baisse en points de win rate (absolute)
MIN_RECENT_TRADES = 10       # Trades minimum dans la fenetre recente
RECENT_WINDOW_DAYS = 7


def _bt_db():
    from backend.services.backtest_service import _DB_PATH
    return _DB_PATH


def _fetch_outcomes(key_col: str):
    """Retourne la liste (key, outcome, emitted_at) pour les trades fermes."""
    query = f"""
        SELECT {key_col} AS k, outcome, emitted_at
          FROM trades
         WHERE outcome IN ('WIN_TP1','WIN_TP2','LOSS')
    """
    with sqlite3.connect(_bt_db()) as c:
        c.row_factory = sqlite3.Row
        return c.execute(query).fetchall()


def _split_recent_vs_baseline(rows, days: int):
    """Sepe les outcomes en (recent, baseline) sur un cutoff `days`."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent: dict[str, list[str]] = {}
    baseline: dict[str, list[str]] = {}
    for r in rows:
        k = r["k"] or "unknown"
        try:
            dt = datetime.fromisoformat(r["emitted_at"].replace("Z", "+00:00"))
        except Exception:
            continue
        bucket = recent if dt >= cutoff else baseline
        bucket.setdefault(k, []).append(r["outcome"])
    return recent, baseline


def _win_rate(outcomes: list[str]) -> float | None:
    if not outcomes:
        return None
    wins = sum(1 for o in outcomes if o in ("WIN_TP1", "WIN_TP2"))
    return round(wins / len(outcomes) * 100, 1)


def _detect_drift_for(key_col: str) -> list[dict]:
    rows = _fetch_outcomes(key_col)
    recent, baseline = _split_recent_vs_baseline(rows, RECENT_WINDOW_DAYS)
    findings: list[dict] = []
    for key in recent:
        recent_outcomes = recent[key]
        baseline_outcomes = baseline.get(key, [])
        if len(recent_outcomes) < MIN_RECENT_TRADES:
            continue
        wr_recent = _win_rate(recent_outcomes)
        wr_baseline = _win_rate(baseline_outcomes)
        if wr_baseline is None:
            continue
        delta = wr_recent - wr_baseline
        if delta <= -DRIFT_THRESHOLD_PCT:
            findings.append({
                "key": key,
                "recent_n": len(recent_outcomes),
                "baseline_n": len(baseline_outcomes),
                "recent_win_rate_pct": wr_recent,
                "baseline_win_rate_pct": wr_baseline,
                "delta_pct": round(delta, 1),
            })
    # Pire drift en premier (le plus negatif).
    findings.sort(key=lambda x: x["delta_pct"])
    return findings


def find_drifts() -> dict:
    """Scanne les drifts sur `pair` et `pattern`. Payload pret pour l'UI."""
    try:
        return {
            "window_days": RECENT_WINDOW_DAYS,
            "threshold_pct": DRIFT_THRESHOLD_PCT,
            "min_recent_trades": MIN_RECENT_TRADES,
            "by_pair": _detect_drift_for("pair"),
            "by_pattern": _detect_drift_for("pattern"),
        }
    except Exception as e:
        logger.warning(f"drift_detection: find_drifts a echoue: {e}", exc_info=True)
        return {"error": str(e)[:200]}
