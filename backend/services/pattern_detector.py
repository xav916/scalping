"""Moteur de détection de patterns de scalping.

Analyse les bougies OHLC pour identifier les patterns exploitables :
- Breakout (cassure de support/résistance)
- Momentum (accélération directionnelle)
- Range bounce (rebond dans un range)
- Mean reversion (retour à la moyenne)
- Engulfing (bougie englobante)
- Pin bar (mèche de rejet)
- SIBI / BISI (Fair Value Gap ICT - déséquilibre acheteur/vendeur)
- Discussion SIBI/BISI (prix revient tester la zone FVG)

Pour chaque pattern détecté, calcule un setup de trade
avec entrée, stop loss et take profit.
"""

import logging
from datetime import datetime, timezone

from backend.models.schemas import (
    Candle,
    PatternDetection,
    PatternType,
    TradeDirection,
    TradeSetup,
)

logger = logging.getLogger(__name__)

# Seuils pour l'or (XAU/USD) en dollars
# Adaptés au scalping 5min
GOLD_ATR_DEFAULT = 3.0  # ATR moyen sur 5min en $


def detect_patterns(candles: list[Candle], pair: str = "XAU/USD") -> list[PatternDetection]:
    """Détecte tous les patterns de scalping dans les bougies données."""
    if len(candles) < 20:
        return []

    patterns: list[PatternDetection] = []

    patterns.extend(_detect_breakout(candles, pair))
    patterns.extend(_detect_momentum(candles, pair))
    patterns.extend(_detect_range_bounce(candles, pair))
    patterns.extend(_detect_mean_reversion(candles, pair))
    patterns.extend(_detect_engulfing(candles, pair))
    patterns.extend(_detect_pin_bar(candles, pair))
    patterns.extend(_detect_fvg(candles, pair))

    # Trier par confiance décroissante
    patterns.sort(key=lambda p: p.confidence, reverse=True)
    return patterns


def calculate_trade_setup(
    pair: str,
    pattern: PatternDetection,
    candles: list[Candle],
    is_simulated: bool = False,
) -> TradeSetup | None:
    """Calcule un setup de trade complet à partir d'un pattern détecté."""
    if len(candles) < 5:
        return None

    now = datetime.now(timezone.utc)
    last = candles[-1]
    atr = _calculate_atr(candles, period=14)

    # Déterminer la direction
    is_buy = pattern.pattern in (
        PatternType.BREAKOUT_UP,
        PatternType.MOMENTUM_UP,
        PatternType.RANGE_BOUNCE_UP,
        PatternType.MEAN_REVERSION_UP,
        PatternType.ENGULFING_BULLISH,
        PatternType.PIN_BAR_UP,
        PatternType.BISI,
        PatternType.BISI_DISCUSSION,
        PatternType.SIBI_DISCUSSION,  # Discussion SIBI = prix reteste puis rebondit → achat
    )

    direction = TradeDirection.BUY if is_buy else TradeDirection.SELL
    entry = last.close

    if is_buy:
        # Achat : SL sous le dernier plus bas, TP au-dessus
        recent_low = min(c.low for c in candles[-5:])
        stop_loss = round(recent_low - atr * 0.3, 2)
        risk = entry - stop_loss

        # TP1 = 1.5x le risque (conservateur), TP2 = 2.5x le risque (agressif)
        take_profit_1 = round(entry + risk * 1.5, 2)
        take_profit_2 = round(entry + risk * 2.5, 2)
    else:
        # Vente : SL au-dessus du dernier plus haut, TP en-dessous
        recent_high = max(c.high for c in candles[-5:])
        stop_loss = round(recent_high + atr * 0.3, 2)
        risk = stop_loss - entry

        take_profit_1 = round(entry - risk * 1.5, 2)
        take_profit_2 = round(entry - risk * 2.5, 2)

    if risk <= 0:
        return None

    reward_1 = abs(take_profit_1 - entry)
    reward_2 = abs(take_profit_2 - entry)

    # Construire le message en français
    dir_label = "ACHAT" if is_buy else "VENTE"
    pattern_label = _pattern_french_name(pattern.pattern)

    message = (
        f"{dir_label} {pair} @ {entry:.2f} | "
        f"Pattern: {pattern_label} (confiance: {pattern.confidence:.0%}) | "
        f"SL: {stop_loss:.2f} | TP1: {take_profit_1:.2f} (R:R {reward_1/risk:.1f}) | "
        f"TP2: {take_profit_2:.2f} (R:R {reward_2/risk:.1f})"
    )

    return TradeSetup(
        pair=pair,
        direction=direction,
        pattern=pattern,
        entry_price=entry,
        stop_loss=stop_loss,
        take_profit_1=take_profit_1,
        take_profit_2=take_profit_2,
        risk_pips=round(risk, 2),
        reward_pips_1=round(reward_1, 2),
        reward_pips_2=round(reward_2, 2),
        risk_reward_1=round(reward_1 / risk, 2) if risk > 0 else 0,
        risk_reward_2=round(reward_2 / risk, 2) if risk > 0 else 0,
        message=message,
        timestamp=now,
        is_simulated=is_simulated,
    )


# ─── Détection de patterns individuels ────────────────────────────────


def _detect_breakout(candles: list[Candle], pair: str) -> list[PatternDetection]:
    """Détecte les cassures de support/résistance.

    Identifie les niveaux clés sur les 30 dernières bougies,
    puis vérifie si la dernière bougie casse un de ces niveaux.
    """
    patterns = []
    now = datetime.now(timezone.utc)

    lookback = candles[-30:]
    last = candles[-1]
    prev = candles[-2]

    # Trouver résistance (plus hauts récents) et support (plus bas récents)
    highs = [c.high for c in lookback[:-1]]
    lows = [c.low for c in lookback[:-1]]

    resistance = _find_level(highs, mode="resistance")
    support = _find_level(lows, mode="support")

    atr = _calculate_atr(candles, period=14)
    threshold = atr * 0.2  # Marge pour confirmer la cassure

    # Cassure de résistance vers le haut
    if resistance and last.close > resistance + threshold and prev.close <= resistance:
        confidence = min(0.85, 0.6 + (last.close - resistance) / atr * 0.2)
        patterns.append(PatternDetection(
            pattern=PatternType.BREAKOUT_UP,
            confidence=round(confidence, 2),
            description=(
                f"Cassure de resistance a {resistance:.2f}. "
                f"Prix actuel: {last.close:.2f} (+{last.close - resistance:.2f})"
            ),
            detected_at=now,
        ))

    # Cassure de support vers le bas
    if support and last.close < support - threshold and prev.close >= support:
        confidence = min(0.85, 0.6 + (support - last.close) / atr * 0.2)
        patterns.append(PatternDetection(
            pattern=PatternType.BREAKOUT_DOWN,
            confidence=round(confidence, 2),
            description=(
                f"Cassure de support a {support:.2f}. "
                f"Prix actuel: {last.close:.2f} (-{support - last.close:.2f})"
            ),
            detected_at=now,
        ))

    return patterns


def _detect_momentum(candles: list[Candle], pair: str) -> list[PatternDetection]:
    """Détecte les accélérations de momentum.

    Vérifie si les N dernières bougies vont dans la même direction
    avec une force croissante.
    """
    patterns = []
    now = datetime.now(timezone.utc)

    last_5 = candles[-5:]
    closes = [c.close for c in last_5]

    # Compter les bougies consécutives dans la même direction
    up_count = sum(1 for c in last_5 if c.close > c.open)
    down_count = sum(1 for c in last_5 if c.close < c.open)

    atr = _calculate_atr(candles, period=14)
    total_move = closes[-1] - closes[0]

    # Momentum haussier : 4+ bougies vertes sur 5
    if up_count >= 4 and total_move > atr * 1.5:
        confidence = min(0.80, 0.55 + up_count * 0.05 + abs(total_move) / atr * 0.05)
        patterns.append(PatternDetection(
            pattern=PatternType.MOMENTUM_UP,
            confidence=round(confidence, 2),
            description=(
                f"Momentum haussier: {up_count}/5 bougies vertes, "
                f"mouvement total +{total_move:.2f} ({total_move/atr:.1f}x ATR)"
            ),
            detected_at=now,
        ))

    # Momentum baissier : 4+ bougies rouges sur 5
    if down_count >= 4 and total_move < -atr * 1.5:
        confidence = min(0.80, 0.55 + down_count * 0.05 + abs(total_move) / atr * 0.05)
        patterns.append(PatternDetection(
            pattern=PatternType.MOMENTUM_DOWN,
            confidence=round(confidence, 2),
            description=(
                f"Momentum baissier: {down_count}/5 bougies rouges, "
                f"mouvement total {total_move:.2f} ({abs(total_move)/atr:.1f}x ATR)"
            ),
            detected_at=now,
        ))

    return patterns


def _detect_range_bounce(candles: list[Candle], pair: str) -> list[PatternDetection]:
    """Détecte les rebonds dans un range.

    Identifie si le marché est en range, puis vérifie si
    le prix rebondit sur le haut ou le bas du range.
    """
    patterns = []
    now = datetime.now(timezone.utc)

    lookback = candles[-20:]
    last = candles[-1]

    highs = [c.high for c in lookback]
    lows = [c.low for c in lookback]

    range_high = max(highs)
    range_low = min(lows)
    range_size = range_high - range_low

    atr = _calculate_atr(candles, period=14)

    # Vérifier que c'est bien un range (pas trop large)
    if range_size > atr * 8:
        return patterns  # Trop volatile, pas un range

    # Zone basse du range (25% inférieur)
    low_zone = range_low + range_size * 0.25
    # Zone haute du range (75% supérieur)
    high_zone = range_high - range_size * 0.25

    # Rebond sur le bas du range (achat)
    if last.close < low_zone and last.close > last.open:
        confidence = 0.65
        # Plus le prix est proche du bas, plus le signal est fort
        proximity = 1 - (last.close - range_low) / range_size
        confidence = min(0.80, confidence + proximity * 0.15)
        patterns.append(PatternDetection(
            pattern=PatternType.RANGE_BOUNCE_UP,
            confidence=round(confidence, 2),
            description=(
                f"Rebond sur bas de range [{range_low:.2f} - {range_high:.2f}]. "
                f"Bougie verte en zone basse ({last.close:.2f})"
            ),
            detected_at=now,
        ))

    # Rejet sur le haut du range (vente)
    if last.close > high_zone and last.close < last.open:
        confidence = 0.65
        proximity = (last.close - range_low) / range_size
        confidence = min(0.80, confidence + proximity * 0.15)
        patterns.append(PatternDetection(
            pattern=PatternType.RANGE_BOUNCE_DOWN,
            confidence=round(confidence, 2),
            description=(
                f"Rejet sur haut de range [{range_low:.2f} - {range_high:.2f}]. "
                f"Bougie rouge en zone haute ({last.close:.2f})"
            ),
            detected_at=now,
        ))

    return patterns


def _detect_mean_reversion(candles: list[Candle], pair: str) -> list[PatternDetection]:
    """Détecte les retours à la moyenne (Bollinger-like).

    Calcule une moyenne mobile et des écarts-types pour identifier
    quand le prix s'éloigne trop de la moyenne.
    """
    patterns = []
    now = datetime.now(timezone.utc)

    if len(candles) < 20:
        return patterns

    # Moyenne mobile 20 périodes
    closes = [c.close for c in candles[-20:]]
    sma = sum(closes) / len(closes)
    variance = sum((c - sma) ** 2 for c in closes) / len(closes)
    std_dev = variance ** 0.5

    last = candles[-1]
    distance = last.close - sma

    # Sur-extension baissière → signal d'achat (retour vers le haut)
    if distance < -std_dev * 2 and last.close > last.open:
        confidence = min(0.75, 0.55 + abs(distance) / std_dev * 0.05)
        patterns.append(PatternDetection(
            pattern=PatternType.MEAN_REVERSION_UP,
            confidence=round(confidence, 2),
            description=(
                f"Prix sur-etendu sous la moyenne ({sma:.2f}). "
                f"Ecart: {distance:.2f} ({abs(distance)/std_dev:.1f} ecarts-types)"
            ),
            detected_at=now,
        ))

    # Sur-extension haussière → signal de vente (retour vers le bas)
    if distance > std_dev * 2 and last.close < last.open:
        confidence = min(0.75, 0.55 + abs(distance) / std_dev * 0.05)
        patterns.append(PatternDetection(
            pattern=PatternType.MEAN_REVERSION_DOWN,
            confidence=round(confidence, 2),
            description=(
                f"Prix sur-etendu au-dessus de la moyenne ({sma:.2f}). "
                f"Ecart: +{distance:.2f} ({distance/std_dev:.1f} ecarts-types)"
            ),
            detected_at=now,
        ))

    return patterns


def _detect_engulfing(candles: list[Candle], pair: str) -> list[PatternDetection]:
    """Détecte les bougies englobantes (bullish/bearish engulfing)."""
    patterns = []
    now = datetime.now(timezone.utc)

    if len(candles) < 3:
        return patterns

    prev = candles[-2]
    last = candles[-1]
    atr = _calculate_atr(candles, period=14)

    prev_body = abs(prev.close - prev.open)
    last_body = abs(last.close - last.open)

    # Taille minimale du corps pour être significatif
    min_body = atr * 0.3

    # Englobante haussière : bougie rouge suivie d'une grande bougie verte
    if (prev.close < prev.open  # bougie précédente rouge
            and last.close > last.open  # bougie actuelle verte
            and last_body > prev_body  # corps plus grand
            and last.open <= prev.close  # ouvre sous le close précédent
            and last.close >= prev.open  # ferme au-dessus de l'open précédent
            and last_body > min_body):
        confidence = min(0.80, 0.60 + last_body / atr * 0.1)
        patterns.append(PatternDetection(
            pattern=PatternType.ENGULFING_BULLISH,
            confidence=round(confidence, 2),
            description=(
                f"Englobante haussiere: bougie verte ({last_body:.2f}) "
                f"englobe la rouge precedente ({prev_body:.2f})"
            ),
            detected_at=now,
        ))

    # Englobante baissière : bougie verte suivie d'une grande bougie rouge
    if (prev.close > prev.open  # bougie précédente verte
            and last.close < last.open  # bougie actuelle rouge
            and last_body > prev_body  # corps plus grand
            and last.open >= prev.close  # ouvre au-dessus du close précédent
            and last.close <= prev.open  # ferme sous l'open précédent
            and last_body > min_body):
        confidence = min(0.80, 0.60 + last_body / atr * 0.1)
        patterns.append(PatternDetection(
            pattern=PatternType.ENGULFING_BEARISH,
            confidence=round(confidence, 2),
            description=(
                f"Englobante baissiere: bougie rouge ({last_body:.2f}) "
                f"englobe la verte precedente ({prev_body:.2f})"
            ),
            detected_at=now,
        ))

    return patterns


def _detect_pin_bar(candles: list[Candle], pair: str) -> list[PatternDetection]:
    """Détecte les pin bars (bougies avec longue mèche de rejet)."""
    patterns = []
    now = datetime.now(timezone.utc)

    last = candles[-1]
    atr = _calculate_atr(candles, period=14)

    body = abs(last.close - last.open)
    upper_wick = last.high - max(last.close, last.open)
    lower_wick = min(last.close, last.open) - last.low
    total_range = last.high - last.low

    if total_range < atr * 0.3:
        return patterns  # Bougie trop petite

    # Pin bar haussière : longue mèche basse, petit corps en haut
    if lower_wick > body * 2 and lower_wick > upper_wick * 2 and lower_wick > atr * 0.5:
        confidence = min(0.75, 0.55 + lower_wick / total_range * 0.2)
        patterns.append(PatternDetection(
            pattern=PatternType.PIN_BAR_UP,
            confidence=round(confidence, 2),
            description=(
                f"Pin bar haussiere: meche basse {lower_wick:.2f} "
                f"({lower_wick/total_range:.0%} de la bougie). Rejet vendeur."
            ),
            detected_at=now,
        ))

    # Pin bar baissière : longue mèche haute, petit corps en bas
    if upper_wick > body * 2 and upper_wick > lower_wick * 2 and upper_wick > atr * 0.5:
        confidence = min(0.75, 0.55 + upper_wick / total_range * 0.2)
        patterns.append(PatternDetection(
            pattern=PatternType.PIN_BAR_DOWN,
            confidence=round(confidence, 2),
            description=(
                f"Pin bar baissiere: meche haute {upper_wick:.2f} "
                f"({upper_wick/total_range:.0%} de la bougie). Rejet acheteur."
            ),
            detected_at=now,
        ))

    return patterns


def _detect_fvg(candles: list[Candle], pair: str) -> list[PatternDetection]:
    """Détecte les Fair Value Gaps (SIBI/BISI) et leur discussion (retest).

    SIBI (Sell-side Imbalance, Buy-side Inefficiency) = FVG baissier :
        La bougie 1 a un low supérieur au high de la bougie 3 dans une
        séquence baissière de 3 bougies. Zone de déséquilibre vendeur.

    BISI (Buy-side Imbalance, Sell-side Inefficiency) = FVG haussier :
        La bougie 1 a un high inférieur au low de la bougie 3 dans une
        séquence haussière de 3 bougies. Zone de déséquilibre acheteur.

    Discussion = le prix revient tester la zone FVG sans la casser.
    C'est le signal le plus fiable (entrée sur retest).
    """
    patterns = []
    now = datetime.now(timezone.utc)

    if len(candles) < 10:
        return patterns

    atr = _calculate_atr(candles, period=14)
    min_gap = atr * 0.3  # Gap minimum significatif
    last = candles[-1]

    # Chercher les FVG dans les 20 dernières bougies
    lookback = min(len(candles) - 2, 20)

    for i in range(-lookback, -2):
        c1 = candles[i]      # Bougie 1
        c2 = candles[i + 1]  # Bougie 2 (impulsion)
        c3 = candles[i + 2]  # Bougie 3

        # SIBI (FVG baissier) : low de c1 > high de c3
        sibi_gap = c1.low - c3.high
        if sibi_gap > min_gap:
            fvg_top = c1.low
            fvg_bottom = c3.high
            fvg_mid = (fvg_top + fvg_bottom) / 2

            # Vérifier si la bougie actuelle "discute" la zone SIBI
            # = le prix revient dans la zone FVG
            if last.high >= fvg_bottom and last.low <= fvg_top:
                # Discussion en cours : le prix est dans la zone SIBI
                if last.close < fvg_mid and last.close < last.open:
                    # Rejet baissier depuis la zone → signal de vente
                    confidence = min(0.85, 0.65 + sibi_gap / atr * 0.1)
                    patterns.append(PatternDetection(
                        pattern=PatternType.SIBI_DISCUSSION,
                        confidence=round(confidence, 2),
                        description=(
                            f"Discussion SIBI: prix reteste la zone FVG "
                            f"[{fvg_bottom:.2f} - {fvg_top:.2f}] et rejette. "
                            f"Signal de vente sur retest."
                        ),
                        detected_at=now,
                    ))
                elif last.close > fvg_mid and last.close > last.open:
                    # Le prix traverse la zone → invalidation potentielle
                    # mais peut être un signal d'achat si le FVG est comblé
                    confidence = min(0.70, 0.50 + sibi_gap / atr * 0.1)
                    patterns.append(PatternDetection(
                        pattern=PatternType.SIBI_DISCUSSION,
                        confidence=round(confidence, 2),
                        description=(
                            f"Discussion SIBI: prix comble la zone FVG "
                            f"[{fvg_bottom:.2f} - {fvg_top:.2f}]. "
                            f"Possible retournement haussier."
                        ),
                        detected_at=now,
                    ))
            elif i >= -5:
                # FVG récent pas encore retesté → signal SIBI pur
                confidence = min(0.75, 0.55 + sibi_gap / atr * 0.1)
                patterns.append(PatternDetection(
                    pattern=PatternType.SIBI,
                    confidence=round(confidence, 2),
                    description=(
                        f"SIBI detecte: FVG baissier "
                        f"[{fvg_bottom:.2f} - {fvg_top:.2f}] "
                        f"(gap: {sibi_gap:.2f}, {sibi_gap/atr:.1f}x ATR). "
                        f"Zone de vente potentielle si le prix y revient."
                    ),
                    detected_at=now,
                ))

        # BISI (FVG haussier) : high de c1 < low de c3
        bisi_gap = c3.low - c1.high
        if bisi_gap > min_gap:
            fvg_bottom = c1.high
            fvg_top = c3.low
            fvg_mid = (fvg_top + fvg_bottom) / 2

            # Vérifier si la bougie actuelle "discute" la zone BISI
            if last.high >= fvg_bottom and last.low <= fvg_top:
                if last.close > fvg_mid and last.close > last.open:
                    # Rebond haussier depuis la zone → signal d'achat
                    confidence = min(0.85, 0.65 + bisi_gap / atr * 0.1)
                    patterns.append(PatternDetection(
                        pattern=PatternType.BISI_DISCUSSION,
                        confidence=round(confidence, 2),
                        description=(
                            f"Discussion BISI: prix reteste la zone FVG "
                            f"[{fvg_bottom:.2f} - {fvg_top:.2f}] et rebondit. "
                            f"Signal d'achat sur retest."
                        ),
                        detected_at=now,
                    ))
                elif last.close < fvg_mid and last.close < last.open:
                    confidence = min(0.70, 0.50 + bisi_gap / atr * 0.1)
                    patterns.append(PatternDetection(
                        pattern=PatternType.BISI_DISCUSSION,
                        confidence=round(confidence, 2),
                        description=(
                            f"Discussion BISI: prix comble la zone FVG "
                            f"[{fvg_bottom:.2f} - {fvg_top:.2f}]. "
                            f"Possible retournement baissier."
                        ),
                        detected_at=now,
                    ))
            elif i >= -5:
                confidence = min(0.75, 0.55 + bisi_gap / atr * 0.1)
                patterns.append(PatternDetection(
                    pattern=PatternType.BISI,
                    confidence=round(confidence, 2),
                    description=(
                        f"BISI detecte: FVG haussier "
                        f"[{fvg_bottom:.2f} - {fvg_top:.2f}] "
                        f"(gap: {bisi_gap:.2f}, {bisi_gap/atr:.1f}x ATR). "
                        f"Zone d'achat potentielle si le prix y revient."
                    ),
                    detected_at=now,
                ))

    return patterns


# ─── Utilitaires ──────────────────────────────────────────────────────


def _calculate_atr(candles: list[Candle], period: int = 14) -> float:
    """Calcule l'Average True Range (ATR)."""
    if len(candles) < period + 1:
        # Fallback : moyenne des ranges
        ranges = [c.high - c.low for c in candles[-period:]]
        return sum(ranges) / len(ranges) if ranges else GOLD_ATR_DEFAULT

    true_ranges = []
    for i in range(-period, 0):
        high = candles[i].high
        low = candles[i].low
        prev_close = candles[i - 1].close
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)

    return sum(true_ranges) / len(true_ranges)


def _find_level(values: list[float], mode: str = "resistance") -> float | None:
    """Trouve un niveau de support/résistance significatif.

    Cherche les zones où le prix a été rejeté plusieurs fois.
    """
    if len(values) < 10:
        return None

    # Trier et chercher des clusters
    sorted_vals = sorted(values, reverse=(mode == "resistance"))
    atr_estimate = (max(values) - min(values)) / 10

    if atr_estimate == 0:
        return None

    # Prendre les 5 plus hauts (résistance) ou plus bas (support)
    top_n = sorted_vals[:5]

    # Vérifier qu'ils forment un cluster (proches les uns des autres)
    cluster_range = max(top_n) - min(top_n)
    if cluster_range < atr_estimate * 3:
        return sum(top_n) / len(top_n)

    return top_n[0]


def _pattern_french_name(pattern: PatternType) -> str:
    """Nom français du pattern."""
    names = {
        PatternType.BREAKOUT_UP: "Cassure resistance",
        PatternType.BREAKOUT_DOWN: "Cassure support",
        PatternType.MOMENTUM_UP: "Momentum haussier",
        PatternType.MOMENTUM_DOWN: "Momentum baissier",
        PatternType.RANGE_BOUNCE_UP: "Rebond sur support",
        PatternType.RANGE_BOUNCE_DOWN: "Rejet sur resistance",
        PatternType.MEAN_REVERSION_UP: "Retour moyenne (achat)",
        PatternType.MEAN_REVERSION_DOWN: "Retour moyenne (vente)",
        PatternType.ENGULFING_BULLISH: "Englobante haussiere",
        PatternType.ENGULFING_BEARISH: "Englobante baissiere",
        PatternType.PIN_BAR_UP: "Pin bar haussiere",
        PatternType.PIN_BAR_DOWN: "Pin bar baissiere",
        PatternType.SIBI: "SIBI (FVG baissier)",
        PatternType.BISI: "BISI (FVG haussier)",
        PatternType.SIBI_DISCUSSION: "Discussion SIBI",
        PatternType.BISI_DISCUSSION: "Discussion BISI",
    }
    return names.get(pattern, pattern.value)
