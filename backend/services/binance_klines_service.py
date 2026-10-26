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
# Plafond de bougies par appel REST (documente plus haut : limit max 1500).
_PLAFOND_PAR_APPEL = 1500

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


async def fetch_klines_fenetre(
    pair: str,
    interval: str,
    debut: "datetime",
    fin: "datetime",
    plafond_appels: int = 200,
) -> list[Candle]:
    """Bougies d'une FENETRE DE DATES [debut, fin], paginees.

    Pose le 2026-10-26 pour le rattrapage des setups en file. `fetch_klines`
    ne sait demander que les N DERNIERES bougies : pour une fenetre ancienne
    il rend donc vide **par construction**, et non parce que la donnee
    manque. C'est la cause racine du silence de 65 jours de la
    reconciliation -- personne n'avait jamais demande la bonne periode.

    ⛔ NE LIT JAMAIS LE CACHE WEBSOCKET. Celui-ci ne porte que le temps reel,
    et un cache indexe sur (paire, intervalle) sans la taille a deja servi la
    serie COURTE du cycle en cours a un appelant qui voulait une serie longue
    (defaut du 2026-09-08 : « 0 bougie », sans erreur ni trace).

    ⚠️ `plafond_appels` borne la pagination : une fenetre absurde ne doit pas
    pouvoir boucler indefiniment. L'atteindre est JOURNALISE -- une troncature
    muette se lirait comme « la periode est couverte » alors qu'elle ne l'est
    pas.

    Best-effort comme `fetch_klines` : toute erreur rend ce qui a ete obtenu
    jusque-la, mais **jamais en silence**.
    """
    symbol = _PAIR_TO_SYMBOL.get(pair)
    if not symbol:
        return []
    bn_interval = _INTERVAL_MAP.get(interval)
    if not bn_interval:
        logger.warning(f"binance klines fenetre: intervalle inconnu {interval}")
        return []

    debut_ms = int(debut.timestamp() * 1000)
    fin_ms = int(fin.timestamp() * 1000)
    if fin_ms <= debut_ms:
        return []

    brutes: list[list] = []
    curseur = debut_ms
    appels = 0
    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            while curseur <= fin_ms and appels < plafond_appels:
                r = await c.get(
                    f"{_BINANCE_PUBLIC_BASE}/fapi/v1/klines",
                    params={
                        "symbol": symbol,
                        "interval": bn_interval,
                        "startTime": curseur,
                        "endTime": fin_ms,
                        "limit": _PLAFOND_PAR_APPEL,
                    },
                )
                r.raise_for_status()
                lot = r.json()
                appels += 1
                if not lot:
                    break
                brutes.extend(lot)
                # on repart APRES la derniere bougie recue, jamais dessus :
                # relire la meme borne ferait boucler sans fin.
                dernier = int(lot[-1][0])
                if dernier <= curseur - 1:
                    break
                curseur = dernier + 1
                if len(lot) < _PLAFOND_PAR_APPEL:
                    break
    except Exception as e:  # noqa: BLE001
        logger.warning(
            f"binance klines fenetre {pair} {debut:%Y-%m-%d}->{fin:%Y-%m-%d}"
            f" : {e} -- {len(brutes)} bougies obtenues avant l'erreur"
        )

    if appels >= plafond_appels and curseur <= fin_ms:
        logger.warning(
            f"binance klines fenetre {pair} : plafond de {plafond_appels}"
            f" appels atteint, la periode n'est PAS entierement couverte"
            f" (arrete a {curseur})"
        )

    bougies: list[Candle] = []
    vus: set[int] = set()
    for k in brutes:
        try:
            ouverture = int(k[0])
            if ouverture in vus or not (debut_ms <= ouverture <= fin_ms):
                continue
            vus.add(ouverture)
            bougies.append(Candle(
                timestamp=datetime.fromtimestamp(ouverture / 1000, tz=timezone.utc),
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
            ))
        except (KeyError, ValueError, IndexError, TypeError) as e:
            logger.debug(f"binance klines fenetre parsing {pair}: {e}")
            continue
    bougies.sort(key=lambda c: c.timestamp)
    return bougies

def is_crypto_pair(pair: str) -> bool:
    """True si la pair est dans la liste des cryptos supportées par Binance Futures."""
    return pair in _PAIR_TO_SYMBOL


async def fetch_klines(pair: str, interval: str, limit: int = 50, _bypass_ws: bool = False) -> list[Candle]:
    """Récupère les bougies OHLC depuis Binance Futures.

    Si chantier #7 WebSocket activé (BINANCE_KLINES_WS_ENABLED) et que la
    pair × interval est streamée, retourne le cache WS (latence ~0 ms).
    Sinon fallback REST API (latence 100-500 ms).

    ``_bypass_ws`` est réservé au pré-amorçage du cache WS lui-même
    (binance_klines_ws._prime_cache_via_rest) pour éviter la boucle.

    Returns list[Candle] triée chronologique (oldest → newest), identique
    en shape à ce que retourne ``_fetch_twelvedata``.

    Best-effort : toute erreur (réseau, parsing, symbole inconnu) renvoie
    une liste vide. Le caller (price_service) doit alors fallback ailleurs
    (Twelve Data) ou skip la pair pour ce cycle.
    """
    if not _bypass_ws:
        from backend.services import binance_klines_ws
        if binance_klines_ws.is_ws_supported(pair, interval):
            await binance_klines_ws.ensure_started()
            cached = binance_klines_ws.get_cached_candles(pair, interval, limit)
            if len(cached) >= min(limit, 20):
                return cached
            # cache insuffisant (pas encore peuplé) → fallback REST silencieux

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
