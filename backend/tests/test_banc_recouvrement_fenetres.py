"""Tests du banc de RECOUVREMENT des fenetres.

Les lecons deja payees et exercees ici :

- ⛔ `py_compile` ne prouve pas qu un module TOURNE : trois `NameError` sont
  passees devant des suites vertes qui n exercaient que les fonctions PURES.
  `main()` est donc appele pour de vrai, sur une base temporaire.
- ⛔ Une mesure de douze minutes a ete perdue parce que le RAPPORT levait sur
  une cle absente APRES le calcul. Un test confronte le rapport aux cles que
  le resultat ecrit vraiment.
- ⛔ Un critere engage sous un nom et mesure sous un autre n est pas un
  critere : les predictions sont lues par NOM.
- 🔑 Et la lecon du 27/10 : les deux bras doivent partager leur SOURCE. Ici
  c est la POPULATION qui doit etre partagee avec le banc d esperance, d ou le
  test de provenance.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import sys

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))

from scripts import banc_recouvrement_fenetres as brf  # noqa: E402
from scripts.banc_esperance_horizon import lire_reels  # noqa: E402

H = 3600.0
W = 96 * H


# ─── recouvrement_moyen : la statistique de PAIRES ──────────────────────────


def test_le_recouvrement_se_calcule_a_la_main():
    """Trois instants espaces de 50 h, fenetre 96 h.

    |t0-t1| = 50 h < 96 h, |t1-t2| = 50 h < 96 h, |t0-t2| = 100 h > 96 h.
    => t0 croise 1, t1 croise 2, t2 croise 1  =>  moyenne 4/3.
    """
    t = [0.0, 50 * H, 100 * H]

    assert brf.recouvrement_moyen(t, W) == pytest.approx(4 / 3)


def test_un_seul_instant_ne_croise_RIEN():
    assert brf.recouvrement_moyen([123.0], W) == 0.0
    assert brf.recouvrement_moyen([], W) == 0.0


def test_la_borne_est_STRICTE_a_la_largeur_de_fenetre():
    """`[t, t+W]` et `[t+W, t+2W]` se TOUCHENT sans se recouvrir."""
    assert brf.recouvrement_moyen([0.0, W], W) == 0.0
    assert brf.recouvrement_moyen([0.0, W - 1.0], W) == 1.0


def test_le_recouvrement_MONTE_avec_l_agglomeration():
    """⛔ LA PROPRIETE QUI JUSTIFIE CETTE STATISTIQUE.

    Meme effectif, meme etendue : seule la DISPOSITION change. Une statistique
    qui ne distinguerait pas ces deux cas ne pourrait pas repondre a la
    question du banc.
    """
    etale = [i * 40 * H for i in range(10)]            # 0 -> 360 h, regulier
    groupe = [0.0, 360 * H] + [180 * H + i * H for i in range(8)]

    assert max(etale) == max(groupe) and min(etale) == min(groupe)
    assert len(etale) == len(groupe)
    assert brf.recouvrement_moyen(groupe, W) > brf.recouvrement_moyen(etale, W)


def test_la_SOMME_des_fenetres_est_INVARIANTE_mais_l_UNION_non():
    """🔑 Pourquoi un premier moment ne peut pas trancher.

    `somme_h` ne depend que de `n` : identique pour les deux dispositions.
    C est `union_h` -- et le recouvrement -- qui portent l information.
    """
    etale = {"A": [i * 40 * H for i in range(10)]}
    groupe = {"A": [0.0, 360 * H] + [180 * H + i * H for i in range(8)]}

    a, b = brf.statistiques(etale, W), brf.statistiques(groupe, W)

    assert a["somme_h"] == b["somme_h"]
    assert b["union_h"] < a["union_h"]
    assert b["ratio_somme_sur_union"] > a["ratio_somme_sur_union"]


# ─── union_secondes ─────────────────────────────────────────────────────────


def test_l_union_fusionne_ce_qui_se_recouvre():
    assert brf.union_secondes([0.0, 50 * H], W) == pytest.approx(146 * H)


def test_l_union_additionne_ce_qui_est_DISJOINT():
    assert brf.union_secondes([0.0, 200 * H], W) == pytest.approx(192 * H)


def test_l_union_d_un_instant_vaut_la_fenetre():
    assert brf.union_secondes([42.0], W) == pytest.approx(W)
    assert brf.union_secondes([], W) == 0.0


# ─── le tirage de structure ─────────────────────────────────────────────────


def test_le_tirage_conserve_l_EFFECTIF_et_les_BORNES_par_paire():
    """Le placebo du banc d esperance ne change QUE l instant d entree."""
    import random
    reel = {"A": [0.0, 10 * H, 300 * H], "B": [5 * H, 7 * H]}

    tire = brf.tirage_placebo(reel, random.Random(1))

    assert set(tire) == set(reel)
    for p in reel:
        assert len(tire[p]) == len(reel[p])
        assert min(reel[p]) <= min(tire[p]) and max(tire[p]) <= max(reel[p])


def test_le_tirage_est_REPRODUCTIBLE_a_graine_egale():
    import random
    reel = {"A": [float(i) * H for i in range(20)]}

    a = brf.tirage_placebo(reel, random.Random(7))
    b = brf.tirage_placebo(reel, random.Random(7))
    c = brf.tirage_placebo(reel, random.Random(8))

    assert a == b and a != c


def test_une_comparaison_rend_un_RATIO_proche_de_1_sur_du_vrai_uniforme():
    """⛔ CONTROLE NEGATIF. Un jeu deja uniforme ne doit pas paraitre
    agglomere : sinon le banc fabriquerait l effet qu il cherche."""
    import random
    alea = random.Random(3)
    uniforme = {"A": [alea.uniform(0, 400 * H) for _ in range(400)]}

    r = brf.compare_a_la_structure_uniforme(uniforme, W, tirages=20, graine=11)

    assert r["ratio_blocs_placebo_sur_reel"] == pytest.approx(1.0, abs=0.10)


def test_une_comparaison_DETECTE_une_vraie_agglomeration():
    import random
    alea = random.Random(3)
    # deux rafales serrees aux extremites d une etendue de 400 h
    groupe = {"A": [alea.uniform(0, 5 * H) for _ in range(200)]
                   + [alea.uniform(395 * H, 400 * H) for _ in range(200)]}

    r = brf.compare_a_la_structure_uniforme(groupe, W, tirages=20, graine=11)

    assert r["ratio_blocs_placebo_sur_reel"] > 1.5


# ─── la base, et la PROVENANCE de la population ─────────────────────────────


def _base(tmp_path, lignes) -> str:
    p = tmp_path / "t.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE shadow_setups (pair TEXT, bar_timestamp TEXT,"
              " timeframe TEXT, resolved_backfill INT, direction TEXT,"
              " entry_price REAL, stop_loss REAL, take_profit_1 REAL,"
              " outcome TEXT, pnl_pct_net REAL)")
    c.executemany("INSERT INTO shadow_setups VALUES (?,?,?,?,'buy',"
                  "100.0,99.0,101.8,'TP1',0.5)", lignes)
    c.commit()
    c.close()
    return str(p)


def test_la_population_est_EXACTEMENT_celle_du_banc_d_esperance(tmp_path):
    """🔑 LE TEST DE PROVENANCE.

    `lire_instants` doit rendre les memes lignes que `lire_reels` du banc
    d esperance pour le meme filtre. Une seconde implementation, meme fidele
    le jour ou elle est ecrite, divergerait -- c est exactement la faute du
    27/10, transposee de la DONNEE a la POPULATION.
    """
    db = _base(tmp_path, [
        ("BTC/USD", "2026-08-01T00:00:00+00:00", "5min", 0),
        ("BTC/USD", "2026-08-02T00:00:00+00:00", "5min", 0),
        ("ETH/USD", "2026-08-03T00:00:00+00:00", "5min", 0),
        ("BTC/USD", "2026-09-01T00:00:00+00:00", "5min", 0),   # hors borne
        ("BTC/USD", "2026-08-04T00:00:00+00:00", "5min", 1),   # rattrape
        ("BTC/USD", "2026-08-05T00:00:00+00:00", "1d", 0),     # autre horizon
        ("XAU/USD", "2026-08-06T00:00:00+00:00", "5min", 0),   # hors ensemble
    ])
    f = brf.parse_population(
        "resolved_backfill=0 AND timeframe=5min AND pair IN 7_BINANCE"
        " AND bar_timestamp < 2026-08-20")

    instants = brf.lire_instants(db, "5min", f)
    attendus = lire_reels(db, "5min", f)

    assert sum(map(len, instants.values())) == len(attendus) == 3
    assert sorted(x for v in instants.values() for x in v) == sorted(
        d["bar"].timestamp() for d in attendus)


def test_les_instants_sont_lus_en_UTC_quand_la_base_n_a_pas_de_fuseau(tmp_path):
    from datetime import datetime, timezone
    db = _base(tmp_path, [("BTC/USD", "2026-08-01T00:00:00", "5min", 0)])

    i = brf.lire_instants(db, "5min", brf.parse_population(
        "resolved_backfill=0 AND timeframe=5min"))

    attendu = datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp()
    assert i["BTC/USD"] == [attendu]


# ─── le critere ─────────────────────────────────────────────────────────────


def _critere(tmp_path, **surcharges) -> str:
    champs = {
        "statistique": "recouvrement_temporel_des_fenetres",
        "forme": "placebo", "horizon": "5min", "fenetre_heures": "96",
        "population": "resolved_backfill=0 AND timeframe=5min",
        "population_secondaire": "resolved_backfill=1 AND timeframe=5min",
        "tirages_placebo": "20", "graine": "20261027",
        "P1_recouvrement_moyen_min": "150",
        "P4_ratio_blocs_min": "1.00",
    }
    champs.update(surcharges)
    champs = {k: v for k, v in champs.items() if v is not None}
    corps = "\n".join(f"{k}: {v}" for k, v in champs.items())
    p = tmp_path / "c.md"
    p.write_text("# c\n\n<!-- CRITERE-MACHINE\n" + corps + "\n-->\n",
                 encoding="utf-8")
    return str(p)


def test_un_critere_SANS_population_secondaire_est_un_ARRET(tmp_path):
    """⛔ Les predictions portent sur les DEUX populations. En mesurer une
    seule rendrait un verdict sur un critere PARTIEL."""
    c = _critere(tmp_path, population_secondaire=None)

    with pytest.raises(SystemExit) as e:
        brf.Criteres(c)

    assert "population_secondaire" in str(e.value)


def test_un_critere_SANS_bloc_machine_est_un_ARRET(tmp_path):
    p = tmp_path / "vide.md"
    p.write_text("# rien\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        brf.Criteres(str(p))


def test_une_clause_de_population_INCONNUE_est_un_ARRET(tmp_path):
    c = _critere(tmp_path, population="volatilite > 3")

    with pytest.raises(SystemExit) as e:
        brf.Criteres(c)

    assert "NON RECONNUE" in str(e.value)


def test_les_predictions_sont_lues_par_NOM(tmp_path):
    cr = brf.Criteres(_critere(tmp_path))

    assert set(cr.predictions) == {"P1_recouvrement_moyen_min",
                                   "P4_ratio_blocs_min"}
    assert cr.predictions["P1_recouvrement_moyen_min"] == 150.0


def test_la_graine_et_les_tirages_viennent_du_CRITERE(tmp_path):
    cr = brf.Criteres(_critere(tmp_path, graine="99", tirages_placebo="7"))

    assert cr.graine == 99 and cr.tirages == 7


# ─── les predictions portent sur les DEUX populations ───────────────────────


def _m(**s):
    base = {"recouvrement_moyen": 300.0, "recouvrement_moyen_secondaire": 300.0,
            "ratio_somme_sur_union": 100.0,
            "ratio_somme_sur_union_secondaire": 100.0,
            "n_eff_naif": 30.0, "n_eff_naif_secondaire": 180.0,
            "ratio_blocs_placebo_sur_reel": 1.3,
            "ratio_blocs_placebo_sur_reel_secondaire": 1.2}
    base.update(s)
    return base


def test_une_prediction_ECHOUE_si_la_SECONDE_population_ne_la_tient_pas():
    """⛔ Le garde-fou contre le critere partiel, cote predictions."""
    _, test = brf.PREDICTIONS["P1_recouvrement_moyen_min"]

    assert test(_m(), 150.0) is True
    assert test(_m(recouvrement_moyen_secondaire=10.0), 150.0) is False
    assert test(_m(recouvrement_moyen=10.0), 150.0) is False


def test_la_prediction_du_RATIO_est_STRICTE_des_deux_cotes():
    _, mini = brf.PREDICTIONS["P4_ratio_blocs_min"]
    _, maxi = brf.PREDICTIONS["P5_ratio_blocs_max"]

    assert mini(_m(ratio_blocs_placebo_sur_reel=1.0), 1.0) is False
    assert maxi(_m(ratio_blocs_placebo_sur_reel=2.0), 2.0) is False
    assert maxi(_m(), 2.0) is True


def test_une_prediction_sur_un_champ_MANQUANT_echoue_sans_lever():
    _, test = brf.PREDICTIONS["P4_ratio_blocs_min"]

    assert test(_m(ratio_blocs_placebo_sur_reel=None), 1.0) is False


# ─── bout en bout : le POINT D ENTREE, pas seulement les fonctions pures ────


def _base_realiste(tmp_path) -> str:
    lignes = []
    for p in ("BTC/USD", "ETH/USD", "XRP/USD"):
        for i in range(120):
            from datetime import datetime, timedelta, timezone
            d = datetime(2026, 8, 1, tzinfo=timezone.utc) + timedelta(hours=2 * i)
            lignes.append((p, d.isoformat(), "5min", 0))
            lignes.append((p, (d + timedelta(days=40)).isoformat(), "5min", 1))
    return _base(tmp_path, lignes)


def test_main_tourne_VRAIMENT_et_ecrit_son_JSON(tmp_path):
    """⛔ Trois `NameError` sont passees devant des suites vertes qui
    n exercaient que les fonctions pures. On appelle `main()`."""
    db = _base_realiste(tmp_path)
    c = _critere(tmp_path, tirages_placebo="3")
    sortie = tmp_path / "r.json"

    code = brf.main(["--preinscription", c, "--db", db,
                     "--json", str(sortie)])

    assert code == 0
    m = json.loads(sortie.read_text(encoding="utf-8"))
    assert m["n"] == 360 and m["n_secondaire"] == 360
    assert m["paires"] == 3
    assert m["recouvrement_moyen"] > 0
    assert m["forme"] == "placebo" and m["valide"] is True


def test_le_RAPPORT_ne_lit_aucune_cle_que_le_RESULTAT_n_ecrit_pas(tmp_path):
    """⛔ Une mesure de douze minutes perdue sur un `KeyError` du rapport."""
    db = _base_realiste(tmp_path)
    cr = brf.Criteres(_critere(tmp_path, tirages_placebo="3"))

    m = brf.mesure(db, cr)
    texte = brf.rapport(m)   # ne doit pas lever

    assert "recouvrement moyen" in texte
    assert "blocs independants" in texte
    assert "DECISION  blocs uniforme/reel" in texte
    assert "MAXIMUM atteignable" in texte
    assert "VERDICT" in texte


def test_une_population_VIDE_rend_une_ERREUR_et_un_code_1(tmp_path):
    """⛔ « Aucune ligne » doit SORTIR EN ERREUR, pas rendre un resultat vide
    qui aurait l air normal -- la relance du 27/10 a lu une base a 73 lignes
    et s est arretee en code 0."""
    db = _base(tmp_path, [("BTC/USD", "2026-08-01T00:00:00+00:00", "5min", 0)])
    c = _critere(tmp_path)

    code = brf.main(["--preinscription", c, "--db", db])

    assert code == 1


def test_le_resultat_porte_les_CHAMPS_REQUIS_par_or_verdict(tmp_path):
    """`n`, `t` et `valide` -- sans eux la forme placebo est REFUSEE."""
    db = _base_realiste(tmp_path)
    cr = brf.Criteres(_critere(tmp_path, tirages_placebo="3"))

    m = brf.mesure(db, cr)

    for champ in ("n", "t", "valide"):
        assert champ in m and m[champ] is not None, champ


# ─── blocs effectifs : la VARIABLE DE DECISION, et son amplitude ────────────


def test_les_blocs_effectifs_valent_1_quand_tout_est_dans_UN_bloc():
    """Plancher de la statistique : une seule unite independante."""
    assert brf.blocs_effectifs([0.0, H, 2 * H], W) == pytest.approx(1.0)


def test_les_blocs_effectifs_comptent_les_blocs_EGALEMENT_peuples():
    """Trois amas de meme taille, espaces d une fenetre pleine => 3."""
    t = ([0.0, H] + [W + 0.0, W + H] + [2 * W + 0.0, 2 * W + H])

    assert brf.blocs_effectifs(t, W) == pytest.approx(3.0, abs=0.35)


def test_les_blocs_effectifs_PENALISENT_un_bloc_dominant():
    """Herfindahl : 100 instants dans un bloc et 1 dans un autre ne font
    pas « deux unites independantes »."""
    beaucoup = [float(i) for i in range(100)]
    isole = [2 * W + 1.0]

    v = brf.blocs_effectifs(beaucoup + isole, W)

    assert 1.0 < v < 1.1, v


def test_les_blocs_effectifs_ne_DEPENDENT_pas_d_UNE_SEULE_frontiere(monkeypatch):
    """⛔ TEST REECRIT : le premier ne discriminait RIEN, prouve par mutation.

    Il decalait TOUS les instants, or `origine0 = min(instants)` rend cela
    invariant d office : je testais une propriete automatique. Le vrai risque
    est un amas serre A CHEVAL sur une frontiere de bloc, qu une origine
    unique couperait en deux et ferait passer pour deux unites independantes.
    """
    # dix instants sur 0,09 fenetre, a cheval sur la frontiere a une fenetre
    amas = [0.0] + [0.95 * W + i * 0.01 * W for i in range(10)]

    moyenne = brf.blocs_effectifs(amas, W)
    monkeypatch.setattr(brf, "ORIGINES", (0.0,))
    une_seule = brf.blocs_effectifs(amas, W)

    assert une_seule > 1.9, une_seule          # l amas parait coupe en deux
    assert moyenne < une_seule - 0.2, (moyenne, une_seule)


def test_le_PLAFOND_de_chaque_statistique_est_PUBLIE_avec_elle(tmp_path):
    """⛔ LE GARDE-FOU QUI M A MANQUE, ET QUI A FAILLI COUTER UN 4e SEUIL.

    J ai engage un seuil a 2,00 sur le rapport des recouvrements sans verifier
    son amplitude : son MAXIMUM ATTEIGNABLE vaut ~2,04 dans ce regime, donc le
    seuil etait quasi infalsifiable. Un rapport ne veut rien dire sans la
    plage dans laquelle il vit : le banc doit donc la publier.
    """
    db = _base_realiste(tmp_path)
    cr = brf.Criteres(_critere(tmp_path, tirages_placebo="3"))

    m = brf.mesure(db, cr)

    for champ in ("ratio_recouvrement_MAXIMUM_ATTEIGNABLE",
                  "ratio_blocs_MAXIMUM_ATTEIGNABLE"):
        for suf in ("", "_secondaire"):
            assert m[champ + suf] is not None, champ + suf
            assert m[champ + suf] > 1.0, (champ + suf, m[champ + suf])

    # et le seuil de decision doit vivre SOUS le plafond de sa statistique
    assert (m["ratio_blocs_placebo_sur_reel"]
            <= m["ratio_blocs_MAXIMUM_ATTEIGNABLE"] + 1e-9)


def test_le_rapport_des_RECOUVREMENTS_sature_mais_pas_celui_des_BLOCS():
    """🔑 LA MESURE QUI JUSTIFIE LE CHANGEMENT DE VARIABLE DE DECISION.

    Sur une agglomeration TOTALE -- tous les instants dans une fenetre --, le
    rapport des recouvrements atteint son plafond etroit, tandis que celui des
    blocs monte franchement.
    """
    import random
    etendue = 400 * H
    alea = random.Random(5)
    tout_colle = {"A": [alea.uniform(0, 1 * H) for _ in range(300)]
                       + [etendue]}

    r = brf.compare_a_la_structure_uniforme(tout_colle, W, tirages=10,
                                            graine=11)

    assert r["ratio_recouvrement_reel_sur_placebo"] < 2.5
    assert r["ratio_blocs_placebo_sur_reel"] > 2.5
