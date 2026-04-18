"""Module de coaching : genere un texte en langage naturel et un verdict
(TAKE / WAIT / SKIP) pour chaque setup de trade detecte.

Pur Python, pas d'IA : regles deterministes basees sur les facteurs
objectifs (score, session, news, volatilite, tendance).
"""

from datetime import datetime, timezone
from typing import Any

from backend.models.schemas import (
    EconomicEvent,
    EventImpact,
    MarketTrend,
    PatternType,
    TradeDirection,
    TradeSetup,
    VolatilityData,
    VolatilityLevel,
)


_PATTERN_EXPLAIN = {
    PatternType.BREAKOUT_UP: "Cassure de résistance : le prix vient de franchir un niveau qui bloquait jusqu'ici. Souvent suivie d'une accélération haussière.",
    PatternType.BREAKOUT_DOWN: "Cassure de support : le prix vient de perdre un niveau de protection. Accélération baissière probable.",
    PatternType.MOMENTUM_UP: "Momentum haussier : plusieurs bougies consécutives vertes avec du volume. Les acheteurs dominent.",
    PatternType.MOMENTUM_DOWN: "Momentum baissier : plusieurs bougies consécutives rouges avec du volume. Les vendeurs dominent.",
    PatternType.RANGE_BOUNCE_UP: "Rebond sur support : le prix revient sur un niveau d'achat historique. Opportunité d'entrer bas.",
    PatternType.RANGE_BOUNCE_DOWN: "Rejet sur résistance : le prix touche un plafond et échoue à passer. Opportunité d'entrer haut.",
    PatternType.MEAN_REVERSION_UP: "Retour à la moyenne : le prix s'était trop écarté vers le bas, il revient. Pari contrariant.",
    PatternType.MEAN_REVERSION_DOWN: "Retour à la moyenne : le prix s'était trop écarté vers le haut, il revient. Pari contrariant.",
    PatternType.ENGULFING_BULLISH: "Englobante haussière : une grosse bougie verte a totalement absorbé la précédente. Retournement probable.",
    PatternType.ENGULFING_BEARISH: "Englobante baissière : une grosse bougie rouge a totalement absorbé la précédente. Retournement probable.",
    PatternType.PIN_BAR_UP: "Pin bar haussière : longue mèche basse = rejet violent du prix bas. Signal d'achat.",
    PatternType.PIN_BAR_DOWN: "Pin bar baissière : longue mèche haute = rejet violent du prix haut. Signal de vente.",
}


def _active_sessions_utc(hour: int) -> list[str]:
    sessions = []
    if hour >= 22 or hour < 7: sessions.append("Sydney")
    if 0 <= hour < 9: sessions.append("Tokyo")
    if 8 <= hour < 17: sessions.append("London")
    if 13 <= hour < 22: sessions.append("New York")
    return sessions


def _is_best_session(pair: str, sessions: list[str]) -> tuple[bool, str]:
    """True si la session active est particulierement bonne pour cette paire."""
    overlap_eu_us = "London" in sessions and "New York" in sessions
    if overlap_eu_us:
        return True, "overlap London/New York (heure d'or du scalping)"
    if pair.startswith("EUR") or pair.startswith("GBP") or pair.endswith("EUR") or pair.endswith("GBP"):
        if "London" in sessions:
            return True, "session London (optimal pour les paires EUR/GBP)"
    if pair.startswith("USD") or pair.endswith("USD"):
        if "New York" in sessions:
            return True, "session New York (optimal pour les paires USD)"
    if pair.startswith("JPY") or pair.endswith("JPY"):
        if "Tokyo" in sessions:
            return True, "session Tokyo (optimal pour les paires JPY)"
    if pair == "XAU/USD":
        if "London" in sessions or "New York" in sessions:
            return True, "session active (London ou New York, bon pour l'or)"
    return False, f"session {', '.join(sessions) if sessions else 'marche peu actif'}"


def _nearby_high_impact_events(pair: str, events: list[EconomicEvent], minutes: int = 30) -> list[EconomicEvent]:
    """Evenements high impact dans les X min pour les devises de la paire."""
    currencies = set()
    for part in pair.split("/"):
        currencies.add(part)
    # Les events ont un format "HH:MM" sans date -> on suppose qu'ils sont proches
    relevant = [e for e in events if e.currency in currencies and e.impact == EventImpact.HIGH]
    return relevant[:3]


def generate_guidance(
    setup: TradeSetup,
    *,
    volatility: VolatilityData | None = None,
    trend: MarketTrend | None = None,
    events: list[EconomicEvent] | None = None,
) -> str:
    """Genere un texte en langage naturel expliquant le setup."""
    events = events or []
    pattern_desc = _PATTERN_EXPLAIN.get(setup.pattern.pattern, "Pattern technique detecte.")
    direction = "à la hausse" if setup.direction == TradeDirection.BUY else "à la baisse"
    direction_fr = "ACHAT" if setup.direction == TradeDirection.BUY else "VENTE"

    lines = [
        f"**{direction_fr} sur {setup.pair}** — {pattern_desc}",
        f"Le radar anticipe un mouvement {direction} jusqu'a {setup.take_profit_1:.4f} (TP1, R:R {setup.risk_reward_1:.1f}) voire {setup.take_profit_2:.4f} (TP2, R:R {setup.risk_reward_2:.1f}).",
    ]

    # Contexte volatilite
    if volatility:
        if volatility.level == VolatilityLevel.HIGH:
            lines.append(f"La volatilite est *elevee* ({volatility.volatility_ratio:.1f}x la moyenne), ce qui augmente l'amplitude attendue mais aussi le risque de whipsaw.")
        elif volatility.level == VolatilityLevel.MEDIUM:
            lines.append(f"La volatilite est *moderee* ({volatility.volatility_ratio:.1f}x), conditions normales de scalping.")
        else:
            lines.append(f"La volatilite est *basse* ({volatility.volatility_ratio:.1f}x) : le marche est calme, les mouvements peuvent etre plus lents que prevu.")

    # Contexte tendance
    if trend:
        trend_dir = trend.direction.value
        aligned = (
            (trend_dir == "bullish" and setup.direction == TradeDirection.BUY)
            or (trend_dir == "bearish" and setup.direction == TradeDirection.SELL)
        )
        if aligned:
            lines.append(f"La tendance de fond est {trend_dir} avec {int(trend.strength * 100)}% de force : le trade va dans le sens du flux.")
        elif trend_dir == "neutral":
            lines.append("Pas de tendance claire sur ce timeframe : le trade est contrarian, restez attentif aux retournements.")
        else:
            lines.append(f"⚠️ La tendance de fond est {trend_dir} alors que vous entrez dans le sens inverse : risque accru de rejet.")

    # Contexte news
    hi = _nearby_high_impact_events(setup.pair, events)
    if hi:
        ev_names = ", ".join(e.event_name for e in hi[:2])
        lines.append(f"⚠️ Evenements high-impact a surveiller : {ev_names}. Si news dans les 30 min, passer ce trade.")

    # Conseil SL
    lines.append(f"SL *obligatoire* a {setup.stop_loss:.4f} ({setup.risk_pips:.1f} pips de risque). Respectez-le meme si le prix flotte.")

    return "\n\n".join(lines)


def compute_verdict(
    setup: TradeSetup,
    *,
    volatility: VolatilityData | None = None,
    trend: MarketTrend | None = None,
    events: list[EconomicEvent] | None = None,
    now: datetime | None = None,
) -> dict:
    """Calcule un verdict TAKE / WAIT / SKIP avec raisons."""
    events = events or []
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []
    warnings: list[str] = []
    blockers: list[str] = []

    score = setup.confidence_score or 0.0

    # Score
    if score >= 85:
        reasons.append(f"Score tres eleve ({score:.0f}/100)")
    elif score >= 75:
        reasons.append(f"Score correct ({score:.0f}/100)")
    else:
        warnings.append(f"Score faible ({score:.0f}/100)")

    # Session
    active = _active_sessions_utc(now.hour)
    if not active:
        blockers.append("Marche ferme (pas de session active)")
    else:
        is_best, sess_label = _is_best_session(setup.pair, active)
        if is_best:
            reasons.append(f"Session favorable : {sess_label}")
        else:
            warnings.append(f"Session sous-optimale : {sess_label}")

    # Tendance
    if trend:
        trend_dir = trend.direction.value
        aligned = (
            (trend_dir == "bullish" and setup.direction == TradeDirection.BUY)
            or (trend_dir == "bearish" and setup.direction == TradeDirection.SELL)
        )
        if aligned and trend.strength >= 0.6:
            reasons.append(f"Tendance {trend_dir} alignee (force {int(trend.strength * 100)}%)")
        elif trend_dir != "neutral" and not aligned:
            warnings.append(f"Tendance contraire ({trend_dir} {int(trend.strength * 100)}%)")

    # Volatilite
    if volatility:
        if volatility.level == VolatilityLevel.HIGH and volatility.volatility_ratio > 2.5:
            warnings.append("Volatilite extreme : risque de whipsaw")
        elif volatility.level == VolatilityLevel.LOW:
            warnings.append("Volatilite basse : mouvement possiblement lent")

    # News
    hi = _nearby_high_impact_events(setup.pair, events)
    if hi:
        warnings.append(f"Evenement high-impact a surveiller : {hi[0].event_name}")

    # R:R
    if setup.risk_reward_1 < 1.0:
        warnings.append(f"R:R TP1 faible ({setup.risk_reward_1:.1f})")
    elif setup.risk_reward_1 >= 2.0:
        reasons.append(f"R:R TP1 excellent ({setup.risk_reward_1:.1f})")

    # Decision finale
    if blockers:
        action = "SKIP"
    elif score < 75 or len(warnings) >= 3:
        action = "SKIP"
    elif len(warnings) >= 1 and score < 85:
        action = "WAIT"
    else:
        action = "TAKE"

    action_label = {
        "TAKE": "✅ PRENDRE",
        "WAIT": "⏳ ATTENDRE",
        "SKIP": "⛔ PASSER",
    }[action]

    summary = {
        "TAKE": "Tous les feux sont verts. Passez l'ordre.",
        "WAIT": "Setup correct mais ambigu. Attendez confirmation (bougie suivante) ou passez.",
        "SKIP": "Trop de facteurs defavorables. Passez ce signal, il y en aura d'autres.",
    }[action]

    return {
        "action": action,
        "action_label": action_label,
        "summary": summary,
        "reasons": reasons,
        "warnings": warnings,
        "blockers": blockers,
    }
