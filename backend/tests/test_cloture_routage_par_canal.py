"""Clôtures : chaque destination part sur SON fil Telegram (2026-08-19).

Le fil `trades` suit le compte réel 13137475 de bout en bout — son ouverture y
est annoncée par `notify-miroir-demo-reel.sh`, sa clôture l'y rejoint. Les
autres destinations restent sur `sales`.

Deux propriétés valent d'être verrouillées, parce que leur violation serait
silencieuse :

1. le routage se fait **par message**. Grouper une clôture réelle et une
   clôture Kraken enverrait du Kraken sur un fil censé ne porter que le
   compte réel ;
2. l'échec d'un fil **n'empêche pas** l'envoi de l'autre. Un `all()` sur un
   générateur court-circuiterait — la clôture Kraken serait perdue parce que
   la réelle a échoué.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

_SCRIPT = (pathlib.Path(__file__).resolve().parents[2]
           / "scripts" / "notify_position_fermee.py")


@pytest.fixture()
def script(tmp_path, monkeypatch):
    monkeypatch.setenv("POSITIONS_SNAPSHOT_PATH", str(tmp_path / "snap.json"))
    spec = importlib.util.spec_from_file_location("cloture_route", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _lancer(script, monkeypatch, par_dest, envois, echecs=()):
    """Exécute main() sans réseau ni courtier.

    `clotures` ne reçoit pas l'identifiant de destination : on le reconstitue
    en suivant l'ordre de `DESTINATIONS_SURVEILLEES`, que la boucle parcourt.
    """
    ordre = list(script.DESTINATIONS_SURVEILLEES)
    appels = {"i": 0}

    monkeypatch.setattr(script, "releve", lambda dest: ({}, True))
    monkeypatch.setattr(script, "enrichir", lambda dest, pos: {})
    monkeypatch.setattr(
        script, "decrire", lambda dest, pos, sortie: f"ligne {pos['ticket']}")

    def _clotures(bt, avant, courant, ok):
        did = ordre[appels["i"]]
        appels["i"] += 1
        return par_dest.get(did, [])

    monkeypatch.setattr(script, "clotures", _clotures)

    def _faux_notifier(corps, cles, canal=script.CANAL_DEFAUT):
        envois.append({"canal": canal, "corps": corps, "cles": list(cles)})
        return canal not in echecs

    monkeypatch.setattr(script, "notifier", _faux_notifier)
    return script.main()


def test_cloture_du_reel_part_sur_trades(script, monkeypatch):
    envois: list = []
    code = _lancer(script, monkeypatch,
                   {"admin_live": [{"ticket": 1}]}, envois)
    assert code == 0
    assert len(envois) == 1
    assert envois[0]["canal"] == "trades"
    assert envois[0]["cles"] == ["admin_live:1"]


def test_cloture_kraken_reste_sur_sales(script, monkeypatch):
    envois: list = []
    _lancer(script, monkeypatch, {"admin_kraken": [{"ticket": 9}]}, envois)
    assert len(envois) == 1
    assert envois[0]["canal"] == "sales"


def test_deux_destinations_font_DEUX_envois_distincts(script, monkeypatch):
    """Grouper enverrait du Kraken sur le fil du compte réel."""
    envois: list = []
    _lancer(script, monkeypatch,
            {"admin_live": [{"ticket": 1}], "admin_kraken": [{"ticket": 9}]},
            envois)
    par_canal = {e["canal"]: e for e in envois}
    assert set(par_canal) == {"trades", "sales"}
    assert par_canal["trades"]["cles"] == ["admin_live:1"]
    assert par_canal["sales"]["cles"] == ["admin_kraken:9"]


def test_echec_d_un_fil_n_empeche_PAS_l_autre(script, monkeypatch):
    """Le piège du court-circuit : `all(generateur)` sauterait le second."""
    envois: list = []
    code = _lancer(script, monkeypatch,
                   {"admin_live": [{"ticket": 1}], "admin_kraken": [{"ticket": 9}]},
                   envois, echecs=("sales",))
    assert {e["canal"] for e in envois} == {"trades", "sales"}
    # Un envoi manqué ⇒ l'instantané ne doit pas avancer.
    assert code == 1


def test_aucune_cloture_n_envoie_rien(script, monkeypatch):
    envois: list = []
    assert _lancer(script, monkeypatch, {}, envois) == 0
    assert envois == []
