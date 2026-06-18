"""Binance USDⓈ-M Futures klines (OHLC) — source data native pour cryptos.

Phase 2 R&D Palier 2 — chantier #1 (2026-06-18) : remplace Twelve Data
pour les paires crypto par les vraies bougies Binance Futures. Avantages :

- Gratuit + illimité (pas de rate limit 429 Twelve Data Grow)
- Pas de delay (Binance publie directement la kline finale à T+0)
- Données alignées avec ce que voit le marché (et avec ce qu'on push via
  binance-bridge → meilleur alignement signal → exécution)
- Volume réel inclus (Twelve Data renvoie 0 pour les cryptos forex-routed)

Endpoint public : GET /fapi/v1/klines
- Pas d'auth
- Limit max 1500 bougies par appel
- Format réponse : array de arrays [openTime_ms, open, high, low, close,
  volume, closeTime_ms, quoteVol, trades, takerBuyBase, takerBuyQuote, ignore]

Convention pair : scalping-radar "BTC/USD" → Binance "BTCUSDT" (identique
au mapping déjà câblé dans binance-bridge/bridge.py).

Le mode est feature-flagged via BINANCE_KLINES_ENABLED. Désactivé = retour
au comportement Twelve Data sur tous les actifs (rollback instantané).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from backend.models.schemas import Candle

logger = logging.getLogger(__name__)

_BINANCE_PUBLIC_BASE = "https://fapi.binance.com"

# Mapping pair scalping-radar → symbole Binance USDⓈ-M (perp USDT-collateralized).
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

# Mapping interval Twelve Data → interval Binance.
_INTERVAL_MAP: dict[str, str] = {
    "1min": "1m", "5min": "5m", "15min": "15m", "30min": "30m",
    "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h", "12h": "12h",
    "1day": "1d", "1week": "1w",
}


def is_crypto_pair(pair: str) -> bool:
    """True si la pair est dans la liste des cryptos supportées par Binance Futures."""
    return pair in _PAIR_TO_SYMBOL


async def fetch_klines(pair: str, interval: str, limit: int = 50) -> list[Candle]:
    """Récupère les bougies OHLC depuis Binance Futures public API.

    Returns list[Candle] triée chronologique (oldest → newest), identique
    en shape à ce que retourne ``_fetch_twelvedata``.

    Best-effort : toute erreur (réseau, parsing, symbole inconnu) renvoie
    une liste vide. Le caller (price_service) doit alors fallback ailleurs
    (Twelve Data) ou skip la pair pour ce cycle.
    """
    symbol = _PAIR_TO_SYMBOL.get(pair)
    if not symbol:
        return []
    bn_interval = _INTERVAL_MAP.get(interval)
    if not bn_interval:
        logger.warning(f"binance_klines: unknown interval {interval}")
        return []
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get(
                f"{_BINANCE_PUBLIC_BASE}/fapi/v1/klines",
                params={"symbol": symbol, "interval": bn_interval, "limit": limit},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.warning(f"binance klines erreur pour {pair} ({interval}): {e}")
        return []

    candles: list[Candle] = []
    for k in data:
        try:
            candles.append(Candle(
                timestamp=datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc),
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
            ))
        except (KeyError, ValueError, IndexError, TypeError) as e:
            logger.debug(f"binance klines parsing erreur {pair}: {e}")
            continue
    # Binance retourne déjà chronologique (oldest → newest), pas de reverse.
    logger.info(f"Binance klines: {len(candles)} bougies pour {pair} ({interval})")
    return candles
