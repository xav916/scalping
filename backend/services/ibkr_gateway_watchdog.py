"""Monitoring IBKR Gateway — alerte Telegram instantanée si DOWN.

## Pourquoi

La Gateway IBKR tourne sur Lightsail Windows. Elle peut se déconnecter :
- Reboot Windows (mise à jour, incident AWS)
- Maintenance dimanche soir IBKR (~22h UTC)
- Perte réseau Tailscale
- Session IBKR expirée (> 7 jours)

Sans monitoring, on ne sait pas que la Gateway est tombée jusqu'au
prochain cycle auto_trader qui va échouer silencieusement. Ce watchdog
poll /health toutes les 5 min et poste une alerte Telegram instantanée
sur canal infra ⚙️ si ``connected != true``.

## State machine

    UP → UP          : silence, cooldown réinitialisé
    UP → DOWN        : ALERTE Telegram immédiate "Gateway IBKR DOWN"
    DOWN → DOWN      : alerte toutes les 30 min (anti-spam) tant que down
    DOWN → UP        : ALERTE Telegram "Gateway IBKR BACK UP"

## Env vars

- ``IBKR_GATEWAY_WATCHDOG_ENABLED`` (défaut ``true``) — switch global
- ``IBKR_BRIDGE_URL`` — déjà présent (ex ``http://100.74.160.72:8792``)
- ``IBKR_BRIDGE_API_KEY`` — déjà présent (optionnel pour /health)
- ``IBKR_GATEWAY_WATCHDOG_COOLDOWN_SEC`` (défaut 1800 = 30 min)

## Fail-safe

Toute exception interne → log WARNING + return silencieux. Un bug du
watchdog ne doit pas tuer le scalping.service.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)


STATE_PATH = os.getenv(
    "IBKR_GATEWAY_WATCHDOG_STATE",
    "/app/data/ibkr_gateway_watchdog.json",
)
COOLDOWN_SEC_DEFAULT = 1800  # 30 min


def _enabled() -> bool:
    return os.getenv(
        "IBKR_GATEWAY_WATCHDOG_ENABLED", "true"
    ).strip().lower() in ("true", "1", "yes", "on")


def _cooldown_sec() -> int:
    try:
        return int(os.getenv("IBKR_GATEWAY_WATCHDOG_COOLDOWN_SEC",
                             str(COOLDOWN_SEC_DEFAULT)))
    except (TypeError, ValueError):
        return COOLDOWN_SEC_DEFAULT


def _load_state() -> dict:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"was_connected": True, "last_alert_at": None}
    except Exception as e:  # noqa: BLE001
        logger.warning("ibkr_gateway_watchdog: load_state failed — %s", e)
        return {"was_connected": True, "last_alert_at": None}


def _save_state(state: dict) -> None:
    try:
        p = pathlib.Path(STATE_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(p) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, STATE_PATH)
    except Exception as e:  # noqa: BLE001
        logger.warning("ibkr_gateway_watchdog: save_state failed — %s", e)


async def _fetch_health() -> dict:
    url = os.getenv("IBKR_BRIDGE_URL", "").strip().rstrip("/")
    key = os.getenv("IBKR_BRIDGE_API_KEY", "").strip()
    if not url:
        return {"ok": False, "error": "no_IBKR_BRIDGE_URL"}
    try:
        headers = {"X-API-Key": key} if key else {}
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{url}/health", headers=headers)
            if r.status_code != 200:
                return {"ok": False, "error": f"http_{r.status_code}"}
            return r.json()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"exception: {str(e)[:120]}"}


def _cooldown_elapsed(last_iso: str | None, cooldown_sec: int) -> bool:
    if not last_iso:
        return True
    try:
        last = datetime.fromisoformat(last_iso)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        return elapsed >= cooldown_sec
    except ValueError:
        return True


async def _send_down_alert(health: dict) -> None:
    """Alerte DOWN sur canal infra."""
    err = health.get("error") or "unknown"
    text = (
        "🚨🚨 <b>Gateway IBKR DOWN</b>\n"
        f"bridge {os.getenv('IBKR_BRIDGE_URL', '?')}\n"
        f"motif : <code>{err}</code>\n"
        f"heure UTC : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}\n"
        f"\n"
        f"🔧 Action :\n"
        f"1. RDP Lightsail Windows\n"
        f"2. Vérifier processus ibgateway (<code>Get-Process ibgateway*</code>)\n"
        f"3. Si mort : <code>Start-Process C:\\Jts\\ibgateway\\1050\\ibgateway1.exe</code>\n"
        f"4. Login paper si demandé (compte DUR358393)\n"
        f"5. Vérifier bridge Python relancé via start-bridge.ps1"
    )
    try:
        from backend.services import telegram_service
        await telegram_service.send_infra_text(text, parse_mode="HTML")
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "ibkr_gateway_watchdog: send_down_alert failed — %s", e)


async def _send_recovery_alert(health: dict) -> None:
    """Alerte UP (retour en ligne) sur canal infra."""
    accounts = health.get("accounts") or []
    acc_str = ", ".join(accounts) if accounts else "?"
    text = (
        "✅ <b>Gateway IBKR BACK UP</b>\n"
        f"bridge {os.getenv('IBKR_BRIDGE_URL', '?')}\n"
        f"accounts : <code>{acc_str}</code>\n"
        f"orders_allowed : {health.get('orders_allowed')}\n"
        f"read_only : {health.get('read_only')}\n"
        f"heure UTC : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    )
    try:
        from backend.services import telegram_service
        await telegram_service.send_infra_text(text, parse_mode="HTML")
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "ibkr_gateway_watchdog: send_recovery_alert failed — %s", e)


async def check_and_alert() -> dict:
    """Job appelé par le scheduler toutes les 5 min.

    Returns ``{"ran": bool, "connected": bool, "alerted": bool, ...}``
    """
    if not _enabled():
        return {"ran": False, "reason": "watchdog_disabled"}

    health = await _fetch_health()
    is_connected = bool(
        health.get("ok") and health.get("connected")
    )

    state = _load_state()
    was_connected = state.get("was_connected", True)
    last_alert_at = state.get("last_alert_at")
    cooldown = _cooldown_sec()
    alerted = False

    if is_connected:
        if not was_connected:
            await _send_recovery_alert(health)
            alerted = True
            logger.warning("ibkr_gateway_watchdog: recovery alert sent")
        state["was_connected"] = True
        state["last_alert_at"] = None
    else:
        if was_connected or _cooldown_elapsed(last_alert_at, cooldown):
            await _send_down_alert(health)
            alerted = True
            state["last_alert_at"] = datetime.now(
                timezone.utc).isoformat(timespec="seconds")
            logger.warning(
                "ibkr_gateway_watchdog: DOWN alert sent (first=%s, was_connected=%s)",
                not was_connected, was_connected,
            )
        state["was_connected"] = False

    _save_state(state)
    return {
        "ran": True,
        "connected": is_connected,
        "alerted": alerted,
        "state": {"was_connected": state["was_connected"]},
    }
