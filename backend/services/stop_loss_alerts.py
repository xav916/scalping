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

## Auto-pause + SMART resume (vs blind countdown)

Si ``RAFALE_AUTO_PAUSE_ENABLED=true`` (env, default true), les rafales par
pair et globale déclenchent les pauses kill_switch. La libération
n'est **pas un countdown bête** : le watchdog vérifie cycliquement si V1
essaie encore d'émettre le pattern défaillant sur la pair paused.

État/timing d'une pause par pair :

- ``min_resume_at`` (= triggered_at + ``RAFALE_MIN_COOL_OFF_MIN``, default 30 min) :
  cool-off anti-flapping, jamais de resume avant
- ``max_resume_at`` (= triggered_at + ``RAFALE_MAX_PAUSE_HOURS``, default 6h) :
  plafond max, force resume après même si V1 essaie encore
- Entre les deux : check toutes les 5 min via ``signal_rejections``
  (count des rejections ``kill_switch_pair_paused`` avec le même
  ``signal_pattern`` dans la fenêtre ``RAFALE_QUIET_WINDOW_MIN``, default 15 min)
  - V1 essaie encore (count > 0) → keep paused
  - V1 quiet (count = 0) → SMART_RESUME

3 raisons possibles de resume avec Telegram dédié :
- ``SMART_RESUME`` : V1 a lâché le pattern, libération propre
- ``FORCE_RESUME`` : plafond max atteint, action humaine recommandée
- (legacy) auto-resume sur expires_at pour les pauses pré-V2

## Précisions

- Trades ouverts : continuent jusqu'à leur SL/TP naturel pendant la pause
  (pas de fermeture forcée — éviterait de figer une perte ouverte).
- Idempotence : si une pair est déjà paused, le timer ne se reset pas
  à chaque cycle (évite de prolonger indéfiniment sur cluster persistant).
- Manual trades (``is_auto=0``) ignorés : l'humain est censé savoir.
- Le filet de sécu globale garde un timing simple (``max_pause_hours`` *60).
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


def _pause_settings() -> tuple[bool, int, int, int]:
    """Read env : (enabled, min_cool_off_min, quiet_window_min, max_pause_hours)."""
    try:
        from config.settings import (
            RAFALE_AUTO_PAUSE_ENABLED,
            RAFALE_MAX_PAUSE_HOURS,
            RAFALE_MIN_COOL_OFF_MIN,
            RAFALE_QUIET_WINDOW_MIN,
        )
        return (
            bool(RAFALE_AUTO_PAUSE_ENABLED),
            int(RAFALE_MIN_COOL_OFF_MIN),
            int(RAFALE_QUIET_WINDOW_MIN),
            int(RAFALE_MAX_PAUSE_HOURS),
        )
    except Exception:
        return False, 30, 15, 6


def _dominant_pattern(trades: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """Identifie le pattern + direction dominants dans une liste de SLs.

    Si plusieurs patterns à égalité, prend le 1er. Retourne (pattern, direction).
    """
    by_pattern: dict[str, int] = {}
    by_direction: dict[str, int] = {}
    for t in trades:
        p = t.get("signal_pattern")
        if p:
            by_pattern[p] = by_pattern.get(p, 0) + 1
        d = t.get("direction")
        if d:
            by_direction[d] = by_direction.get(d, 0) + 1
    top_p = max(by_pattern.items(), key=lambda x: x[1])[0] if by_pattern else None
    top_d = max(by_direction.items(), key=lambda x: x[1])[0] if by_direction else None
    return top_p, top_d


def _maybe_set_pair_pause(
    pair: str, reason: str, failed_pattern: str | None, failed_direction: str | None
) -> dict | None:
    enabled, min_cool_off_min, _quiet, max_pause_hours = _pause_settings()
    if not enabled:
        return None
    try:
        from backend.services import kill_switch
        already, _ = kill_switch.is_pair_rafale_paused(pair)
        if already:
            return None  # idempotent
        return kill_switch.set_pair_rafale_pause(
            pair=pair,
            reason=reason,
            min_cool_off_min=min_cool_off_min,
            max_pause_hours=max_pause_hours,
            failed_pattern=failed_pattern,
            failed_direction=failed_direction,
        )
    except Exception as e:
        logger.warning(f"stop_loss_alerts: pair pause set failed for {pair}: {e}")
        return None


def _maybe_set_global_pause(reason: str) -> dict | None:
    enabled, _min, _quiet, max_pause_hours = _pause_settings()
    if not enabled:
        return None
    try:
        from backend.services import kill_switch
        already, _ = kill_switch.is_global_rafale_paused()
        if already:
            return None
        # Pour le filet global on garde un timing simple : durée = max_pause_hours
        return kill_switch.set_global_rafale_pause(
            reason=reason, duration_min=max_pause_hours * 60,
        )
    except Exception as e:
        logger.warning(f"stop_loss_alerts: global pause set failed: {e}")
        return None


# ─── Smart resume — détection d'activité V1 sur la pair paused ─────────


def _v1_still_attempting(pair: str, pattern: str, since_iso: str) -> int:
    """Count des rejections kill_switch_pair_paused pour (pair, pattern) depuis since.

    Si > 0, V1 est toujours en train d'émettre le pattern défaillant pour
    cette pair → on garde paused. Si 0 → V1 a lâché → safe to resume.
    """
    try:
        with sqlite3.connect(_db_path()) as c:
            row = c.execute(
                """
                SELECT COUNT(*) FROM signal_rejections
                 WHERE pair = ?
                   AND reason_code = 'kill_switch_pair_paused'
                   AND json_extract(details, '$.signal_pattern') = ?
                   AND created_at >= ?
                """,
                (pair, pattern, since_iso),
            ).fetchone()
            return int(row[0] or 0)
    except Exception as e:
        logger.warning(f"stop_loss_alerts: v1_still_attempting query failed: {e}")
        return 0


def _smart_resume_decision(
    pair: str, pause_info: dict, now: datetime
) -> tuple[str, dict[str, Any]]:
    """Décide pour une pair paused : KEEP / RESUME / FORCE_RESUME.

    Retourne (decision, context_dict pour message Telegram).
    """
    _, min_cool_off_min, quiet_window_min, max_pause_hours = _pause_settings()

    triggered_at = pause_info.get("triggered_at")
    min_resume_at_iso = pause_info.get("min_resume_at")
    max_resume_at_iso = pause_info.get("max_resume_at") or pause_info.get("expires_at")
    failed_pattern = pause_info.get("failed_pattern")

    # Sécurité : si données manquent (pause pré-V2), fallback sur expires_at
    try:
        max_resume_at = datetime.fromisoformat(max_resume_at_iso) if max_resume_at_iso else None
    except Exception:
        max_resume_at = None
    try:
        min_resume_at = datetime.fromisoformat(min_resume_at_iso) if min_resume_at_iso else None
    except Exception:
        min_resume_at = None

    # ─ FORCE_RESUME : plafond dépassé ─
    if max_resume_at and now >= max_resume_at:
        return "FORCE_RESUME", {"max_pause_hours": max_pause_hours, "pattern": failed_pattern}

    # ─ KEEP : encore dans le min cool-off (anti-flapping) ─
    if min_resume_at and now < min_resume_at:
        remaining = max(0, int((min_resume_at - now).total_seconds() / 60))
        return "KEEP_COOL_OFF", {"remaining_min": remaining, "pattern": failed_pattern}

    # ─ Pas de pattern connu → simple expiration time-based ─
    if not failed_pattern:
        # Si pas de pattern stocké (legacy pause) on attend juste max_resume_at
        return "KEEP_COOL_OFF", {"remaining_min": "?", "pattern": None}

    # ─ Window de check : V1 a-t-il essayé ce pattern récemment ? ─
    quiet_since = (now - timedelta(minutes=quiet_window_min)).isoformat()
    attempts = _v1_still_attempting(pair, failed_pattern, quiet_since)
    if attempts > 0:
        return "KEEP_V1_STILL_TRYING", {
            "attempts": attempts,
            "window_min": quiet_window_min,
            "pattern": failed_pattern,
        }

    # ─ V1 quiet sur ce pattern → safe resume ─
    return "SMART_RESUME", {
        "window_min": quiet_window_min,
        "pattern": failed_pattern,
    }


# ─── Resume notifications ───────────────────────────────────────────────


async def _send_pair_resume_notification(
    pair: str, info: dict, decision: str, context: dict | None = None
) -> None:
    triggered_at = info.get("triggered_at", "?")
    reason = info.get("reason", "?")
    pattern = info.get("failed_pattern") or "?"
    ctx = context or {}

    if decision == "SMART_RESUME":
        title = f"🔓 *Smart resume — {pair}*"
        body = (
            f"V1 a arrêté de tenter `{pattern}` sur {pair} depuis "
            f"{ctx.get('window_min', '?')} min.\n"
            f"Le watchdog libère {pair} car le mode failure semble fini."
        )
    elif decision == "FORCE_RESUME":
        title = f"⚠️ *Force resume — {pair}* (plafond {ctx.get('max_pause_hours', '?')}h atteint)"
        body = (
            f"La pair {pair} était paused depuis {ctx.get('max_pause_hours', '?')}h "
            "(plafond max). Force resume engagé.\n"
            f"Pattern défaillant : `{pattern}`.\n"
            "**Action humaine recommandée** : analyser pourquoi V1 essayait encore."
        )
    else:
        # Fallback générique (pause legacy sans contexte smart)
        title = f"🔓 *Auto-resume — {pair}*"
        body = (
            f"La pause sur {pair} déclenchée à {triggered_at} a expiré.\n"
            f"Raison initiale : {reason}"
        )

    msg = (
        f"{title}\n"
        f"{body}\n"
        f"L'auto-exec MT5 reprend pour {pair}. Les autres pairs n'ont pas été affectées."
    )
    try:
        from backend.services.telegram_service import is_configured, send_text
        if is_configured():
            await send_text(msg, parse_mode="Markdown")
            logger.warning(f"stop_loss_alerts: pair auto-resume notifié {pair} ({decision})")
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

        # ─ Étape 0a : auto-resume global expiré (filet de sécu) ─
        try:
            from backend.services import kill_switch

            expired_global = kill_switch.consume_expired_global_rafale_pause()
            if expired_global:
                await _send_global_resume_notification(expired_global)
                global_pause_resumed = True
        except Exception as e:
            logger.warning(f"stop_loss_alerts: global expired check failed: {e}")

        # ─ Étape 0b : smart resume per-pair (basé sur activité V1, pas countdown bête) ─
        # On itère list_all_pair_pauses_raw (pas list_paused_pairs) pour aussi
        # voir les pauses dont max_resume_at est dans le passé entre 2 cycles —
        # le smart_resume_decision les classe en FORCE_RESUME et envoie le
        # Telegram dédié avant de clear.
        try:
            from backend.services import kill_switch

            for pair, pause_info in list(kill_switch.list_all_pair_pauses_raw().items()):
                decision, ctx = _smart_resume_decision(pair, pause_info, now)
                if decision in ("SMART_RESUME", "FORCE_RESUME"):
                    snapshot = dict(pause_info)
                    kill_switch.clear_pair_rafale_pause(pair)
                    await _send_pair_resume_notification(pair, snapshot, decision, ctx)
                    pairs_resumed.append(pair)
                else:
                    # KEEP_COOL_OFF / KEEP_V1_STILL_TRYING → debug log seul
                    logger.debug(
                        f"stop_loss_alerts: keep paused {pair} reason={decision} ctx={ctx}"
                    )
        except Exception as e:
            logger.warning(f"stop_loss_alerts: smart resume check failed: {e}")

        # ─ Group by pair / pattern ─
        by_pair: dict[str, list[dict[str, Any]]] = {}
        by_pattern: dict[str, list[dict[str, Any]]] = {}
        for t in sl_trades:
            pair = t.get("pair") or "?"
            by_pair.setdefault(pair, []).append(t)
            p = t.get("signal_pattern") or "unknown"
            by_pattern.setdefault(p, []).append(t)

        # ─ Détection 1 : rafale par PAIR (chirurgical, smart resume) ─
        for pair, trades in by_pair.items():
            if len(trades) < PAIR_THRESHOLD:
                continue
            key = f"pair:{pair}"
            if _in_cooldown(key, now):
                alerts_suppressed.append(key)
                continue
            msg = _format_pair_message(pair, trades)
            # Identifie le pattern dominant pour le smart resume check
            failed_pattern, failed_direction = _dominant_pattern(trades)
            pause_state = _maybe_set_pair_pause(
                pair=pair,
                reason=f"{len(trades)} SL en {WINDOW_HOURS}h",
                failed_pattern=failed_pattern,
                failed_direction=failed_direction,
            )
            if pause_state:
                pairs_paused.append(pair)
                min_resume_at = pause_state.get("min_resume_at", "?")
                msg += (
                    f"\n\n⛔ *AUTO-PAUSE {pair}*\n"
                    f"Pattern défaillant : `{failed_pattern or 'N/A'}` "
                    f"({failed_direction or 'N/A'})\n"
                    f"Cool-off min jusqu'à {min_resume_at}.\n"
                    "Smart resume : le watchdog vérifiera ensuite si V1 essaie "
                    "encore ce pattern. Si quiet pendant 15 min → resume. "
                    "Sinon pause prolongée jusqu'à 6h max."
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
