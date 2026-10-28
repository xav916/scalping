"""Tests du banc des TROIS BRAS."""
from __future__ import annotations

import pathlib
import sqlite3
import sys
from collections import namedtuple
from datetime import datetime, timedelta, timezone

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))

from scripts import banc_trois_bras as btb  # noqa: E402
from scripts.banc_esperance_horizon import Serie  # noqa: E402

T0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
C = namedtuple("C", "timestamp open high low close")


def _serie(n=6000, pas_s=300):
    b = []
    for i in range(n):
        p = 100.0 + (i % 400) * 0.02 - (i % 37) * 0.01
        b.append(C(T0 - timedelta(hours=2) + timedelta(seconds=i * pas_s),
                   p, p * 1.002, p * 0.998, p * 1.0005))
    return Serie(b)


# ─── le bras ISSUE_STOCKEE ne touche PAS aux bougies ────────────────────────


def test_le_bras_ISSUE_STOCKEE_se_calcule_a_la_main():
    """`pnl / risk_pct` moyenne, exactement comme la branche STOCKE du banc
    d esperance."""
    couverts = [{"pnl": 1.0, "risk_pct": 1.0},
                {"pnl": -0.5, "risk_pct": 0.5},
                {"pnl": 0.9, "risk_pct": 0.3}]

    v = btb.esperance_issue_stockee(couverts)

    assert v == pytest.approx((1.0 / 1.0 + -0.5 / 0.5 + 0.9 / 0.3) / 3)


def test_le_bras_ISSUE_STOCKEE_ignore_les_lignes_SANS_pnl():
    couverts = [{"pnl": 1.0, "risk_pct": 1.0}, {"pnl": None, "risk_pct": 1.0},
                {"pnl": 2.0, "risk_pct": 0.0}]

    assert btb.esperance_issue_stockee(couverts) == pytest.approx(1.0)


def test_le_bras_ISSUE_STOCKEE_rend_NONE_quand_rien_n_est_utilisable():
    assert btb.esperance_issue_stockee([{"pnl": None, "risk_pct": 1.0}]) is None


# ─── le critere : les trois bras et leurs ROLES sont EXIGES ─────────────────


def _critere(tmp_path, **surcharges):
    champs = {
        "forme": "placebo", "placebo_schema": "UNIFORME",
        "bras": "ISSUE_STOCKEE,GEOMETRIE_RECALCULEE,FILL_OUVERTURE",
        "bras_reproduction": "ISSUE_STOCKEE",
        "bras_comparable": "GEOMETRIE_RECALCULEE",
        "cellules_horizon": "1d,4h",
        "horizon_1d": "1d",
        "population_1d": "resolved_backfill=1 AND timeframe=1d",
        "fenetre_heures_1d": "240",
        "reference_issue_stockee_1d": "-0.064062",
        "reference_placebo_1d": "0.041348",
        "horizon_4h": "4h",
        "population_4h": "resolved_backfill=1 AND timeframe=4h",
        "fenetre_heures_4h": "96",
        "reference_issue_stockee_4h": "-0.266410",
        "reference_placebo_4h": "-0.244334",
        "tirages_placebo": "3", "graine": "20261027",
        "tolerance_reproduction_pct": "0.5",
        "P1_reproduction_issue_stockee_max_pct": "0.5",
    }
    champs.update(surcharges)
    champs = {k: v for k, v in champs.items() if v is not None}
    p = tmp_path / "c.md"
    p.write_text("# c\n\n<!-- CRITERE-MACHINE\n"
                 + "\n".join(f"{k}: {v}" for k, v in champs.items())
                 + "\n-->\n", encoding="utf-8")
    return str(p)


def test_l_ORDRE_des_trois_bras_est_EXIGE(tmp_path):
    with pytest.raises(SystemExit) as e:
        btb.Criteres(_critere(
            tmp_path,
            bras="GEOMETRIE_RECALCULEE,ISSUE_STOCKEE,FILL_OUVERTURE"))
    assert "EXACTEMENT" in str(e.value)


def test_un_bras_de_REPRODUCTION_autre_est_un_ARRET(tmp_path):
    """⛔ C est la porte qui manquait au banc precedent : seul ISSUE_STOCKEE
    lit les memes lignes que les bancs publies."""
    with pytest.raises(SystemExit) as e:
        btb.Criteres(_critere(tmp_path,
                              bras_reproduction="GEOMETRIE_RECALCULEE"))
    assert "ISSUE_STOCKEE" in str(e.value)


def test_un_bras_COMPARABLE_autre_est_un_ARRET(tmp_path):
    """⛔ Le placebo est SIMULE : seul un bras recalcule partage sa
    provenance."""
    with pytest.raises(SystemExit) as e:
        btb.Criteres(_critere(tmp_path, bras_comparable="ISSUE_STOCKEE"))
    assert "GEOMETRIE_RECALCULEE" in str(e.value)


@pytest.mark.parametrize("manquant", [
    "horizon_1d", "population_1d", "fenetre_heures_1d",
    "reference_issue_stockee_1d", "reference_placebo_1d"])
def test_une_cellule_INCOMPLETE_est_un_ARRET_qui_NOMME_le_champ(tmp_path,
                                                                manquant):
    with pytest.raises(SystemExit) as e:
        btb.Criteres(_critere(tmp_path, **{manquant: None}))
    assert manquant in str(e.value)


def test_les_cinq_predictions_sont_notables():
    for c in ("P1_reproduction_issue_stockee_max_pct",
              "P2_desaccord_1d_pct_plafond", "P3_desaccord_4h_pct_plafond",
              "P4_t_fill_1d_min", "P5_reproduction_placebo_max_pct"):
        assert c in btb.PREDICTIONS, c


def test_les_predictions_de_DESACCORD_lisent_la_CELLULE_nommee():
    _, p2 = btb.PREDICTIONS["P2_desaccord_1d_pct_plafond"]
    _, p3 = btb.PREDICTIONS["P3_desaccord_4h_pct_plafond"]
    m = {"desaccord_pct_1d": 1.2, "desaccord_pct_4h": 9.9}

    assert p2(m, 3.0) is True
    assert p3(m, 0.5) is False


def test_une_prediction_sur_un_champ_MANQUANT_echoue_sans_lever():
    _, t = btb.PREDICTIONS["P4_t_fill_1d_min"]
    assert t({"t_fill_1d": None}, 2.0) is False


# ─── bout en bout ───────────────────────────────────────────────────────────


def _base(tmp_path, n=40):
    p = tmp_path / "t.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE shadow_setups (pair TEXT, bar_timestamp TEXT,"
              " timeframe TEXT, resolved_backfill INT, direction TEXT,"
              " entry_price REAL, stop_loss REAL, take_profit_1 REAL,"
              " outcome TEXT, pnl_pct_net REAL)")
    lignes = []
    for tf in ("1d", "4h"):
        for g in range(n):
            bar = (T0 + timedelta(hours=g)).isoformat()
            for sens in ("buy", "sell"):
                e = 100.0 * 1.02
                sl = e - 1.0 if sens == "buy" else e + 1.0
                tp = e + 1.8 if sens == "buy" else e - 1.8
                # `pnl_pct_net` STOCKE, volontairement different de ce que les
                # bougies donneraient -- c est tout l objet du banc.
                lignes.append(("BTC/USD", bar, tf, 1, sens, e, sl, tp,
                               "TP1", 0.42))
    c.executemany("INSERT INTO shadow_setups VALUES (?,?,?,?,?,?,?,?,?,?)",
                  lignes)
    c.commit()
    c.close()
    return str(p)


@pytest.fixture
def moteur_bouchonne(monkeypatch):
    async def _charge(paires, fin=None):
        return {p: _serie() for p in paires}
    monkeypatch.setattr(btb, "charge", _charge)


def test_la_porte_de_REPRODUCTION_arrete_le_banc(tmp_path, moteur_bouchonne):
    """⛔ LA PORTE QUI MANQUAIT AU BANC PRECEDENT."""
    m = btb.mesure(_base(tmp_path), btb.Criteres(_critere(tmp_path)))

    assert "erreur" in m and "ISSUE_STOCKEE NE REPRODUIT PAS" in m["erreur"]
    # et il publie les trois bras pour le diagnostic
    for nom in ("1d", "4h"):
        for b in ("esperance_issue_stockee", "esperance_geometrie_recalculee",
                  "esperance_fill"):
            assert m[f"{b}_{nom}"] is not None, (b, nom)


def test_les_TROIS_bras_sont_DISTINCTS(tmp_path, moteur_bouchonne):
    """🔑 Si deux bras coincidaient, le banc ne distinguerait rien -- et c est
    precisement la confusion qui a produit la cause fausse de `9d955dc`."""
    m = btb.mesure(_base(tmp_path), btb.Criteres(_critere(tmp_path)))

    a = m["esperance_issue_stockee_1d"]
    b = m["esperance_geometrie_recalculee_1d"]
    c = m["esperance_fill_1d"]
    assert a != b and b != c and a != c


def test_main_tourne_VRAIMENT_et_ecrit_son_JSON(tmp_path, moteur_bouchonne):
    import json
    db = _base(tmp_path)
    brut = btb.mesure(db, btb.Criteres(_critere(tmp_path)))
    c = _critere(
        tmp_path,
        reference_issue_stockee_1d="%.6f" % brut["esperance_issue_stockee_1d"],
        reference_placebo_1d="%.6f" % brut["esperance_placebo_1d"],
        reference_issue_stockee_4h="%.6f" % brut["esperance_issue_stockee_4h"],
        reference_placebo_4h="%.6f" % brut["esperance_placebo_4h"])
    sortie = tmp_path / "r.json"

    code = btb.main(["--preinscription", c, "--db", db, "--json",
                     str(sortie)])

    assert code == 0
    m = json.loads(sortie.read_text(encoding="utf-8"))
    assert m["bras"] == list(btb.BRAS)
    assert m["cellules"] == ["1d", "4h"]
    assert m["reproduction_issue_stockee_max_pct"] < 0.5
    assert m["part_entree_hors_bougie_fill_max_pct"] == 0.0
    assert m["desaccord_pct_1d"] is not None
    assert m["valide"] is True


def test_l_ARTEFACT_vaut_RECALCULEE_moins_FILL(tmp_path, moteur_bouchonne):
    m = btb.mesure(_base(tmp_path), btb.Criteres(_critere(tmp_path)))

    for nom in ("1d", "4h"):
        attendu = (m[f"esperance_geometrie_recalculee_{nom}"]
                   - m[f"esperance_fill_{nom}"])
        assert m[f"artefact_{nom}"] == pytest.approx(attendu, rel=1e-12)


def test_le_RAPPORT_ne_lit_aucune_cle_que_le_RESULTAT_n_ecrit_pas(
        tmp_path, moteur_bouchonne):
    db = _base(tmp_path)
    brut = btb.mesure(db, btb.Criteres(_critere(tmp_path)))
    cr = btb.Criteres(_critere(
        tmp_path,
        reference_issue_stockee_1d="%.6f" % brut["esperance_issue_stockee_1d"],
        reference_placebo_1d="%.6f" % brut["esperance_placebo_1d"],
        reference_issue_stockee_4h="%.6f" % brut["esperance_issue_stockee_4h"],
        reference_placebo_4h="%.6f" % brut["esperance_placebo_4h"]))

    texte = btb.rapport(btb.mesure(db, cr))

    assert "ISSUE_STOCKEE" in texte and "GEOMETRIE_RECALCULEE" in texte
    assert "desaccord stocke/recalcule" in texte
    assert "DIVULGATION" in texte and "VERDICT" in texte


def test_le_resultat_porte_les_CHAMPS_REQUIS_par_or_verdict(
        tmp_path, moteur_bouchonne):
    db = _base(tmp_path)
    brut = btb.mesure(db, btb.Criteres(_critere(tmp_path)))
    cr = btb.Criteres(_critere(
        tmp_path,
        reference_issue_stockee_1d="%.6f" % brut["esperance_issue_stockee_1d"],
        reference_placebo_1d="%.6f" % brut["esperance_placebo_1d"],
        reference_issue_stockee_4h="%.6f" % brut["esperance_issue_stockee_4h"],
        reference_placebo_4h="%.6f" % brut["esperance_placebo_4h"]))

    m = btb.mesure(db, cr)

    for champ in ("n", "t", "valide", "forme"):
        assert champ in m and m[champ] is not None, champ
