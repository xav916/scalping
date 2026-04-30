"""Tests endpoints /api/admin/watchdog/{state,unpause}."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from backend.services import kill_switch, rejection_service, trade_log_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    """DB SQLite isolée + kill_switch state isolé."""
    db_file = tmp_path / "trades.db"
    sqlite3.connect(db_file).close()
    monkeypatch.setattr(trade_log_service, "_DB_PATH", db_file)
    trade_log_service._init_schema()
    rejection_service._ensure_schema()

    ks_file = tmp_path / "kill_switch.json"
    monkeypatch.setattr(kill_switch, "_STATE_PATH", ks_file)

    yield str(db_file)


def _admin_ctx():
    from backend.auth import AuthContext
    return AuthContext(username="admin@test.com", user_id=1)


def _insert_sl(db, closed_at, pair="XAU/USD", pattern="range_bounce_down",
               pnl=-15.0, is_auto=1, close_reason="SL"):
    with sqlite3.connect(db) as c:
        c.execute(
            """
            INSERT INTO personal_trades
                (user, pair, direction, entry_price, stop_loss, take_profit,
                 size_lot, signal_pattern, signal_confidence, status, pnl,
                 created_at, closed_at, is_auto, close_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("test_user", pair, "sell", 4500.0, 4510.0, 4490.0, 0.05, pattern,
             65.0, "CLOSED", pnl, closed_at, closed_at, is_auto, close_reason),
        )


# ─── /api/admin/watchdog/state ───────────────────────────────────────


@pytest.mark.asyncio
async def test_watchdog_state_empty_when_no_pause(db, monkeypatch):
    from backend import app as app_module

    monkeypatch.setattr(app_module, "ADMIN_EMAILS", ["admin@test.com"])

    out = await app_module.api_admin_watchdog_state(_ctx=_admin_ctx())
    assert out["paused_pairs_count"] == 0
    assert out["paused_pairs"] == {}
    assert out["global_rafale_pause_active"] is False
    assert out["total_sl_24h"] == 0


@pytest.mark.asyncio
async def test_watchdog_state_includes_paused_pair(db, monkeypatch):
    from backend import app as app_module

    monkeypatch.setattr(app_module, "ADMIN_EMAILS", ["admin@test.com"])

    kill_switch.set_pair_rafale_pause(
        pair="XAU/USD",
        reason="3 SL en 1h",
        min_cool_off_min=30,
        max_pause_hours=6,
        failed_pattern="range_bounce_down",
        failed_direction="sell",
    )

    out = await app_module.api_admin_watchdog_state(_ctx=_admin_ctx())
    assert out["paused_pairs_count"] == 1
    assert "XAU/USD" in out["paused_pairs"]
    info = out["paused_pairs"]["XAU/USD"]
    assert info["failed_pattern"] == "range_bounce_down"
    assert info["failed_direction"] == "sell"
    assert "min_resume_at" in info
    assert "max_resume_at" in info


@pytest.mark.asyncio
async def test_watchdog_state_includes_sl_breakdown_24h(db, monkeypatch):
    from backend import app as app_module

    monkeypatch.setattr(app_module, "ADMIN_EMAILS", ["admin@test.com"])

    now = datetime.now(timezone.utc)
    # 5 SL XAU range_bounce_down + 3 SL XAG momentum_down dans les 12h
    for i in range(5):
        _insert_sl(db, (now - timedelta(hours=i)).isoformat(),
                   pair="XAU/USD", pattern="range_bounce_down", pnl=-20.0)
    for i in range(3):
        _insert_sl(db, (now - timedelta(hours=i + 1)).isoformat(),
                   pair="XAG/USD", pattern="momentum_down", pnl=-30.0)

    out = await app_module.api_admin_watchdog_state(_ctx=_admin_ctx())
    assert out["total_sl_24h"] == 8

    breakdown = {(r["pair"], r["pattern"]): r for r in out["sl_breakdown_24h"]}
    assert breakdown[("XAU/USD", "range_bounce_down")]["count"] == 5
    assert breakdown[("XAU/USD", "range_bounce_down")]["pnl_total"] == -100.0
    assert breakdown[("XAG/USD", "momentum_down")]["count"] == 3
    assert breakdown[("XAG/USD", "momentum_down")]["pnl_total"] == -90.0


@pytest.mark.asyncio
async def test_watchdog_state_excludes_old_sl(db, monkeypatch):
    from backend import app as app_module

    monkeypatch.setattr(app_module, "ADMIN_EMAILS", ["admin@test.com"])

    old = datetime.now(timezone.utc) - timedelta(hours=30)
    for i in range(5):
        _insert_sl(db, (old - timedelta(minutes=i)).isoformat())

    out = await app_module.api_admin_watchdog_state(_ctx=_admin_ctx())
    # Hors fenêtre 24h
    assert out["total_sl_24h"] == 0


@pytest.mark.asyncio
async def test_watchdog_state_excludes_manual_trades(db, monkeypatch):
    from backend import app as app_module

    monkeypatch.setattr(app_module, "ADMIN_EMAILS", ["admin@test.com"])

    now = datetime.now(timezone.utc)
    # 5 SL manuels (is_auto=0)
    for i in range(5):
        _insert_sl(db, (now - timedelta(minutes=i)).isoformat(), is_auto=0)

    out = await app_module.api_admin_watchdog_state(_ctx=_admin_ctx())
    # Filtre is_auto=1 → 0 dans breakdown
    assert out["total_sl_24h"] == 0


@pytest.mark.asyncio
async def test_watchdog_state_includes_rejected_attempts(db, monkeypatch):
    from backend import app as app_module

    monkeypatch.setattr(app_module, "ADMIN_EMAILS", ["admin@test.com"])

    # Insert quelques rejections kill_switch_pair_paused dans les 24h
    rejection_service.record_rejection(
        pair="XAU/USD", direction="sell", confidence=66.0,
        reason_code="kill_switch_pair_paused",
        details={"signal_pattern": "range_bounce_down"},
    )
    rejection_service.record_rejection(
        pair="XAU/USD", direction="sell", confidence=66.0,
        reason_code="kill_switch_pair_paused",
        details={"signal_pattern": "range_bounce_down"},
    )
    rejection_service.record_rejection(
        pair="XAG/USD", direction="sell", confidence=66.0,
        reason_code="kill_switch_pair_paused",
        details={"signal_pattern": "momentum_down"},
    )

    out = await app_module.api_admin_watchdog_state(_ctx=_admin_ctx())
    attempts = {(r["pair"], r["pattern"]): r for r in out["rejected_attempts_24h"]}
    assert attempts[("XAU/USD", "range_bounce_down")]["count"] == 2
    assert attempts[("XAG/USD", "momentum_down")]["count"] == 1


# ─── /api/admin/watchdog/unpause ─────────────────────────────────────


@pytest.mark.asyncio
async def test_unpause_specific_pair(db, monkeypatch):
    from backend import app as app_module

    monkeypatch.setattr(app_module, "ADMIN_EMAILS", ["admin@test.com"])

    kill_switch.set_pair_rafale_pause(
        pair="XAU/USD", reason="test", min_cool_off_min=30, max_pause_hours=2,
        failed_pattern="p", failed_direction="sell",
    )
    assert kill_switch.is_pair_rafale_paused("XAU/USD")[0] is True

    out = await app_module.api_admin_watchdog_unpause(
        body={"pair": "XAU/USD"}, _ctx=_admin_ctx(),
    )
    assert out["ok"] is True
    assert "XAU/USD" in out["cleared"]["pairs"]
    assert kill_switch.is_pair_rafale_paused("XAU/USD")[0] is False


@pytest.mark.asyncio
async def test_unpause_global(db, monkeypatch):
    from backend import app as app_module

    monkeypatch.setattr(app_module, "ADMIN_EMAILS", ["admin@test.com"])

    kill_switch.set_global_rafale_pause("test global", duration_min=120)
    assert kill_switch.is_global_rafale_paused()[0] is True

    out = await app_module.api_admin_watchdog_unpause(
        body={"global": True}, _ctx=_admin_ctx(),
    )
    assert out["ok"] is True
    assert out["cleared"]["global"] is True
    assert kill_switch.is_global_rafale_paused()[0] is False


@pytest.mark.asyncio
async def test_unpause_all_clears_global_and_pairs(db, monkeypatch):
    from backend import app as app_module

    monkeypatch.setattr(app_module, "ADMIN_EMAILS", ["admin@test.com"])

    kill_switch.set_pair_rafale_pause(
        pair="XAU/USD", reason="r1", min_cool_off_min=30, max_pause_hours=2,
        failed_pattern="p", failed_direction="sell",
    )
    kill_switch.set_pair_rafale_pause(
        pair="XAG/USD", reason="r2", min_cool_off_min=30, max_pause_hours=2,
        failed_pattern="p", failed_direction="sell",
    )
    kill_switch.set_global_rafale_pause("global test", duration_min=120)

    out = await app_module.api_admin_watchdog_unpause(
        body={"all": True}, _ctx=_admin_ctx(),
    )
    assert out["ok"] is True
    assert out["cleared"]["global"] is True
    assert "XAU/USD" in out["cleared"]["pairs"]
    assert "XAG/USD" in out["cleared"]["pairs"]
    assert kill_switch.is_pair_rafale_paused("XAU/USD")[0] is False
    assert kill_switch.is_pair_rafale_paused("XAG/USD")[0] is False
    assert kill_switch.is_global_rafale_paused()[0] is False


@pytest.mark.asyncio
async def test_unpause_unknown_pair_returns_404(db, monkeypatch):
    from backend import app as app_module

    monkeypatch.setattr(app_module, "ADMIN_EMAILS", ["admin@test.com"])

    with pytest.raises(HTTPException) as exc:
        await app_module.api_admin_watchdog_unpause(
            body={"pair": "INEXISTANT/USD"}, _ctx=_admin_ctx(),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_unpause_empty_body_returns_400(db, monkeypatch):
    from backend import app as app_module

    monkeypatch.setattr(app_module, "ADMIN_EMAILS", ["admin@test.com"])

    with pytest.raises(HTTPException) as exc:
        await app_module.api_admin_watchdog_unpause(
            body={}, _ctx=_admin_ctx(),
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_unpause_combined_pair_and_global(db, monkeypatch):
    """Body avec pair + global → les 2 sont clearés."""
    from backend import app as app_module

    monkeypatch.setattr(app_module, "ADMIN_EMAILS", ["admin@test.com"])

    kill_switch.set_pair_rafale_pause(
        pair="XAU/USD", reason="test", min_cool_off_min=30, max_pause_hours=2,
        failed_pattern="p", failed_direction="sell",
    )
    kill_switch.set_global_rafale_pause("global test", duration_min=120)

    out = await app_module.api_admin_watchdog_unpause(
        body={"pair": "XAU/USD", "global": True}, _ctx=_admin_ctx(),
    )
    assert "XAU/USD" in out["cleared"]["pairs"]
    assert out["cleared"]["global"] is True
