import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import porte as P  # noqa: E402

S = {"pair": "XAU/USD", "direction": "buy", "entry_price": 2412.50,
     "stop_loss": 2404.10, "confidence_score": 71, "pattern": "range_bounce",
     "horizon": "30min", "chaine": None, "shadow_system_id": None,
     "is_simulated": False, "verdict_blockers": [], "risk_pct": 0.35}

LOT = {"destinations": ["admin_live"], "setups": [S]}

# Limites et empreinte REELLES du 2026-10-29.
LIM = {"admin_live": {"order_cooldown_sec": 0,
                      "max_risque_engage_pct": 5.0,
                      "max_risque_engage_or_argent_pct": 15.0,
                      "max_open_positions": 2}}


def _brut(reason_code=None, **kw):
    base = {
        "fingerprint_running": "a4d9aedeee17",
        "rem002_allowed": False, "rem002_reason": "DISARMED_MANUALLY",
        "verdicts": [{"i": 0, "destination": "admin_live",
                      "reason_code": reason_code, "classe": "metal",
                      "admission": "AUTO_EXEC"}],
        "limites": LIM, "libelles": {}, "sans_libelle": [],
    }
    base.update(kw)
    return base


def test_tout_passe_rend_0_et_un_etat_avec_les_deux_empreintes():
    code, lignes, etat = P.juger(LOT, _brut())
    assert code == 0
    assert etat["empreinte_code"] == "a4d9aedeee17"
    assert etat["verdicts"][0]["empreinte_setup"]
    assert etat["verdicts"][0]["resultat"] == "PASS"


def test_un_refus_de_production_rend_1_avec_son_origine():
    b = _brut("below_confidence", libelles={"below_confidence": "Confiance < seuil"})
    code, lignes, etat = P.juger(LOT, b)
    assert code == 1
    v = etat["verdicts"][0]
    assert v["resultat"] == "BLOCK"
    assert v["reason_code"] == "below_confidence"
    assert v["libelle"] == "Confiance < seuil"
    assert v["origine"] == P.ORIGINE_PRODUCTION


def test_un_motif_sans_libelle_retombe_sur_le_code_brut_et_est_signale():
    b = _brut("pair_not_whitelisted", sans_libelle=["pair_not_whitelisted"])
    code, lignes, etat = P.juger(LOT, b)
    assert code == 1
    assert etat["verdicts"][0]["libelle"] == "pair_not_whitelisted"
    texte = "\n".join(lignes)
    assert "sans libelle" in texte.lower()


def test_juger_ne_peut_PAS_inventer_un_verdict_de_production():
    """Invariant central : tout BLOCK d'origine `production` porte un
    `reason_code` PRESENT dans `brut`. La skill ne juge jamais a la place de
    la production -- elle ne fait que rapporter ce qu'elle a rendu."""
    for code in (None, "below_confidence", "market_closed", "kill_switch"):
        b = _brut(code)
        _, _, etat = P.juger(LOT, b)
        codes_rendus = {v["reason_code"] for v in b["verdicts"]
                        if v["reason_code"]}
        de_production = [v for v in etat["verdicts"]
                         if v.get("origine") == P.ORIGINE_PRODUCTION]
        for v in de_production:
            assert v["reason_code"] in codes_rendus, (
                "verdict de production INVENTE : %s" % v["reason_code"])
        if code is None:
            assert de_production == [], (
                "la production n'a rien refuse, aucun BLOCK de production "
                "ne doit apparaitre")
        else:
            assert len(de_production) == 1 and \
                de_production[0]["reason_code"] == code


def test_fingerprint_absent_rend_2_et_ne_juge_rien():
    b = _brut()
    b["fingerprint_running"] = None
    code, lignes, etat = P.juger(LOT, b)
    assert code == 2
    assert "empreinte_code_illisible" in "\n".join(lignes)


def test_un_verdict_manquant_pour_un_couple_rend_2():
    b = _brut()
    b["verdicts"] = []
    code, lignes, _ = P.juger(LOT, b)
    assert code == 2


def test_un_code_2_n_affiche_aucun_verdict_meme_pour_les_couples_deja_traites():
    """Le premier couple PASSE, le second n'a aucun verdict de production.
    Un code 2 doit juger RIEN : la ligne PASS du premier couple deja traite
    ne doit pas survivre dans le rapport, sous peine de mentir sur un run
    que l'on declare par ailleurs injugeable."""
    lot = {"destinations": ["admin_live"], "setups": [S, dict(S)]}
    b = _brut()
    b["verdicts"] = [{"i": 0, "destination": "admin_live",
                      "reason_code": None, "classe": "metal",
                      "admission": "AUTO_EXEC"}]
    code, lignes, etat = P.juger(lot, b)
    assert code == 2
    assert etat == {}
    assert "PASS" not in "\n".join(lignes)


def test_une_erreur_de_porte_bloque_le_setup_sans_arreter_le_lot():
    b = _brut("porte_en_erreur:KeyError")
    code, lignes, etat = P.juger(LOT, b)
    assert code == 1
    assert etat["verdicts"][0]["resultat"] == "BLOCK"


def test_la_sortie_rappelle_que_les_clauses_de_lot_sont_un_ajout():
    _, lignes, _ = P.juger(LOT, _brut())
    texte = "\n".join(lignes)
    assert "ajout" in texte.lower()
    assert "a4d9aedeee17" in texte


def test_la_sortie_nomme_l_etat_d_armement():
    _, lignes, _ = P.juger(LOT, _brut())
    assert "DISARMED_MANUALLY" in "\n".join(lignes)


def test_le_correctif_nomme_la_valeur_lue():
    """Le correctif cite la valeur du setup. Le SEUIL, lui, n'est pas dans le
    contrat `brut` : la production rend un `reason_code`, pas le seuil
    franchi. Le faire remonter est une suite, pas une invention d'ici."""
    b = _brut("below_confidence", libelles={"below_confidence": "Confiance < seuil"})
    _, _, etat = P.juger(LOT, b)
    assert "71" in etat["verdicts"][0]["correctif"]


# ──────────────────────────────────────────────────────────────────────
# Important 1 (2026-10-29) : le plafond de lot `max_open_positions` est
# GLOBAL par destination, jamais un cap par paire -- integre ici au niveau
# de `juger()`, en plus de l'unitaire `test_contraintes_lot.py`.
# ──────────────────────────────────────────────────────────────────────

def test_juger_applique_le_plafond_global_meme_sur_des_paires_differentes():
    lot3 = {"destinations": ["admin_live"], "setups": [
        S, dict(S, pair="XAG/USD"), dict(S, pair="EUR/USD")]}
    b = _brut()
    b["verdicts"] = [
        {"i": i, "destination": "admin_live", "reason_code": None,
         "classe": "metal", "admission": "AUTO_EXEC"} for i in range(3)]
    code, lignes, etat = P.juger(lot3, b)
    assert code == 1
    resultats = [v["resultat"] for v in etat["verdicts"]]
    assert resultats == ["PASS", "PASS", "BLOCK"], (
        "max_open_positions=2 (LIM) doit bloquer le TROISIEME setup, meme "
        "sur sa propre troisieme paire -- un cap garde par paire le "
        "laisserait passer")
    assert etat["verdicts"][2]["reason_code"] == "lot_places_destination"


# ──────────────────────────────────────────────────────────────────────
# Important 2 (2026-10-29) : la poche de risque engage suit la classe
# d'actif du setup, pas la destination -- integre ici via `vp["classe"]`.
# ──────────────────────────────────────────────────────────────────────

def test_juger_lit_la_poche_or_argent_pour_un_setup_metal():
    """Avec la poche commune a 5 % et la poche or/argent a 15 %, un risque
    de 10 % doit PASSER pour un setup `classe=metal` -- il serait BLOQUE a
    tort si la clause lisait encore la poche commune (Important 2)."""
    s = dict(S, risk_pct=10.0)
    lot1 = {"destinations": ["admin_live"], "setups": [s]}
    b = _brut()
    b["verdicts"] = [{"i": 0, "destination": "admin_live",
                      "reason_code": None, "classe": "metal",
                      "admission": "AUTO_EXEC"}]
    code, _, etat = P.juger(lot1, b)
    assert code == 0
    assert etat["verdicts"][0]["resultat"] == "PASS"


def test_juger_bloque_un_setup_non_metal_contre_la_poche_commune():
    s = dict(S, pair="EUR/USD", risk_pct=10.0)
    lot1 = {"destinations": ["admin_live"], "setups": [s]}
    b = _brut()
    b["verdicts"] = [{"i": 0, "destination": "admin_live",
                      "reason_code": None, "classe": "forex",
                      "admission": "AUTO_EXEC"}]
    code, _, etat = P.juger(lot1, b)
    assert code == 1
    assert etat["verdicts"][0]["reason_code"] == "lot_risque_engage"


# ──────────────────────────────────────────────────────────────────────
# Minor 1 reclassifie (2026-10-29) : `asset_class_blocked` doit avoir son
# propre correctif, pointant la fonction REELLE qui le reconstruit.
# ──────────────────────────────────────────────────────────────────────

def test_le_correctif_asset_class_blocked_ne_pointe_pas_check_rejection():
    """Avant le correctif, `asset_class_blocked` n'avait pas d'entree dans
    `_CORRECTIFS` : le fallback generique disait « lire `asset_class_blocked`
    dans `mt5_bridge._check_rejection` » -- la MAUVAISE fonction, puisque ce
    code est reconstruit par `_push_to_destination` (mt5_bridge.py:2278)."""
    texte = P.correctif("asset_class_blocked", S)
    assert "asset_class_blocked" in P._CORRECTIFS, (
        "asset_class_blocked doit avoir sa PROPRE entree, pas le fallback "
        "generique qui pointe _check_rejection")
    assert "dans `mt5_bridge._check_rejection`" not in texte
    assert "_push_to_destination" in texte or "2278" in texte


# ──────────────────────────────────────────────────────────────────────
# Important 3 (2026-10-29) : le contrat des codes de sortie. `juger()`
# ne doit RIEN laisser remonter -- c'est `main()` qui l'enveloppe desormais
# (verifie ici au niveau du contrat : une entree qui ferait planter
# `contraintes_lot` a l'interieur de `juger` doit etre rattrapable par
# l'appelant sans jamais produire le code 1 reserve a « au moins un BLOCK »).
# ──────────────────────────────────────────────────────────────────────

def test_une_limite_non_numerique_leve_a_l_interieur_de_juger_pas_un_1_silencieux():
    """`contraintes_lot` fait `int(limites[...])` : une valeur `/health` non
    numerique y leve `ValueError` *a l'interieur* de `juger()`, puisque
    `juger()` n'est pas protege lui-meme -- c'est `main()` qui doit la
    rattraper et rendre 2, jamais laisser Python sortir en 1."""
    import pytest
    b = _brut()
    b["limites"]["admin_live"]["order_cooldown_sec"] = "pas-un-nombre"
    with pytest.raises(ValueError):
        P.juger(LOT, b)
