"""Kill switch global et per-pair : coupe l'auto-exec MT5 selon différents triggers.

Principe
- Trigger automatique daily-loss : daily realized PnL ≤ -DAILY_LOSS_LIMIT_PCT%
  du capital (réutilise la logique existante dans trade_log_service).
- Trigger automatique rafale-SL **per-pair** : le watchdog stop_loss_alerts
  détecte un cluster de SL sur une pair spécifique → ``set_pair_rafale_pause(pair)``.
  Auto-resume après ``RAFALE_PAUSE_DURATION_MIN`` minutes (default 2h). Les
  autres pairs continuent à trader normalement.
- Trigger automatique rafale-SL **global** (filet de sécurité) :
  si ≥ ``GLOBAL_THRESHOLD`` SL toutes pairs confondues → ``set_global_rafale_pause()``
  qui bloque TOUTE l'auto-exec. Pour incident systémique majeur.
- Trigger manuel : flag persisté dans un petit fichier JSON. Permet
  de bloquer l'auto-exec sans toucher à la config/redéployer.
- Reset automatique à minuit UTC pour le daily-PnL ; les pauses rafale
  expirent après leur duration_min ; le flag manuel persiste.

Le kill switch est consulté par mt5_bridge._should_push(setup) qui passe
``setup.pair`` à ``is_active(pair=...)`` pour différencier global vs per-pair.

Le kill switch n'interfère PAS avec :
- L'analyse et l'émission de signaux (on continue de générer / logger)
- Le suivi des trades déjà ouverts (ils vont jusqu'à leur SL/TP naturel)
- Le push Telegram (garde le monitoring visible)

Seul l'envoi de NOUVEAUX ordres au bridge est gelé pour les pairs/globalement.
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


def _empty_pause_info() -> dict:
    return {
        "active": False,
        "triggered_at": None,
        "expires_at": None,
        "reason": None,
        "trigger_type": None,
    }


def _default_state() -> dict:
    return {
        "manual_enabled": False,
        "manual_reason": None,
        "manual_set_at": None,
        # Pause rafale globale (filet de sécurité, incident systémique).
        "global_rafale_pause": _empty_pause_info(),
        # Pause rafale per-pair : dict[pair, info]. Clé = pair name (ex: "XAU/USD").
        "rafale_paused_pairs": {},
    }


def _load_state() -> dict:
    """Charge le state JSON et migre les structures pré-existantes.

    Migration : si l'ancienne clé ``rafale_pause`` existe (pré-2026-04-30),
    elle est renommée ``global_rafale_pause``. La nouvelle clé
    ``rafale_paused_pairs`` est initialisée vide.
    """
    try:
        if _STATE_PATH.exists():
            state = json.loads(_STATE_PATH.read_text())
            # Migration legacy → nouveau schéma
            if "rafale_pause" in state and "global_rafale_pause" not in state:
                state["global_rafale_pause"] = state.pop("rafale_pause")
            if "global_rafale_pause" not in state:
                state["global_rafale_pause"] = _empty_pause_info()
            if "rafale_paused_pairs" not in state:
                state["rafale_paused_pairs"] = {}
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
    state = _load_state()
    state["manual_enabled"] = bool(enabled)
    state["manual_reason"] = reason if enabled else None
    state["manual_set_at"] = (
        datetime.now(timezone.utc).isoformat() if enabled else None
    )
    _save_state(state)
    logger.warning(
        f"kill_switch: manual={enabled} reason={reason!r}"
        if enabled
        else "kill_switch: manual disabled"
    )
    return state


# ─── Pause rafale GLOBALE (filet de sécurité incident systémique) ──────


def set_global_rafale_pause(reason: str, duration_min: int) -> dict:
    """Active la pause globale (toute l'auto-exec coupée). Filet de sécu."""
    state = _load_state()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=duration_min)
    state["global_rafale_pause"] = {
        "active": True,
        "triggered_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "reason": reason,
        "trigger_type": "global",
    }
    _save_state(state)
    logger.warning(
        f"kill_switch: GLOBAL rafale_pause ON reason={reason!r} expires_at={expires.isoformat()}"
    )
    # History event (best-effort, ne casse pas si la table n'est pas dispo)
    try:
        from backend.services import rafale_history
        rafale_history.log_pause_set(
            scope="global", pair=None, reason=reason,
            triggered_at=state["global_rafale_pause"]["triggered_at"],
        )
    except Exception:
        pass
    return state["global_rafale_pause"]


def clear_global_rafale_pause() -> dict:
    state = _load_state()
    state["global_rafale_pause"] = _empty_pause_info()
    _save_state(state)
    logger.warning("kill_switch: GLOBAL rafale_pause OFF (manual clear)")
    return state["global_rafale_pause"]


def _is_pause_info_active_now(info: dict | None) -> tuple[bool, dict | None]:
    """Helper : retourne (active_non_expiree, info) pour une pause_info dict."""
    if not info or not info.get("active"):
        return False, None
    expires_at_iso = info.get("expires_at")
    if not expires_at_iso:
        return False, info
    try:
        expires_at = datetime.fromisoformat(expires_at_iso)
    except Exception:
        return False, info
    now = datetime.now(timezone.utc)
    if now >= expires_at:
        return False, info
    return True, info


def is_global_rafale_paused() -> tuple[bool, dict | None]:
    """Read-only : True si pause globale active ET non expirée."""
    state = _load_state()
    return _is_pause_info_active_now(state.get("global_rafale_pause"))


def consume_expired_global_rafale_pause() -> dict | None:
    """Si pause globale expirée, clear et retourne le snapshot. Idempotent."""
    state = _load_state()
    info = state.get("global_rafale_pause") or {}
    if not info.get("active"):
        return None
    active_now, _ = _is_pause_info_active_now(info)
    if active_now:
        return None
    snapshot = dict(info)
    state["global_rafale_pause"] = _empty_pause_info()
    _save_state(state)
    logger.warning("kill_switch: GLOBAL rafale_pause expired → auto-cleared")
    return snapshot


# ─── Pause rafale PER-PAIR (chirurgical) ──────────────────────────────


def set_pair_rafale_pause(
    pair: str,
    reason: str,
    min_cool_off_min: int,
    max_pause_hours: int,
    failed_pattern: str | None = None,
    failed_direction: str | None = None,
) -> dict:
    """Active une pause auto-exec pour UNE pair spécifique avec smart resume.

    Sémantique :
    - ``min_resume_at`` (= now + min_cool_off_min) : le watchdog ne resume
      jamais avant ce timestamp, même si V1 a lâché (anti-flapping).
    - ``max_resume_at`` (= now + max_pause_hours) : force resume après ce
      timestamp même si V1 essaie encore (plafond de sécurité).
    - Entre les deux, le watchdog vérifie cycliquement si V1 tente encore
      le pattern défaillant. Si quiet → resume. Si V1 essaie → garde paused.

    ``failed_pattern`` / ``failed_direction`` : contexte du pattern qui a
    causé la rafale, utilisé par le watchdog pour tester la convalescence.
    """
    state = _load_state()
    now = datetime.now(timezone.utc)
    min_resume_at = now + timedelta(minutes=min_cool_off_min)
    max_resume_at = now + timedelta(hours=max_pause_hours)
    info = {
        "active": True,
        "triggered_at": now.isoformat(),
        "min_resume_at": min_resume_at.isoformat(),
        "max_resume_at": max_resume_at.isoformat(),
        # expires_at conservé pour rétrocompat (alias = max_resume_at)
        "expires_at": max_resume_at.isoformat(),
        "reason": reason,
        "trigger_type": f"pair:{pair}",
        "failed_pattern": failed_pattern,
        "failed_direction": failed_direction,
    }
    state["rafale_paused_pairs"][pair] = info
    _save_state(state)
    logger.warning(
        f"kill_switch: PAIR rafale_pause ON pair={pair!r} pattern={failed_pattern!r} "
        f"reason={reason!r} min_resume={min_resume_at.isoformat()} "
        f"max_resume={max_resume_at.isoformat()}"
    )
    try:
        from backend.services import rafale_history
        rafale_history.log_pause_set(
            scope="pair", pair=pair, reason=reason,
            failed_pattern=failed_pattern,
            failed_direction=failed_direction,
            triggered_at=info["triggered_at"],
        )
    except Exception:
        pass
    return info


def clear_pair_rafale_pause(pair: str) -> bool:
    """Désactive manuellement la pause d'une pair. Retourne True si clearée."""
    state = _load_state()
    if pair in state["rafale_paused_pairs"]:
        del state["rafale_paused_pairs"][pair]
        _save_state(state)
        logger.warning(f"kill_switch: PAIR rafale_pause OFF pair={pair!r} (manual clear)")
        return True
    return False


def is_pair_rafale_paused(pair: str) -> tuple[bool, dict | None]:
    """Read-only : True si la pair est en pause active ET non expirée."""
    state = _load_state()
    info = state["rafale_paused_pairs"].get(pair)
    return _is_pause_info_active_now(info)


def consume_expired_pair_rafale_pauses() -> dict[str, dict]:
    """Itère toutes les pairs en pause, clear celles expirées, retourne dict
    {pair: info_snapshot} pour notifications. Idempotent.
    """
    state = _load_state()
    expired: dict[str, dict] = {}
    paused = state.get("rafale_paused_pairs", {})
    for pair, info in list(paused.items()):
        active_now, _ = _is_pause_info_active_now(info)
        if not info.get("active"):
            # Already cleared somehow
            continue
        if not active_now:
            expired[pair] = dict(info)
            del paused[pair]
    if expired:
        state["rafale_paused_pairs"] = paused
        _save_state(state)
        for pair in expired:
            logger.warning(f"kill_switch: PAIR rafale_pause expired pair={pair!r} → cleared")
    return expired


def list_paused_pairs() -> dict[str, dict]:
    """Retourne dict {pair: info} des pairs actuellement en pause non expirée
    (utilisé par /api/status pour l'UI : on n'affiche que les pauses qui
    bloquent encore l'exec)."""
    state = _load_state()
    out: dict[str, dict] = {}
    for pair, info in state.get("rafale_paused_pairs", {}).items():
        active_now, _ = _is_pause_info_active_now(info)
        if active_now:
            out[pair] = info
    return out


def list_all_pair_pauses_raw() -> dict[str, dict]:
    """Retourne TOUTES les entrées rafale_paused_pairs avec ``active=True``,
    y compris celles dont ``max_resume_at`` est dans le passé.

    Utilisé par le watchdog stop_loss_alerts pour itérer même les pauses
    dont le plafond max est dépassé, afin de détecter FORCE_RESUME et
    envoyer la notification Telegram appropriée. mt5_bridge ne doit
    PAS utiliser cette fonction (lui doit voir les pauses expirées
    comme inactives via is_pair_rafale_paused)."""
    state = _load_state()
    out: dict[str, dict] = {}
    for pair, info in state.get("rafale_paused_pairs", {}).items():
        if info.get("active"):
            out[pair] = info
    return out


# ─── Daily loss trigger (existant, inchangé) ───────────────────────────


def _daily_loss_triggered() -> tuple[bool, dict]:
    """True si AU MOINS UN user a depasse DAILY_LOSS_LIMIT_PCT aujourd'hui."""
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


# ─── Status + is_active (entry points pour callers) ────────────────────


def status() -> dict:
    """Etat complet pour l'UI : actif global, raison, paused pairs, etc."""
    state = _load_state()
    auto_daily, auto_meta = _daily_loss_triggered()
    global_active, global_info = is_global_rafale_paused()
    paused_pairs = list_paused_pairs()
    manual_active = bool(state.get("manual_enabled"))

    # active = True si N'IMPORTE QUOI bloque (global) ; n'inclut pas les
    # per-pair pauses car celles-ci sont chirurgicales (le système global
    # n'est pas off, juste certaines pairs).
    active = manual_active or auto_daily or global_active

    reason: str | None = None
    if manual_active:
        reason = f"Manuel : {state.get('manual_reason') or 'sans raison'}"
    elif auto_daily:
        reason = (
            f"Perte journaliere >= {auto_meta.get('daily_loss_limit_pct', '?')}% "
            "du capital"
        )
    elif global_active and global_info:
        reason = f"Rafale SL globale : {global_info.get('reason')}"

    return {
        "active": active,
        "reason": reason,
        "manual_enabled": manual_active,
        "manual_reason": state.get("manual_reason"),
        "manual_set_at": state.get("manual_set_at"),
        "auto_triggered_by_daily_loss": auto_daily,
        "daily_loss_limit_pct": auto_meta.get("daily_loss_limit_pct"),
        "global_rafale_pause_active": global_active,
        "global_rafale_pause_info": global_info if global_active else None,
        "paused_pairs": paused_pairs,  # dict[pair, info] des pairs en pause
        "paused_pairs_count": len(paused_pairs),
    }


def is_active(pair: str | None = None) -> bool:
    """True si l'auto-exec doit etre gele.

    - Si ``pair`` fourni : True si manuel OU daily_loss OU global_rafale OU
      cette pair-là est rafale-paused.
    - Si ``pair`` None : True uniquement pour les triggers globaux
      (manuel / daily_loss / global_rafale). Les per-pair pauses ne
      coupent PAS le système globalement.
    """
    state = _load_state()
    if state.get("manual_enabled"):
        return True
    auto_daily, _ = _daily_loss_triggered()
    if auto_daily:
        return True
    global_active, _ = is_global_rafale_paused()
    if global_active:
        return True
    if pair is not None:
        pair_active, _ = is_pair_rafale_paused(pair)
        if pair_active:
            return True
    return False
