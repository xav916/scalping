"""Core analysis engine for scalping signal detection.

Combines volatility data (Mataf) and market context (Forex Factory)
to detect scalping opportunities and generate signals.
"""

import logging
from datetime import datetime, timezone

from backend.models.macro_schemas import MacroContext
from backend.models.schemas import (
    ConfidenceFactor,
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
from backend.services import macro_context_service, macro_scoring
from config.settings import (
    EARNINGS_VETO_ENABLED,
    GEOPOLITICAL_VETO_ENABLED,
    MACRO_SCORING_ENABLED,
    MACRO_VETO_ENABLED,
    MIN_CONFIDENCE_SCORE,
    RISK_PER_TRADE_PCT,
    TRADING_CAPITAL,
    TREND_STRENGTH_MIN,
    asset_class_for,
)

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

            sig_score, sig_factors, sig_expl = _build_signal_confidence(
                vol, trend, nearby, signal_strength, best_setup,
            )

            signals.append(ScalpingSignal(
                pair=vol.pair,
                signal_strength=signal_strength,
                volatility=vol,
                trend=trend,
                nearby_events=nearby,
                trade_setup=best_setup,
                message=message,
                timestamp=now,
                confidence_score=sig_score,
                confidence_factors=sig_factors,
                explanation=sig_expl,
            ))
        elif vol.level != VolatilityLevel.LOW and trend.strength >= TREND_STRENGTH_MIN:
            # Pas de pattern, mais volatilité + tendance suffisantes
            signal_strength = _calculate_signal_strength(vol, trend, nearby)
            message = _build_signal_message(vol, trend, signal_strength, nearby)

            sig_score, sig_factors, sig_expl = _build_signal_confidence(
                vol, trend, nearby, signal_strength, None,
            )

            signals.append(ScalpingSignal(
                pair=vol.pair,
                signal_strength=signal_strength,
                volatility=vol,
                trend=trend,
                nearby_events=nearby,
                message=message,
                timestamp=now,
                confidence_score=sig_score,
                confidence_factors=sig_factors,
                explanation=sig_expl,
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


def _build_signal_confidence(
    vol: VolatilityData,
    trend: MarketTrend,
    nearby_events: list[EconomicEvent],
    strength: SignalStrength,
    setup: TradeSetup | None,
) -> tuple[float, list[ConfidenceFactor], str]:
    """Calcule le score de confiance pour un signal de scalping."""
    factors: list[ConfidenceFactor] = []

    # ── 1. Volatilité (0-30 pts) ──
    if vol.level == VolatilityLevel.HIGH:
        v_score = 30
        v_detail = f"Volatilite haute ({vol.volatility_ratio:.1f}x moyenne) — le marche bouge, conditions ideales pour le scalping"
    elif vol.level == VolatilityLevel.MEDIUM:
        v_score = 18
        v_detail = f"Volatilite moyenne ({vol.volatility_ratio:.1f}x) — mouvements suffisants mais prudence"
    else:
        v_score = 5
        v_detail = f"Volatilite basse ({vol.volatility_ratio:.1f}x) — marche trop calme pour du scalping efficace"
    factors.append(ConfidenceFactor(name="Volatilite", score=round(v_score, 1), detail=v_detail, positive=v_score >= 18))

    # ── 2. Tendance (0-30 pts) ──
    dir_labels = {"bullish": "haussiere", "bearish": "baissiere", "neutral": "neutre"}
    t_label = dir_labels.get(trend.direction.value, trend.direction.value)
    if trend.direction != TrendDirection.NEUTRAL:
        t_score = trend.strength * 30
        t_detail = f"Tendance {t_label} avec force de {trend.strength:.0%} — direction claire du marche"
    else:
        t_score = 8
        t_detail = "Marche neutre — pas de biais directionnel clair, scalping plus risque"
    factors.append(ConfidenceFactor(name="Tendance", score=round(t_score, 1), detail=t_detail, positive=t_score >= 15))

    # ── 3. Contexte éco (0-20 pts) ──
    if not nearby_events:
        e_score = 20
        e_detail = "Aucun evenement eco majeur imminent — environnement calme et previsible"
    else:
        events_with_actual = [e for e in nearby_events if e.actual]
        if events_with_actual:
            e_score = 15
            e_detail = f"Evenement publie ({events_with_actual[0].event_name}) — opportunite de reaction du marche"
        else:
            e_score = 0
            e_detail = f"ATTENTION: evenement a venir ({nearby_events[0].event_name}) — risque de pic de volatilite imprevisible"
    factors.append(ConfidenceFactor(name="Contexte eco", score=round(e_score, 1), detail=e_detail, positive=e_score >= 10))

    # ── 4. Setup de trade (0-20 pts) ──
    if setup:
        s_score = min(20, setup.confidence_score * 0.2)
        s_detail = f"Setup {setup.direction.value.upper()} avec pattern {_pattern_short_name(setup.pattern.pattern)} (confiance setup: {setup.confidence_score:.0f}/100)"
        factors.append(ConfidenceFactor(name="Trade setup", score=round(s_score, 1), detail=s_detail, positive=s_score >= 12))
    else:
        factors.append(ConfidenceFactor(name="Trade setup", score=0, detail="Pas de setup de trade associe — signal base uniquement sur volatilite et tendance", positive=False))

    total = min(100, max(0, sum(f.score for f in factors)))

    # Explication
    strength_labels = {SignalStrength.STRONG: "FORT", SignalStrength.MODERATE: "MODERE", SignalStrength.WEAK: "FAIBLE"}
    pos = [f for f in factors if f.positive]
    neg = [f for f in factors if not f.positive]

    parts = [
        f"Signal {strength_labels.get(strength, '?')} sur {vol.pair} — score de confiance: {total:.0f}/100",
        "",
        "ANALYSE DU SIGNAL :",
    ]
    for f in pos:
        parts.append(f"  + {f.name}: {f.detail}")
    if neg:
        parts.append("")
        parts.append("POINTS DE VIGILANCE :")
        for f in neg:
            parts.append(f"  - {f.name}: {f.detail}")

    return round(total, 1), factors, "\n".join(parts)


def _pattern_short_name(pattern) -> str:
    """Nom court français pour les messages."""
    names = {
        "breakout_up": "Cassure resistance",
        "breakout_down": "Cassure support",
        "momentum_up": "Momentum haussier",
        "momentum_down": "Momentum baissier",
        "range_bounce_up": "Rebond support",
        "range_bounce_down": "Rejet resistance",
        "mean_reversion_up": "Retour moyenne",
        "mean_reversion_down": "Retour moyenne",
        "engulfing_bullish": "Englobante haussiere",
        "engulfing_bearish": "Englobante baissiere",
        "pin_bar_up": "Pin bar haussiere",
        "pin_bar_down": "Pin bar baissiere",
    }
    p_val = pattern.value if hasattr(pattern, 'value') else str(pattern)
    return names.get(p_val, p_val)


def enrich_trade_setup(
    setup: TradeSetup,
    volatility: VolatilityData | None,
    trend: MarketTrend | None,
    events: list[EconomicEvent],
) -> TradeSetup:
    """Enrichit un trade setup avec score de confiance, explications et money management."""
    # Stamp asset class if missing (default "forex")
    if not getattr(setup, "asset_class", None) or setup.asset_class == "forex":
        setup.asset_class = asset_class_for(setup.pair)

    factors: list[ConfidenceFactor] = []

    # ── 1. Score pattern (0-30 pts) ──
    pattern_conf = setup.pattern.confidence
    pattern_score = pattern_conf * 30
    factors.append(ConfidenceFactor(
        name="Pattern",
        score=round(pattern_score, 1),
        detail=f"{setup.pattern.description} (confiance pattern: {pattern_conf:.0%})",
        positive=pattern_conf >= 0.6,
    ))

    # ── 2. Score risk/reward (0-25 pts) ──
    rr = setup.risk_reward_1
    if rr >= 2.0:
        rr_score = 25
        rr_detail = f"Excellent ratio R:R de {rr:.1f} (risque {setup.risk_pips:.2f} pour gain {setup.reward_pips_1:.2f})"
    elif rr >= 1.5:
        rr_score = 18
        rr_detail = f"Bon ratio R:R de {rr:.1f}"
    elif rr >= 1.0:
        rr_score = 10
        rr_detail = f"Ratio R:R acceptable de {rr:.1f}"
    else:
        rr_score = 0
        rr_detail = f"Ratio R:R insuffisant ({rr:.1f}) — risque > recompense"
    factors.append(ConfidenceFactor(
        name="Risk/Reward",
        score=round(rr_score, 1),
        detail=rr_detail,
        positive=rr >= 1.5,
    ))

    # ── 3. Score volatilité (0-20 pts) ──
    vol_score = 0.0
    if volatility:
        if volatility.level == VolatilityLevel.HIGH:
            vol_score = 20
            vol_detail = f"Volatilite haute ({volatility.volatility_ratio:.1f}x moyenne) — mouvement en cours"
        elif volatility.level == VolatilityLevel.MEDIUM:
            vol_score = 12
            vol_detail = f"Volatilite moyenne ({volatility.volatility_ratio:.1f}x) — conditions correctes"
        else:
            vol_score = 3
            vol_detail = f"Volatilite basse ({volatility.volatility_ratio:.1f}x) — marche calme, risque de faux signal"
    else:
        vol_detail = "Donnees de volatilite indisponibles"
    factors.append(ConfidenceFactor(
        name="Volatilite",
        score=round(vol_score, 1),
        detail=vol_detail,
        positive=vol_score >= 12,
    ))

    # ── 4. Score tendance (0-15 pts) ──
    trend_score = 0.0
    if trend:
        is_aligned = (
            (trend.direction == TrendDirection.BULLISH and setup.direction.value == "buy")
            or (trend.direction == TrendDirection.BEARISH and setup.direction.value == "sell")
        )
        if is_aligned:
            trend_score = trend.strength * 15
            trend_detail = f"Tendance alignee ({trend.direction.value}, force {trend.strength:.0%}) — trade dans le sens du marche"
        elif trend.direction == TrendDirection.NEUTRAL:
            trend_score = 5
            trend_detail = "Marche neutre — pas de confirmation directionnelle"
        else:
            trend_score = 0
            trend_detail = f"ATTENTION: trade contre-tendance ({trend.direction.value}, force {trend.strength:.0%})"
    else:
        trend_detail = "Donnees de tendance indisponibles"
    factors.append(ConfidenceFactor(
        name="Tendance",
        score=round(trend_score, 1),
        detail=trend_detail,
        positive=trend_score >= 8,
    ))

    # ── 5. Score contexte éco (0-10 pts) ──
    pair_currencies = _extract_currencies(setup.pair)
    relevant_events = [e for e in events if e.currency in pair_currencies and e.impact == EventImpact.HIGH]

    if not relevant_events:
        eco_score = 10
        eco_detail = "Aucun evenement eco majeur imminent — environnement calme"
    else:
        events_with_actual = [e for e in relevant_events if e.actual]
        if events_with_actual:
            eco_score = 8
            eco_detail = f"Evenement publie ({events_with_actual[0].event_name}) — reaction du marche en cours"
        else:
            eco_score = 0
            eco_detail = f"ATTENTION: evenement a venir ({relevant_events[0].event_name}) — risque de retournement"
    factors.append(ConfidenceFactor(
        name="Contexte eco",
        score=round(eco_score, 1),
        detail=eco_detail,
        positive=eco_score >= 5,
    ))

    # ── Score global ──
    total_score = sum(f.score for f in factors)
    total_score = min(100, max(0, total_score))

    # ── Money management ──
    risk_amount = TRADING_CAPITAL * (RISK_PER_TRADE_PCT / 100)
    if setup.risk_pips > 0:
        # Position size basée sur le risque accepté
        position_size = risk_amount / setup.risk_pips
        suggested_amount = round(position_size * setup.entry_price, 2)
        estimated_gain_1 = round(position_size * setup.reward_pips_1, 2)
        estimated_gain_2 = round(position_size * setup.reward_pips_2, 2)
    else:
        suggested_amount = 0
        estimated_gain_1 = 0
        estimated_gain_2 = 0

    # ── Explication ──
    dir_label = "ACHAT" if setup.direction.value == "buy" else "VENTE"
    positive_factors = [f for f in factors if f.positive]
    negative_factors = [f for f in factors if not f.positive]

    explanation_parts = [
        f"Signal de {dir_label} sur {setup.pair} avec un score de confiance de {total_score:.0f}/100.",
        "",
        "POURQUOI CE SIGNAL :",
    ]
    for f in positive_factors:
        explanation_parts.append(f"  + {f.name}: {f.detail}")
    if negative_factors:
        explanation_parts.append("")
        explanation_parts.append("POINTS DE VIGILANCE :")
        for f in negative_factors:
            explanation_parts.append(f"  - {f.name}: {f.detail}")

    explanation_parts.extend([
        "",
        f"MONEY MANAGEMENT (capital: {TRADING_CAPITAL:.0f} USD, risque: {RISK_PER_TRADE_PCT}%):",
        f"  Montant a risquer: {risk_amount:.2f} USD",
        f"  Taille position suggeree: {suggested_amount:.2f} USD",
        f"  Gain estime TP1: +{estimated_gain_1:.2f} USD (R:R {setup.risk_reward_1:.1f})",
        f"  Gain estime TP2: +{estimated_gain_2:.2f} USD (R:R {setup.risk_reward_2:.1f})",
        f"  Perte max: -{risk_amount:.2f} USD",
    ])

    explanation = "\n".join(explanation_parts)

    # Mettre à jour le setup
    setup.confidence_score = round(total_score, 1)
    setup.confidence_factors = factors
    setup.explanation = explanation
    setup.suggested_amount = suggested_amount
    setup.risk_amount = round(risk_amount, 2)
    setup.estimated_gain_1 = estimated_gain_1
    setup.estimated_gain_2 = estimated_gain_2

    # ── Macro context enrichment (Vague 1) ─────────────────────────────
    if MACRO_SCORING_ENABLED:
        snapshot: MacroContext | None = macro_context_service.get_macro_snapshot()
        if snapshot is not None and macro_context_service.is_fresh(snapshot.fetched_at):
            try:
                multiplier, veto, primaries = macro_scoring.apply(
                    setup.pair, setup.direction.value, snapshot
                )
                reason_texts = [p["reason"] for p in primaries] if primaries else []
                factor_score = round((multiplier - 1.0) * 100, 1)
                factors.append(
                    ConfidenceFactor(
                        name="Contexte macro",
                        score=factor_score,
                        detail=f"×{multiplier:.2f} — " + (" | ".join(reason_texts) if reason_texts else "neutre"),
                        positive=multiplier >= 1.0,
                        source="macro",
                        metadata={"primaries": primaries, "multiplier": multiplier, "veto": veto},
                    )
                )
                new_total = min(100, max(0, total_score * multiplier))
                setup.confidence_score = round(new_total, 1)
                setup.confidence_factors = factors

                if MACRO_VETO_ENABLED and veto:
                    setup.verdict_action = "SKIP"
                    blockers = list(setup.verdict_blockers or [])
                    veto_reasons = [p["reason"] for p in primaries if p["is_veto"]]
                    blockers.extend([f"Macro veto: {r}" for r in veto_reasons])
                    setup.verdict_blockers = blockers
                logger.info(
                    f"macro_applied pair={setup.pair} dir={setup.direction.value} "
                    f"base={round(total_score, 1)} mult={multiplier} "
                    f"final={setup.confidence_score} veto={veto}"
                )
            except Exception as e:
                logger.warning(f"macro scoring error: {e}")
        else:
            logger.debug("macro: snapshot stale or missing, neutral mode")

    # ── Binance funding rate scoring (Phase 2 Palier 2 chantier #2 — 2026-06-18)
    # Filtre contrarien soft : si funding extrême + direction surcrowdée,
    # multiplier 0.85 disqualifie les setups borderline. Crypto uniquement.
    # Feature-flagged via BINANCE_FUNDING_SCORING_ENABLED env var.
    try:
        from config.settings import BINANCE_FUNDING_SCORING_ENABLED
    except Exception:
        BINANCE_FUNDING_SCORING_ENABLED = False
    if BINANCE_FUNDING_SCORING_ENABLED:
        try:
            from backend.services import binance_funding_scoring
            fund_mult, fund_reason = binance_funding_scoring.apply_funding_filter(
                setup.pair, setup.direction.value
            )
            if fund_mult != 1.0:
                prev_score = setup.confidence_score
                new_score = round(min(100, max(0, prev_score * fund_mult)), 1)
                setup.confidence_score = new_score
                factors.append(
                    ConfidenceFactor(
                        name="Funding rate Binance",
                        score=round((fund_mult - 1.0) * 100, 1),
                        detail=f"×{fund_mult:.2f} — {fund_reason}",
                        positive=False,
                        source="microstructure",
                        metadata={"multiplier": fund_mult, "reason": fund_reason},
                    )
                )
                setup.confidence_factors = factors
                logger.info(
                    f"funding_applied pair={setup.pair} dir={setup.direction.value} "
                    f"prev={prev_score} mult={fund_mult} final={new_score} reason={fund_reason}"
                )
        except Exception as e:
            logger.debug(f"funding scoring error: {e}")

    # ── Binance Long/Short Account Ratio scoring (chantier #3 — 2026-06-18)
    # Filtre contrarien soft complémentaire au funding (chantier #2) : mesure
    # la concentration des comptes long vs short. Soft veto ×0.85 si la
    # direction du setup est déjà surcrowdée côté retail.
    try:
        from config.settings import BINANCE_LSR_SCORING_ENABLED
    except Exception:
        BINANCE_LSR_SCORING_ENABLED = False
    if BINANCE_LSR_SCORING_ENABLED:
        try:
            from backend.services import binance_lsr_scoring
            lsr_mult, lsr_reason = binance_lsr_scoring.apply_lsr_filter(
                setup.pair, setup.direction.value
            )
            if lsr_mult != 1.0:
                prev_score = setup.confidence_score
                new_score = round(min(100, max(0, prev_score * lsr_mult)), 1)
                setup.confidence_score = new_score
                factors.append(
                    ConfidenceFactor(
                        name="LSR Binance",
                        score=round((lsr_mult - 1.0) * 100, 1),
                        detail=f"×{lsr_mult:.2f} — {lsr_reason}",
                        positive=False,
                        source="microstructure",
                        metadata={"multiplier": lsr_mult, "reason": lsr_reason},
                    )
                )
                setup.confidence_factors = factors
                logger.info(
                    f"lsr_applied pair={setup.pair} dir={setup.direction.value} "
                    f"prev={prev_score} mult={lsr_mult} final={new_score} reason={lsr_reason}"
                )
        except Exception as e:
            logger.debug(f"lsr scoring error: {e}")

    # ── Binance order book depth scoring (chantier #4 — 2026-06-18)
    # Mesure le spread relatif top-of-book Binance. Si élargi (>5 bps par
    # défaut), marché thin = slippage attendu, soft veto ×0.85 sur cryptos.
    try:
        from config.settings import BINANCE_ORDERBOOK_SCORING_ENABLED
    except Exception:
        BINANCE_ORDERBOOK_SCORING_ENABLED = False
    if BINANCE_ORDERBOOK_SCORING_ENABLED:
        try:
            from backend.services import binance_orderbook_scoring
            ob_mult, ob_reason = binance_orderbook_scoring.apply_orderbook_filter(
                setup.pair, setup.direction.value
            )
            if ob_mult != 1.0:
                prev_score = setup.confidence_score
                new_score = round(min(100, max(0, prev_score * ob_mult)), 1)
                setup.confidence_score = new_score
                factors.append(
                    ConfidenceFactor(
                        name="Order book Binance",
                        score=round((ob_mult - 1.0) * 100, 1),
                        detail=f"×{ob_mult:.2f} — {ob_reason}",
                        positive=False,
                        source="microstructure",
                        metadata={"multiplier": ob_mult, "reason": ob_reason},
                    )
                )
                setup.confidence_factors = factors
                logger.info(
                    f"orderbook_applied pair={setup.pair} dir={setup.direction.value} "
                    f"prev={prev_score} mult={ob_mult} final={new_score} reason={ob_reason}"
                )
        except Exception as e:
            logger.debug(f"orderbook scoring error: {e}")

    # ── Binance aggressor side / orderflow scoring (chantier #5 — 2026-06-18)
    # Mesure quel camp frappe le carnet à market (taker buy vs sell ratio).
    # Soft veto ×0.85 si momentum aggressor opposé à la direction du setup.
    try:
        from config.settings import BINANCE_ORDERFLOW_SCORING_ENABLED
    except Exception:
        BINANCE_ORDERFLOW_SCORING_ENABLED = False
    if BINANCE_ORDERFLOW_SCORING_ENABLED:
        try:
            from backend.services import binance_orderflow_scoring
            of_mult, of_reason = binance_orderflow_scoring.apply_orderflow_filter(
                setup.pair, setup.direction.value
            )
            if of_mult != 1.0:
                prev_score = setup.confidence_score
                new_score = round(min(100, max(0, prev_score * of_mult)), 1)
                setup.confidence_score = new_score
                factors.append(
                    ConfidenceFactor(
                        name="Orderflow Binance",
                        score=round((of_mult - 1.0) * 100, 1),
                        detail=f"×{of_mult:.2f} — {of_reason}",
                        positive=False,
                        source="microstructure",
                        metadata={"multiplier": of_mult, "reason": of_reason},
                    )
                )
                setup.confidence_factors = factors
                logger.info(
                    f"orderflow_applied pair={setup.pair} dir={setup.direction.value} "
                    f"prev={prev_score} mult={of_mult} final={new_score} reason={of_reason}"
                )
        except Exception as e:
            logger.debug(f"orderflow scoring error: {e}")

    # ── Binance Open Interest divergence scoring (chantier #6 — 2026-06-18)
    # Compare le delta OI 1h avec le delta prix 1h pour détecter les
    # mouvements épuisés (short squeeze, liquidation longs). Soft veto ×0.85
    # quand le setup vise dans la direction d'un mouvement déjà fini.
    try:
        from config.settings import BINANCE_OI_SCORING_ENABLED
    except Exception:
        BINANCE_OI_SCORING_ENABLED = False
    if BINANCE_OI_SCORING_ENABLED:
        try:
            from backend.services import binance_oi_scoring
            oi_mult, oi_reason = binance_oi_scoring.apply_oi_filter(
                setup.pair, setup.direction.value
            )
            if oi_mult != 1.0:
                prev_score = setup.confidence_score
                new_score = round(min(100, max(0, prev_score * oi_mult)), 1)
                setup.confidence_score = new_score
                factors.append(
                    ConfidenceFactor(
                        name="Open Interest Binance",
                        score=round((oi_mult - 1.0) * 100, 1),
                        detail=f"×{oi_mult:.2f} — {oi_reason}",
                        positive=False,
                        source="microstructure",
                        metadata={"multiplier": oi_mult, "reason": oi_reason},
                    )
                )
                setup.confidence_factors = factors
                logger.info(
                    f"oi_applied pair={setup.pair} dir={setup.direction.value} "
                    f"prev={prev_score} mult={oi_mult} final={new_score} reason={oi_reason}"
                )
        except Exception as e:
            logger.debug(f"oi scoring error: {e}")

    # ── Multi-timeframe alignment (Tier 2 chantier #14) ────────────────
    try:
        from config.settings import BINANCE_MTF_SCORING_ENABLED
    except Exception:
        BINANCE_MTF_SCORING_ENABLED = False
    if BINANCE_MTF_SCORING_ENABLED:
        try:
            from backend.services import binance_mtf_scoring
            mtf_mult, mtf_reason = binance_mtf_scoring.apply_mtf_filter(
                setup.pair, setup.direction.value
            )
            if mtf_mult != 1.0:
                prev_score = setup.confidence_score
                new_score = round(min(100, max(0, prev_score * mtf_mult)), 1)
                setup.confidence_score = new_score
                factors.append(
                    ConfidenceFactor(
                        name="Multi-timeframe Binance",
                        score=round((mtf_mult - 1.0) * 100, 1),
                        detail=f"×{mtf_mult:.2f} — {mtf_reason}",
                        positive=False,
                        source="microstructure",
                        metadata={"multiplier": mtf_mult, "reason": mtf_reason},
                    )
                )
                setup.confidence_factors = factors
                logger.info(
                    f"mtf_applied pair={setup.pair} dir={setup.direction.value} "
                    f"prev={prev_score} mult={mtf_mult} final={new_score} reason={mtf_reason}"
                )
        except Exception as e:
            logger.debug(f"mtf scoring error: {e}")

    # ── VIX regime veto (Gap 1 MVP — 2026-08-02) ───────────────────────
    # Soft veto multiplicateur sur signaux equity/equity_index selon régime
    # de volatilité implicite S&P500. Calme(×1.0) modéré(×0.95)
    # stress(×0.85) panique(×0.70). No-op sur crypto/forex/metal/energy.
    # Feature-flagged via VIX_SCORING_ENABLED env var (défaut: true).
    try:
        from config.settings import VIX_SCORING_ENABLED
    except Exception:
        VIX_SCORING_ENABLED = False
    if VIX_SCORING_ENABLED:
        try:
            from backend.services import vix_scoring
            vix_new_score, vix_meta = vix_scoring.apply_vix_veto(
                setup.pair, setup.direction.value, setup.confidence_score
            )
            if vix_meta and vix_meta.get("vix_multiplier", 1.0) != 1.0:
                prev_score = setup.confidence_score
                setup.confidence_score = vix_new_score
                mult = vix_meta["vix_multiplier"]
                regime = vix_meta.get("vix_regime", "?")
                vix_val = vix_meta.get("vix_value", 0)
                factors.append(
                    ConfidenceFactor(
                        name="VIX regime",
                        score=round((mult - 1.0) * 100, 1),
                        detail=(
                            f"×{mult:.2f} — VIX {vix_val:.1f} "
                            f"régime {regime}"
                        ),
                        positive=False,
                        source="macro",
                        metadata=vix_meta,
                    )
                )
                setup.confidence_factors = factors
                logger.info(
                    f"vix_applied pair={setup.pair} dir={setup.direction.value} "
                    f"vix={vix_val:.1f} regime={regime} mult={mult} "
                    f"prev={prev_score} final={vix_new_score}"
                )
        except Exception as e:
            logger.debug(f"vix scoring error: {e}")

    # ── Earnings calendar veto (P2 — 2026-08-03) ──────────────────────────
    # Soft veto ×0.60 si earnings dans les 24h à venir (incertitude forte),
    # ×0.70 si earnings dans les 24h passées (volatilité résiduelle post-annonce).
    # Applicable uniquement aux asset_class == "equity" (actions individuelles :
    # AAPL/TSLA/NVDA/MSFT/etc.). No-op sur indices/crypto/forex/metal/energy.
    # Feature-flagged via EARNINGS_VETO_ENABLED env var (défaut: true).
    if EARNINGS_VETO_ENABLED:
        try:
            from backend.services import earnings_veto
            prev_score = setup.confidence_score
            ev_new_score, ev_meta = earnings_veto.apply_earnings_veto(
                setup.pair, setup.direction.value, prev_score
            )
            ev_mult = ev_meta.get("multiplier", 1.0)
            if ev_mult != 1.0:
                setup.confidence_score = ev_new_score
                veto_dir = ev_meta.get("veto_direction", "?")
                hours = ev_meta.get("hours_delta", 0)
                symbol = ev_meta.get("symbol", setup.pair)
                earnings_at = ev_meta.get("earnings_at", "?")
                label = f"dans {hours:.0f}h" if veto_dir == "before" else f"il y a {hours:.0f}h"
                factors.append(
                    ConfidenceFactor(
                        name="Earnings veto",
                        score=round((ev_mult - 1.0) * 100, 1),
                        detail=(
                            f"×{ev_mult:.2f} — {symbol} earnings {label} "
                            f"({veto_dir})"
                        ),
                        positive=False,
                        source="macro",
                        metadata=ev_meta,
                    )
                )
                setup.confidence_factors = factors
                logger.info(
                    f"earnings_veto_applied pair={setup.pair} dir={setup.direction.value} "
                    f"symbol={symbol} veto={veto_dir} hours={hours} "
                    f"earnings_at={earnings_at} mult={ev_mult} "
                    f"prev={prev_score} final={ev_new_score}"
                )
        except Exception as e:
            logger.debug(f"earnings veto error: {e}")

    # ── Kraken Futures funding rate scoring (Gap 2 — 2026-08-02) ─────────
    # Miroir du filtre Binance funding mais source native Kraken Futures.
    # Appliqué pour TOUS les setups crypto (pas seulement admin_kraken) car
    # enrich_trade_setup est appelé une fois avant le routage multi-destination.
    # Le veto Kraken s'empile sur les vetos Binance (le plus sévère l'emporte).
    try:
        from config.settings import KRAKEN_FUNDING_SCORING_ENABLED
    except Exception:
        KRAKEN_FUNDING_SCORING_ENABLED = False
    if KRAKEN_FUNDING_SCORING_ENABLED:
        try:
            from backend.services import kraken_funding_scoring
            prev_score = setup.confidence_score
            new_score, kf_meta = kraken_funding_scoring.apply_kraken_funding(
                setup.pair, setup.direction.value, prev_score
            )
            kf_mult = kf_meta.get("multiplier", 1.0)
            kf_reason = kf_meta.get("reason")
            if kf_mult != 1.0:
                setup.confidence_score = new_score
                factors.append(
                    ConfidenceFactor(
                        name="Funding rate Kraken",
                        score=round((kf_mult - 1.0) * 100, 1),
                        detail=f"×{kf_mult:.2f} — {kf_reason}",
                        positive=False,
                        source="microstructure",
                        metadata=kf_meta,
                    )
                )
                setup.confidence_factors = factors
                logger.info(
                    f"kraken_funding_applied pair={setup.pair} dir={setup.direction.value} "
                    f"prev={prev_score} mult={kf_mult} final={new_score} reason={kf_reason}"
                )
        except Exception as e:
            logger.debug(f"kraken funding scoring error: {e}")

    # ── Kraken Futures OI divergence scoring (Gap 2 — 2026-08-02) ────────
    # OI natif Kraken (snapshot 1h) : détecte short squeeze / liquidation longs
    # sur les setups crypto routés vers admin_kraken.
    try:
        from config.settings import KRAKEN_OI_SCORING_ENABLED
    except Exception:
        KRAKEN_OI_SCORING_ENABLED = False
    if KRAKEN_OI_SCORING_ENABLED:
        try:
            from backend.services import kraken_oi_scoring
            prev_score = setup.confidence_score
            new_score, koi_meta = kraken_oi_scoring.apply_kraken_oi(
                setup.pair, setup.direction.value, prev_score
            )
            koi_mult = koi_meta.get("multiplier", 1.0)
            koi_reason = koi_meta.get("reason")
            if koi_mult != 1.0:
                setup.confidence_score = new_score
                factors.append(
                    ConfidenceFactor(
                        name="Open Interest Kraken",
                        score=round((koi_mult - 1.0) * 100, 1),
                        detail=f"×{koi_mult:.2f} — {koi_reason}",
                        positive=False,
                        source="microstructure",
                        metadata=koi_meta,
                    )
                )
                setup.confidence_factors = factors
                logger.info(
                    f"kraken_oi_applied pair={setup.pair} dir={setup.direction.value} "
                    f"prev={prev_score} mult={koi_mult} final={new_score} reason={koi_reason}"
                )
        except Exception as e:
            logger.debug(f"kraken oi scoring error: {e}")

    # ── Kraken Futures order book depth scoring (Gap 2 — 2026-08-02) ─────
    # Spread top-of-book natif Kraken (seuil 8 bps vs 5 bps Binance car
    # carnet moins profond). Filtre marché thin avant push admin_kraken.
    try:
        from config.settings import KRAKEN_ORDERBOOK_SCORING_ENABLED
    except Exception:
        KRAKEN_ORDERBOOK_SCORING_ENABLED = False
    if KRAKEN_ORDERBOOK_SCORING_ENABLED:
        try:
            from backend.services import kraken_orderbook_scoring
            prev_score = setup.confidence_score
            new_score, kob_meta = kraken_orderbook_scoring.apply_kraken_orderbook(
                setup.pair, setup.direction.value, prev_score
            )
            kob_mult = kob_meta.get("multiplier", 1.0)
            kob_reason = kob_meta.get("reason")
            if kob_mult != 1.0:
                setup.confidence_score = new_score
                factors.append(
                    ConfidenceFactor(
                        name="Order book Kraken",
                        score=round((kob_mult - 1.0) * 100, 1),
                        detail=f"×{kob_mult:.2f} — {kob_reason}",
                        positive=False,
                        source="microstructure",
                        metadata=kob_meta,
                    )
                )
                setup.confidence_factors = factors
                logger.info(
                    f"kraken_orderbook_applied pair={setup.pair} dir={setup.direction.value} "
                    f"prev={prev_score} mult={kob_mult} final={new_score} reason={kob_reason}"
                )
        except Exception as e:
            logger.debug(f"kraken orderbook scoring error: {e}")

    # ── Geopolitical veto (Polymarket + GDELT hard rules) ──────────────
    # Lazy import : évite les cycles + permet aux tests de patcher poly/gdelt
    # snapshots sans setup top-level.
    if GEOPOLITICAL_VETO_ENABLED:
        try:
            from backend.services import geopolitical_veto
            vetoed, reasons, meta = geopolitical_veto.apply(
                setup.pair, setup.direction.value
            )
            if vetoed:
                setup.verdict_action = "SKIP"
                blockers = list(setup.verdict_blockers or [])
                blockers.extend([f"Geopolitical veto: {r}" for r in reasons])
                setup.verdict_blockers = blockers
                logger.info(
                    f"geopolitical_veto pair={setup.pair} dir={setup.direction.value} "
                    f"matched={meta.get('rules_matched')} reasons={reasons}"
                )
                # Notif user 1× par (jour, rule, pair) — dedup côté telegram_service.
                # Fire-and-forget pour ne jamais bloquer le pipeline scoring.
                try:
                    import asyncio as _asyncio
                    from backend.services import telegram_service as _tg
                    _asyncio.create_task(_tg.send_veto_alert(
                        setup.pair, setup.direction.value,
                        meta.get("rules_matched") or [], reasons,
                    ))
                except Exception as _e:
                    logger.warning(f"send_veto_alert hook error: {_e}")
        except Exception as e:
            logger.warning(f"geopolitical_veto error: {e}")

    return setup


def filter_high_confidence_setups(setups: list[TradeSetup]) -> list[TradeSetup]:
    """Filtre les setups pour ne garder que ceux au-dessus du seuil de confiance."""
    filtered = [s for s in setups if s.confidence_score >= MIN_CONFIDENCE_SCORE]
    filtered.sort(key=lambda s: s.confidence_score, reverse=True)
    return filtered


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
