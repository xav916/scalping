"""Tests des alertes Telegram sur rafales de stops loss."""
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from backend.services import kill_switch, stop_loss_alerts, trade_log_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Fixture isole DB + kill_switch state per test.

    Sans isolation kill_switch, les tests qui déclenchent un global rafale
    écrivent dans le vrai ``kill_switch.json`` du repo (pollution + non
    déterminisme). On redirige _STATE_PATH vers tmp_path.
    """
    db_file = tmp_path / "trades.db"
    sqlite3.connect(db_file).close()
    monkeypatch.setattr(trade_log_service, "_DB_PATH", db_file)
    trade_log_service._init_schema()

    # Isolation kill_switch — chaque test a son propre fichier state.
    ks_file = tmp_path / "kill_switch.json"
    monkeypatch.setattr(kill_switch, "_STATE_PATH", ks_file)

    # Auto-pause OFF par défaut dans les tests pour ne pas perturber
    # ceux qui ne testent pas le circuit breaker. Tests dédiés
    # ré-activent explicitement via monkeypatch sur l'attribut.
    # Note : config.settings est lu à l'import → on patch l'attribut
    # plutôt que la variable d'env.
    from config import settings as _cfg
    monkeypatch.setattr(_cfg, "RAFALE_AUTO_PAUSE_ENABLED", False)
    monkeypatch.setattr(_cfg, "RAFALE_PAUSE_DURATION_MIN", 120)

    yield str(db_file)
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


@pytest.fixture
def db_with_auto_pause(db, monkeypatch):
    """Variante de la fixture db avec RAFALE_AUTO_PAUSE_ENABLED=True."""
    from config import settings as _cfg
    monkeypatch.setattr(_cfg, "RAFALE_AUTO_PAUSE_ENABLED", True)
    monkeypatch.setattr(_cfg, "RAFALE_PAUSE_DURATION_MIN", 120)
    return db


@pytest.mark.asyncio
async def test_auto_pause_triggered_on_global_rafale(db_with_auto_pause):
    db = db_with_auto_pause
    now = datetime.now(timezone.utc)
    patterns = ["momentum_up", "engulfing_bullish", "breakout_up",
                "momentum_down", "doji_reversal", "pin_bar_up"]
    for i, p in enumerate(patterns):
        _insert_sl_trade(db, (now - timedelta(minutes=i * 5)).isoformat(), pattern=p)

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await stop_loss_alerts.check_and_alert()

    # Auto-pause set
    assert out["auto_pause_set"] is True
    # Kill switch effectivement actif
    paused, info = kill_switch.is_rafale_paused()
    assert paused is True
    assert info is not None
    assert info["trigger_type"] == "global"
    assert "6 SL" in info["reason"]
    # Message Telegram contient mention auto-pause
    msg = mock_send.call_args_list[0][0][0]
    assert "AUTO-PAUSE" in msg


@pytest.mark.asyncio
async def test_auto_pause_disabled_doesnt_trigger(db):
    """Avec RAFALE_AUTO_PAUSE_ENABLED=false (default fixture), pas de pause."""
    now = datetime.now(timezone.utc)
    patterns = ["momentum_up", "engulfing_bullish", "breakout_up",
                "momentum_down", "doji_reversal", "pin_bar_up"]
    for i, p in enumerate(patterns):
        _insert_sl_trade(db, (now - timedelta(minutes=i * 5)).isoformat(), pattern=p)

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()):
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await stop_loss_alerts.check_and_alert()

    assert out["auto_pause_set"] is False
    paused, _ = kill_switch.is_rafale_paused()
    assert paused is False


@pytest.mark.asyncio
async def test_auto_pause_idempotent_during_active_window(db_with_auto_pause):
    """Si déjà paused, un 2ᵉ check ne re-set pas le timer (pour pas le rallonger indéfiniment)."""
    db = db_with_auto_pause
    now = datetime.now(timezone.utc)
    patterns = ["momentum_up", "engulfing_bullish", "breakout_up",
                "momentum_down", "doji_reversal", "pin_bar_up"]
    for i, p in enumerate(patterns):
        _insert_sl_trade(db, (now - timedelta(minutes=i * 5)).isoformat(), pattern=p)

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()):
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            await stop_loss_alerts.check_and_alert()
            paused1, info1 = kill_switch.is_rafale_paused()
            expires1 = info1["expires_at"]

            # 2ᵉ check immédiat — déjà dans cooldown alert + déjà paused
            out2 = await stop_loss_alerts.check_and_alert()
            paused2, info2 = kill_switch.is_rafale_paused()
            expires2 = info2["expires_at"]

    # Toujours paused, mais expires_at INCHANGÉ (pas reset à chaque cycle)
    assert paused1 is True and paused2 is True
    assert expires1 == expires2
    assert out2["auto_pause_set"] is False


@pytest.mark.asyncio
async def test_auto_resume_triggers_telegram_when_pause_expires(db_with_auto_pause):
    """Une pause ayant expiré dans le passé doit auto-resume + envoyer Telegram."""
    db = db_with_auto_pause
    # Set un kill switch state avec expires_at déjà dans le passé
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    very_past = datetime.now(timezone.utc) - timedelta(hours=3)
    state = kill_switch._load_state()
    state["rafale_pause"] = {
        "active": True,
        "triggered_at": very_past.isoformat(),
        "expires_at": past.isoformat(),
        "reason": "test pause",
        "trigger_type": "global",
    }
    kill_switch._save_state(state)

    # Pas de SL récents → pas de re-déclenchement
    # (sinon le test pourrait re-pauser dans la même call et masquer la transition)

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await stop_loss_alerts.check_and_alert()

    # Transition détectée
    assert out["auto_resume_notified"] is True
    # Pause clearée
    paused, _ = kill_switch.is_rafale_paused()
    assert paused is False
    # Telegram envoyé
    msg = mock_send.call_args_list[0][0][0]
    assert "Auto-resume" in msg
    assert "test pause" in msg


@pytest.mark.asyncio
async def test_no_auto_resume_if_pause_still_active(db_with_auto_pause):
    """Pause toujours dans sa fenêtre → pas de notif resume."""
    db = db_with_auto_pause
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    state = kill_switch._load_state()
    state["rafale_pause"] = {
        "active": True,
        "triggered_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": future.isoformat(),
        "reason": "test active pause",
        "trigger_type": "global",
    }
    kill_switch._save_state(state)

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()):
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await stop_loss_alerts.check_and_alert()

    assert out["auto_resume_notified"] is False
    paused, _ = kill_switch.is_rafale_paused()
    assert paused is True  # Toujours active


@pytest.mark.asyncio
async def test_pattern_rafale_does_not_trigger_auto_pause(db_with_auto_pause):
    """Une rafale par pattern envoie une alerte mais ne déclenche pas la pause."""
    db = db_with_auto_pause
    now = datetime.now(timezone.utc)
    # 3 SL même pattern (franchit pattern threshold mais pas global threshold=5)
    for i in range(3):
        _insert_sl_trade(db, (now - timedelta(minutes=i * 5)).isoformat(),
                         pattern="range_bounce_down")

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()):
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await stop_loss_alerts.check_and_alert()

    assert out["auto_pause_set"] is False
    assert "pattern:range_bounce_down" in out["alerts_sent"]
    paused, _ = kill_switch.is_rafale_paused()
    assert paused is False


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
