"""Kraken : savoir si une position porte encore son stop (2026-08-19).

Une entrée Kraken envoie **trois ordres indépendants** — marché, stop,
objectif. Le stop peut échouer à la pose sans que l'entrée échoue, et
`/positions` ne dit rien des ordres : une position pouvait donc courir des
jours sans protection, en silence. C'est le scénario de l'incident de position
nue du 2026-08-05, resté invisible depuis.

Ce qui est verrouillé ici : un ordre ne compte comme protection que s'il
RÉDUIT la position. Sans ce filtre, un ordre d'entrée en attente sur le même
symbole ferait passer une position nue pour protégée — la validation muette
qui rend le défaut indétectable.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

_BRIDGE = (pathlib.Path(__file__).resolve().parents[2]
           / "kraken-futures-bridge" / "bridge.py")


@pytest.fixture(scope="module")
def bridge():
    spec = importlib.util.spec_from_file_location("kraken_futures_bridge", _BRIDGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ordre(**kw):
    base = {"symbol": "PF_SOLUSD", "orderType": "stp", "reduceOnly": True}
    base.update(kw)
    return base


def test_un_stop_reduceonly_protege(bridge):
    etat = bridge._protection_par_symbole([_ordre()])
    assert etat["PF_SOLUSD"]["stop"] is True
    assert etat["PF_SOLUSD"]["objectif"] is False


def test_un_objectif_ne_vaut_PAS_un_stop(bridge):
    """C'est le stop qui borne la perte. Un TP seul laisse la position nue."""
    etat = bridge._protection_par_symbole([_ordre(orderType="take_profit")])
    assert etat["PF_SOLUSD"]["stop"] is False
    assert etat["PF_SOLUSD"]["objectif"] is True


def test_ordre_non_reduceonly_ignore(bridge):
    """Un ordre d'ENTRÉE en attente n'est pas une protection.

    Sans ce filtre, une position nue serait annoncée protégée — exactement le
    faux négatif que cette sonde existe pour empêcher.
    """
    etat = bridge._protection_par_symbole([_ordre(reduceOnly=False)])
    assert etat == {}


def test_stop_et_objectif_ensemble(bridge):
    etat = bridge._protection_par_symbole([
        _ordre(orderType="stp"),
        _ordre(orderType="take_profit"),
    ])
    assert etat["PF_SOLUSD"] == {"stop": True, "objectif": True}


def test_symboles_independants(bridge):
    """Un stop sur SOL ne protège pas LDO."""
    etat = bridge._protection_par_symbole([
        _ordre(symbol="PF_SOLUSD", orderType="stp"),
        _ordre(symbol="PF_LDOUSD", orderType="take_profit"),
    ])
    assert etat["PF_SOLUSD"]["stop"] is True
    assert etat["PF_LDOUSD"]["stop"] is False


def test_aucun_ordre(bridge):
    assert bridge._protection_par_symbole([]) == {}


@pytest.mark.parametrize("bancal", [
    {"orderType": "stp", "reduceOnly": True},              # pas de symbole
    {"symbol": "PF_SOLUSD", "reduceOnly": True},           # pas de type
    {"symbol": None, "orderType": "stp", "reduceOnly": True},
])
def test_ordres_bancals_ne_cassent_rien(bridge, bancal):
    """Un ordre incomplet ne doit ni lever, ni inventer une protection."""
    etat = bridge._protection_par_symbole([bancal])
    assert etat.get("PF_SOLUSD", {}).get("stop", False) is False


def test_type_inconnu_n_est_pas_un_stop(bridge):
    """Un ordre limite reduceOnly n'est pas un stop : il ne se déclenche pas."""
    etat = bridge._protection_par_symbole([_ordre(orderType="lmt")])
    assert etat["PF_SOLUSD"] == {"stop": False, "objectif": False}
