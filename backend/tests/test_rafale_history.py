"""Tests pour la persistance d'historique des rafales."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import kill_switch, rafale_history, trade_log_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_file = tmp_path / "trades.db"
    sqlite3.connect(db_file).close()
    monkeypatch.setattr(trade_log_service, "_DB_PATH", db_file)
    trade_log_service._init_schema()
    rafale_history._ensure_schema()

    ks_file = tmp_path / "kill_switch.json"
    monkeypatch.setattr(kill_switch, "_STATE_PATH", ks_file)
    return str(db_file)


def test_log_pause_set_and_list(db):
    rafale_history.log_pause_set(
        scope="pair", pair="XAU/USD", reason="3 SL en 1h",
        failed_pattern="range_bounce_down", failed_direction="sell",
        triggered_at=datetime.now(timezone.utc).isoformat(),
    )
    events = rafale_history.list_recent_events()
    assert len(events) == 1
    e = events[0]
    assert e["event_type"] == "PAUSE_SET"
    assert e["scope"] == "pair"
    assert e["pair"] == "XAU/USD"
    assert e["failed_pattern"] == "range_bounce_down"


def test_log_resume_calculates_duration(db):
    triggered = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
    rafale_history.log_resume(
        scope="pair", pair="XAU/USD", decision="SMART_RESUME",
        triggered_at=triggered, reason="r", failed_pattern="p",
    )
    events = rafale_history.list_recent_events()
    assert len(events) == 1
    e = events[0]
    assert e["event_type"] == "RESUME"
    assert e["resume_decision"] == "SMART_RESUME"
    # Duration ~2700s ± fluctuation
    assert e["duration_seconds"] is not None
    assert 2600 < e["duration_seconds"] < 2800


def test_list_recent_events_filters_by_window(db):
    # Insert 1 ancien (>7j) + 2 récents
    old_iso = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    with sqlite3.connect(db) as c:
        c.execute(
            """
            INSERT INTO rafale_pause_history
                (created_at, event_type, scope, pair)
            VALUES (?, ?, ?, ?)
            """,
            (old_iso, "PAUSE_SET", "pair", "XAU/USD"),
        )
    rafale_history.log_pause_set(scope="pair", pair="XAG/USD", reason="r1")
    rafale_history.log_pause_set(scope="pair", pair="ETH/USD", reason="r2")

    events = rafale_history.list_recent_events(days=7)
    pairs_in_window = {e["pair"] for e in events}
    assert "XAG/USD" in pairs_in_window
    assert "ETH/USD" in pairs_in_window
    assert "XAU/USD" not in pairs_in_window  # old


def test_stats_aggregate_correctly(db):
    # 3 PAUSE_SET (XAU x2, XAG x1) + 2 RESUME (1 SMART, 1 FORCE)
    rafale_history.log_pause_set(scope="pair", pair="XAU/USD", reason="r")
    rafale_history.log_pause_set(scope="pair", pair="XAU/USD", reason="r")
    rafale_history.log_pause_set(scope="pair", pair="XAG/USD", reason="r")

    triggered_a = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    triggered_b = (datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat()
    rafale_history.log_resume(
        scope="pair", pair="XAU/USD", decision="SMART_RESUME",
        triggered_at=triggered_a, reason="r",
    )
    rafale_history.log_resume(
        scope="pair", pair="XAG/USD", decision="FORCE_RESUME",
        triggered_at=triggered_b, reason="r",
    )

    stats = rafale_history.stats_for_window(days=7)
    assert stats["pause_set_count"] == 3
    assert stats["resume_count"] == 2
    assert stats["avg_duration_seconds"] is not None
    by_pair = {r["pair"]: r["count"] for r in stats["by_pair"]}
    assert by_pair["XAU/USD"] == 2
    assert by_pair["XAG/USD"] == 1
    assert stats["by_decision"]["SMART_RESUME"] == 1
    assert stats["by_decision"]["FORCE_RESUME"] == 1


def test_set_pair_rafale_pause_logs_event(db):
    """Le hook dans kill_switch.set_pair_rafale_pause doit logger PAUSE_SET."""
    kill_switch.set_pair_rafale_pause(
        pair="XAU/USD", reason="3 SL test",
        min_cool_off_min=30, max_pause_hours=2,
        failed_pattern="range_bounce_down", failed_direction="sell",
    )
    events = rafale_history.list_recent_events()
    assert len(events) == 1
    assert events[0]["event_type"] == "PAUSE_SET"
    assert events[0]["pair"] == "XAU/USD"
    assert events[0]["failed_pattern"] == "range_bounce_down"


def test_set_global_rafale_pause_logs_event(db):
    """Hook dans set_global_rafale_pause."""
    kill_switch.set_global_rafale_pause("incident systémique", duration_min=120)
    events = rafale_history.list_recent_events()
    assert len(events) == 1
    assert events[0]["event_type"] == "PAUSE_SET"
    assert events[0]["scope"] == "global"
    assert events[0]["pair"] is None


def test_log_resume_without_triggered_at(db):
    """Si triggered_at None, duration_seconds = None mais log OK."""
    rafale_history.log_resume(
        scope="pair", pair="XAU/USD", decision="MANUAL",
        triggered_at=None,
    )
    events = rafale_history.list_recent_events()
    assert len(events) == 1
    assert events[0]["duration_seconds"] is None


def test_empty_window_returns_empty(db):
    """Aucun event → list vide + stats à 0."""
    events = rafale_history.list_recent_events()
    stats = rafale_history.stats_for_window()
    assert events == []
    assert stats["pause_set_count"] == 0
    assert stats["resume_count"] == 0
    assert stats["by_pair"] == []


# ─── Endpoint /api/admin/watchdog/history ─────────────────────────────


@pytest.mark.asyncio
async def test_watchdog_history_endpoint_returns_events_and_stats(db, monkeypatch):
    from backend import app as app_module
    from backend.auth import AuthContext

    monkeypatch.setattr(app_module, "ADMIN_EMAILS", ["admin@test.com"])

    rafale_history.log_pause_set(scope="pair", pair="XAU/USD", reason="r")
    rafale_history.log_resume(
        scope="pair", pair="XAU/USD", decision="SMART_RESUME",
        triggered_at=(datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
        reason="r",
    )

    out = await app_module.api_admin_watchdog_history(
        days=7, limit=100,
        _ctx=AuthContext(username="admin@test.com", user_id=1),
    )
    assert "events" in out
    assert "stats" in out
    assert len(out["events"]) == 2
    assert out["stats"]["pause_set_count"] == 1
    assert out["stats"]["resume_count"] == 1
