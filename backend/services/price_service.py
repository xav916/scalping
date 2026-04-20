"""Service de prix temps réel pour XAU/USD et autres paires.

Sources supportées (sélectionnées via PRICE_SOURCE) :
- "mt5" : MetaTrader 5 (temps réel, requiert MT5 desktop + package MetaTrader5)
- "twelvedata" : Twelve Data API (polling, gratuit 800 req/jour)

Fallback : données simulées si la source est indisponible.
"""

import logging
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


async def fetch_candles(
    pair: str,
    interval: str = "5min",
    outputsize: int = 50,
) -> tuple[list[Candle], bool]:
    """Récupère les bougies OHLC pour une paire donnée.

    Args:
        pair: Paire (ex: "XAU/USD")
        interval: Intervalle ("1min", "5min", "15min")
        outputsize: Nombre de bougies à récupérer

    Returns:
        Tuple (liste de Candle triées du plus ancien au plus récent, is_simulated)
    """
    # Source MT5 (temps réel)
    if PRICE_SOURCE == "mt5":
        candles, is_sim = await mt5_service.fetch_candles(pair, interval, outputsize)
        if candles:
            return candles, is_sim
        logger.warning(f"MT5 indisponible pour {pair}, pair ignorée ce cycle")
        return [], False

    # Source Twelve Data (polling)
    candles = await _fetch_twelvedata(pair, interval, outputsize)
    if candles:
        return candles, False

    # API indisponible : on n'invente plus de prix. Les callers (scheduler)
    # skippent naturellement les pairs sans candles. L'ancien fallback
    # _generate_simulated_candles utilisait un prix hardcodé (2650) qui
    # partait en auto-exec MT5 et se faisait rejeter rc=10016.
    logger.warning(f"API Twelve Data indisponible pour {pair}, pair ignorée ce cycle")
    return [], False


async def fetch_current_price(pair: str) -> float | None:
    """Récupère le prix actuel d'une paire."""
    if PRICE_SOURCE == "mt5":
        price = await mt5_service.fetch_current_price(pair)
        if price is not None:
            return price
        # Pas de fallback Twelve Data ici si MT5 est sélectionné explicitement
        return None

    symbol = SYMBOL_MAP.get(pair, pair)

    if not TWELVEDATA_API_KEY:
        return None

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
                return float(data["price"])
    except Exception as e:
        logger.warning(f"Erreur prix {pair}: {e}")

    return None


async def _fetch_twelvedata(
    pair: str, interval: str, outputsize: int
) -> list[Candle]:
    """Récupère les bougies via Twelve Data API."""
    symbol = SYMBOL_MAP.get(pair, pair)

    if not TWELVEDATA_API_KEY:
        logger.info("Pas de clé API Twelve Data configurée")
        return []

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


