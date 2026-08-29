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
- Funding relatif > seuil extrême (longs surcrowdés) + setup BUY  → soft veto ×0.85
- Funding relatif < -seuil extrême (shorts surcrowdés) + setup SELL → soft veto ×0.85
- Sinon : multiplier 1.0 (neutre)

## Seuil "extrême" — recalibré le 2026-08-05

``_DEFAULT_EXTREME_THRESHOLD`` valait ``0.0005`` (0.05%/heure, ~438%/an) —
un artefact du bug d'unité ci-dessus : quand ``fundingRate`` était pris tel
quel (valeur absolue), ce seuil se déclenchait quasi toujours ; une fois le
taux converti en relatif, il ne se déclenche quasi plus jamais (le funding
relatif réel est de l'ordre de 1e-5 à 1e-6). Il a été recalibré sur une
mesure de la distribution réelle du funding relatif Kraken — voir le
commentaire détaillé au-dessus de ``_DEFAULT_EXTREME_THRESHOLD`` ci-dessous
pour la méthode, les percentiles mesurés et la justification du choix
(``2.0e-5``, le p95 convergent des deux paires tradées).

⚠️ Cette recalibration règle la FRÉQUENCE de déclenchement du veto, pas sa
VALEUR : aucune mesure ne démontre qu'un funding extrême prédit un moins
bon résultat de trade. Cette question reste hors de portée tant que le
taux de funding au moment du signal n'est pas persisté (voir le même
commentaire pour le chantier de validation, distinct et non fait ici).

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
# Recalibré le 2026-08-05 sur une mesure de la distribution réelle du
# funding relatif Kraken Futures. Source : endpoint public historique
# ``GET https://futures.kraken.com/derivatives/api/v4/historicalfundingrates
# ?symbol=<SYM>``, champ ``relativeFundingRate`` (déjà relatif, contrairement
# au ``fundingRate`` absolu de l'endpoint ``tickers`` utilisé plus bas dans
# ce module). Échantillon : 8968 observations horaires par paire, ~374
# jours (2025-07-27 → 2026-08-05), sur les deux seules paires tradées :
#
#                       PF_XBTUSD      PF_ETHUSD
#   part négative         27,2 %         31,1 %
#   |taux| médiane      6,107e-06      5,867e-06
#   |taux| p75          1,047e-05      1,030e-05
#   |taux| p90          1,515e-05      1,564e-05
#   |taux| p95          1,879e-05      1,989e-05
#   |taux| p99          2,769e-05      3,159e-05
#   |taux| p99,9        3,643e-05      7,104e-05
#   |taux| maximum      1,773e-04      5,485e-04
#
# Constat qui motive la recalibration : l'ancien seuil (0.0005) est
# AU-DESSUS du maximum observé sur BTC en un an. Rejoué sur l'historique,
# il ne se serait déclenché 0 fois sur 8968 heures pour BTC, et 1 seule
# fois pour ETH — un no-op mesuré, pas supposé.
#
# Seuil retenu : 2.0e-5 — le p95 des deux paires, qui tombent au même
# endroit (1,879e-05 et 1,989e-05). C'est cette convergence entre deux
# actifs différents qui rend la valeur crédible comme seuil plutôt
# qu'ajustée sur une seule série. Avec ce seuil, le veto se déclenche sur
# environ 5% des heures, majoritairement côté achat (BUY) puisque ~72%
# des heures ont un funding positif (27,2%/31,1% de funding négatif
# mesuré ci-dessus).
#
# ⚠️ Ce que cette mesure NE valide PAS : elle règle la FRÉQUENCE de
# déclenchement du veto, pas sa VALEUR. Rien ne démontre qu'un funding
# extrême prédit un moins bon résultat de trade — et on ne peut
# aujourd'hui pas le mesurer, car le taux de funding au moment du signal
# n'est persisté nulle part (ni dans `signals`, ni dans les features
# shadow). Le veto reste donc une hypothèse non validée, désormais dosée
# sur une fréquence plausible plutôt que sur un seuil inatteignable — une
# mesure de fréquence n'est pas une validation de pertinence. Prochaine
# étape pour trancher (chantier distinct, PAS fait ici) : persister le
# taux relatif au moment du signal (ex: dans les features shadow), pour
# pouvoir comparer a posteriori les résultats de trade avec/sans funding
# extrême.
_DEFAULT_EXTREME_THRESHOLD = 2.0e-5
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


# ⛔ Bases qui ne sont JAMAIS de la crypto, nommees une par une.
#
# Kraken Futures cote aussi des perpetuels de DEVISES : `PF_EURUSD` existe.
# La derivation `PF_{base}USD` validee contre le catalogue rendait donc un
# symbole pour `EUR/USD`, et `is_crypto_pair("EUR/USD")` valait **True** —
# le veto de funding et le cout de portage crypto s'appliquaient a du forex.
#
# ⚠️ On ne filtre PAS par `asset_class_for(pair) == "crypto"` : cette fonction
# retombe sur `forex` par defaut, et classe donc AVAX, LINK, PEPE, SUI, TIA...
# en forex. S'en servir ici re-couperait 14 des 23 cryptos de l'univers Kraken
# — exactement le defaut du 2026-08-23. On nomme donc ce qui est EXCLU, et
# l'inconnu reste derivable.
_BASES_NON_CRYPTO = frozenset({
    "EUR", "USD", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD",
    "SEK", "NOK", "DKK", "PLN", "HUF", "CZK", "TRY", "ZAR",
    "MXN", "SGD", "HKD", "CNH", "ILS", "RUB",
})
# Les classes que `asset_class_for` reconnait de facon FIABLE (par prefixe ou
# liste explicite), contrairement a `forex` qui est son repli.
# ⚠️ `metal` RETIRE le 2026-08-29, quand l'or et l'argent ont ete ouverts sur
# Kraken. La vraie question de cette fonction n'a jamais ete « est-ce de la
# crypto ? » mais « Kraken cote-t-il un perpetuel pour cette paire ? ». Tant
# que les metaux n'y etaient pas tradables, les deux se confondaient.
#
# Un perpetuel metal a un VRAI funding, et le refuser ici rendrait le cout de
# portage incalculable — ce qui BLOQUE l'argent reel par la porte de cout.
# Exclure ce qui ne sera jamais route vers Kraken suffit : les devises.
_CLASSES_NON_CRYPTO = frozenset({"energy", "equity_index", "equity"})


def _peut_etre_crypto(pair: str) -> bool:
    """Cette paire peut-elle etre un perpetuel CRYPTO ? Fail-open sur l'inconnu.

    Rend `False` pour ce qu'on sait ne pas etre de la crypto (devises, metaux,
    energie, indices, actions) et `True` pour tout le reste — un altcoin qu'on
    ne connait pas encore doit rester derivable, sinon l'univers Kraken se
    recoupe tout seul a chaque nouvelle cotation.
    """
    base = pair.split("/", 1)[0].upper()
    if base in _BASES_NON_CRYPTO:
        return False
    try:
        from config.settings import asset_class_for
        return asset_class_for(pair) not in _CLASSES_NON_CRYPTO
    except Exception:  # noqa: BLE001 — la classe est un garde-fou secondaire
        return True


def symbole_pour(pair: str) -> str | None:
    """Symbole Kraken Futures d'une paire interne, ou ``None``.

    **Point de resolution unique** — le cout de portage et le veto de score
    doivent couvrir le meme univers. Le 2026-08-08, le repli derive n'avait ete
    pose que sur `get_funding_rate_for_pair` (le cout) ; `apply_kraken_funding`
    (le score) sortait toujours en amont sur l'appartenance a la carte codee en
    dur. Mesure le 2026-08-09 : 9 paires couvertes sur 24 surveillees, et le
    veto ne s'etait jamais declenche que sur les six de la carte.

    Deux univers pour une meme donnee, c'est la derive que cette fonction
    supprime.

    La derivation n'est acceptee QUE si Kraken publie reellement le symbole :
    une derivation non validee rendrait le taux d'une autre paire, ou
    masquerait une absence.
    """
    explicite = _PAIR_TO_SYMBOL.get(pair)
    if explicite:
        return explicite
    if "/" not in pair:
        return None
    base, quote = pair.split("/", 1)
    if quote.upper() != "USD":
        return None
    # ⛔ AVANT d'interroger Kraken : son catalogue contient des perpetuels de
    # DEVISES. Sans ce garde, `EUR/USD` rendait `PF_EURUSD` et passait pour
    # de la crypto — veto de funding et cout de portage crypto sur du forex.
    if not _peut_etre_crypto(pair):
        return None
    derive = f"PF_{base.upper()}USD"
    return derive if derive in _fetch_all_rates() else None


def is_crypto_pair(pair: str) -> bool:
    """Retourne True si Kraken Futures cote un perpetuel pour cette paire."""
    return symbole_pour(pair) is not None


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
        # Repli derive (2026-08-08), factorise dans `symbole_pour` (2026-08-09).
        # `_fetch_all_rates` recupere DEJA tous les taux publies par Kraken ;
        # seule la traduction paire->symbole manquait, et elle rendait `None`
        # pour toute paire absente de la carte codee en dur. Consequence
        # mesuree : BNB, XLM, SEI, ENS et HBAR voyaient leur cout de portage
        # devenir incalculable, donc `exceeds_edge` bloquait l'argent reel --
        # un refus fonde sur une donnee manquante, pas sur un cout.
        symbol = symbole_pour(pair)
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
    # ⚠️ Meme resolution que le cout de portage, cf. `symbole_pour`. Passer par
    # `_PAIR_TO_SYMBOL` directement rouvrirait l'ecart des deux univers.
    try:
        symbol = symbole_pour(pair)
    except Exception as e:
        logger.debug(f"kraken_funding_scoring {pair}: {e}")
        symbol = None
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
