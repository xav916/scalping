"""Funding rate Kraken Futures — filtre contrarien du scoring crypto.

Miroir de ``binance_funding_scoring.py`` mais consomme l'endpoint public
Kraken Futures au lieu de Binance USDⓈ-M.  Les taux de funding Kraken
peuvent diverger de Binance de 10-30% sur XBT/ETH en période de stress,
ce qui justifie un filtre natif pour les signaux routés vers ``admin_kraken``.

## Source de données

``GET https://futures.kraken.com/derivatives/api/v3/tickers``
Pas d'authentification requise.  Champ ``fundingRate`` (par 8h) par symbole
``PF_*`` (perpetual futures).

## Logique

Identique au filtre Binance :
- Funding > +0.05% (longs surcrowdés) + setup BUY  → soft veto ×0.85
- Funding < -0.05% (shorts surcrowdés) + setup SELL → soft veto ×0.85
- Sinon : multiplier 1.0 (neutre)

## Cache

Dict en mémoire avec TTL 30 min (les settlements sont toutes les 8h,
les taux bougent lentement hors chocs).

## Activation

Feature flag ``KRAKEN_FUNDING_SCORING_ENABLED=true`` dans .env.
Désactivé = no-op identique au comportement sans le module.

## Non-livrables dans ce module

- LSR (Long/Short Ratio) : Kraken n'expose pas de LSR retail public via API.
  Fallback = utiliser Binance LSR (``binance_lsr_scoring``) même pour
  signaux ``admin_kraken``. Comportement actuel inchangé.
- Orderflow aggressor : ``/derivatives/api/v3/history`` existe mais le
  pattern d'agrégation taker buy vs sell est à définir — reporté en sprint
  dédié (``kraken_orderflow_scoring`` futur).
- Klines : V1 utilise Twelve Data OHLC pour le scoring principal, les
  klines Kraken ne sont pas nécessaires pour les 3 features side-channel.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request

logger = logging.getLogger(__name__)

_KRAKEN_TICKERS_URL = "https://futures.kraken.com/derivatives/api/v3/tickers"

# Mapping pair interne → symbole Kraken Futures perpetual (PF_*)
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

# Seuil funding rate "extrême" (par 8h, en valeur absolue).
_DEFAULT_EXTREME_THRESHOLD = 0.0005  # 0.05% par 8h, annualisé ~54%
_EXTREME_THRESHOLD = float(
    os.getenv("KRAKEN_FUNDING_EXTREME_THRESHOLD", _DEFAULT_EXTREME_THRESHOLD)
)

_SOFT_VETO_MULTIPLIER = 0.85

# Cache en mémoire : {symbol -> (rate, fetched_at)}.  TTL 30 min.
_CACHE: dict[str, tuple[float, float]] = {}
_CACHE_TTL_SEC = 1800.0

# Timestamp du dernier fetch global (on récupère tous les symbols en une requête).
_LAST_FETCH_AT: float = 0.0
_LAST_FETCH_DATA: dict[str, float] = {}  # {symbol -> fundingRate}


def is_crypto_pair(pair: str) -> bool:
    """Retourne True si la paire est dans la liste crypto Kraken Futures."""
    return pair in _PAIR_TO_SYMBOL


def _fetch_all_rates() -> dict[str, float]:
    """Fetch le snapshot complet des tickers Kraken Futures.

    Retourne {symbol -> fundingRate}.  Dict vide si indisponible.
    Une seule requête HTTP pour tous les symboles (endpoint retourne tous
    les tickers en un seul payload JSON).
    """
    global _LAST_FETCH_AT, _LAST_FETCH_DATA
    now = time.time()
    if now - _LAST_FETCH_AT < _CACHE_TTL_SEC and _LAST_FETCH_DATA:
        return _LAST_FETCH_DATA
    try:
        req = urllib.request.Request(
            _KRAKEN_TICKERS_URL,
            headers={"User-Agent": "scalping-radar/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
        tickers = data.get("tickers", [])
        rates: dict[str, float] = {}
        for t in tickers:
            sym = t.get("symbol", "")
            rate = t.get("fundingRate")
            if sym and rate is not None:
                try:
                    rates[sym] = float(rate)
                except (TypeError, ValueError):
                    pass
        _LAST_FETCH_AT = now
        _LAST_FETCH_DATA = rates
        return rates
    except Exception as e:
        logger.debug(f"kraken_funding: fetch tickers failed: {e}")
        return _LAST_FETCH_DATA  # retourner le cache périmé plutôt que vide


def _get_funding_rate(symbol: str) -> float | None:
    """Retourne le funding rate Kraken pour un symbole PF_*, ou None."""
    rates = _fetch_all_rates()
    return rates.get(symbol)


def apply_kraken_funding(
    pair: str, direction: str, base_score: float
) -> tuple[float, dict]:
    """Applique le filtre funding rate Kraken Futures.

    Parameters
    ----------
    pair:
        Paire interne (ex: ``"BTC/USD"``).
    direction:
        Direction du setup — ``"buy"`` ou ``"sell"``.
    base_score:
        Score de confiance courant avant application du filtre.

    Returns
    -------
    (new_score, meta) où :
    - ``new_score`` : score après application du multiplicateur.
    - ``meta`` : dict avec clés ``multiplier``, ``reason`` (str | None),
      ``symbol``, ``rate`` (float | None).

    Best-effort : retourne (base_score, {multiplier: 1.0, reason: None}) sur
    toute erreur — comportement neutre safe par défaut.
    """
    if not is_crypto_pair(pair):
        return base_score, {"multiplier": 1.0, "reason": None, "symbol": None, "rate": None}
    symbol = _PAIR_TO_SYMBOL.get(pair)
    if not symbol:
        return base_score, {"multiplier": 1.0, "reason": None, "symbol": None, "rate": None}
    try:
        rate = _get_funding_rate(symbol)
        if rate is None:
            return base_score, {"multiplier": 1.0, "reason": None, "symbol": symbol, "rate": None}
        if direction == "buy" and rate > _EXTREME_THRESHOLD:
            reason = (
                f"funding Kraken extrême positif {rate * 100:.3f}% "
                f"— longs surcrowdés, contrarien BUY"
            )
            mult = _SOFT_VETO_MULTIPLIER
        elif direction == "sell" and rate < -_EXTREME_THRESHOLD:
            reason = (
                f"funding Kraken extrême négatif {rate * 100:.3f}% "
                f"— shorts surcrowdés, contrarien SELL"
            )
            mult = _SOFT_VETO_MULTIPLIER
        else:
            return base_score, {"multiplier": 1.0, "reason": None, "symbol": symbol, "rate": rate}
        new_score = round(min(100.0, max(0.0, base_score * mult)), 1)
        return new_score, {"multiplier": mult, "reason": reason, "symbol": symbol, "rate": rate}
    except Exception as e:
        logger.debug(f"kraken_funding_scoring {pair}: {e}")
        return base_score, {"multiplier": 1.0, "reason": None, "symbol": symbol, "rate": None}
