"""Kill switch global : coupe automatiquement l'auto-exec MT5 si la
perte journalière dépasse un seuil. Peut aussi être forcé à la main
(pour une pause weekend, un doute, une maintenance broker...).

Principe
- Trigger automatique : daily realized PnL ≤ -DAILY_LOSS_LIMIT_PCT% du
  capital (réutilise la logique existante dans trade_log_service).
- Trigger manuel : flag persisté dans un petit fichier JSON. Permet
  de bloquer l'auto-exec sans toucher à la config/redéployer.
- Reset automatique à minuit UTC : le trigger daily-PnL se recalcule a
  chaque appel depuis personal_trades, donc un nouveau jour commence
  naturellement avec la jauge à zéro. Le flag manuel, lui, persiste
  tant qu'on ne le coupe pas explicitement.

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
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_PATH = (
    Path("/app/data/kill_switch.json")
    if Path("/app").exists()
    else Path("kill_switch.json")
)
_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_state() -> dict:
    try:
        if _STATE_PATH.exists():
            return json.loads(_STATE_PATH.read_text())
    except Exception as e:
        logger.warning(f"kill_switch: load state failed: {e}")
    return {"manual_enabled": False, "manual_reason": None, "manual_set_at": None}


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


def status() -> dict:
    """Etat complet pour l'UI : est-il actif, pourquoi, depuis quand."""
    manual = _load_state()
    auto, auto_meta = _daily_loss_triggered()
    active = bool(manual.get("manual_enabled")) or auto
    reason: str | None = None
    if manual.get("manual_enabled"):
        reason = f"Manuel : {manual.get('manual_reason') or 'sans raison'}"
    elif auto:
        reason = (
            f"Perte journaliere >= {auto_meta.get('daily_loss_limit_pct', '?')}% "
            "du capital"
        )
    return {
        "active": active,
        "reason": reason,
        "manual_enabled": bool(manual.get("manual_enabled")),
        "manual_reason": manual.get("manual_reason"),
        "manual_set_at": manual.get("manual_set_at"),
        "auto_triggered_by_daily_loss": auto,
        "daily_loss_limit_pct": auto_meta.get("daily_loss_limit_pct"),
    }


def is_active() -> bool:
    """Shortcut : True si l'auto-exec doit etre gele, quelle que soit la
    cause (manuel ou perte journaliere)."""
    manual = _load_state()
    if manual.get("manual_enabled"):
        return True
    auto, _ = _daily_loss_triggered()
    return auto
