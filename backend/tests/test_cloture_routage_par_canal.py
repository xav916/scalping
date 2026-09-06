"""Clôtures : chaque destination part sur SON fil Telegram (2026-08-19).

⛔ Corrigé le 06/09. Ce script portait sa PROPRE table de canaux :

    CANAL_PAR_DESTINATION = {"admin_live": "trades"}
    CANAL_DEFAUT = "sales"

Or `trades` désignait le bot nommé « KRAKEN Trades » et `sales` le bot
« IC MARKETS trades ». Les clôtures du compte réel IC Markets partaient donc
chez Kraken, et celles de Kraken chez IC Markets — exactement inversé. C'est
le message vu dans le fil Kraken : « Position fermée — compte réel 13137475 ».

🔑 Une deuxième table est une table qui dérive. Le canal vient désormais de
`canaux_telegram.canal_pour()`, le seul module qui le sache.

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


def test_cloture_du_reel_part_sur_le_fil_IC_MARKETS(script, monkeypatch):
    envois: list = []
    code = _lancer(script, monkeypatch,
                   {"admin_live": [{"ticket": 1}]}, envois)
    assert code == 0
    assert len(envois) == 1
    assert envois[0]["canal"] == "ic_markets"
    assert envois[0]["cles"] == ["admin_live:1"]


def test_cloture_kraken_part_sur_le_fil_KRAKEN(script, monkeypatch):
    envois: list = []
    _lancer(script, monkeypatch, {"admin_kraken": [{"ticket": 9}]}, envois)
    assert len(envois) == 1
    assert envois[0]["canal"] == "kraken"


def test_deux_destinations_font_DEUX_envois_distincts(script, monkeypatch):
    """Grouper enverrait du Kraken sur le fil du compte réel."""
    envois: list = []
    _lancer(script, monkeypatch,
            {"admin_live": [{"ticket": 1}], "admin_kraken": [{"ticket": 9}]},
            envois)
    par_canal = {e["canal"]: e for e in envois}
    assert set(par_canal) == {"ic_markets", "kraken"}
    assert par_canal["ic_markets"]["cles"] == ["admin_live:1"]
    assert par_canal["kraken"]["cles"] == ["admin_kraken:9"]


def test_echec_d_un_fil_n_empeche_PAS_l_autre(script, monkeypatch):
    """Le piège du court-circuit : `all(generateur)` sauterait le second."""
    envois: list = []
    code = _lancer(script, monkeypatch,
                   {"admin_live": [{"ticket": 1}], "admin_kraken": [{"ticket": 9}]},
                   envois, echecs=("kraken",))
    assert {e["canal"] for e in envois} == {"ic_markets", "kraken"}
    # Un envoi manqué ⇒ l'instantané ne doit pas avancer.
    assert code == 1


def test_aucune_cloture_n_envoie_rien(script, monkeypatch):
    envois: list = []
    assert _lancer(script, monkeypatch, {}, envois) == 0
    assert envois == []


# ── Le titre nomme le COMPTE (2026-09-06) ─────────────────────────────────
#
# ⛔ Il testait `canal == "trades"` et codait le login 13137475 en dur. Une
# fois « trades » disparu, TOUS les messages seraient devenus « Position
# fermee » tout court — le compte s'effaçait du titre au moment même où on
# séparait les fils.

def test_le_titre_ne_code_plus_le_login_en_dur():
    """⛔ « 13137475 » dans un titre est un compte qu'on ne peut plus renommer,
    et qui ment des qu'un autre compte emprunte le meme fil."""
    source = _SCRIPT.read_text(encoding="utf-8")
    assert "compte reel 13137475" not in source


def test_le_titre_vient_du_LIBELLE_du_compte():
    """Une seule facon de nommer un compte — ici comme en session."""
    source = _SCRIPT.read_text(encoding="utf-8")
    assert "titre = f\"{libelle(canal)}" in source
    from backend.services.canaux_telegram import libelle
    assert libelle("ic_markets") == "[RÉEL · IC_MARKETS]"
