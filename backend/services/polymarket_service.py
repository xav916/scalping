"""Polymarket — probabilités chiffrées sur événements géopolitiques/macro.

Source : Polymarket Gamma API (https://gamma-api.polymarket.com/markets).
- Pas d'auth, pas de rate limit officiel — on tient 1 fetch / 5 min.
- Marché de prédiction le plus liquide au monde (~$1B+ volume cumulé).
- Skin in the game : un trader pose son argent, donc le prix = probabilité
  perçue par les traders, pas le bruit news.

Ce que ça apporte vs GDELT :
- GDELT mesure le BRUIT (volume + tonalité de la couverture)
- Polymarket mesure l'OUTCOME ANTICIPÉ (probabilité chiffrée 0-100%)

Thèmes suivis (impact sur indices/forex/crypto) :
- monetary    : Fed, FOMC, taux, inflation
- geopolitical: Russie/Ukraine/Iran/Taïwan, sanctions, peace deals
- economy     : récession, GDP, unemployment
- crypto      : BTC/ETH price targets
- politics    : Trump, élections, impeachment

Pour chaque thème :
- Top 5 marchés par volume24h
- yes_prob = prix actuel du "Yes" (= probabilité 0..1)
- end_date pour filtrer les événements imminents

Intégration : **shadow only au démarrage**. Snapshot exposé via
`/api/polymarket` et stocké dans SQLite (`polymarket_snapshots`).
Aucun impact sur le scoring tant que la corrélation avec les
retournements observés n'est pas validée sur 4-6 semaines.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


GAMMA_ENDPOINT = "https://gamma-api.polymarket.com/markets"

# Keyword matching sur la question — Polymarket n'expose pas de catégories
# stables via l'API. Matching case-insensitive substring.
THEMES: dict[str, list[str]] = {
    "monetary": [
        "fed ", "fomc", "powell", "ecb", "lagarde",
        "rate cut", "rate hike", "interest rate", "inflation", "cpi report",
    ],
    "geopolitical": [
        "russia", "ukraine", "iran", "israel", "taiwan", "north korea",
        "syria", "houthis", "hormuz", "ceasefire", "peace deal", "sanctions",
    ],
    "economy": [
        "recession", " gdp ", "unemployment", "jobs report", "nfp",
        "non-farm", "labor market",
        # v2026-06-11 : tariff/trade war = repricing macro direct.
        # Le veto TARIFF du veto géopolitique scanne ce thème.
        "tariff", "trade war", "trade deal",
    ],
    "crypto": [
        "bitcoin", "btc ", "$100k", "$150k", "$200k", "$1m",
        "ethereum", "eth ", "solana", "sol ",
    ],
    "politics": [
        "trump", "biden", "harris", "election ", "president",
        "impeach", "congress",
        # v2026-06-11 : tariff = policy decision → politique. Coverage redondante
        # avec economy mais permet aux marchés "Trump tariff X by Y" d'apparaître
        # dans le top 5 politics même quand non détectés sous economy.
        "tariff", "trade war",
    ],
}

# Combien de marchés on garde par thème (top par volume24h).
TOP_PER_THEME = 5

# Combien de marchés actifs on fetch au total avant filtering.
FETCH_LIMIT = 200


@dataclass
class MarketReading:
    question: str
    slug: str                # market slug — pour dedup interne
    event_slug: Optional[str]  # slug de l'event parent — utilisé par le deep-link frontend
    yes_prob: float          # 0..1, prix du "Yes" (ou première outcome)
    no_prob: float           # 0..1, prix du "No" (1 - yes pour binaires)
    volume_24h: float        # USD
    liquidity: float         # USD (ordres ouverts)
    end_date: Optional[str]
    matched_themes: list[str] = field(default_factory=list)


@dataclass
class PolymarketSnapshot:
    fetched_at: str
    n_total_fetched: int
    n_matched: int
    themes: dict[str, list[dict]]    # theme → list of MarketReading.asdict()
    top_volume: list[dict]           # global top 5 by volume, all themes mixed


_cache: Optional[PolymarketSnapshot] = None


def _parse_yes_prob(outcomes_raw: str | list, prices_raw: str | list) -> Optional[tuple[float, float]]:
    """Extract (yes_prob, no_prob) d'une paire (outcomes, outcomePrices).

    Polymarket renvoie des JSON-strings ou listes. Pour les marchés non-binaires
    (>2 outcomes), on retourne None pour éviter de mal interpréter.
    """
    try:
        outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(outcomes, list) or not isinstance(prices, list):
        return None
    if len(outcomes) != 2 or len(prices) != 2:
        # Skip multi-outcome markets (e.g. "Next PM of X")
        return None

    try:
        # Convention Polymarket : ["Yes", "No"] ou ["Up", "Down"]
        yes_prob = float(prices[0])
        no_prob = float(prices[1])
    except (ValueError, TypeError):
        return None

    return yes_prob, no_prob


def _match_themes(question: str) -> list[str]:
    q = question.lower()
    matched = []
    for theme, keywords in THEMES.items():
        for kw in keywords:
            if kw in q:
                matched.append(theme)
                break  # 1 keyword suffit pour matcher le thème
    return matched


async def refresh_snapshot() -> Optional[PolymarketSnapshot]:
    """Fetch top FETCH_LIMIT marchés actifs par volume24h, filtre par thèmes,
    persiste un snapshot. Retourne None si fetch raté.
    """
    global _cache

    params = {
        "closed": "false",
        "active": "true",
        "limit": FETCH_LIMIT,
        "order": "volume24hr",
        "ascending": "false",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(GAMMA_ENDPOINT, params=params)
    except Exception as e:
        logger.warning(f"polymarket: fetch error: {e}")
        return None

    if r.status_code != 200:
        logger.warning(f"polymarket: HTTP {r.status_code}")
        return None

    try:
        data = r.json()
    except json.JSONDecodeError:
        logger.warning("polymarket: non-JSON response")
        return None

    if not isinstance(data, list):
        logger.warning("polymarket: unexpected payload (not a list)")
        return None

    # Filter + parse
    by_theme: dict[str, list[MarketReading]] = {t: [] for t in THEMES}
    matched_total: list[MarketReading] = []

    for m in data:
        question = m.get("question") or ""
        if not question:
            continue

        themes = _match_themes(question)
        if not themes:
            continue

        parsed = _parse_yes_prob(m.get("outcomes"), m.get("outcomePrices"))
        if parsed is None:
            continue
        yes_prob, no_prob = parsed

        try:
            volume_24h = float(m.get("volume24hr") or 0)
            liquidity = float(m.get("liquidity") or 0)
        except (ValueError, TypeError):
            continue

        # Skip marchés avec très peu de volume — bruit
        if volume_24h < 1000:
            continue

        # Le deep-link Polymarket /event/<slug> attend le slug de l'event
        # parent, pas du market lui-même. Un market peut être attaché à
        # plusieurs events ; on prend le premier (best-effort).
        events_raw = m.get("events") or []
        event_slug = None
        if isinstance(events_raw, list) and events_raw:
            first = events_raw[0]
            if isinstance(first, dict):
                event_slug = first.get("slug") or None

        reading = MarketReading(
            question=question[:140],
            slug=m.get("slug") or "",
            event_slug=event_slug,
            yes_prob=round(yes_prob, 3),
            no_prob=round(no_prob, 3),
            volume_24h=round(volume_24h, 0),
            liquidity=round(liquidity, 0),
            end_date=(m.get("endDate") or "")[:10] or None,
            matched_themes=themes,
        )
        matched_total.append(reading)
        for t in themes:
            by_theme[t].append(reading)

    # Trier chaque thème par volume desc et garder top N
    themes_out: dict[str, list[dict]] = {}
    for t, items in by_theme.items():
        items.sort(key=lambda x: x.volume_24h, reverse=True)
        themes_out[t] = [asdict(r) for r in items[:TOP_PER_THEME]]

    # Top volume global (cross-thèmes), dedup par slug
    matched_total.sort(key=lambda x: x.volume_24h, reverse=True)
    seen: set[str] = set()
    top_global: list[dict] = []
    for r in matched_total:
        if r.slug in seen:
            continue
        seen.add(r.slug)
        top_global.append(asdict(r))
        if len(top_global) >= 5:
            break

    snapshot = PolymarketSnapshot(
        fetched_at=datetime.now(timezone.utc).isoformat(),
        n_total_fetched=len(data),
        n_matched=len(matched_total),
        themes=themes_out,
        top_volume=top_global,
    )

    _cache = snapshot
    _persist(snapshot)
    logger.info(
        f"polymarket: refreshed — {len(data)} markets fetched, "
        f"{len(matched_total)} matched ({sum(len(v) for v in themes_out.values())} kept)"
    )
    return snapshot


def get_current() -> Optional[dict]:
    if _cache is None:
        return _load_latest_persisted()
    return asdict(_cache)


# --- Persistence (SQLite) ---------------------------------------------------


def _db_path() -> Path:
    from backend.services.trade_log_service import _DB_PATH
    return _DB_PATH


@contextmanager
def _conn():
    conn = sqlite3.connect(str(_db_path()), isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _init_schema() -> None:
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS polymarket_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at TEXT NOT NULL,
                n_matched INTEGER NOT NULL,
                themes_json TEXT NOT NULL,
                top_volume_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_polymarket_recorded
                ON polymarket_snapshots(recorded_at);
        """)


def _persist(snap: PolymarketSnapshot) -> None:
    try:
        _init_schema()
        with _conn() as c:
            c.execute(
                "INSERT INTO polymarket_snapshots "
                "(recorded_at, n_matched, themes_json, top_volume_json) "
                "VALUES (?, ?, ?, ?)",
                (
                    snap.fetched_at,
                    snap.n_matched,
                    json.dumps(snap.themes),
                    json.dumps(snap.top_volume),
                ),
            )
    except Exception as e:
        logger.warning(f"polymarket: persist failed: {e}")


def _load_latest_persisted() -> Optional[dict]:
    try:
        _init_schema()
        with _conn() as c:
            row = c.execute(
                "SELECT recorded_at, n_matched, themes_json, top_volume_json "
                "FROM polymarket_snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
    except Exception as e:
        logger.debug(f"polymarket: load_latest failed: {e}")
        return None
    if not row:
        return None
    try:
        themes = json.loads(row["themes_json"])
        top_volume = json.loads(row["top_volume_json"])
    except Exception:
        themes = {}
        top_volume = []
    return {
        "fetched_at": row["recorded_at"],
        "n_total_fetched": 0,
        "n_matched": row["n_matched"],
        "themes": themes,
        "top_volume": top_volume,
    }
