"""Alertes Telegram sur rafales de rejections auto-exec.

Tourne périodiquement (scheduler toutes les 5 min). Pour chaque
reason_code, compte les rejections sur la dernière heure ; si > seuil
(10 par défaut) ET pas d'alerte déjà envoyée sur ce code dans les
dernières 60 min, déclenche un message Telegram.

Évite de spammer : 1 alerte par code toutes les 60 min max.
"""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.services.rejection_service import REASON_LABELS_FR, _db_path, _ensure_schema

logger = logging.getLogger(__name__)

# Seuil : > N rejections du même code sur la dernière heure déclenche
RAFALE_THRESHOLD = 10
# Fenêtre de recherche
WINDOW_HOURS = 1
# Cooldown par code pour ne pas spammer Telegram
COOLDOWN_MINUTES = 60

# Reason codes silencieux : trackés dans signal_rejections pour traçabilité
# (RejectionsCard les rend) mais jamais d'alerte Telegram parce qu'ils
# reflètent un état calendaire / fonctionnel attendu, pas un incident.
# - market_closed : marché fermé week-end ou daily break — par design
SILENT_REASONS: frozenset[str] = frozenset({"market_closed"})

# État en mémoire : reason_code → last_alert_ts. Reset au reboot, peu grave.
_last_alert_at: dict[str, datetime] = {}


def _count_by_reason(since_iso: str, until_iso: str) -> dict[str, int]:
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        rows = c.execute(
            """
            SELECT reason_code, COUNT(*) AS cnt
              FROM signal_rejections
             WHERE created_at >= ? AND created_at <= ?
             GROUP BY reason_code
            """,
            (since_iso, until_iso),
        ).fetchall()
    return {r[0]: r[1] for r in rows}


def _format_message(reason_code: str, count: int, top_pairs: list[tuple[str, int]]) -> str:
    label = REASON_LABELS_FR.get(reason_code, reason_code)
    lines = [
        f"⚠️ *Rafale rejections* · `{reason_code}`",
        f"**{count}** ordres bloqués dans la dernière heure ({label}).",
    ]
    if top_pairs:
        pairs_str = " · ".join(f"{p}: {c}" for p, c in top_pairs[:5])
        lines.append(f"Top pairs : {pairs_str}")
    lines.append(f"\n→ Vérifier `/v2/cockpit` section RejectionsCard.")
    return "\n".join(lines)


def _top_pairs_for(reason_code: str, since_iso: str, until_iso: str) -> list[tuple[str, int]]:
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        rows = c.execute(
            """
            SELECT pair, COUNT(*) AS cnt
              FROM signal_rejections
             WHERE created_at >= ? AND created_at <= ?
               AND reason_code = ?
             GROUP BY pair
             ORDER BY cnt DESC
             LIMIT 5
            """,
            (since_iso, until_iso, reason_code),
        ).fetchall()
    return [(r[0] or "?", r[1]) for r in rows]


async def check_and_alert() -> dict[str, Any]:
    """Job scheduler : check les rafales, envoie un Telegram si besoin.

    Retourne un résumé pour les tests / debug. Best-effort : toute erreur
    est loggée, pas propagée (ne doit pas planter le scheduler).
    """
    try:
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=WINDOW_HOURS)

        counts = _count_by_reason(since.isoformat(), now.isoformat())
        alerts_sent: list[str] = []
        alerts_suppressed: list[str] = []
        alerts_skipped_silent: list[str] = []

        for reason, count in counts.items():
            if count < RAFALE_THRESHOLD:
                continue
            if reason in SILENT_REASONS:
                alerts_skipped_silent.append(reason)
                continue
            last = _last_alert_at.get(reason)
            if last and (now - last) < timedelta(minutes=COOLDOWN_MINUTES):
                alerts_suppressed.append(reason)
                continue

            # Rafale détectée hors cooldown → envoie
            top_pairs = _top_pairs_for(reason, since.isoformat(), now.isoformat())
            msg = _format_message(reason, count, top_pairs)

            try:
                from backend.services.telegram_service import send_text, is_configured
                if not is_configured():
                    logger.info(f"rejection_alerts: Telegram non configuré, skip {reason}")
                else:
                    await send_text(msg, parse_mode="Markdown")
                    _last_alert_at[reason] = now
                    alerts_sent.append(reason)
                    logger.warning(
                        f"rejection_alerts: rafale {reason} ({count}/h) — alert envoyée"
                    )
            except Exception as e:
                logger.warning(f"rejection_alerts: send failed pour {reason}: {e}")

        return {
            "checked_at": now.isoformat(),
            "counts": counts,
            "alerts_sent": alerts_sent,
            "alerts_suppressed_cooldown": alerts_suppressed,
            "alerts_skipped_silent": alerts_skipped_silent,
        }

    except Exception:
        logger.exception("rejection_alerts: erreur globale check_and_alert")
        return {"error": "crash, voir logs"}
