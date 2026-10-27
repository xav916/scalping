"""Tests du banc du PLACEBO FIDELE.

Le test central est encore un controle de provenance : a `ratios=None`,
`r_par_setup_avec_ratios` doit etre IDENTIQUE a la fonction deja publiee.
Sans cela les barreaux `RESEAU` et `RESEAU_ET_PAIRES` d ici ne seraient pas
comparables a ceux de `2613282`, et le controle de reproduction masquerait un
decalage au lieu de l attraper.
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

from scripts import banc_anticorrelation_jambes as baj  # noqa: E402
from scripts import banc_placebo_fidele as bpf  # noqa: E402
from scripts import banc_placebo_structure as bps  # noqa: E402
from scripts.banc_esperance_horizon import Serie  # noqa: E402

T0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
C = namedtuple("C", "timestamp open high low close")


def _serie(n=4000, pas_s=300):
    """⛔ `close` DIFFERE de `open` : a `close == open`, calculer les ratios
    contre l une ou l autre ne changeait rien et la mutation passait
    (fixture degeneree, prouvee par mutation)."""
    b = []
    for i in range(n):
        p = 100.0 + (i % 400) * 0.02 - (i % 37) * 0.01
        b.append(C(T0 - timedelta(hours=2) + timedelta(seconds=i * pas_s),
                   p, p * 1.002, p * 0.998, p * 1.0005))
    return Serie(b)


def _setups(n_groupes=20, par_groupe=2, paire="BTC/USD", decale=False):
    """Des duos de sens opposes. `decale` donne a chaque jambe son propre
    prix d entree, comme la production le fait reellement."""
    out = []
    for g in range(n_groupes):
        bar = T0 + timedelta(hours=g)
        for k in range(par_groupe):
            achat = k % 2 == 0
            rp = 0.5 + 0.25 * ((g + k) % 4)
            e = 100.0 * (1.0 + (0.001 if decale and achat else
                                -0.001 if decale else 0.0))
            out.append({"pair": paire, "bar": bar, "achat": achat,
                        "entry": e,
                        "sl": e - rp if achat else e + rp,
                        "tp": e + 1.8 * rp if achat else e - 1.8 * rp,
                        "issue": "TP1", "pnl": 0.5, "risk_pct": rp})
    return out


def _bornes(couverts):
    b = {}
    for d in couverts:
        mn, mx = b.get(d["pair"], (d["bar"], d["bar"]))
        b[d["pair"]] = (min(mn, d["bar"]), max(mx, d["bar"]))
    return b


# ─── LE CONTROLE DE PROVENANCE ──────────────────────────────────────────────


def test_sans_ratios_la_fonction_est_IDENTIQUE_a_celle_deja_publiee():
    """🔑 Sinon les barreaux RESEAU et APPARIE d ici ne seraient pas
    comparables a ceux de `2613282`, et le controle de reproduction
    masquerait un decalage au lieu de l attraper."""
    couverts = _setups(20, 2)
    series = {"BTC/USD": _serie()}
    inst = bps.instants_tires("RESEAU_ET_PAIRES", couverts,
                              _bornes(couverts), random.Random(42))

    a = baj.r_par_setup(couverts, series, inst, 96)
    b = bpf.r_par_setup_avec_ratios(couverts, series, inst, 96, None)

    assert a == b


def test_des_ratios_UNITAIRES_ne_changent_RIEN():
    couverts = _setups(10, 2)
    series = {"BTC/USD": _serie()}
    inst = [d["bar"].timestamp() for d in couverts]

    a = bpf.r_par_setup_avec_ratios(couverts, series, inst, 96, None)
    b = bpf.r_par_setup_avec_ratios(couverts, series, inst, 96,
                                    [1.0] * len(couverts))

    assert a == b


def test_des_ratios_NON_unitaires_changent_le_resultat():
    """⛔ Sinon le barreau fidele serait armé et INERTE."""
    couverts = _setups(10, 2)
    series = {"BTC/USD": _serie()}
    inst = [d["bar"].timestamp() for d in couverts]

    a = bpf.r_par_setup_avec_ratios(couverts, series, inst, 96, None)
    b = bpf.r_par_setup_avec_ratios(couverts, series, inst, 96,
                                    [1.004] * len(couverts))

    assert [x[1] for x in a if x] != [x[1] for x in b if x]


# ─── les ratios d entree ────────────────────────────────────────────────────


def test_les_ratios_valent_UN_quand_l_entree_egale_l_ouverture():
    series = {"BTC/USD": _serie()}
    couverts = _setups(4, 1)
    for d in couverts:
        s = series["BTC/USD"]
        d["entry"] = float(s.open[s.index_apres(d["bar"].timestamp())])

    assert bpf.ratios_d_entree(couverts, series) == pytest.approx([1.0] * 4)


def test_les_ratios_reflettent_le_DECALAGE_de_chaque_jambe():
    """Deux jambes d un meme duo, entrees differentes => ratios differents."""
    series = {"BTC/USD": _serie()}
    couverts = _setups(1, 2, decale=True)

    r = bpf.ratios_d_entree(couverts, series)

    assert len(r) == 2 and r[0] != r[1]


def test_une_bougie_MANQUANTE_rend_un_ratio_UNITAIRE_donc_plus_exigeant():
    """⛔ Un ratio neutre compte comme unitaire, ce qui rend la garde
    `part_ratio_non_unitaire_pct` PLUS exigeante, jamais plus permissive."""
    series = {"BTC/USD": _serie(n=3)}
    couverts = _setups(1, 1)
    couverts[0]["bar"] = T0 + timedelta(days=400)   # bien au-dela des bougies

    assert bpf.ratios_d_entree(couverts, series) == [1.0]


# ─── les deux barreaux apparies partagent leurs instants ────────────────────


def test_les_deux_barreaux_APPARIES_tirent_les_MEMES_instants():
    """🔑 Controle gratuit : `RESEAU_ET_PAIRES` et `DECALAGE` passent par le
    MEME schema de tirage avec la MEME graine, donc la difference de `rho` est
    attribuable aux SEULS decalages d entree."""
    couverts = _setups(15, 2)
    bornes = _bornes(couverts)

    a = bps.instants_tires(bpf.SCHEMA_INSTANTS["RESEAU_ET_PAIRES"], couverts,
                           bornes, random.Random(20261027))
    b = bps.instants_tires(bpf.SCHEMA_INSTANTS["RESEAU_PAIRES_DECALAGE"],
                           couverts, bornes, random.Random(20261027))

    assert a == b


def test_seul_le_barreau_DECALAGE_applique_les_ratios():
    assert bpf.AVEC_DECALAGE == ("RESEAU_PAIRES_DECALAGE",)
    assert "RESEAU" not in bpf.AVEC_DECALAGE
    assert "RESEAU_ET_PAIRES" not in bpf.AVEC_DECALAGE


# ─── la variance par jambe ──────────────────────────────────────────────────


def test_la_variance_par_jambe_se_calcule_a_la_main():
    v = bpf.VarianceParJambe()
    for x in (1.0, 2.0, 3.0, 4.0):
        v.ajoute(x)

    assert v.variance() == pytest.approx(1.25)      # variance de population


def test_la_variance_par_jambe_est_INDEFINIE_sous_deux_valeurs():
    v = bpf.VarianceParJambe()
    assert v.variance() is None
    v.ajoute(1.0)
    assert v.variance() is None


# ─── le critere ─────────────────────────────────────────────────────────────


def _critere(tmp_path, **surcharges):
    champs = {
        "forme": "placebo", "horizon": "5min", "fenetre_heures": "96",
        "source_bras_reel": "RECALCULE",
        "placebo_schemas":
            "RESEAU,RESEAU_ET_PAIRES,RESEAU_PAIRES_DECALAGE",
        "placebo_decisif": "RESEAU_PAIRES_DECALAGE",
        "population": "resolved_backfill=0 AND timeframe=5min",
        "tirages_placebo": "4", "graine": "20261027",
        "reference_ecart_reseau": "0.091961",
        "reference_ecart_reseau_et_paires": "0.090488",
        "reference_rho_reel": "-0.1273",
        "P1_ecart_rho_decalage_reel_max": "0.10",
    }
    champs.update(surcharges)
    champs = {k: v for k, v in champs.items() if v is not None}
    p = tmp_path / "c.md"
    p.write_text("# c\n\n<!-- CRITERE-MACHINE\n"
                 + "\n".join(f"{k}: {v}" for k, v in champs.items())
                 + "\n-->\n", encoding="utf-8")
    return str(p)


def test_l_ORDRE_des_TROIS_barreaux_est_EXIGE(tmp_path):
    with pytest.raises(SystemExit) as e:
        bpf.Criteres(_critere(
            tmp_path,
            placebo_schemas="RESEAU_PAIRES_DECALAGE,RESEAU,RESEAU_ET_PAIRES"))
    assert "EXACTEMENT" in str(e.value)


def test_un_barreau_decisif_AUTRE_est_un_ARRET(tmp_path):
    with pytest.raises(SystemExit) as e:
        bpf.Criteres(_critere(tmp_path, placebo_decisif="RESEAU"))
    assert "decisif" in str(e.value)


def test_un_critere_SANS_reference_de_rho_reel_est_un_ARRET(tmp_path):
    with pytest.raises(SystemExit) as e:
        bpf.Criteres(_critere(tmp_path, reference_rho_reel=None))
    assert "reference_rho_reel" in str(e.value)


def test_un_critere_STOCKE_est_REFUSE(tmp_path):
    with pytest.raises(SystemExit):
        bpf.Criteres(_critere(tmp_path, source_bras_reel="STOCKE"))


def test_les_cinq_predictions_sont_notables():
    for c in ("P1_ecart_rho_decalage_reel_max",
              "P2_rapport_variance_par_jambe_plancher",
              "P3_rapport_variance_par_jambe_plafond",
              "P4_rho_reseau_abs_max",
              "P5_mediane_decalage_sur_risque_min"):
        assert c in bpf.PREDICTIONS, c


def test_la_prediction_du_rho_RESEAU_porte_sur_la_VALEUR_ABSOLUE():
    _, t = bpf.PREDICTIONS["P4_rho_reseau_abs_max"]

    assert t({"rho_duos_reseau": 0.01}, 0.05) is True
    assert t({"rho_duos_reseau": -0.01}, 0.05) is True
    assert t({"rho_duos_reseau": 0.20}, 0.05) is False
    assert t({"rho_duos_reseau": -0.20}, 0.05) is False


def test_une_prediction_sur_un_champ_MANQUANT_echoue_sans_lever():
    _, t = bpf.PREDICTIONS["P1_ecart_rho_decalage_reel_max"]
    assert t({"ecart_rho_decalage_reel": None}, 0.10) is False


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
            # entrees DECALEES, comme la production
            e = 100.0 + (0.1 if sens == "buy" else -0.1)
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
    monkeypatch.setattr(bpf, "charge", _charge)


def test_le_controle_de_reproduction_ARRETE_quand_les_barreaux_divergent(
        tmp_path, moteur_bouchonne):
    cr = bpf.Criteres(_critere(tmp_path))

    m = bpf.mesure(_base(tmp_path), cr)

    assert "erreur" in m and "NE REPRODUISENT PAS" in m["erreur"]
    assert m["duos"] == 30
    assert m["part_ratio_non_unitaire_pct"] > 40


def test_main_tourne_VRAIMENT_et_ecrit_son_JSON(tmp_path, moteur_bouchonne):
    import json
    db = _base(tmp_path)
    brut = bpf.mesure(db, bpf.Criteres(_critere(tmp_path)))
    c = _critere(
        tmp_path,
        reference_ecart_reseau="%.6f" % brut["ecart_signal_reseau"],
        reference_ecart_reseau_et_paires="%.6f"
        % brut["ecart_signal_reseau_et_paires"])
    sortie = tmp_path / "r.json"

    code = bpf.main(["--preinscription", c, "--db", db, "--json",
                     str(sortie)])

    assert code == 0
    m = json.loads(sortie.read_text(encoding="utf-8"))
    assert m["n_reel"] == 60 and m["duos"] == 30
    for nom in ("reseau", "reseau_et_paires", "decalage"):
        assert m["rho_duos_" + nom] is not None, nom
        assert m["variance_par_jambe_" + nom] is not None, nom
    assert m["rapport_variance_par_jambe"] is not None
    assert m["mediane_decalage_sur_risque"] is not None
    assert m["valide"] is True


def test_le_barreau_DECALAGE_donne_un_rho_DIFFERENT_du_barreau_APPARIE(
        tmp_path, moteur_bouchonne):
    """🔑 LE CŒUR DU BANC : a instants IDENTIQUES, les decalages d entree
    doivent deplacer l anti-correlation. Sinon le barreau fidele n apporte
    rien et le resultat aurait l air normal."""
    db = _base(tmp_path)

    m = bpf.mesure(db, bpf.Criteres(_critere(tmp_path)))

    assert m["rho_duos_apparie"] != m["rho_duos_decalage"]


def test_le_RAPPORT_ne_lit_aucune_cle_que_le_RESULTAT_n_ecrit_pas(
        tmp_path, moteur_bouchonne):
    db = _base(tmp_path)
    brut = bpf.mesure(db, bpf.Criteres(_critere(tmp_path)))
    cr = bpf.Criteres(_critere(
        tmp_path,
        reference_ecart_reseau="%.6f" % brut["ecart_signal_reseau"],
        reference_ecart_reseau_et_paires="%.6f"
        % brut["ecart_signal_reseau_et_paires"]))

    texte = bpf.rapport(bpf.mesure(db, cr))

    assert "BARREAU" in texte and "DECALAGE" in texte
    assert "rho REEL" in texte and "var/jambe" in texte
    assert "VERDICT" in texte


def test_le_resultat_porte_les_CHAMPS_REQUIS_par_or_verdict(
        tmp_path, moteur_bouchonne):
    db = _base(tmp_path)
    brut = bpf.mesure(db, bpf.Criteres(_critere(tmp_path)))
    cr = bpf.Criteres(_critere(
        tmp_path,
        reference_ecart_reseau="%.6f" % brut["ecart_signal_reseau"],
        reference_ecart_reseau_et_paires="%.6f"
        % brut["ecart_signal_reseau_et_paires"]))

    m = bpf.mesure(db, cr)

    for champ in ("n", "t", "valide", "forme"):
        assert champ in m and m[champ] is not None, champ
