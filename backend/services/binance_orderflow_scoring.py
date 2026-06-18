"""Aggressor side ratio Binance — filtre orderflow court terme sur cryptos.

Phase 2 Palier 2 — chantier #5 (2026-06-18) : mesure quelle camp (acheteurs
ou vendeurs agressifs) domine actuellement en frappant le carnet d'ordres.

## Logique

Chaque trade Binance Futures a un flag `isBuyerMaker` (m=true/false) :
- m=true  → l'acheteur était maker (passif) → vendeur était l'agresseur
- m=false → l'acheteur était taker (market buy) → acheteur était l'agresseur

Ratio = volume_buy_aggressor / volume_total

- Ratio > 0.65 : acheteurs agressifs dominent → momentum hausser
- Ratio < 0.35 : vendeurs agressifs dominent → momentum baissier
- Sinon : équilibré

Comme **filtre de momentum alignment** :
- BUY + ratio < 0.35 (vendeurs agressifs) → misaligned, soft veto ×0.85
- SELL + ratio > 0.65 (acheteurs agressifs) → misaligned, soft veto ×0.85

## Différence avec chantier #2 (funding) et #3 (LSR)

- Funding (#2) = mesure le coût payé sur 8h, signal de positioning structurel
- LSR (#3) = mesure le nombre de comptes long vs short, retail positioning
- Aggressor (#5) = mesure qui frappe le carnet maintenant, momentum très court terme

Les 3 sont complémentaires : positioning structurel, positioning retail,
et momentum live.

## Implémentation

Query `/fapi/v1/aggTrades?symbol=X&limit=500` direct (no auth, public).
500 derniers trades = échantillon court terme (typique 10-60 sec sur les
cryptos liquides). Cache 30 sec pour éviter de hammer.

Feature flag : ``BINANCE_ORDERFLOW_SCORING_ENABLED=true``.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request

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

# Seuils ratio aggressor configurable via env.
_BUY_DOMINANT_THRESHOLD = float(os.getenv("BINANCE_ORDERFLOW_BUY_DOMINANT", "0.65"))
_SELL_DOMINANT_THRESHOLD = float(os.getenv("BINANCE_ORDERFLOW_SELL_DOMINANT", "0.35"))
_SOFT_VETO_MULTIPLIER = 0.85

# Cache en mémoire : {symbol -> (ratio, fetched_at)}. TTL 30s.
_CACHE: dict[str, tuple[float, float]] = {}
_CACHE_TTL_SEC = 30.0
_AGGTRADES_LIMIT = 500


def is_crypto_pair(pair: str) -> bool:
    return pair in _PAIR_TO_SYMBOL


def _get_aggressor_buy_ratio(symbol: str) -> float | None:
    """Retourne le ratio volume_buy_aggressor / volume_total sur les
    500 derniers trades agrégés. None si erreur ou volume 0.
    """
    now = time.time()
    cached = _CACHE.get(symbol)
    if cached is not None and (now - cached[1]) < _CACHE_TTL_SEC:
        return cached[0]
    try:
        req = urllib.request.Request(
            f"{_PUBLIC_BASE}/fapi/v1/aggTrades?symbol={symbol}&limit={_AGGTRADES_LIMIT}",
            headers={"User-Agent": "scalping-radar/1.0"},
        )
        with urllib.request.urlopen(req, timeout=4) as r:
            trades = json.loads(r.read())
    except Exception as e:
        logger.debug(f"orderflow_scoring aggTrades {symbol}: {e}")
        return None
    buy_vol = 0.0
    sell_vol = 0.0
    for t in trades:
        qty = float(t.get("q", 0) or 0)
        if t.get("m"):  # isBuyerMaker=true → seller was aggressor
            sell_vol += qty
        else:
            buy_vol += qty
    total = buy_vol + sell_vol
    if total <= 0:
        return None
    ratio = buy_vol / total
    _CACHE[symbol] = (ratio, now)
    return ratio


def apply_orderflow_filter(pair: str, direction: str) -> tuple[float, str | None]:
    """Retourne (multiplier, reason).

    multiplier : 1.0 (neutre) ou 0.85 (soft veto momentum misaligned).
    reason : string explicative si veto, sinon None.

    Best-effort : (1.0, None) silencieusement sur toute erreur.
    """
    if not is_crypto_pair(pair):
        return 1.0, None
    sym = _PAIR_TO_SYMBOL.get(pair)
    if not sym:
        return 1.0, None
    ratio = _get_aggressor_buy_ratio(sym)
    if ratio is None:
        return 1.0, None
    if direction == "buy" and ratio < _SELL_DOMINANT_THRESHOLD:
        return (_SOFT_VETO_MULTIPLIER,
                f"orderflow {ratio*100:.0f}% acheteurs agressifs — "
                f"vendeurs dominent, momentum baissier court terme, contrarien BUY")
    if direction == "sell" and ratio > _BUY_DOMINANT_THRESHOLD:
        return (_SOFT_VETO_MULTIPLIER,
                f"orderflow {ratio*100:.0f}% acheteurs agressifs — "
                f"acheteurs dominent, momentum haussier court terme, contrarien SELL")
    return 1.0, None
