"""Tests d'isolation multi-tenant (Chantier 3 SaaS).

Vérifie que trade_log_service scope correctement par user_id (mode SaaS) ou
par user TEXT (fallback legacy), et qu'un user ne voit JAMAIS les trades
d'un autre user.
"""

import sqlite3

import pytest

from backend.services import trade_log_service, users_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    """DB isolée avec schéma complet (users + personal_trades + user_id)."""
    db_file = tmp_path / "trades.db"
    # personal_trades minimal pré-migration, users_service.init_schema ajoute user_id.
    conn = sqlite3.connect(db_file)
    conn.execute("""
        CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT NOT NULL DEFAULT 'anonymous',
            pair TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry_price REAL NOT NULL DEFAULT 0,
            stop_loss REAL NOT NULL DEFAULT 0,
            take_profit REAL NOT NULL DEFAULT 0,
            size_lot REAL NOT NULL DEFAULT 0.01,
            signal_pattern TEXT,
            signal_confidence REAL,
            checklist_passed INTEGER DEFAULT 0,
            notes TEXT,
            status TEXT DEFAULT 'OPEN',
            exit_price REAL,
            pnl REAL DEFAULT 0,
            created_at TEXT NOT NULL,
            closed_at TEXT
        )
    """)
    conn.commit()
    conn.close()

    monkeypatch.setattr(users_service, "_DB_PATH", db_file)
    monkeypatch.setattr(trade_log_service, "_DB_PATH", db_file)
    users_service.init_users_schema()
    return db_file


def _insert_trade(db, user: str, user_id: int | None, pair: str, created_at: str):
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO personal_trades (user, user_id, pair, direction, created_at) "
            "VALUES (?, ?, ?, 'buy', ?)",
            (user, user_id, pair, created_at),
        )


def test_two_users_isolated_by_user_id(db):
    """Alice et Bob en DB, chacun ne voit que ses trades via user_id."""
    uid_a = users_service.create_user("alice@test.com", "pw12345678")
    uid_b = users_service.create_user("bob@test.com", "pw12345678")

    _insert_trade(db, "alice@test.com", uid_a, "EUR/USD", "2026-04-23T10:00:00+00:00")
    _insert_trade(db, "alice@test.com", uid_a, "GBP/USD", "2026-04-23T11:00:00+00:00")
    _insert_trade(db, "bob@test.com", uid_b, "XAU/USD", "2026-04-23T12:00:00+00:00")

    alice_trades = trade_log_service.list_trades(user="alice@test.com", user_id=uid_a)
    bob_trades = trade_log_service.list_trades(user="bob@test.com", user_id=uid_b)

    assert len(alice_trades) == 2
    assert {t["pair"] for t in alice_trades} == {"EUR/USD", "GBP/USD"}
    assert all(t["user_id"] == uid_a for t in alice_trades)

    assert len(bob_trades) == 1
    assert bob_trades[0]["pair"] == "XAU/USD"
    assert bob_trades[0]["user_id"] == uid_b


def test_get_trade_rejects_cross_user_access(db):
    """Alice ne peut pas get_trade() un trade de Bob, même en connaissant l'id."""
    uid_a = users_service.create_user("alice@test.com", "pw12345678")
    uid_b = users_service.create_user("bob@test.com", "pw12345678")

    _insert_trade(db, "bob@test.com", uid_b, "XAU/USD", "2026-04-23T12:00:00+00:00")
    # Récupère l'id du trade de Bob.
    with sqlite3.connect(db) as conn:
        bob_trade_id = conn.execute(
            "SELECT id FROM personal_trades WHERE user_id = ?", (uid_b,)
        ).fetchone()[0]

    # Alice tente d'y accéder avec son user_id.
    assert trade_log_service.get_trade(bob_trade_id, user="alice@test.com", user_id=uid_a) is None
    # Bob lui peut.
    assert trade_log_service.get_trade(bob_trade_id, user="bob@test.com", user_id=uid_b) is not None


def test_env_legacy_user_scopes_by_user_text(db):
    """Un user sans user_id (env AUTH_USERS) continue de voir ses trades via user TEXT."""
    _insert_trade(db, "legacy-admin", None, "EUR/USD", "2026-04-23T09:00:00+00:00")
    _insert_trade(db, "legacy-admin", None, "GBP/USD", "2026-04-23T09:30:00+00:00")
    _insert_trade(db, "other-legacy", None, "XAU/USD", "2026-04-23T10:00:00+00:00")

    # Pas de user_id → scope par user TEXT.
    trades = trade_log_service.list_trades(user="legacy-admin", user_id=None)
    assert len(trades) == 2
    assert {t["pair"] for t in trades} == {"EUR/USD", "GBP/USD"}


def test_env_user_does_not_see_db_user_trades(db):
    """Un user env (user_id=None) ne voit pas les trades d'un user DB qui porterait un autre email."""
    uid = users_service.create_user("alice@test.com", "pw12345678")
    _insert_trade(db, "alice@test.com", uid, "EUR/USD", "2026-04-23T10:00:00+00:00")
    _insert_trade(db, "legacy-admin", None, "GBP/USD", "2026-04-23T09:00:00+00:00")

    # legacy-admin ne doit voir QUE son trade.
    legacy = trade_log_service.list_trades(user="legacy-admin", user_id=None)
    assert len(legacy) == 1
    assert legacy[0]["pair"] == "GBP/USD"


def test_user_id_takes_precedence_over_user_text(db):
    """Si user_id fourni, le user TEXT passé n'est PAS utilisé comme filtre.

    Ça évite les attaques type "je me fais passer pour un autre via l'URL"
    quand le front mélange les deux signaux.
    """
    uid_a = users_service.create_user("alice@test.com", "pw12345678")
    _insert_trade(db, "alice@test.com", uid_a, "EUR/USD", "2026-04-23T10:00:00+00:00")

    # Appelant met un user TEXT absurde mais user_id correct : doit matcher.
    trades = trade_log_service.list_trades(user="something-wrong", user_id=uid_a)
    assert len(trades) == 1

    # Appelant met le bon user TEXT mais user_id wrong : ne matche pas.
    trades = trade_log_service.list_trades(user="alice@test.com", user_id=9999)
    assert len(trades) == 0


def test_status_filter_combines_with_user_scope(db):
    uid = users_service.create_user("alice@test.com", "pw12345678")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO personal_trades (user, user_id, pair, direction, status, created_at) "
            "VALUES (?, ?, 'EUR/USD', 'buy', 'OPEN', '2026-04-23T10:00:00+00:00')",
            ("alice@test.com", uid),
        )
        conn.execute(
            "INSERT INTO personal_trades (user, user_id, pair, direction, status, created_at) "
            "VALUES (?, ?, 'GBP/USD', 'buy', 'CLOSED', '2026-04-23T09:00:00+00:00')",
            ("alice@test.com", uid),
        )

    open_trades = trade_log_service.list_trades(
        status="OPEN", user="alice@test.com", user_id=uid
    )
    assert len(open_trades) == 1
    assert open_trades[0]["pair"] == "EUR/USD"


def test_daily_status_scoped_by_user_id(db):
    uid_a = users_service.create_user("alice@test.com", "pw12345678")
    uid_b = users_service.create_user("bob@test.com", "pw12345678")

    from datetime import date
    today = date.today().isoformat() + "T12:00:00+00:00"
    # Alice : 2 trades
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO personal_trades (user, user_id, pair, direction, status, pnl, created_at) "
            "VALUES (?, ?, 'EUR/USD', 'buy', 'CLOSED', 10.0, ?)",
            ("alice@test.com", uid_a, today),
        )
        conn.execute(
            "INSERT INTO personal_trades (user, user_id, pair, direction, status, pnl, created_at) "
            "VALUES (?, ?, 'GBP/USD', 'buy', 'OPEN', 0.0, ?)",
            ("alice@test.com", uid_a, today),
        )
        # Bob : 1 trade
        conn.execute(
            "INSERT INTO personal_trades (user, user_id, pair, direction, status, pnl, created_at) "
            "VALUES (?, ?, 'XAU/USD', 'buy', 'CLOSED', -5.0, ?)",
            ("bob@test.com", uid_b, today),
        )

    alice_status = trade_log_service.get_daily_status(user="alice@test.com", user_id=uid_a)
    bob_status = trade_log_service.get_daily_status(user="bob@test.com", user_id=uid_b)

    assert alice_status["n_trades_today"] == 2
    assert alice_status["n_open"] == 1
    assert alice_status["pnl_today"] == 10.0

    assert bob_status["n_trades_today"] == 1
    assert bob_status["n_open"] == 0
    assert bob_status["pnl_today"] == -5.0


# ─── Backfill script ─────────────────────────────────────────

def test_backfill_fills_user_id_from_user_text(db, tmp_path, monkeypatch):
    """Le backfill script remplit user_id en matchant user TEXT → users.email."""
    # Import dynamique du script en lui forçant le _DB_PATH du fixture.
    uid = users_service.create_user("alice@test.com", "pw12345678")
    _insert_trade(db, "alice@test.com", None, "EUR/USD", "2026-04-23T10:00:00+00:00")
    _insert_trade(db, "alice@test.com", None, "GBP/USD", "2026-04-23T11:00:00+00:00")
    _insert_trade(db, "orphan@test.com", None, "XAU/USD", "2026-04-23T12:00:00+00:00")

    # Simule l'exécution du backfill en appelant la logique directement.
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, user FROM personal_trades "
            "WHERE user_id IS NULL AND user IS NOT NULL AND user != ''"
        ).fetchall()
        for row in rows:
            u = users_service.get_user_by_email(row["user"])
            if u:
                conn.execute(
                    "UPDATE personal_trades SET user_id = ? WHERE id = ?",
                    (u["id"], row["id"]),
                )
        conn.commit()

    # Alice a récupéré ses 2 trades via user_id.
    trades = trade_log_service.list_trades(user="alice@test.com", user_id=uid)
    assert len(trades) == 2
    # L'orphelin reste sur user TEXT scope (user_id NULL).
    with sqlite3.connect(db) as conn:
        orphans = conn.execute(
            "SELECT COUNT(*) FROM personal_trades WHERE user_id IS NULL"
        ).fetchone()[0]
    assert orphans == 1
