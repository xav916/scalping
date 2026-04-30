"""Tests des alertes Telegram sur rafales de stops loss."""
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from backend.services import stop_loss_alerts, trade_log_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_file = tmp_path / "trades.db"
    sqlite3.connect(db_file).close()
    # trade_log_service expose _DB_PATH (utilisé par stop_loss_alerts._db_path)
    monkeypatch.setattr(trade_log_service, "_DB_PATH", db_file)
    # init schema (fonction privée s'appelle _init_schema dans ce module)
    trade_log_service._init_schema()
    yield str(db_file)
    # Reset state inter-test
    stop_loss_alerts._last_alert_at.clear()


def _insert_sl_trade(
    db,
    closed_at,
    pair="XAU/USD",
    direction="sell",
    pattern="range_bounce_down",
    pnl=-15.0,
    is_auto=1,
    close_reason="SL",
    status="CLOSED",
):
    with sqlite3.connect(db) as c:
        c.execute(
            """
            INSERT INTO personal_trades
                (user, pair, direction, entry_price, stop_loss, take_profit,
                 size_lot, signal_pattern, signal_confidence, status, pnl,
                 created_at, closed_at, is_auto, close_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "test_user",
                pair,
                direction,
                4500.0,
                4510.0,
                4490.0,
                0.05,
                pattern,
                65.0,
                status,
                pnl,
                closed_at,
                closed_at,
                is_auto,
                close_reason,
            ),
        )


@pytest.mark.asyncio
async def test_no_alert_if_below_global_threshold(db):
    now = datetime.now(timezone.utc)
    for i in range(4):  # < 5 = GLOBAL_THRESHOLD
        _insert_sl_trade(db, (now - timedelta(minutes=i)).isoformat())

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await stop_loss_alerts.check_and_alert()

    # 4 SLs même pattern → pattern threshold (3) franchi → 1 alerte pattern
    # Mais pas global (4 < 5).
    assert "global" not in out["alerts_sent"]
    # Pattern bien remonté
    assert out["total_sl_count"] == 4


@pytest.mark.asyncio
async def test_global_alert_sent_when_threshold_crossed(db):
    now = datetime.now(timezone.utc)
    # 6 SL avec patterns diversifiés (pour ne pas franchir le pattern threshold à 3)
    patterns = ["momentum_up", "engulfing_bullish", "breakout_up",
                "momentum_down", "doji_reversal", "pin_bar_up"]
    for i, p in enumerate(patterns):
        _insert_sl_trade(
            db,
            (now - timedelta(minutes=i * 5)).isoformat(),
            pattern=p,
        )

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await stop_loss_alerts.check_and_alert()

    assert "global" in out["alerts_sent"]
    msg = mock_send.call_args_list[0][0][0]
    assert "global" in msg.lower() or "Rafale stops loss" in msg
    assert "6" in msg


@pytest.mark.asyncio
async def test_pattern_alert_sent_when_threshold_crossed(db):
    now = datetime.now(timezone.utc)
    # 3 SL même pattern → franchit PATTERN_THRESHOLD mais pas GLOBAL_THRESHOLD
    for i in range(3):
        _insert_sl_trade(
            db,
            (now - timedelta(minutes=i * 5)).isoformat(),
            pattern="range_bounce_down",
        )

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await stop_loss_alerts.check_and_alert()

    assert "pattern:range_bounce_down" in out["alerts_sent"]
    assert "global" not in out["alerts_sent"]
    msg = mock_send.call_args_list[0][0][0]
    assert "range_bounce_down" in msg


@pytest.mark.asyncio
async def test_both_alerts_sent_when_both_thresholds_crossed(db):
    now = datetime.now(timezone.utc)
    # 6 SL même pattern → franchit les 2 seuils
    for i in range(6):
        _insert_sl_trade(
            db,
            (now - timedelta(minutes=i * 2)).isoformat(),
            pattern="range_bounce_down",
        )

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await stop_loss_alerts.check_and_alert()

    assert "global" in out["alerts_sent"]
    assert "pattern:range_bounce_down" in out["alerts_sent"]
    assert mock_send.call_count == 2


@pytest.mark.asyncio
async def test_cooldown_suppresses_duplicate_global_alerts(db):
    now = datetime.now(timezone.utc)
    patterns = ["momentum_up", "engulfing_bullish", "breakout_up",
                "momentum_down", "doji_reversal", "pin_bar_up"]
    for i, p in enumerate(patterns):
        _insert_sl_trade(
            db,
            (now - timedelta(minutes=i * 5)).isoformat(),
            pattern=p,
        )

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            await stop_loss_alerts.check_and_alert()
            out2 = await stop_loss_alerts.check_and_alert()

    # 1er appel → envoie. 2ᵉ appel cooldown 30 min → suppress.
    assert mock_send.call_count == 1
    assert "global" in out2["alerts_suppressed_cooldown"]


@pytest.mark.asyncio
async def test_manual_trades_ignored(db):
    now = datetime.now(timezone.utc)
    # 10 SL mais tous en manual (is_auto=0) → pas d'alerte
    for i in range(10):
        _insert_sl_trade(
            db,
            (now - timedelta(minutes=i)).isoformat(),
            is_auto=0,
        )

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await stop_loss_alerts.check_and_alert()

    assert mock_send.call_count == 0
    assert out["total_sl_count"] == 0


@pytest.mark.asyncio
async def test_old_trades_outside_window_ignored(db):
    now = datetime.now(timezone.utc)
    # 10 SL d'il y a > 1h → hors fenêtre WINDOW_HOURS=1
    old = now - timedelta(hours=2)
    for i in range(10):
        _insert_sl_trade(db, (old - timedelta(minutes=i)).isoformat())

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await stop_loss_alerts.check_and_alert()

    assert mock_send.call_count == 0
    assert out["total_sl_count"] == 0


@pytest.mark.asyncio
async def test_non_sl_close_reason_ignored(db):
    now = datetime.now(timezone.utc)
    # 10 trades fermés mais en TP / MANUAL / TIMEOUT — pas SL
    for i in range(10):
        _insert_sl_trade(
            db,
            (now - timedelta(minutes=i)).isoformat(),
            close_reason="TP1",
        )

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await stop_loss_alerts.check_and_alert()

    assert mock_send.call_count == 0
    assert out["total_sl_count"] == 0


@pytest.mark.asyncio
async def test_telegram_not_configured_skips_send(db):
    now = datetime.now(timezone.utc)
    for i in range(6):
        _insert_sl_trade(db, (now - timedelta(minutes=i)).isoformat())

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=False):
            out = await stop_loss_alerts.check_and_alert()

    assert mock_send.call_count == 0
    # Mais alerts_sent reste vide car le send a été skip
    assert out["alerts_sent"] == []


@pytest.mark.asyncio
async def test_message_contains_breakdown(db):
    now = datetime.now(timezone.utc)
    # 4 SL pattern A sur XAU + 2 SL pattern B sur XAG
    for i in range(4):
        _insert_sl_trade(
            db,
            (now - timedelta(minutes=i * 2)).isoformat(),
            pair="XAU/USD",
            pattern="range_bounce_down",
            pnl=-15.0,
        )
    for i in range(2):
        _insert_sl_trade(
            db,
            (now - timedelta(minutes=15 + i * 2)).isoformat(),
            pair="XAG/USD",
            pattern="momentum_down",
            pnl=-25.0,
        )

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            await stop_loss_alerts.check_and_alert()

    # Récupérer le message global (le 1er envoyé)
    sent_msgs = [call[0][0] for call in mock_send.call_args_list]
    global_msg = next((m for m in sent_msgs if "global" in m.lower() or "Rafale" in m), None)
    assert global_msg is not None
    # Total PnL = 4×(-15) + 2×(-25) = -110 €
    assert "-110" in global_msg
    assert "XAU/USD" in global_msg
    assert "range_bounce_down" in global_msg
