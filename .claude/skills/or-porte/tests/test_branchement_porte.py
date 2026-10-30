"""`or-porte` ne doit plus porter sa propre copie du transport.

Ses TROIS appelants doivent passer par `or_commun.distant`, et le mode vivier
doit continuer de lire un TABLEAU (prefixe `[`) et non un objet.
"""
import ast
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import porte  # noqa: E402

SOURCE = pathlib.Path(porte.__file__).read_text(encoding="utf-8")


def test_plus_de_copie_privee_du_transport():
    assert "_executer_a_distance" not in SOURCE


def test_le_module_importe_or_commun_distant():
    arbre = ast.parse(SOURCE)
    assert any(
        isinstance(n, ast.ImportFrom) and n.module == "or_commun"
        and any(a.name == "distant" for a in n.names)
        for n in ast.walk(arbre))


def test_aucun_appel_subprocess_direct_ne_reste():
    assert "subprocess.run" not in SOURCE


def test_le_mode_vivier_lit_toujours_un_TABLEAU():
    """Le vivier rend une liste de couples : perdre le prefixe `[` le
    casserait en silence, et le lot serait vide au lieu d'echouer."""
    assert 'prefixe="["' in SOURCE or "prefixe='['" in SOURCE
