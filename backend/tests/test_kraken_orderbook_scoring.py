"""Tests unitaires — kraken_orderbook_scoring.py.

Vérifie le soft veto ×0.85 quand le spread top-of-book Kraken dépasse
8 bps, la neutralité sinon, et la résilience aux erreurs réseau.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from backend.services.kraken_orderbook_scoring import (
    _PAIR_TO_SYMBOL,
    _SOFT_VETO_MULTIPLIER,
    _SPREAD_THRESHOLD_BPS,
    apply_kraken_orderbook,
    is_crypto_pair,
)


class TestIsCryptoPair:
    def test_known_pairs_are_crypto(self):
        for pair in _PAIR_TO_SYMBOL:
            assert is_crypto_pair(pair)

    def test_forex_not_crypto(self):
        assert not is_crypto_pair("EUR/USD")
        assert not is_crypto_pair("XAU/USD")
        assert not is_crypto_pair("WTI/USD")


class TestApplyKrakenOrderbook:
    """Tests fonctionnels de apply_kraken_orderbook."""

    def _patch_spread(self, spread_bps: float):
        return patch(
            "backend.services.kraken_orderbook_scoring._get_spread_bps",
            return_value=spread_bps,
        )

    # ── Soft veto : spread > seuil ────────────────────────────────────
    def test_wide_spread_triggers_veto(self):
        spread = _SPREAD_THRESHOLD_BPS + 5.0  # 13 bps si seuil=8
        with self._patch_spread(spread):
            new_score, meta = apply_kraken_orderbook("BTC/USD", "buy", 70.0)
        assert meta["multiplier"] == _SOFT_VETO_MULTIPLIER
        assert new_score == round(70.0 * _SOFT_VETO_MULTIPLIER, 1)
        assert meta["reason"] is not None
        assert "thin" in meta["reason"].lower() or "spread" in meta["reason"].lower()
        assert meta["spread_bps"] == pytest.approx(spread)

    def test_spread_exactly_at_threshold_no_veto(self):
        """Exactement au seuil = pas de veto (condition strictement >)."""
        with self._patch_spread(_SPREAD_THRESHOLD_BPS):
            new_score, meta = apply_kraken_orderbook("BTC/USD", "sell", 60.0)
        assert meta["multiplier"] == 1.0
        assert new_score == 60.0

    def test_spread_below_threshold_no_veto(self):
        spread = _SPREAD_THRESHOLD_BPS - 2.0
        with self._patch_spread(spread):
            new_score, meta = apply_kraken_orderbook("ETH/USD", "buy", 65.0)
        assert meta["multiplier"] == 1.0
        assert new_score == 65.0
        assert meta["spread_bps"] == pytest.approx(spread)

    # ── Veto indépendant de la direction ──────────────────────────────
    def test_veto_applies_on_sell_too(self):
        spread = _SPREAD_THRESHOLD_BPS + 10.0
        with self._patch_spread(spread):
            new_score, meta = apply_kraken_orderbook("BTC/USD", "sell", 70.0)
        assert meta["multiplier"] == _SOFT_VETO_MULTIPLIER

    # ── Non-crypto pair ────────────────────────────────────────────────
    def test_non_crypto_pair_is_noop(self):
        new_score, meta = apply_kraken_orderbook("EUR/USD", "buy", 75.0)
        assert meta["multiplier"] == 1.0
        assert new_score == 75.0
        assert meta["spread_bps"] is None

    # ── Spread indisponible (None) ─────────────────────────────────────
    def test_none_spread_returns_base_score(self):
        with self._patch_spread(None):
            new_score, meta = apply_kraken_orderbook("BTC/USD", "buy", 60.0)
        assert meta["multiplier"] == 1.0
        assert new_score == 60.0

    # ── Erreur réseau ──────────────────────────────────────────────────
    def test_network_error_returns_base_score(self):
        with patch(
            "backend.services.kraken_orderbook_scoring._get_spread_bps",
            side_effect=Exception("connection refused"),
        ):
            new_score, meta = apply_kraken_orderbook("BTC/USD", "buy", 60.0)
        assert meta["multiplier"] == 1.0
        assert new_score == 60.0

    # ── Score borné [0, 100] ───────────────────────────────────────────
    def test_score_not_below_zero(self):
        with self._patch_spread(_SPREAD_THRESHOLD_BPS + 100.0):
            new_score, _ = apply_kraken_orderbook("BTC/USD", "buy", 0.0)
        assert new_score >= 0.0

    def test_score_not_above_100(self):
        with self._patch_spread(_SPREAD_THRESHOLD_BPS + 100.0):
            new_score, _ = apply_kraken_orderbook("BTC/USD", "buy", 100.0)
        assert new_score <= 100.0

    # ── Veto sur altcoins ─────────────────────────────────────────────
    def test_altcoin_veto_applied(self):
        spread = _SPREAD_THRESHOLD_BPS * 3
        with self._patch_spread(spread):
            new_score, meta = apply_kraken_orderbook("SOL/USD", "buy", 80.0)
        assert meta["multiplier"] == _SOFT_VETO_MULTIPLIER
        assert new_score < 80.0


class TestGetSpreadBps:
    """Tests de _get_spread_bps : parsing HTTP + cache."""

    def _make_mock_response(self, bids, asks) -> MagicMock:
        payload = {"orderBook": {"bids": bids, "asks": asks}}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_spread_computed_correctly(self):
        """Vérifie que bids[-1] (best bid ascendant Kraken) et asks[0] sont utilisés.

        Kraken orderbook : bids triés ascendant → best bid = bids[-1].
        Ex: bids=[[1, x], [49990, x], [50000, x]], asks=[[50010, x]]
        → best bid=50000, best ask=50010, spread≈2 bps.
        """
        import backend.services.kraken_orderbook_scoring as mod
        sym = "PF_XBTUSD"
        # Force cache miss
        mod._CACHE.pop(sym, None)

        mock_resp = self._make_mock_response(
            # Bids ascendant : pire (1) → meilleur (50000) en dernier
            bids=[[1.0, 100.0], [49990.0, 0.5], [50000.0, 1.5]],
            asks=[[50010.0, 0.8], [50020.0, 1.2]],
        )
        with patch("urllib.request.urlopen", return_value=mock_resp):
            spread = mod._get_spread_bps(sym)

        expected = (50010.0 - 50000.0) / ((50010.0 + 50000.0) / 2.0) * 10_000
        assert spread == pytest.approx(expected, rel=1e-3)

    def test_cache_hit_no_fetch(self):
        """Second appel dans le TTL → pas de requête HTTP."""
        import backend.services.kraken_orderbook_scoring as mod
        import time
        sym = "PF_ETHUSD"
        mod._CACHE[sym] = (3.5, time.time())  # dans le TTL

        with patch("urllib.request.urlopen") as mock_url:
            spread = mod._get_spread_bps(sym)

        mock_url.assert_not_called()
        assert spread == pytest.approx(3.5)

    def test_empty_orderbook_returns_none(self):
        import backend.services.kraken_orderbook_scoring as mod
        sym = "PF_SOLUSD"
        mod._CACHE.pop(sym, None)
        mock_resp = self._make_mock_response(bids=[], asks=[])
        with patch("urllib.request.urlopen", return_value=mock_resp):
            spread = mod._get_spread_bps(sym)
        assert spread is None

    def test_network_error_returns_none(self):
        import backend.services.kraken_orderbook_scoring as mod
        sym = "PF_ADAUSD"
        mod._CACHE.pop(sym, None)
        with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
            spread = mod._get_spread_bps(sym)
        assert spread is None
