"""Le banc de la DERIVE APRES SURPRISE — pre-enregistre le 2026-10-05 (`c536a2c`).

⛔ Tout ce qui est teste ici a ete DECLARE AVANT ce fichier, dans
`docs/concepts-trading.md`, commit seul. Aucun seuil n'est choisi ici : ils
sont recopies de la declaration.

    seuil |S| >= 1,5 · au moins 12 occurrences anterieures · |s| > 10 ecarte
    six familles d'evenements, polarite declaree · bougies H1 du courtier
    entree a la 1re bougie STRICTEMENT posterieure · sorties +1/2/4/8 h
    R = ATR(14) H1 · spread facture

🔑 Ces tests ne mesurent pas si l'hypothese marche. Ils verifient que
l'appareil fait ce que la declaration dit — ce qui est la seule chose qu'on
puisse verifier avant de regarder le resultat.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.services import banc_surprise as bs


def _b(h: int, o: float, c: float, haut=None, bas=None):
    """Une bougie H1 a l'heure `h` du 2026-01-05."""
    from backend.models.schemas import Candle
    return Candle(timestamp=datetime(2026, 1, 5, h, 0, tzinfo=timezone.utc),
                  open=o, close=c,
                  high=haut if haut is not None else max(o, c),
                  low=bas if bas is not None else min(o, c), volume=1.0)


# ─── La polarite : recopiee de la declaration, jamais deduite ────────────────

def test_les_six_familles_declarees_et_RIEN_d_autre():
    assert bs.polarite("nonfarm-payrolls") == 1
    assert bs.polarite("employment-change") == 1
    assert bs.polarite("gdp") == 1
    assert bs.polarite("retail-sales") == 1
    assert bs.polarite("cpi") == 1
    assert bs.polarite("core-cpi") == 1
    assert bs.polarite("unemployment-rate") == -1
    assert bs.polarite("unemployment-claims") == -1


def test_un_code_INCONNU_est_ECARTE_et_non_devine():
    """⛔ La declaration dit « tout event_code absent de cette table est
    ecarte ». Deviner une polarite serait ajouter un degre de liberte apres
    coup."""
    assert bs.polarite("4-week-bill-auction") is None
    assert bs.polarite("new-years-day") is None
    assert bs.polarite("") is None
    assert bs.polarite(None) is None


def test_la_correspondance_se_fait_par_PREFIXE():
    """Les codes du terminal portent des suffixes de pays ou de variante."""
    assert bs.polarite("employment-change-s-a") == 1
    assert bs.polarite("unemployment-rate-u6") == -1


def test_adp_n_est_PAS_du_nonfarm_payrolls():
    """⚠️ `adp-nonfarm-employment-change` commence par `adp`, pas par
    `nonfarm-payrolls`. Et c'est justement la ligne dont la declaration dit
    qu'elle porte une prevision aberrante (-663 pour un consensus de +400).
    Un prefixe trop laxiste la ferait entrer."""
    assert bs.polarite("adp-nonfarm-employment-change") is None


# ─── La surprise : normalisee sur le PASSE seulement ────────────────────────

def test_sigma_n_utilise_QUE_les_occurrences_anterieures():
    """⛔ Le regard vers l'avenir est l'erreur qui fabrique des edges."""
    passees = [1.0, -1.0] * 8          # 16 occurrences, ecart-type connu
    s = bs.surprise_normalisee(2.0, passees)
    assert s is not None
    assert s == pytest.approx(2.0 / bs._ecart_type(passees), rel=1e-9)


def test_moins_de_12_occurrences_rend_None():
    """La declaration exige AU MOINS 12. Onze ne suffit pas, et on n'estime
    pas : on ecarte."""
    assert bs.surprise_normalisee(2.0, [1.0, -1.0] * 5 + [1.0]) is None
    assert bs.surprise_normalisee(2.0, []) is None


def test_un_ecart_type_NUL_rend_None():
    """Douze fois la meme valeur ⇒ division par zero. On ecarte."""
    assert bs.surprise_normalisee(2.0, [3.0] * 14) is None


def test_une_surprise_ABERRANTE_est_ecartee(monkeypatch):
    """⛔ LA GARDE DECLAREE. L'ADP du 2021-11-03 porte `forecast = -663` quand
    le consensus reel etait ~+400. Sans ce seuil, le banc mesurerait des fautes
    de frappe et les prendrait pour des chocs."""
    passees = [1.0, -1.0] * 8
    sigma = bs._ecart_type(passees)
    assert bs.surprise_normalisee(sigma * 9.9, passees) is not None
    assert bs.surprise_normalisee(sigma * 10.1, passees) is None
    assert bs.surprise_normalisee(-sigma * 10.1, passees) is None


def test_le_SEUIL_de_declenchement_est_celui_declare():
    assert bs.SEUIL_S == 1.5
    assert bs.MIN_OCCURRENCES == 12
    assert bs.MAX_S == 10.0


# ─── Le sens : du signe de la surprise vers une paire ───────────────────────

def test_une_devise_de_BASE_donne_le_sens_direct():
    assert bs.sens_pour_paire(+2.0, "EUR", "EUR/USD") == "buy"
    assert bs.sens_pour_paire(-2.0, "EUR", "EUR/USD") == "sell"


def test_une_devise_de_COTATION_inverse_le_sens():
    assert bs.sens_pour_paire(+2.0, "USD", "EUR/USD") == "sell"
    assert bs.sens_pour_paire(-2.0, "USD", "EUR/USD") == "buy"


def test_l_or_et_le_WTI_n_ont_besoin_d_AUCUN_cas_particulier():
    """🔑 La declaration disait « pour l'or, l'argent et le WTI, cotes en
    dollar, une surprise USD s'applique INVERSEE ». C'est exactement la regle
    generique de la devise de cotation : le cas particulier se dissout.
    Dollar fort ⇒ or en baisse."""
    assert bs.sens_pour_paire(+2.0, "USD", "XAU/USD") == "sell"
    assert bs.sens_pour_paire(+2.0, "USD", "WTI/USD") == "sell"
    assert bs.sens_pour_paire(-2.0, "USD", "XAG/USD") == "buy"


def test_une_devise_ABSENTE_de_la_paire_rend_None():
    assert bs.sens_pour_paire(+2.0, "USD", "EUR/GBP") is None
    assert bs.sens_pour_paire(+2.0, "CAD", "EUR/USD") is None


def test_une_surprise_SOUS_LE_SEUIL_ne_declenche_rien():
    assert bs.sens_pour_paire(+1.49, "EUR", "EUR/USD") is None
    assert bs.sens_pour_paire(-1.49, "EUR", "EUR/USD") is None
    assert bs.sens_pour_paire(+1.5, "EUR", "EUR/USD") == "buy"


# ─── L'entree : STRICTEMENT apres l'evenement ───────────────────────────────

def test_l_entree_est_la_1re_bougie_STRICTEMENT_posterieure():
    bougies = [_b(10, 1, 1), _b(11, 2, 2), _b(12, 3, 3)]
    t = datetime(2026, 1, 5, 11, 30, tzinfo=timezone.utc)
    assert bs.entree_apres(bougies, t) == 2           # celle de 12 h


def test_la_bougie_qui_CONTIENT_l_evenement_est_exclue():
    """⛔ L'utiliser serait lire l'avenir : son ouverture precede la
    publication, mais sa cloture la suit."""
    bougies = [_b(10, 1, 1), _b(11, 2, 2), _b(12, 3, 3)]
    t = datetime(2026, 1, 5, 11, 0, tzinfo=timezone.utc)   # pile a l'ouverture
    assert bs.entree_apres(bougies, t) == 2, \
        "la bougie de 11 h contient l'evenement, elle doit etre exclue"


def test_aucune_bougie_posterieure_rend_None():
    bougies = [_b(10, 1, 1), _b(11, 2, 2)]
    t = datetime(2026, 1, 5, 23, 0, tzinfo=timezone.utc)
    assert bs.entree_apres(bougies, t) is None


# ─── Le rendement en R, spread facture ─────────────────────────────────────

def test_un_achat_gagnant_rend_un_R_positif():
    bougies = [_b(h, 100.0, 100.0) for h in range(10)]
    bougies[2] = _b(2, 100.0, 100.0)
    bougies[4] = _b(4, 100.0, 104.0)
    r = bs.rendement_r(bougies, 2, 2, "buy", atr=2.0, spread=0.0)
    assert r == pytest.approx(2.0)          # +4,0 de prix / ATR 2,0


def test_une_VENTE_gagnante_rend_aussi_un_R_positif():
    bougies = [_b(h, 100.0, 100.0) for h in range(10)]
    bougies[4] = _b(4, 100.0, 96.0)
    r = bs.rendement_r(bougies, 2, 2, "sell", atr=2.0, spread=0.0)
    assert r == pytest.approx(2.0)


def test_le_SPREAD_est_facture_et_ampute_le_resultat():
    bougies = [_b(h, 100.0, 100.0) for h in range(10)]
    bougies[4] = _b(4, 100.0, 104.0)
    sans = bs.rendement_r(bougies, 2, 2, "buy", atr=2.0, spread=0.0)
    avec = bs.rendement_r(bougies, 2, 2, "buy", atr=2.0, spread=1.0)
    assert avec == pytest.approx(sans - 0.5)      # 1,0 de spread / ATR 2,0


def test_une_sortie_HORS_des_bougies_rend_None():
    """On n'extrapole pas : un trade dont la sortie manque n'existe pas."""
    bougies = [_b(h, 100.0, 100.0) for h in range(5)]
    assert bs.rendement_r(bougies, 3, 8, "buy", atr=2.0, spread=0.0) is None


def test_un_ATR_nul_rend_None():
    bougies = [_b(h, 100.0, 104.0) for h in range(10)]
    assert bs.rendement_r(bougies, 2, 2, "buy", atr=0.0, spread=0.0) is None


# ─── Le contrôle aléatoire APPARIÉ ─────────────────────────────────────────

def test_le_controle_garde_les_MEMES_instants_et_tire_le_SENS():
    """⛔ Un controle non apparie mesurerait le COUT, pas la direction — c'est
    le `+8,60` retire le 2026-10-01."""
    trades = [{"i": 2, "h": 2, "sens": "buy", "atr": 2.0, "spread": 0.0},
              {"i": 3, "h": 2, "sens": "sell", "atr": 2.0, "spread": 0.0}]
    a = bs.controle_apparie(trades, graine=1)
    b = bs.controle_apparie(trades, graine=1)
    assert [x["i"] for x in a] == [2, 3], "les instants ont bouge"
    assert [x["h"] for x in a] == [2, 2], "les horizons ont bouge"
    assert a == b, "le tirage n'est pas reproductible"
    assert all(x["sens"] in ("buy", "sell") for x in a)


def test_deux_graines_donnent_des_sens_differents():
    trades = [{"i": i, "h": 2, "sens": "buy", "atr": 2.0, "spread": 0.0}
              for i in range(40)]
    a = [x["sens"] for x in bs.controle_apparie(trades, graine=1)]
    b = [x["sens"] for x in bs.controle_apparie(trades, graine=2)]
    assert a != b


# ─── Le verdict : les quatre predictions, appliquees telles quelles ─────────

def test_un_echantillon_trop_PETIT_est_INDECIDABLE_jamais_positif():
    """⛔ P4 : `n >= 200` hors echantillon, sinon INDECIDABLE."""
    v = bs.verdict(r_moyen=+0.5, t_vs_hasard=5.0, n=199, signes_par_horizon=[1, 1, 1, 1])
    assert v["verdict"] == "INDECIDABLE"
    assert "200" in v["motif"]


def test_un_t_SOUS_la_barre_est_refuse():
    v = bs.verdict(r_moyen=+0.5, t_vs_hasard=0.79, n=500, signes_par_horizon=[1, 1, 1, 1])
    assert v["verdict"] == "REFUTE"
    assert "0.798" in v["motif"] or "0,798" in v["motif"]


def test_un_R_NEGATIF_est_refuse_meme_avec_un_bon_t():
    v = bs.verdict(r_moyen=-0.5, t_vs_hasard=5.0, n=500, signes_par_horizon=[-1] * 4)
    assert v["verdict"] == "REFUTE"


def test_un_signe_INSTABLE_est_refuse():
    """⛔ P2 : le signe doit tenir sur au moins 3 des 4 horizons. Un effet reel
    ne change pas de sens entre 2 h et 4 h."""
    v = bs.verdict(r_moyen=+0.5, t_vs_hasard=5.0, n=500, signes_par_horizon=[1, 1, -1, -1])
    assert v["verdict"] == "REFUTE"
    assert "horizon" in v["motif"].lower()


def test_les_quatre_predictions_ensemble_donnent_CANDIDAT():
    v = bs.verdict(r_moyen=+0.05, t_vs_hasard=0.9, n=240, signes_par_horizon=[1, 1, 1, -1])
    assert v["verdict"] == "CANDIDAT"


def test_la_barre_vient_du_laboratoire_et_n_est_pas_recopiee():
    """🔑 On ne redefinit pas le plafond du hasard : on appelle celui du
    laboratoire. Une constante recopiee finit par diverger."""
    from backend.services.laboratoire_or import plafond_hasard
    assert bs.BARRE_UN_TEST == pytest.approx(plafond_hasard(1), abs=1e-9)
