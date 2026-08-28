"""Tests unitaires pour bridge_tick_validator.

Couvre :
- tick OK (spread + freshness + prix) → None
- tick trop vieux → stale_tick
- spread trop large sur forex → spread_too_wide
- divergence prix → price_divergence
- timeout /tick → None (best-effort)
- seuils différents par asset_class (crypto > forex)
- format Kraken sans time → pas de check freshness
- bridge_url vide → None (skip silencieux)
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from backend.services import bridge_tick_validator as btv


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _dest(
    bridge_url: str = "http://bridge-test:8787",
    bridge_api_key: str = "test-key",
    bridge_type: str = "mt5",
    user_id=None,
) -> SimpleNamespace:
    d = SimpleNamespace()
    d.bridge_url = bridge_url
    d.bridge_api_key = bridge_api_key
    d.bridge_type = bridge_type
    d.user_id = user_id
    return d


def _setup(pair: str = "EUR/USD", entry: float = 1.1000) -> SimpleNamespace:
    s = SimpleNamespace()
    s.pair = pair
    s.entry_price = entry
    return s


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _mock_response(body: dict, status: int = 200) -> httpx.Response:
    """Crée un httpx.Response factice avec un body JSON."""
    content = json.dumps(body).encode()
    return httpx.Response(status_code=status, content=content)


def _mock_client(response: httpx.Response):
    """Context manager simulant httpx.Client.get()."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get = MagicMock(return_value=response)
    return client


# ─── Tests scénario nominal ───────────────────────────────────────────────────

class TestValidTickReturnsNone:
    def test_mt5_format_fresh_tight_spread_ok_price(self):
        """Tick frais, spread 0.01% (< 0.05 forex), prix radar = mid → None."""
        fresh_ts = _now_ts() - 5  # 5s ago
        tick = {"bid": 1.09995, "ask": 1.10005, "time": fresh_ts}
        setup = _setup(pair="EUR/USD", entry=1.10000)
        dest = _dest(bridge_type="mt5")

        with patch("httpx.Client", return_value=_mock_client(_mock_response(tick))):
            result = btv.validate_tick_pre_push(dest, setup)

        assert result is None

    def test_kraken_format_no_time_field(self):
        """Format Kraken sans 'time' : pas de check freshness, spread OK → None."""
        tick = {"bid": 29950.0, "ask": 30050.0}  # BTC spread ~0.33% > crypto 0.20
        # Utiliser un spread plus tight
        tick = {"bid": 29990.0, "ask": 30010.0}  # spread 0.067% < 0.20
        setup = _setup(pair="BTC/USD", entry=30000.0)
        dest = _dest(bridge_type="kraken")

        with patch("httpx.Client", return_value=_mock_client(_mock_response(tick))):
            result = btv.validate_tick_pre_push(dest, setup)

        assert result is None

    def test_now_parameter_injected(self):
        """Paramètre now= sert de référence pour l'âge du tick."""
        tick_ts = 1_700_000_000.0
        tick = {"bid": 1.09995, "ask": 1.10003, "time": tick_ts}
        now_dt = datetime.fromtimestamp(tick_ts + 10, tz=timezone.utc)  # 10s après
        setup = _setup(pair="EUR/USD", entry=1.09999)
        dest = _dest()

        with patch("httpx.Client", return_value=_mock_client(_mock_response(tick))):
            result = btv.validate_tick_pre_push(dest, setup, now=now_dt)

        assert result is None


# ─── Tests stale_tick ─────────────────────────────────────────────────────────

class TestStaleTick:
    def test_tick_1_hour_old_returns_stale_tick(self):
        """Tick vieux de 1h (3600s > 30s seuil) → stale_tick."""
        old_ts = _now_ts() - 3600
        tick = {"bid": 1.09995, "ask": 1.10003, "time": old_ts}
        setup = _setup(pair="EUR/USD", entry=1.09999)
        dest = _dest()

        with patch("httpx.Client", return_value=_mock_client(_mock_response(tick))):
            result = btv.validate_tick_pre_push(dest, setup)

        assert result == "stale_tick"

    def test_tick_31_seconds_old_rejected(self):
        """31s > TICK_MAX_AGE_SEC (30) → stale_tick."""
        tick_ts = _now_ts() - 31
        tick = {"bid": 1.09995, "ask": 1.10003, "time": tick_ts}
        setup = _setup(pair="EUR/USD", entry=1.09999)
        dest = _dest()

        with patch("httpx.Client", return_value=_mock_client(_mock_response(tick))):
            result = btv.validate_tick_pre_push(dest, setup)

        assert result == "stale_tick"

    def test_tick_29_seconds_old_accepted(self):
        """29s < TICK_MAX_AGE_SEC → pas de stale (spread & prix OK aussi)."""
        tick_ts = _now_ts() - 29
        tick = {"bid": 1.09995, "ask": 1.10003, "time": tick_ts}
        setup = _setup(pair="EUR/USD", entry=1.09999)
        dest = _dest()

        with patch("httpx.Client", return_value=_mock_client(_mock_response(tick))):
            result = btv.validate_tick_pre_push(dest, setup)

        assert result is None

    def test_iso_time_string_parsed_correctly(self):
        """time au format ISO 8601 (ex: MT5 Windows bridge) → parsé en timestamp."""
        tick_ts = _now_ts() - 3600
        dt_iso = datetime.fromtimestamp(tick_ts, tz=timezone.utc).isoformat()
        tick = {"bid": 1.09995, "ask": 1.10003, "time": dt_iso}
        setup = _setup(pair="EUR/USD", entry=1.09999)
        dest = _dest()

        with patch("httpx.Client", return_value=_mock_client(_mock_response(tick))):
            result = btv.validate_tick_pre_push(dest, setup)

        assert result == "stale_tick"

    def test_now_injection_controls_age(self):
        """now= injecté à tick_ts + 31s → stale. Même à tick récent."""
        tick_ts = 1_700_000_000.0
        tick = {"bid": 1.09995, "ask": 1.10003, "time": tick_ts}
        now_dt = datetime.fromtimestamp(tick_ts + 31, tz=timezone.utc)
        setup = _setup(pair="EUR/USD", entry=1.09999)
        dest = _dest()

        with patch("httpx.Client", return_value=_mock_client(_mock_response(tick))):
            result = btv.validate_tick_pre_push(dest, setup, now=now_dt)

        assert result == "stale_tick"


# ─── Tests spread_too_wide ────────────────────────────────────────────────────

class TestSpreadTooWide:
    def test_forex_spread_1pct_too_wide(self):
        """Spread 1% sur EUR/USD (seuil forex 0.05%) → spread_too_wide."""
        fresh_ts = _now_ts() - 5
        mid = 1.10000
        spread_half = mid * 0.005  # 1% total
        tick = {"bid": mid - spread_half, "ask": mid + spread_half, "time": fresh_ts}
        setup = _setup(pair="EUR/USD", entry=mid)
        dest = _dest()

        with patch("httpx.Client", return_value=_mock_client(_mock_response(tick))):
            result = btv.validate_tick_pre_push(dest, setup)

        assert result == "spread_too_wide"

    def test_metal_spread_0_15pct_too_wide(self):
        """Spread 0.15% sur XAU/USD (seuil metal 0.10%) → spread_too_wide."""
        fresh_ts = _now_ts() - 5
        mid = 2000.0
        spread_half = mid * 0.00075  # 0.15% total
        tick = {"bid": mid - spread_half, "ask": mid + spread_half, "time": fresh_ts}
        setup = _setup(pair="XAU/USD", entry=mid)
        dest = _dest()

        with patch("httpx.Client", return_value=_mock_client(_mock_response(tick))):
            result = btv.validate_tick_pre_push(dest, setup)

        assert result == "spread_too_wide"

    def test_crypto_0_15pct_accepted(self):
        """Spread 0.15% sur BTC/USD (seuil crypto 0.20%) → OK."""
        fresh_ts = _now_ts() - 5
        mid = 30000.0
        spread_half = mid * 0.00075  # 0.15% total
        tick = {"bid": mid - spread_half, "ask": mid + spread_half, "time": fresh_ts}
        setup = _setup(pair="BTC/USD", entry=mid)
        dest = _dest()

        with patch("httpx.Client", return_value=_mock_client(_mock_response(tick))):
            result = btv.validate_tick_pre_push(dest, setup)

        assert result is None

    def test_crypto_more_permissive_than_forex(self):
        """Crypto seuil (0.20%) > forex seuil (0.05%) : même spread 0.10%
        → OK pour crypto, spread_too_wide pour forex."""
        fresh_ts = _now_ts() - 5
        spread_pct_half = 0.0005  # 0.10% total

        # BTC/USD crypto : 0.10% < 0.20% → OK
        mid_btc = 30000.0
        tick_btc = {
            "bid": mid_btc * (1 - spread_pct_half),
            "ask": mid_btc * (1 + spread_pct_half),
            "time": fresh_ts,
        }
        setup_btc = _setup(pair="BTC/USD", entry=mid_btc)
        with patch("httpx.Client", return_value=_mock_client(_mock_response(tick_btc))):
            assert btv.validate_tick_pre_push(_dest(), setup_btc) is None

        # EUR/USD forex : 0.10% > 0.05% → spread_too_wide
        mid_eur = 1.10000
        tick_eur = {
            "bid": mid_eur * (1 - spread_pct_half),
            "ask": mid_eur * (1 + spread_pct_half),
            "time": fresh_ts,
        }
        setup_eur = _setup(pair="EUR/USD", entry=mid_eur)
        with patch("httpx.Client", return_value=_mock_client(_mock_response(tick_eur))):
            assert btv.validate_tick_pre_push(_dest(), setup_eur) == "spread_too_wide"

    def test_energy_spread_0_25pct_accepted(self):
        """Spread 0.25% sur WTI/USD (seuil energy 0.30%) → OK."""
        fresh_ts = _now_ts() - 5
        mid = 80.0
        spread_half = mid * 0.00125  # 0.25% total
        tick = {"bid": mid - spread_half, "ask": mid + spread_half, "time": fresh_ts}
        setup = _setup(pair="WTI/USD", entry=mid)
        dest = _dest()

        with patch("httpx.Client", return_value=_mock_client(_mock_response(tick))):
            result = btv.validate_tick_pre_push(dest, setup)

        assert result is None


# ─── Tests price_divergence ───────────────────────────────────────────────────

class TestPriceDivergence:
    def test_entry_1p8pct_from_mid_rejected(self):
        """entry=1.1000 mais mid bridge=1.1200 → divergence ~1.79% > 0.5% → price_divergence."""
        fresh_ts = _now_ts() - 5
        mid = 1.1200
        tick = {"bid": mid - 0.00005, "ask": mid + 0.00005, "time": fresh_ts}
        setup = _setup(pair="EUR/USD", entry=1.1000)
        dest = _dest()

        with patch("httpx.Client", return_value=_mock_client(_mock_response(tick))):
            result = btv.validate_tick_pre_push(dest, setup)

        assert result == "price_divergence"

    def test_entry_0_3pct_from_mid_accepted(self):
        """0.3% de divergence < 0.5% → OK (spread aussi OK)."""
        fresh_ts = _now_ts() - 5
        mid = 1.1000
        entry = mid * 1.003  # +0.3%
        spread_half = mid * 0.0002  # 0.04% total, < 0.05% seuil forex
        tick = {"bid": mid - spread_half, "ask": mid + spread_half, "time": fresh_ts}
        setup = _setup(pair="EUR/USD", entry=entry)
        dest = _dest()

        with patch("httpx.Client", return_value=_mock_client(_mock_response(tick))):
            result = btv.validate_tick_pre_push(dest, setup)

        assert result is None

    def test_entry_exact_mid_accepted(self):
        """entry = mid exactement → divergence 0% → OK."""
        fresh_ts = _now_ts() - 5
        mid = 2000.0
        spread_half = 0.5  # 0.05% sur XAU = exactement la limite → tight
        # Utiliser un spread légèrement en dessous du seuil metal (0.10%)
        spread_half = mid * 0.0004  # 0.08% total
        tick = {"bid": mid - spread_half, "ask": mid + spread_half, "time": fresh_ts}
        setup = _setup(pair="XAU/USD", entry=mid)
        dest = _dest()

        with patch("httpx.Client", return_value=_mock_client(_mock_response(tick))):
            result = btv.validate_tick_pre_push(dest, setup)

        assert result is None


# ─── Tests best-effort / robustesse ──────────────────────────────────────────

class TestBestEffort:
    def test_timeout_returns_none(self):
        """Timeout /tick → None (ne bloque pas le push)."""
        setup = _setup()
        dest = _dest()

        client_mock = MagicMock()
        client_mock.__enter__ = MagicMock(return_value=client_mock)
        client_mock.__exit__ = MagicMock(return_value=False)
        client_mock.get = MagicMock(side_effect=httpx.TimeoutException("timeout"))

        with patch("httpx.Client", return_value=client_mock):
            result = btv.validate_tick_pre_push(dest, setup)

        assert result is None

    def test_connection_error_returns_none(self):
        """Erreur réseau générique → None."""
        setup = _setup()
        dest = _dest()

        client_mock = MagicMock()
        client_mock.__enter__ = MagicMock(return_value=client_mock)
        client_mock.__exit__ = MagicMock(return_value=False)
        client_mock.get = MagicMock(side_effect=httpx.ConnectError("refused"))

        with patch("httpx.Client", return_value=client_mock):
            result = btv.validate_tick_pre_push(dest, setup)

        assert result is None

    def test_http_404_returns_none(self):
        """Bridge sans endpoint /tick (404) → None."""
        setup = _setup()
        dest = _dest()
        resp = _mock_response({}, status=404)

        with patch("httpx.Client", return_value=_mock_client(resp)):
            result = btv.validate_tick_pre_push(dest, setup)

        assert result is None

    def test_empty_bridge_url_returns_none(self):
        """bridge_url vide → skip silencieux → None."""
        setup = _setup()
        dest = _dest(bridge_url="")

        result = btv.validate_tick_pre_push(dest, setup)

        assert result is None

    def test_empty_pair_returns_none(self):
        """pair vide → skip silencieux → None."""
        setup = _setup(pair="")
        dest = _dest()

        result = btv.validate_tick_pre_push(dest, setup)

        assert result is None

    def test_invalid_json_returns_none(self):
        """Réponse non-JSON ou champs manquants → None."""
        setup = _setup()
        dest = _dest()
        # Réponse 200 mais sans bid/ask
        resp = _mock_response({"status": "ok"})

        with patch("httpx.Client", return_value=_mock_client(resp)):
            result = btv.validate_tick_pre_push(dest, setup)

        assert result is None


# ─── Tests header d'auth ──────────────────────────────────────────────────────

class TestAuthHeader:
    def test_mt5_uses_x_api_key(self):
        result = btv._auth_header(_dest(bridge_type="mt5", bridge_api_key="mykey"))
        assert result == {"X-API-Key": "mykey"}

    def test_kraken_uses_x_bridge_key(self):
        result = btv._auth_header(_dest(bridge_type="kraken", bridge_api_key="mykey"))
        assert result == {"X-Bridge-Key": "mykey"}

    def test_kraken_spot_uses_x_bridge_key(self):
        result = btv._auth_header(_dest(bridge_type="kraken_spot", bridge_api_key="mykey"))
        assert result == {"X-Bridge-Key": "mykey"}

    def test_binance_uses_x_bridge_key(self):
        result = btv._auth_header(_dest(bridge_type="binance", bridge_api_key="mykey"))
        assert result == {"X-Bridge-Key": "mykey"}

    def test_empty_key_returns_empty_dict(self):
        result = btv._auth_header(_dest(bridge_type="mt5", bridge_api_key=""))
        assert result == {}


# ─── Tests intégration mt5_bridge._check_rejection ───────────────────────────

class TestMt5BridgeIntegration:
    """Vérifie que _check_rejection appelle validate_tick_pre_push et propage
    les rejection codes tick."""

    def _full_setup(self, pair="XAU/USD", entry=2000.0):
        from types import SimpleNamespace
        s = SimpleNamespace()
        s.pair = pair
        s.entry_price = entry
        s.stop_loss = entry * 0.99
        s.take_profit_1 = entry * 1.02
        s.take_profit_2 = None
        s.confidence_score = 80
        s.verdict_action = "TAKE"
        s.verdict_blockers = []
        s.is_simulated = False
        s.direction = "buy"
        return s

    def _dest_admin(self):
        from backend.services.bridge_destinations import BridgeConfig
        return BridgeConfig(
            destination_id="admin_legacy",
            user_id=None,
            bridge_url="http://bridge:8787",
            bridge_api_key="key",
            min_confidence=50,
            allowed_asset_classes=frozenset({"metal"}),
            auto_exec_enabled=True,
        )

    def test_tick_rejection_propagated(self):
        """stale_tick retourné par validate_tick_pre_push → _check_rejection retourne stale_tick."""
        from backend.services import mt5_bridge
        setup = self._full_setup()
        dest = self._dest_admin()

        with patch("backend.services.mt5_bridge.is_market_open_for_destination", return_value=True), \
             patch("backend.services.mt5_bridge._count_open_trades_for_pair", return_value=0), \
             patch("backend.services.mt5_bridge.MT5_BRIDGE_BLOCKED_DIRECTIONS", set()), \
             patch("backend.services.mt5_bridge.MT5_BRIDGE_AVOID_HOURS_UTC", set()), \
             patch("backend.services.mt5_bridge.MT5_BRIDGE_BLOCKED_PAIRS", frozenset()), \
             patch("backend.services.bridge_tick_validator.validate_tick_pre_push", return_value="stale_tick"):
            result = mt5_bridge._check_rejection(setup, dest)

        assert result == "stale_tick"

    def test_tick_ok_does_not_block(self):
        """validate_tick_pre_push retourne None → _check_rejection continue normalement."""
        from backend.services import mt5_bridge
        setup = self._full_setup()
        dest = self._dest_admin()

        with patch("backend.services.mt5_bridge.is_market_open_for_destination", return_value=True), \
             patch("backend.services.mt5_bridge._count_open_trades_for_pair", return_value=0), \
             patch("backend.services.mt5_bridge.MT5_BRIDGE_BLOCKED_DIRECTIONS", set()), \
             patch("backend.services.mt5_bridge.MT5_BRIDGE_AVOID_HOURS_UTC", set()), \
             patch("backend.services.mt5_bridge.MT5_BRIDGE_BLOCKED_PAIRS", frozenset()), \
             patch("backend.services.mt5_bridge._positions_courtier", return_value=[]), \
             patch("backend.services.bridge_tick_validator.validate_tick_pre_push", return_value=None):
            result = mt5_bridge._check_rejection(setup, dest)

        # Doit passer (None = no rejection)
        assert result is None

    def test_user_dest_skips_tick_check(self):
        """Pour les destinations user:N (EA queue), le tick check est skippé."""
        from backend.services import mt5_bridge
        from backend.services.bridge_destinations import BridgeConfig
        setup = self._full_setup()
        dest_user = BridgeConfig(
            destination_id="user:42",
            user_id=42,
            bridge_url="",
            bridge_api_key="key",
            min_confidence=50,
            allowed_asset_classes=frozenset({"metal"}),
            auto_exec_enabled=True,
        )

        mock_validator = MagicMock(return_value="stale_tick")
        with patch("backend.services.mt5_bridge.is_market_open_for_destination", return_value=True), \
             patch("backend.services.mt5_bridge._count_open_trades_for_pair", return_value=0), \
             patch("backend.services.mt5_bridge.MT5_BRIDGE_BLOCKED_DIRECTIONS", set()), \
             patch("backend.services.mt5_bridge.MT5_BRIDGE_AVOID_HOURS_UTC", set()), \
             patch("backend.services.mt5_bridge.MT5_BRIDGE_BLOCKED_PAIRS", frozenset()), \
             patch("backend.services.bridge_tick_validator.validate_tick_pre_push", mock_validator):
            result = mt5_bridge._check_rejection(setup, dest_user)

        # Le validator NE doit PAS avoir été appelé pour user:N
        mock_validator.assert_not_called()
        # Et le résultat doit être None (aucune rejection pour ce setup propre)
        assert result is None
