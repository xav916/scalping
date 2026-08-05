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

    Depuis 2026-06-16, ajoute aussi 4 features dérivées du funding rate
    Binance (cryptos uniquement) : funding_rate, funding_extreme_positive,
    funding_extreme_negative, funding_available. Pour les non-cryptos,
    funding_available=0 et les autres sont à 0 (modèle apprend à ignorer).
    """
    try:
        pattern_type = setup.pattern.pattern.value if hasattr(setup.pattern.pattern, "value") else str(setup.pattern.pattern)
    except AttributeError:
        return {}
    direction = setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction)
    features = extract_features(
        candles,
        pattern_type,
        direction,
        setup.entry_price,
        setup.stop_loss,
        setup.take_profit_1,
    )
    # Augmente avec features Binance funding (live shadow log, training à terme)
    try:
        from backend.services import binance_funding_service as _bf
        features.update(_bf.get_features_for_setup(getattr(setup, "pair", "")))
    except Exception:
        features.update({
            "funding_rate": 0.0,
            "funding_extreme_positive": 0,
            "funding_extreme_negative": 0,
            "funding_available": 0,
        })
    # VIX features (cross-asset stress indicator). Pertinent surtout pour
    # SPX/NDX/cryptos (risk-on/off corrélation).
    try:
        from backend.services import vix_service as _vix
        features.update(_vix.get_features())
    except Exception:
        features.update({
            "vix_value": 0.0, "vix_change_pct": 0.0,
            "vix_low": 0, "vix_medium": 0, "vix_high": 0, "vix_extreme": 0,
            "vix_available": 0,
        })
    # EIA petroleum features (pertinent uniquement WTI/USD ; flag wednesday
    # window utile pour tous les actifs car régime macro change après le report).
    try:
        from backend.services import eia_petroleum_service as _eia
        features.update(_eia.get_features(getattr(setup, "pair", "")))
    except Exception:
        features.update({
            "eia_is_wti": 0, "eia_in_wednesday_window": 0,
            "eia_wti_in_window": 0,
            "eia_crude_delta_pct": 0.0, "eia_gasoline_delta_pct": 0.0,
            "eia_crude_build": 0, "eia_crude_draw": 0,
            "eia_available": 0,
        })
    # Crypto Fear & Greed (alternative.me) — pertinent BTC/ETH/altcoins.
    try:
        from backend.services import crypto_fear_greed_service as _cfg
        features.update(_cfg.get_features(getattr(setup, "pair", "")))
    except Exception:
        features.update({
            "cfg_value": 0, "cfg_extreme_fear": 0, "cfg_fear": 0,
            "cfg_greed": 0, "cfg_extreme_greed": 0, "cfg_available": 0,
        })
    # Binance long/short account ratio — pertinent cryptos suivies.
    try:
        from backend.services import binance_lsr_service as _lsr
        features.update(_lsr.get_features(getattr(setup, "pair", "")))
    except Exception:
        features.update({
            "lsr_ratio": 0, "lsr_long_pct": 0, "lsr_short_pct": 0,
            "lsr_excess_long": 0, "lsr_excess_short": 0, "lsr_available": 0,
        })
    # CFTC COT positionning (forex, métaux, énergie, SPX/NDX, BTC) — z-score
    # vs 52 semaines, plus flags smart_long / smart_short.
    try:
        from backend.services import cot_service as _cot
        features.update(_cot.get_features(getattr(setup, "pair", "")))
    except Exception:
        features.update({
            "cot_lev_net": 0.0, "cot_lev_z": 0.0, "cot_nr_z": 0.0,
            "cot_smart_long": 0, "cot_smart_short": 0, "cot_available": 0,
        })
    # FRED TIPS 10Y real yields — driver historique XAU/XAG (-85% correl).
    try:
        from backend.services import fred_tips_yields_service as _fred
        features.update(_fred.get_features(getattr(setup, "pair", "")))
    except Exception:
        features.update({
            "tips_yield": 0, "tips_delta_bp": 0,
            "tips_high_yield": 0, "tips_low_yield": 0, "tips_available": 0,
        })
    # Historique macro/sentiment réel (macro_daily + fear_greed_snapshots),
    # accès point-in-time sans look-ahead — voir macro_history_features
    # pour le détail des décalages appliqués par source. Contrairement aux
    # blocs ci-dessus, celui-ci est derrière un drapeau explicite car il
    # remplace la couche macro constante (vix_value figé à 17.0) qui a
    # servi jusqu'ici à calibrer les seuils de décision (42/61/71).
    # Désactivé par défaut : voir MACRO_HISTORY_FEATURES_ENABLED dans
    # config/settings.py pour la justification et ce qu'il faut vérifier
    # avant de l'activer. Le réglage est relu à chaque appel (pas de copie
    # au chargement du module) pour que le monkeypatch de test comme le
    # rechargement de config en production soient bien pris en compte.
    try:
        from config.settings import MACRO_HISTORY_FEATURES_ENABLED as _mh_enabled
    except Exception:
        _mh_enabled = False
    if _mh_enabled:
        try:
            from backend.services import macro_history_features as _mh
            last_ts = candles[-1].timestamp if candles else None
            if last_ts is not None:
                features.update(_mh.get_features_at(getattr(setup, "pair", ""), last_ts))
        except Exception:
            pass  # best-effort : une source macro en panne ne casse jamais le cycle radar
    return features
