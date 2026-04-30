"""Tests des alertes Telegram + circuit breaker per-pair sur rafales SL."""
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from backend.services import kill_switch, stop_loss_alerts, trade_log_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    """DB SQLite isolée + kill_switch state isolé + auto-pause OFF par défaut."""
    db_file = tmp_path / "trades.db"
    sqlite3.connect(db_file).close()
    monkeypatch.setattr(trade_log_service, "_DB_PATH", db_file)
    trade_log_service._init_schema()

    ks_file = tmp_path / "kill_switch.json"
    monkeypatch.setattr(kill_switch, "_STATE_PATH", ks_file)

    from config import settings as _cfg
    monkeypatch.setattr(_cfg, "RAFALE_AUTO_PAUSE_ENABLED", False)
    monkeypatch.setattr(_cfg, "RAFALE_PAUSE_DURATION_MIN", 120)

    yield str(db_file)
    stop_loss_alerts._last_alert_at.clear()


@pytest.fixture
def db_with_auto_pause(db, monkeypatch):
    """Variante avec RAFALE_AUTO_PAUSE_ENABLED=True."""
    from config import settings as _cfg
    monkeypatch.setattr(_cfg, "RAFALE_AUTO_PAUSE_ENABLED", True)
    monkeypatch.setattr(_cfg, "RAFALE_PAUSE_DURATION_MIN", 120)
    return db


def _insert_sl(
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
                "test_user", pair, direction, 4500.0, 4510.0, 4490.0,
                0.05, pattern, 65.0, status, pnl, closed_at, closed_at,
                is_auto, close_reason,
            ),
        )


# ─── Détection seuils ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_alert_below_pair_threshold(db):
    now = datetime.now(timezone.utc)
    for i in range(2):  # 2 < PAIR_THRESHOLD=3
        _insert_sl(db, (now - timedelta(minutes=i)).isoformat())

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await stop_loss_alerts.check_and_alert()

    assert mock_send.call_count == 0
    assert out["alerts_sent"] == []
    assert out["pairs_paused"] == []


@pytest.mark.asyncio
async def test_pair_alert_when_pair_threshold_crossed(db):
    """3 SL même pair → alerte par-pair (pas global, pas pattern car ils ont
    aussi le même pattern par défaut)."""
    now = datetime.now(timezone.utc)
    for i in range(3):
        _insert_sl(db, (now - timedelta(minutes=i)).isoformat(), pair="XAU/USD")

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await stop_loss_alerts.check_and_alert()

    # Devrait avoir 2 alertes : pair:XAU/USD ET pattern:range_bounce_down (default pattern)
    assert "pair:XAU/USD" in out["alerts_sent"]
    assert "pattern:range_bounce_down" in out["alerts_sent"]
    assert "global" not in out["alerts_sent"]


@pytest.mark.asyncio
async def test_pair_pause_isolated_other_pairs_continue(db_with_auto_pause):
    """Pause sur XAU n'affecte pas XAG/ETH."""
    db = db_with_auto_pause
    now = datetime.now(timezone.utc)
    # 3 SL XAU → trigger pair pause XAU
    for i in range(3):
        _insert_sl(db, (now - timedelta(minutes=i)).isoformat(), pair="XAU/USD")
    # Aucune SL sur XAG ou ETH

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()):
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await stop_loss_alerts.check_and_alert()

    # XAU paused
    assert "XAU/USD" in out["pairs_paused"]
    paused_xau, _ = kill_switch.is_pair_rafale_paused("XAU/USD")
    assert paused_xau is True

    # XAG et ETH NOT paused
    paused_xag, _ = kill_switch.is_pair_rafale_paused("XAG/USD")
    paused_eth, _ = kill_switch.is_pair_rafale_paused("ETH/USD")
    assert paused_xag is False
    assert paused_eth is False

    # is_active(XAU) = True (pair pause), is_active(XAG) = False
    assert kill_switch.is_active(pair="XAU/USD") is True
    assert kill_switch.is_active(pair="XAG/USD") is False
    # is_active() sans pair = False (les pair-pauses ne coupent pas globalement)
    assert kill_switch.is_active() is False


@pytest.mark.asyncio
async def test_global_pause_when_global_threshold_crossed(db_with_auto_pause):
    """≥ 10 SL toutes pairs confondues → pause GLOBALE."""
    db = db_with_auto_pause
    now = datetime.now(timezone.utc)
    # 10 SL répartis : 3 XAU + 3 XAG + 2 ETH + 2 WTI = 10 total
    for i in range(3):
        _insert_sl(db, (now - timedelta(minutes=i)).isoformat(), pair="XAU/USD",
                   pattern=f"p_xau_{i}")
    for i in range(3):
        _insert_sl(db, (now - timedelta(minutes=10 + i)).isoformat(), pair="XAG/USD",
                   pattern=f"p_xag_{i}")
    for i in range(2):
        _insert_sl(db, (now - timedelta(minutes=20 + i)).isoformat(), pair="ETH/USD",
                   pattern=f"p_eth_{i}")
    for i in range(2):
        _insert_sl(db, (now - timedelta(minutes=30 + i)).isoformat(), pair="WTI/USD",
                   pattern=f"p_wti_{i}")

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()):
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await stop_loss_alerts.check_and_alert()

    # Global pause set (filet de sécu)
    assert out["global_pause_set"] is True
    global_active, _ = kill_switch.is_global_rafale_paused()
    assert global_active is True

    # is_active() = True globalement
    assert kill_switch.is_active() is True
    # is_active(any pair) = True aussi (à cause de global)
    assert kill_switch.is_active(pair="ETH/USD") is True


@pytest.mark.asyncio
async def test_pattern_alert_no_pause(db_with_auto_pause):
    """Pattern threshold dépassé → alerte info seule, pas de pause."""
    db = db_with_auto_pause
    now = datetime.now(timezone.utc)
    # 3 SL même pattern mais sur 3 pairs différentes (donc pair_threshold pas franchi)
    _insert_sl(db, (now - timedelta(minutes=1)).isoformat(),
               pair="XAU/USD", pattern="momentum_up")
    _insert_sl(db, (now - timedelta(minutes=2)).isoformat(),
               pair="XAG/USD", pattern="momentum_up")
    _insert_sl(db, (now - timedelta(minutes=3)).isoformat(),
               pair="ETH/USD", pattern="momentum_up")

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await stop_loss_alerts.check_and_alert()

    assert "pattern:momentum_up" in out["alerts_sent"]
    assert out["pairs_paused"] == []
    assert out["global_pause_set"] is False


# ─── Cooldowns ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cooldown_per_pair(db):
    now = datetime.now(timezone.utc)
    for i in range(3):
        _insert_sl(db, (now - timedelta(minutes=i)).isoformat(), pair="XAU/USD")

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            await stop_loss_alerts.check_and_alert()
            out2 = await stop_loss_alerts.check_and_alert()

    # 1er appel : alertes envoyées (pair + pattern). 2ᵉ : tout en cooldown
    assert "pair:XAU/USD" in out2["alerts_suppressed_cooldown"]


# ─── Filtres ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_manual_trades_ignored(db):
    now = datetime.now(timezone.utc)
    for i in range(10):
        _insert_sl(db, (now - timedelta(minutes=i)).isoformat(), is_auto=0)

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await stop_loss_alerts.check_and_alert()

    assert mock_send.call_count == 0
    assert out["total_sl_count"] == 0


@pytest.mark.asyncio
async def test_old_trades_outside_window_ignored(db):
    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=2)
    for i in range(10):
        _insert_sl(db, (old - timedelta(minutes=i)).isoformat())

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await stop_loss_alerts.check_and_alert()

    assert mock_send.call_count == 0
    assert out["total_sl_count"] == 0


@pytest.mark.asyncio
async def test_non_sl_close_reason_ignored(db):
    now = datetime.now(timezone.utc)
    for i in range(10):
        _insert_sl(db, (now - timedelta(minutes=i)).isoformat(), close_reason="TP1")

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await stop_loss_alerts.check_and_alert()

    assert mock_send.call_count == 0
    assert out["total_sl_count"] == 0


# ─── Auto-pause / resume per-pair ────────────────────────────────────


@pytest.mark.asyncio
async def test_pair_pause_idempotent_during_active_window(db_with_auto_pause):
    """Si la pair est déjà paused, le timer ne se reset pas."""
    db = db_with_auto_pause
    now = datetime.now(timezone.utc)
    for i in range(3):
        _insert_sl(db, (now - timedelta(minutes=i)).isoformat(), pair="XAU/USD")

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()):
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            await stop_loss_alerts.check_and_alert()
            _, info1 = kill_switch.is_pair_rafale_paused("XAU/USD")
            expires1 = info1["expires_at"]

            # 2ᵉ check immédiat
            await stop_loss_alerts.check_and_alert()
            _, info2 = kill_switch.is_pair_rafale_paused("XAU/USD")
            expires2 = info2["expires_at"]

    assert expires1 == expires2  # timer pas reset


@pytest.mark.asyncio
async def test_pair_auto_resume_when_expired(db_with_auto_pause):
    """Pause expirée → auto-clear + Telegram resume."""
    db = db_with_auto_pause
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    very_past = datetime.now(timezone.utc) - timedelta(hours=3)
    state = kill_switch._load_state()
    state["rafale_paused_pairs"]["XAU/USD"] = {
        "active": True,
        "triggered_at": very_past.isoformat(),
        "expires_at": past.isoformat(),
        "reason": "test pause",
        "trigger_type": "pair:XAU/USD",
    }
    kill_switch._save_state(state)

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()) as mock_send:
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await stop_loss_alerts.check_and_alert()

    assert "XAU/USD" in out["pairs_resumed"]
    paused, _ = kill_switch.is_pair_rafale_paused("XAU/USD")
    assert paused is False
    msg = mock_send.call_args_list[0][0][0]
    assert "Auto-resume" in msg
    assert "XAU/USD" in msg


@pytest.mark.asyncio
async def test_multiple_pairs_resume_independently(db_with_auto_pause):
    """Plusieurs pairs paused, certaines expirées → notifications indépendantes."""
    db = db_with_auto_pause
    now = datetime.now(timezone.utc)

    # XAU expirée (passé), XAG encore active (futur)
    state = kill_switch._load_state()
    state["rafale_paused_pairs"]["XAU/USD"] = {
        "active": True,
        "triggered_at": (now - timedelta(hours=3)).isoformat(),
        "expires_at": (now - timedelta(minutes=10)).isoformat(),
        "reason": "expirée",
        "trigger_type": "pair:XAU/USD",
    }
    state["rafale_paused_pairs"]["XAG/USD"] = {
        "active": True,
        "triggered_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "reason": "active",
        "trigger_type": "pair:XAG/USD",
    }
    kill_switch._save_state(state)

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()):
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await stop_loss_alerts.check_and_alert()

    # XAU resumed, XAG still active
    assert "XAU/USD" in out["pairs_resumed"]
    assert "XAG/USD" not in out["pairs_resumed"]
    paused_xau, _ = kill_switch.is_pair_rafale_paused("XAU/USD")
    paused_xag, _ = kill_switch.is_pair_rafale_paused("XAG/USD")
    assert paused_xau is False
    assert paused_xag is True


@pytest.mark.asyncio
async def test_auto_pause_disabled_means_no_pause(db):
    """RAFALE_AUTO_PAUSE_ENABLED=false (default fixture) → pas de pause."""
    now = datetime.now(timezone.utc)
    for i in range(3):
        _insert_sl(db, (now - timedelta(minutes=i)).isoformat(), pair="XAU/USD")

    with patch("backend.services.telegram_service.send_text", new=AsyncMock()):
        with patch("backend.services.telegram_service.is_configured", return_value=True):
            out = await stop_loss_alerts.check_and_alert()

    # Alerte envoyée mais pas de pause
    assert out["pairs_paused"] == []
    paused, _ = kill_switch.is_pair_rafale_paused("XAU/USD")
    assert paused is False


# ─── kill_switch.is_active(pair=...) sémantique ──────────────────────


def test_is_active_pair_isolated(db):
    """is_active(pair=X) ne déclenche pas si une AUTRE pair est paused."""
    kill_switch.set_pair_rafale_pause("XAU/USD", "test", 60)
    assert kill_switch.is_active(pair="XAU/USD") is True
    assert kill_switch.is_active(pair="XAG/USD") is False
    assert kill_switch.is_active() is False  # no pair = global only


def test_is_active_global_blocks_all_pairs(db):
    """Global rafale pause bloque toutes les pairs."""
    kill_switch.set_global_rafale_pause("test global", 60)
    assert kill_switch.is_active() is True
    assert kill_switch.is_active(pair="XAU/USD") is True
    assert kill_switch.is_active(pair="XAG/USD") is True


def test_is_active_manual_blocks_all(db):
    """Manuel bloque tout (comportement existant)."""
    kill_switch.set_manual(enabled=True, reason="weekend")
    assert kill_switch.is_active() is True
    assert kill_switch.is_active(pair="XAU/USD") is True
