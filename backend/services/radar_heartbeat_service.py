"""Heartbeat dédié pour les cycles d'analyse du radar.

Avant 2026-05-09 le bridge_monitor inférait l'état du radar via
``MAX(signal_rejections.created_at)``. Ce proxy générait des faux positifs
quand aucun setup n'était rejeté pendant > 15 min (sessions calmes,
TwelveData throttle, GDELT timeout) → le monitor déclenchait des
``systemctl restart scalping`` inutiles 1-4×/h, coupant les WebSocket
Telegram à chaque restart.

Ce module ajoute une table ``radar_cycle_heartbeat`` peuplée à la fin de
chaque cycle ``run_analysis_cycle()`` même quand 0 signal et 0 rejection
sont produits. Le bridge_monitor pointe désormais sur cette table avec un
seuil resserré (300s = 5 min, vs 1800s du proxy).

Cf. ``feedback_radar_cycle_probe_false_positives.md`` pour le contexte.
"""

import logging
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _db_path() -> str:
    from backend.services.trade_log_service import _DB_PATH
    return str(_DB_PATH)


def _ensure_schema() -> None:
    with sqlite3.connect(_db_path()) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS radar_cycle_heartbeat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cycle_started_at TEXT NOT NULL,
                cycle_completed_at TEXT NOT NULL,
                duration_ms INTEGER NOT NULL,
                signals_count INTEGER NOT NULL DEFAULT 0,
                setups_count INTEGER NOT NULL DEFAULT 0,
                error_message TEXT
            )
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_rch_completed
                ON radar_cycle_heartbeat(cycle_completed_at)
        """)


def record_cycle(
    started_at: datetime,
    signals_count: int = 0,
    setups_count: int = 0,
    error_message: str | None = None,
) -> None:
    """Insère une ligne de heartbeat à la fin d'un cycle d'analyse.

    Best-effort : toute erreur DB est loggée (warning) mais pas propagée.
    Le radar ne doit JAMAIS planter à cause du heartbeat.
    """
    try:
        completed_at = datetime.now(timezone.utc)
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        _ensure_schema()
        with sqlite3.connect(_db_path()) as c:
            c.execute(
                """
                INSERT INTO radar_cycle_heartbeat
                    (cycle_started_at, cycle_completed_at, duration_ms,
                     signals_count, setups_count, error_message)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    started_at.isoformat(),
                    completed_at.isoformat(),
                    duration_ms,
                    signals_count,
                    setups_count,
                    error_message,
                ),
            )
    except Exception as e:
        logger.warning("radar_heartbeat: record_cycle failed (non-bloquant): %s", e)


def trim_old_heartbeats(keep_days: int = 14) -> int:
    """Retention : garde keep_days jours de heartbeats. Retourne le count supprimé.

    À appeler depuis un job scheduler hebdo. Best-effort.
    """
    try:
        _ensure_schema()
        with sqlite3.connect(_db_path()) as c:
            cur = c.execute(
                """
                DELETE FROM radar_cycle_heartbeat
                WHERE cycle_completed_at < datetime('now', ?)
                """,
                (f"-{keep_days} days",),
            )
            return cur.rowcount
    except Exception as e:
        logger.warning("radar_heartbeat: trim failed: %s", e)
        return 0
