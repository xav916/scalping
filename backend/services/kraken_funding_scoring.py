"""Funding rate Kraken Futures — filtre contrarien du scoring crypto.

Miroir de ``binance_funding_scoring.py`` mais consomme l'endpoint public
Kraken Futures au lieu de Binance USDⓈ-M.  Les taux de funding Kraken
peuvent diverger de Binance de 10-30% sur XBT/ETH en période de stress,
ce qui justifie un filtre natif pour les signaux routés vers ``admin_kraken``.

## Source de données

``GET https://futures.kraken.com/derivatives/api/v3/tickers``
Pas d'authentification requise.  Champ ``fundingRate`` par symbole ``PF_*``
(perpetual futures) — attention, ce champ est une valeur **absolue**, en
devise de cotation par contrat (ex: 0.253 USD sur PF_XBTUSD), **pas** un
taux relatif. On le divise par ``indexPrice`` (même ticker) pour obtenir
le taux relatif (fraction du notionnel) réellement comparable à un seuil.

Relevé réel du 2026-08-05 (confirme aussi la cadence — voir plus bas) :
- ``PF_XBTUSD``  fundingRate=0.25299581803314525  indexPrice=64013.79
  → taux relatif = 0.253 / 64013.79 ≈ 3.95e-6
- ``PF_ETHUSD``  fundingRate=0.03174136677858395  indexPrice=1862.71
  → taux relatif = 0.0317 / 1862.71 ≈ 1.70e-5

Cadence : Kraken règle le funding perpetual **toutes les heures** (pas
toutes les 8h comme Binance). Annualisés en horaire, les taux ci-dessus
donnent ≈3,5%/an (BTC) et ≈14,9%/an (ETH) — plausible pour des perpetuals.
En 8-horaire ils donneraient ≈0,43% et ≈1,87%/an — implausiblement bas.
La cadence horaire est donc confirmée par la mesure, cohérente avec
``funding_interval_hours=1.0`` déclaré ailleurs (cf. ``cost_model.py``).

## Logique

Identique au filtre Binance :
- Funding relatif > +0.05% (longs surcrowdés) + setup BUY  → soft veto ×0.85
- Funding relatif < -0.05% (shorts surcrowdés) + setup SELL → soft veto ×0.85
- Sinon : multiplier 1.0 (neutre)

⚠️ Chantier ouvert : ``0.05%`` par échéance horaire correspond à ~438%/an
(voir commentaire sur ``_DEFAULT_EXTREME_THRESHOLD`` ci-dessous) — un seuil
que le funding réel n'atteint quasiment jamais. Il n'a pas été recalibré
ici (décision produit hors périmètre de ce fix d'unité).

## Cache

Dict en mémoire avec TTL 30 min (les settlements Kraken sont horaires,
mais les taux bougent lentement hors chocs — 30 min reste un TTL
raisonnable pour amortir le coût réseau, indépendamment de la cadence de
règlement).

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

# Seuil funding rate "extrême", en taux RELATIF (fraction du notionnel) par
# échéance de règlement Kraken (horaire — cf. docstring d'en-tête pour la
# preuve de mesure du 2026-08-05).
#
# ⚠️ Chantier ouvert — seuil non recalibré : 0.0005 par échéance HORAIRE
# représente 0.05%/heure, soit environ 438%/an. Le funding relatif réel
# mesuré est de l'ordre de 1e-5 à 1e-6 (voir relevé du 2026-08-05 dans le
# docstring d'en-tête), donc ce seuil ne se déclenchera pour ainsi dire
# jamais — le veto passe de "se déclenche toujours" (bug d'unité, avant fix)
# à "ne se déclenche presque jamais" (après fix, seuil inchangé). Les deux
# extrêmes sont également inutiles comme discriminant. Le seuil doit être
# recalibré sur une mesure de la distribution réelle du funding relatif
# Kraken — ce n'est PAS fait ici, c'est une décision produit distincte.
_DEFAULT_EXTREME_THRESHOLD = 0.0005
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
    """Fetch le snapshot complet des tickers Kraken Futures et calcule le
    taux de funding RELATIF (fraction du notionnel) par symbole.

    Kraken expose ``fundingRate`` en valeur absolue (devise de cotation par
    contrat), pas en taux relatif — on le divise par ``indexPrice`` du même
    ticker pour obtenir une grandeur comparable à un seuil relatif (voir
    docstring d'en-tête pour la preuve de mesure du 2026-08-05).

    Retourne {symbol -> taux_relatif}. Un symbole est absent du dict si
    ``fundingRate`` ou ``indexPrice`` est manquant, non numérique, ou si
    ``indexPrice`` est nul/négatif (division impossible) — jamais mappé à
    0.0 ni à la valeur absolue en repli. Dict vide si l'endpoint est
    indisponible. Une seule requête HTTP pour tous les symboles (endpoint
    retourne tous les tickers en un seul payload JSON).
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
            raw_rate = t.get("fundingRate")
            raw_index = t.get("indexPrice")
            if not sym or raw_rate is None or raw_index is None:
                continue
            try:
                rate_abs = float(raw_rate)
                index_price = float(raw_index)
            except (TypeError, ValueError):
                continue
            if index_price <= 0:
                # indexPrice nul/négatif → taux relatif incalculable, on
                # n'insère PAS le symbole (jamais 0.0 ni la valeur absolue).
                continue
            rates[sym] = rate_abs / index_price
        _LAST_FETCH_AT = now
        _LAST_FETCH_DATA = rates
        return rates
    except Exception as e:
        logger.debug(f"kraken_funding: fetch tickers failed: {e}")
        return _LAST_FETCH_DATA  # retourner le cache périmé plutôt que vide


def _get_funding_rate(symbol: str) -> float | None:
    """Retourne le funding rate RELATIF Kraken pour un symbole PF_*, ou None."""
    rates = _fetch_all_rates()
    return rates.get(symbol)


def get_funding_rate_for_pair(pair: str) -> float | None:
    """Taux de funding RELATIF Kraken (fraction du notionnel) pour une paire
    interne (``"BTC/USD"``), ou ``None``.

    Accesseur public — le modèle de coût a besoin du taux comme **coût**,
    là où ce module l'utilisait jusqu'ici seulement comme feature de scoring.
    Best-effort : toute erreur rend ``None``, jamais ``0.0``.
    """
    try:
        symbol = _PAIR_TO_SYMBOL.get(pair)
        if not symbol:
            return None
        return _get_funding_rate(symbol)
    except Exception:
        return None


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
      ``symbol``, ``rate`` (float | None — taux RELATIF, fraction du
      notionnel, jamais la valeur absolue Kraken).

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
