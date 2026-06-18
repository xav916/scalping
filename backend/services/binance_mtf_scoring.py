"""Multi-timeframe alignment filter pour les setups crypto.

Chantier #14 (2026-06-18) — soft veto sur les setups 5m dont la direction
contredit la trend des timeframes supérieurs (15m et 1h). Les faux
breakouts 5m sont fréquents en contre-tendance ; aligner avec le HTF
améliore le win rate au prix du nombre de trades.

Méthode :
- Pour la pair crypto, fetch les 50 dernières klines 15m + 50 klines 1h
  via /fapi/v1/klines (public, gratuit, cache 60s).
- Compute trend simple = sign(close - SMA20).
- Conflits (direction trade vs trend HTF) :
    0/2 conflit → 1.0 (aligné HTF)
    1/2 conflit → 0.85 (mild miss)
    2/2 conflits → 0.70 (full miss, signal contraire au climat HTF)

Best-effort : pair non-crypto, data indispo, exception → (1.0, None).

Toggle via BINANCE_MTF_SCORING_ENABLED.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

ENABLED = os.getenv("BINANCE_MTF_SCORING_ENABLED", "true").strip().lower() in ("true", "1", "yes")
SOFT_VETO_MULT = float(os.getenv("BINANCE_MTF_SOFT_VETO_MULT", "0.85"))
HARD_VETO_MULT = float(os.getenv("BINANCE_MTF_HARD_VETO_MULT", "0.70"))
_CACHE_TTL_SEC = float(os.getenv("BINANCE_MTF_CACHE_TTL_SEC", "60"))
_SMA_PERIOD = int(os.getenv("BINANCE_MTF_SMA_PERIOD", "20"))

_PAIR_TO_SYMBOL: dict[str, str] = {
    "BTC/USD": "BTCUSDT",
    "ETH/USD": "ETHUSDT",
    "SOL/USD": "SOLUSDT",
    "ADA/USD": "ADAUSDT",
    "XRP/USD": "XRPUSDT",
    "LTC/USD": "LTCUSDT",
    "BCH/USD": "BCHUSDT",
    "DOT/USD": "DOTUSDT",
    "DOGE/USD": "DOGEUSDT",
}

# Cache : key = (symbol, interval) → (trend_sign, fetched_at_epoch)
_CACHE: dict[tuple[str, str], tuple[int, float]] = {}


def _fetch_trend(symbol: str, interval: str) -> int | None:
    """Retourne +1 (uptrend), -1 (downtrend), 0 (neutre), None si fail.

    trend = sign(close - SMA(close, SMA_PERIOD)).
    """
    cached = _CACHE.get((symbol, interval))
    now = time.time()
    if cached and (now - cached[1]) < _CACHE_TTL_SEC:
        return cached[0]
    try:
        url = (
            "https://fapi.binance.com/fapi/v1/klines"
            f"?symbol={symbol}&interval={interval}&limit={_SMA_PERIOD + 5}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "scalping-radar/1.0"})
        with urllib.request.urlopen(req, timeout=4) as r:
            klines = json.loads(r.read())
        if len(klines) < _SMA_PERIOD:
            return None
        closes = [float(k[4]) for k in klines[-_SMA_PERIOD:]]
        sma = sum(closes) / len(closes)
        last_close = closes[-1]
        diff = last_close - sma
        # Marge de bruit : 0.05% du prix → neutre, sinon sign(diff)
        threshold = last_close * 0.0005
        if diff > threshold:
            trend = 1
        elif diff < -threshold:
            trend = -1
        else:
            trend = 0
        _CACHE[(symbol, interval)] = (trend, now)
        return trend
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, KeyError, IndexError) as e:
        logger.debug(f"mtf fetch {symbol} {interval}: {e}")
        return None


def apply_mtf_filter(pair: str, direction: str) -> tuple[float, str | None]:
    """Retourne (multiplier, reason).

    multiplier : 1.0 (aligné), 0.85 (1/2 conflit), 0.70 (2/2 conflits).
    Best-effort : (1.0, None) silencieux sur toute erreur / pair non-crypto.
    """
    if not ENABLED:
        return 1.0, None
    sym = _PAIR_TO_SYMBOL.get(pair)
    if not sym:
        return 1.0, None
    trend_15m = _fetch_trend(sym, "15m")
    trend_1h = _fetch_trend(sym, "1h")
    if trend_15m is None or trend_1h is None:
        return 1.0, None
    desired = 1 if direction.lower() == "buy" else -1
    conflicts: list[str] = []
    if trend_15m != 0 and trend_15m != desired:
        conflicts.append("15m")
    if trend_1h != 0 and trend_1h != desired:
        conflicts.append("1h")
    if not conflicts:
        return 1.0, None
    if len(conflicts) == 1:
        return SOFT_VETO_MULT, f"HTF mismatch {conflicts[0]} (direction vs trend SMA{_SMA_PERIOD})"
    return HARD_VETO_MULT, "HTF mismatch 15m + 1h (signal contraire au climat HTF)"


def get_status() -> dict[str, Any]:
    return {
        "enabled": ENABLED,
        "soft_veto_mult": SOFT_VETO_MULT,
        "hard_veto_mult": HARD_VETO_MULT,
        "sma_period": _SMA_PERIOD,
        "cache_size": len(_CACHE),
    }
