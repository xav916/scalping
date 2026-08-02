"""Tests pour reddit_sentiment_scoring.

Couvre :
- No-op sur paires non-crypto ou non-supportées
- Veto ×0.90 sur BUY crowd-following (bullish fort)
- Veto ×0.90 sur SELL crowd-following (bearish fort)
- Pas de veto si contrarien (BUY en marché bearish)
- Pas de veto si sentiment neutre (entre -0.3 et +0.3)
- Best-effort si service Reddit indisponible (None retourné)
- Metadata complète dans le retour
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestApplyRedditSentiment(unittest.TestCase):

    def setUp(self):
        from backend.services import reddit_sentiment_scoring as sc
        self.sc = sc
        self._orig_threshold = sc._THRESHOLD
        self._orig_mult = sc._SOFT_VETO_MULTIPLIER

    def tearDown(self):
        self.sc._THRESHOLD = self._orig_threshold
        self.sc._SOFT_VETO_MULTIPLIER = self._orig_mult

    def _call(self, pair, direction, base_score, sentiment_return):
        with patch(
            "backend.services.reddit_sentiment_service.get_sentiment",
            return_value=sentiment_return,
        ):
            return self.sc.apply_reddit_sentiment(pair, direction, base_score)

    # ── No-op cases ──────────────────────────────────────────────────────

    def test_noop_on_forex_pair(self):
        score, meta = self.sc.apply_reddit_sentiment("EUR/USD", "buy", 70.0)
        self.assertEqual(score, 70.0)
        self.assertEqual(meta, {})

    def test_noop_on_metal_pair(self):
        score, meta = self.sc.apply_reddit_sentiment("XAU/USD", "buy", 65.0)
        self.assertEqual(score, 65.0)
        self.assertEqual(meta, {})

    def test_noop_on_energy_pair(self):
        score, meta = self.sc.apply_reddit_sentiment("WTI/USD", "sell", 60.0)
        self.assertEqual(score, 60.0)
        self.assertEqual(meta, {})

    def test_noop_on_equity_index(self):
        score, meta = self.sc.apply_reddit_sentiment("SPX", "buy", 72.0)
        self.assertEqual(score, 72.0)
        self.assertEqual(meta, {})

    def test_noop_on_unsupported_crypto(self):
        # SOL/USD non supporté par Reddit sentiment (pas de subreddit dédié MVP)
        score, meta = self.sc.apply_reddit_sentiment("SOL/USD", "buy", 65.0)
        self.assertEqual(score, 65.0)
        self.assertEqual(meta, {})

    # ── Best-effort : service indisponible ────────────────────────────────

    def test_returns_unchanged_score_if_service_unavailable(self):
        """Si reddit_sentiment_service lève une exception → best-effort, score intact."""
        with patch(
            "backend.services.reddit_sentiment_service.get_sentiment",
            side_effect=Exception("DB error"),
        ):
            score, meta = self.sc.apply_reddit_sentiment("BTC/USD", "buy", 70.0)
        self.assertEqual(score, 70.0)

    def test_returns_no_data_meta_if_sentiment_none(self):
        """Si get_sentiment retourne None → pas de veto, metadata no_data."""
        score, meta = self._call("BTC/USD", "buy", 70.0, None)
        self.assertEqual(score, 70.0)
        self.assertEqual(meta.get("reddit_error"), "no_data")

    # ── Veto cases : crowd-following ──────────────────────────────────────

    def test_veto_on_btc_buy_when_bullish_extreme(self):
        """BUY BTC + sentiment bullish fort (>0.3) → veto ×0.90."""
        sentiment = {
            "score": 0.65,
            "bullish_count": 20,
            "bearish_count": 3,
            "sample_size": 23,
            "is_fresh": True,
        }
        score, meta = self._call("BTC/USD", "buy", 70.0, sentiment)
        # Score réduit par ×0.90
        self.assertAlmostEqual(score, round(70.0 * 0.90, 1))
        self.assertEqual(meta.get("reddit_multiplier"), 0.90)
        self.assertIn("reddit_reason", meta)
        self.assertIn("bullish", meta["reddit_reason"])

    def test_veto_on_eth_sell_when_bearish_extreme(self):
        """SELL ETH + sentiment bearish fort (<-0.3) → veto ×0.90."""
        sentiment = {
            "score": -0.55,
            "bullish_count": 2,
            "bearish_count": 15,
            "sample_size": 17,
            "is_fresh": True,
        }
        score, meta = self._call("ETH/USD", "sell", 65.0, sentiment)
        self.assertAlmostEqual(score, round(65.0 * 0.90, 1))
        self.assertEqual(meta.get("reddit_multiplier"), 0.90)
        self.assertIn("bearish", meta["reddit_reason"])

    def test_veto_on_btc_sell_when_bearish_extreme(self):
        """SELL BTC + sentiment bearish fort → veto."""
        sentiment = {
            "score": -0.4,
            "bullish_count": 3,
            "bearish_count": 12,
            "sample_size": 15,
            "is_fresh": True,
        }
        score, meta = self._call("BTC/USD", "sell", 60.0, sentiment)
        self.assertAlmostEqual(score, round(60.0 * 0.90, 1))

    # ── No-veto cases : contrarien ou neutre ─────────────────────────────

    def test_no_veto_on_btc_buy_when_bearish_extreme(self):
        """BUY BTC + sentiment bearish fort → pas de veto (contrarien = potentiellement bon trade)."""
        sentiment = {
            "score": -0.55,
            "bullish_count": 2,
            "bearish_count": 15,
            "sample_size": 17,
            "is_fresh": True,
        }
        score, meta = self._call("BTC/USD", "buy", 70.0, sentiment)
        self.assertEqual(score, 70.0)
        self.assertEqual(meta.get("reddit_multiplier"), 1.0)

    def test_no_veto_on_eth_sell_when_bullish_extreme(self):
        """SELL ETH + sentiment bullish fort → pas de veto (contrarien = on vend sur euphorie)."""
        sentiment = {
            "score": 0.65,
            "bullish_count": 20,
            "bearish_count": 3,
            "sample_size": 23,
            "is_fresh": True,
        }
        score, meta = self._call("ETH/USD", "sell", 65.0, sentiment)
        self.assertEqual(score, 65.0)
        self.assertEqual(meta.get("reddit_multiplier"), 1.0)

    def test_no_veto_on_neutral_sentiment_buy(self):
        """BUY BTC + sentiment neutre (score 0.1) → pas de veto."""
        sentiment = {
            "score": 0.10,
            "bullish_count": 5,
            "bearish_count": 4,
            "sample_size": 9,
            "is_fresh": True,
        }
        score, meta = self._call("BTC/USD", "buy", 70.0, sentiment)
        self.assertEqual(score, 70.0)
        self.assertEqual(meta.get("reddit_multiplier"), 1.0)

    def test_no_veto_on_neutral_sentiment_sell(self):
        """SELL ETH + sentiment légèrement negatif (score -0.1) → pas de veto."""
        sentiment = {
            "score": -0.10,
            "bullish_count": 4,
            "bearish_count": 5,
            "sample_size": 9,
            "is_fresh": True,
        }
        score, meta = self._call("ETH/USD", "sell", 68.0, sentiment)
        self.assertEqual(score, 68.0)

    def test_no_veto_exactly_at_threshold(self):
        """Score exactement au seuil (0.30) → pas de veto (seuil strict >)."""
        sentiment = {
            "score": 0.30,
            "bullish_count": 6,
            "bearish_count": 4,
            "sample_size": 10,
            "is_fresh": True,
        }
        score, meta = self._call("BTC/USD", "buy", 70.0, sentiment)
        self.assertEqual(score, 70.0)

    # ── Score bounds ──────────────────────────────────────────────────────

    def test_veto_does_not_go_below_zero(self):
        """Score de 2.0 × 0.90 reste positif."""
        sentiment = {"score": 0.8, "bullish_count": 10, "bearish_count": 0, "sample_size": 10, "is_fresh": True}
        score, meta = self._call("BTC/USD", "buy", 2.0, sentiment)
        self.assertGreaterEqual(score, 0.0)

    def test_metadata_contains_all_expected_keys_on_veto(self):
        """Metadata complète retournée lors d'un veto."""
        sentiment = {
            "score": 0.7,
            "bullish_count": 15,
            "bearish_count": 2,
            "sample_size": 17,
            "is_fresh": True,
        }
        _, meta = self._call("BTC/USD", "buy", 65.0, sentiment)
        for key in [
            "reddit_score", "reddit_bullish_count", "reddit_bearish_count",
            "reddit_sample_size", "reddit_is_fresh", "reddit_multiplier",
            "reddit_reason",
        ]:
            self.assertIn(key, meta, f"Missing key: {key}")

    def test_metadata_contains_basic_keys_on_no_veto(self):
        """Metadata de base retournée même sans veto."""
        sentiment = {
            "score": 0.1,
            "bullish_count": 5,
            "bearish_count": 4,
            "sample_size": 9,
            "is_fresh": True,
        }
        _, meta = self._call("BTC/USD", "buy", 70.0, sentiment)
        self.assertIn("reddit_score", meta)
        self.assertIn("reddit_multiplier", meta)
        self.assertEqual(meta["reddit_multiplier"], 1.0)


if __name__ == "__main__":
    unittest.main()
