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
    """Extrait par AST les codes rendus par la fonction qui categorise un
    refus du bridge. Pas de recherche de chaine.

    ⚠️ **Extraction reecrite le 2026-08-28.** Elle cherchait des affectations
    `reason = "..."`. Le 2026-08-25, la categorisation a ete extraite dans
    `_categoriser_refus`, qui `return` ses codes au lieu de les affecter :
    l'extraction ne trouvait plus RIEN et les deux tests echouaient en
    annoncant « aucun code dedie », alors que les huit codes existaient.

    > **Un test qui lit la FORME du code casse quand la forme change, meme
    > quand le fond est intact.** On vise donc la fonction par son nom, et on
    > lit ses `return` — ce qu'elle rend est justement son contrat.
    """
    arbre = ast.parse(_SRC.read_text(encoding="utf-8"))
    codes = set()
    for n in ast.walk(arbre):
        # La forme d'hier : `reason = "..."`. Gardee, elle ne coute rien.
        if isinstance(n, ast.Assign) and len(n.targets) == 1:
            cible = n.targets[0]
            if (isinstance(cible, ast.Name) and cible.id == "reason"
                    and isinstance(n.value, ast.Constant)
                    and isinstance(n.value.value, str)):
                codes.add(n.value.value)
        # La forme d'aujourd'hui : les `return` de `_categoriser_refus`.
        if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == "_categoriser_refus"):
            for interne in ast.walk(n):
                if (isinstance(interne, ast.Return)
                        and isinstance(interne.value, ast.Constant)
                        and isinstance(interne.value.value, str)):
                    codes.add(interne.value.value)
    return codes


def test_l_extraction_trouve_bien_quelque_chose():
    """⛔ Un extracteur qui ne trouve rien fait passer « le code manque » pour
    un fait. C'est exactement ce qui s'est produit du 25 au 28/08 : les deux
    tests ci-dessous annoncaient l'absence des codes, alors qu'ils avaient
    seulement change de forme."""
    codes = _codes_de_refus_bridge()
    assert len(codes) >= 5, f"extraction cassee, codes trouves : {sorted(codes)}"


def test_le_risque_mal_dimensionne_a_son_propre_code():
    codes = _codes_de_refus_bridge()
    assert "bridge_risque_incoherent" in codes, (
        f"aucun code dedie au risque mal dimensionne ; codes trouves : {sorted(codes)}"
    )


def test_les_codes_existants_sont_preserves():
    codes = _codes_de_refus_bridge()
    for attendu in ("bridge_max_positions", "bridge_invalid_stops", "bridge_error"):
        assert attendu in codes
