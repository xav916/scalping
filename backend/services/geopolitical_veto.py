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

5. **TARIFF** — Polymarket "tariff" ou "trade war" prob ≥ seuil à <X jours
   → veto LONGS sur risk-on (indices US, crypto). Logique : une annonce
   tariff imminente = repricing risk-off (indices baissent, crypto sell-off).

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
    GEOPOLITICAL_VETO_TARIFF_ENABLED,
    GEOPOLITICAL_VETO_TARIFF_PROB,
    GEOPOLITICAL_VETO_TARIFF_DAYS,
)

logger = logging.getLogger(__name__)


# ─── Asset class buckets ─────────────────────────────────────────────
_SAFE_HAVEN_AND_OIL = {"XAU/USD", "XAG/USD", "WTI/USD"}
_US_INDICES = {"SPX", "NDX", "US30"}
_EU_INDICES = {"DAX", "CAC40", "FTSE", "EUR/JPY", "EUR/GBP"}
_RISK_ON_AND_CRYPTO = {"SPX", "NDX", "US30", "BTC/USD", "ETH/USD"}


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
        f"[iran_hormuz] Iran peace deal prob {prob*100:.0f}% à {days}j "
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
        q = m.get("question", "")
        # Polymarket emploie indifféremment "rate cut", "fed cut", ou "decrease interest rates" :
        # on accepte les 4 patterns sinon la règle reste inerte sur la wording actuelle.
        if (
            _q_matches(q, ["rate cut"])
            or _q_matches(q, ["fed", "cut"])
            or _q_matches(q, ["fed", "decrease"])
            or _q_matches(q, ["decrease", "interest", "rates"])
        ):
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
        f"[fed_dovish] Fed cut prob {prob*100:.0f}% à {days}j "
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
        f"[recession] Recession prob {prob*100:.0f}% "
        f"({market.get('question', '')[:60]}) → long {pair} risqué"
    )


def _check_tariff(pair: str, direction: str, poly: dict | None) -> Optional[str]:
    """Tariff / trade war prob élevée à horizon court + long risk-on (indices US, crypto).

    Logique : une annonce tariff imminente déclenche un repricing risk-off
    (indices baissent, crypto sell-off). On veto les longs risk-on.
    Sources : marchés Polymarket sous les thèmes politics/economy/geopolitical
    mentionnant "tariff" ou "trade war".
    """
    if not GEOPOLITICAL_VETO_TARIFF_ENABLED:
        return None
    if direction != "buy" or pair not in _RISK_ON_AND_CRYPTO:
        return None
    if not poly:
        return None
    themes = poly.get("themes") or {}
    best = None
    for theme_name in ("politics", "economy", "geopolitical"):
        for m in themes.get(theme_name) or []:
            q = m.get("question", "")
            if _q_matches(q, ["tariff"]) or _q_matches(q, ["trade", "war"]):
                days = _days_to(m.get("end_date"))
                if days is None or days < 0 or days > GEOPOLITICAL_VETO_TARIFF_DAYS:
                    continue
                prob = m.get("yes_prob") or 0
                if prob >= GEOPOLITICAL_VETO_TARIFF_PROB:
                    if best is None or prob > best[0]:
                        best = (prob, m, days)
    if best is None:
        return None
    prob, market, days = best
    return (
        f"[tariff] Tariff/trade war prob {prob*100:.0f}% à {days}j "
        f"({market.get('question', '')[:60]}) → long {pair} risk-on risqué"
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
    return f"[gdelt_stress] GDELT stress geopolitical=high (tone={tone}) → long {pair} EU risqué"


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
            ("tariff", _check_tariff, (pair, direction, poly)),
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


# ─── Observability — stats sur signal_rejections ─────────────────────
import json as _json
import re as _re
import sqlite3 as _sqlite3
from datetime import timedelta as _timedelta, timezone as _timezone

_RULE_TAG_RE = _re.compile(r"\[(\w+)\]")
KNOWN_RULES = ("iran_hormuz", "fed_dovish", "recession", "gdelt_stress", "tariff")


def get_stats(days: int = 7) -> dict:
    """Stats des vetos géopolitiques sur les ``days`` derniers jours.

    Lit la table ``signal_rejections`` filtre ``reason_code='geopolitical_veto'``,
    parse le tag ``[rule_id]`` au début de chaque blocker pour ventiler par
    règle. Best-effort : retourne dict vide si DB inaccessible.

    Returns
    -------
    dict
        {
          "since": iso,
          "until": iso,
          "days": int,
          "total": int,
          "by_rule": {"iran_hormuz": N, ...},
          "by_pair": [{"pair": "XAU/USD", "count": N}, ...],  # top 10
          "by_day": [{"date": "2026-05-08", "count": N}, ...],
          "recent": [{"created_at": ..., "pair": ..., "rule": ..., "reason": ...}, ...],  # 20 derniers
        }
    """
    days = max(1, min(60, int(days)))
    until = datetime.now(_timezone.utc)
    since = until - _timedelta(days=days)
    since_iso = since.isoformat()
    until_iso = until.isoformat()

    try:
        from backend.services.trade_log_service import _DB_PATH
        with _sqlite3.connect(str(_DB_PATH)) as c:
            c.row_factory = _sqlite3.Row
            rows = c.execute(
                """
                SELECT created_at, pair, direction, details
                  FROM signal_rejections
                 WHERE reason_code = 'geopolitical_veto'
                   AND created_at >= ?
                   AND created_at <= ?
                 ORDER BY created_at DESC
                """,
                (since_iso, until_iso),
            ).fetchall()
    except Exception as e:
        logger.warning(f"geopolitical_veto.get_stats: DB error: {e}")
        return {
            "since": since_iso, "until": until_iso, "days": days,
            "total": 0, "by_rule": {}, "by_pair": [], "by_day": [], "recent": [],
        }

    by_rule: dict[str, int] = {r: 0 for r in KNOWN_RULES}
    by_pair: dict[str, int] = {}
    by_day: dict[str, int] = {}
    recent: list[dict] = []

    for row in rows:
        try:
            details = _json.loads(row["details"]) if row["details"] else {}
        except (_json.JSONDecodeError, TypeError):
            details = {}
        blockers = details.get("blockers") or []

        # Identifier la première règle taggée
        rule_id = "unknown"
        first_blocker = blockers[0] if blockers else ""
        m = _RULE_TAG_RE.search(first_blocker)
        if m and m.group(1) in KNOWN_RULES:
            rule_id = m.group(1)
        by_rule[rule_id] = by_rule.get(rule_id, 0) + 1

        pair = row["pair"] or "UNKNOWN"
        by_pair[pair] = by_pair.get(pair, 0) + 1

        day = row["created_at"][:10] if row["created_at"] else ""
        if day:
            by_day[day] = by_day.get(day, 0) + 1

        if len(recent) < 20:
            recent.append({
                "created_at": row["created_at"],
                "pair": pair,
                "direction": row["direction"],
                "rule": rule_id,
                "reason": first_blocker,
            })

    by_pair_sorted = sorted(
        [{"pair": p, "count": c} for p, c in by_pair.items()],
        key=lambda x: x["count"], reverse=True,
    )[:10]

    by_day_sorted = sorted(
        [{"date": d, "count": c} for d, c in by_day.items()],
        key=lambda x: x["date"],
    )

    return {
        "since": since_iso,
        "until": until_iso,
        "days": days,
        "total": len(rows),
        "by_rule": by_rule,
        "by_pair": by_pair_sorted,
        "by_day": by_day_sorted,
        "recent": recent,
    }
