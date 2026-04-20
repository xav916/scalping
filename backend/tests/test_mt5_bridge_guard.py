"""Verify the MT5 bridge skips setups on unsupported asset classes."""
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from backend.services import mt5_bridge


def _mk_setup(pair: str) -> MagicMock:
    """Minimal setup stub with the attributes used by send_setup."""
    s = MagicMock()
    s.pair = pair
    s.direction = MagicMock()
    s.direction.value = "buy"
    s.entry_price = 1.0
    s.stop_loss = 0.99
    s.take_profit_1 = 1.02
    s.take_profit_2 = 1.04
    s.confidence_score = 95.0
    s.verdict_action = "TAKE"
    s.verdict_blockers = []
    s.timestamp = datetime.now(timezone.utc)
    return s


@pytest.fixture(autouse=True)
def _reset_dedup():
    """Make sure each test starts with a clean dedup cache."""
    mt5_bridge._sent_setups_today.clear()
    yield
    mt5_bridge._sent_setups_today.clear()


@pytest.mark.asyncio
async def test_crypto_skipped_when_not_in_allowed_classes():
    """BTC/USD must be short-circuited when the broker only allows forex+metal."""
    with patch.object(mt5_bridge, "MT5_BRIDGE_ALLOWED_ASSET_CLASSES", ["forex", "metal"]), \
         patch.object(mt5_bridge, "MT5_BRIDGE_ENABLED", True), \
         patch.object(mt5_bridge, "MT5_BRIDGE_URL", "http://test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_API_KEY", "test"), \
         patch("httpx.AsyncClient") as mock_client:
        await mt5_bridge.send_setup(_mk_setup("BTC/USD"))
        # Guard should have returned before creating an HTTP client
        mock_client.assert_not_called()
    # Dedup key must NOT have been registered (we skipped before that line)
    assert not mt5_bridge._sent_setups_today


@pytest.mark.asyncio
async def test_equity_index_skipped_when_not_in_allowed_classes():
    """SPX must be short-circuited when the broker only allows forex+metal."""
    with patch.object(mt5_bridge, "MT5_BRIDGE_ALLOWED_ASSET_CLASSES", ["forex", "metal"]), \
         patch.object(mt5_bridge, "MT5_BRIDGE_ENABLED", True), \
         patch.object(mt5_bridge, "MT5_BRIDGE_URL", "http://test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_API_KEY", "test"), \
         patch("httpx.AsyncClient") as mock_client:
        await mt5_bridge.send_setup(_mk_setup("SPX"))
        mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_forex_not_blocked_by_guard():
    """EUR/USD must get past the asset-class guard (and reach the HTTP layer)."""
    mock_client_ctx = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True, "mode": "paper"}

    # httpx.AsyncClient(...) returns an object usable as an async context manager.
    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return mock_client_ctx

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def _fake_post(url, json=None, headers=None):  # noqa: A002
        return mock_response

    mock_client_ctx.post = _fake_post

    with patch.object(mt5_bridge, "MT5_BRIDGE_ALLOWED_ASSET_CLASSES", ["forex", "metal"]), \
         patch.object(mt5_bridge, "MT5_BRIDGE_ENABLED", True), \
         patch.object(mt5_bridge, "MT5_BRIDGE_URL", "http://test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_API_KEY", "test"), \
         patch("backend.services.mt5_bridge.httpx.AsyncClient", _FakeClient):
        await mt5_bridge.send_setup(_mk_setup("EUR/USD"))

    # The guard did not block → dedup key was registered.
    today = date.today().isoformat()
    assert any(k[0] == today and k[1] == "EUR/USD" for k in mt5_bridge._sent_setups_today)


@pytest.mark.asyncio
async def test_crypto_allowed_when_in_allowed_classes():
    """When the broker supports crypto, BTC/USD must get past the guard."""
    mock_client_ctx = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True, "mode": "paper"}

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return mock_client_ctx

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def _fake_post(url, json=None, headers=None):  # noqa: A002
        return mock_response

    mock_client_ctx.post = _fake_post

    with patch.object(
        mt5_bridge, "MT5_BRIDGE_ALLOWED_ASSET_CLASSES", ["forex", "metal", "crypto"]
    ), patch.object(mt5_bridge, "MT5_BRIDGE_ENABLED", True), \
         patch.object(mt5_bridge, "MT5_BRIDGE_URL", "http://test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_API_KEY", "test"), \
         patch("backend.services.mt5_bridge.httpx.AsyncClient", _FakeClient):
        await mt5_bridge.send_setup(_mk_setup("BTC/USD"))

    today = date.today().isoformat()
    assert any(k[0] == today and k[1] == "BTC/USD" for k in mt5_bridge._sent_setups_today)


@pytest.mark.asyncio
async def test_skip_verdict_without_blockers_still_pushed():
    """A setup tagged SKIP purely because score < 75 must still reach the
    bridge as long as verdict_blockers is empty and score ≥ threshold."""
    setup = _mk_setup("EUR/USD")
    setup.verdict_action = "SKIP"   # e.g. base score 60 → verdict engine picks SKIP
    setup.verdict_blockers = []
    setup.confidence_score = 62.0

    mock_client_ctx = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True, "mode": "paper"}

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return mock_client_ctx

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def _fake_post(url, json=None, headers=None):  # noqa: A002
        return mock_response

    mock_client_ctx.post = _fake_post

    with patch.object(mt5_bridge, "MT5_BRIDGE_ALLOWED_ASSET_CLASSES", ["forex"]), \
         patch.object(mt5_bridge, "MT5_BRIDGE_ENABLED", True), \
         patch.object(mt5_bridge, "MT5_BRIDGE_URL", "http://test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_API_KEY", "test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_MIN_CONFIDENCE", 60), \
         patch("backend.services.mt5_bridge.httpx.AsyncClient", _FakeClient):
        await mt5_bridge.send_setup(setup)

    today = date.today().isoformat()
    assert any(k[0] == today and k[1] == "EUR/USD" for k in mt5_bridge._sent_setups_today)


@pytest.mark.asyncio
async def test_setup_with_hard_blockers_is_rejected():
    """A setup carrying verdict_blockers (market closed, macro veto…) must
    be rejected even if its confidence score is high."""
    setup = _mk_setup("EUR/USD")
    setup.verdict_action = "SKIP"
    setup.verdict_blockers = ["Marche ferme (pas de session active)"]
    setup.confidence_score = 92.0

    with patch.object(mt5_bridge, "MT5_BRIDGE_ALLOWED_ASSET_CLASSES", ["forex"]), \
         patch.object(mt5_bridge, "MT5_BRIDGE_ENABLED", True), \
         patch.object(mt5_bridge, "MT5_BRIDGE_URL", "http://test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_API_KEY", "test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_MIN_CONFIDENCE", 60), \
         patch("httpx.AsyncClient") as mock_client:
        await mt5_bridge.send_setup(setup)
        mock_client.assert_not_called()
    assert not mt5_bridge._sent_setups_today


@pytest.mark.asyncio
async def test_setup_below_numeric_threshold_is_rejected():
    """Score numérique strict : un setup en dessous de MT5_BRIDGE_MIN_CONFIDENCE
    doit être rejeté, même sans blocker et même en verdict TAKE."""
    setup = _mk_setup("EUR/USD")
    setup.verdict_action = "TAKE"
    setup.verdict_blockers = []
    setup.confidence_score = 55.0

    with patch.object(mt5_bridge, "MT5_BRIDGE_ALLOWED_ASSET_CLASSES", ["forex"]), \
         patch.object(mt5_bridge, "MT5_BRIDGE_ENABLED", True), \
         patch.object(mt5_bridge, "MT5_BRIDGE_URL", "http://test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_API_KEY", "test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_MIN_CONFIDENCE", 60), \
         patch("httpx.AsyncClient") as mock_client:
        await mt5_bridge.send_setup(setup)
        mock_client.assert_not_called()
    assert not mt5_bridge._sent_setups_today


@pytest.mark.asyncio
async def test_send_setups_batch_filters_unsupported():
    """send_setups must pre-filter setups whose asset class isn't allowed."""
    calls: list[str] = []

    async def _spy(setup):
        calls.append(setup.pair)

    setups = [
        _mk_setup("EUR/USD"),     # forex → kept
        _mk_setup("XAU/USD"),     # metal → kept
        _mk_setup("BTC/USD"),     # crypto → filtered out
        _mk_setup("SPX"),         # equity_index → filtered out
        _mk_setup("WTI/USD"),     # energy → filtered out
    ]

    with patch.object(mt5_bridge, "MT5_BRIDGE_ALLOWED_ASSET_CLASSES", ["forex", "metal"]), \
         patch.object(mt5_bridge, "MT5_BRIDGE_ENABLED", True), \
         patch.object(mt5_bridge, "MT5_BRIDGE_URL", "http://test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_API_KEY", "test"), \
         patch.object(mt5_bridge, "send_setup", _spy):
        await mt5_bridge.send_setups(setups)

    assert sorted(calls) == ["EUR/USD", "XAU/USD"]
