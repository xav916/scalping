"""Feature engineering pour ml_predictor en mode live.

Reproduit fidèlement la logique de `scripts/ml_extract_features.py` afin
que les features calculées en live soient identiques à celles utilisées
pendant le training. Toute divergence ferait dériver les probas.

Usage typique (dans le scheduler) :

    from backend.services.ml_features import extract_features_for_setup
    from backend.services import ml_predictor

    feats = extract_features_for_setup(setup, candles)
    if feats:
        proba = ml_predictor.predict_win_proba(feats)
"""
from __future__ import annotations

import math
from typing import Any

from backend.models.schemas import Candle, TradeDirection
from backend.services.pattern_detector import _calculate_atr


PATTERN_TYPES = [
    "breakout_up", "breakout_down", "momentum_up", "momentum_down",
    "range_bounce_up", "range_bounce_down", "mean_reversion_up",
    "mean_reversion_down", "engulfing_bullish", "engulfing_bearish",
    "pin_bar_up", "pin_bar_down",
]

SESSION_BUCKETS = ["tokyo", "london", "london_ny", "ny", "sydney"]


def _sma(values: list[float], period: int) -> float:
    if len(values) < period:
        return float("nan")
    return sum(values[-period:]) / period


def _ema(values: list[float], period: int) -> float:
    if not values or period <= 0:
        return float("nan")
    k = 2 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return float("nan")
    gains = []
    losses = []
    for i in range(1, period + 1):
        diff = closes[-i] - closes[-i - 1]
        if diff > 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(-diff)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _adx(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < period + 1:
        return float("nan")
    trs: list[float] = []
    dmp: list[float] = []
    dmm: list[float] = []
    for i in range(1, len(candles)):
        prev = candles[i - 1]
        cur = candles[i]
        tr = max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close))
        trs.append(tr)
        up = cur.high - prev.high
        down = prev.low - cur.low
        dmp.append(up if up > down and up > 0 else 0)
        dmm.append(down if down > up and down > 0 else 0)
    if len(trs) < period:
        return float("nan")
    atr = sum(trs[-period:]) / period
    if atr == 0:
        return 0.0
    di_plus = 100 * (sum(dmp[-period:]) / period) / atr
    di_minus = 100 * (sum(dmm[-period:]) / period) / atr
    if (di_plus + di_minus) <= 0:
        return 0.0
    return 100 * abs(di_plus - di_minus) / (di_plus + di_minus)


def _stoch(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < period:
        return float("nan")
    recent = candles[-period:]
    hh = max(c.high for c in recent)
    ll = min(c.low for c in recent)
    if hh == ll:
        return 50.0
    close = candles[-1].close
    return 100 * (close - ll) / (hh - ll)


def _body_wick_ratio(candle: Candle) -> float:
    total = candle.high - candle.low
    if total == 0:
        return 0.0
    return abs(candle.close - candle.open) / total


def _session_utc(hour: int) -> str:
    if 0 <= hour < 8:
        return "tokyo"
    if 8 <= hour < 13:
        return "london"
    if 13 <= hour < 17:
        return "london_ny"
    if 17 <= hour < 22:
        return "ny"
    return "sydney"


def extract_features(
    candles_before: list[Candle],
    pattern_type: str,
    direction: str,
    entry: float,
    sl: float,
    tp: float,
) -> dict[str, Any]:
    """Features connues AU MOMENT T (pas de look-ahead).

    Identique à `scripts/ml_extract_features.extract_features` (sans les
    métadonnées `pair`/`timestamp`/`direction` qui ne sont pas en input
    du modèle).

    Retourne {} si pas assez de candles (< 30).
    """
    if len(candles_before) < 30:
        return {}
    closes = [c.close for c in candles_before]
    last = candles_before[-1]

    atr14 = _calculate_atr(candles_before, period=14)
    atr50 = _calculate_atr(candles_before[-50:], period=14) if len(candles_before) >= 50 else atr14
    atr_ratio = atr14 / atr50 if atr50 > 0 else 1.0

    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    sma200 = _sma(closes, 200)
    ema10 = _ema(closes[-30:], 10)
    ema30 = _ema(closes[-30:], 30)

    dist_sma20 = (last.close - sma20) / atr14 if atr14 > 0 and not math.isnan(sma20) else 0
    dist_sma50 = (last.close - sma50) / atr14 if atr14 > 0 and not math.isnan(sma50) else 0
    dist_sma200 = (last.close - sma200) / atr14 if atr14 > 0 and not math.isnan(sma200) else 0

    ema_spread = (ema10 - ema30) / ema30 if ema30 > 0 else 0

    rsi14 = _rsi(closes, 14)
    adx14 = _adx(candles_before, 14)
    stoch_k = _stoch(candles_before, 14)

    bw_last = _body_wick_ratio(last)
    bw_prev = _body_wick_ratio(candles_before[-2]) if len(candles_before) >= 2 else 0
    bw_prev2 = _body_wick_ratio(candles_before[-3]) if len(candles_before) >= 3 else 0

    risk = abs(entry - sl) / entry if entry > 0 else 0
    reward = abs(tp - entry) / entry if entry > 0 else 0
    rr = reward / risk if risk > 0 else 0

    ts = last.timestamp
    hour = ts.hour
    dow = ts.weekday()
    session = _session_utc(hour)

    pattern_onehot = {f"pat_{p}": 1 if p == pattern_type else 0 for p in PATTERN_TYPES}
    session_onehot = {f"ses_{s}": 1 if s == session else 0 for s in SESSION_BUCKETS}

    return {
        "risk_pct": risk,
        "reward_pct": reward,
        "rr": rr,
        "atr14": atr14,
        "atr_ratio": atr_ratio,
        "dist_sma20_atr": dist_sma20,
        "dist_sma50_atr": dist_sma50,
        "dist_sma200_atr": dist_sma200,
        "ema_spread": ema_spread,
        "rsi14": rsi14 if not math.isnan(rsi14) else 50,
        "adx14": adx14 if not math.isnan(adx14) else 20,
        "stoch_k": stoch_k if not math.isnan(stoch_k) else 50,
        "bw_last": bw_last,
        "bw_prev": bw_prev,
        "bw_prev2": bw_prev2,
        "hour_sin": math.sin(2 * math.pi * hour / 24),
        "hour_cos": math.cos(2 * math.pi * hour / 24),
        "dow": dow,
        **pattern_onehot,
        **session_onehot,
    }


def extract_features_for_setup(setup: Any, candles: list[Candle]) -> dict[str, Any]:
    """Wrapper qui extrait les features depuis un TradeSetup live.

    Le setup doit avoir : pair, direction, entry_price, stop_loss,
    take_profit_1, pattern (.pattern.value).

    Les candles doivent être un historique 1h (la même granularité que
    le training). En live, le scheduler dispose déjà des candles 5min
    pour l'analyse — pour le ML il faudrait idéalement des candles 1h
    (ou re-aggregé). On utilise donc l'historique fourni tel quel et on
    accepte une légère divergence : c'est un shadow log.
    """
    try:
        pattern_type = setup.pattern.pattern.value if hasattr(setup.pattern.pattern, "value") else str(setup.pattern.pattern)
    except AttributeError:
        return {}
    direction = setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction)
    return extract_features(
        candles,
        pattern_type,
        direction,
        setup.entry_price,
        setup.stop_loss,
        setup.take_profit_1,
    )
