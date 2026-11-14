"""Watchdog quotidien du compte RÉEL IC Markets (bridge port 8788).

## Pourquoi

Post-audit 2026-11-13 : Xavier a coupé l'IA le 2026-10-12 en regardant
le compte DEMO (125 trades / -18 EUR), ignorant que le compte RÉEL
continuait au même moment avec 180 trades et des pertes 2× plus
importantes. Confusion mentale entre demo et réel.

Cette alerte Telegram quotidienne force la visibilité du compte RÉEL
dans un canal dédié 🟩 ``ic_markets``, avec un format SI visuellement
distinct qu'il est impossible de le confondre avec la demo 🟦.

## Format

    🔴🔴🔴 COMPTE RÉEL — IC Markets EU 🔴🔴🔴
    Login 13137475 · 2026-11-13 22:00 UTC

    💰 Balance:     344.47 EUR
    📉 Daily PnL:   -14.17 / -35.52 EUR (40% du stop auto)
    📊 Open positions: 3

    Tickets ouverts:
    · XAUUSD sell 0.01 @ 3877.96 → -3.03 USD
    · ...

Déclenche une alerte URGENTE si daily_pnl < -daily_limit/2.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


BRIDGE_URL = _env("MT5_BRIDGE_LIVE_URL").rstrip("/")
API_KEY = _env("MT5_BRIDGE_LIVE_API_KEY")


async def _fetch_health() -> dict | None:
    if not BRIDGE_URL:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{BRIDGE_URL}/health")
            if r.status_code != 200:
                logger.warning(
                    "real_account_watchdog: /health HTTP %s", r.status_code)
                return None
            return r.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("real_account_watchdog: /health failed — %s", e)
        return None


async def _fetch_positions() -> list[dict]:
    if not BRIDGE_URL or not API_KEY:
        return []
    headers = {"X-API-Key": API_KEY}
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{BRIDGE_URL}/positions", headers=headers)
            if r.status_code != 200:
                logger.warning(
                    "real_account_watchdog: /positions HTTP %s", r.status_code)
                return []
            return (r.json() or {}).get("positions") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("real_account_watchdog: /positions failed — %s", e)
        return []


def _format_message(
    health: dict | None, positions: list[dict], now_utc: datetime,
) -> str:
    lines = ["🔴🔴🔴 <b>COMPTE RÉEL — IC Markets EU</b> 🔴🔴🔴"]
    login = (health or {}).get("login", "?")
    server = (health or {}).get("server", "?")
    lines.append(f"Login {login} · {server}")
    lines.append(f"<i>{now_utc.strftime('%Y-%m-%d %H:%M UTC')}</i>")
    lines.append("")

    if health is None:
        lines.append("⚠️ <b>Bridge INJOIGNABLE</b> — impossible de lire l'état")
        lines.append("Vérifie que la session MT5 Live tourne sur Lightsail.")
        return "\n".join(lines)

    gf = health.get("garde_fous") or {}
    daily_pnl = gf.get("daily_loss")
    daily_limit = gf.get("daily_loss_limit")

    # Pseudo-balance — le /health ne la publie pas directement, on la
    # devine via positions si possible, sinon on dit N/A.
    lines.append(f"📊 Positions ouvertes: <b>{len(positions)}</b>")

    if daily_pnl is not None and daily_limit is not None:
        try:
            pct = (abs(daily_pnl) / daily_limit) * 100 if daily_limit else 0
            pnl_signe = f"-{daily_pnl:.2f}" if daily_pnl > 0 else f"{daily_pnl:+.2f}"
            # /health exprime daily_loss comme valeur positive (perte).
            # Reconvertir en PnL signé : perte → négatif.
            daily_pnl_display = -abs(float(daily_pnl))
            lines.append(
                f"📉 Daily PnL: <b>{daily_pnl_display:+.2f}</b> EUR "
                f"(cap -{daily_limit:.2f}, consommé {pct:.0f}%)"
            )
            if pct >= 50:
                lines.append(
                    f"⚠️⚠️ <b>Daily loss dépasse 50% du cap</b> — attention."
                )
            if pct >= 80:
                lines.append(
                    f"🚨🚨🚨 <b>URGENCE</b> — stop auto bridge à {100-pct:.0f}% près."
                )
        except (TypeError, ValueError):
            pass

    if positions:
        lines.append("")
        lines.append("<b>Tickets ouverts :</b>")
        for p in positions[:10]:
            sym = p.get("symbol") or p.get("pair") or "?"
            direction = p.get("type") or p.get("direction") or "?"
            vol = p.get("volume") or p.get("lots") or "?"
            entry = p.get("price_open") or p.get("entry") or "?"
            profit = p.get("profit")
            profit_str = f" P&L {profit:+.2f}" if profit is not None else ""
            lines.append(
                f"· {sym} {direction} {vol} @ {entry}{profit_str}"
            )
        if len(positions) > 10:
            lines.append(f"... +{len(positions) - 10} autres")

    lines.append("")
    lines.append(
        "<i>Si tu veux couper : "
        "<code>disarm REM-002</code> + "
        "<code>MT5_BRIDGE_LIVE_ENABLED=false</code></i>"
    )
    return "\n".join(lines)


async def send_daily_real_recap() -> dict:
    """Envoie un résumé du compte RÉEL dans le canal 🟩 ic_markets.

    Appelé par le scheduler quotidiennement (cron). Log en cas d'erreur
    mais ne lève jamais : le watchdog ne doit pas tuer le service.

    Désactivable via env ``REAL_ACCOUNT_WATCHDOG_ENABLED=false`` (default true).
    Utile si le bridge est volontairement off (ex: réel coupé) pour éviter
    des alertes "Bridge INJOIGNABLE" quotidiennes jugées spammy.
    """
    import os as _os
    if _os.getenv("REAL_ACCOUNT_WATCHDOG_ENABLED", "true").strip().lower() not in ("true", "1", "yes", "on"):
        logger.info("real_account_watchdog: désactivé via env, skip.")
        return {"sent": False, "skipped": "disabled"}
    try:
        health = await _fetch_health()
        positions = await _fetch_positions()
        now_utc = datetime.now(timezone.utc)
        text = _format_message(health, positions, now_utc)
        from backend.services.telegram_service import send_sales_text
        delivered = await send_sales_text(text, parse_mode="HTML")
        return {
            "sent": bool(delivered),
            "has_health": health is not None,
            "open_positions": len(positions),
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("real_account_watchdog: send failed — %s", e)
        return {"sent": False, "error": str(e)}
