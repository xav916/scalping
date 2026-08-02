"""Reddit sentiment scoring pour BTC/ETH — source de signal contrarien crypto.

P3 MVP (2026-08-03) : utilise le JSON public Reddit (hot.json, no auth requis
avec User-Agent) pour mesurer le sentiment des posts r/CryptoCurrency,
r/Bitcoin, r/ethtrader. Filtre contrarien : score fortement bearish sur Reddit
quand le marché pousse un BUY = signal d'épuisement retail.

## Logique

Mots-clés dans les titres de posts (top 50 hot par subreddit) :
- Bullish : "moon", "pump", "bull", "long", "buy", "rally", "ath", "breakout",
  "bullish", "surge", "skyrocket", "mooning"
- Bearish : "dump", "crash", "bear", "short", "sell", "rekt", "drop", "collapse",
  "bearish", "plunge", "correction", "bottom", "rug"

Score par symbol : (bullish_count - bearish_count) / total_mentions ∈ [-1, +1]
- > 0 = sentiment net bullish
- < 0 = sentiment net bearish

## Activation

Fetch horaire via scheduler. Cache SQLite table ``reddit_sentiment``
dans macro.db. Best-effort : si Reddit 429 ou fail, retourne None.

## Non-scope MVP

- Reddit API PRAW authentifiée (nécessite Reddit app registered — chantier futur)
- LLM sentiment analysis (nuance meilleure mais coût inference — keyword suffit)
- Autres subreddits (r/altcoin, r/CryptoMoonShots, r/SatoshiStreetBets)
- Comments top-level (titles suffisent pour MVP — plus stables, moins de spam)
"""
from __future__ import annotations

import json
import logging
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_DB_PATH = "/app/data/macro.db"
_CACHE_TTL_SEC = 60 * 60  # 1h — aligné cadence refresh scheduler
_USER_AGENT = "ScalpingRadar/1.0 (signal research; contact: admin@scalping-radar.online)"
_FETCH_TIMEOUT = 10  # secondes

# Subreddits par symbol
_SUBREDDITS_BTC = ["CryptoCurrency", "Bitcoin"]
_SUBREDDITS_ETH = ["CryptoCurrency", "ethtrader"]

# Mots-clés sentimentaux dans les titres (lowercase match)
_BULLISH_KEYWORDS = frozenset([
    "moon", "pump", "bull", "long", "buy", "rally", "ath", "breakout",
    "bullish", "surge", "skyrocket", "mooning", "uptrend", "green",
    "gains", "profit", "hodl", "accumulate", "dip buy", "support",
])
_BEARISH_KEYWORDS = frozenset([
    "dump", "crash", "bear", "short", "sell", "rekt", "drop", "collapse",
    "bearish", "plunge", "correction", "bottom", "rug", "scam", "fear",
    "panic", "loss", "downtrend", "red", "dump it", "sell off", "selloff",
])

# Mapping symbol → subreddits + termes de reconnaissance dans les posts
_SYMBOL_CONFIG: dict[str, dict[str, Any]] = {
    "BTC/USD": {
        "subreddits": _SUBREDDITS_BTC,
        "terms": {"bitcoin", "btc", "sat", "sats", "satoshi"},
    },
    "ETH/USD": {
        "subreddits": _SUBREDDITS_ETH,
        "terms": {"ethereum", "eth", "ether", "vitalik"},
    },
}

# Symbols supportés par ce service
SUPPORTED_SYMBOLS = frozenset(_SYMBOL_CONFIG.keys())


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS reddit_sentiment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subreddit TEXT NOT NULL,
            symbol TEXT NOT NULL,
            sentiment_score REAL NOT NULL,
            bullish_count INTEGER NOT NULL,
            bearish_count INTEGER NOT NULL,
            sample_size INTEGER NOT NULL,
            fetched_at TEXT NOT NULL,
            UNIQUE(subreddit, symbol)
        )
    """)
    con.commit()


def _fetch_hot_posts(subreddit: str) -> list[dict[str, Any]] | None:
    """Fetch les top 50 posts hot depuis Reddit JSON public.

    Retourne une liste de dicts {title, score} ou None si erreur.
    Reddit autorise le JSON public sans auth avec un User-Agent valide.
    """
    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit=50"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            raw = json.loads(resp.read())
        posts = raw.get("data", {}).get("children", [])
        return [
            {
                "title": p["data"].get("title", "").lower(),
                "score": p["data"].get("score", 0),
            }
            for p in posts
            if p.get("data")
        ]
    except urllib.error.HTTPError as e:
        if e.code == 429:
            logger.warning(f"reddit_sentiment: rate limited (429) on r/{subreddit}")
        else:
            logger.warning(f"reddit_sentiment: HTTP {e.code} on r/{subreddit}")
        return None
    except (urllib.error.URLError, json.JSONDecodeError, KeyError) as e:
        logger.warning(f"reddit_sentiment: fetch r/{subreddit} failed: {e}")
        return None


def _score_posts(posts: list[dict[str, Any]], symbol_terms: frozenset[str]) -> dict[str, int]:
    """Analyse les titres pour un symbol donné.

    Retourne {bullish_count, bearish_count, sample_size} sur les posts
    qui mentionnent le symbol.
    """
    bullish = 0
    bearish = 0
    relevant = 0

    for post in posts:
        title = post["title"]
        # Filtre : le post doit mentionner le symbol
        mentions_symbol = any(term in title for term in symbol_terms)
        if not mentions_symbol:
            continue
        relevant += 1
        has_bull = any(kw in title for kw in _BULLISH_KEYWORDS)
        has_bear = any(kw in title for kw in _BEARISH_KEYWORDS)
        if has_bull:
            bullish += 1
        if has_bear:
            bearish += 1

    return {
        "bullish_count": bullish,
        "bearish_count": bearish,
        "sample_size": relevant,
    }


def _compute_score(bullish: int, bearish: int, sample: int) -> float:
    """Score normalisé ∈ [-1, +1]. 0.0 si pas de données."""
    total = bullish + bearish
    if total == 0:
        return 0.0
    return round((bullish - bearish) / total, 4)


def refresh_subreddit(subreddit: str) -> dict[str, int]:
    """Fetch et stocke les scores sentiment pour les 2 symbols sur un subreddit.

    Retourne stats {ok, fail}.
    """
    posts = _fetch_hot_posts(subreddit)
    if posts is None:
        return {"ok": 0, "fail": 1}

    n_ok = 0
    n_fail = 0
    now = datetime.now(timezone.utc).isoformat()

    try:
        con = sqlite3.connect(_DB_PATH)
        _ensure_schema(con)
    except Exception as e:
        logger.error(f"reddit_sentiment: db connect failed: {e}")
        return {"ok": 0, "fail": 1}

    for symbol, cfg in _SYMBOL_CONFIG.items():
        # On n'analyse ce subreddit que s'il est dans la config du symbol
        if subreddit not in cfg["subreddits"]:
            continue
        try:
            counts = _score_posts(posts, frozenset(cfg["terms"]))
            score = _compute_score(
                counts["bullish_count"],
                counts["bearish_count"],
                counts["sample_size"],
            )
            con.execute(
                """
                INSERT OR REPLACE INTO reddit_sentiment
                    (subreddit, symbol, sentiment_score, bullish_count,
                     bearish_count, sample_size, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subreddit,
                    symbol,
                    score,
                    counts["bullish_count"],
                    counts["bearish_count"],
                    counts["sample_size"],
                    now,
                ),
            )
            n_ok += 1
            logger.debug(
                f"reddit_sentiment r/{subreddit} {symbol}: "
                f"score={score:.3f} bull={counts['bullish_count']} "
                f"bear={counts['bearish_count']} n={counts['sample_size']}"
            )
        except Exception as e:
            logger.warning(f"reddit_sentiment score {symbol} r/{subreddit}: {e}")
            n_fail += 1

    try:
        con.commit()
    finally:
        con.close()

    return {"ok": n_ok, "fail": n_fail}


def refresh_all() -> dict[str, int]:
    """Refresh sentiment pour tous les subreddits configurés.

    Appelé par le scheduler toutes les heures. Retourne stats agrégées.
    """
    all_subreddits: set[str] = set()
    for cfg in _SYMBOL_CONFIG.values():
        all_subreddits.update(cfg["subreddits"])

    total_ok = 0
    total_fail = 0
    for sub in sorted(all_subreddits):
        stats = refresh_subreddit(sub)
        total_ok += stats["ok"]
        total_fail += stats["fail"]

    logger.info(f"reddit_sentiment refresh_all: {total_ok} ok, {total_fail} fail")
    return {"ok": total_ok, "fail": total_fail}


def get_sentiment(symbol: str) -> dict[str, Any] | None:
    """Retourne le sentiment agrégé multi-subreddit pour un symbol.

    Agrégation : moyenne pondérée par sample_size des scores par subreddit.
    Retourne None si :
    - symbol non supporté
    - aucune donnée en cache
    - data périmée (> 2h, tolérance fail-safe)

    Dict retourné :
        score         : float [-1, +1]
        bullish_count : int (somme tous subreddits)
        bearish_count : int
        sample_size   : int
        fetched_at    : str ISO (la plus récente)
        age_sec       : float
        is_fresh      : bool (< 1h)
    """
    if symbol not in SUPPORTED_SYMBOLS:
        return None

    cfg = _SYMBOL_CONFIG[symbol]
    subreddits = cfg["subreddits"]

    try:
        con = sqlite3.connect(_DB_PATH)
        con.row_factory = sqlite3.Row
        _ensure_schema(con)
        placeholders = ",".join("?" * len(subreddits))
        rows = con.execute(
            f"""
            SELECT subreddit, sentiment_score, bullish_count, bearish_count,
                   sample_size, fetched_at
            FROM reddit_sentiment
            WHERE symbol = ? AND subreddit IN ({placeholders})
            """,
            [symbol] + list(subreddits),
        ).fetchall()
        con.close()
    except Exception as e:
        logger.warning(f"reddit_sentiment get_sentiment {symbol}: {e}")
        return None

    if not rows:
        return None

    # Agrégation pondérée par sample_size
    total_bull = 0
    total_bear = 0
    total_sample = 0
    weighted_score_sum = 0.0
    weight_total = 0.0
    latest_fetched: str | None = None

    now = datetime.now(timezone.utc)
    max_age = 2 * 3600  # tolérance 2h (fail-safe : données périmées neutres)

    for row in rows:
        fetched_at = datetime.fromisoformat(row["fetched_at"])
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        age = (now - fetched_at).total_seconds()
        if age > max_age:
            logger.debug(f"reddit_sentiment: {symbol} r/{row['subreddit']} stale ({age:.0f}s), skip")
            continue

        w = max(1, row["sample_size"])  # poids = taille échantillon (min 1)
        weighted_score_sum += row["sentiment_score"] * w
        weight_total += w
        total_bull += row["bullish_count"]
        total_bear += row["bearish_count"]
        total_sample += row["sample_size"]

        if latest_fetched is None or row["fetched_at"] > latest_fetched:
            latest_fetched = row["fetched_at"]

    if weight_total == 0 or latest_fetched is None:
        return None

    agg_score = round(weighted_score_sum / weight_total, 4)
    fetched_dt = datetime.fromisoformat(latest_fetched)
    if fetched_dt.tzinfo is None:
        fetched_dt = fetched_dt.replace(tzinfo=timezone.utc)
    age_sec = (now - fetched_dt).total_seconds()

    return {
        "score": agg_score,
        "bullish_count": total_bull,
        "bearish_count": total_bear,
        "sample_size": total_sample,
        "fetched_at": latest_fetched,
        "age_sec": round(age_sec),
        "is_fresh": age_sec < _CACHE_TTL_SEC,
    }
