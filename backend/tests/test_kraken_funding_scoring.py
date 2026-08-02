"""Tests unitaires — kraken_funding_scoring.py.

Vérifie le soft veto ×0.85 sur funding rate Kraken Futures extrême,
le comportement neutre quand le taux est dans la norme, et la résilience
aux erreurs réseau (best-effort : retourner base_score inchangé).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.services.kraken_funding_scoring import (
    _EXTREME_THRESHOLD,
    _PAIR_TO_SYMBOL,
    _SOFT_VETO_MULTIPLIER,
    apply_kraken_funding,
    is_crypto_pair,
)


class TestIsCryptoPair:
    def test_known_pairs_are_crypto(self):
        for pair in _PAIR_TO_SYMBOL:
            assert is_crypto_pair(pair), f"{pair} should be crypto"

    def test_forex_not_crypto(self):
        assert not is_crypto_pair("EUR/USD")
        assert not is_crypto_pair("XAU/USD")
        assert not is_crypto_pair("SPX")

    def test_unknown_pair_not_crypto(self):
        assert not is_crypto_pair("UNKNOWN/USD")


class TestApplyKrakenFunding:
    """Tests fonctionnels de apply_kraken_funding."""

    def _patch_rate(self, rate: float):
        """Context manager qui injecte un funding rate fixe."""
        return patch(
            "backend.services.kraken_funding_scoring._get_funding_rate",
            return_value=rate,
        )

    # ── Soft veto BUY ──────────────────────────────────────────────────
    def test_buy_extreme_positive_funding_triggers_veto(self):
        rate = _EXTREME_THRESHOLD * 2  # double du seuil
        with self._patch_rate(rate):
            new_score, meta = apply_kraken_funding("BTC/USD", "buy", 70.0)
        assert meta["multiplier"] == _SOFT_VETO_MULTIPLIER
        assert new_score == round(70.0 * _SOFT_VETO_MULTIPLIER, 1)
        assert meta["reason"] is not None
        assert "BUY" in meta["reason"]

    def test_buy_at_threshold_boundary_no_veto(self):
        """Exactement au seuil = pas de veto (condition strictement >)."""
        with self._patch_rate(_EXTREME_THRESHOLD):
            new_score, meta = apply_kraken_funding("BTC/USD", "buy", 60.0)
        assert meta["multiplier"] == 1.0
        assert new_score == 60.0

    # ── Soft veto SELL ─────────────────────────────────────────────────
    def test_sell_extreme_negative_funding_triggers_veto(self):
        rate = -_EXTREME_THRESHOLD * 2
        with self._patch_rate(rate):
            new_score, meta = apply_kraken_funding("ETH/USD", "sell", 65.0)
        assert meta["multiplier"] == _SOFT_VETO_MULTIPLIER
        assert new_score == round(65.0 * _SOFT_VETO_MULTIPLIER, 1)
        assert meta["reason"] is not None
        assert "SELL" in meta["reason"]

    def test_sell_positive_funding_no_veto(self):
        """Funding positif + SELL = direction non surcrowdée → neutre."""
        rate = _EXTREME_THRESHOLD * 2
        with self._patch_rate(rate):
            new_score, meta = apply_kraken_funding("BTC/USD", "sell", 60.0)
        assert meta["multiplier"] == 1.0
        assert new_score == 60.0

    def test_buy_negative_funding_no_veto(self):
        """Funding négatif + BUY = direction non surcrowdée → neutre."""
        rate = -_EXTREME_THRESHOLD * 2
        with self._patch_rate(rate):
            new_score, meta = apply_kraken_funding("BTC/USD", "buy", 60.0)
        assert meta["multiplier"] == 1.0
        assert new_score == 60.0

    # ── Neutre : funding normal ────────────────────────────────────────
    def test_neutral_funding_no_veto(self):
        rate = 0.0001  # bien sous le seuil 0.0005
        with self._patch_rate(rate):
            new_score, meta = apply_kraken_funding("BTC/USD", "buy", 70.0)
        assert meta["multiplier"] == 1.0
        assert new_score == 70.0

    # ── Non-crypto pair ────────────────────────────────────────────────
    def test_non_crypto_pair_is_noop(self):
        new_score, meta = apply_kraken_funding("EUR/USD", "buy", 75.0)
        assert meta["multiplier"] == 1.0
        assert new_score == 75.0
        assert meta["symbol"] is None

    # ── Rate indisponible (None) ───────────────────────────────────────
    def test_none_rate_returns_base_score(self):
        with patch(
            "backend.services.kraken_funding_scoring._get_funding_rate",
            return_value=None,
        ):
            new_score, meta = apply_kraken_funding("BTC/USD", "buy", 60.0)
        assert meta["multiplier"] == 1.0
        assert new_score == 60.0

    # ── Erreur réseau ──────────────────────────────────────────────────
    def test_network_error_returns_base_score(self):
        with patch(
            "backend.services.kraken_funding_scoring._fetch_all_rates",
            side_effect=Exception("timeout"),
        ):
            new_score, meta = apply_kraken_funding("BTC/USD", "buy", 60.0)
        assert meta["multiplier"] == 1.0
        assert new_score == 60.0

    # ── Score borné [0, 100] ───────────────────────────────────────────
    def test_score_capped_at_100(self):
        rate = _EXTREME_THRESHOLD * 3
        with self._patch_rate(rate):
            new_score, meta = apply_kraken_funding("BTC/USD", "buy", 100.0)
        assert new_score <= 100.0

    def test_score_floored_at_0(self):
        rate = _EXTREME_THRESHOLD * 3
        with self._patch_rate(rate):
            new_score, meta = apply_kraken_funding("BTC/USD", "buy", 0.0)
        assert new_score >= 0.0

    # ── Meta contient symbol et rate ──────────────────────────────────
    def test_meta_contains_symbol_and_rate(self):
        rate = 0.0002
        with self._patch_rate(rate):
            _, meta = apply_kraken_funding("ETH/USD", "buy", 60.0)
        assert meta["symbol"] == "PF_ETHUSD"
        assert meta["rate"] == rate

    # ── Veto appliqué sur SOL (altcoin) ───────────────────────────────
    def test_altcoin_veto_applied(self):
        rate = _EXTREME_THRESHOLD * 5
        with self._patch_rate(rate):
            new_score, meta = apply_kraken_funding("SOL/USD", "buy", 80.0)
        assert meta["multiplier"] == _SOFT_VETO_MULTIPLIER
        assert new_score < 80.0


class TestFetchAllRates:
    """Tests de _fetch_all_rates : parsing et cache."""

    def test_parse_tickers_response(self):
        from backend.services.kraken_funding_scoring import _fetch_all_rates
        import backend.services.kraken_funding_scoring as mod

        fake_response = {
            "tickers": [
                {"symbol": "PF_XBTUSD", "fundingRate": 0.0003},
                {"symbol": "PF_ETHUSD", "fundingRate": -0.0002},
                {"symbol": "PF_SOLUSD"},  # pas de fundingRate → ignoré
            ]
        }
        import json
        from io import BytesIO
        from unittest.mock import MagicMock

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(fake_response).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        # Forcer re-fetch en réinitialisant le timestamp
        original_ts = mod._LAST_FETCH_AT
        mod._LAST_FETCH_AT = 0.0
        mod._LAST_FETCH_DATA = {}
        try:
            with patch("urllib.request.urlopen", return_value=mock_resp):
                rates = _fetch_all_rates()
        finally:
            mod._LAST_FETCH_AT = original_ts

        assert rates.get("PF_XBTUSD") == pytest.approx(0.0003)
        assert rates.get("PF_ETHUSD") == pytest.approx(-0.0002)
        assert "PF_SOLUSD" not in rates
