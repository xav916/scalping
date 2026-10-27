"""Tests du banc d ANTI-CORRELATION des jambes.

Le test central est un **controle de provenance** : `r_par_setup` recalcule
setup par setup ce que `banc_placebo_structure._esperance_d_un_tirage` rend en
moyenne. Les deux doivent coincider exactement -- sinon j aurais deux sources
de verite pour la meme quantite, la faute du 27/10 transposee du DONNEES au
CODE.
"""
from __future__ import annotations

import math
import pathlib
import random
import sqlite3
import sys
from collections import namedtuple
from datetime import datetime, timedelta, timezone

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))

from scripts import banc_anticorrelation_jambes as baj  # noqa: E402
from scripts import banc_placebo_structure as bps  # noqa: E402
from scripts.banc_esperance_horizon import Serie  # noqa: E402

T0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
C = namedtuple("C", "timestamp open high low close")


def _serie(n=4000, pas_s=300):
    b = []
    for i in range(n):
        p = 100.0 + (i % 400) * 0.02 - (i % 37) * 0.01
        b.append(C(T0 - timedelta(hours=2) + timedelta(seconds=i * pas_s),
                   p, p * 1.002, p * 0.998, p))
    return Serie(b)


def _setups(n_groupes=20, par_groupe=2, paire="BTC/USD"):
    out = []
    for g in range(n_groupes):
        bar = T0 + timedelta(hours=g)
        for k in range(par_groupe):
            achat = k % 2 == 0
            # ⛔ `risk_pct` VARIABLE : a 1,0 partout, diviser par lui ou
            # non ne change RIEN, et le controle de provenance passait meme
            # sans la division (prouve par mutation). Fixture degeneree.
            rp = 0.5 + 0.25 * ((g + k) % 4)
            out.append({"pair": paire, "bar": bar, "achat": achat,
                        "entry": 100.0,
                        "sl": 100.0 - rp if achat else 100.0 + rp,
                        "tp": 100.0 + 1.8 * rp if achat else 100.0 - 1.8 * rp,
                        "issue": "TP1", "pnl": 0.5, "risk_pct": rp})
    return out


def _bornes(couverts):
    b = {}
    for d in couverts:
        mn, mx = b.get(d["pair"], (d["bar"], d["bar"]))
        b[d["pair"]] = (min(mn, d["bar"]), max(mx, d["bar"]))
    return b


# ─── LE CONTROLE DE PROVENANCE ──────────────────────────────────────────────


def test_r_par_setup_reproduit_EXACTEMENT_l_esperance_importee():
    """🔑 DEUX IMPLEMENTATIONS D UNE MEME QUANTITE DOIVENT COINCIDER.

    `_esperance_d_un_tirage` (importee, celle qui a produit `2613282`) rend la
    moyenne ; `r_par_setup` rend le detail. La moyenne du detail doit egaler la
    moyenne importee, sinon ce banc mesure autre chose que celui qu il explique.
    """
    couverts = _setups(20, 2)
    series = {"BTC/USD": _serie()}
    inst = bps.instants_tires("RESEAU_ET_PAIRES", couverts,
                              _bornes(couverts), random.Random(42))

    esp_importee, _ = bps._esperance_d_un_tirage(couverts, series, inst, 96)
    detail = [x[1] for x in baj.r_par_setup(couverts, series, inst, 96)
              if x is not None]

    assert esp_importee == pytest.approx(sum(detail) / len(detail), rel=1e-12)


def test_r_par_setup_rend_aussi_l_ISSUE_et_l_indice():
    couverts = _setups(5, 2)
    series = {"BTC/USD": _serie()}
    inst = [d["bar"].timestamp() for d in couverts]

    rs = baj.r_par_setup(couverts, series, inst, 96)

    assert len(rs) == len(couverts)
    for i, x in enumerate(rs):
        if x is not None:
            assert x[0] == i
            assert x[2] in ("TP1", "SL", "TIMEOUT")


# ─── les duos ───────────────────────────────────────────────────────────────


def test_les_duos_sont_les_groupes_de_DEUX_exactement():
    couverts = _setups(3, 2) + _setups(2, 1, "ETH/USD")

    d = baj.duos(couverts)

    assert len(d) == 3
    for ia, ib in d:
        assert couverts[ia]["bar"] == couverts[ib]["bar"]
        assert couverts[ia]["pair"] == couverts[ib]["pair"]


def test_un_groupe_de_TROIS_est_IGNORE():
    """⛔ La formule pre-inscrite ne couvre que `2D + S = N`."""
    couverts = _setups(1, 3)

    assert baj.duos(couverts) == []


def test_les_duos_distinguent_les_PAIRES():
    couverts = _setups(2, 1, "BTC/USD") + _setups(2, 1, "ETH/USD")

    assert baj.duos(couverts) == []


# ─── la correlation INTRA-CLASSE ────────────────────────────────────────────


def test_rho_vaut_MOINS_UN_sur_des_jambes_parfaitement_opposees():
    a = baj.Accumulateur()
    for x in (1.0, 2.0, 3.0, 4.0):
        a.ajoute(x, -x, "TP1", "SL")

    assert a.rho() == pytest.approx(-1.0, abs=1e-9)


def test_rho_vaut_PLUS_UN_sur_des_jambes_identiques():
    a = baj.Accumulateur()
    for x in (1.0, 2.0, 3.0, 4.0):
        a.ajoute(x, x, "TP1", "TP1")

    assert a.rho() == pytest.approx(1.0, abs=1e-9)


def test_rho_est_SYMETRIQUE_et_ne_depend_pas_de_l_ordre_des_jambes():
    """⛔ L ordre des deux jambes vient de l ordre de lecture en base : une
    correlation qui en dependrait mesurerait un artefact."""
    couples = [(1.0, -0.5), (2.0, -1.0), (-1.0, 0.3), (0.5, 0.1)]
    a, b = baj.Accumulateur(), baj.Accumulateur()
    for x, y in couples:
        a.ajoute(x, y, "TP1", "SL")
    for x, y in couples:
        b.ajoute(y, x, "SL", "TP1")   # ordre inverse

    assert a.rho() == pytest.approx(b.rho(), abs=1e-12)


def test_rho_est_NUL_sur_des_jambes_independantes():
    """⛔ CONTROLE NEGATIF : sans anti-correlation, rho doit etre ~ 0."""
    alea = random.Random(1)
    a = baj.Accumulateur()
    for _ in range(20000):
        a.ajoute(alea.gauss(0, 1), alea.gauss(0, 1), "TP1", "TP1")

    assert abs(a.rho()) < 0.03


def test_rho_est_INDEFINI_sous_deux_observations():
    assert baj.Accumulateur().rho() is None
    a = baj.Accumulateur()
    a.ajoute(1.0, 1.0, "TP1", "TP1")
    assert a.rho() is None


def test_la_part_un_TP_un_SL_compte_les_couples_MIXTES_seulement():
    a = baj.Accumulateur()
    a.ajoute(1.0, -1.0, "TP1", "SL")
    a.ajoute(1.0, -1.0, "SL", "TP1")
    a.ajoute(1.0, -1.0, "SL", "SL")
    a.ajoute(1.0, -1.0, "TIMEOUT", "TP1")

    assert a.part_un_tp_un_sl_pct() == pytest.approx(50.0)


# ─── la formule de variance, verifiee sur de l artificiel ───────────────────


def test_la_formule_de_variance_predit_la_baisse_sur_un_cas_SIMULE():
    """🔑 LA FORMULE ELLE-MEME, eprouvee hors de la donnee reelle.

    On fabrique N tirages de jambes anti-correlees de correlation connue, on
    mesure l ecart-type de la moyenne avec et sans appariement, et on verifie
    que `sqrt(1 + (2D/N) rho)` rend le rapport observe.
    """
    alea = random.Random(7)
    D, S, tirages = 400, 100, 4000
    N = 2 * D + S
    rho_vrai = -0.5
    c = math.sqrt(1 - rho_vrai * rho_vrai)
    apparie, libre = [], []
    for _ in range(tirages):
        sa = []
        for _ in range(D):
            x = alea.gauss(0, 1)
            y = rho_vrai * x + c * alea.gauss(0, 1)
            sa += [x, y]
        sa += [alea.gauss(0, 1) for _ in range(S)]
        apparie.append(sum(sa) / N)
        libre.append(sum(alea.gauss(0, 1) for _ in range(N)) / N)

    import statistics
    rapport = statistics.stdev(apparie) / statistics.stdev(libre)
    attendu = math.sqrt(1 + (2 * D / N) * rho_vrai)

    assert rapport == pytest.approx(attendu, rel=0.05)


# ─── le critere ─────────────────────────────────────────────────────────────


def _critere(tmp_path, **surcharges):
    champs = {
        "forme": "placebo", "horizon": "5min", "fenetre_heures": "96",
        "source_bras_reel": "RECALCULE",
        "placebo_schemas": "RESEAU,RESEAU_ET_PAIRES",
        "placebo_decisif": "RESEAU_ET_PAIRES",
        "population": "resolved_backfill=0 AND timeframe=5min",
        "tirages_placebo": "4", "graine": "20261027",
        "reference_ecart_reseau": "0.091961",
        "reference_ecart_reseau_et_paires": "0.090488",
        "P1_rho_placebo_max": "-0.30",
    }
    champs.update(surcharges)
    champs = {k: v for k, v in champs.items() if v is not None}
    p = tmp_path / "c.md"
    p.write_text("# c\n\n<!-- CRITERE-MACHINE\n"
                 + "\n".join(f"{k}: {v}" for k, v in champs.items())
                 + "\n-->\n", encoding="utf-8")
    return str(p)


def test_un_critere_STOCKE_est_REFUSE(tmp_path):
    with pytest.raises(SystemExit) as e:
        baj.Criteres(_critere(tmp_path, source_bras_reel="STOCKE"))
    assert "RECALCULE" in str(e.value)


def test_l_ORDRE_des_deux_schemas_est_EXIGE(tmp_path):
    """⛔ Le premier barreau est la BASE de variance, le second celui dont on
    explique la baisse. Les inverser retournerait la formule."""
    with pytest.raises(SystemExit) as e:
        baj.Criteres(_critere(tmp_path,
                              placebo_schemas="RESEAU_ET_PAIRES,RESEAU"))
    assert "EXACTEMENT" in str(e.value)


def test_un_critere_SANS_reference_de_reproduction_est_un_ARRET(tmp_path):
    with pytest.raises(SystemExit) as e:
        baj.Criteres(_critere(tmp_path, reference_ecart_reseau=None))
    assert "reference_ecart_reseau" in str(e.value)


def test_les_predictions_sont_lues_par_NOM(tmp_path):
    cr = baj.Criteres(_critere(tmp_path))
    assert set(cr.predictions) == {"P1_rho_placebo_max"}


def test_les_cinq_predictions_sont_notables():
    for c in ("P1_rho_placebo_max", "P2_rho_placebo_plancher",
              "P3_ecart_sd_predit_pct_max", "P4_rho_reel_max",
              "P5_part_duos_un_tp_un_sl_pct_min"):
        assert c in baj.PREDICTIONS, c


def test_une_prediction_sur_un_champ_MANQUANT_echoue_sans_lever():
    _, t = baj.PREDICTIONS["P3_ecart_sd_predit_pct_max"]
    assert t({"ecart_sd_predit_pct": None}, 15.0) is False


# ─── bout en bout ───────────────────────────────────────────────────────────


def _base(tmp_path, n_groupes=30):
    p = tmp_path / "t.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE shadow_setups (pair TEXT, bar_timestamp TEXT,"
              " timeframe TEXT, resolved_backfill INT, direction TEXT,"
              " entry_price REAL, stop_loss REAL, take_profit_1 REAL,"
              " outcome TEXT, pnl_pct_net REAL)")
    lignes = []
    for g in range(n_groupes):
        bar = (T0 + timedelta(hours=g)).isoformat()
        for sens in ("buy", "sell"):
            sl = 99.0 if sens == "buy" else 101.0
            tp = 101.8 if sens == "buy" else 98.2
            lignes.append(("BTC/USD", bar, "5min", 0, sens, 100.0, sl, tp,
                           "TP1", 0.5))
    c.executemany("INSERT INTO shadow_setups VALUES (?,?,?,?,?,?,?,?,?,?)",
                  lignes)
    c.commit()
    c.close()
    return str(p)


@pytest.fixture
def moteur_bouchonne(monkeypatch):
    async def _charge(paires, fin=None):
        return {p: _serie() for p in paires}
    monkeypatch.setattr(baj, "charge", _charge)


def test_le_controle_de_reproduction_ARRETE_quand_les_barreaux_divergent(
        tmp_path, moteur_bouchonne):
    """⛔ Les deux passes doivent mesurer la meme chose, sinon le rho d ici ne
    peut pas expliquer l ecart-type de la-bas."""
    cr = baj.Criteres(_critere(tmp_path))

    m = baj.mesure(_base(tmp_path), cr)

    assert "erreur" in m
    assert "NE REPRODUISENT PAS" in m["erreur"]
    # il publie quand meme ce qu il a mesure, pour le diagnostic
    assert m["rho_duos_placebo"] is not None
    assert m["duos"] == 30


def test_main_tourne_VRAIMENT_et_ecrit_son_JSON(tmp_path, moteur_bouchonne):
    """⛔ `py_compile` ne prouve pas qu un module tourne."""
    import json
    db = _base(tmp_path)
    cr0 = baj.Criteres(_critere(tmp_path))
    brut = baj.mesure(db, cr0)

    c = _critere(
        tmp_path,
        reference_ecart_reseau="%.6f" % brut["ecart_signal_reseau"],
        reference_ecart_reseau_et_paires="%.6f"
        % brut["ecart_signal_reseau_et_paires"])
    sortie = tmp_path / "r.json"
    code = baj.main(["--preinscription", c, "--db", db, "--json",
                     str(sortie)])

    assert code == 0
    m = json.loads(sortie.read_text(encoding="utf-8"))
    assert m["n_reel"] == 60 and m["duos"] == 30
    assert m["facteur_2D_sur_N"] == pytest.approx(1.0)
    assert m["rho_duos_placebo"] is not None
    assert m["rho_duos_reel"] is not None
    assert m["observations_rho"] == 30 * 4
    assert m["valide"] is True


def test_le_RAPPORT_ne_lit_aucune_cle_que_le_RESULTAT_n_ecrit_pas(
        tmp_path, moteur_bouchonne):
    db = _base(tmp_path)
    cr0 = baj.Criteres(_critere(tmp_path))
    brut = baj.mesure(db, cr0)
    cr = baj.Criteres(_critere(
        tmp_path,
        reference_ecart_reseau="%.6f" % brut["ecart_signal_reseau"],
        reference_ecart_reseau_et_paires="%.6f"
        % brut["ecart_signal_reseau_et_paires"]))

    texte = baj.rapport(baj.mesure(db, cr))

    assert "rho intra-duo PLACEBO" in texte
    assert "sd nul PREDIT depuis rho" in texte
    assert "VERDICT" in texte


def test_le_resultat_porte_les_CHAMPS_REQUIS_par_or_verdict(
        tmp_path, moteur_bouchonne):
    db = _base(tmp_path)
    cr0 = baj.Criteres(_critere(tmp_path))
    brut = baj.mesure(db, cr0)
    cr = baj.Criteres(_critere(
        tmp_path,
        reference_ecart_reseau="%.6f" % brut["ecart_signal_reseau"],
        reference_ecart_reseau_et_paires="%.6f"
        % brut["ecart_signal_reseau_et_paires"]))

    m = baj.mesure(db, cr)

    for champ in ("n", "t", "valide", "forme"):
        assert champ in m and m[champ] is not None, champ


# ─── la formule de variance, testee pour elle-meme ─────────────────────────


def test_la_formule_sd_predite_applique_bien_le_facteur_2D_sur_N():
    """⛔ TEST AJOUTE APRES MUTATION : remplacer `2D/N` par `D/N` ne faisait
    tomber aucun test. La formule qui porte la prediction decisive doit avoir
    le sien."""
    # N = 100, D = 40 => 2D/N = 0,8 ; rho = -0,5 => facteur 0,6
    v = baj.sd_predite(0.02, -0.5, 40, 100)

    assert v == pytest.approx(0.02 * math.sqrt(0.6), rel=1e-12)
    # un facteur D/N (0,4) donnerait sqrt(0,8) : nettement different
    assert abs(v - 0.02 * math.sqrt(0.8)) > 1e-4


def test_la_formule_sd_predite_est_NEUTRE_a_rho_nul():
    assert baj.sd_predite(0.02, 0.0, 40, 100) == pytest.approx(0.02)


def test_la_formule_sd_predite_rend_NONE_au_MIROIR_PARFAIT():
    """⛔ Mon premier test etait FAUX, et le corriger apprend quelque chose.

    Comme `2D <= N` et `rho >= -1`, le facteur `1 + (2D/N) rho` ne peut valoir
    zero QU AU POINT EXACT ou tous les setups sont apparies (`2D = N`) et les
    deux jambes parfaitement en miroir (`rho = -1`). La garde n est donc
    atteignable qu a cette borne -- ou la variance de la moyenne est
    reellement NULLE, chaque duo rendant toujours la meme somme.
    """
    assert baj.sd_predite(0.02, -1.0, 50, 100) is None      # 2D/N = 1, bord
    assert baj.sd_predite(0.02, -0.99, 50, 100) is not None  # juste au-dessus


def test_la_formule_sd_predite_rend_NONE_sur_une_entree_absente():
    assert baj.sd_predite(None, -0.5, 40, 100) is None
    assert baj.sd_predite(0.02, None, 40, 100) is None
    assert baj.sd_predite(0.02, -0.5, 40, 0) is None
