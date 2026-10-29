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
LIM = {"admin_live": {"max_correlated_positions": 3, "order_cooldown_sec": 0,
                      "max_risque_engage_pct": 5.0, "places_par_paire": 2}}


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
