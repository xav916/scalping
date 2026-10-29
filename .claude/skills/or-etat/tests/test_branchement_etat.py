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
