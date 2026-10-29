import ast
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import charge as C  # noqa: E402

LOT = {
    "destinations": ["admin_live"],
    "setups": [{
        "pair": "XAU/USD", "direction": "buy", "entry_price": 2412.50,
        "stop_loss": 2404.10, "confidence_score": 71,
        "pattern": "range_bounce", "horizon": "30min", "chaine": None,
        "shadow_system_id": None, "is_simulated": False,
        "verdict_blockers": [], "risk_pct": 0.35,
    }],
}


def test_la_charge_est_du_python_valide():
    ast.parse(C.construire(LOT))


def test_la_charge_APPELLE_check_rejection_de_production():
    src = C.construire(LOT)
    assert "_check_rejection" in src
    arbre = ast.parse(src)
    appels = [n for n in ast.walk(arbre)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "_check_rejection"]
    assert appels, "la charge doit APPELER la porte de production"


def test_la_charge_ne_REIMPLEMENTE_aucune_porte():
    """Un reason_code en litteral dans la charge serait une porte recopiee."""
    src = C.construire(LOT)
    for code in ("below_confidence", "market_closed", "kill_switch",
                 "pair_not_whitelisted", "correlated_exposure"):
        assert code not in src, "%s est recopie dans la charge" % code


def test_la_charge_APPELLE_asset_class_for_au_lieu_de_deduire_la_classe():
    """La classe d'actif doit venir de la production, pas d'une table locale."""
    src = C.construire(LOT)
    arbre = ast.parse(src)
    appels = [n for n in ast.walk(arbre)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == "asset_class_for"]
    assert appels, "la charge doit APPELER asset_class_for"


def test_aucun_litteral_de_classe_d_actif_dans_la_charge():
    """Un littéral de classe serait une table de correspondance recopiée."""
    src = C.construire(LOT)
    arbre = ast.parse(src)
    litteraux = {n.value for n in ast.walk(arbre)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    interdits = {"metal", "forex", "crypto", "energy", "equity"}
    assert not (litteraux & interdits), (
        "classe(s) d'actif en dur dans la charge : %s"
        % sorted(litteraux & interdits))


def test_le_lot_est_embarque_par_json_et_non_par_concatenation():
    src = C.construire(LOT)
    assert "2412.5" in src or "2412.50" in src
    assert "json.loads(" in src, "le lot doit etre injecte en JSON"


def test_la_charge_rend_le_fingerprint_et_les_sans_libelle():
    src = C.construire(LOT)
    for clef in ("fingerprint_running", "sans_libelle", "limites",
                 "verdicts", "admission", "classe"):
        assert clef in src, "la charge doit rendre `%s`" % clef
