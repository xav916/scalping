"""Alertes Telegram + circuit breaker per-pair sur rafales de stops loss.

Complément de ``rejection_alerts`` : ce dernier surveille les setups
**bloqués avant exécution**. Ce module-ci surveille les ordres
**exécutés puis stoppés** — typiquement un système qui rejoue la même
mauvaise idée en boucle sur un instrument.

Cas qui a motivé ce watchdog (2026-04-30) : V1 a enchaîné 9 SL consécutifs
sur ``range_bounce_down`` short XAU/XAG en 5h. Cf. journal
``2026-04-30-v1-drawdown-observation.md``.

## Détections (3 niveaux)

- **Rafale par pair** : ≥ ``PAIR_THRESHOLD`` SL auto-exec sur **la même pair**
  en ``WINDOW_HOURS`` h. Action : **pause cette pair seule** pour
  ``RAFALE_PAUSE_DURATION_MIN`` minutes (auto-resume). Les autres pairs
  continuent à trader. C'est le mode chirurgical par défaut.
- **Rafale globale (filet de sécurité)** : ≥ ``GLOBAL_THRESHOLD`` SL auto-exec
  toutes pairs confondues en ``WINDOW_HOURS`` h. Action : **pause TOUT**
  l'auto-exec. Pour incident systémique majeur (ex: bug global de scoring,
  régime de marché qui casse partout).
- **Rafale par pattern** : ≥ ``PATTERN_THRESHOLD`` SL sur le même
  ``signal_pattern`` en ``WINDOW_HOURS`` h. Action : **alerte Telegram seule**,
  pas de pause. Sert de signal informatif pour décider manuellement de
  désactiver un pattern.

## Auto-pause / auto-resume

Si ``RAFALE_AUTO_PAUSE_ENABLED=true`` (env, default true), les rafales par
pair et globale déclenchent les pauses kill_switch. À chaque cycle, les
pauses expirées sont auto-clearées via ``consume_expired_*`` et un
Telegram resume est envoyé.

## Précisions

- Trades ouverts : continuent jusqu'à leur SL/TP naturel pendant la pause
  (pas de fermeture forcée — éviterait de figer une perte ouverte).
- Idempotence : si une pair est déjà paused, le timer ne se reset pas
  à chaque cycle (évite de prolonger indéfiniment sur cluster persistant).
- Manual trades (``is_auto=0``) ignorés : l'humain est censé savoir.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Seuils de détection
PAIR_THRESHOLD = 3       # ≥ 3 SL même pair en 1h → pause cette pair
GLOBAL_THRESHOLD = 10    # ≥ 10 SL toutes pairs en 1h → pause GLOBAL (filet)
PATTERN_THRESHOLD = 3    # ≥ 3 SL même pattern en 1h → Telegram seul

# Fenêtre de recherche
WINDOW_HOURS = 1
# Cooldown par type d'alerte pour ne pas spammer
COOLDOWN_MINUTES = 30

# État en mémoire : alert_key → last_alert_ts. Reset au reboot, peu grave.
# Keys : "global", "pair:<name>", "pattern:<name>"
_last_alert_at: dict[str, datetime] = {}


def _db_path() -> str:
    from backend.services.trade_log_service import _DB_PATH

    return str(_DB_PATH)


def _fetch_recent_sl(since_iso: str, until_iso: str) -> list[dict[str, Any]]:
    """Retourne les trades auto-exec fermés en SL sur la fenêtre."""
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


# ─── Format messages ────────────────────────────────────────────────────


def _format_global_message(sl_trades: list[dict[str, Any]]) -> str:
    count = len(sl_trades)
    total_pnl = sum(t.get("pnl") or 0.0 for t in sl_trades)

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
        "🚨 *RAFALE GLOBALE — incident systémique*",
        f"**{count}** SL auto-exec dans la dernière heure (PnL = {total_pnl:.2f}€).",
    ]
    if top_patterns:
        lines.append("Top patterns : " + " · ".join(f"{p}: {c}" for p, c in top_patterns))
    if top_pairs:
        lines.append("Top pairs : " + " · ".join(f"{p}: {c}" for p, c in top_pairs))
    lines.append("\n→ Système globalement défaillant. Vérifier infra + scoring.")
    return "\n".join(lines)


def _format_pair_message(pair: str, sl_trades: list[dict[str, Any]]) -> str:
    count = len(sl_trades)
    total_pnl = sum(t.get("pnl") or 0.0 for t in sl_trades)

    by_pattern: dict[str, int] = {}
    by_direction: dict[str, int] = {}
    for t in sl_trades:
        p = t.get("signal_pattern") or "unknown"
        by_pattern[p] = by_pattern.get(p, 0) + 1
        direction = t.get("direction") or "?"
        by_direction[direction] = by_direction.get(direction, 0) + 1

    directions = " / ".join(f"{d}: {c}" for d, c in by_direction.items())
    top_patterns = sorted(by_pattern.items(), key=lambda x: -x[1])[:3]

    lines = [
        f"⚠️ *Rafale stops loss — {pair}*",
        f"**{count}** SL sur {pair} dans la dernière heure (PnL = {total_pnl:.2f}€).",
        f"Direction : {directions}",
    ]
    if top_patterns:
        lines.append("Patterns : " + " · ".join(f"{p}: {c}" for p, c in top_patterns))
    return "\n".join(lines)


def _format_pattern_message(pattern: str, sl_trades: list[dict[str, Any]]) -> str:
    count = len(sl_trades)
    total_pnl = sum(t.get("pnl") or 0.0 for t in sl_trades)

    by_pair: dict[str, int] = {}
    for t in sl_trades:
        pair = t.get("pair") or "?"
        by_pair[pair] = by_pair.get(pair, 0) + 1
    top_pairs = sorted(by_pair.items(), key=lambda x: -x[1])[:3]

    lines = [
        f"📢 *Pattern défaillant* `{pattern}`",
        f"**{count}** SL sur ce pattern dans la dernière heure (PnL = {total_pnl:.2f}€).",
    ]
    if top_pairs:
        lines.append("Top pairs : " + " · ".join(f"{p}: {c}" for p, c in top_pairs))
    lines.append("\nℹ️ Info seulement (pas de pause). Si récurrent, désactiver le pattern.")
    return "\n".join(lines)


# ─── Telegram + cooldown helpers ────────────────────────────────────────


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


# ─── Auto-pause helpers ─────────────────────────────────────────────────


def _pause_enabled() -> tuple[bool, int]:
    """Read env via config.settings (rafale_auto_pause_enabled, duration_min)."""
    try:
        from config.settings import RAFALE_AUTO_PAUSE_ENABLED, RAFALE_PAUSE_DURATION_MIN
        return bool(RAFALE_AUTO_PAUSE_ENABLED), int(RAFALE_PAUSE_DURATION_MIN)
    except Exception:
        return False, 120


def _maybe_set_pair_pause(pair: str, reason: str) -> dict | None:
    enabled, duration_min = _pause_enabled()
    if not enabled:
        return None
    try:
        from backend.services import kill_switch
        already, _ = kill_switch.is_pair_rafale_paused(pair)
        if already:
            return None  # idempotent
        return kill_switch.set_pair_rafale_pause(pair, reason, duration_min)
    except Exception as e:
        logger.warning(f"stop_loss_alerts: pair pause set failed for {pair}: {e}")
        return None


def _maybe_set_global_pause(reason: str) -> dict | None:
    enabled, duration_min = _pause_enabled()
    if not enabled:
        return None
    try:
        from backend.services import kill_switch
        already, _ = kill_switch.is_global_rafale_paused()
        if already:
            return None
        return kill_switch.set_global_rafale_pause(reason, duration_min)
    except Exception as e:
        logger.warning(f"stop_loss_alerts: global pause set failed: {e}")
        return None


# ─── Resume notifications ───────────────────────────────────────────────


async def _send_pair_resume_notification(pair: str, info: dict) -> None:
    triggered_at = info.get("triggered_at", "?")
    reason = info.get("reason", "?")
    msg = (
        f"🔓 *Auto-resume — {pair}*\n"
        f"La pause sur {pair} déclenchée à {triggered_at} a expiré.\n"
        f"Raison initiale : {reason}\n"
        f"L'auto-exec MT5 reprend pour {pair}. Les autres pairs n'ont pas été affectées."
    )
    try:
        from backend.services.telegram_service import is_configured, send_text
        if is_configured():
            await send_text(msg, parse_mode="Markdown")
            logger.warning(f"stop_loss_alerts: pair auto-resume notifié {pair}")
    except Exception as e:
        logger.warning(f"stop_loss_alerts: pair resume notification failed: {e}")


async def _send_global_resume_notification(info: dict) -> None:
    triggered_at = info.get("triggered_at", "?")
    reason = info.get("reason", "?")
    msg = (
        "🔓 *Auto-resume — pause GLOBALE expirée*\n"
        f"La pause globale déclenchée à {triggered_at} a expiré.\n"
        f"Raison initiale : {reason}\n"
        "L'auto-exec MT5 reprend sur toutes les pairs. "
        "Surveiller les prochains trades — si la rafale revient, "
        "le watchdog re-déclenchera une pause."
    )
    try:
        from backend.services.telegram_service import is_configured, send_text
        if is_configured():
            await send_text(msg, parse_mode="Markdown")
            logger.warning("stop_loss_alerts: global auto-resume notifié")
    except Exception as e:
        logger.warning(f"stop_loss_alerts: global resume notification failed: {e}")


# ─── Main scheduler entry point ─────────────────────────────────────────


async def check_and_alert() -> dict[str, Any]:
    """Job scheduler : check rafales + déclenche pause/resume + Telegram.

    Best-effort : toute erreur est loggée, pas propagée.
    """
    try:
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=WINDOW_HOURS)

        sl_trades = _fetch_recent_sl(since.isoformat(), now.isoformat())
        total_count = len(sl_trades)

        alerts_sent: list[str] = []
        alerts_suppressed: list[str] = []
        pairs_paused: list[str] = []
        pairs_resumed: list[str] = []
        global_pause_set = False
        global_pause_resumed = False

        # ─ Étape 0 : check expirations → auto-resume + Telegram ─
        try:
            from backend.services import kill_switch

            expired_global = kill_switch.consume_expired_global_rafale_pause()
            if expired_global:
                await _send_global_resume_notification(expired_global)
                global_pause_resumed = True

            expired_pairs = kill_switch.consume_expired_pair_rafale_pauses()
            for pair, info in expired_pairs.items():
                await _send_pair_resume_notification(pair, info)
                pairs_resumed.append(pair)
        except Exception as e:
            logger.warning(f"stop_loss_alerts: consume expired check failed: {e}")

        # ─ Group by pair / pattern ─
        by_pair: dict[str, list[dict[str, Any]]] = {}
        by_pattern: dict[str, list[dict[str, Any]]] = {}
        for t in sl_trades:
            pair = t.get("pair") or "?"
            by_pair.setdefault(pair, []).append(t)
            p = t.get("signal_pattern") or "unknown"
            by_pattern.setdefault(p, []).append(t)

        # ─ Détection 1 : rafale par PAIR (chirurgical) ─
        for pair, trades in by_pair.items():
            if len(trades) < PAIR_THRESHOLD:
                continue
            key = f"pair:{pair}"
            if _in_cooldown(key, now):
                alerts_suppressed.append(key)
                continue
            msg = _format_pair_message(pair, trades)
            pause_state = _maybe_set_pair_pause(
                pair=pair,
                reason=f"{len(trades)} SL en {WINDOW_HOURS}h",
            )
            if pause_state:
                pairs_paused.append(pair)
                expires_at = pause_state.get("expires_at", "?")
                msg += (
                    f"\n\n⛔ *AUTO-PAUSE {pair}* jusqu'à {expires_at}.\n"
                    "Les autres pairs continuent à trader. Resume automatique."
                )
            if await _send_alert(key, msg, now):
                alerts_sent.append(key)

        # ─ Détection 2 : rafale GLOBALE (filet de sécurité) ─
        if total_count >= GLOBAL_THRESHOLD:
            if _in_cooldown("global", now):
                alerts_suppressed.append("global")
            else:
                msg = _format_global_message(sl_trades)
                pause_state = _maybe_set_global_pause(
                    reason=f"{total_count} SL en {WINDOW_HOURS}h (toutes pairs)",
                )
                if pause_state:
                    global_pause_set = True
                    expires_at = pause_state.get("expires_at", "?")
                    msg += (
                        f"\n\n🛑 *AUTO-PAUSE GLOBALE* — auto-exec gelé pour TOUTES "
                        f"les pairs jusqu'à {expires_at}. Resume automatique."
                    )
                if await _send_alert("global", msg, now):
                    alerts_sent.append("global")

        # ─ Détection 3 : rafale par PATTERN (info seule, pas de pause) ─
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
            "by_pair_counts": {p: len(t) for p, t in by_pair.items()},
            "by_pattern_counts": {p: len(t) for p, t in by_pattern.items()},
            "alerts_sent": alerts_sent,
            "alerts_suppressed_cooldown": alerts_suppressed,
            "pairs_paused": pairs_paused,
            "pairs_resumed": pairs_resumed,
            "global_pause_set": global_pause_set,
            "global_pause_resumed": global_pause_resumed,
        }

    except Exception:
        logger.exception("stop_loss_alerts: erreur globale check_and_alert")
        return {"error": "crash, voir logs"}
