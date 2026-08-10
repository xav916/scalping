"""La cause de clôture ne doit JAMAIS être affirmée sans preuve.

Le bridge ne remonte pas `reason` dans /deals, donc `_derive_close_reason_from_exit`
devine à partir de la position du prix de sortie. Sa branche par défaut renvoyait
"MANUAL" — c'est-à-dire qu'elle affirmait « fermé à la main » chaque fois qu'elle
ne savait pas conclure.

Mesuré le 2026-08-10 : 215 trades étiquetés MANUAL, dont 215 (100 %) avec
post_entry_sl=1. Aucun n'avait été fermé à la main ; c'étaient les sorties du
stop suiveur (TRAIL_DISTANCE_POINTS=150) et de la mise à zéro du risque
(BREAKEVEN_TRIGGER_PCT=50).

Même maladie que `pnl=0.0` qui valait « inconnu » (cf. clôtures Kraken, 08-09) :
une valeur par défaut qui se fait passer pour une mesure.
"""
import sqlite3

import pytest

from backend.services import mt5_sync


@pytest.fixture
def db(tmp_path, monkeypatch):
    f = tmp_path / "trades.db"
    conn = sqlite3.connect(f)
    conn.execute("""
        CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY,
            pair TEXT, direction TEXT,
            entry_price REAL, stop_loss REAL, take_profit REAL,
            exit_price REAL, pnl REAL, status TEXT,
            mt5_ticket INTEGER, post_entry_sl INTEGER, close_reason TEXT
        )
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(mt5_sync, "_db_path", lambda: str(f))
    return str(f)


def _trade(db, ticket, *, pair, direction, entry, sl, tp, post_entry_sl=1):
    with sqlite3.connect(db) as c:
        c.execute(
            "INSERT INTO personal_trades (pair, direction, entry_price, stop_loss, "
            "take_profit, status, mt5_ticket, post_entry_sl) "
            "VALUES (?,?,?,?,?,'OPEN',?,?)",
            (pair, direction, entry, sl, tp, ticket, post_entry_sl),
        )


# --- ce que l'heuristique SAIT établir ------------------------------------

def test_sortie_sur_le_stop_dorigine_est_un_SL(db):
    _trade(db, 1, pair="XAU/USD", direction="sell", entry=4358.81, sl=4376.68, tp=4322.05)
    assert mt5_sync._derive_close_reason_from_exit(1, 4376.70) == "SL"


def test_sortie_sur_le_take_profit_est_un_TP(db):
    _trade(db, 2, pair="XAU/USD", direction="sell", entry=4358.81, sl=4376.68, tp=4322.05)
    assert mt5_sync._derive_close_reason_from_exit(2, 4322.10) == "TP1"


def test_sortie_AU_DELA_du_take_profit_reste_un_TP(db):
    """Pour une vente, sortir SOUS le TP implique que le prix l'a traversé :
    l'ordre a bien été touché, avec un glissement favorable. Ce n'est pas une
    conjecture, c'est une conséquence de l'ordre des prix."""
    _trade(db, 3, pair="XAU/USD", direction="sell", entry=4358.81, sl=4376.68, tp=4322.05)
    assert mt5_sync._derive_close_reason_from_exit(3, 4315.00) == "TP1"


def test_sortie_au_prix_dentree_est_une_mise_a_zero_du_risque(db):
    _trade(db, 4, pair="XAU/USD", direction="sell", entry=4358.81, sl=4376.68, tp=4322.05)
    assert mt5_sync._derive_close_reason_from_exit(4, 4358.90) == "BREAKEVEN"


def test_sortie_en_gain_avant_le_TP_est_le_stop_suiveur(db):
    """Le cas réel du ticket 82840896 : le cours est descendu à 14 centimes du
    TP, a rebondi, et le stop suiveur (150 points = 1,50 $) a fermé à 4323,69."""
    _trade(db, 82840896, pair="XAU/USD", direction="sell",
           entry=4358.81, sl=4376.68, tp=4322.05)
    assert mt5_sync._derive_close_reason_from_exit(82840896, 4323.69) == "TRAILING_SL"


def test_le_stop_suiveur_vaut_aussi_a_l_achat(db):
    _trade(db, 6, pair="EUR/USD", direction="buy", entry=1.08000, sl=1.07500, tp=1.09000)
    assert mt5_sync._derive_close_reason_from_exit(6, 1.08600) == "TRAILING_SL"


# --- ce que l'heuristique NE PEUT PAS établir -----------------------------

def test_sortie_en_perte_hors_du_stop_ne_ment_plus(db):
    """91 cas mesurés : sortie défavorable sans toucher le SL. Ça peut être un
    /kill, une fermeture partielle, un stop-out courtier ou une vraie main
    humaine. L'heuristique ne peut pas trancher — elle doit le dire."""
    _trade(db, 7, pair="XAU/USD", direction="sell", entry=4358.81, sl=4376.68, tp=4322.05)
    assert mt5_sync._derive_close_reason_from_exit(7, 4365.00) == "INDETERMINE"


def test_jamais_MANUAL_sans_preuve(db):
    """MANUAL ne doit venir QUE du courtier (DEAL_REASON_CLIENT), jamais d'une
    branche par défaut."""
    _trade(db, 8, pair="XAU/USD", direction="sell", entry=4358.81, sl=4376.68, tp=4322.05)
    for exit_price in (4365.00, 4370.00, 4350.00, 4340.00):
        assert mt5_sync._derive_close_reason_from_exit(8, exit_price) != "MANUAL"


def test_sans_stop_deplace_le_gain_avant_TP_reste_indetermine(db):
    """Si le SL n'a jamais bougé, la sortie en gain avant le TP n'est pas
    attribuable au stop suiveur."""
    _trade(db, 9, pair="XAU/USD", direction="sell", entry=4358.81, sl=4376.68,
           tp=4322.05, post_entry_sl=0)
    assert mt5_sync._derive_close_reason_from_exit(9, 4323.69) == "INDETERMINE"


def test_ticket_inconnu_ou_prix_absent_ne_conclut_rien(db):
    assert mt5_sync._derive_close_reason_from_exit(999, 4323.69) is None
    _trade(db, 10, pair="XAU/USD", direction="sell", entry=4358.81, sl=4376.68, tp=4322.05)
    assert mt5_sync._derive_close_reason_from_exit(10, None) is None


# --- la cause venue du courtier fait toujours autorite ---------------------

def test_la_cause_remontee_par_MT5_prime_sur_l_heuristique():
    assert mt5_sync._normalize_close_reason("DEAL_REASON_CLIENT") == "MANUAL"
    assert mt5_sync._normalize_close_reason("DEAL_REASON_SL") == "SL"
    assert mt5_sync._normalize_close_reason("DEAL_REASON_TP") == "TP1"


def test_la_liquidation_par_le_courtier_a_son_propre_nom():
    """DEAL_REASON_SO = stop out. C'est exactement ce qui menace la position or
    ouverte ; le confondre avec un SL effacerait la distinction entre une sortie
    choisie et une liquidation subie."""
    assert mt5_sync._normalize_close_reason("DEAL_REASON_SO") == "STOP_OUT"
