"""Tests pour backend.services.ea_closed_trades_service + endpoint /api/ea/closed-trade."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Redirige _DB_PATH vers une DB temporaire pour isolation tests."""
    db_path = tmp_path / "trades.db"
    from backend.services import trade_log_service

    monkeypatch.setattr(trade_log_service, "_DB_PATH", db_path)

    from backend.services import ea_closed_trades_service
    monkeypatch.setattr(ea_closed_trades_service, "_SCHEMA_ENSURED", False)

    # Table mt5_pending_orders pour tester le pair lookup
    with sqlite3.connect(db_path) as c:
        c.execute(
            """
            CREATE TABLE mt5_pending_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, api_key TEXT, payload TEXT, status TEXT,
                created_at TEXT, fetched_at TEXT, executed_at TEXT,
                mt5_ticket INTEGER, mt5_error TEXT, expires_at TEXT
            )
            """
        )
    yield db_path


# ─── normalize_pair ─────────────────────────────────────────────────────


def test_normalize_pair_via_mt5_pending_orders(_isolated_db):
    """Lookup par mt5_ticket en priorité."""
    from backend.services import ea_closed_trades_service

    with sqlite3.connect(_isolated_db) as c:
        c.execute(
            "INSERT INTO mt5_pending_orders (user_id, payload, status, mt5_ticket) VALUES (?, ?, ?, ?)",
            (17, '{"pair": "WTI/USD", "direction": "sell"}', "EXECUTED", 12345),
        )
    result = ea_closed_trades_service.normalize_pair("USOIL", 17, 12345)
    assert result == "WTI/USD"


def test_normalize_pair_heuristic_oil():
    from backend.services import ea_closed_trades_service
    assert ea_closed_trades_service.normalize_pair("USOIL", 17) == "WTI/USD"
    assert ea_closed_trades_service.normalize_pair("WTI", 17) == "WTI/USD"
    assert ea_closed_trades_service.normalize_pair("XTIUSD", 17) == "WTI/USD"


def test_normalize_pair_heuristic_metals():
    from backend.services import ea_closed_trades_service
    assert ea_closed_trades_service.normalize_pair("GOLD", 17) == "XAU/USD"
    assert ea_closed_trades_service.normalize_pair("XAUUSD", 17) == "XAU/USD"
    assert ea_closed_trades_service.normalize_pair("SILVER", 17) == "XAG/USD"
    assert ea_closed_trades_service.normalize_pair("XAGUSDm", 17) == "XAG/USD"


def test_normalize_pair_heuristic_indices():
    from backend.services import ea_closed_trades_service
    assert ea_closed_trades_service.normalize_pair("US500", 17) == "SPX"
    assert ea_closed_trades_service.normalize_pair("SPX500", 17) == "SPX"
    assert ea_closed_trades_service.normalize_pair("NAS100", 17) == "NDX"


def test_normalize_pair_heuristic_forex():
    from backend.services import ea_closed_trades_service
    assert ea_closed_trades_service.normalize_pair("EURUSD", 17) == "EUR/USD"
    assert ea_closed_trades_service.normalize_pair("GBPJPY", 17) == "GBP/JPY"
    # Avec suffixe broker
    assert ea_closed_trades_service.normalize_pair("EURUSDm", 17) == "EUR/USD"


# ─── record + dedup ─────────────────────────────────────────────────────


def test_record_basic(_isolated_db):
    from backend.services import ea_closed_trades_service

    inserted_id = ea_closed_trades_service.record(
        user_id=17, pair="USOIL", direction="sell",
        entry_price=100.0, exit_price=98.0, pnl=20.0,
        volume=0.1, mt5_ticket=99999, mt5_deal_id=11111,
        magic=20260429,
    )
    assert inserted_id is not None
    # Pair doit être normalisé via heuristique (USOIL → WTI/USD)
    trades = ea_closed_trades_service.get_last_n_for_pair(17, "WTI/USD", 10)
    assert len(trades) == 1


def test_record_dedup_on_deal_id(_isolated_db):
    """Re-record du même deal_id retourne None (dédup silencieux)."""
    from backend.services import ea_closed_trades_service

    id1 = ea_closed_trades_service.record(
        user_id=17, pair="USOIL", direction="sell",
        entry_price=100.0, exit_price=98.0, pnl=20.0,
        mt5_deal_id=11111, magic=20260429,
    )
    id2 = ea_closed_trades_service.record(
        user_id=17, pair="USOIL", direction="sell",
        entry_price=100.0, exit_price=98.0, pnl=20.0,
        mt5_deal_id=11111, magic=20260429,
    )
    assert id1 is not None
    assert id2 is None  # dedup


def test_record_normalizes_pair_only_if_no_slash(_isolated_db):
    """Si pair contient déjà '/', on ne tente pas la normalisation."""
    from backend.services import ea_closed_trades_service

    ea_closed_trades_service.record(
        user_id=17, pair="WTI/USD", direction="sell",
        entry_price=100.0, exit_price=98.0, pnl=20.0,
    )
    trades = ea_closed_trades_service.get_last_n_for_pair(17, "WTI/USD", 10)
    assert len(trades) == 1
