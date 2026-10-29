"""Le transport de la charge vers le conteneur.

Mesure du 2026-10-29 : la 2e charge de `collecter` est MULTI-LIGNES (13 sauts
de ligne reels, a cause de son `def h(url):` et de ses blocs `try`). Passee en
argument de `python3 -c` apres `json.dumps`, elle arrive sur UNE seule ligne
avec des `\\n` litteraux : bash ne les interprete pas entre guillemets doubles,
et Python lit le backslash comme une continuation de ligne.

    SyntaxError: unexpected character after line continuation character

La 1re charge survit UNIQUEMENT parce qu'elle n'a aucun saut de ligne (tout y
est enchaine par des `;`). Le correctif est celui deja eprouve dans `or-porte` :
transmettre par STDIN, verifie jusqu'a 50 Ko.
"""
import pathlib
import sys
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import etat  # noqa: E402

MULTILIGNE = (
    "import json\n"
    "def f():\n"
    "    return 1\n"
    "print(json.dumps({'a':f()}))"
)


class _FauxRun:
    """Capture l'appel subprocess sans rien executer."""

    def __init__(self, stdout='{"a": 1}'):
        self.argv = None
        self.kwargs = None
        self._stdout = stdout

    def __call__(self, argv, **kw):
        self.argv = argv
        self.kwargs = kw
        return types.SimpleNamespace(
            stdout=self._stdout, stderr="", returncode=0)


def test_la_charge_passe_par_STDIN_et_non_par_la_ligne_de_commande(monkeypatch):
    faux = _FauxRun()
    monkeypatch.setattr(etat.subprocess, "run", faux)
    etat._executer_a_distance(pathlib.Path("."), MULTILIGNE)
    commande = " ".join(faux.argv)
    assert "python3 -c" not in commande, \
        "la charge ne doit PAS etre un argument de ligne de commande"
    assert "python3 -" in commande, "la charge doit etre lue sur stdin"
    assert "docker exec -i" in commande, \
        "-i est requis pour relayer le stdin dans le conteneur"
    assert "-n" not in faux.argv, \
        "-n fermerait le stdin dont on se sert maintenant"
    assert faux.kwargs.get("input") == MULTILIGNE


def test_aucun_fragment_de_la_charge_n_est_embarque_dans_la_commande(monkeypatch):
    """Le defaut se reconnait a ceci : du code dans l'argv."""
    faux = _FauxRun()
    monkeypatch.setattr(etat.subprocess, "run", faux)
    etat._executer_a_distance(pathlib.Path("."), MULTILIGNE)
    for morceau in faux.argv:
        assert "def f()" not in morceau
        assert "\\n" not in morceau


def test_une_sortie_illisible_LEVE_au_lieu_de_rendre_None(monkeypatch):
    """Fail-closed : un silence de la production ne doit pas devenir un trou
    dans le dict rendu — c'est ce qui avait rendu le defaut invisible."""
    faux = _FauxRun(stdout="pas du json")
    monkeypatch.setattr(etat.subprocess, "run", faux)
    try:
        etat._executer_a_distance(pathlib.Path("."), MULTILIGNE)
    except RuntimeError:
        return
    raise AssertionError("une sortie illisible doit lever, pas se taire")
