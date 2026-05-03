"""Tests des alertes Telegram sur rafales de rejections."""
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from backend.services import rejection_alerts, rejection_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_file = tmp_path / "trades.db"
    sqlite3.connect(db_file).close()
    monkeypatch.setattr(rejection_service, "_db_path", lambda: str(db_file))
    # rejection_alerts a fait `from X import _db_path` au moment de son
    # propre import → il a SA copie de la référence. Il faut aussi la
    # patcher.
    monkeypatch.setattr(rejection_alerts, "_db_path", lambda: str(db_file))
    yield str(db_file)
    # Reset state inter-test
    rejection_alerts._last_alert_at.clear()


def _insert_rejection(db, created_at, reason_code, pair="EUR/USD"):
    rejection_service._ensure_schema()
    with sqlite3.connect(db) as c:
        c.execute(
            """
            INSERT INTO signal_rejections (created_at, pair, reason_code)
            VALUES (?, ?, ?)
            """,
            (created_at, pair, reason_code),
        )


@pytest.mark.asyncio
async def test_no_alert_if_below_threshold(db):
    now = datetime.now(timezone.utc)
    for i in range(5):  # < 10
        _insert_rejection(db, (now - timedelta(minutes=i)).isoformat(), "bridge_max_positions")

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await rejection_alerts.check_and_alert()

    assert mock_send.call_count == 0
    assert out["alerts_sent"] == []


@pytest.mark.asyncio
async def test_alert_sent_when_threshold_crossed(db):
    now = datetime.now(timezone.utc)
    for i in range(15):  # > 10
        _insert_rejection(db, (now - timedelta(minutes=i)).isoformat(), "bridge_max_positions")

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await rejection_alerts.check_and_alert()

    assert mock_send.call_count == 1
    assert "bridge_max_positions" in out["alerts_sent"]
    # Message contient le count et le label FR
    msg = mock_send.call_args[0][0]
    assert "15" in msg
    assert "Cap positions bridge" in msg


@pytest.mark.asyncio
async def test_cooldown_suppresses_duplicate_alerts(db):
    now = datetime.now(timezone.utc)
    for i in range(15):
        _insert_rejection(db, (now - timedelta(minutes=i)).isoformat(), "bridge_max_positions")

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            # 1er appel : envoie
            await rejection_alerts.check_and_alert()
            # 2ᵉ appel immédiat : devrait être coupé par le cooldown 60 min
            out2 = await rejection_alerts.check_and_alert()

    assert mock_send.call_count == 1
    assert out2["alerts_suppressed_cooldown"] == ["bridge_max_positions"]


@pytest.mark.asyncio
async def test_multiple_reason_codes_independently_alerted(db):
    now = datetime.now(timezone.utc)
    for i in range(15):
        _insert_rejection(db, (now - timedelta(minutes=i)).isoformat(), "bridge_max_positions")
    for i in range(12):
        _insert_rejection(db, (now - timedelta(minutes=i)).isoformat(), "sl_too_close", pair="XAU/USD")

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await rejection_alerts.check_and_alert()

    assert mock_send.call_count == 2
    assert set(out["alerts_sent"]) == {"bridge_max_positions", "sl_too_close"}


@pytest.mark.asyncio
async def test_market_closed_does_not_trigger_telegram(db):
    """`market_closed` est un état calendaire normal (week-end, daily break),
    pas une situation actionnable. Pas de Telegram même au-delà du seuil.
    Reste loggé pour la card RejectionsCard.
    """
    now = datetime.now(timezone.utc)
    for i in range(15):  # > seuil 10
        _insert_rejection(
            db, (now - timedelta(minutes=i)).isoformat(), "market_closed",
            pair="XAU/USD",
        )

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await rejection_alerts.check_and_alert()

    assert mock_send.call_count == 0
    assert out["alerts_sent"] == []
    # Le compte est bien remonté pour traçabilité (la card RejectionsCard
    # le rendra), mais classé en "skipped"
    assert out["counts"].get("market_closed") == 15
    assert "market_closed" in out["alerts_skipped_silent"]


@pytest.mark.asyncio
async def test_telegram_not_configured_is_no_op(db):
    now = datetime.now(timezone.utc)
    for i in range(15):
        _insert_rejection(db, (now - timedelta(minutes=i)).isoformat(), "bridge_max_positions")

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=False):
            out = await rejection_alerts.check_and_alert()

    assert mock_send.call_count == 0
    # alerts_sent vide aussi puisque send_text n'a pas été appelé
    assert out["alerts_sent"] == []
