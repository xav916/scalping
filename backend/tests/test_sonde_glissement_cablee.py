"""La sonde du coût d'exécution est-elle vraiment CÂBLÉE à l'ordonnanceur ?

⛔ LE DÉFAUT EXACT QUE CE FICHIER EXISTE POUR EMPÊCHER (2026-10-28).
`slippage_instrumentation_check.run()` existait depuis le 06/08 et n'était
appelé par **RIEN**, sauf son propre test. Le module écrit pour empêcher le
silence de se réinstaller était lui-même **muet** : onze semaines de glissement
absurde (`BTC/USD` à 1 113 350 pips) sans que personne ne le sache.

🔑 Un observateur non câblé vaut **moins** que pas d'observateur, parce qu'on
croit en avoir un. Vérifier que le module expose `executer()` ne prouve **rien**
sur l'appelant — c'est la leçon du 13/10, où j'avais vérifié que le module
appelé contenait la fonction sans vérifier que le script appelant l'appelait.

## ⛔ Et le choix du harnais, qui évite deux pièges opposés

- **Ne PAS exécuter `start_scheduler()`** : la première version d'un test voisin
  l'a fait, a écrit dans `data/scalping.db` et fait tomber **30 tests** d'autres
  fichiers. Le harnais était invasif.
- **Ne PAS chercher une chaîne dans le source** : un test qui cherche
  `"sonde_glissement"` dans un fichier passe encore quand la ligne est
  **commentée** (cf. `feedback_source_inspection_tests_weak`).

⇒ On lit l'**AST**. Une ligne commentée ne produit aucun nœud, donc le test
tombe — et rien n'est exécuté.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "services" / "scheduler.py"


def _appels_add_job() -> list[ast.Call]:
    arbre = ast.parse(_SRC.read_text(encoding="utf-8"))
    out = []
    for n in ast.walk(arbre):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "add_job"):
            out.append(n)
    return out


def _par_id(identifiant: str) -> ast.Call | None:
    for appel in _appels_add_job():
        for kw in appel.keywords:
            if (kw.arg == "id" and isinstance(kw.value, ast.Constant)
                    and kw.value.value == identifiant):
                return appel
    return None


def _kw(appel: ast.Call, nom: str):
    for kw in appel.keywords:
        if kw.arg == nom:
            return kw.value
    return None


# ─── 🔑 LE TEST QUI MANQUAIT ────────────────────────────────────────────────


def test_le_job_de_la_sonde_est_DECLARE():
    """⛔ C'est l'absence de ce job qui a laissé la sonde muette onze
    semaines."""
    assert _par_id("sonde_glissement") is not None, (
        "aucun add_job(id='sonde_glissement') dans scheduler.py — la sonde "
        "existe mais personne ne l'appelle, exactement le defaut du 06/08")


def test_le_job_appelle_bien_EXECUTER_de_la_sonde():
    """Un job déclaré qui appellerait autre chose serait armé et inerte."""
    appel = _par_id("sonde_glissement")
    cible = appel.args[0]

    assert isinstance(cible, ast.Attribute), "la cible n'est pas un attribut"
    assert cible.attr == "executer", f"cible = {cible.attr}, attendu executer"
    assert isinstance(cible.value, ast.Name)
    assert "sonde_glis" in cible.value.id or "slippage" in cible.value.id


def test_un_commentaire_ne_suffirait_PAS_a_faire_passer_ce_test():
    """🔑 La garde du harnais lui-même : on lit l'AST, donc une ligne
    commentée disparaît. Ce test le prouve sur un source fabriqué."""
    src = (
        "def f(s):\n"
        "    # s.add_job(x.executer, 'interval', id='sonde_glissement')\n"
        "    pass\n"
    )
    arbre = ast.parse(src)
    appels = [n for n in ast.walk(arbre)
              if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute)
              and n.func.attr == "add_job"]

    assert appels == [], "un appel commente ne doit produire AUCUN noeud"


# ─── la cadence et l'anti-empilement ────────────────────────────────────────


def test_la_cadence_est_en_HEURES_pas_en_minutes():
    """Elle juge une MÉDIANE sur des dizaines de trades : la sonder à la
    minute ne la ferait pas bouger plus vite, et une sonde qui parle trop
    finit par ne plus être lue."""
    appel = _par_id("sonde_glissement")

    assert _kw(appel, "hours") is not None, "cadence absente ou en minutes"
    assert _kw(appel, "minutes") is None
    assert _kw(appel, "seconds") is None


def test_le_job_REMPLACE_au_lieu_de_s_empiler():
    appel = _par_id("sonde_glissement")
    v = _kw(appel, "replace_existing")

    assert isinstance(v, ast.Constant) and v.value is True


def test_le_job_PORTE_UN_NOM_lisible():
    """Sans nom, un job est une ligne illisible dans `/tasks`."""
    appel = _par_id("sonde_glissement")
    v = _kw(appel, "name")

    assert isinstance(v, ast.Constant) and v.value
    assert len(v.value) > 10


# ─── et le module cible expose bien ce que le job appelle ───────────────────


def test_la_sonde_expose_EXECUTER_et_il_est_appelable():
    """⚠️ Nécessaire mais PAS suffisant : c'est précisément ce que je
    vérifiais le 13/10 en croyant avoir vérifié le câblage."""
    from backend.services import slippage_instrumentation_check as chk

    assert callable(chk.executer)
    assert callable(chk.run)
    assert callable(chk.message)


def test_le_job_de_la_sonde_1d_est_TOUJOURS_la():
    """⛔ Garde anti-régression : mon ajout ne doit pas avoir délogé le job
    voisin, puisque je l'ai inséré juste après lui."""
    assert _par_id("sonde_horizon_1d") is not None
