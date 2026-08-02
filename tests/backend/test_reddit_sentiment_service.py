"""Tests pour reddit_sentiment_service.

Couvre :
- Parsing titres Reddit + calcul scores
- Fetch mock JSON Reddit → score correct
- Fallback None si Reddit unreachable
- Agrégation multi-subreddit dans get_sentiment
- Filtre données périmées (> 2h)
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers pour construire un payload Reddit JSON minimal
# ---------------------------------------------------------------------------

def _make_reddit_response(titles: list[str]) -> bytes:
    """Construit un payload JSON hot.json Reddit minimal."""
    children = [
        {"kind": "t3", "data": {"title": t, "score": 100}}
        for t in titles
    ]
    return json.dumps({"data": {"children": children}}).encode()


def _make_mock_urlopen(payload: bytes):
    """Retourne un context manager mock simulant urlopen."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = payload
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ---------------------------------------------------------------------------
# Tests unitaires scoring interne (_score_posts, _compute_score)
# ---------------------------------------------------------------------------

class TestScorePostsUnit(unittest.TestCase):
    """Tests des fonctions internes de scoring (pas d'I/O)."""

    def setUp(self):
        from backend.services import reddit_sentiment_service as svc
        self.svc = svc

    def test_bullish_keywords_detected(self):
        posts = [
            {"title": "bitcoin to the moon this week!", "score": 500},
            {"title": "btc pump incoming, buy the dip", "score": 300},
        ]
        result = self.svc._score_posts(posts, frozenset({"bitcoin", "btc"}))
        self.assertEqual(result["bullish_count"], 2)
        self.assertEqual(result["bearish_count"], 0)
        self.assertEqual(result["sample_size"], 2)

    def test_bearish_keywords_detected(self):
        posts = [
            {"title": "btc crash incoming, rekt all longs", "score": 200},
            {"title": "bitcoin dump to 20k, bear market confirmed", "score": 100},
        ]
        result = self.svc._score_posts(posts, frozenset({"bitcoin", "btc"}))
        self.assertGreater(result["bearish_count"], 0)
        self.assertEqual(result["sample_size"], 2)

    def test_irrelevant_posts_filtered(self):
        posts = [
            {"title": "ethereum dumps 10%, eth bear market", "score": 100},
            {"title": "solana moon", "score": 50},
        ]
        # BTC terms — eth/sol posts ne comptent pas
        result = self.svc._score_posts(posts, frozenset({"bitcoin", "btc"}))
        self.assertEqual(result["sample_size"], 0)

    def test_mixed_post_counts_both(self):
        posts = [
            {"title": "btc to the moon but also crash risk", "score": 100},
        ]
        result = self.svc._score_posts(posts, frozenset({"bitcoin", "btc"}))
        self.assertEqual(result["sample_size"], 1)
        # post mentions both bull and bear keywords — both counted
        self.assertEqual(result["bullish_count"], 1)
        self.assertEqual(result["bearish_count"], 1)

    def test_compute_score_pure_bullish(self):
        score = self.svc._compute_score(10, 0, 10)
        self.assertAlmostEqual(score, 1.0)

    def test_compute_score_pure_bearish(self):
        score = self.svc._compute_score(0, 10, 10)
        self.assertAlmostEqual(score, -1.0)

    def test_compute_score_balanced(self):
        score = self.svc._compute_score(5, 5, 10)
        self.assertAlmostEqual(score, 0.0)

    def test_compute_score_no_data(self):
        score = self.svc._compute_score(0, 0, 0)
        self.assertAlmostEqual(score, 0.0)

    def test_compute_score_range(self):
        for bull in range(0, 11):
            bear = 10 - bull
            score = self.svc._compute_score(bull, bear, bull + bear)
            self.assertGreaterEqual(score, -1.0)
            self.assertLessEqual(score, 1.0)


# ---------------------------------------------------------------------------
# Tests intégration avec mock Reddit JSON
# ---------------------------------------------------------------------------

class TestFetchHotPosts(unittest.TestCase):

    def setUp(self):
        from backend.services import reddit_sentiment_service as svc
        self.svc = svc

    @patch("urllib.request.urlopen")
    def test_fetch_returns_posts(self, mock_urlopen):
        payload = _make_reddit_response([
            "BTC moon 🚀",
            "Bitcoin crash incoming",
            "ETH bull run starting",
        ])
        mock_urlopen.return_value = _make_mock_urlopen(payload)
        posts = self.svc._fetch_hot_posts("CryptoCurrency")
        self.assertIsNotNone(posts)
        self.assertEqual(len(posts), 3)
        # titles are lowercased
        self.assertIn("moon", posts[0]["title"])

    @patch("urllib.request.urlopen")
    def test_fetch_returns_none_on_429(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://reddit.com", code=429, msg="Too Many Requests",
            hdrs=None, fp=None,
        )
        posts = self.svc._fetch_hot_posts("CryptoCurrency")
        self.assertIsNone(posts)

    @patch("urllib.request.urlopen")
    def test_fetch_returns_none_on_network_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        posts = self.svc._fetch_hot_posts("Bitcoin")
        self.assertIsNone(posts)

    @patch("urllib.request.urlopen")
    def test_fetch_returns_none_on_invalid_json(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json at all"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        posts = self.svc._fetch_hot_posts("CryptoCurrency")
        self.assertIsNone(posts)


# ---------------------------------------------------------------------------
# Tests refresh_subreddit avec DB temporaire
# ---------------------------------------------------------------------------

class TestRefreshSubreddit(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = f"{self.tmpdir}/test_macro.db"
        import backend.services.reddit_sentiment_service as svc_mod
        self._orig_db = svc_mod._DB_PATH
        svc_mod._DB_PATH = self.db_path
        self.svc = svc_mod

    def tearDown(self):
        self.svc._DB_PATH = self._orig_db

    @patch("urllib.request.urlopen")
    def test_refresh_stores_score_in_db(self, mock_urlopen):
        payload = _make_reddit_response([
            "bitcoin to the moon pump",
            "btc bull run incoming buy",
            "bitcoin bearish crash dump",
        ])
        mock_urlopen.return_value = _make_mock_urlopen(payload)

        stats = self.svc.refresh_subreddit("Bitcoin")
        self.assertEqual(stats["ok"], 1)  # BTC/USD only on Bitcoin subreddit
        self.assertEqual(stats["fail"], 0)

        # Verify DB content
        con = sqlite3.connect(self.db_path)
        row = con.execute(
            "SELECT sentiment_score, bullish_count, bearish_count, sample_size "
            "FROM reddit_sentiment WHERE symbol='BTC/USD' AND subreddit='Bitcoin'"
        ).fetchone()
        con.close()
        self.assertIsNotNone(row)
        score, bull, bear, sample = row
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(sample, 1)

    @patch("urllib.request.urlopen")
    def test_refresh_fail_when_reddit_unreachable(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("offline")
        stats = self.svc.refresh_subreddit("Bitcoin")
        self.assertEqual(stats["ok"], 0)
        self.assertEqual(stats["fail"], 1)

    @patch("urllib.request.urlopen")
    def test_refresh_skips_subreddit_not_in_symbol_config(self, mock_urlopen):
        # ethtrader only covers ETH/USD, not BTC/USD
        payload = _make_reddit_response(["ethereum eth moon", "eth bull run"])
        mock_urlopen.return_value = _make_mock_urlopen(payload)
        stats = self.svc.refresh_subreddit("ethtrader")
        self.assertEqual(stats["ok"], 1)  # ETH/USD stored

        con = sqlite3.connect(self.db_path)
        row_btc = con.execute(
            "SELECT * FROM reddit_sentiment WHERE symbol='BTC/USD' AND subreddit='ethtrader'"
        ).fetchone()
        row_eth = con.execute(
            "SELECT * FROM reddit_sentiment WHERE symbol='ETH/USD' AND subreddit='ethtrader'"
        ).fetchone()
        con.close()
        self.assertIsNone(row_btc)
        self.assertIsNotNone(row_eth)


# ---------------------------------------------------------------------------
# Tests get_sentiment avec DB temporaire
# ---------------------------------------------------------------------------

class TestGetSentiment(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = f"{self.tmpdir}/test_macro.db"
        import backend.services.reddit_sentiment_service as svc_mod
        self._orig_db = svc_mod._DB_PATH
        svc_mod._DB_PATH = self.db_path
        self.svc = svc_mod

        # Initialiser le schéma
        con = sqlite3.connect(self.db_path)
        self.svc._ensure_schema(con)
        con.commit()
        con.close()

    def tearDown(self):
        self.svc._DB_PATH = self._orig_db

    def _insert_row(self, subreddit, symbol, score, bull, bear, sample, age_sec=0):
        fetched = (datetime.now(timezone.utc) - timedelta(seconds=age_sec)).isoformat()
        con = sqlite3.connect(self.db_path)
        con.execute(
            """INSERT OR REPLACE INTO reddit_sentiment
               (subreddit, symbol, sentiment_score, bullish_count, bearish_count, sample_size, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (subreddit, symbol, score, bull, bear, sample, fetched),
        )
        con.commit()
        con.close()

    def test_returns_none_for_unsupported_symbol(self):
        result = self.svc.get_sentiment("XAU/USD")
        self.assertIsNone(result)

    def test_returns_none_when_no_data(self):
        result = self.svc.get_sentiment("BTC/USD")
        self.assertIsNone(result)

    def test_returns_aggregated_score(self):
        self._insert_row("CryptoCurrency", "BTC/USD", 0.5, 5, 1, 6, age_sec=100)
        self._insert_row("Bitcoin", "BTC/USD", 0.3, 3, 1, 4, age_sec=200)
        result = self.svc.get_sentiment("BTC/USD")
        self.assertIsNotNone(result)
        self.assertIn("score", result)
        self.assertIn("bullish_count", result)
        self.assertIn("bearish_count", result)
        self.assertIn("sample_size", result)
        self.assertIn("is_fresh", result)
        # Totals sum correctly
        self.assertEqual(result["bullish_count"], 8)
        self.assertEqual(result["bearish_count"], 2)
        self.assertEqual(result["sample_size"], 10)
        # Score entre -1 et +1
        self.assertGreaterEqual(result["score"], -1.0)
        self.assertLessEqual(result["score"], 1.0)

    def test_fresh_flag_correct(self):
        self._insert_row("Bitcoin", "BTC/USD", 0.2, 2, 1, 3, age_sec=300)
        result = self.svc.get_sentiment("BTC/USD")
        self.assertTrue(result["is_fresh"])

    def test_stale_data_excluded(self):
        # Data périmée > 2h (7201s) → filtrée → None
        self._insert_row("Bitcoin", "BTC/USD", 0.5, 5, 0, 5, age_sec=7201)
        result = self.svc.get_sentiment("BTC/USD")
        self.assertIsNone(result)

    def test_eth_usd_supported(self):
        self._insert_row("CryptoCurrency", "ETH/USD", -0.4, 1, 5, 6, age_sec=100)
        self._insert_row("ethtrader", "ETH/USD", -0.6, 0, 6, 6, age_sec=200)
        result = self.svc.get_sentiment("ETH/USD")
        self.assertIsNotNone(result)
        self.assertLess(result["score"], 0)


if __name__ == "__main__":
    unittest.main()
