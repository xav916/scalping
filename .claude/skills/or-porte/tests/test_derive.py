import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import lot as L  # noqa: E402

prod = pytest.importorskip("backend.services.mt5_bridge",
                           reason="hors conteneur de production")


def _champs_lus_transitivement():
    """Recalcule les champs que `_check_rejection` et ses aides lisent.

    Durci le 2026-10-29 (Minor reclassifie Important par le controleur) :
    le parcours d'origine ne suivait que les appels `Name` prefixes `_` et
    les attributs d'une variable LITTERALEMENT nommee `setup` -- un
    parametre renomme, un appel qualifie (`module.fonction(setup)`) ou un
    `getattr(s, 'x', None)` sur un alias passaient inapercus. Un champ
    manquant devient un DEFAULT dans `SimpleNamespace` (`lot.py`/`porte.py`
    construisent le setup via `**s`), jamais une erreur : la SEULE forme qui
    pourrait devenir un FAUX PASS.

    Le parcours propage maintenant l'alias de `setup` a travers les
    arguments POSITIONNELS ET NOMMES de chaque appel, en lisant la vraie
    signature (`inspect.signature`) du callee pour nommer son parametre --
    donc un parametre renomme est suivi correctement, par construction.
    Les appels qualifies (`module.fonction(...)`) et non-prefixes `_` sont
    suivis de la meme facon, tant qu'ils resolvent a un attribut du module
    (une methode d'instance ou un import local reste invisible, ce qui est
    le cote SUR de l'approximation, jamais le cote qui pourrait manquer un
    champ). Un attribut/`getattr` n'est retenu que si sa cible est un ALIAS
    CONNU de `setup` -- jamais « toute variable nommee setup », qui etait
    la source de l'angle mort.
    """
    import ast
    import inspect

    champs: set = set()
    vus: set = set()
    pile = [("_check_rejection", frozenset({"setup"}))]

    while pile:
        nom, alias = pile.pop()
        cle = (nom, alias)
        if cle in vus:
            continue
        vus.add(cle)
        fn = getattr(prod, nom, None)
        if not callable(fn):
            continue
        try:
            arbre = ast.parse(inspect.getsource(fn))
        except Exception:
            continue

        def _est_alias(node, _alias=alias):
            return isinstance(node, ast.Name) and node.id in _alias

        for n in ast.walk(arbre):
            if isinstance(n, ast.Attribute) and _est_alias(n.value):
                champs.add(n.attr)
                continue
            if not isinstance(n, ast.Call):
                continue
            func = n.func
            est_getattr = (
                (isinstance(func, ast.Name) and func.id == "getattr")
                or (isinstance(func, ast.Attribute) and func.attr == "getattr"))
            if (est_getattr and len(n.args) > 1 and _est_alias(n.args[0])
                    and isinstance(n.args[1], ast.Constant)):
                champs.add(n.args[1].value)

            # Nom de la fonction appelee : direct (`foo(...)`) ou qualifie
            # (`mod.foo(...)`) -- seul le dernier segment compte.
            if isinstance(func, ast.Name):
                nom_appel = func.id
            elif isinstance(func, ast.Attribute):
                nom_appel = func.attr
            else:
                continue
            if nom_appel == "getattr":
                continue  # deja traite ci-dessus, jamais un callee a suivre
            callee = getattr(prod, nom_appel, None)
            if not callable(callee):
                continue  # methode d'instance / import local : invisible ici
            try:
                params = list(inspect.signature(callee).parameters)
            except (TypeError, ValueError):
                params = []

            alias_callee = set()
            for i, arg in enumerate(n.args):
                if i < len(params) and _est_alias(arg):
                    alias_callee.add(params[i])
            for kw in n.keywords:
                if kw.arg and _est_alias(kw.value):
                    alias_callee.add(kw.arg)
            if alias_callee:
                pile.append((nom_appel, frozenset(alias_callee)))
    return champs


def test_la_liste_des_onze_est_celle_que_la_production_lit():
    lus = _champs_lus_transitivement()
    assert lus == set(L.CHAMPS_PORTES), (
        "la production lit %s ; l'empreinte couvre %s. Un champ de plus "
        "garderait vivant un verdict perime."
        % (sorted(lus), sorted(L.CHAMPS_PORTES)))
