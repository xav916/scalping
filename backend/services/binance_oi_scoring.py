"""Open Interest divergence Binance — filtre fake breakout / liquidation.

Phase 2 Palier 2 — chantier #6 (2026-06-18) : compare l'évolution de
l'Open Interest (somme positions ouvertes) avec l'évolution du prix
sur la dernière heure pour détecter les mouvements épuisés.

## Patterns détectés

| Prix | OI | Interprétation | Setup pénalisé |
|---|---|---|---|
| Up | Up | Vraie tendance haussière (nouveaux longs entrent) | aucun |
| Up | **Down** | Short squeeze (shorts couvrent, pas de vrais longs) | **BUY** |
| Down | Up | Vraie tendance baissière (nouveaux shorts entrent) | aucun |
| Down | **Down** | Liquidation longs (longs ferment, pas de vrais shorts) | **SELL** |

Quand le mouvement est porté par des fermetures de positions (OI baisse)
plutôt que par de nouveaux entrants (OI monte), la dynamique est
**épuisable** — le retour à la moyenne est probable.

## Seuils

- Mouvement prix significatif : ±0.5% sur 1h
- OI déclin significatif : −2% sur 1h
- Si les 2 conditions remplies dans le sens "squeeze" → soft veto ×0.85

## Architecture

- Endpoint `/futures/data/openInterestHist?period=5m&limit=12` → 12 points
  sur la dernière heure
- Combiné avec klines 5m pour delta prix sur la même fenêtre
- Sync urllib + cache 60s (OI change lentement)

Feature flag : ``BINANCE_OI_SCORING_ENABLED=true``.
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

_PRICE_THRESHOLD = float(os.getenv("BINANCE_OI_PRICE_THRESHOLD", "0.005"))   # 0.5%
_OI_DECLINE_THRESHOLD = float(os.getenv("BINANCE_OI_DECLINE_THRESHOLD", "-0.02"))  # -2%
_SOFT_VETO_MULTIPLIER = 0.85

# Cache : {symbol -> (pct_price, pct_oi, fetched_at)}. TTL 60s.
_CACHE: dict[str, tuple[float, float, float]] = {}
_CACHE_TTL_SEC = 60.0


def is_crypto_pair(pair: str) -> bool:
    return pair in _PAIR_TO_SYMBOL


def _fetch_pct(symbol: str) -> tuple[float, float] | None:
    """Retourne (pct_price_1h, pct_oi_1h) ou None si data indispo."""
    now = time.time()
    cached = _CACHE.get(symbol)
    if cached is not None and (now - cached[2]) < _CACHE_TTL_SEC:
        return (cached[0], cached[1])
    try:
        # OI history (12 points 5m = 1h)
        req = urllib.request.Request(
            f"{_PUBLIC_BASE}/futures/data/openInterestHist"
            f"?symbol={symbol}&period=5m&limit=12",
            headers={"User-Agent": "scalping-radar/1.0"},
        )
        with urllib.request.urlopen(req, timeout=4) as r:
            oi_hist = json.loads(r.read())
        if len(oi_hist) < 2:
            return None
        oi_past = float(oi_hist[0]["sumOpenInterest"])
        oi_now = float(oi_hist[-1]["sumOpenInterest"])
        if oi_past <= 0:
            return None
        pct_oi = (oi_now - oi_past) / oi_past

        # Klines 5m × 12 = 1h
        req = urllib.request.Request(
            f"{_PUBLIC_BASE}/fapi/v1/klines?symbol={symbol}&interval=5m&limit=12",
            headers={"User-Agent": "scalping-radar/1.0"},
        )
        with urllib.request.urlopen(req, timeout=4) as r:
            klines = json.loads(r.read())
        if len(klines) < 2:
            return None
        price_past = float(klines[0][1])   # open de la 1ère bougie
        price_now = float(klines[-1][4])    # close de la dernière
        if price_past <= 0:
            return None
        pct_price = (price_now - price_past) / price_past

        _CACHE[symbol] = (pct_price, pct_oi, now)
        return (pct_price, pct_oi)
    except Exception as e:
        logger.debug(f"oi_scoring fetch {symbol}: {e}")
        return None


def apply_oi_filter(pair: str, direction: str) -> tuple[float, str | None]:
    """Retourne (multiplier, reason).

    multiplier : 1.0 (neutre) ou 0.85 (soft veto squeeze / liquidation).
    Best-effort : (1.0, None) silencieux sur toute erreur.
    """
    if not is_crypto_pair(pair):
        return 1.0, None
    sym = _PAIR_TO_SYMBOL.get(pair)
    if not sym:
        return 1.0, None
    res = _fetch_pct(sym)
    if res is None:
        return 1.0, None
    pct_price, pct_oi = res
    if direction == "buy" and pct_price > _PRICE_THRESHOLD and pct_oi < _OI_DECLINE_THRESHOLD:
        return (_SOFT_VETO_MULTIPLIER,
                f"short squeeze 1h : prix {pct_price*100:+.2f}% + OI {pct_oi*100:+.2f}% "
                f"(mouvement épuisé, contrarien BUY)")
    if direction == "sell" and pct_price < -_PRICE_THRESHOLD and pct_oi < _OI_DECLINE_THRESHOLD:
        return (_SOFT_VETO_MULTIPLIER,
                f"liquidation longs 1h : prix {pct_price*100:+.2f}% + OI {pct_oi*100:+.2f}% "
                f"(mouvement épuisé, contrarien SELL)")
    return 1.0, None
