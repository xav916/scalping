"""Aucune sonde ne doit envoyer de balises à `notify-infra-telegram`.

L'endpoint passe le body dans `html.escape` : une balise n'y est pas
interprétée, elle s'affiche **telle quelle**. Mesuré le 26/08 sur la sonde
horizon, puis retrouvé le 28/08 sur **huit** sondes — dont celle de
saturation, qui affichait `<b>28,75 €</b>` à chaque alerte depuis sa pose.

> **Une mise en forme qui traverse un échappement n'est plus une mise en
> forme, c'est du bruit.**

⛔ Second défaut de la même famille : `html.escape` appliqué **dans** la sonde
en plus de l'endpoint. Un `&` ressortait alors en `&amp;` à l'écran.
Échapper deux fois n'est pas échapper mieux.

## Pourquoi ce test-ci est de niveau SOURCE, contrairement à l'usage

Un test par sonde exigerait de harnacher sept constructeurs de messages
différents, et **ne dirait rien de la huitième**. La propriété vérifiée est
textuelle par nature : « aucune chaîne littérale destinée à un body ne
contient de balise ». On la vérifie donc par l'AST — pas par une regex sur le
source — en excluant les docstrings, où la prose a le droit de MONTRER la
balise qu'elle explique.

⚠️ Ce test s'applique automatiquement à toute sonde future qui poste sur cet
endpoint. C'est son intérêt principal : le défaut s'est propagé par copie.

⚠️ Il ne concerne QUE ce chemin. La commande `risque` à la demande garde ses
balises et c'est correct : elle passe par `send_sales_text(parse_mode="HTML")`,
qui les rend. Deux chemins, deux contrats.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

_SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "scripts"

_BALISE = re.compile(r"</?[a-zA-Z][a-zA-Z0-9]*>")


def _sondes_de_l_endpoint() -> list[pathlib.Path]:
    """Les scripts qui postent sur `notify-infra-telegram`, et eux seuls."""
    return sorted(p for p in _SCRIPTS.glob("*.py")
                  if "notify-infra-telegram" in p.read_text(encoding="utf-8"))


def _docstrings(arbre: ast.AST) -> set[int]:
    """`id()` des nœuds qui sont des docstrings — la prose peut montrer une
    balise pour expliquer pourquoi il ne faut pas en envoyer."""
    ids = set()
    for n in ast.walk(arbre):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                          ast.AsyncFunctionDef)):
            corps = getattr(n, "body", None) or []
            if (corps and isinstance(corps[0], ast.Expr)
                    and isinstance(corps[0].value, ast.Constant)
                    and isinstance(corps[0].value.value, str)):
                ids.add(id(corps[0].value))
    return ids


def test_il_y_a_bien_des_sondes_a_verifier():
    """⛔ Un test qui ne trouve aucun fichier passe toujours. Il faut donc
    d'abord prouver qu'il regarde quelque chose."""
    sondes = _sondes_de_l_endpoint()
    assert len(sondes) >= 8, [p.name for p in sondes]


@pytest.mark.parametrize("chemin", _sondes_de_l_endpoint(),
                         ids=lambda p: p.name)
def test_aucune_balise_dans_les_chaines_envoyees(chemin):
    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    docs = _docstrings(arbre)
    fautives = [
        n.value for n in ast.walk(arbre)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and id(n) not in docs and _BALISE.search(n.value)
    ]
    assert not fautives, f"{chemin.name} : {fautives}"


@pytest.mark.parametrize("chemin", _sondes_de_l_endpoint(),
                         ids=lambda p: p.name)
def test_aucun_echappement_local(chemin):
    """⛔ L'endpoint échappe déjà. Le faire ici aussi produit du `&amp;` à
    l'écran — et un test qui ne regarde que les balises le laisserait passer."""
    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    appels = [
        n for n in ast.walk(arbre)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "escape"
        and isinstance(n.func.value, ast.Name) and n.func.value.id == "html"
    ]
    assert not appels, f"{chemin.name} : {len(appels)} html.escape() restant(s)"
