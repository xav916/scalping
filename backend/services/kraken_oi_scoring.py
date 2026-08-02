"""Open Interest divergence Kraken Futures — filtre fake breakout / liquidation.

Miroir de ``binance_oi_scoring.py`` mais consomme l'endpoint public
Kraken Futures.  L'OI Kraken Futures diverge de Binance sur les altcoins
(profondeur de marché différente) ; utiliser la source native améliore la
précision du signal pour les setups routés vers ``admin_kraken``.

## Source de données

``GET https://futures.kraken.com/derivatives/api/v3/tickers``
Champ ``openInterest`` (notionnel USD) par symbole PF_*.
Endpoint sans authentification.

## Logique

Compare l'évolution de l'Open Interest (snapshot courant vs snapshot il y a
~1h conservé en mémoire) avec l'évolution de prix sur la même fenêtre.

| Prix | OI | Interprétation | Setup pénalisé |
|---|---|---|---|
| Up | Up | Vraie tendance haussière | aucun |
| Up | **Down** | Short squeeze (shorts couvrent, pas de vrais longs) | **BUY** |
| Down | Up | Vraie tendance baissière | aucun |
| Down | **Down** | Liquidation longs (longs ferment, pas de vrais shorts) | **SELL** |

Seuils :
- Mouvement prix significatif : ±1% sur 1h (seuil légèrement plus élevé que
  Binance car Kraken Futures est moins liquide → plus de bruit de prix)
- OI déclin significatif : −2% sur 1h

## Architecture

- Cache 5 min pour le snapshot courant (OI + prix mid).
- Historique 1h conservé en dict mémoire {symbol -> (oi, price, ts)}.
- Pas de dépendance externe au-delà de urllib.request.

Feature flag : ``KRAKEN_OI_SCORING_ENABLED=true``.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request

logger = logging.getLogger(__name__)

_KRAKEN_TICKERS_URL = "https://futures.kraken.com/derivatives/api/v3/tickers"

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

_PRICE_THRESHOLD = float(os.getenv("KRAKEN_OI_PRICE_THRESHOLD", "0.01"))      # 1% sur 1h
_OI_DECLINE_THRESHOLD = float(os.getenv("KRAKEN_OI_DECLINE_THRESHOLD", "-0.02"))  # -2% sur 1h
_SOFT_VETO_MULTIPLIER = 0.85

# Cache snapshot courant : {symbol -> (oi, price_mid, fetched_at)}.  TTL 5 min.
_CURRENT_CACHE: dict[str, tuple[float, float, float]] = {}
_CACHE_TTL_SEC = 300.0

# Historique 1h : {symbol -> (oi, price_mid, ts)}.
# On conserve le premier snapshot enregistré il y a ≥ 55 min (fenêtre 1h ±5 min).
_HISTORY_1H: dict[str, tuple[float, float, float]] = {}
_HISTORY_MAX_AGE_SEC = 4200.0   # 70 min : on recycle si snapshot > 70 min
_HISTORY_MIN_AGE_SEC = 3300.0   # 55 min : on n'utilise pas un snapshot < 55 min

# Cache global tickers (partagé avec kraken_funding_scoring si importé conjointement).
_LAST_FETCH_AT: float = 0.0
_LAST_FETCH_DATA: list[dict] = []


def is_crypto_pair(pair: str) -> bool:
    """Retourne True si la paire est dans la liste crypto Kraken Futures."""
    return pair in _PAIR_TO_SYMBOL


def _fetch_tickers() -> list[dict]:
    """Retourne la liste brute des tickers Kraken Futures."""
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
        _LAST_FETCH_AT = now
        _LAST_FETCH_DATA = tickers
        return tickers
    except Exception as e:
        logger.debug(f"kraken_oi: fetch tickers failed: {e}")
        return _LAST_FETCH_DATA


def _get_current_snapshot(symbol: str) -> tuple[float, float] | None:
    """Retourne (oi, price_mid) courant pour un symbole, ou None."""
    now = time.time()
    cached = _CURRENT_CACHE.get(symbol)
    if cached is not None and (now - cached[2]) < _CACHE_TTL_SEC:
        return (cached[0], cached[1])
    tickers = _fetch_tickers()
    for t in tickers:
        if t.get("symbol") == symbol:
            oi_raw = t.get("openInterest")
            bid = t.get("bid")
            ask = t.get("ask")
            last = t.get("last")
            # Préférer mid bid/ask, fallback sur last price
            try:
                if bid is not None and ask is not None and float(bid) > 0 and float(ask) > 0:
                    price_mid = (float(bid) + float(ask)) / 2.0
                elif last is not None and float(last) > 0:
                    price_mid = float(last)
                else:
                    return None
                oi = float(oi_raw) if oi_raw is not None else None
                if oi is None or oi <= 0:
                    return None
            except (TypeError, ValueError):
                return None
            _CURRENT_CACHE[symbol] = (oi, price_mid, now)
            return (oi, price_mid)
    return None


def _get_pct_changes(symbol: str) -> tuple[float, float] | None:
    """Retourne (pct_price_1h, pct_oi_1h) ou None si data insuffisante.

    Met à jour l'historique 1h en interne.
    """
    now = time.time()
    current = _get_current_snapshot(symbol)
    if current is None:
        return None
    oi_now, price_now = current

    # Mise à jour historique 1h
    hist = _HISTORY_1H.get(symbol)
    if hist is None:
        # Premier enregistrement : on stocke et on attend la prochaine fenêtre
        _HISTORY_1H[symbol] = (oi_now, price_now, now)
        return None
    oi_past, price_past, ts_past = hist
    age = now - ts_past
    if age > _HISTORY_MAX_AGE_SEC:
        # Snapshot trop vieux → recycler
        _HISTORY_1H[symbol] = (oi_now, price_now, now)
        return None
    if age < _HISTORY_MIN_AGE_SEC:
        # Pas encore assez vieux pour être représentatif d'1h
        return None

    if price_past <= 0 or oi_past <= 0:
        return None
    pct_price = (price_now - price_past) / price_past
    pct_oi = (oi_now - oi_past) / oi_past
    return (pct_price, pct_oi)


def apply_kraken_oi(
    pair: str,
    direction: str,
    base_score: float,
    price_change_pct_1h: float | None = None,
) -> tuple[float, dict]:
    """Applique le filtre OI divergence Kraken Futures.

    Parameters
    ----------
    pair:
        Paire interne (ex: ``"BTC/USD"``).
    direction:
        Direction du setup — ``"buy"`` ou ``"sell"``.
    base_score:
        Score de confiance courant avant application du filtre.
    price_change_pct_1h:
        Delta prix 1h optionnel fourni par l'appelant (ex: depuis klines
        Twelve Data).  Si fourni, utilisé à la place du delta interne Kraken.
        Permet de combiner source de prix externe avec OI Kraken natif.

    Returns
    -------
    (new_score, meta) où :
    - ``new_score`` : score après application du multiplicateur.
    - ``meta`` : dict avec clés ``multiplier``, ``reason`` (str | None),
      ``pct_price``, ``pct_oi``.

    Best-effort : retourne (base_score, {multiplier: 1.0, ...}) sur toute erreur.
    """
    _neutral = {"multiplier": 1.0, "reason": None, "pct_price": None, "pct_oi": None}
    if not is_crypto_pair(pair):
        return base_score, _neutral
    symbol = _PAIR_TO_SYMBOL.get(pair)
    if not symbol:
        return base_score, _neutral
    try:
        res = _get_pct_changes(symbol)
        if res is None:
            return base_score, _neutral
        pct_price_internal, pct_oi = res
        pct_price = price_change_pct_1h if price_change_pct_1h is not None else pct_price_internal

        if direction == "buy" and pct_price > _PRICE_THRESHOLD and pct_oi < _OI_DECLINE_THRESHOLD:
            reason = (
                f"short squeeze Kraken 1h : prix {pct_price * 100:+.2f}% "
                f"+ OI {pct_oi * 100:+.2f}% (mouvement épuisé, contrarien BUY)"
            )
            mult = _SOFT_VETO_MULTIPLIER
        elif direction == "sell" and pct_price < -_PRICE_THRESHOLD and pct_oi < _OI_DECLINE_THRESHOLD:
            reason = (
                f"liquidation longs Kraken 1h : prix {pct_price * 100:+.2f}% "
                f"+ OI {pct_oi * 100:+.2f}% (mouvement épuisé, contrarien SELL)"
            )
            mult = _SOFT_VETO_MULTIPLIER
        else:
            return base_score, {
                "multiplier": 1.0, "reason": None,
                "pct_price": pct_price, "pct_oi": pct_oi,
            }
        new_score = round(min(100.0, max(0.0, base_score * mult)), 1)
        return new_score, {
            "multiplier": mult, "reason": reason,
            "pct_price": pct_price, "pct_oi": pct_oi,
        }
    except Exception as e:
        logger.debug(f"kraken_oi_scoring {pair}: {e}")
        return base_score, _neutral
