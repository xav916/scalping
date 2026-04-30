"""Kill switch global : coupe automatiquement l'auto-exec MT5 si la
perte journalière dépasse un seuil. Peut aussi être forcé à la main
(pour une pause weekend, un doute, une maintenance broker...).

Principe
- Trigger automatique daily-loss : daily realized PnL ≤ -DAILY_LOSS_LIMIT_PCT%
  du capital (réutilise la logique existante dans trade_log_service).
- Trigger automatique rafale-SL : le watchdog stop_loss_alerts détecte un
  cluster de SL et appelle ``set_rafale_pause(...)``. Auto-resume après
  ``RAFALE_PAUSE_DURATION_MIN`` minutes (default 2h). Cf. journal
  ``2026-04-30-v1-drawdown-observation.md``.
- Trigger manuel : flag persisté dans un petit fichier JSON. Permet
  de bloquer l'auto-exec sans toucher à la config/redéployer.
- Reset automatique à minuit UTC : le trigger daily-PnL se recalcule a
  chaque appel depuis personal_trades. Le rafale_pause expire après son
  duration_min. Le flag manuel, lui, persiste tant qu'on ne le coupe
  pas explicitement.

Le kill switch est consulte par mt5_bridge._should_push() pour bloquer
toute nouvelle execution. Il n'interfere PAS avec :
- L'analyse et l'emission de signaux (on continue de generer / logger)
- Le suivi des trades deja ouverts (ils vont jusqu'a leur SL/TP naturel)
- Le push Telegram (garde le monitoring visible)

Seul l'envoi de NOUVEAUX ordres au bridge est gele.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_PATH = (
    Path("/app/data/kill_switch.json")
    if Path("/app").exists()
    else Path("kill_switch.json")
)
_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _default_state() -> dict:
    return {
        "manual_enabled": False,
        "manual_reason": None,
        "manual_set_at": None,
        # Rafale pause : auto-déclenché par stop_loss_alerts, expire après
        # RAFALE_PAUSE_DURATION_MIN minutes. Auto-resume sans intervention.
        "rafale_pause": {
            "active": False,
            "triggered_at": None,
            "expires_at": None,
            "reason": None,
            "trigger_type": None,  # "global" | "pattern:<name>"
        },
    }


def _load_state() -> dict:
    try:
        if _STATE_PATH.exists():
            state = json.loads(_STATE_PATH.read_text())
            # Migration : ajout du champ rafale_pause sur DB pré-existante.
            if "rafale_pause" not in state:
                state["rafale_pause"] = _default_state()["rafale_pause"]
            return state
    except Exception as e:
        logger.warning(f"kill_switch: load state failed: {e}")
    return _default_state()


def _save_state(state: dict) -> None:
    try:
        _STATE_PATH.write_text(json.dumps(state))
    except Exception as e:
        logger.warning(f"kill_switch: save state failed: {e}")


def is_manually_enabled() -> bool:
    return bool(_load_state().get("manual_enabled"))


def set_manual(enabled: bool, reason: str | None = None) -> dict:
    """Active / desactive le kill switch manuel. Retourne le nouvel etat."""
    state = {
        "manual_enabled": bool(enabled),
        "manual_reason": reason if enabled else None,
        "manual_set_at": datetime.now(timezone.utc).isoformat() if enabled else None,
    }
    _save_state(state)
    logger.warning(
        f"kill_switch: manual={enabled} reason={reason!r}"
        if enabled
        else "kill_switch: manual disabled"
    )
    return state


def _daily_loss_triggered() -> tuple[bool, dict]:
    """True si AU MOINS UN user a depasse DAILY_LOSS_LIMIT_PCT aujourd'hui.
    Retourne aussi le detail pour l'UI / les alertes."""
    try:
        from backend.services import trade_log_service
        from config.settings import DAILY_LOSS_LIMIT_PCT, TRADING_CAPITAL
    except Exception:
        return False, {}

    try:
        triggered = trade_log_service.silent_mode_active_any_user()
    except Exception:
        triggered = False
    return triggered, {
        "daily_loss_limit_pct": DAILY_LOSS_LIMIT_PCT,
        "capital": TRADING_CAPITAL,
    }


def set_rafale_pause(
    reason: str, duration_min: int, trigger_type: str
) -> dict:
    """Active une pause auto-exec déclenchée par le watchdog rafale SL.

    ``duration_min`` : durée du cool-off avant auto-resume.
    ``trigger_type`` : "global" ou "pattern:<name>" pour traçabilité.
    Retourne le nouvel état du sub-state rafale_pause.
    """
    state = _load_state()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=duration_min)
    state["rafale_pause"] = {
        "active": True,
        "triggered_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "reason": reason,
        "trigger_type": trigger_type,
    }
    _save_state(state)
    logger.warning(
        f"kill_switch: rafale_pause ON ({trigger_type}) reason={reason!r} "
        f"expires_at={expires.isoformat()}"
    )
    return state["rafale_pause"]


def clear_rafale_pause() -> dict:
    """Désactive manuellement la pause rafale (cas rare). Retourne l'état."""
    state = _load_state()
    state["rafale_pause"] = _default_state()["rafale_pause"]
    _save_state(state)
    logger.warning("kill_switch: rafale_pause OFF (manual clear)")
    return state["rafale_pause"]


def is_rafale_paused() -> tuple[bool, dict | None]:
    """True si une rafale pause est active ET non expirée. Read-only, ne clear pas.

    Sémantique : un flag ``active=True`` + ``expires_at > now`` = paused.
    Si ``expires_at`` est dans le passé, on retourne ``(False, info)`` mais
    on ne touche PAS au state JSON. Le clear effectif se fait via
    ``consume_expired_rafale_pause()`` appelé depuis le watchdog uniquement,
    pour éviter les races sur la notification de transition.
    """
    state = _load_state()
    rp = state.get("rafale_pause") or {}
    if not rp.get("active"):
        return False, None

    expires_at_iso = rp.get("expires_at")
    if not expires_at_iso:
        return False, rp

    try:
        expires_at = datetime.fromisoformat(expires_at_iso)
    except Exception:
        return False, rp

    now = datetime.now(timezone.utc)
    if now >= expires_at:
        # Expirée : sémantiquement plus paused, mais le flag JSON reste à True
        # tant que consume_expired_rafale_pause() n'a pas été appelé.
        return False, rp

    return True, rp


def consume_expired_rafale_pause() -> dict | None:
    """Si une rafale pause est expirée, clear le flag et retourne son info.

    Idempotent : si pas expirée ou déjà clearée, retourne None.
    Doit être appelé par le job watchdog (toutes les 5 min) — c'est le
    point unique où la transition active→clear se matérialise, garantissant
    qu'on envoie exactement un Telegram resume par expiration.
    """
    state = _load_state()
    rp = state.get("rafale_pause") or {}
    if not rp.get("active"):
        return None

    expires_at_iso = rp.get("expires_at")
    if not expires_at_iso:
        # Corrompu, on clear par sécurité
        clear_rafale_pause()
        return rp

    try:
        expires_at = datetime.fromisoformat(expires_at_iso)
    except Exception:
        clear_rafale_pause()
        return rp

    now = datetime.now(timezone.utc)
    if now < expires_at:
        return None  # Toujours paused, rien à faire

    # Expirée → clear et retourne le snapshot pour notification
    info = dict(rp)
    clear_rafale_pause()
    return info


def status() -> dict:
    """Etat complet pour l'UI : est-il actif, pourquoi, depuis quand."""
    manual = _load_state()
    auto_daily, auto_meta = _daily_loss_triggered()
    rafale_active, rafale_info = is_rafale_paused()
    active = bool(manual.get("manual_enabled")) or auto_daily or rafale_active
    reason: str | None = None
    if manual.get("manual_enabled"):
        reason = f"Manuel : {manual.get('manual_reason') or 'sans raison'}"
    elif auto_daily:
        reason = (
            f"Perte journaliere >= {auto_meta.get('daily_loss_limit_pct', '?')}% "
            "du capital"
        )
    elif rafale_active and rafale_info:
        reason = f"Rafale SL ({rafale_info.get('trigger_type')}) : {rafale_info.get('reason')}"
    return {
        "active": active,
        "reason": reason,
        "manual_enabled": bool(manual.get("manual_enabled")),
        "manual_reason": manual.get("manual_reason"),
        "manual_set_at": manual.get("manual_set_at"),
        "auto_triggered_by_daily_loss": auto_daily,
        "daily_loss_limit_pct": auto_meta.get("daily_loss_limit_pct"),
        "rafale_pause_active": rafale_active,
        "rafale_pause_info": rafale_info if rafale_active else None,
    }


def is_active() -> bool:
    """Shortcut : True si l'auto-exec doit etre gele, quelle que soit la
    cause (manuel, perte journaliere, ou rafale SL)."""
    manual = _load_state()
    if manual.get("manual_enabled"):
        return True
    auto_daily, _ = _daily_loss_triggered()
    if auto_daily:
        return True
    rafale_active, _ = is_rafale_paused()
    return rafale_active
