"""Les niveaux STOCKÉS ne sont pas ceux du courtier — il faut garder les vrais.

MT5 ne conserve aucune trace des `TRADE_ACTION_SLTP` : modifier un stop mute la
position sans créer d'ordre. À la seconde où elle ferme, le niveau qu'elle
portait réellement est perdu. La base, elle, garde les niveaux d'ORIGINE.

Mesure du 2026-08-24 sur les 39 clôtures à la main, rejouées minute par minute
sur bougies M1 : **16 des 36 contrefactuels (44 %) voient le niveau stocké
franchi AVANT l'heure réelle de clôture** — preuve directe que le niveau stocké
n'était pas vivant. Exemples : WTI 81311989, SL stocké franchi à 06h16, position
fermée à 06h43 ; EUR/USD 1352367416, SL franchi à 01h06, fermée à 10h05.

⇒ Toute simulation de sortie assise sur `stop_loss`/`take_profit` est fausse
dans ~4 cas sur 10. Le bridge capture désormais les niveaux vivants ; ce test
verrouille leur arrivée en base, et surtout le fait qu'une ABSENCE de niveau ne
s'écrit jamais comme un zéro.

Cf. [[project_analyse_clotures_main_2026_08_24]] ·
    [[project_close_reason_manual_invente_2026_08_10]]
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
            mt5_ticket INTEGER, post_entry_sl INTEGER, close_reason TEXT,
            closed_at TEXT,
            sl_at_close REAL, tp_at_close REAL, niveaux_source TEXT
        )
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(mt5_sync, "_db_path", lambda: str(f))
    return str(f)


def _trade(db, ticket, *, sl, tp):
    with sqlite3.connect(db) as c:
        c.execute(
            "INSERT INTO personal_trades (pair, direction, entry_price, "
            "stop_loss, take_profit, status, mt5_ticket, post_entry_sl) "
            "VALUES ('XAU/USD','sell',4100.0,?,?,'OPEN',?,1)",
            (sl, tp, ticket),
        )


def _lire(db, ticket):
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        return dict(c.execute(
            "SELECT stop_loss, take_profit, sl_at_close, tp_at_close, "
            "niveaux_source FROM personal_trades WHERE mt5_ticket=?",
            (ticket,)).fetchone())


def test_le_niveau_vivant_est_enregistre_sans_ecraser_l_origine(db):
    """Le stop d'origine et le stop réellement porté sont DEUX faits distincts.

    Écraser `stop_loss` par le niveau vivant perdrait le R:R décidé à l'entrée ;
    ne garder que l'origine perd la réalité de la sortie. Les deux colonnes
    coexistent — c'est tout l'intérêt.
    """
    _trade(db, 111, sl=4104.23, tp=4085.13)
    mt5_sync._update_closed_trade({
        "ticket": 111, "exit_price": 4405.67, "pnl": -265.11,
        "reason": "MANUAL",
        "sl_at_close": 4785.05, "tp_at_close": 4095.0,
        "niveaux_source": "monitor",
    })
    r = _lire(db, 111)
    assert r["stop_loss"] == 4104.23, "le niveau d'origine doit survivre"
    assert r["sl_at_close"] == 4785.05
    assert r["tp_at_close"] == 4095.0
    assert r["niveaux_source"] == "monitor"


def test_une_absence_de_niveau_ne_s_ecrit_pas_comme_un_zero(db):
    """MT5 rend `sl = 0.0` pour « aucun stop ». Écrit tel quel, ce zéro devient
    indiscernable d'un stop réellement posé à zéro — et la position NUE du
    2026-08-05 se lirait comme une position protégée.

    Quatrième occurrence de la maladie « une valeur par défaut se fait passer
    pour une mesure », après `pnl=0.0`, `entry_price=0.0`, `close_reason=MANUAL`.
    """
    _trade(db, 222, sl=4104.23, tp=4085.13)
    mt5_sync._update_closed_trade({
        "ticket": 222, "exit_price": 4405.67, "pnl": -265.11,
        "reason": "MANUAL", "sl_at_close": 0.0, "tp_at_close": 0.0,
    })
    r = _lire(db, 222)
    assert r["sl_at_close"] is None, "0.0 signifie ABSENT, pas 'stop à zéro'"
    assert r["tp_at_close"] is None


def test_le_niveau_declencheur_alimente_le_cote_qui_a_ferme(db):
    """Sur une position déjà fermée, MT5 ne rend qu'un seul niveau : celui qui
    l'a déclenchée, porté par l'ordre de clôture. C'est partiel, et c'est
    exactement pour ça qu'il arrive étiqueté `ordre_declencheur` — un niveau
    reconstruit après coup ne doit pas se lire comme un niveau observé vivant.
    """
    _trade(db, 333, sl=4104.23, tp=4085.13)
    mt5_sync._update_closed_trade({
        "ticket": 333, "exit_price": 4150.0, "pnl": -50.0, "reason": "SL",
        "niveau_declencheur": 4150.0, "niveaux_source": "ordre_declencheur",
    })
    r = _lire(db, 333)
    assert r["sl_at_close"] == 4150.0, "SL déclencheur => c'est le stop vivant"
    assert r["tp_at_close"] is None, "l'autre côté reste INCONNU"
    assert r["niveaux_source"] == "ordre_declencheur"


def test_un_niveau_deja_connu_n_est_pas_ecrase_par_une_reconstruction(db):
    """Le monitor voit les deux côtés ; la reconstruction n'en voit qu'un. Si
    le réconciliateur repasse après coup avec sa version partielle, elle ne doit
    pas remplacer la mesure complète — sinon on dégrade en silence."""
    _trade(db, 444, sl=4104.23, tp=4085.13)
    mt5_sync._update_closed_trade({
        "ticket": 444, "exit_price": 4150.0, "pnl": -50.0, "reason": "SL",
        "sl_at_close": 4149.0, "tp_at_close": 4000.0, "niveaux_source": "monitor",
    })
    mt5_sync._update_closed_trade({
        "ticket": 444, "exit_price": 4150.0, "pnl": -50.0, "reason": "SL",
        "niveau_declencheur": 4150.0, "niveaux_source": "ordre_declencheur",
    })
    r = _lire(db, 444)
    assert r["sl_at_close"] == 4149.0
    assert r["tp_at_close"] == 4000.0
    assert r["niveaux_source"] == "monitor"


def test_le_niveau_declencheur_d_un_TP_alimente_le_cote_TP(db):
    """Symétrique du test SL : la cause dit quel côté le niveau décrit. Sans
    elle, on ne saurait pas dans quelle colonne le ranger."""
    _trade(db, 555, sl=4104.23, tp=4085.13)
    mt5_sync._update_closed_trade({
        "ticket": 555, "exit_price": 4080.0, "pnl": 20.0, "reason": "TP",
        "niveau_declencheur": 4080.0, "niveaux_source": "ordre_declencheur",
    })
    r = _lire(db, 555)
    assert r["tp_at_close"] == 4080.0
    assert r["sl_at_close"] is None
