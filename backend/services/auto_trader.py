"""Auto-trader IBKR v1 — pipeline end-to-end sans intervention humaine.

Chaîne : screener → vetos → budget → risk → exec via bridge IBKR.

## Status

**OFF par défaut** (``AUTO_TRADER_ENABLED=false``). Même quand on l'allume,
le mode par défaut est ``dry_run`` : chaque cycle est logué + poussé sur
Telegram, mais aucun ordre réel ne part. C'est le mode validation.

Pour passer en ``live`` : ``AUTO_TRADER_MODE=live`` + ``IBKR_ALLOW_ORDERS=true``
côté bridge. Les deux flags sont indépendants et fail-closed.

## Garde-fous (fail-closed, un seul False abort le cycle)

| Check | Env var | Baseline |
|---|---|---|
| Feature flag global | ``AUTO_TRADER_ENABLED`` | false |
| Mode | ``AUTO_TRADER_MODE`` | ``dry_run`` |
| Kill switch global | ``kill_switch.status()`` | — |
| Perte journalière plafond | ``AUTO_TRADER_MAX_DAILY_LOSS_EUR`` | 5.0 |
| Positions ouvertes max | ``AUTO_TRADER_MAX_POSITIONS`` | 3 |
| Plafond par ordre | ``AUTO_TRADER_MAX_ORDER_EUR`` | 20.0 |
| Fenêtre horaire | NYSE 15h30-22h Paris L-V | — |
| Blackout vendredi soir | ``AUTO_TRADER_FRIDAY_LATE_BLOCK_UTC`` | 19:30 |
| Univers restreint | ``AUTO_TRADER_UNIVERSE`` | AAPL,TSLA,F,SPY,QQQ |
| Earnings <48h | via ``earnings_calendar_service`` | — |

## Exits

- **Bracket order** côté bridge : SL+TP posés à l'entrée
- **Friday force-close** à 20h30 UTC : ferme tout ce que l'auto-trader
  a ouvert cette semaine (évite gap weekend)

## Ce qu'il NE fait pas

- Pas de short selling
- Pas d'options, pas de crypto
- Pas de pyramide (1 position par ticker max)
- Pas d'ajustement SL/TP après entrée
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)


# ─── Config env ─────────────────────────────────────────────────────────

def _env_bool(key: str, default: str = "false") -> bool:
    return os.getenv(key, default).strip().lower() in ("true", "1", "yes", "on")


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


# Flag relu à chaque cycle (activation/désactivation à chaud)
def _config_enabled() -> bool:
    return _env_bool("AUTO_TRADER_ENABLED", "false")


def _config_mode() -> str:
    """``dry_run`` (défaut) ou ``live``. Autre valeur → dry_run (fail-closed)."""
    mode = os.getenv("AUTO_TRADER_MODE", "dry_run").strip().lower()
    return mode if mode in ("dry_run", "live") else "dry_run"


BRIDGE_URL = os.getenv("IBKR_BRIDGE_URL", "http://100.74.160.72:8792").rstrip("/")
BRIDGE_KEY = os.getenv("IBKR_BRIDGE_API_KEY", "")
MAX_DAILY_LOSS_EUR = _env_float("AUTO_TRADER_MAX_DAILY_LOSS_EUR", 5.0)
MAX_POSITIONS = _env_int("AUTO_TRADER_MAX_POSITIONS", 3)
MAX_ORDER_EUR = _env_float("AUTO_TRADER_MAX_ORDER_EUR", 20.0)
MIN_CONFIDENCE = _env_float("AUTO_TRADER_MIN_CONFIDENCE", 70.0)
UNIVERSE = [
    t.strip().upper() for t in os.getenv("AUTO_TRADER_UNIVERSE", "AAPL,TSLA,F,SPY,QQQ").split(",")
    if t.strip()
]
FRIDAY_LATE_BLOCK_UTC = os.getenv("AUTO_TRADER_FRIDAY_LATE_BLOCK_UTC", "19:30")
SL_PCT = _env_float("AUTO_TRADER_SL_PCT", 2.0)
TP_PCT = _env_float("AUTO_TRADER_TP_PCT", 4.0)
EUR_USD_RATE = _env_float("AUTO_TRADER_EUR_USD_FIXED", 1.07)
EARNINGS_VETO_HOURS = _env_int("AUTO_TRADER_EARNINGS_WINDOW_HOURS", 48)
FOMC_VETO_MINUTES = _env_int("AUTO_TRADER_FOMC_WINDOW_MINUTES", 120)
SCAN_INTERVAL_SEC = _env_int("AUTO_TRADER_SCAN_INTERVAL_SEC", 300)
POLL_INTERVAL_SEC = SCAN_INTERVAL_SEC  # alias exposé au scheduler


# ─── État in-memory ─────────────────────────────────────────────────────

# Positions ouvertes par AUTO-TRADER (pas les positions IBKR globales).
# Reset au restart du radar — acceptable : au restart, on refetch via bridge
# et on considère toute position existante comme non gérée par l'auto-trader
# (elle ne sera donc pas fermée au friday close).
_opened_today: dict[str, dict[str, Any]] = {}
_opening_date: date | None = None
_opening_net_liq_eur: float | None = None
_disabled_until_tomorrow: bool = False


# ─── Safety gates ───────────────────────────────────────────────────────

def _is_market_hours() -> bool:
    """NYSE : 15h30-22h Paris en semaine (approximation sans DST)."""
    now = datetime.now(ZoneInfo("Europe/Paris"))
    if now.weekday() >= 5:
        return False
    if now.hour < 15 or now.hour >= 22:
        return False
    if now.hour == 15 and now.minute < 30:
        return False
    return True


def _is_friday_late() -> bool:
    """Après FRIDAY_LATE_BLOCK_UTC le vendredi : plus de nouveaux trades."""
    now_utc = datetime.now(timezone.utc)
    if now_utc.weekday() != 4:  # Friday = 4
        return False
    try:
        h, m = map(int, FRIDAY_LATE_BLOCK_UTC.split(":"))
        block_time = time(hour=h, minute=m)
    except Exception:
        block_time = time(hour=19, minute=30)
    return now_utc.time() >= block_time


def _is_kill_switch_active() -> bool:
    try:
        from backend.services import kill_switch as _ks
        return bool(_ks.status().get("active"))
    except Exception:
        return False


async def _is_daily_loss_exceeded() -> bool:
    """True si drawdown IBKR journalier dépasse le seuil EUR."""
    global _opening_date, _opening_net_liq_eur, _disabled_until_tomorrow

    today = date.today()
    if _opening_date != today:
        _opening_date = today
        _opening_net_liq_eur = None
        _disabled_until_tomorrow = False

    if _disabled_until_tomorrow:
        return True

    try:
        snapshot = await _fetch_account()
    except Exception as e:
        logger.warning("auto_trader: fetch_account failed, prudence → block cycle (%s)", e)
        return True  # fail-closed

    if not snapshot.get("ok"):
        return True

    net_liq = float(snapshot.get("NetLiquidation") or 0)
    if _opening_net_liq_eur is None:
        _opening_net_liq_eur = net_liq
        logger.info("auto_trader: baseline net_liq jour = %.2f EUR", net_liq)
        return False

    daily_pnl = net_liq - _opening_net_liq_eur
    if daily_pnl < -MAX_DAILY_LOSS_EUR:
        _disabled_until_tomorrow = True
        logger.warning(
            "auto_trader: KILL — daily PnL %.2f EUR < seuil -%.2f EUR → désactivé jusqu'à minuit",
            daily_pnl, MAX_DAILY_LOSS_EUR,
        )
        await _send_info(
            f"🚨 auto_trader DÉSACTIVÉ auto\n"
            f"Daily PnL {daily_pnl:+.2f} EUR < seuil -{MAX_DAILY_LOSS_EUR:.2f}\n"
            f"Re-activer manuellement dans .env + restart"
        )
        return True
    return False


# ─── Bridge calls ───────────────────────────────────────────────────────

def _headers() -> dict[str, str]:
    return {"X-Bridge-Key": BRIDGE_KEY} if BRIDGE_KEY else {}


async def _fetch_account() -> dict:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f"{BRIDGE_URL}/account", headers=_headers())
        return r.json()


async def _fetch_positions() -> dict:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f"{BRIDGE_URL}/positions", headers=_headers())
        return r.json()


async def _fetch_tick(ticker: str) -> dict | None:
    """Renvoie {bid, ask, last} ou None si bridge/Gateway KO sur ce ticker."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{BRIDGE_URL}/tick/{ticker}", headers=_headers())
            if r.status_code != 200:
                return None
            data = r.json()
            if not data.get("ok"):
                return None
            return data
    except Exception as e:
        logger.warning("auto_trader: fetch_tick %s failed — %s", ticker, e)
        return None


# ─── Vetos ──────────────────────────────────────────────────────────────

def _veto_earnings(ticker: str) -> str | None:
    """Return raison du veto, ou None si pas de veto."""
    try:
        from backend.services import earnings_calendar_service as _ec
        hours_to = _ec.hours_to_next_earnings(ticker)
        if hours_to is not None and abs(hours_to) < EARNINGS_VETO_HOURS:
            return f"earnings dans {hours_to:+.1f}h"
    except Exception:
        pass
    return None


def _veto_fomc_cpi() -> str | None:
    """Veto global si on est dans la fenêtre FOMC/CPI."""
    try:
        from backend.services import economic_calendar_veto as _ecv
        active = _ecv.is_high_impact_window(window_minutes=FOMC_VETO_MINUTES)
        if active:
            return "FOMC/CPI window active"
    except Exception:
        pass
    return None


# ─── Helpers ────────────────────────────────────────────────────────────

async def _send_info(text: str) -> None:
    try:
        from backend.services import telegram_service
        await telegram_service.send_info_text(text, parse_mode="HTML")
    except Exception as e:
        logger.warning("auto_trader: send_info_text failed — %s", e)


def _usd_from_eur(eur: float) -> float:
    return eur * EUR_USD_RATE


def _size_qty(price_usd: float) -> int:
    """Calcule nombre d'actions entières pour max_order_eur."""
    budget_usd = _usd_from_eur(MAX_ORDER_EUR)
    return max(0, int(budget_usd // price_usd))


# ─── Cycle principal ────────────────────────────────────────────────────

async def cycle() -> dict:
    """Un cycle auto-trader. Appelé toutes les SCAN_INTERVAL_SEC par le scheduler."""
    result = {"ran": False, "reason": None, "candidates": [], "actions": []}

    if not _config_enabled():
        result["reason"] = "disabled"
        return result

    mode = _config_mode()

    # ─── Gate 1 : horaire marché ────────────────────────────────────────
    if not _is_market_hours():
        result["reason"] = "market_closed"
        return result

    # ─── Gate 2 : vendredi tardif ───────────────────────────────────────
    if _is_friday_late():
        result["reason"] = "friday_late"
        return result

    # ─── Gate 3 : kill switch global ────────────────────────────────────
    if _is_kill_switch_active():
        result["reason"] = "kill_switch_active"
        return result

    # ─── Gate 4 : FOMC/CPI window ───────────────────────────────────────
    fomc_veto = _veto_fomc_cpi()
    if fomc_veto:
        result["reason"] = f"veto_global: {fomc_veto}"
        return result

    # ─── Gate 5 : daily loss ────────────────────────────────────────────
    if await _is_daily_loss_exceeded():
        result["reason"] = "daily_loss_exceeded"
        return result

    # ─── Fetch positions, count open ────────────────────────────────────
    pos_data = await _fetch_positions()
    if not pos_data.get("ok"):
        result["reason"] = "bridge_positions_ko"
        return result
    open_positions = pos_data.get("positions", [])
    n_open = len(open_positions)

    if n_open >= MAX_POSITIONS:
        result["reason"] = f"max_positions_reached ({n_open}/{MAX_POSITIONS})"
        return result

    # ─── Candidats : univers moins tickers déjà en position ─────────────
    already_held = {p.get("symbol", "").upper() for p in open_positions}
    candidates = [t for t in UNIVERSE if t not in already_held]

    actions: list[dict] = []
    for ticker in candidates:
        # Veto earnings par ticker
        veto = _veto_earnings(ticker)
        if veto:
            actions.append({"ticker": ticker, "verdict": "VETO", "reason": veto})
            continue

        # Fetch prix
        tick = await _fetch_tick(ticker)
        if tick is None:
            actions.append({"ticker": ticker, "verdict": "SKIP", "reason": "no_tick"})
            continue

        last = tick.get("last") or tick.get("ask")
        if not last:
            actions.append({"ticker": ticker, "verdict": "SKIP", "reason": "no_price"})
            continue

        last = float(last)
        qty = _size_qty(last)
        if qty <= 0:
            actions.append({"ticker": ticker, "verdict": "SKIP", "reason": f"capital insuffisant ({last:.2f} USD/action)"})
            continue

        entry = last
        sl = round(entry * (1 - SL_PCT / 100), 2)
        tp = round(entry * (1 + TP_PCT / 100), 2)

        action = {
            "ticker": ticker,
            "verdict": "TAKE",
            "direction": "buy",
            "qty": qty,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "notional_usd": round(qty * entry, 2),
            "mode": mode,
        }

        if mode == "dry_run":
            # Log seulement, pas d'ordre
            action["executed"] = False
            action["reason"] = "dry_run"
            _opened_today[ticker] = action  # trace pour friday close simulation
        else:
            # LIVE : POST bridge
            try:
                payload = {
                    "pair": ticker,
                    "direction": "buy",
                    "qty": qty,
                    "sl": sl,
                    "tp": tp,
                    "dry_run": False,
                }
                async with httpx.AsyncClient(timeout=30.0) as c:
                    r = await c.post(f"{BRIDGE_URL}/order", json=payload, headers=_headers())
                body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                if r.status_code == 200 and body.get("ok"):
                    action["executed"] = True
                    action["order_id"] = body.get("order_id")
                    _opened_today[ticker] = action
                else:
                    action["executed"] = False
                    action["reason"] = f"bridge_http_{r.status_code}: {str(body)[:200]}"
            except Exception as e:
                action["executed"] = False
                action["reason"] = f"exception: {e}"

        actions.append(action)

        # On ne prend qu'une seule entrée par cycle pour éviter d'ouvrir 5
        # positions d'un coup si tous les tickers passent les filtres.
        if action.get("executed") or mode == "dry_run":
            break

    # ─── Reporting Telegram ─────────────────────────────────────────────
    await _report_cycle(mode, n_open, candidates, actions)

    result["ran"] = True
    result["actions"] = actions
    return result


async def _report_cycle(mode: str, n_open: int, candidates: list, actions: list) -> None:
    """Résumé Telegram concis."""
    if not actions:
        return  # cycles silencieux si rien d'intéressant

    # Format HTML compact
    taken = [a for a in actions if a.get("verdict") == "TAKE"]
    vetoed = [a for a in actions if a.get("verdict") == "VETO"]
    skipped = [a for a in actions if a.get("verdict") == "SKIP"]

    lines = [f"🔄 <b>auto_trader</b> [{mode}] cycle"]
    lines.append(f"Positions ouvertes: {n_open}/{MAX_POSITIONS}")
    lines.append(f"Univers scanné: {', '.join(candidates)}")

    if vetoed:
        lines.append(f"\nVetos:")
        for v in vetoed:
            lines.append(f"  • {v['ticker']}: {v.get('reason', '')}")

    if skipped:
        lines.append(f"\nSkips:")
        for s in skipped:
            lines.append(f"  • {s['ticker']}: {s.get('reason', '')}")

    if taken:
        lines.append(f"\n<b>Actions:</b>")
        for t in taken:
            exec_tag = "✅ EXEC" if t.get("executed") else ("📋 DRY" if mode == "dry_run" else "❌ FAIL")
            lines.append(
                f"  {exec_tag} {t['direction'].upper()} {t['qty']} {t['ticker']} "
                f"@ {t['entry']:.2f} SL {t['sl']:.2f} TP {t['tp']:.2f} "
                f"(~{t['notional_usd']:.2f} USD)"
            )
            if not t.get("executed") and t.get("reason"):
                lines.append(f"     reason: {t['reason']}")

    await _send_info("\n".join(lines))


# ─── Friday force-close ─────────────────────────────────────────────────

async def friday_force_close() -> dict:
    """Vendredi 20h30 UTC : ferme toutes les positions auto-trader.

    Appelé par le scheduler via un trigger cron 30 20 * * 5 (fri).
    """
    if not _config_enabled():
        return {"ran": False, "reason": "disabled"}

    mode = _config_mode()
    if not _opened_today:
        return {"ran": False, "reason": "no_positions_to_close"}

    pos_data = await _fetch_positions()
    if not pos_data.get("ok"):
        return {"ran": False, "reason": "bridge_ko"}

    held = {p.get("symbol", "").upper(): float(p.get("position") or 0)
            for p in pos_data.get("positions", [])}

    closed = []
    for ticker in list(_opened_today.keys()):
        qty_held = held.get(ticker, 0)
        if qty_held <= 0:
            # Déjà fermé (SL ou TP atteint)
            _opened_today.pop(ticker, None)
            continue

        action = {"ticker": ticker, "qty": int(qty_held), "mode": mode}
        if mode == "dry_run":
            action["executed"] = False
            action["reason"] = "dry_run"
        else:
            try:
                payload = {"pair": ticker, "direction": "sell", "qty": int(qty_held), "dry_run": False}
                async with httpx.AsyncClient(timeout=30.0) as c:
                    r = await c.post(f"{BRIDGE_URL}/order", json=payload, headers=_headers())
                body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                action["executed"] = r.status_code == 200 and bool(body.get("ok"))
                action["reason"] = str(body)[:200]
            except Exception as e:
                action["executed"] = False
                action["reason"] = f"exception: {e}"

        closed.append(action)
        _opened_today.pop(ticker, None)

    if closed:
        lines = [f"🔚 <b>auto_trader</b> [{mode}] Friday force-close"]
        for c in closed:
            tag = "✅" if c.get("executed") else ("📋" if mode == "dry_run" else "❌")
            lines.append(f"  {tag} SELL {c['qty']} {c['ticker']} MARKET")
            if not c.get("executed") and c.get("reason"):
                lines.append(f"     {c['reason']}")
        await _send_info("\n".join(lines))

    return {"ran": True, "closed": closed}
