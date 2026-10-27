"""Les lignes RATTRAPEES sont ecartees du vivier qui decide l'admission.

DECISION DE XAVIER le 2026-10-27, apres mesure.

⛔ LE DEFAUT QUE CA CORRIGE, et il est de MOI. Le rattrapage du 2026-10-26 a
injecte 21 805 issues dans `shadow_setups`. Mesure du vivier `peer_control` le
lendemain : **20 498 lignes sur 26 465, soit 77,5 %**, etaient de la donnee
rattrapee -- dans un mecanisme qui est condition NECESSAIRE au passage d'une
paire en AUTO_EXEC. Et son esperance est de signe OPPOSE au vecu :
**-0,0333 R** contre **+0,0919 R**.

🔑 La colonne `resolved_backfill` existe precisement pour permettre de mesurer
AVEC et SANS. `pair_admission_controller` ne la lisait pas.

COUT MESURE AVANT D'ARMER : 5 paires cote ACHAT perdent le controle inter-paires
(EUR/GBP 170->29, USD/CHF 146->29, EUR/JPY 138->27, GBP/JPY 131->25, XAG/USD
53->0). Cote vente, aucune perte. Le seuil est 30 (`block_size` 10 x
`min_domain_blocks` 3). Quatre des cinq sont a 25-29, donc repasseraient la
barre en quelques semaines de donnee vecue -- la reconciliation remarche.
⚠️ Le controle conditionne le PASSAGE en AUTO_EXEC, pas le maintien : ces
paires y sont deja, elles ne pourraient plus y REVENIR automatiquement.
"""
from __future__ import annotations

import sqlite3

import pytest

from backend.services import pair_admission_controller as pac


@pytest.fixture
def db(tmp_path, monkeypatch):
    chemin = tmp_path / "pac_rattrapes.db"
    with sqlite3.connect(chemin) as c:
        c.execute("""
            CREATE TABLE shadow_setups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT, bar_timestamp TIMESTAMP, timeframe TEXT,
                direction TEXT, outcome TEXT,
                risk_pct REAL, pnl_pct_net REAL,
                resolved_backfill INTEGER
            )""")
    monkeypatch.setattr(pac, "_db_path", lambda: str(chemin))
    monkeypatch.setattr(
        "backend.services.shadow_v2_core_long.ensure_schema", lambda: None)
    return chemin


def _pose(db, rattrape, tf="5min", pair="EUR/USD", sens="buy"):
    with sqlite3.connect(db) as c:
        c.execute(
            "INSERT INTO shadow_setups (pair, bar_timestamp, timeframe,"
            " direction, outcome, risk_pct, pnl_pct_net, resolved_backfill)"
            " VALUES (?, '2026-09-15T04:00:00+00:00', ?, ?, 'TP1', 0.01, 1.8, ?)",
            (pair, tf, sens, rattrape))


def test_les_lignes_RATTRAPEES_sont_ECARTEES(db):
    """LE TEST CENTRAL."""
    _pose(db, rattrape=0)
    _pose(db, rattrape=0)
    _pose(db, rattrape=1)
    _pose(db, rattrape=1)
    _pose(db, rattrape=1)

    assert len(pac._fetch_peer_control_rows("buy")) == 2


def test_les_lignes_VECUES_sont_INTACTES(db):
    """⛔ Le defaut symetrique : un filtre qui vide tout le vivier."""
    for _ in range(4):
        _pose(db, rattrape=0)

    assert len(pac._fetch_peer_control_rows("buy")) == 4


def test_une_valeur_NULLE_est_traitee_comme_VECUE(db):
    """⛔ MEME PIEGE QUE POUR LE 1d, et il vient d'etre paye une fois.

    `resolved_backfill = 0` est FAUX quand la colonne vaut NULL. La migration
    l'a posee en `NOT NULL DEFAULT 0`, donc aucun NULL n'existe aujourd'hui --
    mais une base plus ancienne, une table de test, ou un futur
    `ALTER TABLE` sans defaut en recreeraient. Une ligne NULL est une ligne
    VECUE (la colonne n'existait pas quand elle a ete ecrite) : elle doit
    RESTER.
    """
    _pose(db, rattrape=None)
    _pose(db, rattrape=0)
    _pose(db, rattrape=1)

    lignes = pac._fetch_peer_control_rows("buy")

    assert len(lignes) == 2, (
        "la ligne a resolved_backfill NULL a ete perdue", lignes)


def test_l_exclusion_est_DESARMABLE(db, monkeypatch):
    _pose(db, rattrape=0)
    _pose(db, rattrape=1)

    monkeypatch.setattr(pac, "PAC_EXCLURE_RATTRAPES", False)

    assert len(pac._fetch_peer_control_rows("buy")) == 2


def test_l_exclusion_est_ARMEE_par_defaut(db):
    assert pac.PAC_EXCLURE_RATTRAPES is True


def test_les_DEUX_exclusions_se_CUMULENT(db):
    """1d et rattrape sont deux decisions distinctes, et les deux s'appliquent."""
    _pose(db, rattrape=0, tf="5min")   # garde
    _pose(db, rattrape=0, tf="1d")     # retire par l'exclusion 1d
    _pose(db, rattrape=1, tf="5min")   # retire par l'exclusion rattrape
    _pose(db, rattrape=1, tf="1d")     # retire par les deux

    assert len(pac._fetch_peer_control_rows("buy")) == 1


def test_les_conditions_d_origine_tiennent_toujours(db):
    """Ni le sens, ni la fenetre saine, ni les issues ne doivent bouger."""
    _pose(db, rattrape=0, sens="sell")
    _pose(db, rattrape=0, sens="buy")
    with sqlite3.connect(db) as c:
        c.execute(
            "INSERT INTO shadow_setups (pair, bar_timestamp, timeframe,"
            " direction, outcome, risk_pct, pnl_pct_net, resolved_backfill)"
            " VALUES ('EUR/USD', '2026-07-01T00:00:00+00:00', '5min',"
            " 'buy', 'TP1', 0.01, 1.8, 0)")

    assert len(pac._fetch_peer_control_rows("buy")) == 1
    assert len(pac._fetch_peer_control_rows("sell")) == 1
