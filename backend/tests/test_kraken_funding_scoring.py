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
    """Tests de _fetch_all_rates : parsing, conversion absolu→relatif, cache.

    Kraken expose ``fundingRate`` en valeur ABSOLUE (devise de cotation par
    contrat), pas en taux relatif. ``_fetch_all_rates`` doit diviser par
    ``indexPrice`` pour produire un taux relatif comparable à
    ``_EXTREME_THRESHOLD``. Ces tests utilisent un relevé réel du
    2026-08-05 :
    - PF_XBTUSD  fundingRate=0.25299581803314525  indexPrice=64013.79
      → relatif ≈ 3.95e-6
    - PF_ETHUSD  fundingRate=0.03174136677858395  indexPrice=1862.71
      → relatif ≈ 1.70e-5

    Avant le fix, ``_fetch_all_rates`` retournait directement ``fundingRate``
    (la valeur absolue) sans diviser par ``indexPrice`` — ces tests
    échouent contre ce code (confronté via ``git stash`` du service).
    """

    @staticmethod
    def _mock_urlopen(fake_response: dict):
        import json
        from unittest.mock import MagicMock

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(fake_response).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def _force_refetch(self, mod):
        """Reset le cache module pour forcer un vrai appel réseau (mocké)."""
        original_ts = mod._LAST_FETCH_AT
        original_data = mod._LAST_FETCH_DATA
        mod._LAST_FETCH_AT = 0.0
        mod._LAST_FETCH_DATA = {}
        return original_ts, original_data

    def test_parse_tickers_response_converts_absolute_to_relative(self):
        """Taux absolu réaliste (relevé du 2026-08-05) → taux relatif attendu."""
        from backend.services.kraken_funding_scoring import _fetch_all_rates
        import backend.services.kraken_funding_scoring as mod

        fake_response = {
            "tickers": [
                {
                    "symbol": "PF_XBTUSD",
                    "fundingRate": 0.25299581803314525,
                    "indexPrice": 64013.79,
                },
                {
                    "symbol": "PF_ETHUSD",
                    "fundingRate": 0.03174136677858395,
                    "indexPrice": 1862.71,
                },
                {"symbol": "PF_SOLUSD"},  # pas de fundingRate → ignoré
            ]
        }
        mock_resp = self._mock_urlopen(fake_response)
        original_ts, original_data = self._force_refetch(mod)
        try:
            with patch("urllib.request.urlopen", return_value=mock_resp):
                rates = _fetch_all_rates()
        finally:
            mod._LAST_FETCH_AT = original_ts
            mod._LAST_FETCH_DATA = original_data

        assert rates.get("PF_XBTUSD") == pytest.approx(3.9520e-6, rel=1e-3)
        assert rates.get("PF_ETHUSD") == pytest.approx(1.7038e-5, rel=1e-3)
        assert "PF_SOLUSD" not in rates
        # Le taux relatif doit être très inférieur à la valeur absolue brute
        # (facteur ~64000 pour BTC) — sinon la conversion n'a pas eu lieu.
        assert rates["PF_XBTUSD"] < 0.25299581803314525 / 1000

    def test_missing_index_price_symbol_absent_not_zero(self):
        """``indexPrice`` absent → le symbole est absent du dict (jamais 0.0
        ni la valeur absolue en repli)."""
        from backend.services.kraken_funding_scoring import (
            _fetch_all_rates,
            _get_funding_rate,
        )
        import backend.services.kraken_funding_scoring as mod

        fake_response = {
            "tickers": [
                {"symbol": "PF_XBTUSD", "fundingRate": 0.253},  # pas d'indexPrice
            ]
        }
        mock_resp = self._mock_urlopen(fake_response)
        original_ts, original_data = self._force_refetch(mod)
        try:
            with patch("urllib.request.urlopen", return_value=mock_resp):
                rates = _fetch_all_rates()
                rate = _get_funding_rate("PF_XBTUSD")
        finally:
            mod._LAST_FETCH_AT = original_ts
            mod._LAST_FETCH_DATA = original_data

        assert "PF_XBTUSD" not in rates
        assert rate is None
        assert rate != 0.0
        assert rate != 0.253

    def test_zero_or_negative_index_price_symbol_absent_not_zero(self):
        """``indexPrice`` nul ou négatif → incalculable, symbole absent."""
        from backend.services.kraken_funding_scoring import _fetch_all_rates
        import backend.services.kraken_funding_scoring as mod

        fake_response = {
            "tickers": [
                {"symbol": "PF_XBTUSD", "fundingRate": 0.253, "indexPrice": 0.0},
                {"symbol": "PF_ETHUSD", "fundingRate": 0.03, "indexPrice": -100.0},
            ]
        }
        mock_resp = self._mock_urlopen(fake_response)
        original_ts, original_data = self._force_refetch(mod)
        try:
            with patch("urllib.request.urlopen", return_value=mock_resp):
                rates = _fetch_all_rates()
        finally:
            mod._LAST_FETCH_AT = original_ts
            mod._LAST_FETCH_DATA = original_data

        assert "PF_XBTUSD" not in rates
        assert "PF_ETHUSD" not in rates


class TestRealFundingNoLongerVetoesEveryBuy:
    """Le test qui démontre la correction du bug de production, de bout en
    bout (mock au niveau HTTP, PAS au niveau ``_get_funding_rate``).

    Avant le fix : ``_fetch_all_rates`` retournait directement
    ``fundingRate`` (valeur ABSOLUE Kraken, ex: 0.253 pour BTC), largement
    > ``_EXTREME_THRESHOLD`` (0.0005) → tout achat crypto au funding positif
    était vetoé. Un test qui patche ``_get_funding_rate`` directement avec
    une valeur déjà relative ne détecterait PAS ce bug (il passerait aussi
    contre le code d'avant fix) — d'où le mock au niveau
    ``urllib.request.urlopen``, qui force le passage par la conversion
    ``fundingRate / indexPrice`` dans ``_fetch_all_rates``.

    Après le fix : le taux RELATIF réel (≈3.95e-6 pour BTC, ≈1.70e-5 pour
    ETH, mesurés le 2026-08-05) est très en dessous du seuil → plus de
    veto sur ces cas réels.
    """

    @staticmethod
    def _mock_urlopen(fake_response: dict):
        import json
        from unittest.mock import MagicMock

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(fake_response).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def _apply_with_mocked_ticker(self, pair: str, direction: str, base_score: float,
                                   symbol: str, funding_rate: float, index_price: float):
        import backend.services.kraken_funding_scoring as mod

        fake_response = {
            "tickers": [
                {"symbol": symbol, "fundingRate": funding_rate, "indexPrice": index_price}
            ]
        }
        mock_resp = self._mock_urlopen(fake_response)
        original_ts, original_data = mod._LAST_FETCH_AT, mod._LAST_FETCH_DATA
        mod._LAST_FETCH_AT = 0.0
        mod._LAST_FETCH_DATA = {}
        try:
            with patch("urllib.request.urlopen", return_value=mock_resp):
                return apply_kraken_funding(pair, direction, base_score)
        finally:
            mod._LAST_FETCH_AT = original_ts
            mod._LAST_FETCH_DATA = original_data

    def test_btc_buy_at_real_funding_is_not_vetoed(self):
        new_score, meta = self._apply_with_mocked_ticker(
            "BTC/USD", "buy", 70.0,
            symbol="PF_XBTUSD", funding_rate=0.25299581803314525, index_price=64013.79,
        )
        assert meta["multiplier"] == 1.0
        assert meta["reason"] is None
        assert new_score == 70.0

    def test_eth_buy_at_real_funding_is_not_vetoed(self):
        new_score, meta = self._apply_with_mocked_ticker(
            "ETH/USD", "buy", 70.0,
            symbol="PF_ETHUSD", funding_rate=0.03174136677858395, index_price=1862.71,
        )
        assert meta["multiplier"] == 1.0
        assert meta["reason"] is None
        assert new_score == 70.0

    def test_relative_funding_still_vetoes_extreme_buy(self):
        """Un funding réellement extrême (au-dessus du seuil, en relatif)
        déclenche toujours le veto — direction BUY."""
        extreme_relative_rate = _EXTREME_THRESHOLD * 3
        with patch(
            "backend.services.kraken_funding_scoring._get_funding_rate",
            return_value=extreme_relative_rate,
        ):
            new_score, meta = apply_kraken_funding("BTC/USD", "buy", 70.0)
        assert meta["multiplier"] == _SOFT_VETO_MULTIPLIER
        assert new_score < 70.0

    def test_relative_funding_still_vetoes_extreme_sell(self):
        """Un funding réellement extrême (au-dessus du seuil, en relatif)
        déclenche toujours le veto — direction SELL."""
        extreme_relative_rate = -_EXTREME_THRESHOLD * 3
        with patch(
            "backend.services.kraken_funding_scoring._get_funding_rate",
            return_value=extreme_relative_rate,
        ):
            new_score, meta = apply_kraken_funding("ETH/USD", "sell", 70.0)
        assert meta["multiplier"] == _SOFT_VETO_MULTIPLIER
        assert new_score < 70.0
