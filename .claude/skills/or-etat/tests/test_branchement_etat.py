"""`or-etat` ne doit plus porter sa propre copie du transport."""
import ast
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import etat  # noqa: E402

SOURCE = pathlib.Path(etat.__file__).read_text(encoding="utf-8")


def test_plus_de_copie_privee_du_transport():
    assert "_executer_a_distance" not in SOURCE, \
        "le transport doit venir de or_commun, pas d'une copie locale"


def test_le_module_importe_or_commun_distant():
    arbre = ast.parse(SOURCE)
    importe = any(
        isinstance(n, ast.ImportFrom) and n.module == "or_commun"
        and any(a.name == "distant" for a in n.names)
        for n in ast.walk(arbre))
    assert importe, "attendu : `from or_commun import distant`"


def test_aucun_appel_subprocess_direct_ne_reste():
    """Tout passe par `distant.executer` desormais."""
    assert "subprocess.run" not in SOURCE


def test_aucun_import_mort():
    """`json` ne servait que dans la fonction supprimee au branchement.
    Verifie par AST et non par grep : `json` apparait encore dans des
    CHAINES destinees au processus distant, et un grep aurait conclu qu'il
    servait. Troisieme fois ce jour-la qu'un grep trompe sur un motif qui
    figure aussi dans la prose ou la donnee."""
    arbre = ast.parse(SOURCE)
    utilises = {n.id for n in ast.walk(arbre) if isinstance(n, ast.Name)}
    utilises |= {n.value.id for n in ast.walk(arbre)
                 if isinstance(n, ast.Attribute)
                 and isinstance(n.value, ast.Name)}
    importes = [al.name.split(".")[0]
                for n in ast.walk(arbre) if isinstance(n, ast.Import)
                for al in n.names]
    morts = [i for i in importes if i not in utilises]
    assert morts == [], "import(s) mort(s) : %s" % morts
