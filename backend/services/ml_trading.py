"""ML-driven signal generation for live trading.

Génère des setups candidats uniquement basés sur le scoring ML,
puis les envoie par le pipeline standard (portes de filtrage, MT5 bridge).

Philosophie :
- Indépendant des patterns heuristiques (cycle parallèle)
- Fail-safe : si modèle manquant, retourne vide (pas de setups ML)
- Tous les setups créés passent par les portes existantes (admission, whitelist, confiance, etc.)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from backend.models.schemas import Candle, TradeDirection
from backend.services import ml_predictor
from backend.services.ml_features import extract_features
from backend.services.ml_features import extract_features_for_setup

logger = logging.getLogger(__name__)

# Score ML minimum pour considérer un signal comme viable
ML_CONFIDENCE_THRESHOLD = 0.65  # 65% de proba de hit TP avant SL


class MLTradeSetup:
    """Setup généré purement par ML, structuré comme TradeSetup."""

    def __init__(
        self,
        pair: str,
        direction: str,  # "buy" ou "sell"
        entry_price: float,
        stop_loss: float,
        take_profit_1: float,
        ml_score: float,
        pattern: str = "ml_generated",
        source: str = "internal_ml",
    ):
        self.pair = pair
        self.direction = TradeDirection(direction)
        self.entry_price = entry_price
        self.stop_loss = stop_loss
        self.take_profit_1 = take_profit_1
        self.take_profit = take_profit_1  # Alias pour compatibilité
        self.confidence_score = ml_score  # Lecteur : getattr(setup, "confidence_score", None) or 0
        self.ml_score = ml_score
        self.pattern = _MLPattern(pattern)
        self.source = source  # "internal_ml" ou un bot tiers
        self.horizon = "5min"
        self.chaine = None  # Pas de chaîne pour les signaux ML
        self.verdict_action = None
        self.verdict_summary = None
        self.verdict_reasons = None
        self.verdict_warnings = None
        self.verdict_blockers = None
        self.is_simulated = False

    def model_dump(self, mode="json"):
        """Rend compatible avec le pipeline broadcast/logging."""
        return {
            "pair": self.pair,
            "direction": self.direction.value,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit_1": self.take_profit_1,
            "take_profit": self.take_profit,
            "ml_score": self.ml_score,
            "confidence_score": self.confidence_score,
            "pattern": self.pattern.value,
            "source": self.source,
            "horizon": self.horizon,
        }


class _MLPattern:
    """Wrapper pour compatibilité avec pattern.value."""

    def __init__(self, value: str):
        self.value = value
        self.pattern = self


def generate_ml_signals_for_pair(
    pair: str,
    candles_5min: list[Candle],
    candles_1h: list[Candle] | None = None,
) -> list[MLTradeSetup]:
    """Génère des candidats de trade pour une paire basés sur ML scoring.

    Stratégie simple pour start :
    - Calcule des points d'entrée candidats (ATR-based)
    - Score chaque candidat avec ML
    - Retourne seulement ceux > threshold

    Args:
        pair: Symbole (EUR/USD, BTC/USD, etc.)
        candles_5min: Historique 5min pour détection volatilité
        candles_1h: Historique 1h pour features ML (optionnel, defaut 5min)

    Returns:
        Liste de MLTradeSetup prêts pour send_setup()
    """
    if not candles_5min:
        return []

    # Fallback : utiliser 5min si pas 1h
    feature_candles = candles_1h or candles_5min
    if not feature_candles:
        return []

    setups = []

    # ─ Détection basique : max/min sur les 20 dernières bougies
    closes = [c.close for c in candles_5min[-20:]]
    if not closes:
        return []

    recent_high = max([c.high for c in candles_5min[-20:]])
    recent_low = min([c.low for c in candles_5min[-20:]])
    current_close = candles_5min[-1].close
    atr = _calculate_atr_simple(candles_5min[-20:])

    if atr == 0:
        return []

    # SL fixe pour XAU/USD, ATR pour les autres
    upper = (pair or "").upper()
    is_xau = "XAU" in upper

    # ─ Candidat 1 : Breakout haut (achat)
    buy_entry = recent_high + atr * 0.1
    if is_xau:
        buy_sl = buy_entry - 10.0   # SL fixe à 10 dollars pour XAU
        buy_tp = buy_entry + 20.0   # TP à 2x le risk
    else:
        buy_sl = recent_low - atr * 0.2  # ATR-based pour autres
        buy_tp = buy_entry + atr * 0.5

    if buy_entry < current_close * 1.01:
        setup_buy = MLTradeSetup(
            pair=pair,
            direction="buy",
            entry_price=buy_entry,
            stop_loss=buy_sl,
            take_profit_1=buy_tp,
            ml_score=0.5,
            pattern="ml_breakout_up",
        )
        _score_setup(setup_buy, feature_candles)
        if setup_buy.ml_score >= ML_CONFIDENCE_THRESHOLD:
            setups.append(setup_buy)

    # ─ Candidat 2 : Breakout bas (vente)
    sell_entry = recent_low - atr * 0.1
    if is_xau:
        sell_sl = sell_entry + 10.0   # SL fixe à 10 dollars pour XAU
        sell_tp = sell_entry - 20.0   # TP à 2x le risk
    else:
        sell_sl = recent_high + atr * 0.2  # ATR-based pour autres
        sell_tp = sell_entry - atr * 0.5

    if sell_entry > current_close * 0.99:
        setup_sell = MLTradeSetup(
            pair=pair,
            direction="sell",
            entry_price=sell_entry,
            stop_loss=sell_sl,
            take_profit_1=sell_tp,
            ml_score=0.5,
            pattern="ml_breakout_down",
        )
        _score_setup(setup_sell, feature_candles)
        if setup_sell.ml_score >= ML_CONFIDENCE_THRESHOLD:
            setups.append(setup_sell)

    logger.info(f"ml_trading[{pair}]: {len(setups)} candidat(s) ML > {ML_CONFIDENCE_THRESHOLD}")
    return setups


def _score_setup(setup: MLTradeSetup, candles: list[Candle]) -> None:
    """In-place : score le setup avec ML predictor et met à jour ml_score."""
    features = extract_features(
        candles,
        setup.pattern.value,
        setup.direction.value,
        setup.entry_price,
        setup.stop_loss,
        setup.take_profit_1,
    )

    # Ajouter les services auxiliaires (funding, VIX, etc.)
    try:
        from backend.services import binance_funding_service as _bf
        features.update(_bf.get_features_for_setup(setup.pair))
    except Exception:
        features.update({
            "funding_rate": 0.0,
            "funding_extreme_positive": 0,
            "funding_extreme_negative": 0,
            "funding_available": 0,
        })

    try:
        from backend.services import vix_service as _vix
        features.update(_vix.get_features())
    except Exception:
        features.update({
            "vix_value": 0.0, "vix_change_pct": 0.0,
            "vix_low": 0, "vix_medium": 0, "vix_high": 0, "vix_extreme": 0,
            "vix_available": 0,
        })

    try:
        from backend.services import eia_petroleum_service as _eia
        features.update(_eia.get_features(setup.pair))
    except Exception:
        features.update({
            "eia_is_wti": 0, "eia_in_wednesday_window": 0,
            "eia_wti_in_window": 0,
            "eia_crude_delta_pct": 0.0, "eia_gasoline_delta_pct": 0.0,
            "eia_crude_build": 0, "eia_crude_draw": 0,
            "eia_available": 0,
        })

    try:
        from backend.services import crypto_fear_greed_service as _cfg
        features.update(_cfg.get_features(setup.pair))
    except Exception:
        features.update({
            "cfg_value": 0, "cfg_extreme_fear": 0, "cfg_fear": 0,
            "cfg_greed": 0, "cfg_extreme_greed": 0, "cfg_available": 0,
        })

    try:
        from backend.services import binance_lsr_service as _lsr
        features.update(_lsr.get_features(setup.pair))
    except Exception:
        features.update({
            "lsr_value": 0.0, "lsr_extreme_long": 0, "lsr_extreme_short": 0,
            "lsr_available": 0,
        })

    # Score ML
    proba = ml_predictor.predict_win_proba(features)
    setup.ml_score = proba
    setup.confidence_score = proba
    logger.debug(f"ml_trading: {setup.pair} {setup.direction.value} score={proba:.2%}")


def _calculate_atr_simple(candles: list[Candle], period: int = 14) -> float:
    """ATR simplifié pour détection volatilité."""
    if len(candles) < period:
        return 0.0

    trs = []
    for i in range(len(candles) - period, len(candles)):
        if i == 0:
            tr = candles[i].high - candles[i].low
        else:
            prev_close = candles[i - 1].close
            tr = max(
                candles[i].high - candles[i].low,
                abs(candles[i].high - prev_close),
                abs(candles[i].low - prev_close),
            )
        trs.append(tr)

    return sum(trs) / len(trs) if trs else 0.0
