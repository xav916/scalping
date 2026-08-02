"""Order book depth Kraken Futures — filtre liquidité sur cryptos.

Miroir de ``binance_orderbook_scoring.py`` mais consomme l'endpoint public
Kraken Futures.  Le spread Kraken Futures est structurellement plus large que
Binance (carnet moins profond) — seuil calibré à 8 bps vs 5 bps Binance.

## Source de données

``GET https://futures.kraken.com/derivatives/api/v3/orderbook?symbol=PF_XBTUSD``
Pas d'authentification.  Retourne ``{"orderBook": {"bids": [[price, size], ...],
"asks": [[price, size], ...]}, ...}``.

## Logique

Spread relatif top-of-book = (ask_top - bid_top) / mid_price × 10 000 (bps).
- Spread > 8 bps → soft veto ×0.85 (marché thin Kraken)
- Sinon : neutre ×1.0

Calibration mesurée sur Kraken Futures en condition normale :
- BTC (PF_XBTUSD) ~ 0.5-1.5 bps
- ETH (PF_ETHUSD) ~ 1-3 bps
- Altcoins (SOL/ADA/...) ~ 3-10 bps en régime normal, pic > 20 bps en stress

Seuil 8 bps catche les conditions anormales sans flagguer le bruit habituel
sur les altcoins.  Surcharge via env ``KRAKEN_ORDERBOOK_SPREAD_THRESHOLD_BPS``.

## Cache

Dict mémoire TTL 30 sec (cohérent avec Binance orderbook, microstructure
évolue en secondes).

Feature flag : ``KRAKEN_ORDERBOOK_SCORING_ENABLED=true``.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request

logger = logging.getLogger(__name__)

_KRAKEN_ORDERBOOK_BASE = "https://futures.kraken.com/derivatives/api/v3/orderbook"

_PAIR_TO_SYMBOL: dict[str, str] = {
    "BTC/USD": "PF_XBTUSD",
    "ETH/USD": "PF_ETHUSD",
    "SOL/USD": "PF_SOLUSD",
    "ADA/USD": "PF_ADAUSD",
    "XRP/USD": "PF_XRPUSD",
    "LTC/USD": "PF_LTCUSD",
    "BCH/USD": "PF_BCHUSD",
    "DOT/USD": "PF_DOTUSD",
    "DOGE/USD": "PF_DOGEUSD",
}

# Seuil spread (bps) — plus élevé que Binance (5 bps) car Kraken est moins liquide.
_SPREAD_THRESHOLD_BPS = float(
    os.getenv("KRAKEN_ORDERBOOK_SPREAD_THRESHOLD_BPS", "8.0")
)
_SOFT_VETO_MULTIPLIER = 0.85

# Cache en mémoire : {symbol -> (spread_bps, fetched_at)}.  TTL 30 sec.
_CACHE: dict[str, tuple[float, float]] = {}
_CACHE_TTL_SEC = 30.0


def is_crypto_pair(pair: str) -> bool:
    """Retourne True si la paire est dans la liste crypto Kraken Futures."""
    return pair in _PAIR_TO_SYMBOL


def _get_spread_bps(symbol: str) -> float | None:
    """Retourne le spread relatif top-of-book en basis points, ou None."""
    now = time.time()
    cached = _CACHE.get(symbol)
    if cached is not None and (now - cached[1]) < _CACHE_TTL_SEC:
        return cached[0]
    try:
        url = f"{_KRAKEN_ORDERBOOK_BASE}?symbol={symbol}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "scalping-radar/1.0"},
        )
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read())
        book = data.get("orderBook", {})
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        if not bids or not asks:
            return None
        # Format Kraken : [[price, size], ...]
        bid = float(bids[0][0])
        ask = float(asks[0][0])
        if bid <= 0 or ask <= 0:
            return None
        mid = (bid + ask) / 2.0
        spread_bps = (ask - bid) / mid * 10_000
        _CACHE[symbol] = (spread_bps, now)
        return spread_bps
    except Exception as e:
        logger.debug(f"kraken_orderbook: depth {symbol}: {e}")
        return None


def apply_kraken_orderbook(
    pair: str, direction: str, base_score: float
) -> tuple[float, dict]:
    """Applique le filtre order book depth Kraken Futures.

    Parameters
    ----------
    pair:
        Paire interne (ex: ``"BTC/USD"``).
    direction:
        Direction du setup — ``"buy"`` ou ``"sell"`` (non utilisé pour le
        filtre spread mais conservé pour cohérence avec les autres modules).
    base_score:
        Score de confiance courant avant application du filtre.

    Returns
    -------
    (new_score, meta) où :
    - ``new_score`` : score après application du multiplicateur.
    - ``meta`` : dict avec clés ``multiplier``, ``reason`` (str | None),
      ``spread_bps`` (float | None).

    Best-effort : retourne (base_score, {multiplier: 1.0, ...}) sur toute erreur.
    """
    _neutral: dict = {"multiplier": 1.0, "reason": None, "spread_bps": None}
    if not is_crypto_pair(pair):
        return base_score, _neutral
    symbol = _PAIR_TO_SYMBOL.get(pair)
    if not symbol:
        return base_score, _neutral
    try:
        spread_bps = _get_spread_bps(symbol)
        if spread_bps is None:
            return base_score, _neutral
        if spread_bps > _SPREAD_THRESHOLD_BPS:
            reason = (
                f"spread Kraken élargi {spread_bps:.1f} bps "
                f"(seuil {_SPREAD_THRESHOLD_BPS}) — marché thin, slippage attendu"
            )
            mult = _SOFT_VETO_MULTIPLIER
            new_score = round(min(100.0, max(0.0, base_score * mult)), 1)
            return new_score, {"multiplier": mult, "reason": reason, "spread_bps": spread_bps}
        return base_score, {"multiplier": 1.0, "reason": None, "spread_bps": spread_bps}
    except Exception as e:
        logger.debug(f"kraken_orderbook_scoring {pair}: {e}")
        return base_score, _neutral
