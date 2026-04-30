"""Historique persistant des rafales SL (pauses + resumes).

Logue chaque transition d'état du circuit breaker en SQLite pour permettre :
- Tuning des seuils watchdog avec vraies données (PAIR_THRESHOLD,
  RAFALE_QUIET_WINDOW_MIN, etc.)
- Analyse rétrospective : quelles pairs ont été paused, combien de temps,
  ratio smart_resume / force_resume
- Visualisation UI dans /v2/admin → card Watchdog → section Historique

Schéma minimaliste : 1 row par event (PAUSE_SET / RESUME). Pour reconstituer
une "session de pause", on join PAUSE_SET avec le RESUME suivant sur la
même pair par triggered_at.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _db_path() -> str:
    from backend.services.trade_log_service import _DB_PATH

    return str(_DB_PATH)


# ─── Schéma + migration ───────────────────────────────────────────────


def _ensure_schema() -> None:
    """Crée la table rafale_pause_history si elle n'existe pas."""
    with sqlite3.connect(_db_path()) as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS rafale_pause_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                scope TEXT NOT NULL,
                pair TEXT,
                reason TEXT,
                failed_pattern TEXT,
                failed_direction TEXT,
                triggered_at TEXT,
                resume_decision TEXT,
                duration_seconds INTEGER
            )
            """
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_rph_created ON rafale_pause_history(created_at DESC)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_rph_pair ON rafale_pause_history(pair)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_rph_event_type ON rafale_pause_history(event_type)"
        )


# ─── Logging des events (appelé depuis kill_switch / stop_loss_alerts) ───


def log_pause_set(
    scope: str,
    pair: str | None,
    reason: str,
    failed_pattern: str | None = None,
    failed_direction: str | None = None,
    triggered_at: str | None = None,
) -> None:
    """Logue un event PAUSE_SET. ``scope`` = 'pair' ou 'global'.

    Best-effort : tout error est silencieusement loggé pour ne pas casser
    le set_pair_rafale_pause / set_global_rafale_pause amont.
    """
    try:
        _ensure_schema()
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(_db_path()) as c:
            c.execute(
                """
                INSERT INTO rafale_pause_history
                    (created_at, event_type, scope, pair, reason,
                     failed_pattern, failed_direction, triggered_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (now, "PAUSE_SET", scope, pair, reason,
                 failed_pattern, failed_direction, triggered_at or now),
            )
    except Exception as e:
        logger.warning(f"rafale_history: log_pause_set failed: {e}")


def log_resume(
    scope: str,
    pair: str | None,
    decision: str,
    triggered_at: str | None,
    reason: str | None = None,
    failed_pattern: str | None = None,
) -> None:
    """Logue un event RESUME avec decision (SMART_RESUME / FORCE_RESUME / MANUAL).

    Calcule duration_seconds si triggered_at fourni.
    """
    try:
        _ensure_schema()
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        duration: int | None = None
        if triggered_at:
            try:
                start = datetime.fromisoformat(triggered_at)
                duration = max(0, int((now - start).total_seconds()))
            except Exception:
                duration = None

        with sqlite3.connect(_db_path()) as c:
            c.execute(
                """
                INSERT INTO rafale_pause_history
                    (created_at, event_type, scope, pair, reason,
                     failed_pattern, triggered_at, resume_decision,
                     duration_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (now_iso, "RESUME", scope, pair, reason,
                 failed_pattern, triggered_at, decision, duration),
            )
    except Exception as e:
        logger.warning(f"rafale_history: log_resume failed: {e}")


# ─── Queries pour l'UI / analytics ───────────────────────────────────


def list_recent_events(days: int = 7, limit: int = 100) -> list[dict[str, Any]]:
    """Retourne les events des N derniers jours, ordre antichronologique."""
    _ensure_schema()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with sqlite3.connect(_db_path()) as c:
        rows = c.execute(
            """
            SELECT id, created_at, event_type, scope, pair, reason,
                   failed_pattern, failed_direction, triggered_at,
                   resume_decision, duration_seconds
              FROM rafale_pause_history
             WHERE created_at >= ?
             ORDER BY created_at DESC
             LIMIT ?
            """,
            (since, limit),
        ).fetchall()
    return [
        {
            "id": r[0],
            "created_at": r[1],
            "event_type": r[2],
            "scope": r[3],
            "pair": r[4],
            "reason": r[5],
            "failed_pattern": r[6],
            "failed_direction": r[7],
            "triggered_at": r[8],
            "resume_decision": r[9],
            "duration_seconds": r[10],
        }
        for r in rows
    ]


def stats_for_window(days: int = 7) -> dict[str, Any]:
    """Stats agrégées : nb pauses, durée moyenne, distribution par pair,
    ratio smart_resume vs force_resume."""
    _ensure_schema()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    out: dict[str, Any] = {
        "window_days": days,
        "pause_set_count": 0,
        "resume_count": 0,
        "avg_duration_seconds": None,
        "max_duration_seconds": None,
        "by_pair": [],
        "by_decision": {},
    }
    with sqlite3.connect(_db_path()) as c:
        # Counts globaux
        out["pause_set_count"] = c.execute(
            "SELECT COUNT(*) FROM rafale_pause_history "
            "WHERE event_type=? AND created_at>=?",
            ("PAUSE_SET", since),
        ).fetchone()[0]

        out["resume_count"] = c.execute(
            "SELECT COUNT(*) FROM rafale_pause_history "
            "WHERE event_type=? AND created_at>=?",
            ("RESUME", since),
        ).fetchone()[0]

        # Durée moyenne / max sur les RESUME (qui ont duration)
        row = c.execute(
            """
            SELECT AVG(duration_seconds), MAX(duration_seconds)
              FROM rafale_pause_history
             WHERE event_type='RESUME'
               AND duration_seconds IS NOT NULL
               AND created_at>=?
            """,
            (since,),
        ).fetchone()
        if row and row[0] is not None:
            out["avg_duration_seconds"] = int(row[0])
            out["max_duration_seconds"] = int(row[1])

        # Distribution par pair (PAUSE_SET)
        rows = c.execute(
            """
            SELECT pair, COUNT(*) AS cnt
              FROM rafale_pause_history
             WHERE event_type='PAUSE_SET' AND scope='pair' AND created_at>=?
             GROUP BY pair ORDER BY cnt DESC
            """,
            (since,),
        ).fetchall()
        out["by_pair"] = [{"pair": r[0], "count": r[1]} for r in rows]

        # Distribution par decision (RESUME)
        rows2 = c.execute(
            """
            SELECT resume_decision, COUNT(*) AS cnt
              FROM rafale_pause_history
             WHERE event_type='RESUME' AND resume_decision IS NOT NULL
               AND created_at>=?
             GROUP BY resume_decision ORDER BY cnt DESC
            """,
            (since,),
        ).fetchall()
        out["by_decision"] = {r[0]: r[1] for r in rows2}

    return out
