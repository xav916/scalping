"""Un refus pour risque mal dimensionne doit porter son NOM.

Le bridge refuse desormais en 422 `risque_realise_trop_faible` quand le lot
obtenu risque moins de la moitie du voulu (455 trades du demo etaient dans ce
cas). Sans code dedie, ce refus tomberait dans le fourre-tout `bridge_error` et
serait invisible dans les tableaux — exactement comme `bridge_max_positions`
melangeait trois causes distinctes.
"""
import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "backend" / "services" / "mt5_bridge.py"


def _codes_de_refus_bridge():
    """Extrait par AST les litteraux affectes a `reason` dans la branche qui
    categorise une reponse HTTP en erreur. Pas de recherche de chaine."""
    arbre = ast.parse(_SRC.read_text(encoding="utf-8"))
    codes = set()
    for n in ast.walk(arbre):
        if isinstance(n, ast.Assign) and len(n.targets) == 1:
            cible = n.targets[0]
            if isinstance(cible, ast.Name) and cible.id == "reason":
                if isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
                    codes.add(n.value.value)
    return codes


def test_le_risque_mal_dimensionne_a_son_propre_code():
    codes = _codes_de_refus_bridge()
    assert "bridge_risque_incoherent" in codes, (
        f"aucun code dedie au risque mal dimensionne ; codes trouves : {sorted(codes)}"
    )


def test_les_codes_existants_sont_preserves():
    codes = _codes_de_refus_bridge()
    for attendu in ("bridge_max_positions", "bridge_invalid_stops", "bridge_error"):
        assert attendu in codes
