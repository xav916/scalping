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
    """Un reason_code en litteral dans la charge serait une porte recopiee.

    ⚠️ "asset_class_blocked" est volontairement ABSENT de cette liste : c'est
    la SEULE exception admise (cf. test ci-dessous), car c'est la SEULE porte
    reconstruite -- la production l'applique dans `_push_to_destination`,
    une fonction qui envoie des ordres et qu'un miroir en lecture seule ne
    peut donc pas appeler.
    """
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


def test_exceptions_dans_la_boucle_setup_sont_gardees():
    """Les trois appels critiques doivent être dans un try/except."""
    src = C.construire(LOT)
    arbre = ast.parse(src)

    # Collect all calls in Try nodes
    calls_protected = set()
    for node in ast.walk(arbre):
        if isinstance(node, ast.Try):
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name):
                        calls_protected.add(child.func.id)
                    elif isinstance(child.func, ast.Attribute):
                        calls_protected.add(child.func.attr)

    # All three critical calls must be inside try blocks
    assert "asset_class_for" in calls_protected, "asset_class_for not protected"
    assert "get_current_state" in calls_protected, "get_current_state not protected"
    assert "_check_rejection" in calls_protected, "_check_rejection not protected"


# ──────────────────────────────────────────────────────────────────────
# Tests de derive ajoutes le 2026-10-29 (correctif R13-R17) : la charge
# resolvait les destinations avec le MAUVAIS type d'objet -- invisible
# tant que `execution_globale_fermee` court-circuite tout, et qui se
# serait revele au rearmement, le seul moment ou l'outil doit etre juste.
# ──────────────────────────────────────────────────────────────────────

def test_la_charge_resout_par_admin_destinations_et_plus_par_le_registre():
    """`_check_rejection(setup, dest)` attend un `BridgeConfig` --
    `destinations_registry.get()` rend un `Destination` qui n'a ni
    `.destination_id` ni `.min_confidence`. La charge doit resoudre par
    `bridge_destinations.admin_destinations()`, la fonction que la
    production elle-meme itere, et `destinations_registry` ne doit plus
    servir a decider quoi que ce soit ici."""
    src = C.construire(LOT)
    assert "destinations_registry" not in src, (
        "le registre ne doit plus etre une source de decision dans la charge")
    arbre = ast.parse(src)
    appels = [n for n in ast.walk(arbre)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "admin_destinations"]
    assert appels, "la charge doit APPELER bridge_destinations.admin_destinations"


def test_la_charge_lit_allowed_asset_classes_et_pas_asset_classes_du_registre():
    """Le registre et le `BridgeConfig` desaccordent sur les classes
    autorisees (admin_live a FAUSSEMENT `equity`, admin_kraken a FAUSSEMENT
    `metal`) : la charge doit lire `allowed_asset_classes` du `BridgeConfig`,
    jamais `asset_classes` du registre."""
    src = C.construire(LOT)
    assert "allowed_asset_classes" in src, (
        "la charge doit lire `allowed_asset_classes` sur le BridgeConfig")
    assert ".asset_classes" not in src, (
        "la charge ne doit plus lire `asset_classes` (l'attribut du "
        "registre, dont l'ensemble est faux)")


def test_la_charge_rend_le_littteral_asset_class_blocked_comme_SEULE_exception():
    """`asset_class_blocked` est le code que `_push_to_destination` rend pour
    la clause de classe d'actif -- inutilisable ici car cette fonction
    envoie des ordres. C'est la SEULE porte reconstruite de toute la charge,
    donc la SEULE exception admise a la regle « aucun reason_code en dur »
    (verifiee par `test_la_charge_ne_REIMPLEMENTE_aucune_porte` ci-dessus,
    qui exclut nommement ce code de sa liste interdite)."""
    src = C.construire(LOT)
    assert '"asset_class_blocked"' in src


def test_la_charge_APPELLE_order_cooldown_delai_requis():
    """R16 : la cadence vient de `order_cooldown.delai_requis(dest)`, pas
    d'un champ du registre (`order_cooldown_sec` n'existe pas sur le
    `BridgeConfig`)."""
    src = C.construire(LOT)
    arbre = ast.parse(src)
    appels = [n for n in ast.walk(arbre)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "delai_requis"]
    assert appels, "la charge doit APPELER order_cooldown.delai_requis"
