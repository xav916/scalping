import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import regles as R  # noqa: E402

# admin_kraken, releve REEL du 2026-10-30.
KRAKEN = {
    "destination_id": "admin_kraken", "bridge_type": "kraken", "reel": True,
    "min_confidence": 42.0, "classes_porte": ["crypto"],
    "classes_registre": ["crypto", "metal"], "connue_du_registre": True,
    "garde_fous": {},
}
# admin_live, releve REEL du 2026-10-30.
LIVE = {
    "destination_id": "admin_live", "bridge_type": "mt5", "reel": True,
    "min_confidence": 42.0, "classes_porte": ["energy", "forex", "metal"],
    "classes_registre": ["energy", "equity", "forex", "metal"],
    "connue_du_registre": True,
    "garde_fous": {"max_open_positions": 10, "max_daily_loss_pct": 10.0},
}
LEGACY = dict(LIVE, destination_id="admin_legacy", reel=False,
              classes_registre=["energy", "forex", "metal"])
BLANCHES = {"admin_live": ["XAU/USD"], "admin_legacy": ["AUD/USD"]}


def _regle(dest, n, blanches=BLANCHES):
    return next(v for v in R.juger_destination(dest, blanches)
                if v["regle"] == n)


def test_cinq_verdicts_un_par_regle():
    v = R.juger_destination(KRAKEN, BLANCHES)
    assert [x["regle"] for x in v] == [1, 2, 3, 4, 5]


def test_regle1_FAIL_sur_argent_reel_sans_filtre():
    v = _regle(KRAKEN, 1)
    assert v["verdict"] == R.FAIL
    assert "admin_kraken" in v["valeur"] or "aucun" in v["valeur"].lower()


def test_regle1_CONFORME_quand_une_liste_existe():
    assert _regle(LIVE, 1)["verdict"] == R.CONFORME


def test_regle1_NON_APPLICABLE_sans_argent_reel():
    assert _regle(LEGACY, 1)["verdict"] == R.NON_APPLICABLE


def test_regle2_FAIL_quand_garde_fous_vide_et_argent_reel():
    assert _regle(KRAKEN, 2)["verdict"] == R.FAIL


def test_regle2_CONFORME_quand_le_pont_publie_ses_gardes():
    assert _regle(LIVE, 2)["verdict"] == R.CONFORME


def test_regle3_FAIL_sur_seuil_nul_ou_absent():
    for mauvais in (0, 0.0, None):
        assert _regle(dict(LIVE, min_confidence=mauvais), 3)["verdict"] == R.FAIL
    assert _regle(LIVE, 3)["verdict"] == R.CONFORME


def test_regle4_FAIL_si_inconnue_du_registre():
    v = _regle(dict(LIVE, connue_du_registre=False), 4)
    assert v["verdict"] == R.FAIL


def test_regle5_WARN_et_jamais_FAIL_sur_divergence():
    assert _regle(LIVE, 5)["verdict"] == R.WARN
    assert _regle(KRAKEN, 5)["verdict"] == R.WARN
    coherent = dict(LIVE, classes_registre=LIVE["classes_porte"])
    assert _regle(coherent, 5)["verdict"] == R.CONFORME


def test_chaque_verdict_nomme_sa_SOURCE_et_sa_VALEUR():
    for v in R.juger_destination(KRAKEN, BLANCHES):
        assert v["source"], "regle %d sans source" % v["regle"]
        assert v["valeur"] != "", "regle %d sans valeur lue" % v["regle"]


def test_argent_reel_sans_filtre_ET_sans_garde_rend_DEUX_fail():
    """Les deux disent la meme inquietude par deux chemins : les fondre en un
    seul motif ferait croire qu'il n'y a qu'un probleme."""
    faux = [v for v in R.juger_destination(KRAKEN, BLANCHES)
            if v["verdict"] == R.FAIL]
    assert len(faux) == 2
    assert {v["regle"] for v in faux} == {1, 2}


def test_admin_legacy_ne_declenche_AUCUN_fail():
    """Une skill qui alerte sur un compte papier crie au loup."""
    assert not [v for v in R.juger_destination(LEGACY, BLANCHES)
                if v["verdict"] == R.FAIL]
