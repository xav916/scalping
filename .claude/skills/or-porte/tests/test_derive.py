import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import lot as L  # noqa: E402

prod = pytest.importorskip("backend.services.mt5_bridge",
                           reason="hors conteneur de production")


def _champs_lus_transitivement():
    """Recalcule les champs que `_check_rejection` et ses aides lisent."""
    import ast
    import inspect
    champs, vus, pile = set(), set(), ["_check_rejection"]
    while pile:
        nom = pile.pop()
        if nom in vus:
            continue
        vus.add(nom)
        fn = getattr(prod, nom, None)
        if not callable(fn):
            continue
        try:
            arbre = ast.parse(inspect.getsource(fn))
        except Exception:
            continue
        for n in ast.walk(arbre):
            if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                    and n.value.id == "setup"):
                champs.add(n.attr)
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "getattr" and len(n.args) > 1
                    and isinstance(n.args[0], ast.Name)
                    and n.args[0].id == "setup"
                    and isinstance(n.args[1], ast.Constant)):
                champs.add(n.args[1].value)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                    and n.func.id.startswith("_"):
                pile.append(n.func.id)
    return champs


def test_la_liste_des_onze_est_celle_que_la_production_lit():
    lus = _champs_lus_transitivement()
    assert lus == set(L.CHAMPS_PORTES), (
        "la production lit %s ; l'empreinte couvre %s. Un champ de plus "
        "garderait vivant un verdict perime."
        % (sorted(lus), sorted(L.CHAMPS_PORTES)))
