"""Tests unitaires — kraken_oi_scoring.py.

Vérifie le soft veto ×0.85 quand mouvement prix > 1% + OI décline > 2%
(short squeeze / liquidation longs), la neutralité sinon, et la résilience
aux erreurs (best-effort).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.services.kraken_oi_scoring import (
    _OI_DECLINE_THRESHOLD,
    _PAIR_TO_SYMBOL,
    _PRICE_THRESHOLD,
    _SOFT_VETO_MULTIPLIER,
    apply_kraken_oi,
    is_crypto_pair,
)


class TestIsCryptoPair:
    def test_known_pairs_are_crypto(self):
        for pair in _PAIR_TO_SYMBOL:
            assert is_crypto_pair(pair)

    def test_forex_not_crypto(self):
        assert not is_crypto_pair("EUR/USD")
        assert not is_crypto_pair("XAU/USD")


class TestApplyKrakenOi:
    """Tests fonctionnels de apply_kraken_oi."""

    def _patch_pct(self, pct_price: float, pct_oi: float):
        """Injecte des deltas (price, OI) fixes en bypassant _get_pct_changes."""
        return patch(
            "backend.services.kraken_oi_scoring._get_pct_changes",
            return_value=(pct_price, pct_oi),
        )

    # ── Soft veto BUY : short squeeze ─────────────────────────────────
    def test_buy_short_squeeze_triggers_veto(self):
        """Prix up > 1% + OI down > 2% sur BUY = short squeeze = veto."""
        pct_price = _PRICE_THRESHOLD * 1.5   # +1.5%
        pct_oi = _OI_DECLINE_THRESHOLD * 1.5  # -3%
        with self._patch_pct(pct_price, pct_oi):
            new_score, meta = apply_kraken_oi("BTC/USD", "buy", 70.0)
        assert meta["multiplier"] == _SOFT_VETO_MULTIPLIER
        assert new_score == round(70.0 * _SOFT_VETO_MULTIPLIER, 1)
        assert "BUY" in meta["reason"]
        assert "squeeze" in meta["reason"].lower()

    def test_buy_small_price_move_no_veto(self):
        """Mouvement prix sous le seuil → pas de veto même si OI décline."""
        pct_price = _PRICE_THRESHOLD * 0.5   # +0.5% < seuil 1%
        pct_oi = _OI_DECLINE_THRESHOLD * 1.5  # -3%
        with self._patch_pct(pct_price, pct_oi):
            new_score, meta = apply_kraken_oi("BTC/USD", "buy", 70.0)
        assert meta["multiplier"] == 1.0
        assert new_score == 70.0

    def test_buy_oi_stable_no_veto(self):
        """OI stable (déclin < seuil) → pas de veto même si prix monte fort."""
        pct_price = _PRICE_THRESHOLD * 2    # +2%
        pct_oi = -0.005                     # -0.5% < seuil -2%
        with self._patch_pct(pct_price, pct_oi):
            new_score, meta = apply_kraken_oi("BTC/USD", "buy", 70.0)
        assert meta["multiplier"] == 1.0

    # ── Soft veto SELL : liquidation longs ────────────────────────────
    def test_sell_long_liquidation_triggers_veto(self):
        """Prix down > 1% + OI down > 2% sur SELL = liquidation longs = veto."""
        pct_price = -_PRICE_THRESHOLD * 1.5
        pct_oi = _OI_DECLINE_THRESHOLD * 1.5
        with self._patch_pct(pct_price, pct_oi):
            new_score, meta = apply_kraken_oi("ETH/USD", "sell", 65.0)
        assert meta["multiplier"] == _SOFT_VETO_MULTIPLIER
        assert "SELL" in meta["reason"]

    def test_sell_price_up_no_veto(self):
        """Prix monte + SELL → condition prix baissier non remplie → pas de veto."""
        pct_price = _PRICE_THRESHOLD * 2
        pct_oi = _OI_DECLINE_THRESHOLD * 1.5
        with self._patch_pct(pct_price, pct_oi):
            new_score, meta = apply_kraken_oi("BTC/USD", "sell", 60.0)
        assert meta["multiplier"] == 1.0

    # ── param price_change_pct_1h externe ─────────────────────────────
    def test_external_price_change_overrides_internal(self):
        """price_change_pct_1h fourni par l'appelant remplace le delta interne."""
        # OI internal dit neutral, mais caller force prix up > seuil
        pct_price_internal = 0.002  # sous seuil
        pct_oi = _OI_DECLINE_THRESHOLD * 2  # déclin fort
        with self._patch_pct(pct_price_internal, pct_oi):
            # On force prix externe au-dessus du seuil
            new_score, meta = apply_kraken_oi(
                "BTC/USD", "buy", 70.0,
                price_change_pct_1h=_PRICE_THRESHOLD * 2,
            )
        assert meta["multiplier"] == _SOFT_VETO_MULTIPLIER

    # ── Non-crypto pair ────────────────────────────────────────────────
    def test_non_crypto_pair_is_noop(self):
        new_score, meta = apply_kraken_oi("EUR/USD", "buy", 75.0)
        assert meta["multiplier"] == 1.0
        assert new_score == 75.0

    # ── Data indisponible (None) ───────────────────────────────────────
    def test_none_pct_returns_base_score(self):
        with patch(
            "backend.services.kraken_oi_scoring._get_pct_changes",
            return_value=None,
        ):
            new_score, meta = apply_kraken_oi("BTC/USD", "buy", 60.0)
        assert meta["multiplier"] == 1.0
        assert new_score == 60.0

    # ── Erreur réseau ──────────────────────────────────────────────────
    def test_fetch_error_returns_base_score(self):
        with patch(
            "backend.services.kraken_oi_scoring._fetch_tickers",
            side_effect=Exception("network error"),
        ):
            new_score, meta = apply_kraken_oi("BTC/USD", "buy", 60.0)
        assert meta["multiplier"] == 1.0
        assert new_score == 60.0

    # ── Score borné [0, 100] ───────────────────────────────────────────
    def test_score_floored_at_0(self):
        pct_price = _PRICE_THRESHOLD * 3
        pct_oi = _OI_DECLINE_THRESHOLD * 3
        with self._patch_pct(pct_price, pct_oi):
            new_score, meta = apply_kraken_oi("BTC/USD", "buy", 0.0)
        assert new_score >= 0.0

    # ── Meta contient pct_price et pct_oi ─────────────────────────────
    def test_meta_contains_pct_values_on_veto(self):
        pct_price = _PRICE_THRESHOLD * 2
        pct_oi = _OI_DECLINE_THRESHOLD * 2
        with self._patch_pct(pct_price, pct_oi):
            _, meta = apply_kraken_oi("BTC/USD", "buy", 70.0)
        assert meta["pct_price"] == pytest.approx(pct_price)
        assert meta["pct_oi"] == pytest.approx(pct_oi)

    def test_meta_contains_pct_values_on_neutral(self):
        pct_price = 0.001
        pct_oi = -0.001
        with self._patch_pct(pct_price, pct_oi):
            _, meta = apply_kraken_oi("BTC/USD", "buy", 70.0)
        assert meta["pct_price"] == pytest.approx(pct_price)
        assert meta["pct_oi"] == pytest.approx(pct_oi)


class TestHistorySnapshot:
    """Tests du mécanisme d'historique 1h interne."""

    def test_first_call_returns_neutral(self):
        """Premier appel : pas d'historique 1h disponible → neutre."""
        import backend.services.kraken_oi_scoring as mod
        sym = "PF_XBTUSD"
        mod._HISTORY_1H.pop(sym, None)
        mod._CURRENT_CACHE.pop(sym, None)
        mod._LAST_FETCH_DATA = []

        import json, time
        from unittest.mock import MagicMock
        fake_tickers = {"tickers": [
            {"symbol": sym, "openInterest": 1000.0, "bid": 50000.0, "ask": 50001.0},
        ]}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(fake_tickers).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        mod._LAST_FETCH_AT = 0.0
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = mod._get_pct_changes(sym)
        assert result is None  # pas encore d'historique 1h

    def test_recent_history_too_fresh_returns_none(self):
        """Snapshot historique < 55 min → données insuffisantes → None."""
        import backend.services.kraken_oi_scoring as mod
        import time
        sym = "PF_ETHUSD"
        # Injecter un snapshot récent (30 min)
        mod._HISTORY_1H[sym] = (900.0, 3000.0, time.time() - 1800)
        mod._CURRENT_CACHE[sym] = (950.0, 3050.0, time.time())
        result = mod._get_pct_changes(sym)
        assert result is None
