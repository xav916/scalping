"""Un P&L inconnu ne doit pas s'écrire comme un P&L nul.

Constaté le 2026-08-09. Les trois positions Kraken du jour — ETHFI, SEI, CRV —
ont été fermées **hors du système** : les fills de clôture portent des
``order_id`` neufs, qui ne sont ni l'ordre d'ouverture, ni le SL, ni le TP. Le
bridge n'a vu aucun ``POST`` ce jour-là hormis les deux ouvertures.

``kraken_sync`` refuse alors d'attribuer, **et c'est le bon choix** : son
en-tête le dit, « aucun rapprochement par prix ou par horodatage n'est tenté ».
Il pose donc ``pnl_usd = None``.

⛔ **Le défaut est à l'écriture.** ``pnl = COALESCE(?, pnl)`` avec ``?`` à
``None`` laisse la colonne à sa valeur d'insertion, ``0.0``. Un P&L **inconnu**
devient donc indiscernable d'un trade **à plat** — alors que
``recent_pnl_multiplier``, ``pair_admission_controller``, ``pair_pnl_regulator``
et ``promotion_engine`` somment tous cette colonne.

> **Une absence rendue comme une valeur.** Le motif de la journée entière, cf.
> [[feedback_detection_par_absence]].

La convention « NULL = inconnu » existe déjà dans le code : ``insights_service``
agrège explicitement sur ``pnl NOT NULL``. On l'applique donc, au lieu de
mentir avec un zéro.

⚠️ On ne touche PAS au refus d'attribuer. Ce que ces tests verrouillent, c'est
que le refus soit **lisible** : cause distincte et montant nul-inconnu.
"""
import sqlite3

import pytest

from backend.services import kraken_sync


@pytest.fixture
def db(tmp_path, monkeypatch):
    f = tmp_path / "trades.db"
    c = sqlite3.connect(f)
    c.execute("""
        CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY, user TEXT, pair TEXT, direction TEXT,
            entry_price REAL, stop_loss REAL, take_profit REAL, size_lot REAL,
            status TEXT, exit_price REAL, pnl REAL DEFAULT 0.0,
            created_at TEXT, closed_at TEXT, close_reason TEXT,
            mt5_ticket TEXT, is_auto INTEGER, signal_pattern TEXT,
            signal_confidence REAL
        )
    """)
    c.commit()
    c.close()
    monkeypatch.setattr(kraken_sync, "_db_path", lambda: str(f))
    return str(f)


PUSH = {
    "push_id": 1, "order_id": "a274fd62-bd1b-4163-8ebe-5df6d1c539a6",
    "pair": "ETHFI/USD", "direction": "buy", "entry_price": 0.3833,
    "volume": 14.1, "pushed_at": "2026-08-08T23:58:29+00:00",
    "sl": 0.3445, "tp": 0.451, "symbol": "PF_ETHFIUSD",
}


def _ouvrir(db_path, pnl=0.0):
    """Reproduit la ligne telle que le trade OUVERT l'écrit : pnl à 0,0."""
    with sqlite3.connect(db_path) as c:
        c.execute(
            "INSERT INTO personal_trades (user,pair,direction,entry_price,"
            "stop_loss,take_profit,size_lot,status,pnl,created_at,mt5_ticket,"
            "is_auto) VALUES ('auto',?,?,?,?,?,?, 'OPEN', ?,?,?,1)",
            (PUSH["pair"], PUSH["direction"], PUSH["entry_price"], PUSH["sl"],
             PUSH["tp"], PUSH["volume"], pnl, PUSH["pushed_at"],
             PUSH["order_id"]),
        )


def _lire(db_path):
    with sqlite3.connect(db_path) as c:
        return c.execute(
            "SELECT status, pnl, exit_price, close_reason FROM personal_trades"
            " WHERE mt5_ticket = ?", (PUSH["order_id"],)).fetchone()


def test_un_pnl_inconnu_s_ecrit_NULL_et_non_zero(db):
    """LE test : sans ça, +0,00 € se lit comme un trade à plat."""
    _ouvrir(db)
    kraken_sync.enregistrer_cloture(
        {"push": PUSH, "cause": kraken_sync.CAUSE_EXTERNE, "taille": 14.1,
         "pnl_usd": None, "exit_price": None, "complete": True,
         "closed_at": "2026-08-09T15:30:00+00:00"},
        eur_usd=1.09,
    )
    status, pnl, exit_price, cause = _lire(db)

    assert status == "CLOSED"
    assert pnl is None, "un P&L inconnu doit rester NULL, jamais 0.0"
    assert exit_price is None
    assert cause == kraken_sync.CAUSE_EXTERNE


def test_la_cause_distingue_une_cloture_externe_d_un_nettage(db):
    """``NET`` couvrait deux situations opposées : un ordre qui réduit une
    position (P&L connu) et une position disparue (P&L inconnu)."""
    assert kraken_sync.CAUSE_EXTERNE != kraken_sync.CAUSE_NET


def test_un_pnl_connu_s_ecrit_toujours(db):
    """Le chemin normal ne bouge pas."""
    _ouvrir(db)
    kraken_sync.enregistrer_cloture(
        {"push": PUSH, "cause": kraken_sync.CAUSE_TP, "taille": 14.1,
         "pnl_usd": 0.14946, "exit_price": 0.3939, "complete": True,
         "closed_at": "2026-08-09T15:30:00+00:00"},
        eur_usd=1.09,
    )
    status, pnl, exit_price, cause = _lire(db)

    assert status == "CLOSED"
    assert pnl == pytest.approx(0.14, abs=0.01)
    assert exit_price == pytest.approx(0.3939)
    assert cause == kraken_sync.CAUSE_TP


def test_un_pnl_reellement_nul_reste_zero_pas_NULL(db):
    """0,0 mesuré et « inconnu » sont deux états : ne pas les confondre non
    plus dans l'autre sens."""
    _ouvrir(db)
    kraken_sync.enregistrer_cloture(
        {"push": PUSH, "cause": kraken_sync.CAUSE_TP, "taille": 14.1,
         "pnl_usd": 0.0, "exit_price": 0.3833, "complete": True,
         "closed_at": "2026-08-09T15:30:00+00:00"},
        eur_usd=1.09,
    )
    _, pnl, _, _ = _lire(db)
    assert pnl == 0.0
    assert pnl is not None


def test_une_ligne_absente_est_inseree_avec_un_pnl_NULL(db):
    """Cas d'une clôture détectée sans ligne d'ouverture correspondante."""
    kraken_sync.enregistrer_cloture(
        {"push": PUSH, "cause": kraken_sync.CAUSE_EXTERNE, "taille": 14.1,
         "pnl_usd": None, "exit_price": None, "complete": True,
         "closed_at": "2026-08-09T15:30:00+00:00"},
        eur_usd=1.09,
    )
    status, pnl, _, cause = _lire(db)
    assert status == "CLOSED"
    assert pnl is None
    assert cause == kraken_sync.CAUSE_EXTERNE


def test_les_positions_disparues_portent_la_cause_externe():
    """La construction de la clôture, pas son écriture."""
    sortie = kraken_sync.clotures_par_nettage(
        pushes=[PUSH], fills=[], positions={}, deja_closes=set())
    assert len(sortie) == 1
    assert sortie[0]["cause"] == kraken_sync.CAUSE_EXTERNE
    assert sortie[0]["pnl_usd"] is None
