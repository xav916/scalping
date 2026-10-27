"""Tests du banc de l ECHELLE DE PLACEBOS.

Les lecons exercees ici :
- ⛔ `py_compile` ne prouve pas qu un module tourne : `main()` est appele pour
  de vrai, sur une base temporaire et des series synthetiques.
- ⛔ Le rapport est confronte aux cles que le resultat ecrit vraiment.
- 🔑 Le tirage `UNIFORME` doit reproduire **a l identique** celui du banc
  d esperance : c est la condition pour que les trois barreaux soient
  comparables entre eux ET au resultat publie.
- ⛔ Et les instruments de validite doivent DISCRIMINER : un instrument qui
  vaut 100 % quel que soit le schema ne verifie rien.
"""
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

from scripts import banc_placebo_structure as bps  # noqa: E402
from scripts.banc_esperance_horizon import Serie  # noqa: E402

H = 3600.0
T0 = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _setups(n_groupes=3, par_groupe=2, paire="BTC/USD"):
    """`n_groupes` barres horaires, `par_groupe` setups de sens opposes."""
    out = []
    for g in range(n_groupes):
        bar = T0 + timedelta(hours=g)
        for k in range(par_groupe):
            out.append({"pair": paire, "bar": bar, "achat": k % 2 == 0,
                        "entry": 100.0, "sl": 99.0, "tp": 101.8,
                        "issue": "TP1", "pnl": 0.5, "risk_pct": 1.0})
    return out


def _bornes(couverts):
    b = {}
    for d in couverts:
        mn, mx = b.get(d["pair"], (d["bar"], d["bar"]))
        b[d["pair"]] = (min(mn, d["bar"]), max(mx, d["bar"]))
    return b


# ─── le tirage UNIFORME doit reproduire celui du banc d esperance ───────────


def test_UNIFORME_reproduit_EXACTEMENT_le_tirage_du_banc_d_esperance():
    """🔑 LA CONDITION DE COMPARABILITE.

    Le banc d esperance fait, pour chaque setup dans l ordre :
        `alea.uniform(mn, mx)`
    Un appel, dans cet ordre. A graine egale, la suite doit etre identique --
    sinon le barreau UNIFORME ne peut pas servir de controle de reproduction.
    """
    # ⛔ DEUX paires aux bornes DIFFERENTES : avec une seule paire, toutes
    # les bornes sont identiques et l ORDRE du tirage devient sans effet --
    # le test passait alors meme en tirant a l envers (prouve par mutation).
    couverts = _setups(4, 2, "BTC/USD") + _setups(6, 1, "ETH/USD")
    bornes = _bornes(couverts)
    assert bornes["BTC/USD"] != bornes["ETH/USD"]

    obtenu = bps.instants_tires("UNIFORME", couverts, bornes,
                                random.Random(20261027))

    ref_alea = random.Random(20261027)
    attendu = [ref_alea.uniform(bornes[d["pair"]][0].timestamp(),
                                bornes[d["pair"]][1].timestamp())
               for d in couverts]
    assert obtenu == attendu


def test_UNIFORME_ne_tombe_presque_JAMAIS_sur_le_reseau():
    """C est tout le probleme : le reel est a `:00`, l uniforme non."""
    couverts = _setups(50, 1)

    inst = bps.instants_tires("UNIFORME", couverts, _bornes(couverts),
                              random.Random(1))

    assert bps.part_sur_le_reseau_pct(inst) < 5.0


# ─── RESEAU ─────────────────────────────────────────────────────────────────


def test_RESEAU_tire_UNIQUEMENT_des_heures_pleines():
    couverts = _setups(30, 1)
    bornes = _bornes(couverts)

    inst = bps.instants_tires("RESEAU", couverts, bornes, random.Random(2))

    assert bps.part_sur_le_reseau_pct(inst) == 100.0
    t0, t1 = bornes["BTC/USD"][0].timestamp(), bornes["BTC/USD"][1].timestamp()
    assert all(t0 <= t <= t1 for t in inst)


def test_RESEAU_couvre_PLUSIEURS_heures_et_pas_une_seule():
    """⛔ CONTROLE NEGATIF : un tirage degenere (toujours la meme heure) aurait
    `part_reseau = 100 %` sans rien tirer du tout."""
    couverts = _setups(40, 1)

    inst = bps.instants_tires("RESEAU", couverts, _bornes(couverts),
                              random.Random(3))

    assert len(set(inst)) > 5


def test_RESEAU_ne_respecte_PAS_les_groupes():
    """Le barreau intermediaire corrige l heure, pas l appariement."""
    couverts = _setups(30, 2)

    inst = bps.instants_tires("RESEAU", couverts, _bornes(couverts),
                              random.Random(4))

    assert bps.groupes_respectes_pct(couverts, inst) < 50.0


# ─── RESEAU_ET_PAIRES ───────────────────────────────────────────────────────


def test_RESEAU_ET_PAIRES_donne_le_MEME_instant_aux_deux_jambes():
    couverts = _setups(30, 2)

    inst = bps.instants_tires("RESEAU_ET_PAIRES", couverts, _bornes(couverts),
                              random.Random(5))

    assert bps.groupes_respectes_pct(couverts, inst) == 100.0
    assert bps.part_sur_le_reseau_pct(inst) == 100.0


def test_RESEAU_ET_PAIRES_tire_des_instants_DIFFERENTS_entre_groupes():
    couverts = _setups(40, 2)

    inst = bps.instants_tires("RESEAU_ET_PAIRES", couverts,
                              _bornes(couverts), random.Random(6))

    assert len(set(inst)) > 5


def test_les_groupes_sont_distingues_par_PAIRE_autant_que_par_BARRE():
    """Deux paires sur la MEME barre sont deux groupes distincts."""
    couverts = _setups(3, 1, "BTC/USD") + _setups(3, 1, "ETH/USD")

    inst = bps.instants_tires("RESEAU_ET_PAIRES", couverts,
                              _bornes(couverts), random.Random(7))

    assert bps.groupes_respectes_pct(couverts, inst) == 100.0
    # 6 groupes : rien n impose qu ils partagent un instant
    assert len({(d["pair"], d["bar"]) for d in couverts}) == 6


def test_un_schema_INCONNU_est_un_ARRET():
    couverts = _setups(2, 1)

    with pytest.raises(SystemExit) as e:
        bps.instants_tires("GAUSSIEN", couverts, _bornes(couverts),
                           random.Random(8))

    assert "INCONNU" in str(e.value)


# ─── les instruments DISCRIMINENT ───────────────────────────────────────────


def test_groupes_respectes_DISCRIMINE_les_trois_schemas():
    """⛔ L INSTRUMENT QUI A REMPLACE CELUI DE LA v1.

    La v1 exigeait « autant d instants distincts qu au reel », impossible a
    cause des collisions. Celui-ci vaut 100 % pour le seul schema apparie et
    bien moins pour les deux autres : il verifie la propriete VOULUE.
    """
    couverts = _setups(30, 2)
    bornes = _bornes(couverts)
    vus = {}
    for s in bps.SCHEMAS:
        inst = bps.instants_tires(s, couverts, bornes, random.Random(9))
        vus[s] = bps.groupes_respectes_pct(couverts, inst)

    assert vus["RESEAU_ET_PAIRES"] == 100.0
    assert vus["UNIFORME"] < 50.0 and vus["RESEAU"] < 50.0


def test_part_sur_le_reseau_se_calcule_simplement():
    assert bps.part_sur_le_reseau_pct([0.0, H, 2 * H]) == 100.0
    assert bps.part_sur_le_reseau_pct([0.0, H + 1.0]) == 50.0
    assert bps.part_sur_le_reseau_pct([]) == 0.0


def test_un_groupe_a_UN_SEUL_setup_est_toujours_respecte():
    couverts = _setups(5, 1)
    inst = bps.instants_tires("UNIFORME", couverts, _bornes(couverts),
                              random.Random(10))

    assert bps.groupes_respectes_pct(couverts, inst) == 100.0


# ─── le critere ─────────────────────────────────────────────────────────────


def _critere(tmp_path, **surcharges):
    champs = {
        "forme": "placebo", "horizon": "5min", "fenetre_heures": "96",
        "source_bras_reel": "RECALCULE",
        "placebo_schemas": "UNIFORME,RESEAU,RESEAU_ET_PAIRES",
        "placebo_decisif": "RESEAU_ET_PAIRES",
        "population": "resolved_backfill=0 AND timeframe=5min",
        "tirages_placebo": "3", "graine": "20261027",
        "reference_ecart_uniforme_publie": "0.0874",
        "P3_ecart_reseau_et_paires_min": "0.0",
    }
    champs.update(surcharges)
    champs = {k: v for k, v in champs.items() if v is not None}
    p = tmp_path / "c.md"
    p.write_text("# c\n\n<!-- CRITERE-MACHINE\n"
                 + "\n".join(f"{k}: {v}" for k, v in champs.items())
                 + "\n-->\n", encoding="utf-8")
    return str(p)


def test_un_critere_STOCKE_est_REFUSE(tmp_path):
    """⛔ La lecon du 27/10 : les deux bras doivent partager leur source."""
    with pytest.raises(SystemExit) as e:
        bps.Criteres(_critere(tmp_path, source_bras_reel="STOCKE"))

    assert "RECALCULE" in str(e.value)


def test_un_decisif_HORS_des_schemas_est_un_ARRET(tmp_path):
    with pytest.raises(SystemExit) as e:
        bps.Criteres(_critere(tmp_path, placebo_decisif="RESEAU",
                              placebo_schemas="UNIFORME"))

    assert "placebo_decisif" in str(e.value)


def test_un_critere_SANS_reference_publiee_est_un_ARRET(tmp_path):
    """Sans elle, le barreau UNIFORME ne peut pas servir de controle."""
    with pytest.raises(SystemExit) as e:
        bps.Criteres(_critere(tmp_path,
                              reference_ecart_uniforme_publie=None))

    assert "reference_ecart_uniforme_publie" in str(e.value)


def test_un_schema_inconnu_dans_le_critere_est_un_ARRET(tmp_path):
    with pytest.raises(SystemExit):
        bps.Criteres(_critere(tmp_path, placebo_schemas="UNIFORME,BROWNIEN"))


def test_les_predictions_sont_lues_par_NOM(tmp_path):
    cr = bps.Criteres(_critere(tmp_path))

    assert set(cr.predictions) == {"P3_ecart_reseau_et_paires_min"}


def test_les_cinq_predictions_sont_TOUTES_notables():
    for cle in ("P1_ecart_reseau_max", "P2_ecart_reseau_et_paires_max",
                "P3_ecart_reseau_et_paires_min", "P4_t_reseau_et_paires_min",
                "P5_ecart_reseau_et_paires_plancher"):
        assert cle in bps.PREDICTIONS, cle


def test_une_prediction_sur_un_champ_MANQUANT_echoue_sans_lever():
    _, test = bps.PREDICTIONS["P4_t_reseau_et_paires_min"]

    assert test({"t_contre_placebo_reseau_et_paires": None}, 2.0) is False


# ─── bout en bout, avec des series SYNTHETIQUES ─────────────────────────────

C = namedtuple("C", "timestamp open high low close")


def _serie(n=4000, pas_s=300):
    """Une marche deterministe, montante puis descendante."""
    b = []
    for i in range(n):
        p = 100.0 + (i % 400) * 0.02 - (i % 37) * 0.01
        b.append(C(T0 - timedelta(hours=2) + timedelta(seconds=i * pas_s),
                   p, p * 1.002, p * 0.998, p))
    return Serie(b)


def _base(tmp_path, n_groupes=40):
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
    """⛔ `monkeypatch`, jamais une affectation de module : un test qui
    remplace durablement un module partage casse la suite selon l ORDRE."""
    async def _charge(paires, fin=None):
        return {p: _serie() for p in paires}
    monkeypatch.setattr(bps, "charge", _charge)
    monkeypatch.setattr(bps, "controle_moteur", lambda *a, **k: (1, 1))


def test_le_controle_de_reproduction_ARRETE_quand_l_ecart_diverge(
        tmp_path, moteur_bouchonne):
    """⛔ LE GARDE-FOU CENTRAL. Si ma re-implementation du placebo ne rend pas
    l ecart publie, comparer les barreaux entre eux n a aucun sens."""
    cr = bps.Criteres(_critere(tmp_path,
                               reference_ecart_uniforme_publie="99.0"))

    m = bps.mesure(_base(tmp_path), cr, controle=False)

    assert "erreur" in m
    assert "NE REPRODUIT PAS" in m["erreur"]
    # il doit tout de meme publier ce qu il a mesure, pour le diagnostic
    assert m["ecart_signal_uniforme"] is not None


def test_main_tourne_VRAIMENT_et_ecrit_son_JSON(tmp_path, moteur_bouchonne):
    """⛔ Trois `NameError` sont passees devant des suites vertes qui
    n exercaient que les fonctions pures."""
    import json
    db = _base(tmp_path)

    # 1er passage : on recupere l ecart UNIFORME que ces series produisent
    cr0 = bps.Criteres(_critere(tmp_path,
                                reference_ecart_uniforme_publie="99.0"))
    reel = bps.mesure(db, cr0, controle=False)["ecart_signal_uniforme"]

    # 2e passage : la reference est coherente, le banc doit aboutir
    c = _critere(tmp_path, reference_ecart_uniforme_publie="%.6f" % reel)
    sortie = tmp_path / "r.json"
    code = bps.main(["--preinscription", c, "--db", db, "--json",
                     str(sortie), "--sans-controle-moteur"])

    assert code == 0
    m = json.loads(sortie.read_text(encoding="utf-8"))
    assert m["n_reel"] == 80
    assert m["part_entrees_reseau_pct"] == 100.0
    assert m["instants_distincts_reel"] == 40
    assert m["groupes_respectes_pct"] == 100.0
    assert m["part_placebo_reseau_pct"] == 100.0
    assert m["valide"] is True
    for s in ("uniforme", "reseau", "reseau_et_paires"):
        assert m["ecart_signal_" + s] is not None, s


def test_le_RAPPORT_ne_lit_aucune_cle_que_le_RESULTAT_n_ecrit_pas(
        tmp_path, moteur_bouchonne):
    db = _base(tmp_path)
    cr0 = bps.Criteres(_critere(tmp_path,
                                reference_ecart_uniforme_publie="99.0"))
    reel = bps.mesure(db, cr0, controle=False)["ecart_signal_uniforme"]
    cr = bps.Criteres(_critere(tmp_path,
                               reference_ecart_uniforme_publie="%.6f" % reel))

    texte = bps.rapport(bps.mesure(db, cr, controle=False))

    assert "BARREAU" in texte and "RESEAU_ET_PAIRES" in texte
    assert "groupes%" in texte and "VERDICT" in texte


def test_le_resultat_porte_les_CHAMPS_REQUIS_par_or_verdict(
        tmp_path, moteur_bouchonne):
    db = _base(tmp_path)
    cr0 = bps.Criteres(_critere(tmp_path,
                                reference_ecart_uniforme_publie="99.0"))
    reel = bps.mesure(db, cr0, controle=False)["ecart_signal_uniforme"]
    cr = bps.Criteres(_critere(tmp_path,
                               reference_ecart_uniforme_publie="%.6f" % reel))

    m = bps.mesure(db, cr, controle=False)

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

    code = bps.main(["--preinscription", _critere(tmp_path),
                     "--db", str(p), "--sans-controle-moteur"])

    assert code == 1
