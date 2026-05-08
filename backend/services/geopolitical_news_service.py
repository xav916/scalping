"""GDELT 2.0 — sentiment géopolitique mondial pour le scoring marché.

Source unique : API GDELT Doc 2.0 publique (https://api.gdeltproject.org).
- Pas d'auth, pas de rate limit officiel — on tient 1 fetch/heure pour rester citoyen.
- Couvre >1M articles/jour, 65 langues, mise à jour tous les 15 min.
- Endpoint `mode=timelinetone` : avg tone des articles matching la query,
  binné par 15 min sur la fenêtre demandée. Tone ∈ [-100, +100], range
  pratique [-10, +10]. Négatif = tonalité négative (stress, peur).

Thèmes suivis (impact direct sur les indices/forex) :
- monetary    : Fed, BCE, BoE, taux directeurs, hawkish/dovish
- geopolitical: guerre, sanctions, conflits armés (Russie, Ukraine, Iran, Taiwan)
- energy      : OPEC, pétrole, supply, sanctions energy
- trade       : Chine, tariffs, semiconducteurs, US-China

Pour chaque thème :
- avg_tone sur 24h (moyenne pondérée par volume d'articles)
- volume total (nb articles indexés)
- stress_level : "calm" / "elevated" / "high" selon avg_tone

Intégration : **shadow only au démarrage**. Snapshot exposé via
`/api/geopolitical` et stocké en SQLite (`geopolitical_snapshots`) pour
analyse postérieure. Aucun impact sur le scoring tant que la corrélation
avec les retournements observés n'est pas validée sur 4-6 semaines.

Le service est défensif : toute erreur réseau/parsing → return None, jamais
d'exception qui casserait le scheduler.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)


GDELT_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"

# Thèmes : query GDELT (syntaxe DocAPI : OR/AND/parenthèses, "exact phrase").
# Garder les queries courtes — GDELT tronque au-delà de ~200 chars.
THEMES: dict[str, str] = {
    "monetary": (
        '(Fed OR FOMC OR Powell OR ECB OR Lagarde OR BoE) '
        '("rate hike" OR "rate cut" OR hawkish OR dovish OR inflation)'
    ),
    "geopolitical": (
        '(Ukraine OR Iran OR Taiwan) (war OR sanctions OR missile OR strike)'
    ),
    "energy": (
        '(OPEC OR "crude oil" OR "natural gas") '
        '(cut OR supply OR shortage OR sanctions OR pipeline)'
    ),
    "trade": (
        'China (tariff OR "trade war" OR sanctions OR semiconductor OR chips)'
    ),
}

# Seuils de classification du stress (avg_tone GDELT).
# Tone moyen mondial habituel ≈ -2 (les news négatives sont sur-représentées).
# Donc "calm" est centré autour de -2, pas 0.
_STRESS_THRESHOLDS = [
    (-5.0, "high"),       # tone < -5 → stress élevé (catastrophes, guerre, crash)
    (-3.0, "elevated"),   # -5 ≤ tone < -3 → tension notable
    (10.0, "calm"),       # ≥ -3 → bruit de fond habituel
]


@dataclass
class ThemeReading:
    """Lecture d'un thème sur la fenêtre fetchée."""
    theme: str
    avg_tone: float
    volume: int
    stress_level: str
    samples: int  # nb de bins timeline reçus


@dataclass
class GeopoliticalSnapshot:
    """Snapshot global cross-thèmes."""
    fetched_at: str
    timespan: str
    themes: dict[str, dict]  # theme name → asdict(ThemeReading)
    overall_stress: str
    overall_tone: float


_cache: Optional[GeopoliticalSnapshot] = None


def _classify_stress(avg_tone: float) -> str:
    for threshold, label in _STRESS_THRESHOLDS:
        if avg_tone < threshold:
            return label
    return "calm"


async def _fetch_theme_tone(
    client: httpx.AsyncClient, theme: str, query: str, timespan: str
) -> Optional[ThemeReading]:
    """Fetch avg tone sur `timespan` pour une query GDELT.

    Retry avec backoff exp sur HTTP 429 (GDELT throttle agressif sur burst).
    Retourne None si toutes les tentatives échouent ou si parsing échoue.
    """
    import asyncio
    params = {
        "query": query,
        "mode": "timelinetone",
        "timespan": timespan,
        "format": "json",
    }
    url = f"{GDELT_ENDPOINT}?{urlencode(params)}"

    r = None
    for attempt in range(3):
        try:
            r = await client.get(url, timeout=15.0)
        except Exception as e:
            logger.warning(f"geopolitical: {theme} fetch error: {e}")
            return None
        if r.status_code == 200:
            break
        if r.status_code == 429 and attempt < 2:
            await asyncio.sleep(3 * (2 ** attempt))  # 3s, 6s
            continue
        logger.warning(f"geopolitical: {theme} HTTP {r.status_code}")
        return None

    if r is None or r.status_code != 200:
        return None

    # GDELT renvoie parfois du HTML au lieu du JSON quand la query est mal
    # formée — on doit gérer le cas defensivement.
    try:
        data = r.json()
    except json.JSONDecodeError:
        logger.warning(f"geopolitical: {theme} non-JSON response")
        return None

    timeline = data.get("timeline", [])
    if not timeline or not isinstance(timeline, list):
        return None

    # GDELT timelinetone : timeline = [{"data": [{"date": ..., "value": tone}, ...]}]
    # On prend le premier dataset (mode tone n'en a qu'un).
    series = timeline[0].get("data", []) if timeline else []
    if not series:
        return None

    # Avg tone = moyenne simple sur les bins. Volume = nb de bins (proxy
    # de "intensité de couverture" ; pas le vrai count d'articles, mais
    # suffisant pour ranker).
    tones = []
    for bin_ in series:
        v = bin_.get("value")
        if v is not None:
            try:
                tones.append(float(v))
            except (ValueError, TypeError):
                pass

    if not tones:
        return None

    avg_tone = sum(tones) / len(tones)
    return ThemeReading(
        theme=theme,
        avg_tone=round(avg_tone, 2),
        volume=len(series),
        stress_level=_classify_stress(avg_tone),
        samples=len(tones),
    )


async def refresh_snapshot(timespan: str = "24h") -> Optional[GeopoliticalSnapshot]:
    """Refresh tous les thèmes séquentiellement avec backoff. Persiste + cache.

    `timespan` : format GDELT, ex `24h`, `12h`, `7d`. Default 24h pour
    capturer le cycle news complet sans sur-pondérer le bruit intraday.

    Pourquoi séquentiel : GDELT throttle dur les requêtes en burst (HTTP 429
    si 4 calls parallèles). 1.5s d'espacement = 4 thèmes en ~6s, sans 429.

    Retourne le snapshot fraîchement construit, ou None si **tous** les
    fetches ont échoué (dans ce cas le cache précédent est conservé).
    """
    global _cache

    import asyncio

    readings: dict[str, ThemeReading] = {}
    async with httpx.AsyncClient(headers={"User-Agent": "ScalpingRadar/1.0"}) as client:
        themes_list = list(THEMES.items())
        for idx, (theme, query) in enumerate(themes_list):
            reading = await _fetch_theme_tone(client, theme, query, timespan)
            if reading is not None:
                readings[theme] = reading
            if idx < len(themes_list) - 1:
                await asyncio.sleep(1.5)

    if not readings:
        logger.warning("geopolitical: refresh failed — all themes empty, keeping previous cache")
        return None

    # Stress global = stress max parmi les thèmes (le thème le plus
    # négatif drive l'attention). Tone global = moyenne simple.
    stress_rank = {"calm": 0, "elevated": 1, "high": 2}
    overall_stress = max(
        (r.stress_level for r in readings.values()),
        key=lambda s: stress_rank.get(s, 0),
    )
    overall_tone = round(
        sum(r.avg_tone for r in readings.values()) / len(readings), 2
    )

    snapshot = GeopoliticalSnapshot(
        fetched_at=datetime.now(timezone.utc).isoformat(),
        timespan=timespan,
        themes={t: asdict(r) for t, r in readings.items()},
        overall_stress=overall_stress,
        overall_tone=overall_tone,
    )

    _cache = snapshot
    _persist(snapshot)
    logger.info(
        f"geopolitical: refreshed — overall_tone={overall_tone} "
        f"stress={overall_stress} themes={len(readings)}/{len(THEMES)}"
    )
    return snapshot


def get_current() -> Optional[dict]:
    """Snapshot in-memory courant. None si refresh jamais réussi."""
    if _cache is None:
        return _load_latest_persisted()
    return asdict(_cache)


def is_high_stress() -> bool:
    """Raccourci pour les modules qui veulent juste savoir si on est en
    régime tendu (utile pour veto futur)."""
    snap = get_current()
    if not snap:
        return False
    return snap.get("overall_stress") == "high"


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
            CREATE TABLE IF NOT EXISTS geopolitical_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at TEXT NOT NULL,
                timespan TEXT NOT NULL,
                overall_tone REAL NOT NULL,
                overall_stress TEXT NOT NULL,
                themes_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_geopol_recorded
                ON geopolitical_snapshots(recorded_at);
        """)


def _persist(snapshot: GeopoliticalSnapshot) -> None:
    try:
        _init_schema()
        with _conn() as c:
            c.execute(
                "INSERT INTO geopolitical_snapshots "
                "(recorded_at, timespan, overall_tone, overall_stress, themes_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    snapshot.fetched_at,
                    snapshot.timespan,
                    snapshot.overall_tone,
                    snapshot.overall_stress,
                    json.dumps(snapshot.themes),
                ),
            )
    except Exception as e:
        logger.warning(f"geopolitical: persist failed: {e}")


def _load_latest_persisted() -> Optional[dict]:
    try:
        _init_schema()
        with _conn() as c:
            row = c.execute(
                "SELECT recorded_at, timespan, overall_tone, overall_stress, themes_json "
                "FROM geopolitical_snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
    except Exception as e:
        logger.debug(f"geopolitical: load_latest failed: {e}")
        return None
    if not row:
        return None
    try:
        themes = json.loads(row["themes_json"])
    except Exception:
        themes = {}
    return {
        "fetched_at": row["recorded_at"],
        "timespan": row["timespan"],
        "overall_tone": row["overall_tone"],
        "overall_stress": row["overall_stress"],
        "themes": themes,
    }
