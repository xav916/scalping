"""Une cadence illisible ne doit pas emporter l'ordonnanceur (2026-10-30).

L'incident du 2026-10-11 : `start_scheduler()` faisait
`int(os.getenv("ECHELLE_STOP_INTERVAL_SEC", "15"))` sans garde. Un `.env`
dont une ligne s'etait collee a la precedente a donne
`ECHELLE_STOP_INTERVAL_SEC=1FENETRE_HEBDO_DEBUT=lun 00:00` => `ValueError`
=> la fonction s'arrete => **aucun travail declare apres cette ligne**. Le
conteneur restait `active` avec un ordonnanceur mort, et `systemctl
is-active` disait « tout va bien ».

`intervalle_sec()` a ete ecrite pour fermer ce defaut, mais une conversion y
avait echappe : `PROTECTION_PERTE_INTERVAL_SEC`, l.1210, DANS
`start_scheduler` (l.1062-1838) -- donc ~600 lignes de declarations de
travaux derriere elle. Trouve par analyse AST le 30/10, dix-neuf jours apres
l'incident : mon `grep` trouvait la DOCSTRING qui cite l'ancien code fautif,
pas le code fautif.

⛔ Pourquoi une fonction a part et pas `intervalle_sec()` : ici **0 est une
valeur LEGITIME** qui signifie « inerte, le cron `*/5` continue seul ».
`intervalle_sec` crie au niveau ERROR sur tout `v <= 0`. La reutiliser ferait
hurler une alerte sur une desactivation volontaire -- et du bruit dans un
journal de surete est exactement la facon dont une vraie alerte se perd.

⛔ Et ces tests n'appellent PAS `start_scheduler`. Le fichier le documente
lui-meme : un test qui l'appelait a ecrit dans `data/scalping.db`, bascule
`EUR/USD buy` en non-eligible et fait tomber **30 tests ailleurs**. D'ou
l'extraction, comme pour `config_cycle_rapide`.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from backend.services import scheduler as S

_SRC = pathlib.Path(S.__file__).read_text(encoding="utf-8")


# --- la fonction extraite, testee directement ----------------------------

@pytest.mark.parametrize("valeur,attendu", [
    (None, 0),          # absente  -> inerte, le cron continue seul
    ("", 0),            # vide     -> inerte
    ("0", 0),           # desactivation EXPLICITE -> inerte
    ("30", 30),         # cadence demandee
    ("  45  ", 45),     # espaces tolerees
])
def test_les_valeurs_lisibles(monkeypatch, valeur, attendu):
    if valeur is None:
        monkeypatch.delenv("PROTECTION_PERTE_INTERVAL_SEC", raising=False)
    else:
        monkeypatch.setenv("PROTECTION_PERTE_INTERVAL_SEC", valeur)
    assert S.intervalle_protection_sec() == attendu


@pytest.mark.parametrize("mauvaise", ["cinq", "1FENETRE_HEBDO_DEBUT=lun", "4.5", "-"])
def test_une_valeur_illisible_rend_0_et_NE_LEVE_PAS(monkeypatch, mauvaise):
    """La propriete centrale : elle ne leve jamais. Une levee ici tuerait
    tous les travaux declares apres la ligne d'appel."""
    monkeypatch.setenv("PROTECTION_PERTE_INTERVAL_SEC", mauvaise)
    assert S.intervalle_protection_sec() == 0, (
        "illisible doit rendre 0 (inerte, le cron continue seul), jamais lever")


def test_une_valeur_negative_rend_0():
    """Une cadence negative n'arme rien."""
    import os
    ancien = os.environ.get("PROTECTION_PERTE_INTERVAL_SEC")
    os.environ["PROTECTION_PERTE_INTERVAL_SEC"] = "-10"
    try:
        assert S.intervalle_protection_sec() == 0
    finally:
        if ancien is None:
            os.environ.pop("PROTECTION_PERTE_INTERVAL_SEC", None)
        else:
            os.environ["PROTECTION_PERTE_INTERVAL_SEC"] = ancien


def test_une_valeur_illisible_est_CRIEE(monkeypatch, caplog):
    """Elle ne leve pas, mais elle ne se tait pas non plus : une cadence qui
    n'est pas celle qu'on croit se lit six mois trop tard."""
    monkeypatch.setenv("PROTECTION_PERTE_INTERVAL_SEC", "cinq")
    with caplog.at_level("ERROR"):
        S.intervalle_protection_sec()
    assert any("PROTECTION_PERTE_INTERVAL_SEC" in r.message
               for r in caplog.records), "une valeur illisible doit CRIER"


def test_une_desactivation_explicite_ne_crie_PAS(monkeypatch, caplog):
    """`=0` est legitime. Crier dessus serait du bruit, et le bruit dans un
    journal de surete est la facon dont une vraie alerte se perd."""
    monkeypatch.setenv("PROTECTION_PERTE_INTERVAL_SEC", "0")
    with caplog.at_level("ERROR"):
        S.intervalle_protection_sec()
    assert not [r for r in caplog.records
                if "PROTECTION_PERTE_INTERVAL_SEC" in r.message]


# --- garde de DERIVE : plus aucune conversion nue dans start_scheduler ----

def _conversions_nues_dans(nom_fonction: str) -> list[int]:
    """Les `int/float(os.getenv(...))` hors `try`, dans cette fonction."""
    arbre = ast.parse(_SRC)
    cible = None
    for n in ast.walk(arbre):
        if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == nom_fonction):
            cible = n
            break
    assert cible is not None, "%s() introuvable" % nom_fonction

    sous_try = set()
    for t in ast.walk(cible):
        if isinstance(t, ast.Try):
            for sous in ast.walk(t):
                sous_try.add(id(sous))

    nues = []
    for n in ast.walk(cible):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id in ("int", "float") and n.args
                and isinstance(n.args[0], ast.Call)
                and getattr(n.args[0].func, "attr", "") == "getenv"
                and id(n) not in sous_try):
            nues.append(n.lineno)
    return nues


def test_aucune_conversion_nue_ne_subsiste_dans_start_scheduler():
    """⛔ LE garde-fou de derive. `start_scheduler` declare les travaux les
    uns apres les autres : une levee au milieu fait disparaitre TOUS CEUX QUI
    SUIVENT, sans que rien ne le signale. Toute lecture d'entier y passe donc
    par une fonction qui ne leve pas.

    Si ce test echoue, lire la ligne indiquee : quelqu'un a remis un
    `int(os.getenv(...))` nu dans la fonction la plus fragile du fichier.
    """
    nues = _conversions_nues_dans("start_scheduler")
    assert nues == [], (
        "conversion(s) nue(s) ligne(s) %s : une valeur illisible tuerait tous "
        "les travaux declares apres" % nues)
