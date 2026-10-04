"""Service calendrier économique — veto pre/post news HIGH impact.

Source : ForexFactory weekly XML feed (nfs.faireconomy.media).
Cache SQLite table ``economic_events``. Sync hebdo dimanche 20h UTC +
fallback jeudi 20h UTC.

## Utilisation principale

    from backend.services import economic_calendar_service as ec
    events = ec.get_upcoming_events(within_minutes=30, min_impact="High")

## Robustesse

Best-effort : si le fetch XML échoue, log warning + return [] sans jamais
bloquer le pipeline scoring. Le cache SQLite est conservé entre les restarts.

## Currencies couvertes

USD, EUR, GBP, JPY, CAD, AUD, CHF, NZD — les 8 majors forex.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ─── Chemins ────────────────────────────────────────────────────────────────
# Aligné sur _DB_PATH de trade_log_service (même répertoire data).
_DB_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_DB_PATH = _DB_DIR / "scalping.db"

# URL XML ForexFactory (format public, actualisation hebdomadaire).
# Alternative JSON (même source, même données) :
#   https://nfs.faireconomy.media/ff_calendar_thisweek.json
_FF_XML_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
_FF_JSON_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

_IMPACT_LEVELS = {"High", "Medium", "Low"}
_MAJOR_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "NZD"}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/xml, */*;q=0.8",
}

# ─── DB init ────────────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    """Ouvre (et crée si besoin) la table economic_events dans le DB SQLite partagé."""
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS economic_events (
            id          TEXT PRIMARY KEY,
            ts_utc      TEXT NOT NULL,
            currency    TEXT NOT NULL,
            event_name  TEXT NOT NULL,
            impact      TEXT NOT NULL,
            actual      TEXT,
            forecast    TEXT,
            previous    TEXT,
            fetched_at  TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_eco_ts ON economic_events(ts_utc)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_eco_impact ON economic_events(impact)")
    conn.commit()
    return conn


# ─── Parsing ────────────────────────────────────────────────────────────────

def _normalize_impact(raw: str) -> str:
    """Normalise le niveau d'impact → 'High' | 'Medium' | 'Low'."""
    r = (raw or "").strip().lower()
    if r in ("high", "red", "3"):
        return "High"
    if r in ("medium", "orange", "amber", "2"):
        return "Medium"
    return "Low"


def _parse_ff_json(data: list[dict]) -> list[dict]:
    """Parse la réponse JSON ForexFactory en liste de dicts normalisés."""
    events: list[dict] = []
    for item in data:
        try:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            currency = (item.get("country") or item.get("currency") or "").upper()
            if currency not in _MAJOR_CURRENCIES:
                continue
            impact = _normalize_impact(item.get("impact") or "")
            # date field : "2026-08-02T08:30:00-05:00" ou ISO avec Z
            date_str = item.get("date") or item.get("datetime") or ""
            if not date_str:
                continue
            try:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                ts_utc = dt.astimezone(timezone.utc).isoformat()
            except (ValueError, TypeError):
                continue
            # id déterministe : évite les doublons sur re-fetch
            event_id = f"{ts_utc}_{currency}_{title[:40]}"
            events.append({
                "id": event_id,
                "ts_utc": ts_utc,
                "currency": currency,
                "event_name": title,
                "impact": impact,
                "actual": item.get("actual") or None,
                "forecast": item.get("forecast") or None,
                "previous": item.get("previous") or None,
            })
        except Exception as e:
            logger.debug(f"economic_calendar: parse item error: {e}")
    return events


# ─── Fetch ──────────────────────────────────────────────────────────────────

def _fetch_json() -> Optional[list[dict]]:
    """Fetch synchrone du JSON ForexFactory. Retourne None si échec."""
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            resp = client.get(_FF_JSON_URL, headers=_HEADERS)
            resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            logger.warning(f"economic_calendar: JSON inattendu (type={type(data).__name__})")
            return None
        return data
    except Exception as e:
        logger.warning(f"economic_calendar: JSON fetch failed ({e})")
        return None


# ─── Public API ─────────────────────────────────────────────────────────────

def refresh_calendar() -> int:
    """Fetch le calendrier ForexFactory et met à jour le cache SQLite.

    Retourne le nombre d'événements stockés (0 si fetch échoue).
    Best-effort : ne lève jamais d'exception.
    """
    try:
        raw = _fetch_json()
        if not raw:
            logger.warning("economic_calendar: refresh skipped — source unavailable")
            return 0
        events = _parse_ff_json(raw)
        if not events:
            logger.warning("economic_calendar: refresh fetched 0 events")
            return 0
        fetched_at = datetime.now(timezone.utc).isoformat()
        with _get_db() as conn:
            # ⛔ ICI SE TROUVAIT UNE PURGE À 7 JOURS GLISSANTS, retirée le
            # 2026-10-04 sur demande de Xavier :
            #
            #     # Purge les événements passés de >7j pour garder la table légère
            #     conn.execute("DELETE FROM economic_events WHERE ts_utc < ?", ...)
            #
            # 🔑 Ce qu'elle effaçait, c'est l'ÉTIQUETTE, pas les prix. Les
            # bougies restent disponibles chez le courtier à la demande — M5
            # jusqu'au 2025-05-07, D1 jusqu'en avril 2021. Ce qui disparaissait,
            # c'est « ce jour-là à 12h30, publication de l'emploi américain,
            # consensus 9,0K, réel -41,7K ».
            #
            # Sans l'étiquette, une hypothèse événementielle est INÉPROUVABLE
            # rétroactivement. Xavier l'a formulé exactement : « si le pattern a
            # eu lieu il y a 3 semaines, comment on fait ? »
            #
            # ⚠️ Ce que la purge économisait, MESURÉ avant de la retirer :
            #
            #     220 lignes = 45 056 octets, soit 205 octets par ligne
            #     4 000 événements par an = 800 Ko/an
            #     la base entière pesait 88 Ko
            #
            # On détruisait un historique irremplaçable pour économiser moins
            # qu'une photo. Le motif « garder la table légère » était sincère —
            # ce projet a connu un disque à 97 % et un `backtest.db` qui grossit
            # de 0,6 Go par jour — mais il ne s'applique PAS ici, et personne
            # n'avait fait la division.
            #
            # ⛔ Ne pas la remettre. `test_calendrier_historique.py` la refuse,
            # par le comportement ET par la forme.
            #
            # ⚠️ `INSERT OR REPLACE` sur l'`id` reste indispensable : le champ
            # `actual` n'existe qu'APRÈS la publication, et doit remplacer le
            # `None` initial. Accumuler n'est pas doubler.
            # Upsert
            conn.executemany(
                """
                INSERT OR REPLACE INTO economic_events
                    (id, ts_utc, currency, event_name, impact, actual, forecast, previous, fetched_at)
                VALUES
                    (:id, :ts_utc, :currency, :event_name, :impact, :actual, :forecast, :previous, :fetched_at)
                """,
                [{**e, "fetched_at": fetched_at} for e in events],
            )
        logger.info(f"economic_calendar: refreshed {len(events)} events")
        return len(events)
    except Exception as e:
        logger.warning(f"economic_calendar: refresh error: {e}")
        return 0


def get_upcoming_events(
    within_minutes: int = 30,
    min_impact: str = "High",
    now: Optional[datetime] = None,
) -> list[dict]:
    """Retourne les events HIGH impact dans la fenêtre ±within_minutes autour de now.

    La fenêtre est bilatérale : events AVANT (dans les X min précédentes)
    ET APRÈS (dans les X min suivantes) — car la volatilité "surprise" peut
    persister après publication, et on veut éviter les SL pré-annonce.

    Parameters
    ----------
    within_minutes : int
        Demi-fenêtre en minutes (défaut 30 : ±30 min autour de now).
    min_impact : str
        Impact minimum à retourner ('High' | 'Medium' | 'Low'). Défaut 'High'.
    now : datetime | None
        Timestamp de référence (UTC). Si None, utilise datetime.now(UTC).

    Retourne une liste de dicts avec clés :
        id, ts_utc, currency, event_name, impact, actual, forecast, previous,
        minutes_delta (positif = futur, négatif = passé)
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Ordre de priorité des impacts
    _impact_rank = {"High": 3, "Medium": 2, "Low": 1}
    min_rank = _impact_rank.get(min_impact, 3)

    window_start = (now - timedelta(minutes=within_minutes)).isoformat()
    window_end = (now + timedelta(minutes=within_minutes)).isoformat()

    try:
        with _get_db() as conn:
            rows = conn.execute(
                """
                SELECT id, ts_utc, currency, event_name, impact,
                       actual, forecast, previous, fetched_at
                  FROM economic_events
                 WHERE ts_utc BETWEEN ? AND ?
                 ORDER BY ts_utc ASC
                """,
                (window_start, window_end),
            ).fetchall()
    except Exception as e:
        logger.warning(f"economic_calendar: get_upcoming_events DB error: {e}")
        return []

    result: list[dict] = []
    for row in rows:
        impact = row["impact"]
        if _impact_rank.get(impact, 0) < min_rank:
            continue
        try:
            ev_dt = datetime.fromisoformat(row["ts_utc"])
            minutes_delta = round((ev_dt - now).total_seconds() / 60, 1)
        except (ValueError, TypeError):
            minutes_delta = 0.0
        result.append({
            "id": row["id"],
            "ts_utc": row["ts_utc"],
            "currency": row["currency"],
            "event_name": row["event_name"],
            "impact": impact,
            "actual": row["actual"],
            "forecast": row["forecast"],
            "previous": row["previous"],
            "minutes_delta": minutes_delta,
        })

    return result
