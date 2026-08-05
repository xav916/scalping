"""Features macro/sentiment point-in-time, à partir des deux historiques
réels déjà présents dans le dépôt mais jusqu'ici non branchés :

- `macro_daily` (backend.services.macro_data) : VIX, dollar index, S&P,
  taux 10 ans US, bitcoin — daily, depuis 2024.
- `fear_greed_snapshots` (backend.services.fear_greed_service) : CNN Fear
  & Greed — daily, depuis mai 2026.

Contexte (audit du 2026-08-05) : la couche macro consultée par le scoring
depuis des mois (`macro_context_service.vix_value`) vaut 17.0 dans 100% des
lignes non nulles — c'est la valeur de repli codée en dur, la vraie
récupération n'a jamais abouti en production. Ce module ne touche pas à
`macro_context_service` ; il expose les deux historiques réels via une
interface différente, conçue pour ne jamais reproduire ce défaut :

Règle no look-ahead — deux décalages différents pour deux raisons différentes :

- `macro_daily` (Yahoo, clôture quotidienne) : la donnée du jour J n'est
  publiée qu'après la clôture de J. `macro_data.get_macro_features_at(ts)`
  applique donc un décalage conservateur d'un jour calendaire plein
  (asof = date(ts) - 1 jour), quelle que soit l'heure de `ts` dans la
  journée. Ce choix est déjà en place et déjà testé dans macro_data — on le
  réutilise tel quel, sans le modifier.
- `fear_greed_snapshots` (notre propre cron) : chaque ligne porte
  `recorded_at`, l'instant réel où la donnée a été insérée en base
  (append-only, jamais réécrite). `fear_greed_service.get_value_at(ts)`
  peut donc utiliser une borne stricte `recorded_at <= ts` sans marge de
  sécurité additionnelle : une ligne postérieure à `ts` n'existait
  simplement pas encore en base à cet instant, aucune fuite possible.

Règle valeur manquante : toute feature indisponible (avant le début de
l'historique, source injoignable, erreur SQL) vaut `None` — jamais 0.0 ni
une autre constante de repli. C'est exactement le défaut réparé ici.

Best-effort total : `get_features_at` ne lève jamais. Une source en panne
ne doit jamais casser le cycle radar.

Activation : derrière `MACRO_HISTORY_FEATURES_ENABLED` (config/settings.py),
désactivé par défaut — voir le commentaire du flag pour la justification et
ce qu'il faut vérifier avant de l'activer.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Encodage numérique de la classification CNN F&G (0 = peur max, 4 = avidité
# max). Une classification absente ou inconnue vaut None, jamais 0 (0 est
# une vraie catégorie ici : "extreme_fear").
_FEAR_GREED_CODE = {
    "extreme_fear": 0,
    "fear": 1,
    "neutral": 2,
    "greed": 3,
    "extreme_greed": 4,
}

_EMPTY_FEATURES: dict[str, Any] = {
    "mh_vix_level": None,
    "mh_vix_delta_1d": None,
    "mh_dxy_level": None,
    "mh_spx_level": None,
    "mh_tnx_level": None,
    "mh_btc_level": None,
    "mh_fear_greed_value": None,
    "mh_fear_greed_code": None,
}


def get_features_at(pair: str, ts: datetime) -> dict[str, Any]:
    """Features macro/sentiment connues à l'instant `ts`, sans look-ahead.

    `pair` n'est pas utilisé pour filtrer aujourd'hui (toutes les features
    sont cross-asset) — conservé pour la symétrie avec les autres blocs de
    `ml_features.extract_features_for_setup` et une éventuelle
    spécialisation future (ex. n'exposer `mh_btc_level` que pour les paires
    crypto).

    Retourne toujours les 8 clés ci-dessus ; chacune vaut None si la source
    correspondante n'a pas de donnée antérieure ou égale à `ts`.
    """
    out = dict(_EMPTY_FEATURES)

    try:
        from backend.services import macro_data
        feats = macro_data.get_macro_features_at(ts)
        out["mh_vix_level"] = feats.get("vix_level")
        out["mh_vix_delta_1d"] = feats.get("vix_delta_1d")
        out["mh_dxy_level"] = feats.get("dxy_level")
        out["mh_spx_level"] = feats.get("spx_level")
        out["mh_tnx_level"] = feats.get("tnx_level")
        out["mh_btc_level"] = feats.get("btc_level")
    except Exception as e:
        logger.debug(f"macro_history_features: macro_data indisponible: {e}")

    try:
        from backend.services import fear_greed_service
        snap = fear_greed_service.get_value_at(ts)
        if snap:
            out["mh_fear_greed_value"] = snap["value"]
            out["mh_fear_greed_code"] = _FEAR_GREED_CODE.get(snap["classification"])
    except Exception as e:
        logger.debug(f"macro_history_features: fear_greed_snapshots indisponible: {e}")

    return out
