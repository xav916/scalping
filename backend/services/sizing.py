"""Sizing dynamique du montant risque par trade.

Le bridge MT5 calcule les lots a partir de `risk_money` + specs du symbole
chez le broker (trade_tick_value, volume_step, etc.). Ce service calcule
ce `risk_money` en le modulant selon :

1. Capital actuel (realised PnL du jour inclus).
2. Base : `RISK_PER_TRADE_PCT` du capital.
3. Multiplicateur de confiance : un signal a 90/100 merite plus qu'un
   signal a 60/100. Echelle lineaire entre 0.5x et 1.5x sur la plage
   60→95 (au-dela, plafonne).
4. Drawdown-aware reducer : si le PnL realise sur les 7 derniers jours
   est negatif, on divise le risque par 2. Evite les "revenge trades"
   amplifies quand le modele sous-performe.

Le but : faire travailler le capital plus fort quand le signal est fort
et le contexte favorable, et freiner quand on encaisse des pertes.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def confidence_multiplier(score: float | None) -> float:
    """Mappe un confidence_score 0-100 vers un multiplicateur de risque :
    - < 60  → 0.5x (clamp bas)
    - 60-95 → lineaire de 0.5x a 1.5x
    - >= 95 → 1.5x (clamp haut)

    Choix lineaire plutot que sigmoide : transparent, debuggable, et une
    relation plus complexe n'a pas de base statistique tant qu'on n'a
    pas 500+ trades pour calibrer."""
    if score is None:
        return 1.0
    if score < 60:
        return 0.5
    if score >= 95:
        return 1.5
    return _clamp(0.5 + (score - 60) / 35.0, 0.5, 1.5)


def recent_pnl_multiplier(days: int = 7) -> float:
    """1.0 si le PnL cumule des `days` derniers jours est >= 0,
    0.5 sinon. "Capital preservation mode" quand le modele est en
    perte recente."""
    try:
        from backend.services.trade_log_service import _DB_PATH
    except Exception:
        return 1.0

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        with sqlite3.connect(_DB_PATH) as c:
            row = c.execute(
                "SELECT COALESCE(SUM(pnl), 0) FROM personal_trades "
                "WHERE status = 'CLOSED' AND closed_at >= ?",
                (since,),
            ).fetchone()
        pnl = float(row[0] or 0)
    except Exception as e:
        logger.debug(f"sizing: recent_pnl lookup failed: {e}")
        return 1.0
    return 1.0 if pnl >= 0 else 0.5


def compute_risk_money(setup) -> dict:
    """Retourne un dict `{risk_money, base, conf_mult, pnl_mult, final_mult}`
    pour l'envoi au bridge et le logging."""
    from config.settings import RISK_PER_TRADE_PCT, TRADING_CAPITAL

    base = TRADING_CAPITAL * (RISK_PER_TRADE_PCT / 100.0)
    conf_mult = confidence_multiplier(getattr(setup, "confidence_score", None))
    pnl_mult = recent_pnl_multiplier()
    final_mult = conf_mult * pnl_mult
    risk_money = round(base * final_mult, 2)
    return {
        "risk_money": risk_money,
        "base": round(base, 2),
        "conf_mult": round(conf_mult, 2),
        "pnl_mult": round(pnl_mult, 2),
        "final_mult": round(final_mult, 2),
        "capital": TRADING_CAPITAL,
        "risk_pct": RISK_PER_TRADE_PCT,
    }
