"""Tests isolation multi-tenant pour insights_service + analytics_service
(Chantier 3B SaaS).

Vérifie qu'Alice ne voit pas les trades de Bob via toutes les routes insights,
et que analytics._execution_quality est aussi scoped.
"""

import json
import sqlite3

import pytest

from backend.services import analytics_service, insights_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    """DB avec schéma complet incluant user_id."""
    db_file = tmp_path / "trades.db"
    conn = sqlite3.connect(db_file)
    conn.execute("""
        CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY,
            user TEXT, user_id INTEGER,
            pair TEXT, direction TEXT,
            entry_price REAL, stop_loss REAL, take_profit REAL,
            size_lot REAL, signal_pattern TEXT, signal_confidence REAL,
            checklist_passed INTEGER, notes TEXT, status TEXT,
            created_at TEXT, mt5_ticket INTEGER, is_auto INTEGER,
            post_entry_sl INTEGER, post_entry_tp INTEGER, post_entry_size INTEGER,
            context_macro TEXT, exit_price REAL, pnl REAL, closed_at TEXT,
            close_reason TEXT, slippage_pips REAL
        )
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(insights_service, "_db_path", lambda: str(db_file))
    monkeypatch.setattr(analytics_service, "_trades_db", lambda: str(db_file))
    # Reset cache analytics pour isoler entre tests.
    analytics_service._ANALYTICS_CACHE.clear()
    return str(db_file)


def _seed_trades_for_two_users(db):
    """Alice (uid=1) : 3 trades gagnants EUR/USD.
    Bob (uid=2) : 2 trades perdants XAU/USD."""
    alice_trades = [
        ("alice@test.com", 1, "EUR/USD", 20.0, "2026-04-23T10:00:00+00:00", "2026-04-23T10:30:00+00:00", "TP1"),
        ("alice@test.com", 1, "EUR/USD", 15.0, "2026-04-23T11:00:00+00:00", "2026-04-23T11:30:00+00:00", "TP2"),
        ("alice@test.com", 1, "EUR/USD", 25.0, "2026-04-23T12:00:00+00:00", "2026-04-23T12:30:00+00:00", "TP1"),
    ]
    bob_trades = [
        ("bob@test.com", 2, "XAU/USD", -30.0, "2026-04-23T10:00:00+00:00", "2026-04-23T10:30:00+00:00", "SL"),
        ("bob@test.com", 2, "XAU/USD", -20.0, "2026-04-23T11:00:00+00:00", "2026-04-23T11:30:00+00:00", "SL"),
    ]
    with sqlite3.connect(db) as c:
        for user, uid, pair, pnl, created, closed, close_reason in alice_trades + bob_trades:
            c.execute(
                """INSERT INTO personal_trades
                   (user, user_id, pair, direction, is_auto, status, pnl,
                    created_at, closed_at, close_reason, signal_confidence,
                    entry_price, stop_loss, take_profit, size_lot, slippage_pips,
                    context_macro)
                   VALUES (?, ?, ?, 'buy', 1, 'CLOSED', ?, ?, ?, ?, 75.0,
                           1.1, 1.09, 1.12, 0.1, 0.5, ?)""",
                (user, uid, pair, pnl, created, closed, close_reason,
                 json.dumps({"risk_regime": "neutral"})),
            )


# ─── insights_service ─────────────────────────────────────────

def test_get_performance_scoped_by_user_id(db):
    _seed_trades_for_two_users(db)

    alice = insights_service.get_performance(user_id=1)
    bob = insights_service.get_performance(user_id=2)

    assert alice["total_trades"] == 3
    assert alice["total_pnl"] == 60.0  # 20 + 15 + 25
    assert bob["total_trades"] == 2
    assert bob["total_pnl"] == -50.0  # -30 - 20


def test_get_performance_no_user_returns_all(db):
    """Sans user/user_id, retourne tout (admin/internal)."""
    _seed_trades_for_two_users(db)
    allout = insights_service.get_performance()
    assert allout["total_trades"] == 5


def test_get_equity_curve_scoped(db):
    _seed_trades_for_two_users(db)

    alice = insights_service.get_equity_curve(user_id=1)
    assert alice["total_trades"] == 3
    # Dernière valeur = somme pnls Alice
    assert alice["final_pnl"] == 60.0

    bob = insights_service.get_equity_curve(user_id=2)
    assert bob["total_trades"] == 2
    assert bob["final_pnl"] == -50.0


def test_get_period_stats_range_scoped(db):
    _seed_trades_for_two_users(db)

    since, until = "2026-04-23T00:00:00+00:00", "2026-04-23T23:59:59+00:00"
    alice = insights_service.get_period_stats_range(since, until, user_id=1)
    bob = insights_service.get_period_stats_range(since, until, user_id=2)

    assert alice["n_trades"] == 3
    assert alice["n_wins"] == 3
    assert alice["win_rate"] == 1.0

    assert bob["n_trades"] == 2
    assert bob["n_wins"] == 0


def test_get_pnl_buckets_scoped(db):
    _seed_trades_for_two_users(db)
    since, until = "2026-04-23T00:00:00+00:00", "2026-04-23T23:59:59+00:00"

    alice = insights_service.get_pnl_buckets(since, until, granularity="day", user_id=1)
    bob = insights_service.get_pnl_buckets(since, until, granularity="day", user_id=2)

    alice_total = sum(b["pnl"] for b in alice["buckets"])
    bob_total = sum(b["pnl"] for b in bob["buckets"])
    assert alice_total == 60.0
    assert bob_total == -50.0


def test_get_exposure_timeseries_scoped(db):
    """Open trades spécifiques par user."""
    with sqlite3.connect(db) as c:
        c.execute(
            """INSERT INTO personal_trades (user, user_id, pair, direction, is_auto,
               status, entry_price, stop_loss, take_profit, size_lot, created_at, closed_at)
               VALUES ('alice@test.com', 1, 'EUR/USD', 'buy', 1, 'OPEN',
                       1.1, 1.09, 1.12, 0.1, '2026-04-23T10:00:00+00:00', NULL)"""
        )
        c.execute(
            """INSERT INTO personal_trades (user, user_id, pair, direction, is_auto,
               status, entry_price, stop_loss, take_profit, size_lot, created_at, closed_at)
               VALUES ('bob@test.com', 2, 'XAU/USD', 'buy', 1, 'OPEN',
                       2000.0, 1990.0, 2020.0, 0.2, '2026-04-23T10:00:00+00:00', NULL)"""
        )

    since, until = "2026-04-23T10:00:00+00:00", "2026-04-23T12:00:00+00:00"
    alice = insights_service.get_exposure_timeseries(since, until, granularity="hour", user_id=1)
    bob = insights_service.get_exposure_timeseries(since, until, granularity="hour", user_id=2)

    # Alice : 1 position ouverte sur ces heures, Bob aussi.
    assert alice["max_open"] == 1
    assert bob["max_open"] == 1
    # Risques différents : Alice EUR/USD 0.1 lot = 100€, Bob XAU/USD 0.2 lot = 200€.
    assert alice["peak_at_risk"] == 100.0
    assert bob["peak_at_risk"] == 200.0


def test_legacy_user_text_fallback(db):
    """User env sans user_id → fallback sur colonne user TEXT."""
    with sqlite3.connect(db) as c:
        c.execute(
            """INSERT INTO personal_trades (user, user_id, pair, direction, is_auto,
               status, pnl, created_at, closed_at, signal_confidence, entry_price,
               stop_loss, take_profit, size_lot, context_macro)
               VALUES ('legacy-admin', NULL, 'EUR/USD', 'buy', 1, 'CLOSED', 10.0,
                       '2026-04-23T10:00:00+00:00', '2026-04-23T11:00:00+00:00',
                       70.0, 1.1, 1.09, 1.12, 0.1, '{}')"""
        )

    out = insights_service.get_performance(user="legacy-admin")
    assert out["total_trades"] == 1


# ─── analytics_service._execution_quality ─────────────────────

def test_execution_quality_scoped_by_user_id(db):
    _seed_trades_for_two_users(db)

    alice = analytics_service._execution_quality(user_id=1)
    bob = analytics_service._execution_quality(user_id=2)

    assert alice["total_closed_trades"] == 3
    assert bob["total_closed_trades"] == 2

    # Slippage breakdown : Alice a EUR/USD, Bob a XAU/USD.
    alice_pairs = {s["pair"] for s in alice["slippage_by_pair"]}
    bob_pairs = {s["pair"] for s in bob["slippage_by_pair"]}
    assert alice_pairs == {"EUR/USD"}
    assert bob_pairs == {"XAU/USD"}


def test_analytics_cache_per_user(db, monkeypatch):
    """Le cache analytics est par user : Alice et Bob ont chacun leur entrée."""
    _seed_trades_for_two_users(db)

    # Stub les autres breakdowns qui touchent backtest.db pour isoler le test.
    monkeypatch.setattr(analytics_service, "_by_pair", lambda: [])
    monkeypatch.setattr(analytics_service, "_by_hour", lambda: [])
    monkeypatch.setattr(analytics_service, "_by_pattern", lambda: [])
    monkeypatch.setattr(analytics_service, "_by_confidence_bucket", lambda: [])
    monkeypatch.setattr(analytics_service, "_by_asset_class", lambda: [])
    monkeypatch.setattr(analytics_service, "_by_risk_regime", lambda: [])
    monkeypatch.setattr(analytics_service, "_signal_volume", lambda: {})

    alice_data = analytics_service.build_analytics(user_id=1)
    bob_data = analytics_service.build_analytics(user_id=2)

    assert alice_data["execution_quality"]["total_closed_trades"] == 3
    assert bob_data["execution_quality"]["total_closed_trades"] == 2

    # Entrées cache séparées
    assert "uid:1" in analytics_service._ANALYTICS_CACHE
    assert "uid:2" in analytics_service._ANALYTICS_CACHE
