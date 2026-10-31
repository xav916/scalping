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


# ─── La CIBLE est reglable, et sa construction est testable (2026-10-31) ──
#
# L'adresse a DEJA change une fois, et un repli perime ecrit en dur dans
# `deploy-v2.sh` a coute une demi-heure le 2026-09-15 : « une adresse de
# secours fausse coute exactement au moment ou on en a besoin ».

def _recharge(monkeypatch, **env):
    """Recharge le module avec un environnement donne. Les constantes sont
    lues a l'IMPORT, donc un simple setenv ne suffirait pas."""
    import importlib
    for k in ("OR_HOTE", "OR_CONTENEUR", "OR_CLE_SSH"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return importlib.reload(distant)


def test_les_defauts_sont_ceux_de_la_production(monkeypatch):
    """⛔ Le defaut NE DOIT PAS changer : c'est l'IP publique, pas Tailscale
    (injoignable depuis le bac a sable)."""
    d = _recharge(monkeypatch)
    assert d.HOTE == "ec2-user@13.63.77.180"
    assert d.CONTENEUR == "scalping-radar"
    assert d.CLE == "scalping-key.pem"
    assert "100." not in d.HOTE, "l'adresse Tailscale est injoignable d'ici"


def test_l_hote_et_le_conteneur_se_surchargent(monkeypatch):
    d = _recharge(monkeypatch, OR_HOTE="moi@10.0.0.1",
                  OR_CONTENEUR="autre", OR_CLE_SSH="k.pem")
    assert d.HOTE == "moi@10.0.0.1"
    assert d.CONTENEUR == "autre"
    assert d.CLE == "k.pem"


def test_une_variable_VIDE_retombe_sur_le_defaut(monkeypatch):
    """`or ...` et non `os.getenv(x, defaut)` : une variable posee mais VIDE
    doit retomber sur le defaut plutot que de viser une chaine vide."""
    d = _recharge(monkeypatch, OR_HOTE="", OR_CONTENEUR="")
    assert d.HOTE == "ec2-user@13.63.77.180"
    assert d.CONTENEUR == "scalping-radar"


def test_la_commande_porte_la_cle_DU_DEPOT(monkeypatch):
    """🔑 La cle est DANS le depot, pas dans ~/.ssh — une demi-heure perdue
    a essayer les trois cles de ~/.ssh, toutes refusees."""
    d = _recharge(monkeypatch)
    c = d.commande(pathlib.Path("/depot"))
    assert "-i" in c
    assert c[c.index("-i") + 1].endswith("scalping-key.pem")
    # separateur dependant de la plateforme : on compare au Path attendu
    assert c[c.index("-i") + 1] == str(pathlib.Path("/depot") / "scalping-key.pem")


def test_la_commande_garde_le_i_de_docker_exec(monkeypatch):
    """⛔ Sans `-i`, le conteneur ne recoit pas le flux stdin — et toute la
    raison d'etre de ce module est de passer par stdin."""
    d = _recharge(monkeypatch)
    c = d.commande(pathlib.Path("/depot"))
    assert "docker exec -i scalping-radar python3 -" in c[-1]


def test_la_commande_n_a_PAS_de_n(monkeypatch):
    """⛔ `-n` fermerait le stdin dont on se sert."""
    d = _recharge(monkeypatch)
    assert "-n" not in d.commande(pathlib.Path("/depot"))


def test_la_commande_reste_NON_INTERACTIVE(monkeypatch):
    """BatchMode : un ssh qui attend une saisie bloquerait la skill."""
    d = _recharge(monkeypatch)
    c = d.commande(pathlib.Path("/depot"))
    assert "BatchMode=yes" in c
    assert "StrictHostKeyChecking=no" in c


def test_la_surcharge_atteint_la_commande(monkeypatch):
    """Le reglage doit AGIR, pas seulement exister."""
    d = _recharge(monkeypatch, OR_HOTE="moi@10.0.0.1", OR_CONTENEUR="autre")
    c = d.commande(pathlib.Path("/depot"))
    assert "moi@10.0.0.1" in c
    assert "docker exec -i autre python3 -" in c[-1]
    _recharge(monkeypatch)   # on rend le module a son etat par defaut
