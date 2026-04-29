"""Tests Phase MQL.B — `mt5_pending_orders_service`.

Couvre : enqueue, fetch atomique avec marquage SENT, record_result,
purge_expired, isolation par api_key, TTL.
"""
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.services import mt5_pending_orders_service as svc, trade_log_service


@pytest.fixture
def db(tmp_path: Path):
    db_file = tmp_path / "trades.db"
    with patch.object(trade_log_service, "_DB_PATH", db_file):
        svc._ensure_schema()
        yield db_file


def _payload(pair: str = "EUR/USD") -> dict:
    return {
        "pair": pair,
        "direction": "buy",
        "entry": 1.10,
        "sl": 1.09,
        "tp": 1.11,
        "risk_money": 10.0,
        "comment": "test",
    }


# ─── enqueue ──────────────────────────────────────────────────────────


def test_enqueue_returns_id_and_persists(db):
    order_id = svc.enqueue(user_id=42, api_key="apikey_xxx", payload=_payload())
    assert order_id > 0
    counts = svc.count_by_status(user_id=42)
    assert counts == {"PENDING": 1}


def test_enqueue_with_custom_ttl(db):
    """Un order avec TTL court doit se faire purger plus vite."""
    order_id = svc.enqueue(
        user_id=42, api_key="apikey", payload=_payload(), ttl_seconds=1
    )
    assert order_id > 0
    time.sleep(1.5)
    purged = svc.purge_expired()
    assert purged == 1
    assert svc.count_by_status(user_id=42) == {"EXPIRED": 1}


# ─── fetch_for_api_key ────────────────────────────────────────────────


def test_fetch_returns_pending_and_marks_sent(db):
    svc.enqueue(user_id=42, api_key="alice", payload=_payload("EUR/USD"))
    svc.enqueue(user_id=42, api_key="alice", payload=_payload("XAU/USD"))

    fetched = svc.fetch_for_api_key("alice")
    assert len(fetched) == 2
    pairs = sorted([f["payload"]["pair"] for f in fetched])
    assert pairs == ["EUR/USD", "XAU/USD"]

    # Tous marqués SENT, plus rien à fetch au prochain appel
    assert svc.fetch_for_api_key("alice") == []
    assert svc.count_by_status(user_id=42) == {"SENT": 2}


def test_fetch_isolated_by_api_key(db):
    svc.enqueue(user_id=42, api_key="alice", payload=_payload())
    svc.enqueue(user_id=43, api_key="bob", payload=_payload())

    fetched_alice = svc.fetch_for_api_key("alice")
    assert len(fetched_alice) == 1
    assert fetched_alice[0]["user_id"] == 42

    # Bob a toujours son order PENDING
    fetched_bob = svc.fetch_for_api_key("bob")
    assert len(fetched_bob) == 1
    assert fetched_bob[0]["user_id"] == 43


def test_fetch_respects_limit(db):
    for i in range(10):
        svc.enqueue(user_id=42, api_key="alice", payload=_payload(f"PAIR{i}"))

    fetched = svc.fetch_for_api_key("alice", limit=3)
    assert len(fetched) == 3
    # Les 7 autres restent en PENDING
    assert svc.count_by_status(user_id=42) == {"PENDING": 7, "SENT": 3}


def test_fetch_returns_oldest_first(db):
    """ORDER BY created_at ASC : FIFO."""
    svc.enqueue(user_id=42, api_key="alice", payload=_payload("A"))
    time.sleep(0.01)  # force ordre temporel
    svc.enqueue(user_id=42, api_key="alice", payload=_payload("B"))

    fetched = svc.fetch_for_api_key("alice", limit=1)
    assert fetched[0]["payload"]["pair"] == "A"


def test_fetch_excludes_expired(db):
    """expires_at < now → exclu du fetch (mais reste PENDING en DB)."""
    svc.enqueue(user_id=42, api_key="alice", payload=_payload(), ttl_seconds=1)
    svc.enqueue(user_id=42, api_key="alice", payload=_payload("XAU/USD"), ttl_seconds=300)
    time.sleep(1.5)

    fetched = svc.fetch_for_api_key("alice")
    assert len(fetched) == 1
    assert fetched[0]["payload"]["pair"] == "XAU/USD"


def test_fetch_empty_when_no_orders(db):
    assert svc.fetch_for_api_key("nobody") == []


# ─── record_result ────────────────────────────────────────────────────


def test_record_result_ok_marks_executed(db):
    order_id = svc.enqueue(user_id=42, api_key="alice", payload=_payload())
    svc.fetch_for_api_key("alice")  # passe en SENT

    success = svc.record_result(
        order_id, api_key="alice", ok=True, mt5_ticket=123456
    )
    assert success is True
    assert svc.count_by_status(user_id=42) == {"EXECUTED": 1}


def test_record_result_failed_marks_failed(db):
    order_id = svc.enqueue(user_id=42, api_key="alice", payload=_payload())
    svc.fetch_for_api_key("alice")

    success = svc.record_result(
        order_id, api_key="alice", ok=False, error="rc=10016 INVALID_STOPS"
    )
    assert success is True
    assert svc.count_by_status(user_id=42) == {"FAILED": 1}


def test_record_result_rejected_for_wrong_api_key(db):
    """L'EA d'un autre user ne peut pas ack l'order de mon user."""
    order_id = svc.enqueue(user_id=42, api_key="alice", payload=_payload())
    svc.fetch_for_api_key("alice")

    success = svc.record_result(
        order_id, api_key="bob_attacker", ok=True, mt5_ticket=999
    )
    assert success is False
    assert svc.count_by_status(user_id=42) == {"SENT": 1}  # toujours SENT


def test_record_result_rejected_for_pending_order(db):
    """Ne peut ack qu'un order SENT, pas un PENDING."""
    order_id = svc.enqueue(user_id=42, api_key="alice", payload=_payload())
    # PAS de fetch → reste PENDING

    success = svc.record_result(
        order_id, api_key="alice", ok=True, mt5_ticket=123
    )
    assert success is False


def test_record_result_truncates_long_error(db):
    order_id = svc.enqueue(user_id=42, api_key="alice", payload=_payload())
    svc.fetch_for_api_key("alice")

    long_err = "x" * 1000
    svc.record_result(order_id, api_key="alice", ok=False, error=long_err)

    import sqlite3
    with sqlite3.connect(db) as c:
        row = c.execute(
            "SELECT mt5_error FROM mt5_pending_orders WHERE id=?", (order_id,)
        ).fetchone()
    assert len(row[0]) <= 500


# ─── purge_expired ────────────────────────────────────────────────────


def test_purge_marks_old_pending_as_expired(db):
    svc.enqueue(user_id=42, api_key="alice", payload=_payload(), ttl_seconds=1)
    svc.enqueue(user_id=42, api_key="alice", payload=_payload("XAU/USD"), ttl_seconds=300)
    time.sleep(1.5)

    purged = svc.purge_expired()
    assert purged == 1
    counts = svc.count_by_status(user_id=42)
    assert counts.get("EXPIRED") == 1
    assert counts.get("PENDING") == 1


def test_purge_doesnt_touch_executed(db):
    """Un order EXECUTED reste EXECUTED même après TTL — c'est du log."""
    order_id = svc.enqueue(
        user_id=42, api_key="alice", payload=_payload(), ttl_seconds=1
    )
    svc.fetch_for_api_key("alice")
    svc.record_result(order_id, api_key="alice", ok=True, mt5_ticket=1)
    time.sleep(1.5)

    purged = svc.purge_expired()
    assert purged == 0
    assert svc.count_by_status(user_id=42) == {"EXECUTED": 1}


# ─── _ensure_schema idempotent ────────────────────────────────────────


def test_ensure_schema_is_idempotent(db):
    svc._ensure_schema()
    svc._ensure_schema()  # ne doit pas raise


# ─── count_by_status ──────────────────────────────────────────────────


def test_count_by_status_global(db):
    svc.enqueue(user_id=42, api_key="alice", payload=_payload())
    svc.enqueue(user_id=43, api_key="bob", payload=_payload())

    counts = svc.count_by_status()  # pas de filtre user
    assert counts == {"PENDING": 2}


def test_count_by_status_per_user(db):
    svc.enqueue(user_id=42, api_key="alice", payload=_payload())
    svc.enqueue(user_id=42, api_key="alice", payload=_payload("XAU/USD"))
    svc.enqueue(user_id=43, api_key="bob", payload=_payload())

    assert svc.count_by_status(user_id=42) == {"PENDING": 2}
    assert svc.count_by_status(user_id=43) == {"PENDING": 1}
