"""Alertes Telegram + circuit breaker sur rafales de stops loss auto-exec.

Complément de ``rejection_alerts`` : ce dernier surveille les setups
**bloqués avant exécution** (kill_switch, sl_too_close, bridge_timeout, etc.).
Ce module-ci surveille les ordres **exécutés puis stoppés** — typiquement
un système qui rejoue la même mauvaise idée en boucle.

Cas qui a motivé ce watchdog (2026-04-30) : V1 a enchaîné 9 SL consécutifs
sur ``range_bounce_down`` short XAU/XAG en 5h. Aucune alerte rafale
existante ne s'est déclenchée car les ordres passaient les filtres
pré-exécution (les SL placés étaient acceptés par le broker, juste très
serrés). Cf. ``docs/superpowers/journal/2026-04-30-v1-drawdown-observation.md``.

## Comportements

Deux détections en parallèle, cooldowns indépendants :

- **Rafale globale** : ≥ ``GLOBAL_THRESHOLD`` SL auto-exec en ``WINDOW_HOURS`` h
  (toutes pairs/patterns confondus). Détecte une journée rouge.
- **Rafale par pattern** : ≥ ``PATTERN_THRESHOLD`` SL sur le même
  ``signal_pattern`` en ``WINDOW_HOURS`` h. Détecte un mode de défaillance
  pattern-spécifique (V1 qui rejoue la même idée).

## Circuit breaker (auto-pause + auto-resume)

Si ``RAFALE_AUTO_PAUSE_ENABLED=true`` (env), une rafale globale détectée
déclenche en plus ``kill_switch.set_rafale_pause()`` qui bloque l'envoi de
NOUVEAUX ordres au bridge MT5 pour ``RAFALE_PAUSE_DURATION_MIN`` minutes
(default 2h). Les trades ouverts continuent jusqu'à leur SL/TP.

À chaque cycle, ``consume_expired_rafale_pause()`` vérifie si une pause a
expiré ; si oui, l'auto-resume se matérialise (clear du flag) et un
Telegram de notification est envoyé.

Note : seules les **rafales globales** déclenchent l'auto-pause. Les
rafales par pattern envoient une alerte mais ne pausent pas (pour ne
pas geler le système au moindre cluster pattern-spécifique). Pour
bloquer un pattern précis sans tout couper, désactiver le pattern
manuellement.

Tourne périodiquement (scheduler 5 min). Tous les SL comptés sont issus
de trades ``is_auto=1`` (auto-exec) — les trades manuels ne déclenchent
pas d'alerte (l'humain est censé savoir ce qu'il fait).
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Seuil global : N SL auto-exec sur la fenêtre déclenche l'alerte
GLOBAL_THRESHOLD = 5
# Seuil par pattern : N SL même pattern sur la fenêtre déclenche l'alerte
PATTERN_THRESHOLD = 3
# Fenêtre de recherche
WINDOW_HOURS = 1
# Cooldown par type d'alerte (global / pattern_X) pour ne pas spammer
COOLDOWN_MINUTES = 30

# État en mémoire : alert_key → last_alert_ts. Reset au reboot, peu grave.
# Keys : "global" pour la rafale globale, "pattern:<name>" pour les rafales
# par pattern.
_last_alert_at: dict[str, datetime] = {}


def _db_path() -> str:
    from backend.services.trade_log_service import _DB_PATH

    return str(_DB_PATH)


def _fetch_recent_sl(since_iso: str, until_iso: str) -> list[dict[str, Any]]:
    """Retourne les trades auto-exec fermés en SL sur la fenêtre.

    Ne dépend pas de ``user_id`` : compte tous les SL (admin + futurs users
    Premium) car le watchdog protège l'infra globalement, pas un user
    spécifique. Si on veut un watchdog per-user plus tard, ajouter un
    paramètre ``user_id``.
    """
    with sqlite3.connect(_db_path()) as c:
        rows = c.execute(
            """
            SELECT id, pair, direction, signal_pattern, pnl, closed_at
              FROM personal_trades
             WHERE status = 'CLOSED'
               AND close_reason = 'SL'
               AND is_auto = 1
               AND closed_at >= ?
               AND closed_at <= ?
            """,
            (since_iso, until_iso),
        ).fetchall()
    return [
        {
            "id": r[0],
            "pair": r[1],
            "direction": r[2],
            "signal_pattern": r[3],
            "pnl": r[4],
            "closed_at": r[5],
        }
        for r in rows
    ]


def _format_global_message(sl_trades: list[dict[str, Any]]) -> str:
    count = len(sl_trades)
    total_pnl = sum(t.get("pnl") or 0.0 for t in sl_trades)

    # Top patterns / pairs pour donner un signal d'orientation
    by_pattern: dict[str, int] = {}
    by_pair: dict[str, int] = {}
    for t in sl_trades:
        p = t.get("signal_pattern") or "unknown"
        by_pattern[p] = by_pattern.get(p, 0) + 1
        pair = t.get("pair") or "?"
        by_pair[pair] = by_pair.get(pair, 0) + 1

    top_patterns = sorted(by_pattern.items(), key=lambda x: -x[1])[:3]
    top_pairs = sorted(by_pair.items(), key=lambda x: -x[1])[:3]

    lines = [
        "⚠️ *Rafale stops loss — global*",
        f"**{count}** SL auto-exec dans la dernière heure (PnL = {total_pnl:.2f}€).",
    ]
    if top_patterns:
        patterns_str = " · ".join(f"{p}: {c}" for p, c in top_patterns)
        lines.append(f"Top patterns : {patterns_str}")
    if top_pairs:
        pairs_str = " · ".join(f"{p}: {c}" for p, c in top_pairs)
        lines.append(f"Top pairs : {pairs_str}")
    lines.append("\n→ Vérifier que le système n'est pas en boucle. "
                 "Kill switch dispo via `/v2/admin → Auto-exec OFF`.")
    return "\n".join(lines)


def _format_pattern_message(pattern: str, sl_trades: list[dict[str, Any]]) -> str:
    count = len(sl_trades)
    total_pnl = sum(t.get("pnl") or 0.0 for t in sl_trades)

    by_pair: dict[str, int] = {}
    by_direction: dict[str, int] = {}
    for t in sl_trades:
        pair = t.get("pair") or "?"
        by_pair[pair] = by_pair.get(pair, 0) + 1
        direction = t.get("direction") or "?"
        by_direction[direction] = by_direction.get(direction, 0) + 1

    top_pairs = sorted(by_pair.items(), key=lambda x: -x[1])[:3]
    directions = " / ".join(f"{d}: {c}" for d, c in by_direction.items())

    lines = [
        f"⚠️ *Rafale stops loss — pattern* `{pattern}`",
        f"**{count}** SL sur ce pattern dans la dernière heure (PnL = {total_pnl:.2f}€).",
        f"Direction : {directions}",
    ]
    if top_pairs:
        pairs_str = " · ".join(f"{p}: {c}" for p, c in top_pairs)
        lines.append(f"Top pairs : {pairs_str}")
    lines.append(f"\n→ Le radar rejoue {pattern} en boucle. "
                 "Envisager désactiver ce pattern temporairement ou kill switch.")
    return "\n".join(lines)


async def _send_alert(key: str, msg: str, now: datetime) -> bool:
    """Envoie un message Telegram et marque le cooldown. Retourne True si envoyé."""
    try:
        from backend.services.telegram_service import is_configured, send_text

        if not is_configured():
            logger.info(f"stop_loss_alerts: Telegram non configuré, skip {key}")
            return False
        await send_text(msg, parse_mode="Markdown")
        _last_alert_at[key] = now
        logger.warning(f"stop_loss_alerts: rafale {key} — alert envoyée")
        return True
    except Exception as e:
        logger.warning(f"stop_loss_alerts: send failed pour {key}: {e}")
        return False


def _in_cooldown(key: str, now: datetime) -> bool:
    last = _last_alert_at.get(key)
    return bool(last and (now - last) < timedelta(minutes=COOLDOWN_MINUTES))


async def _maybe_auto_pause(reason: str, trigger_type: str) -> dict | None:
    """Active la pause kill_switch si activée par config. Retourne le state ou None."""
    try:
        from config.settings import RAFALE_AUTO_PAUSE_ENABLED, RAFALE_PAUSE_DURATION_MIN
    except Exception:
        return None

    if not RAFALE_AUTO_PAUSE_ENABLED:
        logger.info(f"stop_loss_alerts: auto-pause disabled, skip ({trigger_type})")
        return None

    try:
        from backend.services import kill_switch

        # Si déjà paused (rafale précédente non expirée), ne pas re-set pour
        # ne pas reset le timer expires_at à chaque cycle.
        already_paused, _info = kill_switch.is_rafale_paused()
        if already_paused:
            return None
        return kill_switch.set_rafale_pause(reason, RAFALE_PAUSE_DURATION_MIN, trigger_type)
    except Exception as e:
        logger.warning(f"stop_loss_alerts: auto-pause set failed: {e}")
        return None


async def _send_resume_notification(expired_info: dict, now: datetime) -> None:
    """Notifie Telegram qu'une pause auto a expiré et que l'auto-exec reprend."""
    try:
        triggered_at = expired_info.get("triggered_at", "?")
        trigger_type = expired_info.get("trigger_type", "?")
        reason = expired_info.get("reason", "?")
        msg = (
            "🔓 *Auto-resume — fin de pause rafale*\n"
            f"La pause déclenchée à {triggered_at} ({trigger_type}) a expiré.\n"
            f"Raison initiale : {reason}\n"
            "L'auto-exec MT5 reprend automatiquement. "
            "Surveiller les prochains trades — si la rafale revient, "
            "le watchdog re-déclenchera une pause."
        )
        from backend.services.telegram_service import is_configured, send_text
        if is_configured():
            await send_text(msg, parse_mode="Markdown")
            logger.warning(
                f"stop_loss_alerts: auto-resume notifié ({trigger_type})"
            )
    except Exception as e:
        logger.warning(f"stop_loss_alerts: resume notification failed: {e}")


async def check_and_alert() -> dict[str, Any]:
    """Job scheduler : check rafales SL global + par pattern, déclenche
    auto-pause + auto-resume, envoie Telegram.

    Best-effort : toute erreur est loggée, pas propagée (ne doit pas planter
    le scheduler).
    """
    try:
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=WINDOW_HOURS)

        sl_trades = _fetch_recent_sl(since.isoformat(), now.isoformat())
        total_count = len(sl_trades)

        alerts_sent: list[str] = []
        alerts_suppressed: list[str] = []
        auto_pause_set = False
        auto_resume_notified = False

        # --- Étape 0 : check si une pause a expiré → auto-resume + Telegram ---
        try:
            from backend.services import kill_switch
            expired_info = kill_switch.consume_expired_rafale_pause()
            if expired_info is not None:
                await _send_resume_notification(expired_info, now)
                auto_resume_notified = True
        except Exception as e:
            logger.warning(f"stop_loss_alerts: consume expired check failed: {e}")

        # --- Détection 1 : rafale globale ---
        if total_count >= GLOBAL_THRESHOLD:
            if _in_cooldown("global", now):
                alerts_suppressed.append("global")
            else:
                msg = _format_global_message(sl_trades)
                # Auto-pause AVANT l'envoi du message pour qu'on puisse
                # informer du status pause dans le même Telegram
                pause_state = await _maybe_auto_pause(
                    reason=f"{total_count} SL en {WINDOW_HOURS}h",
                    trigger_type="global",
                )
                if pause_state:
                    auto_pause_set = True
                    expires_at = pause_state.get("expires_at", "?")
                    msg += (
                        f"\n\n⛔ *AUTO-PAUSE activée* — auto-exec gelé jusqu'à {expires_at}. "
                        "Resume automatique."
                    )
                if await _send_alert("global", msg, now):
                    alerts_sent.append("global")

        # --- Détection 2 : rafale par pattern (alerte seule, pas de pause) ---
        by_pattern: dict[str, list[dict[str, Any]]] = {}
        for t in sl_trades:
            p = t.get("signal_pattern") or "unknown"
            by_pattern.setdefault(p, []).append(t)

        for pattern, trades in by_pattern.items():
            if len(trades) < PATTERN_THRESHOLD:
                continue
            key = f"pattern:{pattern}"
            if _in_cooldown(key, now):
                alerts_suppressed.append(key)
                continue
            msg = _format_pattern_message(pattern, trades)
            if await _send_alert(key, msg, now):
                alerts_sent.append(key)

        return {
            "checked_at": now.isoformat(),
            "total_sl_count": total_count,
            "by_pattern_counts": {p: len(trades) for p, trades in by_pattern.items()},
            "alerts_sent": alerts_sent,
            "alerts_suppressed_cooldown": alerts_suppressed,
            "auto_pause_set": auto_pause_set,
            "auto_resume_notified": auto_resume_notified,
        }

    except Exception:
        logger.exception("stop_loss_alerts: erreur globale check_and_alert")
        return {"error": "crash, voir logs"}
