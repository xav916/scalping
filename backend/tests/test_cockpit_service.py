"""Smoke tests for the cockpit aggregator."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from backend.services import cockpit_service


class _FakeTick:
    def __init__(self, price: float):
        self.price = price


@pytest.mark.asyncio
async def test_build_cockpit_empty_state():
    """Cockpit ne doit pas planter même sans trade ni overview ni bridge."""
    with (
        patch.object(cockpit_service.trade_log_service, "list_trades", return_value=[]),
        patch.object(
            cockpit_service.trade_log_service,
            "get_daily_status",
            return_value={
                "date": "2026-04-21",
                "n_trades_today": 0,
                "n_open": 0,
                "n_closed_today": 0,
                "pnl_today": 0.0,
                "pnl_pct": 0.0,
                "silent_mode": False,
                "loss_alert": False,
                "daily_loss_limit_pct": 3.0,
                "capital": 100000,
            },
        ),
        patch.object(cockpit_service, "get_latest_overview", return_value=None),
        patch.object(cockpit_service, "get_last_cycle_at", return_value=None),
        patch(
            "backend.services.cockpit_service.mt5_bridge_health_check",
            return_value={"configured": False},
        ),
        patch.object(cockpit_service, "_macro_snapshot", return_value=None),
    ):
        snap = await cockpit_service.build_cockpit(user="test")

    assert snap["active_trades"]["count"] == 0
    assert snap["active_trades"]["items"] == []
    assert snap["pending_setups"]["count"] == 0
    assert snap["alerts"] == []
    assert snap["system_health"]["bridge"]["configured"] is False


@pytest.mark.asyncio
async def test_build_cockpit_enriches_open_trade_with_pnl():
    """Un trade OPEN doit être enrichi avec PnL unrealized + distance SL."""
    open_trade = {
        "id": 42,
        "pair": "EUR/USD",
        "direction": "buy",
        "entry_price": 1.1000,
        "stop_loss": 1.0950,
        "take_profit": 1.1100,
        "size_lot": 0.10,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_auto": 1,
        "mt5_ticket": 123456,
    }

    with (
        patch.object(
            cockpit_service.trade_log_service, "list_trades", return_value=[open_trade]
        ),
        patch.object(
            cockpit_service.trade_log_service,
            "get_daily_status",
            return_value={
                "date": "2026-04-21",
                "n_trades_today": 1,
                "n_open": 1,
                "n_closed_today": 0,
                "pnl_today": 0.0,
                "pnl_pct": 0.0,
                "silent_mode": False,
                "loss_alert": False,
                "daily_loss_limit_pct": 3.0,
                "capital": 100000,
            },
        ),
        patch.object(cockpit_service, "get_latest_overview", return_value=None),
        patch.object(cockpit_service, "get_last_cycle_at", return_value=None),
        patch(
            "backend.services.cockpit_service.mt5_bridge_health_check",
            return_value={"configured": False},
        ),
        patch.object(cockpit_service, "_macro_snapshot", return_value=None),
        # Prix actuel : 1.1050 → long gagnant de 50 pips.
        patch.object(
            cockpit_service, "get_latest_ticks", return_value={"EUR/USD": _FakeTick(1.1050)}
        ),
    ):
        snap = await cockpit_service.build_cockpit(user="test")

    assert snap["active_trades"]["count"] == 1
    item = snap["active_trades"]["items"][0]
    assert item["pair"] == "EUR/USD"
    assert item["current_price"] == 1.1050
    # (1.1050 - 1.1000) * 100000 * 0.10 = 50.0
    assert item["pnl_unrealized"] == 50.0
    assert item["pnl_pips"] == 50.0
    assert item["near_sl"] is False
    assert item["is_auto"] is True


@pytest.mark.asyncio
async def test_build_cockpit_flags_near_sl_alert():
    """Un trade proche du SL doit générer une alerte warning."""
    open_trade = {
        "id": 1,
        "pair": "EUR/USD",
        "direction": "buy",
        "entry_price": 1.1000,
        "stop_loss": 1.0900,
        "take_profit": 1.1200,
        "size_lot": 0.05,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_auto": 0,
    }

    with (
        patch.object(
            cockpit_service.trade_log_service, "list_trades", return_value=[open_trade]
        ),
        patch.object(
            cockpit_service.trade_log_service,
            "get_daily_status",
            return_value={
                "date": "2026-04-21",
                "n_trades_today": 1,
                "n_open": 1,
                "n_closed_today": 0,
                "pnl_today": 0.0,
                "pnl_pct": 0.0,
                "silent_mode": False,
                "loss_alert": False,
                "daily_loss_limit_pct": 3.0,
                "capital": 100000,
            },
        ),
        patch.object(cockpit_service, "get_latest_overview", return_value=None),
        patch.object(cockpit_service, "get_last_cycle_at", return_value=None),
        patch(
            "backend.services.cockpit_service.mt5_bridge_health_check",
            return_value={"configured": False},
        ),
        patch.object(cockpit_service, "_macro_snapshot", return_value=None),
        # Prix 1.0920 : il reste 20 / 100 = 20% de la distance entry→SL.
        patch.object(
            cockpit_service, "get_latest_ticks", return_value={"EUR/USD": _FakeTick(1.0920)}
        ),
    ):
        snap = await cockpit_service.build_cockpit(user="test")

    item = snap["active_trades"]["items"][0]
    assert item["near_sl"] is True
    assert any(a["code"] == "near_sl" for a in snap["alerts"])


def test_compute_unrealized_pnl_xau_uses_100_units_per_lot():
    """XAU/USD : 1 lot = 100 onces, pas 100k unités comme le forex."""
    trade = {"pair": "XAU/USD", "direction": "sell", "entry_price": 4800, "size_lot": 0.10}
    # Short XAU, prix monte à 4810 → perte = (4800-4810) * 100 * 0.1 = -100
    pnl = cockpit_service._compute_unrealized_pnl(trade, 4810)
    assert pnl == -100.0
