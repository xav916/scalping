"""L'horizon `1d` est ECARTE du vivier qui decide l'admission des paires.

DECISION DE XAVIER le 2026-10-27, sur le verdict `0b8106b` : l'espérance du
`1d` vaut **−0,0641 R** contre **+0,0413 R** pour des entrées au hasard, et le
réel ne bat **aucun** des 200 tirages (`t = −4,23`).

⛔ POURQUOI CE N'EST PAS UNE SIMPLE PREFERENCE. `_fetch_peer_control_rows`
alimente `peer_control_for_pair`, qui est une condition NECESSAIRE au passage
d'une paire en AUTO_EXEC. Sa requete n'avait AUCUN filtre de timeframe : les
1 016 lignes `1d` du vivier pesaient donc sur l'admission de paires qui, elles,
sont tradees en `5min` et `4h`.

⚠️ CE QUI N'EST PAS FAIT ICI, et c'est volontaire : la GENERATION des setups
`1d` continue. Le verdict n'a aucune mesure hors echantillon, et la seule autre
fenetre disponible (08 -> 20/08, n=288, +0,5483 R) dit l'inverse -- sans
chevauchement temporel, donc sans comparaison possible. Couper l'observation
interdirait de trancher plus tard.
"""
from __future__ import annotations

import sqlite3

import pytest

from backend.services import pair_admission_controller as pac


@pytest.fixture
def db(tmp_path, monkeypatch):
    chemin = tmp_path / "pac_1d.db"
    with sqlite3.connect(chemin) as c:
        c.execute("""
            CREATE TABLE shadow_setups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT, bar_timestamp TIMESTAMP, timeframe TEXT,
                direction TEXT, outcome TEXT,
                risk_pct REAL, pnl_pct_net REAL,
                resolved_backfill INTEGER NOT NULL DEFAULT 0
            )""")
    monkeypatch.setattr(pac, "_db_path", lambda: str(chemin))
    monkeypatch.setattr(
        "backend.services.shadow_v2_core_long.ensure_schema", lambda: None)
    return chemin


def _pose(db, tf, pair="EUR/USD", sens="buy", issue="TP1",
          risk=0.01, pnl=1.8, bar="2026-09-15T04:00:00+00:00"):
    with sqlite3.connect(db) as c:
        c.execute(
            "INSERT INTO shadow_setups (pair, bar_timestamp, timeframe,"
            " direction, outcome, risk_pct, pnl_pct_net)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pair, bar, tf, sens, issue, risk, pnl))


def test_les_lignes_1d_sont_ECARTEES_du_vivier(db):
    """LE TEST CENTRAL."""
    _pose(db, "5min")
    _pose(db, "4h")
    _pose(db, "1d")
    _pose(db, "1d")

    lignes = pac._fetch_peer_control_rows("buy")

    assert len(lignes) == 2, [l[0] for l in lignes]


def test_les_AUTRES_horizons_sont_INTACTS(db):
    """⛔ Le defaut a eviter : un filtre trop large qui vide le vivier."""
    for tf in ("5min", "5min", "4h", "1h"):
        _pose(db, tf)

    assert len(pac._fetch_peer_control_rows("buy")) == 4


def test_l_exclusion_est_DESARMABLE(db, monkeypatch):
    """Le verdict n'a pas de hors echantillon, et l'autre fenetre dit
    l'inverse : cette decision doit pouvoir etre defaite en une variable."""
    _pose(db, "5min")
    _pose(db, "1d")

    monkeypatch.setattr(pac, "PAC_EXCLURE_HORIZON_1D", False)

    assert len(pac._fetch_peer_control_rows("buy")) == 2, (
        "desarmee, l'exclusion ne doit plus rien retirer")


def test_l_exclusion_est_ARMEE_par_defaut(db):
    """C'est la decision de Xavier : armee, pas proposee."""
    assert pac.PAC_EXCLURE_HORIZON_1D is True


def test_le_filtre_de_SENS_tient_toujours(db):
    _pose(db, "5min", sens="buy")
    _pose(db, "5min", sens="sell")
    _pose(db, "1d", sens="sell")

    assert len(pac._fetch_peer_control_rows("sell")) == 1


def test_un_timeframe_NUL_n_est_pas_pris_pour_du_1d(db):
    """⛔ `timeframe != '1d'` est FAUX en SQL quand la colonne est NULL : une
    ligne sans timeframe disparaitrait silencieusement du vivier. Ce sont des
    lignes anciennes et legitimes -- elles doivent rester."""
    with sqlite3.connect(db) as c:
        c.execute(
            "INSERT INTO shadow_setups (pair, bar_timestamp, timeframe,"
            " direction, outcome, risk_pct, pnl_pct_net)"
            " VALUES ('EUR/USD', '2026-09-15T04:00:00+00:00', NULL,"
            " 'buy', 'TP1', 0.01, 1.8)")

    lignes = pac._fetch_peer_control_rows("buy")

    assert len(lignes) == 1, (
        "une ligne sans timeframe a ete perdue par le filtre", lignes)


def test_les_conditions_d_origine_tiennent(db):
    """Ni TIMEOUT, ni pnl nul, ni risk nul, ni hors fenetre saine."""
    _pose(db, "5min", issue="TIMEOUT")
    _pose(db, "5min", pnl=None)
    _pose(db, "5min", risk=0.0)
    _pose(db, "5min", bar="2026-07-01T00:00:00+00:00")
    _pose(db, "5min")

    assert len(pac._fetch_peer_control_rows("buy")) == 1
