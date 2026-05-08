"""Veto géopolitique sur le scoring trade — règles hard rule sur Polymarket + GDELT.

Branché en aval du `macro_scoring.apply()` dans `analysis_engine.enrich_trade_setup`.
Comportement identique : si une règle match, set ``verdict_action="SKIP"`` et
ajoute la raison dans ``verdict_blockers``. Le rejet final est ensuite acté par
``mt5_bridge._check_rejection`` qui regarde ``setup.verdict_blockers``.

Best-effort : toute exception (snapshot manquant, malformé) retourne pas de veto,
jamais d'erreur qui casserait le scoring.

Règles V1 (toggleables individuellement via env vars) :

1. **IRAN_HORMUZ** — Polymarket "Iran peace deal" prob ≥ seuil à <14j
   → veto LONGS sur XAU/XAG/WTI. Logique : un peace deal imminent
   tue la prime de risque safe-haven et la prime supply oil.

2. **FED_DOVISH** — Polymarket "rate cut" prob ≥ seuil à <14j
   → veto trades qui parient sur USD fort (sell XX/USD ou buy USD/XX).
   Logique : un cut imminent affaiblit l'USD à court terme.

3. **RECESSION_FEAR** — Polymarket "recession" prob ≥ seuil
   → veto LONGS sur indices US (SPX/NDX/US30). Logique : recession
   imminente = repricing baissier des actions.

4. **GDELT_HIGH_STRESS** — GDELT overall_stress = "high"
   ET stress géopolitique theme = "high"
   → veto LONGS sur indices européens (DAX/CAC40/FTSE). Logique :
   tension globale + Europe particulièrement exposée = aversion risque.

Toutes les règles ont des seuils env-tunables (cf. ``config.settings``).
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from config.settings import (
    GEOPOLITICAL_VETO_ENABLED,
    GEOPOLITICAL_VETO_IRAN_HORMUZ_ENABLED,
    GEOPOLITICAL_VETO_IRAN_HORMUZ_PROB,
    GEOPOLITICAL_VETO_IRAN_HORMUZ_DAYS,
    GEOPOLITICAL_VETO_FED_DOVISH_ENABLED,
    GEOPOLITICAL_VETO_FED_DOVISH_PROB,
    GEOPOLITICAL_VETO_FED_DOVISH_DAYS,
    GEOPOLITICAL_VETO_RECESSION_ENABLED,
    GEOPOLITICAL_VETO_RECESSION_PROB,
    GEOPOLITICAL_VETO_GDELT_STRESS_ENABLED,
)

logger = logging.getLogger(__name__)


# ─── Asset class buckets ─────────────────────────────────────────────
_SAFE_HAVEN_AND_OIL = {"XAU/USD", "XAG/USD", "WTI/USD"}
_US_INDICES = {"SPX", "NDX", "US30"}
_EU_INDICES = {"DAX", "CAC40", "FTSE", "EUR/JPY", "EUR/GBP"}


# ─── Polymarket question matchers ────────────────────────────────────
def _q_matches(question: str, includes: list[str], excludes: list[str] | None = None) -> bool:
    """Question case-insensitive substring matcher.

    Tous les mots de ``includes`` doivent être présents (AND).
    Aucun mot de ``excludes`` ne doit être présent.
    """
    q = question.lower()
    for w in includes:
        if w not in q:
            return False
    if excludes:
        for w in excludes:
            if w in q:
                return False
    return True


def _days_to(end_date_str: Optional[str]) -> Optional[int]:
    """Parse end_date 'YYYY-MM-DD' → nb jours d'ici. None si parsing fail."""
    if not end_date_str:
        return None
    try:
        end = date.fromisoformat(end_date_str[:10])
    except (ValueError, TypeError):
        return None
    delta = (end - date.today()).days
    return delta


# ─── Règles individuelles ────────────────────────────────────────────
def _check_iran_hormuz(pair: str, direction: str, poly: dict | None) -> Optional[str]:
    """Iran peace deal prob élevée à courte échéance + long safe-haven/oil."""
    if not GEOPOLITICAL_VETO_IRAN_HORMUZ_ENABLED:
        return None
    if direction != "buy" or pair not in _SAFE_HAVEN_AND_OIL:
        return None
    if not poly:
        return None
    geo_markets = (poly.get("themes") or {}).get("geopolitical") or []
    best = None
    for m in geo_markets:
        if _q_matches(m.get("question", ""), ["iran", "peace deal"]):
            days = _days_to(m.get("end_date"))
            if days is None or days < 0 or days > GEOPOLITICAL_VETO_IRAN_HORMUZ_DAYS:
                continue
            prob = m.get("yes_prob") or 0
            if prob >= GEOPOLITICAL_VETO_IRAN_HORMUZ_PROB:
                if best is None or prob > best[0]:
                    best = (prob, m, days)
    if best is None:
        return None
    prob, market, days = best
    return (
        f"Iran peace deal prob {prob*100:.0f}% à {days}j "
        f"({market.get('question', '')[:60]}) → long {pair} risqué"
    )


def _check_fed_dovish(pair: str, direction: str, poly: dict | None) -> Optional[str]:
    """Fed rate cut prob haute à courte échéance + position USD-fort."""
    if not GEOPOLITICAL_VETO_FED_DOVISH_ENABLED:
        return None
    if not poly:
        return None
    is_xx_usd = pair.endswith("/USD")
    is_usd_xx = pair.startswith("USD/")
    # USD-bull = sell XX/USD OR buy USD/XX
    is_usd_bull = (direction == "sell" and is_xx_usd) or (direction == "buy" and is_usd_xx)
    if not is_usd_bull:
        return None
    monetary_markets = (poly.get("themes") or {}).get("monetary") or []
    best = None
    for m in monetary_markets:
        if _q_matches(m.get("question", ""), ["rate cut"]) or _q_matches(m.get("question", ""), ["fed", "cut"]):
            days = _days_to(m.get("end_date"))
            if days is None or days < 0 or days > GEOPOLITICAL_VETO_FED_DOVISH_DAYS:
                continue
            prob = m.get("yes_prob") or 0
            if prob >= GEOPOLITICAL_VETO_FED_DOVISH_PROB:
                if best is None or prob > best[0]:
                    best = (prob, m, days)
    if best is None:
        return None
    prob, market, days = best
    return (
        f"Fed cut prob {prob*100:.0f}% à {days}j "
        f"({market.get('question', '')[:60]}) → position USD-fort risquée"
    )


def _check_recession(pair: str, direction: str, poly: dict | None) -> Optional[str]:
    """Récession prob haute + long indice US."""
    if not GEOPOLITICAL_VETO_RECESSION_ENABLED:
        return None
    if direction != "buy" or pair not in _US_INDICES:
        return None
    if not poly:
        return None
    economy_markets = (poly.get("themes") or {}).get("economy") or []
    best = None
    for m in economy_markets:
        if _q_matches(m.get("question", ""), ["recession"]):
            prob = m.get("yes_prob") or 0
            if prob >= GEOPOLITICAL_VETO_RECESSION_PROB:
                if best is None or prob > best[0]:
                    best = (prob, m)
    if best is None:
        return None
    prob, market = best
    return (
        f"Recession prob {prob*100:.0f}% "
        f"({market.get('question', '')[:60]}) → long {pair} risqué"
    )


def _check_gdelt_stress(pair: str, direction: str, gdelt: dict | None) -> Optional[str]:
    """Stress géopolitique GDELT élevé + long indice européen."""
    if not GEOPOLITICAL_VETO_GDELT_STRESS_ENABLED:
        return None
    if direction != "buy" or pair not in _EU_INDICES:
        return None
    if not gdelt:
        return None
    if gdelt.get("overall_stress") != "high":
        return None
    geo_theme = (gdelt.get("themes") or {}).get("geopolitical") or {}
    if geo_theme.get("stress_level") != "high":
        return None
    tone = geo_theme.get("avg_tone")
    return f"GDELT stress geopolitical=high (tone={tone}) → long {pair} EU risqué"


# ─── Entry point ─────────────────────────────────────────────────────
def apply(pair: str, direction: str) -> tuple[bool, list[str], dict]:
    """Évalue toutes les règles veto activées contre le setup.

    Parameters
    ----------
    pair : str
        Paire du setup (ex. "XAU/USD", "EUR/USD", "SPX").
    direction : str
        "buy" ou "sell".

    Returns
    -------
    tuple[bool, list[str], dict]
        (vetoed, reasons, metadata)
        - vetoed : True si au moins une règle match
        - reasons : liste des raisons human-readable (1 par règle matchée)
        - metadata : ``{rules_matched: [str], rules_evaluated: [str]}``

    Best-effort : toute erreur retourne ``(False, [], {})`` pour ne jamais
    bloquer le pipeline scoring sur un bug du veto.
    """
    if not GEOPOLITICAL_VETO_ENABLED:
        return False, [], {}

    try:
        # Lazy imports : évite les cycles + permet aux tests de patcher.
        from backend.services import polymarket_service, geopolitical_news_service
        try:
            poly = polymarket_service.get_current()
        except Exception as e:
            logger.debug(f"geopolitical_veto: polymarket get_current error: {e}")
            poly = None
        try:
            gdelt = geopolitical_news_service.get_current()
        except Exception as e:
            logger.debug(f"geopolitical_veto: gdelt get_current error: {e}")
            gdelt = None

        rules_matched: list[str] = []
        rules_evaluated: list[str] = []
        reasons: list[str] = []

        for rule_id, fn, args in (
            ("iran_hormuz", _check_iran_hormuz, (pair, direction, poly)),
            ("fed_dovish", _check_fed_dovish, (pair, direction, poly)),
            ("recession", _check_recession, (pair, direction, poly)),
            ("gdelt_stress", _check_gdelt_stress, (pair, direction, gdelt)),
        ):
            try:
                rules_evaluated.append(rule_id)
                reason = fn(*args)
                if reason:
                    rules_matched.append(rule_id)
                    reasons.append(reason)
            except Exception as e:
                logger.debug(f"geopolitical_veto: rule {rule_id} error: {e}")

        metadata = {
            "rules_evaluated": rules_evaluated,
            "rules_matched": rules_matched,
        }
        return (len(reasons) > 0), reasons, metadata

    except Exception as e:
        logger.warning(f"geopolitical_veto: top-level error: {e}")
        return False, [], {}
