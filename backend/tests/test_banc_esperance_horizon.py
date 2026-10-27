"""Le moteur et les branches du banc d'esperance 1d.

⛔ CE QUI EST EN JEU. Le banc rejoue 272 400 simulations, ce qui interdit
d'appeler `simulate_trade_forward` a chaque fois : la recherche du premier
franchissement est donc vectorisee. Une divergence, meme sur la regle « SL et
TP dans la MEME bougie », deplacerait silencieusement l'esperance -- et c'est
exactement le genre de detail qui decide sur un stop large.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.models.schemas import Candle, TradeDirection
from backend.services.backtest_engine import simulate_trade_forward
from scripts import banc_esperance_horizon as banc

T0 = datetime(2026, 8, 20, tzinfo=timezone.utc)

# Les criteres REELS, lus dans la pre-inscription commitee. Les tests portent
# donc sur ce qui est engage, pas sur des valeurs inventees ici.
CR_1D = banc.Criteres("docs/preinscriptions/2026-10-27-esperance-1d.md")
CR_4H = banc.Criteres("docs/preinscriptions/2026-10-27-esperance-4h.md")


def _bougies(specs: list[tuple[float, float, float]]) -> list[Candle]:
    """`(high, low, close)` par bougie de 5 min, a partir de T0."""
    return [Candle(timestamp=T0 + timedelta(minutes=5 * (i + 1)),
                   open=(h + b) / 2, high=h, low=b, close=cl, volume=0)
            for i, (h, b, cl) in enumerate(specs)]


class _Stub:
    def __init__(self, achat, entry, sl, tp, pair="EUR/USD"):
        self.pair = pair
        self.direction = TradeDirection.BUY if achat else TradeDirection.SELL
        self.entry_price = entry
        self.stop_loss = sl
        self.take_profit_1 = tp


def _les_deux(bougies, achat, entry, sl, tp, heures=240):
    """Rend (issue_production, issue_vectorisee) pour comparaison."""
    prod = simulate_trade_forward(_Stub(achat, entry, sl, tp), bougies, T0,
                                  timeout_hours=heures)
    s = banc.Serie(bougies)
    vect = s.simule(s.index_apres(T0.timestamp()),
                    T0.timestamp() + heures * 3600, achat, sl, tp)
    return prod[0], (vect[0] if vect else None)


# ─── Le moteur vectorise contre la production ───────────────────────────────


def test_un_TP_touche_donne_TP1_dans_les_deux_moteurs():
    b = _bougies([(100.5, 99.5, 100.0), (102.0, 99.8, 101.5)])
    prod, vect = _les_deux(b, True, 100.0, 95.0, 101.0)
    assert prod == vect == "TP1", (prod, vect)


def test_un_SL_touche_donne_SL_dans_les_deux_moteurs():
    b = _bougies([(100.5, 99.5, 100.0), (100.2, 94.0, 94.5)])
    prod, vect = _les_deux(b, True, 100.0, 95.0, 110.0)
    assert prod == vect == "SL", (prod, vect)


def test_LA_REGLE_QUI_COMPTE_le_SL_gagne_dans_la_MEME_bougie():
    """⛔ Une bougie qui touche les DEUX bornes : la production prend le SL
    (pire cas). Un moteur qui prendrait le TP surestimerait l'esperance."""
    b = _bougies([(111.0, 94.0, 100.0)])
    prod, vect = _les_deux(b, True, 100.0, 95.0, 110.0)
    assert prod == "SL", prod
    assert vect == "SL", "le moteur vectorise doit AUSSI prendre le pire cas"


def test_la_meme_regle_a_la_VENTE():
    b = _bougies([(106.0, 89.0, 100.0)])
    prod, vect = _les_deux(b, False, 100.0, 105.0, 90.0)
    assert prod == vect == "SL", (prod, vect)


def test_aucune_borne_touchee_donne_TIMEOUT_dans_les_deux():
    b = _bougies([(100.5, 99.5, 100.0)] * 5)
    prod, vect = _les_deux(b, True, 100.0, 90.0, 110.0)
    assert prod == vect == "TIMEOUT", (prod, vect)


def test_une_bougie_HORS_FENETRE_est_ignoree_par_les_deux():
    """La borne est franchie APRES l'echeance : ce n'est pas un hit."""
    b = [Candle(timestamp=T0 + timedelta(hours=250), open=100, high=120,
                low=99, close=119, volume=0)]
    prod, vect = _les_deux(b, True, 100.0, 95.0, 110.0, heures=240)
    assert prod == "TIMEOUT"
    assert vect is None or vect == "TIMEOUT", vect


def test_une_bougie_AVANT_l_entree_ne_compte_pas():
    avant = Candle(timestamp=T0 - timedelta(minutes=5), open=100, high=120,
                   low=99, close=119, volume=0)
    b = [avant] + _bougies([(100.5, 99.5, 100.0)])
    prod, vect = _les_deux(b, True, 100.0, 95.0, 110.0)
    assert prod == vect == "TIMEOUT", (prod, vect)


def test_le_TP_avant_le_SL_donne_bien_TP1():
    b = _bougies([(111.0, 99.0, 110.5), (100.0, 94.0, 94.5)])
    prod, vect = _les_deux(b, True, 100.0, 95.0, 110.0)
    assert prod == vect == "TP1", (prod, vect)


# ─── Les statistiques ───────────────────────────────────────────────────────


def test_l_esperance_est_la_moyenne_des_R():
    # pnl 1,8 % sur un risque de 1 % => +1,8 R ; -1 % => -1 R
    assert banc.esperance_R([(1.8, 1.0), (-1.0, 1.0)]) == pytest.approx(0.4)


def test_un_risque_NUL_est_ecarte_et_ne_divise_pas():
    assert banc.esperance_R([(1.8, 0.0)]) is None
    assert banc.esperance_R([(1.8, 1.0), (5.0, 0.0)]) == pytest.approx(1.8)


def test_une_population_vide_rend_None():
    assert banc.esperance_R([]) is None


def test_le_t_contre_placebo_a_la_bonne_echelle():
    tirages = [0.0, 0.0, 0.1, -0.1]  # moyenne 0, ecart-type connu
    import statistics
    attendu = (0.5 - 0.0) / statistics.stdev(tirages)
    assert banc.t_contre_placebo(0.5, tirages) == pytest.approx(attendu)


def test_moins_de_DEUX_tirages_rend_None_et_pas_zero():
    """⛔ Rendre 0,0 ferait passer une absence de reference pour une egalite."""
    assert banc.t_contre_placebo(0.5, []) is None
    assert banc.t_contre_placebo(0.5, [0.1]) is None


def test_une_dispersion_NULLE_rend_None():
    assert banc.t_contre_placebo(0.5, [0.2, 0.2, 0.2]) is None


def test_la_part_de_tirages_battus():
    assert banc.part_battus_pct(0.5, [0.1, 0.2, 0.9, 1.0]) == pytest.approx(50.0)
    assert banc.part_battus_pct(0.5, []) is None


# ─── Les branches : c'est elles qui publient ────────────────────────────────


def test_la_VALIDITE_passe_avant_tout():
    assert banc.branche(1.0, 0.0, 9.0, 100.0, 0.002, valide=False, cr=CR_1D) \
        == "NON_CONCLUANT_VALIDITE"


def test_reel_et_placebo_INDISCERNABLES_rendent_INDECIDABLE():
    assert banc.branche(-0.001, -0.005, 0.3, 50.0, 0.002, valide=True, cr=CR_1D) \
        == "INDECIDABLE_REEL_ET_PLACEBO_INDISCERNABLES"


def test_l_ADMISSION_exige_les_TROIS_conditions():
    assert banc.branche(0.30, 0.00, 3.0, 99.0, 0.002, valide=True, cr=CR_1D) \
        == "ADMISSION_information_a_l_entree_1d"
    # t insuffisant
    assert banc.branche(0.30, 0.00, 1.0, 99.0, 0.002, valide=True, cr=CR_1D) \
        != "ADMISSION_information_a_l_entree_1d"
    # tirages battus insuffisants
    assert banc.branche(0.30, 0.00, 3.0, 80.0, 0.002, valide=True, cr=CR_1D) \
        != "ADMISSION_information_a_l_entree_1d"
    # sous le cout
    assert banc.branche(0.001, 0.00, 3.0, 99.0, 0.002, valide=True, cr=CR_1D) \
        != "ADMISSION_information_a_l_entree_1d"


def test_le_REJET_exige_une_esperance_NEGATIVE_et_un_t_faible():
    assert banc.branche(-0.20, 0.00, -1.0, 10.0, 0.002, valide=True, cr=CR_1D) \
        == "REJET_horizon_1d_ECARTE"


def test_une_esperance_positive_SANS_le_t_n_est_ni_l_un_ni_l_autre():
    """⛔ Le piege : publier une admission sur le seul signe de l'esperance."""
    assert banc.branche(0.30, 0.00, 1.0, 60.0, 0.002, valide=True, cr=CR_1D) \
        == "NON_CONCLUANT_BRANCHES_EN_DESACCORD"


# ─── Les seuils viennent du fichier PRE-INSCRIT ─────────────────────────────


def test_les_criteres_sont_LUS_et_differents_selon_le_fichier():
    """⛔ CE QUI REMPLACE LE TEST DES SEUILS RECOPIES.

    Le banc ne porte plus aucun seuil de decision : il les LIT. Deux criteres
    engagent des valeurs differentes, et le banc doit servir les deux sans
    qu une seule constante traine dans le code.
    """
    assert CR_1D.horizon == "1d" and CR_1D.fenetre_h == 240
    assert CR_4H.horizon == "4h" and CR_4H.fenetre_h == 96
    assert CR_1D.n_min == 1000 and CR_4H.n_min == 1500
    assert CR_1D.ecart_risk_max == 1.0 and CR_4H.ecart_risk_max == 0.05
    assert CR_1D.t_min == CR_4H.t_min == 2.00


def test_les_DEUX_abs_de_la_clause_indecidable_ne_se_COLLISIONNENT_pas():
    """⛔ BUG TROUVE DANS MON PROPRE LECTEUR.

    `abs(esperance_reel - esperance_placebo) < 0,01 ET abs(t) < 2,00` : une cle
    unique « abs » faisait ecraser 0,01 par 2,00. C est exactement la liaison
    silencieuse que ce lecteur existe pour empecher.
    """
    d = banc.seuils_par_champ(
        "abs(esperance_R_reel - esperance_R_placebo) < 0.01"
        " ET abs(t_contre_placebo) < 2.00")
    assert d == {"abs:esperance_R_reel": 0.01, "abs:t_contre_placebo": 2.0}
    assert CR_1D.indecidable_ecart == 0.01, "et pas 2,00"


def test_un_seuil_ABSENT_du_bloc_est_un_ARRET_et_pas_un_defaut(tmp_path):
    """🔑 Retomber sur une valeur de secours ferait mesurer autre chose que
    ce qui a ete souscrit."""
    ENTETE = "# critere"
    CLAUSES = [
        "<!-- CRITERE-MACHINE",
        "horizon: 4h",
        "fenetre_heures: 96",
        "tirages_placebo: 200",
        # ⛔ la clause `abs(...)` du risque MANQUE volontairement
        "validite: n_reel >= 1500 ET couverture_bougies_pct > 99"
        " ET tirages_aboutis >= 190",
        "admission: t_contre_placebo > 2.00 ET tirages_battus_pct >= 95.0",
        "indecidable: abs(esperance_R_reel - esperance_R_placebo) < 0.01",
        "P1_esperance_R_reel_attendue_max: 0.0",
        "-->",
    ]
    f = tmp_path / "ampute.md"
    f.write_text(ENTETE + chr(10) + chr(10) + chr(10).join(CLAUSES) + chr(10),
                 encoding="utf-8")

    with pytest.raises(SystemExit) as e:
        banc.Criteres(str(f))

    assert "abs:risk_pct_median_placebo" in str(e.value), str(e.value)


def test_une_PREDICTION_inconnue_est_un_ARRET():
    """⛔ Une prediction inscrite mais NON NOTEE serait un critere applique en
    PARTIE, sans que rien ne le dise."""
    class _Faux:
        predictions = {"P9_quelque_chose_de_neuf": 1.0}

    with pytest.raises(SystemExit) as e:
        banc.noter_predictions(_Faux(), {})

    assert "P9_quelque_chose_de_neuf" in str(e.value)
    assert "EN PARTIE" in str(e.value)


def test_les_P4_DIFFERENTS_des_deux_criteres_sont_tous_deux_notes():
    """Le 1d predit sur les TIMEOUT, le 4h sur le COUT. Les deux doivent etre
    notables par la meme table."""
    mesures = {"esperance_R_reel": -0.06, "esperance_R_placebo": 0.04,
               "tirages_battus_pct": 0.0, "esperance_R_timeout": 0.055,
               "cout_R_median": 0.0537, "ecart_esperance_B_moins_A": -0.10}
    n1 = banc.noter_predictions(CR_1D, mesures)
    n4 = banc.noter_predictions(CR_4H, mesures)
    assert "P4_esperance_R_timeout_abs_max" in n1
    assert "P4_cout_R_median_min" in n4
    assert all(d["passe"] for d in n1.values()), n1
    assert all(d["passe"] for d in n4.values()), n4


# ─── Le point d'ENTREE, que rien n'exercait ─────────────────────────────────
#
# ⛔ LE TROU QUE CES TESTS FERMENT. Le 2026-10-27, un `logging.basicConfig`
# ajoute sans `import logging` a fait planter le banc en production -- apres
# que `py_compile` ET les 21 tests soient passes. Les tests ne couvraient que
# les fonctions PURES : `mesure()` et `main()` n'etaient jamais appeles, donc
# une NameError dans l'un ou l'autre restait invisible.
#
# 🔑 C'est la deuxieme fois le meme jour (apres `os` contre `_os` dans
# `pair_admission_controller`) : une NameError n'est pas une erreur de syntaxe,
# et un module qui compile n'a pas prouve qu'il TOURNE.


def test_mesure_sur_une_base_VIDE_ne_leve_pas(tmp_path):
    """Exerce `lire_reels` et le premier jalon de journal."""
    import sqlite3

    db = tmp_path / "vide.db"
    with sqlite3.connect(db) as c:
        c.execute("""
            CREATE TABLE shadow_setups (
                id INTEGER PRIMARY KEY, pair TEXT, bar_timestamp TIMESTAMP,
                timeframe TEXT, direction TEXT, entry_price REAL,
                stop_loss REAL, take_profit_1 REAL, outcome TEXT,
                pnl_pct_net REAL, resolved_backfill INTEGER DEFAULT 0)""")

    r = banc.mesure(str(db), CR_1D)

    assert r.get("erreur"), r
    assert "aucun setup" in r["erreur"]


def test_le_rapport_d_ERREUR_s_imprime_sans_lever():
    """`rapport()` doit savoir rendre un arret, pas seulement un succes."""
    texte = banc.rapport({"erreur": "LE MOTEUR DIVERGE", "accord": 5,
                          "essais": 7, "consigne": "le banc s'arrete"})

    assert "LE MOTEUR DIVERGE" in texte
    assert "5" in texte and "7" in texte


def test_main_configure_le_JOURNAL_sans_NameError(tmp_path, monkeypatch, capsys):
    """⛔ LE TEST QUI AURAIT ATTRAPE LE DEFAUT. Appelle `main()` pour de vrai."""
    import sqlite3

    db = tmp_path / "vide2.db"
    with sqlite3.connect(db) as c:
        c.execute("""
            CREATE TABLE shadow_setups (
                id INTEGER PRIMARY KEY, pair TEXT, bar_timestamp TIMESTAMP,
                timeframe TEXT, direction TEXT, entry_price REAL,
                stop_loss REAL, take_profit_1 REAL, outcome TEXT,
                pnl_pct_net REAL, resolved_backfill INTEGER DEFAULT 0)""")

    code = banc.main(["--db", str(db), "--preinscription",
                      "docs/preinscriptions/2026-10-27-esperance-1d.md"])

    assert code == 1, "une base vide est un ARRET, donc code 1"
    assert "ARRET" in capsys.readouterr().out


def test_le_RAPPORT_ne_lit_aucune_cle_que_le_RESULTAT_n_ecrit_pas():
    """⛔ LE TEST QUI AURAIT SAUVE DOUZE MINUTES DE MESURE.

    Le 2026-10-27, `rapport()` lisait `r['validite_n_min']` que le dict de
    resultat n'ecrivait pas : `KeyError` apres douze minutes de chargement et
    200 tirages, et -- le JSON etant ecrit APRES le rapport a l'epoque -- la
    mesure entiere a ete perdue.

    🔑 Ce test est STATIQUE : il compare les cles LUES par `rapport()` aux cles
    ECRITES par `mesure()`, sans avoir besoin de la moindre bougie. C'est
    exactement le genre de verification qu'un banc long merite, parce qu'y
    echouer coute une mesure entiere.
    """
    import inspect
    import re

    src_mesure = inspect.getsource(banc.mesure)
    src_rapport = inspect.getsource(banc.rapport)

    ecrites = set(re.findall(r'^\s+"([a-zA-Z_][a-zA-Z0-9_]*)":',
                             src_mesure, re.M))
    ecrites |= set(re.findall(r'resultat\["([a-zA-Z_][a-zA-Z0-9_]*)"\]',
                              src_mesure))
    lues = set(re.findall(r"""r\[['"]([a-zA-Z_][a-zA-Z0-9_]*)['"]\]""",
                          src_rapport))
    lues |= set(re.findall(r"""r\.get\(['"]([a-zA-Z_][a-zA-Z0-9_]*)['"]""",
                           src_rapport))

    # `erreur`, `accord`, `essais`, `consigne` appartiennent a la branche
    # d'ARRET, construite ailleurs : elles sont legitimement absentes.
    BRANCHE_ARRET = {"erreur", "accord", "essais", "consigne"}
    manquantes = sorted(lues - ecrites - BRANCHE_ARRET)

    assert not manquantes, (
        "rapport() lit des cles que mesure() n'ecrit pas : %s" % manquantes)


def test_le_VERDICT_nomme_l_horizon_MESURE():
    """⛔ DEFAUT REEL DU 2026-10-27. Le banc 4h a rendu
    « REJET_horizon_1d_ECARTE » et un titre « horizon 1d » : un verdict qui
    nomme le mauvais horizon empoisonne le dossier, et rien ne l'aurait
    signale.
    """
    v4 = banc.branche(-0.27, -0.24, -0.98, 13.0, 0.0537, valide=True, cr=CR_4H)
    v1 = banc.branche(-0.06, 0.04, -4.23, 0.0, 0.0021, valide=True, cr=CR_1D)

    assert "4h" in v4 and "1d" not in v4, v4
    assert "1d" in v1 and "4h" not in v1, v1


def test_le_TITRE_du_rapport_nomme_l_horizon_du_resultat():
    titre = banc.rapport({"erreur": "x"})  # branche d'arret, pas de titre
    assert "ARRET" in titre

    complet = {"horizon": "4h", "n": 1, "n_reel_total": 1,
               "couverture_bougies_pct": 100.0, "controle_moteur_accord": 1,
               "controle_moteur_essais": 1, "validite_n_min": 1,
               "risk_pct_median_reel": 0.37, "risk_pct_median_placebo": 0.37,
               "tirages_aboutis": 200, "tirages_demandes": 200, "valide": True,
               "esperance_R_reel": -0.27, "esperance_R_placebo": -0.24,
               "esperance_R_convention_B": -0.47, "esperance_R_timeout": 0.17,
               "cout_R_median": 0.0537, "predictions": {},
               "t_contre_placebo": -0.98, "tirages_battus_pct": 13.0,
               "ecart_esperance_B_moins_A": -0.20, "graine": 1,
               "commit_preinscription": "x", "verdict": "REJET_horizon_4h_ECARTE"}

    texte = banc.rapport(complet)

    assert "horizon 4h" in texte, texte[:200]
    assert "horizon 1d" not in texte
