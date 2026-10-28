"""Tests du banc du FILL REALISABLE."""
from __future__ import annotations

import pathlib
import random
import sqlite3
import sys
from collections import namedtuple
from datetime import datetime, timedelta, timezone

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))

from scripts import banc_fill_realisable as bfr  # noqa: E402
from scripts.banc_esperance_horizon import Serie  # noqa: E402

T0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
C = namedtuple("C", "timestamp open high low close")


def _serie(n=4000, pas_s=300):
    b = []
    for i in range(n):
        p = 100.0 + (i % 400) * 0.02 - (i % 37) * 0.01
        b.append(C(T0 - timedelta(hours=2) + timedelta(seconds=i * pas_s),
                   p, p * 1.002, p * 0.998, p * 1.0005))
    return Serie(b)


def _setups(n=10, hors_bougie=False):
    """`hors_bougie` place `entry` LOIN de la bougie, comme un niveau de motif
    que le marche n a pas traite."""
    out = []
    for g in range(n):
        bar = T0 + timedelta(hours=g)
        for k in range(2):
            achat = k == 0
            rp = 0.5 + 0.25 * (g % 4)
            e = 100.0 * (1.05 if hors_bougie else 1.0)
            out.append({"pair": "BTC/USD", "bar": bar, "achat": achat,
                        "entry": e,
                        "sl": e - rp if achat else e + rp,
                        "tp": e + 1.8 * rp if achat else e - 1.8 * rp,
                        "issue": "TP1", "pnl": 0.5, "risk_pct": rp})
    return out


# ─── la garde qui prouve que la re-specification agit ───────────────────────


def test_l_entree_a_l_OUVERTURE_est_TOUJOURS_dans_sa_bougie():
    """⛔ C est la garde `part_entree_hors_bougie_fill_pct < 0,5`, et elle doit
    valoir ZERO par construction -- sinon la re-specification est inerte."""
    series = {"BTC/USD": _serie()}
    couverts = _setups(10, hors_bougie=True)

    assert bfr.part_entree_hors_bougie_pct(couverts, series, False) == 0.0


def test_une_entree_STOCKEE_hors_de_sa_bougie_est_COMPTEE():
    series = {"BTC/USD": _serie()}
    s = series["BTC/USD"]
    # ⛔ Les prix synthetiques derivent : une entree a 100,0 n est PAS
    # forcement dans sa bougie. On la prend donc DANS la serie.
    au_marche = _setups(10, False)
    for d in au_marche:
        d["entry"] = float(s.open[s.index_apres(d["bar"].timestamp())])

    dedans = bfr.part_entree_hors_bougie_pct(au_marche, series, True)
    dehors = bfr.part_entree_hors_bougie_pct(_setups(10, True), series, True)

    assert dedans == 0.0
    assert dehors == 100.0


# ─── les taux de premiere bougie ────────────────────────────────────────────


def test_le_taux_de_premiere_bougie_applique_la_regle_SL_GAGNE_LES_EX_AEQUO():
    """⛔ Sans cette regle, ces taux ne decriraient pas ce que le moteur fait.

    Barrieres TRES serrees : la premiere bougie touche les deux, donc tout doit
    compter en SL et rien en TP1.
    """
    series = {"BTC/USD": _serie()}
    couverts = _setups(10, False)
    for d in couverts:
        d["risk_pct"] = 0.0001          # barrieres a l interieur de la bougie

    sl, tp = bfr.taux_premiere_bougie(
        couverts, series, [d["bar"].timestamp() for d in couverts], False)

    assert sl == 100.0 and tp == 0.0


def test_des_barrieres_LARGES_ne_resolvent_PAS_a_la_premiere_bougie():
    series = {"BTC/USD": _serie()}
    couverts = _setups(10, False)
    for d in couverts:
        d["risk_pct"] = 50.0

    sl, tp = bfr.taux_premiere_bougie(
        couverts, series, [d["bar"].timestamp() for d in couverts], False)

    assert sl == 0.0 and tp == 0.0


def test_les_taux_STOCKE_et_FILL_DIFFERENT_quand_l_entree_est_hors_bougie():
    """🔑 Le cœur du banc : c est cette difference que la re-specification
    supprime."""
    series = {"BTC/USD": _serie()}
    couverts = _setups(10, hors_bougie=True)
    inst = [d["bar"].timestamp() for d in couverts]

    a = bfr.taux_premiere_bougie(couverts, series, inst, True)
    b = bfr.taux_premiere_bougie(couverts, series, inst, False)

    assert a != b


# ─── le critere ─────────────────────────────────────────────────────────────


def _critere(tmp_path, **surcharges):
    champs = {
        "forme": "placebo", "horizon": "5min", "fenetre_heures": "96",
        "source_bras_reel": "RECALCULE",
        "cellules_fill": "REF_STOCKE,FILL_OUVERTURE",
        "cellule_decisive": "FILL_OUVERTURE",
        "population": "resolved_backfill=0 AND timeframe=5min",
        "tirages_placebo": "4", "graine": "20261027",
        "reference_esperance_reel_stocke": "-0.059336",
        "reference_ecart_stocke": "0.091961",
        "P2_t_fill_abs_max": "2.00",
    }
    champs.update(surcharges)
    champs = {k: v for k, v in champs.items() if v is not None}
    p = tmp_path / "c.md"
    p.write_text("# c\n\n<!-- CRITERE-MACHINE\n"
                 + "\n".join(f"{k}: {v}" for k, v in champs.items())
                 + "\n-->\n", encoding="utf-8")
    return str(p)


def test_l_ORDRE_des_cellules_est_EXIGE(tmp_path):
    """⛔ La premiere est le controle de reproduction : les inverser ferait
    reproduire le mauvais chiffre."""
    with pytest.raises(SystemExit) as e:
        bfr.Criteres(_critere(tmp_path,
                              cellules_fill="FILL_OUVERTURE,REF_STOCKE"))
    assert "EXACTEMENT" in str(e.value)


def test_une_cellule_decisive_AUTRE_est_un_ARRET(tmp_path):
    with pytest.raises(SystemExit):
        bfr.Criteres(_critere(tmp_path, cellule_decisive="REF_STOCKE"))


def test_un_critere_SANS_reference_de_reproduction_est_un_ARRET(tmp_path):
    with pytest.raises(SystemExit) as e:
        bfr.Criteres(_critere(tmp_path, reference_ecart_stocke=None))
    assert "reference_ecart_stocke" in str(e.value)


def test_un_critere_STOCKE_est_REFUSE(tmp_path):
    with pytest.raises(SystemExit):
        bfr.Criteres(_critere(tmp_path, source_bras_reel="STOCKE"))


def test_les_cinq_predictions_sont_notables():
    for c in ("P1_ecart_signal_fill_max", "P2_t_fill_abs_max",
              "P3_esperance_reel_fill_max",
              "P4_asymetrie_premiere_bougie_pts_max",
              "P5_ecart_signal_fill_plancher"):
        assert c in bfr.PREDICTIONS, c


def test_la_prediction_du_t_porte_sur_la_VALEUR_ABSOLUE():
    _, t = bfr.PREDICTIONS["P2_t_fill_abs_max"]

    assert t({"t_fill": 1.5}, 2.0) is True
    assert t({"t_fill": -1.5}, 2.0) is True
    assert t({"t_fill": -2.5}, 2.0) is False
    assert t({"t_fill": 4.4}, 2.0) is False


def test_une_prediction_sur_un_champ_MANQUANT_echoue_sans_lever():
    _, t = bfr.PREDICTIONS["P2_t_fill_abs_max"]
    assert t({"t_fill": None}, 2.0) is False


# ─── bout en bout ───────────────────────────────────────────────────────────


def _base(tmp_path, n_groupes=30, hors=True):
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
            e = 100.0 * (1.03 if hors else 1.0)
            sl = e - 1.0 if sens == "buy" else e + 1.0
            tp = e + 1.8 if sens == "buy" else e - 1.8
            lignes.append(("BTC/USD", bar, "5min", 0, sens, e, sl, tp,
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
    monkeypatch.setattr(bfr, "charge", _charge)


def test_la_reproduction_ARRETE_quand_REF_STOCKE_ne_colle_pas(
        tmp_path, moteur_bouchonne):
    m = bfr.mesure(_base(tmp_path), bfr.Criteres(_critere(tmp_path)))

    assert "erreur" in m and "NE REPRODUIT PAS" in m["erreur"]
    # et il publie quand meme les deux bras, pour le diagnostic
    assert m["esperance_R_reel_stocke"] != m["esperance_R_reel_fill"]


def test_main_tourne_VRAIMENT_et_ecrit_son_JSON(tmp_path, moteur_bouchonne):
    import json
    db = _base(tmp_path)
    brut = bfr.mesure(db, bfr.Criteres(_critere(tmp_path)))
    c = _critere(
        tmp_path,
        reference_esperance_reel_stocke="%.6f" % brut["esperance_R_reel_stocke"],
        reference_ecart_stocke="%.6f" % brut["ecart_signal_stocke"])
    sortie = tmp_path / "r.json"

    code = bfr.main(["--preinscription", c, "--db", db, "--json",
                     str(sortie)])

    assert code == 0
    m = json.loads(sortie.read_text(encoding="utf-8"))
    assert m["n_reel"] == 60
    assert m["part_entree_hors_bougie_fill_pct"] == 0.0
    assert m["part_entree_hors_bougie_stocke_pct"] > 30.0
    assert m["t_fill"] is not None and m["t_stocke"] is not None
    assert m["valide"] is True


def test_un_SEUL_placebo_sert_aux_DEUX_cellules(tmp_path, moteur_bouchonne):
    """🔑 Le placebo entre deja a l ouverture : il est INCHANGE par la
    re-specification, donc l ecart entre cellules vient du seul bras reel."""
    db = _base(tmp_path)
    m = bfr.mesure(db, bfr.Criteres(_critere(tmp_path)))

    diff_ecarts = m["ecart_signal_stocke"] - m["ecart_signal_fill"]
    diff_reels = m["esperance_R_reel_stocke"] - m["esperance_R_reel_fill"]

    assert diff_ecarts == pytest.approx(diff_reels, rel=1e-12)


def test_le_RAPPORT_ne_lit_aucune_cle_que_le_RESULTAT_n_ecrit_pas(
        tmp_path, moteur_bouchonne):
    db = _base(tmp_path)
    brut = bfr.mesure(db, bfr.Criteres(_critere(tmp_path)))
    cr = bfr.Criteres(_critere(
        tmp_path,
        reference_esperance_reel_stocke="%.6f" % brut["esperance_R_reel_stocke"],
        reference_ecart_stocke="%.6f" % brut["ecart_signal_stocke"]))

    texte = bfr.rapport(bfr.mesure(db, cr))

    assert "FILL OUVERTURE" in texte and "des la 1re bougie" in texte
    assert "DIVULGATION" in texte and "VERDICT" in texte


def test_le_resultat_porte_les_CHAMPS_REQUIS_par_or_verdict(
        tmp_path, moteur_bouchonne):
    db = _base(tmp_path)
    brut = bfr.mesure(db, bfr.Criteres(_critere(tmp_path)))
    cr = bfr.Criteres(_critere(
        tmp_path,
        reference_esperance_reel_stocke="%.6f" % brut["esperance_R_reel_stocke"],
        reference_ecart_stocke="%.6f" % brut["ecart_signal_stocke"]))

    m = bfr.mesure(db, cr)

    for champ in ("n", "t", "valide", "forme"):
        assert champ in m and m[champ] is not None, champ
