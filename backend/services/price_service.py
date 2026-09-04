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
# 55 req/min.
#
# ⛔ CE RAISONNEMENT NE SUFFIT PLUS (2026-09-04). « 8 requêtes parallèles + un
# cycle de 200 s » était vrai avec moins de paires. L'univers a grandi — 29
# paires x 2 intervalles + le shadow journalier — et la CONCURRENCE N'EST PAS
# LE DEBIT : 8 requêtes en vol avec ~100 ms de latence, c'est jusqu'à 80
# appels par seconde.
#
# Mesuré en prod :
#     usage en régime          7 / 55     <- aucun dépassement en MOYENNE
#     appels dans une minute 171          <- limite 55
#     appels en UNE seconde   54
#     paires ignorées        502 en 6 h
#
# Le débit moyen valait ~12/min. Tout le problème tenait à la concentration :
# ~35 requêtes tirées en une à deux secondes, puis 178 s de silence.
_TWELVEDATA_MAX_CONCURRENT = int(os.getenv("TWELVEDATA_MAX_CONCURRENT", "8"))

# 50 et non 55 : une marge sous la limite du plan absorbe les réessais et les
# appels faits hors de ce module. `0` désactive le limiteur (comportement
# d'avant), pour pouvoir revenir en arrière sans redéploiement.
_TWELVEDATA_MAX_PER_MIN = int(os.getenv("TWELVEDATA_MAX_PER_MIN", "50"))

# ⛔ Plafond d'attente. Sans lui, une rafale de réessais ferait la queue
# indéfiniment et un cycle pourrait dépasser son intervalle de 180 s — on
# empilerait des cycles au lieu d'en rater un proprement.
_TWELVEDATA_WAIT_MAX_SEC = float(os.getenv("TWELVEDATA_WAIT_MAX_SEC", "60"))


class _SeauAJetons:
    """Limiteur de débit à seau de jetons, sûr en concurrence.

    Le seau part PLEIN : une rafale sous la capacité ne coûte aucune latence,
    ce qui est le cas 90 % du temps. Au-delà, chaque jeton se regagne au
    rythme ``par_minute / 60`` par seconde.

    ``acquerir()`` rend ``False`` — sans attendre — quand l'attente
    dépasserait ``plafond_attente``. Renoncer vite vaut mieux que faire
    déborder un cycle sur le suivant.
    """

    def __init__(self, par_minute: int, plafond_attente: float):
        self.par_minute = par_minute
        self.plafond_attente = plafond_attente
        self.jetons = float(par_minute)
        self._dernier = time.monotonic()
        self._verrou: asyncio.Lock | None = None

    def _remplir(self) -> None:
        maintenant = time.monotonic()
        gagnes = (maintenant - self._dernier) * self.par_minute / 60.0
        self.jetons = min(float(self.par_minute), self.jetons + gagnes)
        self._dernier = maintenant

    async def acquerir(self) -> bool:
        if self.par_minute <= 0:
            return True
        if self._verrou is None:
            # Paresseux comme le sémaphore : `asyncio.Lock()` veut une boucle.
            self._verrou = asyncio.Lock()

        # ⚠️ Le calcul de l'attente ET la consommation du jeton se font SOUS
        # LE MEME VERROU. Les séparer laisserait deux coroutines consommer le
        # même jeton — le limiteur laisserait alors passer plus que sa
        # capacité, soit exactement le défaut qu'il corrige.
        async with self._verrou:
            self._remplir()
            if self.jetons < 1.0:
                manque = 1.0 - self.jetons
                attente = manque * 60.0 / self.par_minute
                if attente > self.plafond_attente:
                    return False          # ⛔ on renonce SANS consommer
                await asyncio.sleep(attente)
                self._remplir()
            self.jetons -= 1.0
            return True


_twelvedata_seau: "_SeauAJetons | None" = None


def _get_seau() -> "_SeauAJetons":
    global _twelvedata_seau
    if _twelvedata_seau is None:
        _twelvedata_seau = _SeauAJetons(
            _TWELVEDATA_MAX_PER_MIN, _TWELVEDATA_WAIT_MAX_SEC)
    return _twelvedata_seau

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

    # Source Binance Futures public klines pour cryptos (Phase 2 Palier 2,
    # chantier #1 2026-06-18). Native + gratuit + illimité, plus fidèle au
    # marché réel que Twelve Data CFD-routed. Feature flag pour rollback.
    try:
        from config.settings import BINANCE_KLINES_ENABLED
    except Exception:
        BINANCE_KLINES_ENABLED = False
    if BINANCE_KLINES_ENABLED:
        from backend.services import binance_klines_service
        if binance_klines_service.is_crypto_pair(pair):
            candles = await binance_klines_service.fetch_klines(pair, interval, outputsize)
            if candles:
                _cache_store_candles(pair, interval, candles)
                return candles, False
            logger.warning(f"Binance klines indisponible pour {pair}, fallback Twelve Data")

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

    # Crypto routing Binance natif (cf. fetch_candles ci-dessus).
    try:
        from config.settings import BINANCE_KLINES_ENABLED
    except Exception:
        BINANCE_KLINES_ENABLED = False
    if BINANCE_KLINES_ENABLED:
        from backend.services import binance_klines_service
        if binance_klines_service.is_crypto_pair(pair):
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.get(
                        "https://fapi.binance.com/fapi/v1/ticker/price",
                        params={"symbol": binance_klines_service._PAIR_TO_SYMBOL[pair]},
                    )
                    r.raise_for_status()
                    price = float(r.json()["price"])
                    _cache_store_price(pair, price)
                    return price
            except Exception as e:
                logger.warning(f"Binance ticker indisponible pour {pair}, fallback Twelve Data: {e}")

    symbol = SYMBOL_MAP.get(pair, pair)

    if not TWELVEDATA_API_KEY:
        return None

    # ⛔ Le limiteur AVANT le semaphore : celui-ci borne la concurrence, celui-la
    # le debit. Les deux sont necessaires, et ce n'est pas la meme chose — 8
    # requetes en vol a 100 ms de latence font 80 appels/seconde.
    if not await _get_seau().acquerir():
        logger.warning(
            "Twelve Data: debit sature, prix abandonne pour %s (attente > %ss)",
            pair, _TWELVEDATA_WAIT_MAX_SEC)
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

    # ⛔ Le limiteur AVANT le semaphore : celui-ci borne la concurrence, celui-la
    # le debit. Les deux sont necessaires, et ce n'est pas la meme chose — 8
    # requetes en vol a 100 ms de latence font 80 appels/seconde.
    if not await _get_seau().acquerir():
        # ⚠️ Liste VIDE et non exception : l'appelant traite deja « pas de
        # bougies » (il passe la paire pour ce cycle). Lever ferait remonter
        # une saturation prevue comme une panne.
        logger.warning(
            "Twelve Data: debit sature, bougies abandonnees pour %s %s "
            "(attente > %ss)", pair, interval, _TWELVEDATA_WAIT_MAX_SEC)
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
