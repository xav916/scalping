"""Tests du banc de DECOMPOSITION par horizon."""
from __future__ import annotations

import pathlib
import sqlite3
import sys
from collections import namedtuple
from datetime import datetime, timedelta, timezone

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))

from scripts import banc_decomposition_horizons as bdh  # noqa: E402
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


def _critere(tmp_path, **surcharges):
    champs = {
        "forme": "placebo", "placebo_schema": "UNIFORME",
        "cellules_horizon": "1d,4h",
        "horizon_1d": "1d",
        "population_1d": "resolved_backfill=1 AND timeframe=1d",
        "fenetre_heures_1d": "240",
        "reference_esperance_reel_1d": "-0.064062",
        "reference_ecart_1d": "-0.105410",
        "horizon_4h": "4h",
        "population_4h": "resolved_backfill=1 AND timeframe=4h",
        "fenetre_heures_4h": "96",
        "reference_esperance_reel_4h": "-0.266410",
        "reference_ecart_4h": "-0.022076",
        "artefact_5min_mesure": "0.138494",
        "decalage_sur_risque_5min_mesure": "0.341",
        "tirages_placebo": "3", "graine": "20261027",
        "tolerance_reproduction_pct": "2.0",
        "P1_artefact_1d_max": "0.02",
    }
    champs.update(surcharges)
    champs = {k: v for k, v in champs.items() if v is not None}
    p = tmp_path / "c.md"
    p.write_text("# c\n\n<!-- CRITERE-MACHINE\n"
                 + "\n".join(f"{k}: {v}" for k, v in champs.items())
                 + "\n-->\n", encoding="utf-8")
    return str(p)


# ─── le critere : chaque cellule exige ses CINQ champs ──────────────────────


def test_les_deux_cellules_sont_lues_avec_leur_PROPRE_fenetre(tmp_path):
    """⛔ Deviner une fenetre mesurerait un AUTRE horizon que celui annonce --
    exactement la faute d etiquette du 27/10."""
    cr = bdh.Criteres(_critere(tmp_path))

    assert set(cr.cellules) == {"1d", "4h"}
    assert cr.cellules["1d"]["fenetre_h"] == 240
    assert cr.cellules["4h"]["fenetre_h"] == 96
    assert cr.cellules["1d"]["horizon"] == "1d"
    assert cr.cellules["4h"]["horizon"] == "4h"


@pytest.mark.parametrize("manquant", [
    "horizon_1d", "population_1d", "fenetre_heures_1d",
    "reference_esperance_reel_1d", "reference_ecart_1d"])
def test_une_cellule_INCOMPLETE_est_un_ARRET_qui_NOMME_le_champ(tmp_path,
                                                                manquant):
    with pytest.raises(SystemExit) as e:
        bdh.Criteres(_critere(tmp_path, **{manquant: None}))

    assert manquant in str(e.value)


def test_un_critere_SANS_schema_de_placebo_est_un_ARRET(tmp_path):
    """⛔ Les bancs publies ont utilise UNIFORME : le deviner reproduirait le
    mauvais chiffre."""
    with pytest.raises(SystemExit) as e:
        bdh.Criteres(_critere(tmp_path, placebo_schema=None))

    assert "placebo_schema" in str(e.value)


def test_un_critere_SANS_cellule_est_un_ARRET(tmp_path):
    with pytest.raises(SystemExit):
        bdh.Criteres(_critere(tmp_path, cellules_horizon=None))


def test_les_references_du_5min_sont_lues(tmp_path):
    cr = bdh.Criteres(_critere(tmp_path))

    assert cr.artefact_5min == pytest.approx(0.138494)
    assert cr.decalage_5min == pytest.approx(0.341)


def test_les_cinq_predictions_sont_notables():
    for c in ("P1_artefact_1d_max", "P2_artefact_4h_max",
              "P3_artefact_4h_plancher", "P4_decalage_sur_risque_1d_max",
              "P5_artefact_1d_plancher"):
        assert c in bdh.PREDICTIONS, c


def test_les_predictions_lisent_la_CELLULE_nommee():
    """⛔ `P1` porte sur le `1d`, `P2`/`P3` sur le `4h`. Les confondre
    publierait un seuil engage sous un nom et mesure sous un autre."""
    _, p1 = bdh.PREDICTIONS["P1_artefact_1d_max"]
    _, p2 = bdh.PREDICTIONS["P2_artefact_4h_max"]

    m = {"artefact_1d": 0.001, "artefact_4h": 0.5}
    assert p1(m, 0.02) is True
    assert p2(m, 0.138494) is False


def test_une_prediction_sur_un_champ_MANQUANT_echoue_sans_lever():
    _, t = bdh.PREDICTIONS["P5_artefact_1d_plancher"]
    assert t({"artefact_1d": None}, -0.02) is False


# ─── bout en bout ───────────────────────────────────────────────────────────


def _base(tmp_path, n=60):
    p = tmp_path / "t.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE shadow_setups (pair TEXT, bar_timestamp TEXT,"
              " timeframe TEXT, resolved_backfill INT, direction TEXT,"
              " entry_price REAL, stop_loss REAL, take_profit_1 REAL,"
              " outcome TEXT, pnl_pct_net REAL)")
    lignes = []
    for tf, decal in (("1d", 1.0), ("4h", 1.03)):
        for g in range(n):
            bar = (T0 + timedelta(hours=g)).isoformat()
            for sens in ("buy", "sell"):
                e = 100.0 * decal
                sl = e - 1.0 if sens == "buy" else e + 1.0
                tp = e + 1.8 if sens == "buy" else e - 1.8
                lignes.append(("BTC/USD", bar, tf, 1, sens, e, sl, tp,
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
    monkeypatch.setattr(bdh, "charge", _charge)


def test_la_reproduction_ARRETE_quand_une_cellule_ne_colle_pas(
        tmp_path, moteur_bouchonne):
    m = bdh.mesure(_base(tmp_path), bdh.Criteres(_critere(tmp_path)))

    assert "erreur" in m and "NE REPRODUIT PAS" in m["erreur"]
    # et il publie quand meme les artefacts, pour le diagnostic
    assert m["artefact_1d"] is not None and m["artefact_4h"] is not None


def test_l_ARTEFACT_ne_depend_PAS_du_placebo(tmp_path, moteur_bouchonne):
    """🔑 LA PROPRIETE QUI REND CE BANC IMMUNE A LA DERIVE DU PLACEBO.

    `artefact = ecart(STOCKE) - ecart(FILL)` doit valoir exactement
    `esp_STOCKE - esp_FILL`, le placebo se simplifiant.
    """
    m = bdh.mesure(_base(tmp_path), bdh.Criteres(_critere(tmp_path)))

    for nom in ("1d", "4h"):
        par_ecarts = m[f"ecart_stocke_{nom}"] - m[f"ecart_fill_{nom}"]
        par_reels = (m[f"esperance_reel_stocke_{nom}"]
                     - m[f"esperance_reel_fill_{nom}"])
        assert m[f"artefact_{nom}"] == pytest.approx(par_reels, rel=1e-12)
        assert par_ecarts == pytest.approx(par_reels, rel=1e-9)


def test_les_deux_cellules_utilisent_des_FENETRES_differentes(
        tmp_path, moteur_bouchonne):
    m = bdh.mesure(_base(tmp_path), bdh.Criteres(_critere(tmp_path)))

    assert m["fenetre_heures_1d"] == 240 and m["fenetre_heures_4h"] == 96


def test_main_tourne_VRAIMENT_et_ecrit_son_JSON(tmp_path, moteur_bouchonne):
    import json
    db = _base(tmp_path)
    brut = bdh.mesure(db, bdh.Criteres(_critere(tmp_path)))
    c = _critere(
        tmp_path,
        reference_esperance_reel_1d="%.6f" % brut["esperance_reel_stocke_1d"],
        reference_ecart_1d="%.6f" % brut["ecart_stocke_1d"],
        reference_esperance_reel_4h="%.6f" % brut["esperance_reel_stocke_4h"],
        reference_ecart_4h="%.6f" % brut["ecart_stocke_4h"])
    sortie = tmp_path / "r.json"

    code = bdh.main(["--preinscription", c, "--db", db, "--json",
                     str(sortie)])

    assert code == 0
    m = json.loads(sortie.read_text(encoding="utf-8"))
    assert m["cellules"] == ["1d", "4h"]
    assert m["n_reel_1d"] == 120 and m["n_reel_4h"] == 120
    assert m["part_entree_hors_bougie_fill_max_pct"] == 0.0
    assert m["mediane_decalage_sur_risque_4h"] > 0
    assert m["valide"] is True


def test_le_RAPPORT_ne_lit_aucune_cle_que_le_RESULTAT_n_ecrit_pas(
        tmp_path, moteur_bouchonne):
    db = _base(tmp_path)
    brut = bdh.mesure(db, bdh.Criteres(_critere(tmp_path)))
    cr = bdh.Criteres(_critere(
        tmp_path,
        reference_esperance_reel_1d="%.6f" % brut["esperance_reel_stocke_1d"],
        reference_ecart_1d="%.6f" % brut["ecart_stocke_1d"],
        reference_esperance_reel_4h="%.6f" % brut["esperance_reel_stocke_4h"],
        reference_ecart_4h="%.6f" % brut["ecart_stocke_4h"]))

    texte = bdh.rapport(bdh.mesure(db, cr))

    assert "ARTEFACT" in texte and "decalage/risque median" in texte
    assert "1re bougie" in texte and "VERDICT" in texte


def test_le_resultat_porte_les_CHAMPS_REQUIS_par_or_verdict(
        tmp_path, moteur_bouchonne):
    db = _base(tmp_path)
    brut = bdh.mesure(db, bdh.Criteres(_critere(tmp_path)))
    cr = bdh.Criteres(_critere(
        tmp_path,
        reference_esperance_reel_1d="%.6f" % brut["esperance_reel_stocke_1d"],
        reference_ecart_1d="%.6f" % brut["ecart_stocke_1d"],
        reference_esperance_reel_4h="%.6f" % brut["esperance_reel_stocke_4h"],
        reference_ecart_4h="%.6f" % brut["ecart_stocke_4h"]))

    m = bdh.mesure(db, cr)

    for champ in ("n", "t", "valide", "forme"):
        assert champ in m and m[champ] is not None, champ


def test_une_population_VIDE_rend_une_erreur_et_un_code_1(tmp_path):
    p = tmp_path / "vide.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE shadow_setups (pair TEXT, bar_timestamp TEXT,"
              " timeframe TEXT, resolved_backfill INT, direction TEXT,"
              " entry_price REAL, stop_loss REAL, take_profit_1 REAL,"
              " outcome TEXT, pnl_pct_net REAL)")
    c.commit()
    c.close()

    code = bdh.main(["--preinscription", _critere(tmp_path), "--db", str(p)])

    assert code == 1
