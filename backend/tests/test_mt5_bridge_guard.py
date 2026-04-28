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
    s.is_simulated = False
    s.timestamp = datetime.now(timezone.utc)
    return s


@pytest.fixture(autouse=True)
def _reset_dedup():
    """Make sure each test starts with a clean dedup state (memory + DB).

    Phase B added a DB-side dedup via mt5_pushes_service. The shared
    cwd-relative trades.db can leak between tests, so we wipe both layers.
    """
    mt5_bridge._sent_setups_today.clear()
    try:
        import sqlite3

        from backend.services.trade_log_service import _DB_PATH

        with sqlite3.connect(_DB_PATH) as c:
            c.execute("DELETE FROM mt5_pushes")
    except Exception:
        pass  # DB pas encore créée, pas grave
    yield
    mt5_bridge._sent_setups_today.clear()
    try:
        import sqlite3

        from backend.services.trade_log_service import _DB_PATH

        with sqlite3.connect(_DB_PATH) as c:
            c.execute("DELETE FROM mt5_pushes")
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _disable_star_filter(monkeypatch):
    """Most existing tests in this module exercise the asset-class guard with
    EUR/USD, BTC/USD, SPX, etc. Since we now also filter by SHADOW_PAIRS
    upstream, neutralize that filter here so the asset-class assertions stay
    on point. The dedicated star-filter behaviour has its own test below."""
    monkeypatch.setattr(
        mt5_bridge,
        "_STAR_PAIRS_SET",
        frozenset({"EUR/USD", "GBP/USD", "USD/JPY", "EUR/JPY", "BTC/USD",
                   "SPX", "XAU/USD", "XAG/USD", "WTI/USD", "ETH/USD",
                   "XLI", "XLK"}),
    )


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
async def test_setup_rejected_when_sl_too_close_jpy():
    """EUR/JPY avec SL à 1 pip (0.005%) → rejeté par seuil forex_jpy 0.02%."""
    setup = _mk_setup("EUR/JPY")
    setup.entry_price = 187.15
    setup.stop_loss = 187.14  # 1 pip JPY = 0.005%
    setup.confidence_score = 90.0
    setup.verdict_blockers = []
    setup.is_simulated = False

    with patch.object(mt5_bridge, "MT5_BRIDGE_ALLOWED_ASSET_CLASSES", ["forex"]), \
         patch.object(mt5_bridge, "MT5_BRIDGE_ENABLED", True), \
         patch.object(mt5_bridge, "MT5_BRIDGE_URL", "http://test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_API_KEY", "test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_MIN_CONFIDENCE", 55), \
         patch("backend.services.mt5_bridge.is_market_open_for", lambda p: True), \
         patch("httpx.AsyncClient") as mock_client:
        await mt5_bridge.send_setup(setup)
        mock_client.assert_not_called()
    assert not mt5_bridge._sent_setups_today


@pytest.mark.asyncio
async def test_setup_accepted_when_jpy_sl_reasonable_after_per_class_fix():
    """EUR/JPY avec SL à 4 pips (0.021%) passe désormais — avec seuil
    forex_jpy=0.02% (vs ancien global 0.05% = 9 pips min, infaisable sur JPY)."""
    setup = _mk_setup("EUR/JPY")
    setup.entry_price = 187.15
    setup.stop_loss = 187.11  # 4 pips JPY = 0.021%
    setup.take_profit_1 = 187.30
    setup.confidence_score = 90.0
    setup.verdict_blockers = []
    setup.is_simulated = False

    with patch.object(mt5_bridge, "MT5_BRIDGE_ALLOWED_ASSET_CLASSES", ["forex"]), \
         patch.object(mt5_bridge, "MT5_BRIDGE_ENABLED", True), \
         patch.object(mt5_bridge, "MT5_BRIDGE_URL", "http://test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_API_KEY", "test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_MIN_CONFIDENCE", 55), \
         patch("backend.services.mt5_bridge.is_market_open_for", lambda p: True):
        rejection = mt5_bridge._check_rejection(setup)
    assert rejection is None, f"Expected acceptance, got rejection: {rejection}"


def test_min_sl_distance_pct_for_jpy_pair():
    """Pairs avec JPY utilisent le seuil forex_jpy, pas forex_major."""
    assert mt5_bridge._min_sl_distance_pct_for("USD/JPY") == 0.02
    assert mt5_bridge._min_sl_distance_pct_for("EUR/JPY") == 0.02
    assert mt5_bridge._min_sl_distance_pct_for("GBP/JPY") == 0.02


def test_min_sl_distance_pct_for_major_forex():
    assert mt5_bridge._min_sl_distance_pct_for("EUR/USD") == 0.04
    assert mt5_bridge._min_sl_distance_pct_for("USD/CHF") == 0.04


def test_min_sl_distance_pct_for_metal_and_crypto():
    assert mt5_bridge._min_sl_distance_pct_for("XAU/USD") == 0.05
    assert mt5_bridge._min_sl_distance_pct_for("BTC/USD") == 0.15


def test_min_sl_distance_pct_falls_back_when_class_missing():
    """Si la pair donne un asset class non mappé, on tombe sur le legacy."""
    with patch.object(mt5_bridge, "MT5_BRIDGE_MIN_SL_DISTANCE_PCT_PER_CLASS", {}):
        # dict vide → tombe sur le legacy
        assert mt5_bridge._min_sl_distance_pct_for("EUR/USD") == mt5_bridge.MT5_BRIDGE_MIN_SL_DISTANCE_PCT


def test_max_positions_per_pair_respects_asset_class_cap():
    """forex=2, crypto=1 par défaut."""
    assert mt5_bridge._max_positions_for_pair("EUR/USD") == 2
    assert mt5_bridge._max_positions_for_pair("XAU/USD") == 2
    assert mt5_bridge._max_positions_for_pair("BTC/USD") == 1
    assert mt5_bridge._max_positions_for_pair("SPX") == 1


def test_max_positions_per_pair_override_via_config():
    """Surcharge via MT5_BRIDGE_MAX_POSITIONS_PER_PAIR."""
    with patch.object(mt5_bridge, "MT5_BRIDGE_MAX_POSITIONS_PER_PAIR",
                      {"forex": 3, "metal": 1}):
        assert mt5_bridge._max_positions_for_pair("EUR/USD") == 3
        assert mt5_bridge._max_positions_for_pair("XAU/USD") == 1


@pytest.mark.asyncio
async def test_setup_rejected_when_max_positions_per_pair_reached():
    """Si 2 XAU/USD OPEN et un 3e setup arrive → rejeté."""
    setup = _mk_setup("XAU/USD")
    setup.entry_price = 2600.0
    setup.stop_loss = 2595.0
    setup.take_profit_1 = 2610.0
    setup.confidence_score = 90.0
    setup.verdict_blockers = []
    setup.is_simulated = False

    with patch.object(mt5_bridge, "MT5_BRIDGE_ALLOWED_ASSET_CLASSES", ["metal"]), \
         patch.object(mt5_bridge, "MT5_BRIDGE_ENABLED", True), \
         patch.object(mt5_bridge, "MT5_BRIDGE_URL", "http://test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_API_KEY", "test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_MIN_CONFIDENCE", 55), \
         patch("backend.services.mt5_bridge.is_market_open_for", lambda p: True), \
         patch("backend.services.mt5_bridge._count_open_trades_for_pair", return_value=2):
        rejection = mt5_bridge._check_rejection(setup)
    assert rejection == "max_positions_per_pair"


@pytest.mark.asyncio
async def test_setup_accepted_when_below_max_positions():
    """Si 1 XAU/USD OPEN et cap forex=2 → accepté."""
    setup = _mk_setup("XAU/USD")
    setup.entry_price = 2600.0
    setup.stop_loss = 2595.0
    setup.take_profit_1 = 2610.0
    setup.confidence_score = 90.0
    setup.verdict_blockers = []
    setup.is_simulated = False

    with patch.object(mt5_bridge, "MT5_BRIDGE_ALLOWED_ASSET_CLASSES", ["metal"]), \
         patch.object(mt5_bridge, "MT5_BRIDGE_ENABLED", True), \
         patch.object(mt5_bridge, "MT5_BRIDGE_URL", "http://test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_API_KEY", "test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_MIN_CONFIDENCE", 55), \
         patch("backend.services.mt5_bridge.is_market_open_for", lambda p: True), \
         patch("backend.services.mt5_bridge._count_open_trades_for_pair", return_value=1):
        rejection = mt5_bridge._check_rejection(setup)
    assert rejection is None


@pytest.mark.asyncio
async def test_setup_rejected_when_market_closed():
    """XAU/USD poussé pendant le daily break 21-22h UTC → refusé avant envoi.
    Évite les rc=10018 MARKET_CLOSED côté bridge."""
    setup = _mk_setup("XAU/USD")
    setup.confidence_score = 90.0
    setup.verdict_blockers = []
    setup.is_simulated = False

    with patch.object(mt5_bridge, "MT5_BRIDGE_ALLOWED_ASSET_CLASSES", ["metal"]), \
         patch.object(mt5_bridge, "MT5_BRIDGE_ENABLED", True), \
         patch.object(mt5_bridge, "MT5_BRIDGE_URL", "http://test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_API_KEY", "test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_MIN_CONFIDENCE", 55), \
         patch("backend.services.mt5_bridge.is_market_open_for", lambda p: False), \
         patch("httpx.AsyncClient") as mock_client:
        await mt5_bridge.send_setup(setup)
        mock_client.assert_not_called()
    assert not mt5_bridge._sent_setups_today


@pytest.mark.asyncio
async def test_simulated_setup_is_rejected():
    """Un setup construit sur des candles simulées (fallback price_service quand
    l'API Twelve Data ne répond pas) doit être bloqué avant envoi au bridge :
    le prix simulé est hardcodé à 2650 pour la plupart des pairs, ce qui
    produit des entry/SL/TP complètement hors du prix marché réel et cause
    des rc=10016 INVALID_STOPS côté MT5."""
    setup = _mk_setup("EUR/USD")
    setup.is_simulated = True  # fallback simulated_candles s'est activé
    setup.verdict_action = "TAKE"
    setup.verdict_blockers = []
    setup.confidence_score = 90.0

    with patch.object(mt5_bridge, "MT5_BRIDGE_ALLOWED_ASSET_CLASSES", ["forex"]), \
         patch.object(mt5_bridge, "MT5_BRIDGE_ENABLED", True), \
         patch.object(mt5_bridge, "MT5_BRIDGE_URL", "http://test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_API_KEY", "test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_MIN_CONFIDENCE", 55), \
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


@pytest.mark.asyncio
async def test_send_setups_filters_non_star_pairs(monkeypatch):
    """send_setups must drop pairs that are not in SHADOW_PAIRS (Phase 4 stars)."""
    # Restore the real star filter for this test (the autouse fixture relaxes it)
    monkeypatch.setattr(
        mt5_bridge,
        "_STAR_PAIRS_SET",
        frozenset({"XAU/USD", "XAG/USD", "WTI/USD", "ETH/USD", "XLI", "XLK"}),
    )

    calls: list[str] = []

    async def _spy(setup):
        calls.append(setup.pair)

    setups = [
        _mk_setup("EUR/USD"),     # forex but NOT a star → filtered
        _mk_setup("BTC/USD"),     # crypto and not a star → filtered
        _mk_setup("XAU/USD"),     # star metal → kept
        _mk_setup("ETH/USD"),     # star crypto → kept
        _mk_setup("WTI/USD"),     # star energy → kept
    ]

    with patch.object(mt5_bridge, "MT5_BRIDGE_ALLOWED_ASSET_CLASSES",
                      ["forex", "metal", "energy", "crypto"]), \
         patch.object(mt5_bridge, "MT5_BRIDGE_ENABLED", True), \
         patch.object(mt5_bridge, "MT5_BRIDGE_URL", "http://test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_API_KEY", "test"), \
         patch.object(mt5_bridge, "send_setup", _spy):
        await mt5_bridge.send_setups(setups)

    assert sorted(calls) == ["ETH/USD", "WTI/USD", "XAU/USD"]


def test_check_rejection_returns_not_a_star_for_non_stars(monkeypatch):
    """_check_rejection must return the private reason '_not_a_star' for non-star pairs."""
    monkeypatch.setattr(
        mt5_bridge,
        "_STAR_PAIRS_SET",
        frozenset({"XAU/USD", "XAG/USD", "WTI/USD", "ETH/USD", "XLI", "XLK"}),
    )
    with patch.object(mt5_bridge, "MT5_BRIDGE_ENABLED", True), \
         patch.object(mt5_bridge, "MT5_BRIDGE_URL", "http://test"), \
         patch.object(mt5_bridge, "MT5_BRIDGE_API_KEY", "test"):
        assert mt5_bridge._check_rejection(_mk_setup("EUR/USD")) == "_not_a_star"
        assert mt5_bridge._check_rejection(_mk_setup("BTC/USD")) == "_not_a_star"
        # Star pair should not be rejected for that reason (other rejections may apply)
        assert mt5_bridge._check_rejection(_mk_setup("XAU/USD")) != "_not_a_star"
