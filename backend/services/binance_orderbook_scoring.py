"""Binance order book depth — filtre liquidité sur cryptos.

Phase 2 Palier 2 — chantier #4 (2026-06-18) : utilise l'épaisseur du
carnet d'ordres Binance Futures comme signal de qualité d'exécution.
Un spread élargi = marché thin = slippage attendu plus élevé = mauvais
moment pour entrer.

## Logique Phase R&D (simple, à enrichir en chantier #5/#6)

Spread relatif = (ask_top - bid_top) / mid_price en basis points.
- Spread > 5 bps (0.05%) → soft veto ×0.85 (marché peu liquide)
- Sinon : neutre ×1.0

Calibration des seuils (mesurés sur Binance USDⓈ-M en condition normale) :
- BTC ~ 0.1-0.3 bps
- ETH ~ 0.5-1.5 bps
- Altcoins (SOL/ADA/...) ~ 1-3 bps
- En période de stress / news : peut monter à 10-50 bps

Seuil 5 bps catche les conditions anormales sans flagguer le bruit normal.

## Architecture

Cache léger en mémoire (TTL 10s) car les setups crypto sont rares mais
peuvent être plusieurs au même cycle. urllib.request sync (cohérent avec
les autres scoring modules synchrones).

Feature flag : ``BINANCE_ORDERBOOK_SCORING_ENABLED=true``.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_PUBLIC_BASE = "https://fapi.binance.com"

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

# Seuil spread relatif (bps) au-delà duquel on considère le marché thin.
_SPREAD_THRESHOLD_BPS = float(os.getenv("BINANCE_ORDERBOOK_SPREAD_THRESHOLD_BPS", "5.0"))
_SOFT_VETO_MULTIPLIER = 0.85

# Cache en mémoire : {symbol -> (spread_bps, fetched_at)}. TTL 10s.
_CACHE: dict[str, tuple[float, float]] = {}
_CACHE_TTL_SEC = 10.0


def is_crypto_pair(pair: str) -> bool:
    return pair in _PAIR_TO_SYMBOL


def _get_spread_bps(symbol: str) -> float | None:
    """Retourne le spread relatif top-of-book en basis points, ou None."""
    now = time.time()
    cached = _CACHE.get(symbol)
    if cached is not None and (now - cached[1]) < _CACHE_TTL_SEC:
        return cached[0]
    try:
        req = urllib.request.Request(
            f"{_PUBLIC_BASE}/fapi/v1/depth?symbol={symbol}&limit=5",
            headers={"User-Agent": "scalping-radar/1.0"},
        )
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read())
        bid = float(data["bids"][0][0])
        ask = float(data["asks"][0][0])
        if bid <= 0 or ask <= 0:
            return None
        mid = (bid + ask) / 2.0
        spread_bps = (ask - bid) / mid * 10_000
        _CACHE[symbol] = (spread_bps, now)
        return spread_bps
    except Exception as e:
        logger.debug(f"orderbook_scoring depth {symbol}: {e}")
        return None


def apply_orderbook_filter(pair: str, direction: str) -> tuple[float, str | None]:
    """Retourne (multiplier, reason).

    multiplier : 1.0 (neutre) ou 0.85 (soft veto thin market).
    reason : string explicative si veto, sinon None.

    Best-effort : (1.0, None) silencieusement sur toute erreur.
    """
    if not is_crypto_pair(pair):
        return 1.0, None
    sym = _PAIR_TO_SYMBOL.get(pair)
    if not sym:
        return 1.0, None
    spread_bps = _get_spread_bps(sym)
    if spread_bps is None:
        return 1.0, None
    if spread_bps > _SPREAD_THRESHOLD_BPS:
        return (
            _SOFT_VETO_MULTIPLIER,
            f"spread élargi {spread_bps:.1f} bps (seuil {_SPREAD_THRESHOLD_BPS}) — "
            f"marché thin, slippage attendu",
        )
    return 1.0, None
