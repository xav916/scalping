"""Tickets retirés du scoring d'admission (2026-08-25).

Le cas fondateur : le ticket `1353960866`, tenu **sans stop** sur consigne
explicite de Xavier — « ne pas le compter dans l'équation, le laisser vivre sa
vie » — puis fermé à la main à −265,11 €. Il avait été exclu du garde-fou de
perte journalière du bridge, **jamais** du calcul d'admission. À lui seul il
faisait passer le côté vente de l'or de +230,39 € à −34,72 €, sous le plancher
de −3 %, donc en `PAUSED` — et la pause gelait l'échantillon, qui ne pouvait
plus se renouveler faute de nouveaux trades.

⚠️ Ce que ces tests verrouillent :
  - l'exclusion se fait **avant** le `LIMIT`, sinon la fenêtre contient moins
    de trades comptables qu'annoncé ;
  - elle est **inscrite dans le relevé**, sinon le score n'est pas
    reproductible et un écart silencieux ressemble à une absence d'écart ;
  - elle est **vide par défaut** ;
  - elle ne franchit ni la frontière de direction ni celle de paire ;
  - elle ne retire **rien** du registre : l'argent a réellement été perdu.

Les tests appellent les fonctions livrées plutôt que de recopier leur
condition. Cf. [[feedback_source_inspection_tests_weak]].
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "trades.db"
    from backend.services import backtest_service, trade_log_service
    monkeypatch.setattr(trade_log_service, "_DB_PATH", db_path)
    monkeypatch.setattr(backtest_service, "_DB_PATH", tmp_path / "backtest.db")

    from backend.services import (
        ea_closed_trades_service,
        pair_admission_controller,
        pair_pnl_regulator,
    )
    monkeypatch.setattr(pair_admission_controller, "_SCHEMA_ENSURED", False)
    monkeypatch.setattr(pair_pnl_regulator, "_SCHEMA_ENSURED", False)
    monkeypatch.setattr(ea_closed_trades_service, "_SCHEMA_ENSURED", False)

    with sqlite3.connect(db_path) as c:
        c.execute(
            """
            CREATE TABLE personal_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT, direction TEXT, entry_price REAL,
                stop_loss REAL, take_profit REAL, size_lot REAL,
                signal_pattern TEXT, signal_confidence REAL,
                checklist_passed INTEGER, notes TEXT,
                status TEXT, exit_price REAL, pnl REAL,
                created_at TEXT, closed_at TEXT, user TEXT,
                post_entry_sl REAL, post_entry_tp REAL, post_entry_size REAL,
                post_entry_alarm TEXT, mt5_ticket TEXT, is_auto INTEGER,
                context_macro TEXT, signal_id TEXT, fill_price REAL,
                slippage_pips REAL, close_reason TEXT, user_id INTEGER
            )
            """
        )
        c.execute(
            """
            CREATE TABLE shadow_setups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                system_id TEXT, pair TEXT, direction TEXT,
                outcome TEXT, exit_at TEXT, pnl_eur REAL
            )
            """
        )
    yield db_path


def _poser(db, pair, pnl, ticket, direction="sell", jours=0):
    quand = (datetime.now(timezone.utc) - timedelta(days=jours)).isoformat()
    with sqlite3.connect(db) as c:
        c.execute(
            "INSERT INTO personal_trades (pair, direction, status, pnl, is_auto,"
            " closed_at, close_reason, mt5_ticket) "
            "VALUES (?, ?, 'CLOSED', ?, 1, ?, ?, ?)",
            (pair, direction, pnl, quand, "SL" if pnl < 0 else "TP1", str(ticket)),
        )


@pytest.fixture
def exclure(monkeypatch):
    """Règle la liste telle que la lit la fonction livrée."""
    def _set(tickets):
        import config.settings as st
        monkeypatch.setattr(st, "PAC_EXCLUDED_TICKETS", frozenset(tickets))
    return _set


# ── Défauts ───────────────────────────────────────────────────────────

def test_liste_vide_par_defaut(monkeypatch):
    import importlib
    monkeypatch.delenv("PAC_EXCLUDED_TICKETS", raising=False)
    import config.settings as st
    importlib.reload(st)
    assert st.PAC_EXCLUDED_TICKETS == frozenset()


def test_sans_reglage_rien_n_est_ecarte(_isolated_db):
    from backend.services import pair_admission_controller as pac
    for i in range(5):
        _poser(_isolated_db, "XAU/USD", -10.0, 900 + i, jours=i)
    assert pac.tickets_exclus_presents("XAU/USD", "sell") == []
    assert len(pac._fetch_real_trades_for_pair("XAU/USD", 30, "sell")) == 5


def test_un_reglage_illisible_ne_casse_rien(monkeypatch):
    import importlib
    monkeypatch.setenv("PAC_EXCLUDED_TICKETS", "abc, , 42 ,x7")
    import config.settings as st
    importlib.reload(st)
    assert st.PAC_EXCLUDED_TICKETS == frozenset({42})
    monkeypatch.delenv("PAC_EXCLUDED_TICKETS", raising=False)
    importlib.reload(st)


# ── Le cœur : ce qui sort du bulletin ─────────────────────────────────

def test_le_ticket_exclu_disparait_de_l_echantillon(_isolated_db, exclure):
    from backend.services import pair_admission_controller as pac
    _poser(_isolated_db, "XAU/USD", -265.11, 1353960866, jours=1)
    for i in range(4):
        _poser(_isolated_db, "XAU/USD", 10.0, 800 + i, jours=2 + i)

    avant = pac._fetch_real_trades_for_pair("XAU/USD", 30, "sell")
    assert sum(avant) == pytest.approx(-225.11)

    exclure({1353960866})
    apres = pac._fetch_real_trades_for_pair("XAU/USD", 30, "sell")
    assert len(apres) == 4
    assert sum(apres) == pytest.approx(40.0)


def test_l_exclusion_precede_le_LIMIT(_isolated_db, exclure):
    """Le défaut que ce test existe pour empêcher.

    Écarter APRÈS le `LIMIT` rendrait 29 trades là où la fenêtre en promet
    30 : on noterait la paire sur un échantillon plus court sans le dire.
    """
    _poser(_isolated_db, "XAU/USD", -265.11, 1353960866, jours=1)
    for i in range(40):
        _poser(_isolated_db, "XAU/USD", 1.0, 700 + i, jours=2 + i)

    from backend.services import pair_admission_controller as pac
    exclure({1353960866})
    fenetre = pac._fetch_real_trades_for_pair("XAU/USD", 30, "sell")
    assert len(fenetre) == 30, "la fenêtre doit rester pleine de trades comptables"
    assert -265.11 not in fenetre


def test_le_cas_reel_de_l_or(_isolated_db, exclure):
    """Reproduit la bascule mesurée le 2026-08-25 : un seul trade décide.

    31 trades pour que l'exclusion en laisse 30 — le plancher de trades réels.
    Sinon la paire deviendrait indécidable et masquerait ses métriques, ce que
    vérifie le test suivant.
    """
    from backend.services import pair_admission_controller as pac
    _poser(_isolated_db, "XAU/USD", -265.11, 1353960866, jours=1)
    for i in range(30):
        _poser(_isolated_db, "XAU/USD", 230.39 / 30, 600 + i, jours=2 + i)

    avec = pac.compute_promotion_score("XAU/USD", direction="sell")
    assert avec["sum_pnl"] < 0, "avec le ticket, le bulletin est négatif"

    exclure({1353960866})
    sans = pac.compute_promotion_score("XAU/USD", direction="sell")
    assert sans["n_real"] == 30
    assert sans["sum_pnl"] > 0, "sans lui, les 30 autres sont positifs"


def test_exclure_sous_le_plancher_rend_INDECIDABLE(_isolated_db, exclure):
    """⚠️ Conséquence à connaître, pas effet de bord à cacher.

    Retirer un trade retire aussi un trade RÉEL. Passer sous
    `PAC_MIN_REAL_TRADES` rend la paire indécidable et **masque** ses
    métriques — le système dit « je n'ai pas de quoi juger » au lieu
    d'inventer un verdict sur un échantillon complété par des signaux
    simulés. C'est le garde-fou du 2026-08-04.
    """
    from backend.services import pair_admission_controller as pac
    _poser(_isolated_db, "XAU/USD", -265.11, 1353960866, jours=1)
    for i in range(29):
        _poser(_isolated_db, "XAU/USD", 8.0, 600 + i, jours=2 + i)

    exclure({1353960866})
    score = pac.compute_promotion_score("XAU/USD", direction="sell")
    assert score["n_real"] == 29
    assert score["eligible_for"] == pac.STATE_INDETERMINATE
    assert score["sum_pnl"] is None, "des métriques non fiables se masquent"


def test_indecidable_ne_declenche_AUCUNE_mise_en_pause(_isolated_db, exclure):
    """Le corollaire qui compte : masquer les métriques ne doit pas planter.

    `evaluate_pair` compare `pnl_pct < -3.0`. Sur une paire indécidable ce
    champ vaut `None` : sans le retour anticipé sur `INDETERMINATE`, la
    comparaison lèverait un `TypeError` et casserait la boucle d'évaluation
    de TOUTES les paires, pas seulement de l'or.
    """
    from backend.services import pair_admission_controller as pac
    _poser(_isolated_db, "XAU/USD", -265.11, 1353960866, jours=1)
    for i in range(29):
        _poser(_isolated_db, "XAU/USD", -8.0, 600 + i, jours=2 + i)

    pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "mise en place du test",
                  direction="sell")
    exclure({1353960866})

    verdict = pac.evaluate_pair("XAU/USD", direction="sell")
    assert verdict["action"] == "keep"
    assert pac.get_current_state("XAU/USD", direction="sell") == pac.STATE_AUTO_EXEC


# ── La trace : un écart silencieux est indiscernable d'aucun écart ────

def test_l_exclusion_est_inscrite_dans_le_releve(_isolated_db, exclure):
    from backend.services import pair_admission_controller as pac
    _poser(_isolated_db, "XAU/USD", -265.11, 1353960866, jours=1)
    for i in range(5):
        _poser(_isolated_db, "XAU/USD", 5.0, 500 + i, jours=2 + i)

    exclure({1353960866})
    score = pac.compute_promotion_score("XAU/USD", direction="sell")
    assert score["tickets_exclus"] == [1353960866], (
        "sans cette trace, le score n'est pas reproductible"
    )


def test_un_ticket_exclu_absent_de_la_paire_n_est_pas_annonce(_isolated_db, exclure):
    from backend.services import pair_admission_controller as pac
    _poser(_isolated_db, "XAU/USD", 5.0, 111, jours=1)
    exclure({999999999})
    assert pac.tickets_exclus_presents("XAU/USD", "sell") == []


# ── Portée : l'exclusion ne déborde pas ───────────────────────────────

def test_l_exclusion_respecte_la_direction(_isolated_db, exclure):
    from backend.services import pair_admission_controller as pac
    _poser(_isolated_db, "XAU/USD", -265.11, 1353960866, direction="sell", jours=1)
    _poser(_isolated_db, "XAU/USD", -50.0, 222, direction="buy", jours=2)

    exclure({1353960866})
    assert pac.tickets_exclus_presents("XAU/USD", "buy") == []
    achats = pac._fetch_real_trades_for_pair("XAU/USD", 30, "buy")
    assert achats == [-50.0], "le côté achat est intact"


def test_l_exclusion_respecte_la_paire(_isolated_db, exclure):
    from backend.services import pair_admission_controller as pac
    _poser(_isolated_db, "EUR/USD", -20.0, 1353960866, jours=1)
    exclure({1353960866})
    assert pac.tickets_exclus_presents("XAU/USD", "sell") == []


# ── Ce que l'exclusion ne fait PAS ────────────────────────────────────

def test_le_trade_reste_en_base(_isolated_db, exclure):
    """⛔ On retire du BULLETIN, jamais du registre. L'argent a été perdu.

    Un scoring qui supprimerait la ligne rendrait le P&L et le risque faux.
    """
    _poser(_isolated_db, "XAU/USD", -265.11, 1353960866, jours=1)
    exclure({1353960866})
    from backend.services import pair_admission_controller as pac
    pac.compute_promotion_score("XAU/USD", direction="sell")

    with sqlite3.connect(_isolated_db) as c:
        reste = c.execute(
            "SELECT pnl FROM personal_trades WHERE mt5_ticket = '1353960866'"
        ).fetchall()
    assert reste == [(-265.11,)], "la ligne doit survivre intacte au scoring"
