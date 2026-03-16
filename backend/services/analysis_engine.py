"""Core analysis engine for scalping signal detection.

Combines volatility data (Mataf) and market context (Forex Factory)
to detect scalping opportunities and generate signals.
"""

import logging
from datetime import datetime, timezone

from backend.models.schemas import (
    EconomicEvent,
    EventImpact,
    MarketTrend,
    ScalpingSignal,
    SignalStrength,
    TradeSetup,
    TrendDirection,
    VolatilityData,
    VolatilityLevel,
)
from config.settings import TREND_STRENGTH_MIN

logger = logging.getLogger(__name__)


def analyze_trend(pair: str, volatility: VolatilityData, events: list[EconomicEvent]) -> MarketTrend:
    """Derive a market trend estimation for a pair.

    Uses volatility direction and economic event context to estimate
    the likely trend direction and strength.
    """
    now = datetime.now(timezone.utc)
    pair_currencies = _extract_currencies(pair)

    # Count high-impact events for each currency in the pair
    base_events = [e for e in events if e.currency in pair_currencies and e.impact == EventImpact.HIGH]

    # Determine trend direction from event bias
    direction = TrendDirection.NEUTRAL
    strength = 0.5

    if volatility.level == VolatilityLevel.HIGH:
        strength = 0.8
        # High volatility with high-impact events suggests strong directional move
        if base_events:
            # If actual > forecast for base currency, bullish
            for event in base_events:
                if event.actual and event.forecast:
                    try:
                        actual_val = _parse_number(event.actual)
                        forecast_val = _parse_number(event.forecast)
                        if actual_val > forecast_val:
                            direction = TrendDirection.BULLISH
                            strength = min(0.9, strength + 0.1)
                        elif actual_val < forecast_val:
                            direction = TrendDirection.BEARISH
                            strength = min(0.9, strength + 0.1)
                    except ValueError:
                        pass
        else:
            # High volatility without events = momentum-based
            if volatility.volatility_ratio > 1.8:
                direction = TrendDirection.BULLISH  # Strong momentum
                strength = 0.85
    elif volatility.level == VolatilityLevel.MEDIUM:
        strength = 0.6

    description = _build_trend_description(pair, direction, strength, volatility, base_events)

    return MarketTrend(
        pair=pair,
        direction=direction,
        strength=round(strength, 2),
        description=description,
        updated_at=now,
    )


def detect_signals(
    volatility_data: list[VolatilityData],
    events: list[EconomicEvent],
    trends: list[MarketTrend],
    trade_setups: list[TradeSetup] | None = None,
) -> list[ScalpingSignal]:
    """Détecte les opportunités de scalping en combinant toutes les sources.

    Un signal est généré quand :
    1. Volatilité moyenne ou haute (le marché bouge)
    2. Force de tendance suffisante
    3. Pattern détecté avec un trade setup valide (si disponible)
    """
    signals: list[ScalpingSignal] = []
    now = datetime.now(timezone.utc)

    trade_setups = trade_setups or []
    setup_map: dict[str, list[TradeSetup]] = {}
    for setup in trade_setups:
        setup_map.setdefault(setup.pair, []).append(setup)

    trend_map = {t.pair: t for t in trends}

    for vol in volatility_data:
        trend = trend_map.get(vol.pair)
        if not trend:
            continue

        pair_currencies = _extract_currencies(vol.pair)
        nearby = [
            e for e in events
            if e.currency in pair_currencies and e.impact == EventImpact.HIGH
        ]

        pair_setups = setup_map.get(vol.pair, [])

        # Si on a des trade setups avec patterns, créer un signal pour chaque
        if pair_setups:
            # Prendre le meilleur setup (confiance la plus haute)
            best_setup = max(pair_setups, key=lambda s: s.pattern.confidence)

            signal_strength = _calculate_signal_strength(vol, trend, nearby)

            # Booster le signal si le pattern a une bonne confiance
            if best_setup.pattern.confidence >= 0.7 and signal_strength == SignalStrength.MODERATE:
                signal_strength = SignalStrength.STRONG
            elif best_setup.pattern.confidence >= 0.6 and signal_strength == SignalStrength.WEAK:
                signal_strength = SignalStrength.MODERATE

            message = _build_signal_message(vol, trend, signal_strength, nearby)

            signals.append(ScalpingSignal(
                pair=vol.pair,
                signal_strength=signal_strength,
                volatility=vol,
                trend=trend,
                nearby_events=nearby,
                trade_setup=best_setup,
                message=message,
                timestamp=now,
            ))
        elif vol.level != VolatilityLevel.LOW and trend.strength >= TREND_STRENGTH_MIN:
            # Pas de pattern, mais volatilité + tendance suffisantes
            signal_strength = _calculate_signal_strength(vol, trend, nearby)
            message = _build_signal_message(vol, trend, signal_strength, nearby)

            signals.append(ScalpingSignal(
                pair=vol.pair,
                signal_strength=signal_strength,
                volatility=vol,
                trend=trend,
                nearby_events=nearby,
                message=message,
                timestamp=now,
            ))

    # Trier par force de signal (fort en premier)
    strength_order = {SignalStrength.STRONG: 0, SignalStrength.MODERATE: 1, SignalStrength.WEAK: 2}
    signals.sort(key=lambda s: strength_order.get(s.signal_strength, 3))

    return signals


def _calculate_signal_strength(
    vol: VolatilityData,
    trend: MarketTrend,
    nearby_events: list[EconomicEvent],
) -> SignalStrength:
    """Calculate signal strength from volatility, trend, and event proximity."""
    score = 0.0

    # Volatility contribution (0-40 points)
    if vol.level == VolatilityLevel.HIGH:
        score += 40
    elif vol.level == VolatilityLevel.MEDIUM:
        score += 20

    # Trend contribution (0-40 points)
    score += trend.strength * 40

    # Event penalty: imminent high-impact events add risk
    # But also opportunity if the event just happened
    if nearby_events:
        events_with_actual = [e for e in nearby_events if e.actual]
        if events_with_actual:
            score += 10  # Event already released = opportunity
        else:
            score -= 15  # Upcoming event = risk

    if score >= 60:
        return SignalStrength.STRONG
    elif score >= 40:
        return SignalStrength.MODERATE
    return SignalStrength.WEAK


def _build_signal_message(
    vol: VolatilityData,
    trend: MarketTrend,
    strength: SignalStrength,
    nearby_events: list[EconomicEvent],
) -> str:
    """Build a human-readable notification message."""
    strength_label = {
        SignalStrength.STRONG: "FORT",
        SignalStrength.MODERATE: "MODERE",
        SignalStrength.WEAK: "FAIBLE",
    }

    direction_label = {
        "bullish": "HAUSSIER",
        "bearish": "BAISSIER",
        "neutral": "NEUTRE",
    }

    vol_label = {"high": "haute", "medium": "moyenne", "low": "basse"}

    direction = direction_label.get(trend.direction.value, trend.direction.value.upper())
    vol_level = vol_label.get(vol.level.value, vol.level.value)

    msg = (
        f"[{strength_label[strength]}] Opportunite scalping sur {vol.pair} - "
        f"Volatilite: {vol_level} ({vol.volatility_ratio:.1f}x moy) | "
        f"Tendance: {direction} (force: {trend.strength:.0%})"
    )

    if nearby_events:
        event_names = ", ".join(e.event_name for e in nearby_events[:2])
        msg += f" | Attention: {event_names}"

    return msg


def _build_trend_description(
    pair: str,
    direction: TrendDirection,
    strength: float,
    vol: VolatilityData,
    events: list[EconomicEvent],
) -> str:
    """Build a description of the trend analysis."""
    parts = [f"{pair}: {direction.value} trend"]
    parts.append(f"strength {strength:.0%}")
    parts.append(f"volatility {vol.level.value} ({vol.volatility_ratio:.1f}x)")

    if events:
        parts.append(f"{len(events)} high-impact event(s) affecting this pair")

    return " | ".join(parts)


def _extract_currencies(pair: str) -> set[str]:
    """Extract the two currencies from a pair like EUR/USD.

    For commodities like XAU/USD (gold), maps XAU to USD since
    gold is primarily affected by USD-related economic events.
    """
    parts = pair.replace("/", "").strip()
    currencies = set()
    if len(parts) >= 6:
        currencies = {parts[:3], parts[3:6]}

    # Commodities are affected by their quote currency's events
    # XAU (gold), XAG (silver) → impacted by USD events
    COMMODITY_CURRENCY_MAP = {"XAU": "USD", "XAG": "USD", "XPT": "USD"}
    for commodity, related in COMMODITY_CURRENCY_MAP.items():
        if commodity in currencies:
            currencies.add(related)

    return currencies


def _parse_number(text: str) -> float:
    """Parse a number from text like '180K', '5.25%', etc."""
    cleaned = text.replace("%", "").replace(",", "").strip()
    multiplier = 1.0
    if cleaned.upper().endswith("K"):
        multiplier = 1000
        cleaned = cleaned[:-1]
    elif cleaned.upper().endswith("M"):
        multiplier = 1_000_000
        cleaned = cleaned[:-1]
    elif cleaned.upper().endswith("B"):
        multiplier = 1_000_000_000
        cleaned = cleaned[:-1]
    return float(cleaned) * multiplier
