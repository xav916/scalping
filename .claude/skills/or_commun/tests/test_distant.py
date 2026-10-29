"""Le transport vers le conteneur, et l'analyse de ce qu'il rend.

Mesure du 2026-10-29 : une charge MULTI-LIGNES passee en argument de
`python3 -c` apres `json.dumps` arrive sur UNE seule ligne avec des `\\n`
litteraux. Bash ne les interprete pas entre guillemets doubles, et Python lit
le backslash comme une continuation de ligne :

    SyntaxError: unexpected character after line continuation character

Le defaut a persiste dans `or-etat` PARCE QUE le correctif d'`or-porte`
n'etait pas partage : deux copies, une seule reparee. D'ou ce module.
"""
import pathlib
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from or_commun import distant  # noqa: E402

MULTILIGNE = (
    "import json\n"
    "def f():\n"
    "    return 1\n"
    "print(json.dumps({'a':f()}))"
)


class _FauxRun:
    def __init__(self, stdout="", stderr=""):
        self.argv = None
        self.kwargs = None
        self._out = types.SimpleNamespace(
            stdout=stdout, stderr=stderr, returncode=0)

    def __call__(self, argv, **kw):
        self.argv, self.kwargs = argv, kw
        return self._out


def test_la_charge_passe_par_STDIN_et_non_par_la_ligne_de_commande(monkeypatch):
    faux = _FauxRun()
    monkeypatch.setattr(distant.subprocess, "run", faux)
    distant.executer(pathlib.Path("."), MULTILIGNE)
    commande = " ".join(faux.argv)
    assert "python3 -c" not in commande
    assert "python3 -" in commande
    assert "docker exec -i" in commande, "-i relaie le stdin dans le conteneur"
    assert "-n" not in faux.argv, "-n fermerait le stdin qu'on utilise"
    assert faux.kwargs.get("input") == MULTILIGNE


def test_aucun_fragment_de_la_charge_dans_la_commande(monkeypatch):
    faux = _FauxRun()
    monkeypatch.setattr(distant.subprocess, "run", faux)
    distant.executer(pathlib.Path("."), MULTILIGNE)
    for morceau in faux.argv:
        assert "def f()" not in morceau
        assert "\\n" not in morceau


def test_le_timeout_par_defaut_est_120(monkeypatch):
    """Unifie sur le PLUS GRAND des deux : un delai plus court sur la charge
    la plus grosse (12 Ko du vivier) serait le mauvais defaut."""
    faux = _FauxRun()
    monkeypatch.setattr(distant.subprocess, "run", faux)
    distant.executer(pathlib.Path("."), "print(1)")
    assert faux.kwargs.get("timeout") == 120


def test_la_DERNIERE_ligne_json_est_prise():
    """La banniere ssh ecrit sur stdout a chaque appel."""
    sortie = types.SimpleNamespace(
        stdout='** banniere ssh\n{"a": 1}\n{"a": 2}\n', stderr="", returncode=0)
    assert distant.derniere_ligne_json(sortie) == {"a": 2}


def test_un_tableau_est_lisible_avec_son_prefixe():
    sortie = types.SimpleNamespace(
        stdout='** banniere\n[{"pair": "XAU/USD"}]\n', stderr="", returncode=0)
    assert distant.derniere_ligne_json(sortie, prefixe="[") == [
        {"pair": "XAU/USD"}]


def test_une_sortie_illisible_LEVE_au_lieu_de_rendre_None():
    sortie = types.SimpleNamespace(
        stdout="pas du json", stderr="erreur distante", returncode=1)
    with pytest.raises(RuntimeError, match="erreur distante"):
        distant.derniere_ligne_json(sortie)


def test_le_message_d_erreur_porte_stderr_quand_il_existe():
    sortie = types.SimpleNamespace(
        stdout="", stderr="SyntaxError: quelque chose", returncode=1)
    with pytest.raises(RuntimeError, match="SyntaxError"):
        distant.derniere_ligne_json(sortie)
