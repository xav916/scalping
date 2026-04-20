"""Service de prix temps réel pour XAU/USD et autres paires.

Sources supportées (sélectionnées via PRICE_SOURCE) :
- "mt5" : MetaTrader 5 (temps réel, requiert MT5 desktop + package MetaTrader5)
- "twelvedata" : Twelve Data API (polling)

Performance : cache par clé (pair, interval) et limite de concurrence sur
Twelve Data pour rester sous les 55 req/min du plan Grow. Sans cela, un
cycle parallélisé sature immédiatement le quota (observé 200 req en <1s →
rate limit + 0 candles pendant tout le reste du cycle).
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

import httpx

from backend.models.schemas import Candle
from backend.services import mt5_service
from config.settings import PRICE_SOURCE, TWELVEDATA_API_KEY

logger = logging.getLogger(__name__)

TWELVEDATA_BASE = "https://api.twelvedata.com"

HEADERS = {
    "User-Agent": "ScalpingRadar/1.0",
}

# Mapping des paires vers les symboles Twelve Data
SYMBOL_MAP = {
    "XAU/USD": "XAU/USD",
    "EUR/USD": "EUR/USD",
    "GBP/USD": "GBP/USD",
    "USD/JPY": "USD/JPY",
    "EUR/GBP": "EUR/GBP",
    "USD/CHF": "USD/CHF",
    "AUD/USD": "AUD/USD",
    "USD/CAD": "USD/CAD",
    "EUR/JPY": "EUR/JPY",
    "GBP/JPY": "GBP/JPY",
}

# TTL cache (secondes) — une candle OHLC ne bouge qu'aux bornes, donc un
# cache court < période de la candle est toujours sans perte d'info.
_CANDLE_TTL_SEC = {
    "1min": 45,
    "5min": int(os.getenv("CANDLE_CACHE_5MIN_TTL", "200")),
    "15min": 600,
    "30min": 1200,
    "1h": int(os.getenv("CANDLE_CACHE_1H_TTL", "900")),
    "4h": 1800,
    "1day": 7200,
}
_PRICE_TTL_SEC = int(os.getenv("PRICE_CACHE_TTL", "5"))

# Limite de concurrence sur les appels Twelve Data : le plan Grow autorise
# 55 req/min. 8 requêtes parallèles + un cycle de 200s = ~3 bursts/min → OK.
_TWELVEDATA_MAX_CONCURRENT = int(os.getenv("TWELVEDATA_MAX_CONCURRENT", "8"))

# État interne (caches + semaphore).
_candle_cache: dict[tuple[str, str], tuple[list[Candle], float]] = {}
_price_cache: dict[str, tuple[float, float]] = {}
_twelvedata_sem: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """Semaphore paresseux : asyncio.Semaphore() veut une boucle évent active."""
    global _twelvedata_sem
    if _twelvedata_sem is None:
        _twelvedata_sem = asyncio.Semaphore(_TWELVEDATA_MAX_CONCURRENT)
    return _twelvedata_sem


def _cache_get_candles(pair: str, interval: str) -> list[Candle] | None:
    key = (pair, interval)
    entry = _candle_cache.get(key)
    if entry is None:
        return None
    candles, fetched_at = entry
    ttl = _CANDLE_TTL_SEC.get(interval, 60)
    if time.monotonic() - fetched_at < ttl:
        return candles
    return None


def _cache_store_candles(pair: str, interval: str, candles: list[Candle]) -> None:
    _candle_cache[(pair, interval)] = (candles, time.monotonic())


def _cache_get_price(pair: str) -> float | None:
    entry = _price_cache.get(pair)
    if entry is None:
        return None
    price, fetched_at = entry
    if time.monotonic() - fetched_at < _PRICE_TTL_SEC:
        return price
    return None


def _cache_store_price(pair: str, price: float) -> None:
    _price_cache[pair] = (price, time.monotonic())


def invalidate_caches() -> None:
    """Vider tous les caches (pour tests ou rechargement manuel)."""
    _candle_cache.clear()
    _price_cache.clear()


async def fetch_candles(
    pair: str,
    interval: str = "5min",
    outputsize: int = 50,
) -> tuple[list[Candle], bool]:
    """Récupère les bougies OHLC pour une paire donnée.

    Returns:
        Tuple (liste de Candle triées du plus ancien au plus récent, is_simulated)
    """
    # Cache hit : pas d'appel API, pas de credit consommé.
    cached = _cache_get_candles(pair, interval)
    if cached is not None:
        return cached, False

    # Source MT5 (temps réel)
    if PRICE_SOURCE == "mt5":
        candles, is_sim = await mt5_service.fetch_candles(pair, interval, outputsize)
        if candles:
            _cache_store_candles(pair, interval, candles)
            return candles, is_sim
        logger.warning(f"MT5 indisponible pour {pair}, pair ignorée ce cycle")
        return [], False

    # Source Twelve Data (polling)
    candles = await _fetch_twelvedata(pair, interval, outputsize)
    if candles:
        _cache_store_candles(pair, interval, candles)
        return candles, False

    # API indisponible : on n'invente plus de prix. Les callers (scheduler)
    # skippent naturellement les pairs sans candles.
    logger.warning(f"API Twelve Data indisponible pour {pair}, pair ignorée ce cycle")
    return [], False


async def fetch_current_price(pair: str) -> float | None:
    """Récupère le prix actuel d'une paire."""
    cached = _cache_get_price(pair)
    if cached is not None:
        return cached

    if PRICE_SOURCE == "mt5":
        price = await mt5_service.fetch_current_price(pair)
        if price is not None:
            _cache_store_price(pair, price)
            return price
        return None

    symbol = SYMBOL_MAP.get(pair, pair)

    if not TWELVEDATA_API_KEY:
        return None

    async with _get_semaphore():
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{TWELVEDATA_BASE}/price",
                    params={"symbol": symbol, "apikey": TWELVEDATA_API_KEY},
                    headers=HEADERS,
                )
                response.raise_for_status()
                data = response.json()
                if "price" in data:
                    price = float(data["price"])
                    _cache_store_price(pair, price)
                    return price
        except Exception as e:
            logger.warning(f"Erreur prix {pair}: {e}")

    return None


async def _fetch_twelvedata(
    pair: str, interval: str, outputsize: int
) -> list[Candle]:
    """Récupère les bougies via Twelve Data API.

    Limite la concurrence via un semaphore global pour rester sous le quota
    req/min du plan Grow, même quand le scheduler lance ~32 appels en parallèle.
    """
    symbol = SYMBOL_MAP.get(pair, pair)

    if not TWELVEDATA_API_KEY:
        logger.info("Pas de clé API Twelve Data configurée")
        return []

    async with _get_semaphore():
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{TWELVEDATA_BASE}/time_series",
                    params={
                        "symbol": symbol,
                        "interval": interval,
                        "outputsize": outputsize,
                        "apikey": TWELVEDATA_API_KEY,
                    },
                    headers=HEADERS,
                )
                response.raise_for_status()

            data = response.json()

            if "values" not in data:
                logger.warning(f"Twelve Data: pas de données pour {pair}: {data.get('message', '')}")
                return []

            candles = []
            for item in data["values"]:
                try:
                    candles.append(Candle(
                        timestamp=datetime.fromisoformat(item["datetime"]).replace(tzinfo=timezone.utc),
                        open=float(item["open"]),
                        high=float(item["high"]),
                        low=float(item["low"]),
                        close=float(item["close"]),
                        volume=float(item.get("volume", 0)),
                    ))
                except (KeyError, ValueError) as e:
                    logger.debug(f"Erreur parsing bougie: {e}")
                    continue

            # Twelve Data renvoie du plus récent au plus ancien, on inverse
            candles.reverse()
            logger.info(f"Twelve Data: {len(candles)} bougies pour {pair} ({interval})")
            return candles

        except Exception as e:
            logger.warning(f"Twelve Data erreur pour {pair}: {e}")
            return []
