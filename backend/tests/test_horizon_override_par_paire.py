"""Ouvrir des horizons pour UNE paire, sans toucher aux autres.

⛔ **Demande de Xavier le 2026-10-01** : « tous les horizons ouverts pour
l'or ». Le chemin par `.env` existait déjà — élargir
`MT5_BRIDGE_LIVE_ALLOWED_HORIZONS` — mais il est **par destination** : il
aurait ouvert 15 min et 30 min pour TOUTES les paires du compte réel, où la
liste blanche globale (`range_bounce_up/down`) les aurait laissées passer.

> **« Pour l'or » veut dire pour l'or.** Une demande de portée étroite
> exécutée largement n'est pas la demande.

⚠️ **Ce que ce mécanisme a de particulier, et qu'il faut dire.**
`_restreindre_horizons` est **restriction seule**, par construction : « déclarer
un horizon que la route ne sert pas ne l'ouvre PAS ». Cet override est le
premier dispositif de ce dépôt qui peut **ouvrir**. Il est donc nommé paire par
paire ET destination par destination — jamais un joker — et il tranche
lui-même, dans les deux sens : ce qu'il ne déclare pas reste refusé.

🔑 Décision prise CONTRE la mesure, et assumée comme telle : le laboratoire du
2026-10-01 rend 0 cellule retenue sur 232 pour l'or, R moyen négatif aux
quatre échelles. Cf. la déclaration dans `docs/concepts-trading.md`.
"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from backend.services import mt5_bridge as mb


def _dest(dest_id="admin_live", horizons=("5min", "4h")):
    return NS(destination_id=dest_id, allowed_horizons=frozenset(horizons))


def _setup(pair="XAU/USD", horizon="30min"):
    return NS(pair=pair, horizon=horizon)


@pytest.fixture
def or_tous_horizons(monkeypatch):
    """L'or ouvert à cinq échelles sur le réel, et rien d'autre de touché."""
    monkeypatch.setattr(
        mb, "MT5_BRIDGE_HORIZON_OVERRIDES",
        {"XAU/USD": {"admin_live": ["5min", "15min", "30min", "4h", "1d"]}},
        raising=False)


# --- Ce qui est demandé --------------------------------------------------

@pytest.mark.parametrize("h", ["5min", "15min", "30min", "4h", "1d"])
def test_l_or_passe_a_toutes_les_echelles_declarees(or_tous_horizons, h):
    """Alors que `allowed_horizons` de la route ne sert que 5min et 4h."""
    assert mb._horizon_rejection(_setup("XAU/USD", h), _dest()) is None


# --- Ce qui ne doit SURTOUT pas bouger -----------------------------------

def test_une_autre_paire_reste_refusee_au_meme_horizon(or_tous_horizons):
    """⛔ Le cœur de la portée : EUR/USD en 30 min reste fermé sur le réel.

    Sans cette assertion, la version `.env` du changement passerait — et elle
    ouvrait 15 min et 30 min pour tout le compte.
    """
    assert mb._horizon_rejection(_setup("EUR/USD", "30min"),
                                 _dest()) == "horizon_not_allowed"


def test_une_autre_destination_reste_refusee_sur_l_or(or_tous_horizons):
    """L'override nomme `admin_live` : la démo n'en hérite pas."""
    assert mb._horizon_rejection(
        _setup("XAU/USD", "30min"),
        _dest("admin_legacy")) == "horizon_not_allowed"


def test_un_horizon_NON_declare_reste_refuse_sur_l_or(or_tous_horizons):
    """Fail-closed À L'INTÉRIEUR de l'override : `1h` n'y est pas, donc non.

    ⚠️ Et `1h` n'est de toute façon pas PRODUIT aujourd'hui : les échelles
    agrégées valent 15 min et 30 min. Un override qui l'ouvrirait ne ferait
    rien — mais il mentirait sur ce qui est ouvert.
    """
    assert mb._horizon_rejection(_setup("XAU/USD", "1h"),
                                 _dest()) == "horizon_not_allowed"


def test_un_horizon_illisible_reste_refuse(or_tous_horizons):
    """Un setup sans horizon ne profite pas de l'ouverture."""
    assert mb._horizon_rejection(_setup("XAU/USD", None),
                                 _dest()) == "horizon_not_allowed"


# --- Sans override, rien ne change --------------------------------------

def test_sans_override_le_comportement_est_celui_d_avant(monkeypatch):
    monkeypatch.setattr(mb, "MT5_BRIDGE_HORIZON_OVERRIDES", {}, raising=False)
    assert mb._horizon_rejection(_setup("XAU/USD", "5min"), _dest()) is None
    assert mb._horizon_rejection(_setup("XAU/USD", "30min"),
                                 _dest()) == "horizon_not_allowed"


def test_une_destination_sans_filtre_reste_sans_filtre(monkeypatch):
    """`allowed_horizons` vide = aucun filtre, comportement d'avant 2026-08-05."""
    monkeypatch.setattr(mb, "MT5_BRIDGE_HORIZON_OVERRIDES", {}, raising=False)
    assert mb._horizon_rejection(_setup("XAU/USD", "30min"),
                                 _dest(horizons=())) is None
