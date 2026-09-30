#!/usr/bin/env python3
"""REM-005 — le ledger financier, éprouvé.

⛔ CE QUE CETTE SUITE DOIT ATTRAPER, et qui est le seul vrai danger du
chantier : **un champ inconnu écrit comme un zéro**. Une table à 31 colonnes
toutes remplies a l'air d'un succès et rend indéfendable tout ce qu'on en
tire. Plusieurs tests ci-dessous échouent donc précisément si un `0` remplace
un `None`, et non si un calcul est « un peu faux ».

🔑 Chaque test dit QUEL DÉFAUT il attrape. Un test qui ne nomme pas son
défaut ne sait pas s'il mord (cf. les 15 tests portés par le fail-open du
25/09, tous verts sur une porte débranchée).
"""

from __future__ import annotations

import sqlite3

import pytest

from backend.services import trade_ledger as ledger

# --------------------------------------------------------------------------
# Le banc : une base minuscule qui a la FORME de la production.
# ⛔ Pas une doublure inventée — les noms de colonnes sont ceux relevés le
# 01/10 sur `/app/data/trades.db`. Une doublure qui n'a pas la forme de la
# prod rend la suite verte sur un no-op.

SCHEMA = """
create table personal_trades (
  id integer primary key, user text, pair text, direction text,
  entry_price real, stop_loss real, take_profit real, size_lot real,
  signal_pattern text, signal_confidence real, checklist_passed integer,
  notes text, status text, exit_price real, pnl real, created_at text,
  closed_at text, post_entry_sl real, post_entry_tp real,
  post_entry_size real, post_entry_alarm text, mt5_ticket text,
  is_auto integer, context_macro text, signal_id text, fill_price real,
  slippage_pips real, close_reason text, user_id integer,
  destination_id text, sl_at_close real, tp_at_close real,
  niveaux_source text, horizon text, source text, motif_interne text,
  motif_interne_detail text);
create table broker_close_snapshots (
  ticket text, bridge text, reason text, entry_price real, exit_price real,
  volume real, pnl real, pnl_net real, swap real, commission real,
  fee real, closed_at text, niveau_declencheur real, niveaux_source text,
  n_deals integer, vu_le text, brut text);
create table mt5_pushes (
  id integer primary key, destination_id text, date text, pair text,
  direction text, entry_price_5dp real, pushed_at text, ok integer,
  bridge_response text, horizon text, pattern text, mt5_ticket text,
  source text, chaine text);
"""


def _trade(conn, **kw):
    base = dict(id=1, pair="XAU/USD", direction="buy", entry_price=3800.0,
                stop_loss=3795.0, take_profit=3809.0, size_lot=0.01,
                exit_price=3795.0, pnl=-5.0, created_at="2026-09-20T10:00:00",
                closed_at="2026-09-20T11:00:00", mt5_ticket="1000",
                is_auto=1, close_reason="SL", destination_id="admin_live")
    base.update(kw)
    cols = ",".join(base)
    conn.execute("insert into personal_trades (%s) values (%s)"
                 % (cols, ",".join("?" * len(base))), tuple(base.values()))


def _courtier(conn, **kw):
    base = dict(ticket="1000", reason="SL", entry_price=3800.2,
                exit_price=3795.1, volume=0.01, pnl=-5.1, pnl_net=-5.1,
                swap=0.0, commission=0.0, fee=0.0,
                closed_at="2026-09-20T11:00:02")
    base.update(kw)
    cols = ",".join(base)
    conn.execute("insert into broker_close_snapshots (%s) values (%s)"
                 % (cols, ",".join("?" * len(base))), tuple(base.values()))


@pytest.fixture()
def banc():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    yield conn
    conn.close()


def _lire(conn, trade_id=1):
    ledger.construire(conn)
    conn.row_factory = sqlite3.Row
    return conn.execute("select * from %s where trade_id=?" % ledger.TABLE,
                        (trade_id,)).fetchone()


# --------------------------------------------------------------------------
# 1. La correspondance au cahier

def test_les_31_colonnes_du_cahier_mot_pour_mot():
    """⛔ DÉFAUT ATTRAPÉ : renommer une colonne « pour faire plus clair »
    casserait la correspondance avec le document d'audit, qui est la seule
    raison d'être de la table."""
    assert ledger.COLONNES_CAHIER == (
        "trade_id", "broker_trade_id", "account_id", "environment",
        "strategy_id", "experiment_id", "signal_id", "chain_id",
        "human_intervention", "bug_affected", "execution_type",
        "entry_requested", "entry_executed", "exit_executed",
        "quantity", "stop", "take_profit",
        "gross_pnl", "spread_cost", "commission", "swap", "slippage",
        "fx_effect", "net_pnl", "risk_amount", "r_multiple",
        "opened_at", "closed_at", "close_reason",
        "deployment_commit", "configuration_hash")
    assert len(ledger.COLONNES_CAHIER) == 31


def test_la_table_porte_toutes_les_colonnes(banc):
    ledger.creer_table(banc)
    reels = {r[1] for r in banc.execute("pragma table_info(%s)" % ledger.TABLE)}
    manquantes = set(ledger.COLONNES_CAHIER) - reels
    assert not manquantes, "colonnes du cahier absentes : %s" % manquantes


def test_une_colonne_ajoutee_apres_coup_est_RATTRAPEE(banc):
    """⛔ DÉFAUT ATTRAPÉ : `CREATE TABLE IF NOT EXISTS` ne touche pas une
    table existante. Sans rattrapage, la table d'hier resterait amputée de la
    colonne d'aujourd'hui et `construire()` mourrait — ou écrirait un ledger
    incomplet en silence."""
    banc.execute("create table %s (trade_id INTEGER PRIMARY KEY)"
                 % ledger.TABLE)
    ajoutees = ledger.creer_table(banc)
    assert "categorie_pnl" in ajoutees
    assert "net_pnl" in ajoutees
    reels = {r[1] for r in banc.execute("pragma table_info(%s)" % ledger.TABLE)}
    assert not set(ledger.COLONNES_CAHIER) - reels
    # 🔑 ET LE RATTRAPAGE EST IDEMPOTENT : au second passage, rien à ajouter.
    assert ledger.creer_table(banc) == []


def test_une_colonne_rattrapee_vaut_NULL_pas_ZERO(banc):
    """⛔ Un `DEFAULT 0` sur l'`ALTER TABLE` réécrirait toute l'histoire avec
    une affirmation : « le net de ces 1 353 trades valait zéro »."""
    banc.execute("create table %s (trade_id INTEGER PRIMARY KEY)"
                 % ledger.TABLE)
    banc.execute("insert into %s (trade_id) values (7)" % ledger.TABLE)
    ledger.creer_table(banc)
    banc.row_factory = sqlite3.Row
    li = banc.execute("select * from %s where trade_id=7"
                      % ledger.TABLE).fetchone()
    assert li["net_pnl"] is None
    assert li["bug_affected"] is None
    assert li["categorie_pnl"] is None


# --------------------------------------------------------------------------
# 2. LE CŒUR : aucun zéro fabriqué

def test_sans_instantane_courtier_l_argent_est_NUL_pas_ZERO(banc):
    """⛔ LE DÉFAUT CENTRAL DU CHANTIER. Sans instantané, le swap, la
    commission et le net sont INCONNUS. Les écrire à 0 affirmerait « le swap
    était nul » sur 848 trades, et rendrait faux tout calcul de coût."""
    _trade(banc)  # aucun instantané courtier
    li = _lire(banc)
    assert li["net_pnl"] is None, "net_pnl fabrique au lieu d etre inconnu"
    assert li["swap"] is None, "swap fabrique a 0 — affirmation non fondee"
    assert li["commission"] is None, "commission fabriquee a 0"
    assert li["src_argent"] == "stock"


def test_le_zero_du_COURTIER_est_ecrit_lui(banc):
    """🔑 LE PENDANT DU TEST PRÉCÉDENT, et il est indispensable : la règle
    n'est pas « jamais de zéro » mais « jamais de zéro INVENTÉ ». Le payload
    brut porte bien `commission` et le courtier y répond `0.0` — refuser de
    l'écrire perdrait une information vraie."""
    _trade(banc)
    _courtier(banc, swap=0.0, commission=0.0)
    li = _lire(banc)
    assert li["commission"] == 0.0
    assert li["swap"] == 0.0
    assert li["src_argent"] == "courtier"


def test_un_swap_non_nul_du_courtier_est_conserve(banc):
    _trade(banc)
    _courtier(banc, pnl=0.43, pnl_net=-2.54, swap=-2.97)
    li = _lire(banc)
    assert li["gross_pnl"] == pytest.approx(0.43)
    assert li["net_pnl"] == pytest.approx(-2.54)
    assert li["swap"] == pytest.approx(-2.97)


def test_bug_affected_est_NUL_hors_des_dix_ordres(banc):
    """⛔ Un `0` ici voudrait dire « ce trade n'est affecté par aucun
    défaut » — une affirmation qui demanderait d'avoir audité tous les
    défauts du projet. Personne ne l'a fait."""
    _trade(banc, mt5_ticket="999999")
    assert _lire(banc)["bug_affected"] is None


def test_bug_affected_marque_les_dix_ordres_de_la_chaine(banc):
    """🔑 TÉMOIN POSITIF : sans lui, le test précédent passerait aussi sur un
    module qui ne marque JAMAIS rien."""
    _trade(banc, mt5_ticket="1359026109")
    assert _lire(banc)["bug_affected"] == 1
    assert len(ledger.TICKETS_BUG_CHAINE) == 10


# --------------------------------------------------------------------------
# 3. Le prix d'exécution ne doit jamais être confondu avec l'intention

def test_entry_executed_ne_tombe_JAMAIS_sur_entry_price(banc):
    """⛔ DÉFAUT ATTRAPÉ : `entry_price` du stock est un mélange — parfois le
    prix du signal, parfois le remplissage (217 lignes valaient 0 avant le
    rattrapage du 24/08). L'utiliser comme exécution noierait le slippage
    dans du bruit en le faisant paraître mesuré."""
    _trade(banc, entry_price=3800.0, fill_price=None)  # pas d'instantané
    li = _lire(banc)
    assert li["entry_executed"] is None, \
        "entry_executed est retombe sur entry_price — le slippage devient faux"
    assert li["src_entree"] is None


def test_entry_executed_prefere_le_courtier_a_fill_price(banc):
    _trade(banc, fill_price=3800.9)
    _courtier(banc, entry_price=3800.2)
    li = _lire(banc)
    assert li["entry_executed"] == pytest.approx(3800.2)
    assert li["src_entree"] == "courtier"


def test_entry_executed_retombe_sur_fill_price_sans_courtier(banc):
    _trade(banc, fill_price=3800.9)
    li = _lire(banc)
    assert li["entry_executed"] == pytest.approx(3800.9)
    assert li["src_entree"] == "fill_price"


def test_entry_requested_vient_du_push_pas_du_stock(banc):
    _trade(banc)
    banc.execute("insert into mt5_pushes (mt5_ticket, entry_price_5dp, chaine)"
                 " values (?,?,?)", ("1000", 3799.55, "chaine:sweep"))
    li = _lire(banc)
    assert li["entry_requested"] == pytest.approx(3799.55)
    assert li["chain_id"] == "chaine:sweep"


# --------------------------------------------------------------------------
# 4. Le R se calcule sur l'argent, et seulement quand l'argent est connu

def test_r_multiple_est_NUL_quand_le_net_est_inconnu(banc):
    """⛔ DÉFAUT ATTRAPÉ : diviser un P&L BRUT par le risque produirait un R
    qui ignore le swap, tout en ayant l'air d'un R. Le risque, lui, reste
    calculable et doit être écrit."""
    _trade(banc)  # pas d'instantané -> net inconnu
    li = _lire(banc)
    assert li["risk_amount"] is not None and li["risk_amount"] > 0
    assert li["src_risque"] == "calcule"
    assert li["r_multiple"] is None, "R calcule sur un brut — silencieusement faux"


def test_r_multiple_vaut_net_sur_risque(banc):
    _trade(banc)
    _courtier(banc, pnl_net=-5.1)
    li = _lire(banc)
    assert li["r_multiple"] == pytest.approx(-5.1 / li["risk_amount"], rel=1e-6)


def test_risque_incalculable_laisse_tout_NUL(banc):
    """Sans stop, il n'y a pas de risque — donc pas de R. ⛔ Un 0 ici ferait
    d'un trade non dimensionné un trade « sans risque »."""
    _trade(banc, stop_loss=None)
    li = _lire(banc)
    assert li["risk_amount"] is None
    assert li["r_multiple"] is None
    assert li["src_risque"] is None


# --------------------------------------------------------------------------
# 5. L'environnement passe par le juge de la production

def test_environment_sans_destination_est_INCONNU(banc):
    """⛔ DÉFAUT ATTRAPÉ : 385 trades sont antérieurs à la notion de
    destination. Les classer « DEMO par défaut » ferait passer pour de la
    démo des trades dont on ignore s'ils ont touché de l'argent réel — le
    sens exact de la faute serait inversé."""
    _trade(banc, destination_id=None)
    li = _lire(banc)
    assert li["environment"] is None
    assert li["account_id"] is None


def test_environment_suit_le_registre(banc):
    """🔑 Le même juge que la production : deux définitions d'« argent réel »
    finissent toujours par divorcer."""
    _trade(banc, id=1, mt5_ticket="1", destination_id="admin_live")
    _trade(banc, id=2, mt5_ticket="2", destination_id="admin_legacy")
    ledger.construire(banc)
    banc.row_factory = sqlite3.Row
    vus = {r["trade_id"]: r["environment"] for r in
           banc.execute("select trade_id, environment from %s" % ledger.TABLE)}
    assert vus == {1: "REAL", 2: "DEMO"}


# --------------------------------------------------------------------------
# 6. La clôture : le motif fin, et qui l'atteste

def test_le_motif_FIN_du_stock_est_conserve(banc):
    """🔑 Le courtier résume `TP1` en `TP` et `TRAILING_SL` en `SL`. Prendre
    le motif du courtier perdrait 50 distinctions utiles."""
    _trade(banc, close_reason="TRAILING_SL")
    _courtier(banc, reason="SL")
    li = _lire(banc)
    assert li["close_reason"] == "TRAILING_SL"
    assert li["src_cloture"] == "courtier_confirme"


def test_un_MANUAL_orphelin_est_signale_comme_tel(banc):
    """⚠️ `MANUAL` a été écrit PAR DÉFAUT pendant une période (défaut du
    10/08). Sans `src_cloture`, une main attestée et une main supposée
    deviennent indistinguables."""
    _trade(banc, close_reason="MANUAL")
    li = _lire(banc)
    assert li["human_intervention"] == 1
    assert li["src_cloture"] == "stock_seul"


def test_sans_motif_la_main_est_INCONNUE_pas_ABSENTE(banc):
    """⛔ Un `0` dirait « aucune main n'est intervenue » sur 13 trades dont
    on ignore comment ils se sont fermés."""
    _trade(banc, close_reason=None)
    li = _lire(banc)
    assert li["human_intervention"] is None
    assert li["close_reason"] is None


# --------------------------------------------------------------------------
# 7. Les vides assumés restent vides

def test_les_colonnes_sans_source_restent_NULLES(banc):
    """⛔ DÉFAUT ATTRAPÉ : remplir `strategy_id` avec `signal_pattern`
    inventerait une taxonomie, et `configuration_hash` avec l'empreinte
    actuelle signerait l'histoire avec « un nombre crédible et faux »."""
    _trade(banc, signal_pattern="fvg_up")
    _courtier(banc)
    li = _lire(banc)
    for col in ("strategy_id", "experiment_id", "spread_cost", "fx_effect",
                "deployment_commit", "configuration_hash"):
        assert li[col] is None, "%s a ete rempli sans source" % col


# --------------------------------------------------------------------------
# 8. L'invariant qui protège le P&L

def test_une_jointure_DEMULTIPLIEE_annule_l_ecriture(banc):
    """⛔ LE DÉFAUT LE PLUS COÛTEUX qu'on puisse imaginer ici : un doublon de
    clé dupliquerait des trades et gonflerait le P&L EN SILENCE. Les clés
    sont uniques le 01/10 ; rien ne garantit qu'elles le restent."""
    _trade(banc)
    _courtier(banc, ticket="1000", pnl_net=-5.1)
    _courtier(banc, ticket="1000", pnl_net=-5.1)  # le doublon
    with pytest.raises(RuntimeError, match="DÉMULTIPLIÉE"):
        ledger.construire(banc)
    n = banc.execute("select count(*) from %s" % ledger.TABLE).fetchone()[0]
    assert n == 0, "le ledger demultiplie a ete ECRIT malgre la garde"


def test_reconstruire_ne_duplique_pas(banc):
    _trade(banc)
    ledger.construire(banc)
    ledger.construire(banc)
    n = banc.execute("select count(*) from %s" % ledger.TABLE).fetchone()[0]
    assert n == 1


# --------------------------------------------------------------------------
# 9. L'identité du courtier, avec le bon signe

def test_l_identite_du_courtier_a_le_BON_SIGNE(banc):
    """⛔ DÉFAUT VÉCU, puis corrigé : écrite `brut − net = swap + …`, elle
    déclarait 78 lignes divergentes sur 496. La vraie forme est
    `net = brut + swap + commission + fee`. Un signe inversé transformerait
    une base saine en 16 % d'anomalies imaginaires."""
    ledger.creer_table(banc)
    _courtier(banc, ticket="A", pnl=0.43, pnl_net=-2.54, swap=-2.97)
    _courtier(banc, ticket="B", pnl=19.76, pnl_net=43.65, swap=0.0)
    v = ledger.verifier_identite_courtier(banc)
    assert v["concordent"] == 1, "le signe du swap est inverse"
    assert v["divergent"] == 1
    assert v["pires"][0]["ticket"] == "B"
    assert v["pires"][0]["ecart"] == pytest.approx(23.89, abs=0.01)


# --------------------------------------------------------------------------
# 10. REM-006 — la classification

def test_les_trois_categories_du_cahier():
    assert ledger.CAT_ALGO == "VALID_ALGORITHM"
    assert ledger.CAT_RECHERCHE == "RESEARCH_EXPERIMENT"
    assert ledger.CAT_MAIN == "HUMAN_INTERVENTION"


def test_la_main_passe_AVANT_l_environnement():
    """🔑 Une clôture manuelle sur l'argent réel appartient à la main, pas à
    l'algorithme : c'est la main qui a décidé du résultat. L'ordre des tests
    dans la fonction est donc porteur du sens."""
    assert ledger.categorie_pnl(1, "REAL") == ledger.CAT_MAIN
    assert ledger.categorie_pnl(1, "DEMO") == ledger.CAT_MAIN


def test_la_demo_est_de_la_RECHERCHE():
    assert ledger.categorie_pnl(0, "DEMO") == ledger.CAT_RECHERCHE
    assert ledger.categorie_pnl(0, "REAL") == ledger.CAT_ALGO


def test_un_environnement_inconnu_n_est_PAS_classable():
    """⛔ DÉFAUT ATTRAPÉ : classer par défaut ferait entrer 385 trades
    d'origine inconnue dans le compte de performance de l'algorithme."""
    assert ledger.categorie_pnl(0, None) is None
    assert ledger.categorie_pnl(None, None) is None


def test_un_ordre_defectueux_reste_algorithmique_et_FLAGUE(banc):
    """⛔ DÉFAUT ATTRAPÉ : ranger un ordre né du fail-open dans
    `RESEARCH_EXPERIMENT` le blanchirait en expérience. Il reste
    algorithmique — c'est bien l'algorithme qui l'a émis — et c'est
    `bug_affected` qui porte le défaut, dans une colonne séparée."""
    _trade(banc, mt5_ticket="1359026109", close_reason="SL")
    _courtier(banc, ticket="1359026109")
    li = _lire(banc)
    assert li["categorie_pnl"] == ledger.CAT_ALGO
    assert li["bug_affected"] == 1


def test_le_rapport_exclut_l_argent_NON_VERIFIE(banc):
    """⛔ LE DÉFAUT LE PLUS SOURNOIS DU RAPPORT : `sum()` ignore les NULL
    sans le dire. Sommer sur tous les trades publierait le total des 36,7 %
    mesurés en le présentant comme celui des 100 %."""
    _trade(banc, id=1, mt5_ticket="1", pnl=-5.0)           # sans instantané
    _trade(banc, id=2, mt5_ticket="2", pnl=-9.0)
    _courtier(banc, ticket="2", pnl_net=-9.9)
    ledger.construire(banc)

    # ⛔ SANS ARGUMENT — et c'est le point. Une mutation du DÉFAUT de
    # `verifie_seulement` a survécu à une première version de ce test, qui
    # passait la valeur explicitement : le défaut n'était donc jamais
    # éprouvé, alors que c'est lui que le rapport de production utilise.
    verifie = ledger.rapport_categories(banc)
    assert sum(li["trades"] for li in verifie) == 1, \
        "le rapport a compte un trade dont le net est inconnu"
    assert verifie[0]["net"] == pytest.approx(-9.9)

    assert ledger.rapport_categories(banc, verifie_seulement=True) == verifie

    tout = ledger.rapport_categories(banc, verifie_seulement=False)
    assert sum(li["trades"] for li in tout) == 2
    # 🔑 LA PREUVE DU DANGER : 2 trades comptés, 1 seul net connu. Sans
    # `net_connu_sur`, ce total ressemblerait a celui des deux.
    assert sum(li["net_connu_sur"] for li in tout) == 1


# --------------------------------------------------------------------------
# 11. Le rapport mesure bien le vide

def test_le_rapport_compte_le_VIDE_et_pas_les_lignes(banc):
    """🔑 Si le rapport comptait les lignes au lieu des valeurs non nulles,
    il afficherait 100 % partout et le ledger aurait l'air complet."""
    _trade(banc)
    ledger.construire(banc)
    par_col = {li["colonne"]: li for li in ledger.rapport_completude(banc)}
    assert par_col["trade_id"]["pct"] == 100.0
    assert par_col["strategy_id"]["pct"] == 0.0
    assert par_col["net_pnl"]["pct"] == 0.0
