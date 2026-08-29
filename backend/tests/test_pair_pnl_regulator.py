"""Tests pour backend.services.pair_pnl_regulator."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Redirige _DB_PATH du trade_log_service vers une DB temporaire."""
    db_path = tmp_path / "trades.db"
    from backend.services import trade_log_service

    monkeypatch.setattr(trade_log_service, "_DB_PATH", db_path)

    # Reset le cache schema-ensured pour que les modules recréent les tables dans tmp
    from backend.services import pair_pnl_regulator, ea_closed_trades_service

    monkeypatch.setattr(pair_pnl_regulator, "_SCHEMA_ENSURED", False)
    monkeypatch.setattr(ea_closed_trades_service, "_SCHEMA_ENSURED", False)

    # Crée la table personal_trades minimale
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
                slippage_pips REAL, close_reason TEXT, user_id INTEGER,
                destination_id TEXT
            )
            """
        )
    yield db_path


def _insert_trade(db_path: Path, pair: str, pnl: float, closed_at: str | None = None,
                  destination: str | None = None):
    closed_at = closed_at or datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as c:
        c.execute(
            """
            INSERT INTO personal_trades (pair, status, pnl, is_auto, closed_at,
                                         close_reason, destination_id)
            VALUES (?, 'CLOSED', ?, 1, ?, ?, ?)
            """,
            (pair, pnl, closed_at, "SL" if pnl < 0 else "TP1", destination),
        )


# ─── compute_window_metrics ─────────────────────────────────────────────


def test_compute_window_metrics_empty(_isolated_db):
    from backend.services import pair_pnl_regulator

    m = pair_pnl_regulator.compute_window_metrics("XAG/USD", 30)
    assert m["n"] == 0
    assert m["sum_pnl"] == 0.0


def test_compute_window_metrics_aggregates_last_n(_isolated_db):
    from backend.services import pair_pnl_regulator

    for i in range(40):
        # Plus récent = i grand, on alterne signe
        _insert_trade(
            _isolated_db,
            "XAG/USD",
            pnl=10.0 if i % 2 == 0 else -20.0,
            closed_at=(datetime.now(timezone.utc) + timedelta(minutes=i)).isoformat(),
        )
    m = pair_pnl_regulator.compute_window_metrics("XAG/USD", 30)
    # Les 30 derniers (i=10..39) : 15 wins de 10€, 15 losses de -20€
    assert m["n"] == 30
    assert m["sum_pnl"] == 15 * 10 - 15 * 20  # = -150


# ─── evaluate_pair decision tree ────────────────────────────────────────


def test_evaluate_pair_keep_active_if_sample_too_small(_isolated_db, monkeypatch):
    monkeypatch.setenv("PAIR_PNL_REGULATOR_MIN_SAMPLE", "10")
    # Reload settings
    import importlib
    from config import settings as _s
    importlib.reload(_s)
    from backend.services import pair_pnl_regulator
    importlib.reload(pair_pnl_regulator)

    # Seulement 5 trades, en grosse perte
    for _ in range(5):
        _insert_trade(_isolated_db, "XAG/USD", pnl=-100.0)

    d = pair_pnl_regulator.evaluate_pair("XAG/USD")
    assert d["action"] == "keep_active"


def test_evaluate_pair_pause_if_pnl_below_threshold(_isolated_db, monkeypatch):
    monkeypatch.setenv("PAIR_PNL_REGULATOR_MIN_SAMPLE", "10")
    monkeypatch.setenv("PAIR_PNL_REGULATOR_PAUSE_THRESHOLD_PCT", "-3.0")
    monkeypatch.setenv("TRADING_CAPITAL", "10000")
    import importlib
    from config import settings as _s
    importlib.reload(_s)
    from backend.services import pair_pnl_regulator
    importlib.reload(pair_pnl_regulator)

    # 15 trades, sum_pnl = -500€ → -5% sur 10000€ capital → < -3% → pause
    for _ in range(15):
        _insert_trade(_isolated_db, "XAG/USD", pnl=-33.33)

    d = pair_pnl_regulator.evaluate_pair("XAG/USD")
    assert d["action"] == "pause"
    assert pair_pnl_regulator.is_paused("XAG/USD") is True


def test_evaluate_pair_keep_paused_if_not_expired(_isolated_db):
    from backend.services import pair_pnl_regulator

    pair_pnl_regulator.apply_pause("XAG/USD", "ev_negative", -5.0, 30)
    d = pair_pnl_regulator.evaluate_pair("XAG/USD")
    assert d["action"] == "keep_paused"


def test_apply_pause_idempotent(_isolated_db):
    from backend.services import pair_pnl_regulator

    id1 = pair_pnl_regulator.apply_pause("XAG/USD", "ev_negative", -5.0, 30)
    id2 = pair_pnl_regulator.apply_pause("XAG/USD", "ev_negative", -6.0, 30)
    # Même id retourné (pas créé de doublon)
    assert id1 == id2


def test_resume_clears_active_pause(_isolated_db):
    from backend.services import pair_pnl_regulator

    pair_pnl_regulator.apply_pause("XAG/USD", "ev_negative", -5.0, 30)
    assert pair_pnl_regulator.is_paused("XAG/USD") is True
    pair_pnl_regulator.apply_resume("XAG/USD", "manual_test")
    assert pair_pnl_regulator.is_paused("XAG/USD") is False


# ─── PAC_EXCLUDED_TICKETS : le second juge ──────────────────────────────
#
# Le régulateur et `pair_admission_controller` notent la même paire sur les
# mêmes clôtures, mais seul le second consultait la liste d'exclusion. Une
# paire pouvait donc être promue par l'un et gardée en pause par l'autre —
# c'est exactement ce qui est arrivé à l'or le 2026-08-25.


def _poser_ticket(db_path: Path, pair: str, pnl: float, ticket, jours: int = 0):
    """Insère un trade daté et TICKETÉ. `mt5_ticket` est en TEXTE ici, comme
    en production — le piège d'affinité SQLite se reproduit tel quel."""
    quand = (datetime.now(timezone.utc) - timedelta(days=jours)).isoformat()
    with sqlite3.connect(db_path) as c:
        c.execute(
            """
            INSERT INTO personal_trades (pair, status, pnl, is_auto, closed_at,
                                         close_reason, mt5_ticket)
            VALUES (?, 'CLOSED', ?, 1, ?, ?, ?)
            """,
            (pair, pnl, quand, "MANUAL" if pnl < 0 else "TP1", str(ticket)),
        )


@pytest.fixture
def exclure(monkeypatch):
    """Règle la liste telle que la lit la fonction livrée."""
    def _set(tickets):
        import config.settings as st
        monkeypatch.setattr(st, "PAC_EXCLUDED_TICKETS", frozenset(tickets))
    return _set


def test_sans_reglage_aucun_trade_n_est_ecarte(_isolated_db, exclure):
    """Vide par défaut : la fenêtre est celle d'avant le correctif."""
    from backend.services import pair_pnl_regulator

    exclure([])
    for i in range(5):
        _poser_ticket(_isolated_db, "XAU/USD", -10.0, 900 + i, jours=i)

    m = pair_pnl_regulator.compute_window_metrics("XAU/USD", 30)
    assert m["n"] == 5
    assert m["sum_pnl"] == -50.0


def test_un_ticket_exclu_sort_de_la_fenetre(_isolated_db, exclure):
    """Le cas de l'or : une position tenue sans stop sur consigne, fermée à la
    main, pèse à elle seule le verdict. Elle ne doit pas noter le système."""
    from backend.services import pair_pnl_regulator

    _poser_ticket(_isolated_db, "XAU/USD", -265.11, 1353960866, jours=5)
    for i in range(4):
        _poser_ticket(_isolated_db, "XAU/USD", +10.0, 900 + i, jours=i)

    exclure([1353960866])
    m = pair_pnl_regulator.compute_window_metrics("XAU/USD", 30)

    assert m["n"] == 4
    assert m["sum_pnl"] == 40.0


def test_la_fenetre_reste_pleine_un_trade_plus_ancien_remonte(_isolated_db, exclure):
    """⛔ L'exclusion se fait avant le LIMIT. L'écarter après rendrait une
    fenêtre de 9 trades en annonçant 10 : on noterait la paire sur moins de
    clôtures que le relevé ne le prétend."""
    from backend.services import pair_pnl_regulator

    # 12 trades : le plus récent (jours=0) est le ticket honni.
    _poser_ticket(_isolated_db, "XAU/USD", -500.0, 777, jours=0)
    for i in range(11):
        _poser_ticket(_isolated_db, "XAU/USD", +1.0, 800 + i, jours=i + 1)

    exclure([777])
    m = pair_pnl_regulator.compute_window_metrics("XAU/USD", 10)

    assert m["n"] == 10, "la fenêtre doit rester pleine"
    assert m["sum_pnl"] == 10.0


def test_les_trades_des_users_premium_sont_filtres_aussi(_isolated_db, exclure):
    """`ea_closed_trades` stocke `mt5_ticket` en ENTIER quand `personal_trades`
    le stocke en TEXTE. Le filtre doit valoir des deux côtés de l'UNION."""
    from backend.services import ea_closed_trades_service, pair_pnl_regulator

    ea_closed_trades_service._ensure_schema()
    with sqlite3.connect(_isolated_db) as c:
        for ticket, pnl in ((555, -300.0), (556, +20.0)):
            c.execute(
                """
                INSERT INTO ea_closed_trades (user_id, pair, direction,
                    entry_price, exit_price, pnl, mt5_ticket, closed_at, reported_at)
                VALUES (2, 'XAU/USD', 'sell', 1.0, 1.0, ?, ?, ?, ?)
                """,
                (pnl, ticket, datetime.now(timezone.utc).isoformat(),
                 datetime.now(timezone.utc).isoformat()),
            )

    exclure([555])
    m = pair_pnl_regulator.compute_window_metrics("XAU/USD", 30)

    assert m["n"] == 1
    assert m["sum_pnl"] == 20.0


def test_la_fenetre_dit_ce_qu_elle_a_ecarte(_isolated_db, exclure):
    """⚠️ Un relevé qui écarte en silence est indiscernable d'un relevé qui
    n'a rien écarté. Le ticket retiré doit être nommé dans le résultat."""
    from backend.services import pair_pnl_regulator

    _poser_ticket(_isolated_db, "XAU/USD", -265.11, 1353960866, jours=5)
    _poser_ticket(_isolated_db, "XAU/USD", +10.0, 901, jours=1)

    exclure([1353960866, 424242])  # 424242 n'existe pas pour cette paire
    m = pair_pnl_regulator.compute_window_metrics("XAU/USD", 30)

    assert m["excluded_tickets"] == [1353960866]


def test_un_seul_ticket_fait_basculer_la_pause(_isolated_db, exclure, monkeypatch):
    """Bout en bout : c'est `evaluate_pair` qui pose la pause opposable à
    TOUTES les destinations. Sans le ticket exclu, elle ne doit pas être posée.

    ⚠️ `TRADING_CAPITAL` est épinglé à sa valeur de PRODUCTION : le seuil se
    mesure en % du capital, donc un test qui laisse traîner le défaut local
    (10 000 €) jugerait sur une échelle que la prod (650 €) n'a jamais eue.
    """
    import config.settings as st
    from backend.services import pair_pnl_regulator

    monkeypatch.setattr(st, "TRADING_CAPITAL", 650.0)

    _poser_ticket(_isolated_db, "XAU/USD", -265.11, 1353960866, jours=5)
    for i in range(11):
        _poser_ticket(_isolated_db, "XAU/USD", +1.0, 900 + i, jours=i)

    exclure([])
    assert pair_pnl_regulator.evaluate_pair("XAU/USD")["action"] == "pause"

    with sqlite3.connect(_isolated_db) as c:
        c.execute("DELETE FROM auto_paused_pairs")

    exclure([1353960866])
    assert pair_pnl_regulator.evaluate_pair("XAU/USD")["action"] == "keep_active"


# ─── Le plancher d'âge de la fenêtre (2026-08-29) ────────────────────────
#
# ⛔ `compute_window_metrics` n'avait AUCUN plancher : il notait une paire sur
# ses N derniers trades, quelle que soit leur ancienneté. Le 29/08/2026,
# l'argent était tenu en pause sur le compte réel IC Markets par 30 trades
# clôturés entre le 7 et le 12 MAI sur l'ancien compte démo MetaQuotes —
# un autre courtier, un autre compte, une période déclarée contaminée par le
# bug de déduplication corrigé le 04/08.
#
# 🔑 Et le verrou était circulaire : la paire ne pouvait pas trader à cause
# d'une mesure, et la mesure ne pouvait pas se rafraîchir puisqu'elle ne
# tradait pas.


@pytest.fixture
def plancher(monkeypatch):
    """Règle le plancher tel que le lit la fonction livrée."""
    def _set(jours):
        import config.settings as st
        monkeypatch.setattr(st, "PAIR_PNL_REGULATOR_MAX_AGE_DAYS", jours)
    return _set


def test_un_trade_plus_vieux_que_le_plancher_ne_compte_plus(_isolated_db, plancher):
    from backend.services import pair_pnl_regulator

    plancher(90)
    _insert_trade(_isolated_db, "XAG/USD", -500.0,
                  (datetime.now(timezone.utc) - timedelta(days=110)).isoformat())
    _insert_trade(_isolated_db, "XAG/USD", +10.0,
                  (datetime.now(timezone.utc) - timedelta(days=2)).isoformat())

    m = pair_pnl_regulator.compute_window_metrics("XAG/USD", 30)
    assert m["n"] == 1
    assert m["sum_pnl"] == 10.0


def test_a_zero_le_plancher_est_DESARME(_isolated_db, plancher):
    """0 = comportement d'avant le correctif, à l'identique."""
    from backend.services import pair_pnl_regulator

    plancher(0)
    _insert_trade(_isolated_db, "XAG/USD", -500.0,
                  (datetime.now(timezone.utc) - timedelta(days=1000)).isoformat())

    m = pair_pnl_regulator.compute_window_metrics("XAG/USD", 30)
    assert m["n"] == 1
    assert m["plancher_age"] is None


def test_le_plancher_s_applique_AVANT_le_limit(_isolated_db, plancher):
    """⛔ Filtrer après coup rendrait une fenêtre plus courte que
    `window_trades` en prétendant l'inverse — même piège que l'exclusion par
    ticket. Ici : 3 vieux + 3 récents, fenêtre de 3. Le filtre passant avant,
    la fenêtre doit contenir les 3 RÉCENTS, pas 0."""
    from backend.services import pair_pnl_regulator

    plancher(90)
    for i in range(3):
        _insert_trade(_isolated_db, "XAG/USD", -100.0,
                      (datetime.now(timezone.utc) - timedelta(days=200 + i)).isoformat())
    for i in range(3):
        _insert_trade(_isolated_db, "XAG/USD", +5.0,
                      (datetime.now(timezone.utc) - timedelta(days=i)).isoformat())

    m = pair_pnl_regulator.compute_window_metrics("XAG/USD", 3)
    assert m["n"] == 3
    assert m["sum_pnl"] == 15.0


def test_la_fenetre_dit_combien_l_age_a_ecarte(_isolated_db, plancher):
    """⚠️ Une fenêtre qui écarte en silence est indiscernable d'une fenêtre
    qui n'a rien écarté."""
    from backend.services import pair_pnl_regulator

    plancher(90)
    for i in range(4):
        _insert_trade(_isolated_db, "XAG/USD", -50.0,
                      (datetime.now(timezone.utc) - timedelta(days=150 + i)).isoformat())
    _insert_trade(_isolated_db, "XAG/USD", +5.0,
                  (datetime.now(timezone.utc) - timedelta(days=1)).isoformat())

    m = pair_pnl_regulator.compute_window_metrics("XAG/USD", 30)
    assert m["n_hors_age"] == 4
    assert m["plancher_age"] is not None


def test_les_trades_des_users_premium_ont_le_meme_plancher(_isolated_db, plancher):
    """Le filtre doit valoir des DEUX côtés de l'UNION — un plancher posé d'un
    seul côté n'est pas un plancher."""
    from backend.services import ea_closed_trades_service, pair_pnl_regulator

    plancher(90)
    ea_closed_trades_service._ensure_schema()
    with sqlite3.connect(_isolated_db) as c:
        for pnl, jours in ((-300.0, 200), (+20.0, 1)):
            quand = (datetime.now(timezone.utc) - timedelta(days=jours)).isoformat()
            c.execute(
                """
                INSERT INTO ea_closed_trades (user_id, pair, direction,
                    entry_price, exit_price, pnl, mt5_ticket, closed_at, reported_at)
                VALUES (2, 'XAG/USD', 'sell', 1.0, 1.0, ?, ?, ?, ?)
                """,
                (pnl, int(jours), quand, quand),
            )

    m = pair_pnl_regulator.compute_window_metrics("XAG/USD", 30)
    assert m["n"] == 1
    assert m["sum_pnl"] == 20.0


def test_une_paire_DORMANTE_n_est_plus_mise_en_pause_sur_son_passe_mort(
        _isolated_db, plancher, monkeypatch):
    """⛔ LE test central — le cas de l'argent, reproduit à l'identique.

    30 trades perdants clôturés il y a plus de trois mois, plus rien depuis.
    Sans plancher, la paire est mise en pause et ne peut plus jamais se
    défaire de ce verdict, faute de trader. Avec plancher, la fenêtre est vide
    et le régulateur répond `no_data` : **inconnu, pas coupable.**
    """
    import config.settings as st
    from backend.services import pair_pnl_regulator

    monkeypatch.setattr(st, "TRADING_CAPITAL", 650.0)
    for i in range(30):
        _insert_trade(_isolated_db, "XAG/USD", -20.0,
                      (datetime.now(timezone.utc) - timedelta(days=110 + i)).isoformat())

    plancher(0)
    assert pair_pnl_regulator.evaluate_pair("XAG/USD")["action"] == "pause"

    with sqlite3.connect(_isolated_db) as c:
        c.execute("DELETE FROM auto_paused_pairs")

    plancher(90)
    assert pair_pnl_regulator.evaluate_pair("XAG/USD")["action"] == "no_data"


def test_une_pause_ACTIVE_n_est_pas_levee_par_le_plancher(_isolated_db, plancher):
    """⚠️ Le plancher change ce qu'on MESURE, pas ce qui est déjà décidé. Une
    pause en cours court jusqu'à son terme — sans quoi le correctif aurait
    relâché d'un coup toutes les paires pausées en production."""
    from backend.services import pair_pnl_regulator

    _insert_trade(_isolated_db, "XAG/USD", -500.0,
                  (datetime.now(timezone.utc) - timedelta(days=300)).isoformat())
    pair_pnl_regulator.apply_pause("XAG/USD", "ev_negative", -80.0, 30)

    plancher(90)
    assert pair_pnl_regulator.evaluate_pair("XAG/USD")["action"] == "keep_paused"


def test_le_defaut_est_90_jours():
    """⚠️ Le défaut n'est pas neutre : il décide quelles paires restent
    jugeables. 90 jours laisse largement le temps de réunir 30 clôtures à une
    paire active, et écarte le passé d'un autre courtier."""
    import re
    src = Path(__file__).resolve().parents[2] / "config" / "settings.py"
    trouve = re.search(
        r'PAIR_PNL_REGULATOR_MAX_AGE_DAYS = int\(os\.getenv\('
        r'"PAIR_PNL_REGULATOR_MAX_AGE_DAYS",\s*"(\d+)"\)\)',
        src.read_text(encoding="utf-8"))
    assert trouve and int(trouve.group(1)) == 90


# --- La separation par destination (2026-08-29, second volet) ------------
#
# ⛔ Le plancher d'age borne les degats dans le TEMPS. Il ne dit toujours pas
# de QUEL compte on parle : la fenetre melangeait demo, reel et anciens
# courtiers dans un seul verdict, et une pause s'appliquait partout.
#
# 🔑 Le contrat est celui de `pair_admission_state` : `destination` NULL =
# portee globale, une ligne par destination la precise. L'heritage va du
# particulier vers le global, et **jamais l'inverse**.


def test_la_fenetre_ne_voit_QUE_la_destination_demandee(_isolated_db):
    from backend.services import pair_pnl_regulator

    _insert_trade(_isolated_db, "XAG/USD", -500.0, destination="admin_legacy")
    _insert_trade(_isolated_db, "XAG/USD", +10.0, destination="admin_live")

    reel = pair_pnl_regulator.compute_window_metrics(
        "XAG/USD", 30, destination="admin_live")
    assert reel["n"] == 1 and reel["sum_pnl"] == 10.0

    demo = pair_pnl_regulator.compute_window_metrics(
        "XAG/USD", 30, destination="admin_legacy")
    assert demo["n"] == 1 and demo["sum_pnl"] == -500.0


def test_sans_destination_la_fenetre_reste_celle_d_avant(_isolated_db):
    """Le comportement historique doit survivre intact : c'est lui que lisent
    le tableau de bord et le backfill d'admission."""
    from backend.services import pair_pnl_regulator

    _insert_trade(_isolated_db, "XAG/USD", -500.0, destination="admin_legacy")
    _insert_trade(_isolated_db, "XAG/USD", +10.0, destination="admin_live")
    _insert_trade(_isolated_db, "XAG/USD", -1.0)  # ancienne ligne sans destination

    m = pair_pnl_regulator.compute_window_metrics("XAG/USD", 30)
    assert m["n"] == 3
    assert m["sum_pnl"] == -491.0


def test_les_trades_SANS_destination_ne_comptent_pour_AUCUN_compte(_isolated_db):
    """⛔ Le cas de l'argent : les trades de l'ancien compte demo portent
    `destination_id` NULL. Ils ne doivent etre attribues a personne — surtout
    pas au compte reel."""
    from backend.services import pair_pnl_regulator

    _insert_trade(_isolated_db, "XAG/USD", -500.0)  # ancien compte demo
    m = pair_pnl_regulator.compute_window_metrics(
        "XAG/USD", 30, destination="admin_live")
    assert m["n"] == 0


def test_l_EA_des_clients_sort_quand_une_destination_est_nommee(_isolated_db):
    """⚠️ Les trades de l'EA viennent des comptes des clients Premium. Les
    compter dans le verdict d'admin_live referait, entre comptes, l'erreur
    qu'on corrige entre courtiers."""
    from backend.services import ea_closed_trades_service, pair_pnl_regulator

    ea_closed_trades_service._ensure_schema()
    quand = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(_isolated_db) as c:
        c.execute(
            """
            INSERT INTO ea_closed_trades (user_id, pair, direction,
                entry_price, exit_price, pnl, mt5_ticket, closed_at, reported_at)
            VALUES (2, 'XAG/USD', 'sell', 1.0, 1.0, -300.0, 777, ?, ?)
            """,
            (quand, quand),
        )
    _insert_trade(_isolated_db, "XAG/USD", +5.0, destination="admin_live")

    cible = pair_pnl_regulator.compute_window_metrics(
        "XAG/USD", 30, destination="admin_live")
    assert cible["n"] == 1 and cible["sum_pnl"] == 5.0

    tout = pair_pnl_regulator.compute_window_metrics("XAG/USD", 30)
    assert tout["n"] == 2


# -- L'heritage des pauses -----------------------------------------------


def test_une_pause_GLOBALE_bloque_toutes_les_destinations(_isolated_db):
    """⛔ LE test fail-closed. Toutes les pauses posees avant le 29/08/2026 ont
    `destination` NULL : separer les comptes ne doit en relacher aucune."""
    from backend.services import pair_pnl_regulator

    pair_pnl_regulator.apply_pause("XAG/USD", "ev_negative", -50.0, 30)

    assert pair_pnl_regulator.is_paused("XAG/USD") is True
    assert pair_pnl_regulator.is_paused("XAG/USD", "admin_live") is True
    assert pair_pnl_regulator.is_paused("XAG/USD", "admin_kraken") is True


def test_une_pause_par_compte_ne_condamne_PAS_les_autres(_isolated_db):
    from backend.services import pair_pnl_regulator

    pair_pnl_regulator.apply_pause("XAG/USD", "ev_negative", -50.0, 30,
                                   destination="admin_legacy")

    assert pair_pnl_regulator.is_paused("XAG/USD", "admin_legacy") is True
    assert pair_pnl_regulator.is_paused("XAG/USD", "admin_live") is False
    assert pair_pnl_regulator.is_paused("XAG/USD") is False


def test_lever_la_pause_d_un_compte_ne_leve_PAS_la_globale(_isolated_db):
    """⛔ Sans portee exacte, `apply_resume` remonterait a la pause heritee et
    ouvrirait tous les comptes d'un coup."""
    from backend.services import pair_pnl_regulator

    pair_pnl_regulator.apply_pause("XAG/USD", "ev_negative", -50.0, 30)

    assert pair_pnl_regulator.apply_resume(
        "XAG/USD", "essai", destination="admin_live") is False
    assert pair_pnl_regulator.is_paused("XAG/USD", "admin_live") is True

    assert pair_pnl_regulator.apply_resume("XAG/USD", "levee globale") is True
    assert pair_pnl_regulator.is_paused("XAG/USD", "admin_live") is False


def test_pas_de_doublon_quand_une_pause_globale_court_deja(_isolated_db):
    """L'idempotence tient compte de l'heritage : le compte est deja bloque."""
    from backend.services import pair_pnl_regulator

    gid = pair_pnl_regulator.apply_pause("XAG/USD", "ev_negative", -50.0, 30)
    assert pair_pnl_regulator.apply_pause(
        "XAG/USD", "ev_negative", -50.0, 30, destination="admin_live") == gid


# -- Bout en bout --------------------------------------------------------


def test_un_compte_qui_saigne_ne_ferme_plus_l_autre(_isolated_db, monkeypatch,
                                                    plancher):
    """⛔ LE test central du second volet — le cas de l'argent, generalise.

    La demo saigne, le reel non. Avant, un seul verdict fermait les deux.
    """
    import config.settings as st
    from backend.services import pair_pnl_regulator

    monkeypatch.setattr(st, "TRADING_CAPITAL", 650.0)
    plancher(90)
    for _ in range(12):
        _insert_trade(_isolated_db, "XAG/USD", -20.0, destination="admin_legacy")
    for _ in range(12):
        _insert_trade(_isolated_db, "XAG/USD", +5.0, destination="admin_live")

    assert pair_pnl_regulator.evaluate_pair(
        "XAG/USD", destination="admin_legacy")["action"] == "pause"
    assert pair_pnl_regulator.evaluate_pair(
        "XAG/USD", destination="admin_live")["action"] == "keep_active"

    assert pair_pnl_regulator.is_paused("XAG/USD", "admin_legacy") is True
    assert pair_pnl_regulator.is_paused("XAG/USD", "admin_live") is False


def test_une_pause_globale_EXPIREE_est_bien_levee_globalement(_isolated_db):
    """⛔ En evaluant une destination, la pause trouvee peut etre la globale.
    La lever au nom de cette destination seule la laisserait courir pour
    toujours : plus rien ne viendrait la toucher."""
    from backend.services import pair_pnl_regulator

    pair_pnl_regulator.apply_pause("XAG/USD", "ev_negative", -50.0, 30)
    passe = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    with sqlite3.connect(_isolated_db) as c:
        c.execute("UPDATE auto_paused_pairs SET expires_at = ?", (passe,))

    d = pair_pnl_regulator.evaluate_pair("XAG/USD", destination="admin_live")
    assert d["action"] == "resume"
    assert pair_pnl_regulator.get_active_pause("XAG/USD") is None
    assert pair_pnl_regulator.is_paused("XAG/USD", "admin_kraken") is False


def test_les_destinations_evaluees_viennent_des_DONNEES(_isolated_db):
    """Une destination configuree mais jamais tradee n'a rien a juger ; une
    destination retiree du registre peut encore porter une pause a lever."""
    from backend.services import pair_pnl_regulator

    _insert_trade(_isolated_db, "XAU/USD", +1.0, destination="admin_live")
    pair_pnl_regulator.apply_pause("XAG/USD", "ev_negative", -50.0, 30,
                                   destination="destination_disparue")

    assert pair_pnl_regulator._destinations_actives() == [
        "admin_live", "destination_disparue"]


def test_la_porte_du_bridge_interroge_la_DESTINATION():
    """⛔ La logique ci-dessus ne dirait rien si `_check_rejection` continuait
    d'interroger la pause sans destination : un saignement sur la demo fermerait
    encore le compte reel. C'est la lecon du detecteur de positions nues — une
    logique correcte, jamais atteinte."""
    src = (Path(__file__).resolve().parents[1] / "services" / "mt5_bridge.py"
           ).read_text(encoding="utf-8")
    assert "pair_pnl_regulator.is_paused(setup.pair, dest_id_pause)" in src
