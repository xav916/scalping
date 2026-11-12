"""Auto-trader IBKR v1 — pipeline end-to-end sans intervention humaine.

Chaîne : screener → vetos → budget → risk → exec via bridge IBKR.

## Status

**OFF par défaut** (``AUTO_TRADER_ENABLED=false``). Même quand on l'allume,
le mode par défaut est ``dry_run`` : chaque cycle est logué + poussé sur
Telegram, mais aucun ordre réel ne part.

En ``dry_run``, les positions virtuelles sont persistées dans
``AUTO_TRADER_STATE_PATH`` (défaut ``/app/data/auto_trader_state.json``) et
le code **simule les touches SL/TP** sur les prix live à chaque cycle. Les
gates ``MAX_POSITIONS`` et ``MAX_DAILY_LOSS_EUR`` mordent sur ces positions
virtuelles — le comportement est donc **iso live** sauf qu'aucun ordre réel
ne part et aucune commission n'est payée.

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

## Simulation SL/TP (dry_run)

À chaque cycle, pour chaque position virtuelle ouverte, on fetch le prix
courant via ``/tick/{ticker}``. Si last <= SL → position close au SL, si
last >= TP → close au TP. Approximation (polling 5min peut rater des wicks
intra-période) mais fournit un backtest live réaliste.

Le PnL simulé = somme des PnL réalisés aujourd'hui + somme des PnL non
réalisés (entry vs current) des positions ouvertes.

## Friday force-close

Vendredi 19:30 UTC : toutes les positions ouvertes (réelles en live,
virtuelles en dry_run) sont fermées au MARKET SELL (live) ou au prix spot
courant (dry_run). Évite le gap weekend.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
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
STATE_PATH = os.getenv("AUTO_TRADER_STATE_PATH", "/app/data/auto_trader_state.json")


# ─── État persisté JSON ─────────────────────────────────────────────────
#
# Structure :
# {
#   "opening_date_utc": "2026-11-11",
#   "opening_net_liq_eur": 99.67,        # pour daily PnL live (mémoire)
#   "disabled_until_tomorrow": false,
#   "virtual_positions": [                # dry_run seulement
#     {
#       "ticker": "F", "qty": 1,
#       "entry_price": 12.16, "sl": 11.92, "tp": 12.65,
#       "entry_time_utc": "2026-11-11T19:42:00+00:00",
#       "status": "open" | "closed_sl" | "closed_tp" | "closed_friday",
#       "exit_price": null, "exit_time_utc": null,
#       "pnl_usd": null
#     }, ...
#   ]
# }


def _load_state() -> dict:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning("auto_trader: load_state failed — %s", e)
        return {}


def _save_state(state: dict) -> None:
    try:
        p = pathlib.Path(STATE_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(p) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, STATE_PATH)
    except Exception as e:
        logger.warning("auto_trader: save_state failed — %s", e)


def _ensure_daily_reset(state: dict, today_utc: str) -> dict:
    """Si on change de jour, reset les compteurs journaliers mais garde l'historique."""
    if state.get("opening_date_utc") != today_utc:
        state["opening_date_utc"] = today_utc
        state["opening_net_liq_eur"] = None
        state["disabled_until_tomorrow"] = False
    state.setdefault("virtual_positions", [])
    return state


def _virtual_open_positions(state: dict) -> list[dict]:
    return [p for p in state.get("virtual_positions", []) if p.get("status") == "open"]


def _virtual_closed_today(state: dict) -> list[dict]:
    today = state.get("opening_date_utc", "")
    return [
        p for p in state.get("virtual_positions", [])
        if p.get("status") != "open"
        and (p.get("exit_time_utc") or "").startswith(today)
    ]


def _virtual_realized_pnl_today_usd(state: dict) -> float:
    return round(sum(float(p.get("pnl_usd") or 0) for p in _virtual_closed_today(state)), 4)


# ─── Safety gates ───────────────────────────────────────────────────────

def _is_market_hours() -> bool:
    now = datetime.now(ZoneInfo("Europe/Paris"))
    if now.weekday() >= 5:
        return False
    if now.hour < 15 or now.hour >= 22:
        return False
    if now.hour == 15 and now.minute < 30:
        return False
    return True


def _is_friday_late() -> bool:
    now_utc = datetime.now(timezone.utc)
    if now_utc.weekday() != 4:
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


def _tick_price(tick: dict) -> float | None:
    for k in ("last", "mid", "ask"):
        v = tick.get(k)
        if v:
            return float(v)
    return None


# ─── Simulation SL/TP sur positions virtuelles ──────────────────────────

async def _simulate_virtual_sl_tp(state: dict) -> list[dict]:
    """Pour chaque position virtuelle ouverte, fetch prix et check SL/TP.

    Retourne la liste des positions FERMÉES pendant ce cycle (pour log).
    Mute ``state["virtual_positions"]`` en place.
    """
    closed_this_cycle = []
    now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for p in state.get("virtual_positions", []):
        if p.get("status") != "open":
            continue

        tick = await _fetch_tick(p["ticker"])
        if tick is None:
            continue
        last = _tick_price(tick)
        if not last:
            continue

        entry = float(p["entry_price"])
        qty = int(p["qty"])
        sl = float(p["sl"])
        tp = float(p["tp"])

        exit_price = None
        new_status = None
        if last <= sl:
            exit_price = sl
            new_status = "closed_sl"
        elif last >= tp:
            exit_price = tp
            new_status = "closed_tp"

        if new_status:
            p["status"] = new_status
            p["exit_price"] = exit_price
            p["exit_time_utc"] = now_utc
            p["pnl_usd"] = round((exit_price - entry) * qty, 4)
            p["last_seen_price"] = last
            closed_this_cycle.append(p)
        else:
            # track last seen price pour le PnL non-réalisé
            p["last_seen_price"] = last

    return closed_this_cycle


def _virtual_unrealized_pnl_usd(state: dict) -> float:
    total = 0.0
    for p in _virtual_open_positions(state):
        last = p.get("last_seen_price")
        if last is None:
            continue
        total += (float(last) - float(p["entry_price"])) * int(p["qty"])
    return round(total, 4)


# ─── Vetos ──────────────────────────────────────────────────────────────

def _veto_earnings(ticker: str) -> str | None:
    try:
        from backend.services import earnings_calendar_service as _ec
        hours_to = _ec.hours_to_next_earnings(ticker)
        if hours_to is not None and abs(hours_to) < EARNINGS_VETO_HOURS:
            return f"earnings dans {hours_to:+.1f}h"
    except Exception:
        pass
    return None


def _veto_fomc_cpi() -> str | None:
    try:
        from backend.services import economic_calendar_veto as _ecv
        active = _ecv.is_high_impact_window(window_minutes=FOMC_VETO_MINUTES)
        if active:
            return "FOMC/CPI window active"
    except Exception:
        pass
    return None


# ─── Daily loss checker ─────────────────────────────────────────────────

async def _is_daily_loss_exceeded(state: dict, mode: str) -> tuple[bool, dict]:
    """Retourne (dépassé?, state mis à jour).

    En mode live : compare net_liquidation IBKR vs opening.
    En mode dry_run : utilise le PnL simulé (réalisé + non réalisé en USD convert EUR).
    """
    if state.get("disabled_until_tomorrow"):
        return True, state

    if mode == "live":
        try:
            snapshot = await _fetch_account()
        except Exception as e:
            logger.warning("auto_trader: fetch_account failed, prudence → block (%s)", e)
            return True, state
        if not snapshot.get("ok"):
            return True, state

        net_liq = float(snapshot.get("NetLiquidation") or 0)
        if state.get("opening_net_liq_eur") is None:
            state["opening_net_liq_eur"] = net_liq
            logger.info("auto_trader: baseline net_liq jour = %.2f EUR", net_liq)
            return False, state

        daily_pnl = net_liq - float(state["opening_net_liq_eur"])
        if daily_pnl < -MAX_DAILY_LOSS_EUR:
            state["disabled_until_tomorrow"] = True
            logger.warning(
                "auto_trader: KILL live — daily PnL %.2f EUR < seuil -%.2f EUR",
                daily_pnl, MAX_DAILY_LOSS_EUR,
            )
            await _send_info(
                f"🚨 auto_trader [live] DÉSACTIVÉ auto\n"
                f"Daily PnL {daily_pnl:+.2f} EUR < seuil -{MAX_DAILY_LOSS_EUR:.2f}\n"
                f"Re-activer manuellement dans .env + restart"
            )
            return True, state
        return False, state

    # dry_run : PnL simulé en USD → converti en EUR
    realized_usd = _virtual_realized_pnl_today_usd(state)
    unrealized_usd = _virtual_unrealized_pnl_usd(state)
    total_usd = realized_usd + unrealized_usd
    total_eur = total_usd / EUR_USD_RATE

    if total_eur < -MAX_DAILY_LOSS_EUR:
        state["disabled_until_tomorrow"] = True
        logger.warning(
            "auto_trader: KILL dry_run — daily PnL simulé %.2f EUR < seuil -%.2f EUR",
            total_eur, MAX_DAILY_LOSS_EUR,
        )
        await _send_info(
            f"🚨 auto_trader [dry_run] DÉSACTIVÉ auto (simulé)\n"
            f"Daily PnL simulé {total_eur:+.2f} EUR < seuil -{MAX_DAILY_LOSS_EUR:.2f}\n"
            f"Réalisé: {realized_usd:+.2f} USD, non réalisé: {unrealized_usd:+.2f} USD\n"
            f"Re-activer en vidant disabled_until_tomorrow dans state JSON + restart"
        )
        return True, state
    return False, state


# ─── Helpers ────────────────────────────────────────────────────────────

async def _send_info(text: str) -> None:
    """Route le message selon le mode.

    - ``dry_run`` : canal ``demo`` (bot ``@xav_scalping_radar_bot``, préfixe
      ``[DÉMO · IC_MARKETS]`` 🟦) via ``send_info_text`` — cohérent avec le
      fait que les positions sont simulées.
    - ``live`` : canal ``ibkr`` (bot IBKR trades, préfixe ``[RÉEL · IBKR]``
      🟥) via POST direct sur l'API Telegram avec les credentials IBKR —
      les ordres partent sur le compte IBKR réel, le message doit arriver
      sur le fil IBKR pour ne pas faire croire à de la démo.

    Si le canal ``ibkr`` n'est pas configuré en mode live, repli sur
    ``send_info_text`` pour ne pas perdre le message — avec un WARNING.
    """
    try:
        from backend.services import telegram_service
        mode = _config_mode()
        if mode == "live":
            from backend.services import canaux_telegram as ct
            jeton, chat = ct.jeton_et_chat("ibkr")
            if jeton and chat:
                url = f"https://api.telegram.org/bot{jeton}/sendMessage"
                payload = {
                    "chat_id": chat,
                    "text": text[:4000],
                    "disable_web_page_preview": True,
                    "parse_mode": "HTML",
                }
                async with httpx.AsyncClient(timeout=10.0) as c:
                    r = await c.post(url, json=payload)
                if r.status_code != 200:
                    logger.warning(
                        "auto_trader: Telegram IBKR HTTP %s %s — repli demo",
                        r.status_code, r.text[:200],
                    )
                    await telegram_service.send_info_text(text, parse_mode="HTML")
            else:
                logger.warning(
                    "auto_trader: IBKR_TELEGRAM_* non configuré, repli sur canal demo"
                )
                await telegram_service.send_info_text(text, parse_mode="HTML")
        else:
            await telegram_service.send_info_text(text, parse_mode="HTML")
    except Exception as e:
        logger.warning("auto_trader: send telegram failed — %s", e)


def _usd_from_eur(eur: float) -> float:
    return eur * EUR_USD_RATE


def _size_qty(price_usd: float) -> int:
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
    today_utc = date.today().isoformat()

    # Charger état persisté + reset journalier si nouveau jour
    state = _load_state()
    state = _ensure_daily_reset(state, today_utc)

    # ─── Gate 1 : horaire marché ────────────────────────────────────────
    if not _is_market_hours():
        result["reason"] = "market_closed"
        _save_state(state)
        return result

    # ─── Gate 2 : vendredi tardif ───────────────────────────────────────
    if _is_friday_late():
        result["reason"] = "friday_late"
        _save_state(state)
        return result

    # ─── Gate 3 : kill switch global ────────────────────────────────────
    if _is_kill_switch_active():
        result["reason"] = "kill_switch_active"
        _save_state(state)
        return result

    # ─── Gate 4 : FOMC/CPI window ───────────────────────────────────────
    fomc_veto = _veto_fomc_cpi()
    if fomc_veto:
        result["reason"] = f"veto_global: {fomc_veto}"
        _save_state(state)
        return result

    # ─── Dry_run : simuler les SL/TP sur positions virtuelles ───────────
    closed_this_cycle: list[dict] = []
    if mode == "dry_run":
        closed_this_cycle = await _simulate_virtual_sl_tp(state)

    # ─── Gate 5 : daily loss ────────────────────────────────────────────
    killed, state = await _is_daily_loss_exceeded(state, mode)
    if killed:
        result["reason"] = "daily_loss_exceeded"
        _save_state(state)
        return result

    # ─── Compter positions ouvertes (réelles ou virtuelles) ─────────────
    if mode == "live":
        pos_data = await _fetch_positions()
        if not pos_data.get("ok"):
            result["reason"] = "bridge_positions_ko"
            _save_state(state)
            return result
        open_positions_syms = {p.get("symbol", "").upper() for p in pos_data.get("positions", [])}
        n_open = len(open_positions_syms)
    else:
        open_positions_syms = {p["ticker"].upper() for p in _virtual_open_positions(state)}
        n_open = len(open_positions_syms)

    if n_open >= MAX_POSITIONS:
        result["reason"] = f"max_positions_reached ({n_open}/{MAX_POSITIONS})"
        _save_state(state)
        # Reporter quand même les clôtures simulées de ce cycle
        if closed_this_cycle:
            await _report_closures(mode, closed_this_cycle, state)
        return result

    # ─── Candidats : univers moins tickers déjà en position ─────────────
    candidates = [t for t in UNIVERSE if t not in open_positions_syms]

    actions: list[dict] = []
    for ticker in candidates:
        veto = _veto_earnings(ticker)
        if veto:
            actions.append({"ticker": ticker, "verdict": "VETO", "reason": veto})
            continue

        tick = await _fetch_tick(ticker)
        if tick is None:
            actions.append({"ticker": ticker, "verdict": "SKIP", "reason": "no_tick"})
            continue

        last = _tick_price(tick)
        if not last:
            actions.append({"ticker": ticker, "verdict": "SKIP", "reason": "no_price"})
            continue

        qty = _size_qty(last)
        if qty <= 0:
            actions.append({
                "ticker": ticker, "verdict": "SKIP",
                "reason": f"capital insuffisant ({last:.2f} USD/action)",
            })
            continue

        entry = last
        sl = round(entry * (1 - SL_PCT / 100), 2)
        tp = round(entry * (1 + TP_PCT / 100), 2)

        action = {
            "ticker": ticker, "verdict": "TAKE", "direction": "buy",
            "qty": qty, "entry": entry, "sl": sl, "tp": tp,
            "notional_usd": round(qty * entry, 2), "mode": mode,
        }

        if mode == "dry_run":
            # Ajouter à la liste virtuelle persistée
            virtual_position = {
                "ticker": ticker,
                "qty": qty,
                "entry_price": entry,
                "sl": sl,
                "tp": tp,
                "entry_time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "status": "open",
                "exit_price": None,
                "exit_time_utc": None,
                "pnl_usd": None,
                "last_seen_price": entry,
            }
            state["virtual_positions"].append(virtual_position)
            action["executed"] = True  # virtuellement
            action["reason"] = "dry_run_simulated_open"
        else:
            # LIVE : POST bridge
            try:
                payload = {
                    "pair": ticker, "direction": "buy", "qty": qty,
                    "sl": sl, "tp": tp, "dry_run": False,
                }
                async with httpx.AsyncClient(timeout=30.0) as c:
                    r = await c.post(f"{BRIDGE_URL}/order", json=payload, headers=_headers())
                body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                if r.status_code == 200 and body.get("ok"):
                    action["executed"] = True
                    action["order_id"] = body.get("order_id")
                else:
                    action["executed"] = False
                    action["reason"] = f"bridge_http_{r.status_code}: {str(body)[:200]}"
            except Exception as e:
                action["executed"] = False
                action["reason"] = f"exception: {e}"

        actions.append(action)
        # Une seule entrée par cycle (break après le 1er TAKE exécuté)
        if action.get("executed"):
            break

    _save_state(state)

    # ─── Reporting Telegram ─────────────────────────────────────────────
    await _report_cycle(mode, n_open, candidates, actions, closed_this_cycle, state)

    result["ran"] = True
    result["actions"] = actions
    result["closed_this_cycle"] = closed_this_cycle
    return result


async def _report_cycle(
    mode: str, n_open: int, candidates: list, actions: list,
    closed_this_cycle: list, state: dict,
) -> None:
    """Rapport Telegram + inclut clôtures simulées + PnL simulé du jour."""
    # Silence si rien d'intéressant à dire
    if not actions and not closed_this_cycle:
        return

    taken = [a for a in actions if a.get("verdict") == "TAKE" and a.get("executed")]
    vetoed = [a for a in actions if a.get("verdict") == "VETO"]
    skipped = [a for a in actions if a.get("verdict") == "SKIP"]

    lines = [f"🔄 <b>auto_trader</b> [{mode}] cycle"]
    lines.append(f"Positions ouvertes: {n_open}/{MAX_POSITIONS}")
    lines.append(f"Univers scanné: {', '.join(candidates) if candidates else '—'}")

    if closed_this_cycle:
        lines.append("\n<b>Clôtures simulées ce cycle:</b>")
        for p in closed_this_cycle:
            reason = p.get("status", "").replace("closed_", "").upper()
            lines.append(
                f"  🏁 {reason} {p['ticker']} qty {p['qty']} @ {p['exit_price']:.2f} "
                f"(entry {p['entry_price']:.2f}) PnL {p['pnl_usd']:+.2f} USD"
            )

    if vetoed:
        lines.append("\nVetos:")
        for v in vetoed:
            lines.append(f"  • {v['ticker']}: {v.get('reason', '')}")

    if skipped:
        lines.append("\nSkips:")
        for s in skipped:
            lines.append(f"  • {s['ticker']}: {s.get('reason', '')}")

    if taken:
        lines.append("\n<b>Actions:</b>")
        for t in taken:
            exec_tag = "📋 DRY" if mode == "dry_run" else "✅ EXEC"
            lines.append(
                f"  {exec_tag} {t['direction'].upper()} {t['qty']} {t['ticker']} "
                f"@ {t['entry']:.2f} SL {t['sl']:.2f} TP {t['tp']:.2f} "
                f"(~{t['notional_usd']:.2f} USD)"
            )

    # Toujours montrer le PnL simulé du jour en dry_run
    if mode == "dry_run":
        realized = _virtual_realized_pnl_today_usd(state)
        unrealized = _virtual_unrealized_pnl_usd(state)
        total_eur = (realized + unrealized) / EUR_USD_RATE
        n_virt_open = len(_virtual_open_positions(state))
        n_virt_closed_today = len(_virtual_closed_today(state))
        lines.append(
            f"\n<b>PnL simulé jour:</b> {total_eur:+.2f} EUR "
            f"(réalisé {realized:+.2f} + non réalisé {unrealized:+.2f} USD)"
        )
        lines.append(
            f"Positions virtuelles: {n_virt_open} ouvertes, "
            f"{n_virt_closed_today} fermées aujourd'hui"
        )

    await _send_info("\n".join(lines))


async def _report_closures(mode: str, closed_this_cycle: list, state: dict) -> None:
    """Rapport dédié aux clôtures quand on skip le cycle (max_positions)."""
    if not closed_this_cycle:
        return
    lines = [f"🏁 <b>auto_trader</b> [{mode}] clôtures simulées"]
    for p in closed_this_cycle:
        reason = p.get("status", "").replace("closed_", "").upper()
        lines.append(
            f"  {reason} {p['ticker']} qty {p['qty']} @ {p['exit_price']:.2f} "
            f"(entry {p['entry_price']:.2f}) PnL {p['pnl_usd']:+.2f} USD"
        )
    if mode == "dry_run":
        realized = _virtual_realized_pnl_today_usd(state)
        total_eur = realized / EUR_USD_RATE
        lines.append(f"\nRéalisé jour simulé: {total_eur:+.2f} EUR ({realized:+.2f} USD)")
    await _send_info("\n".join(lines))


# ─── Friday force-close ─────────────────────────────────────────────────

async def friday_force_close() -> dict:
    """Vendredi 19:30 UTC : ferme toutes les positions auto-trader.

    En live : MARKET SELL des positions ouvertes auto-trader (bridge /order).
    En dry_run : clôture virtuelle au prix spot courant (pour éviter gap weekend).
    """
    if not _config_enabled():
        return {"ran": False, "reason": "disabled"}

    mode = _config_mode()
    state = _load_state()
    state = _ensure_daily_reset(state, date.today().isoformat())

    closed = []
    now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if mode == "dry_run":
        # Fermer toutes les positions virtuelles ouvertes au prix spot
        for p in state.get("virtual_positions", []):
            if p.get("status") != "open":
                continue
            tick = await _fetch_tick(p["ticker"])
            if tick is None:
                # Fallback : entrée = sortie (PnL 0)
                exit_price = float(p["entry_price"])
            else:
                exit_price = _tick_price(tick) or float(p["entry_price"])
            qty = int(p["qty"])
            entry = float(p["entry_price"])
            p["status"] = "closed_friday"
            p["exit_price"] = round(exit_price, 2)
            p["exit_time_utc"] = now_utc
            p["pnl_usd"] = round((exit_price - entry) * qty, 4)
            closed.append(p)
        _save_state(state)
    else:
        # LIVE : SELL market pour chaque position IBKR connue
        pos_data = await _fetch_positions()
        if not pos_data.get("ok"):
            return {"ran": False, "reason": "bridge_ko"}
        for pos in pos_data.get("positions", []):
            ticker = pos.get("symbol", "").upper()
            qty_held = float(pos.get("position") or 0)
            if qty_held <= 0:
                continue
            payload = {
                "pair": ticker, "direction": "sell", "qty": int(qty_held),
                "dry_run": False,
            }
            try:
                async with httpx.AsyncClient(timeout=30.0) as c:
                    r = await c.post(f"{BRIDGE_URL}/order", json=payload, headers=_headers())
                body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                closed.append({
                    "ticker": ticker, "qty": int(qty_held),
                    "executed": r.status_code == 200 and bool(body.get("ok")),
                    "reason": str(body)[:200],
                })
            except Exception as e:
                closed.append({"ticker": ticker, "qty": int(qty_held),
                               "executed": False, "reason": f"exception: {e}"})

    # Rapport Telegram
    if closed:
        lines = [f"🔚 <b>auto_trader</b> [{mode}] Friday force-close"]
        if mode == "dry_run":
            for p in closed:
                lines.append(
                    f"  🏁 FRIDAY {p['ticker']} qty {p['qty']} @ {p['exit_price']:.2f} "
                    f"(entry {p['entry_price']:.2f}) PnL {p['pnl_usd']:+.2f} USD"
                )
            realized_usd = _virtual_realized_pnl_today_usd(state)
            # Compute total realized this week (all closed positions in state)
            week_realized_usd = round(
                sum(float(p.get("pnl_usd") or 0) for p in state.get("virtual_positions", [])
                    if p.get("status") != "open"),
                4,
            )
            lines.append(
                f"\nRéalisé jour simulé: {realized_usd:+.2f} USD "
                f"({realized_usd / EUR_USD_RATE:+.2f} EUR)"
            )
            lines.append(
                f"Réalisé semaine simulé (toutes positions historiques): "
                f"{week_realized_usd:+.2f} USD ({week_realized_usd / EUR_USD_RATE:+.2f} EUR)"
            )
        else:
            for c in closed:
                tag = "✅" if c.get("executed") else "❌"
                lines.append(f"  {tag} SELL {c['qty']} {c['ticker']} MARKET")
                if not c.get("executed") and c.get("reason"):
                    lines.append(f"     {c['reason']}")
        await _send_info("\n".join(lines))

    return {"ran": True, "closed": closed}


# ─── Recap quotidien (optionnel, à appeler depuis scheduler si voulu) ────

async def daily_recap() -> dict:
    """Rapport Telegram récapitulatif à la fermeture NYSE (22h Paris)."""
    if not _config_enabled():
        return {"ran": False, "reason": "disabled"}
    mode = _config_mode()
    state = _load_state()
    today_utc = date.today().isoformat()
    state = _ensure_daily_reset(state, today_utc)

    closed_today = _virtual_closed_today(state)
    open_virt = _virtual_open_positions(state)

    if not closed_today and not open_virt:
        return {"ran": False, "reason": "nothing_to_report"}

    realized_usd = _virtual_realized_pnl_today_usd(state) if mode == "dry_run" else 0.0
    unrealized_usd = _virtual_unrealized_pnl_usd(state) if mode == "dry_run" else 0.0
    total_usd = realized_usd + unrealized_usd
    total_eur = total_usd / EUR_USD_RATE

    lines = [f"📊 <b>auto_trader</b> [{mode}] recap quotidien {today_utc}"]
    lines.append(f"Positions encore ouvertes: {len(open_virt)}")
    lines.append(f"Positions fermées aujourd'hui: {len(closed_today)}")

    if mode == "dry_run":
        lines.append(f"\nPnL simulé: {total_eur:+.2f} EUR")
        lines.append(f"  Réalisé: {realized_usd:+.2f} USD")
        lines.append(f"  Non réalisé: {unrealized_usd:+.2f} USD")

        if closed_today:
            tp_count = sum(1 for p in closed_today if p["status"] == "closed_tp")
            sl_count = sum(1 for p in closed_today if p["status"] == "closed_sl")
            friday_count = sum(1 for p in closed_today if p["status"] == "closed_friday")
            lines.append(f"\nBreakdown: TP={tp_count}, SL={sl_count}, Friday={friday_count}")
            lines.append("Détail:")
            for p in closed_today:
                reason = p["status"].replace("closed_", "").upper()
                lines.append(
                    f"  {reason} {p['ticker']} qty {p['qty']}: "
                    f"{p['entry_price']:.2f} → {p['exit_price']:.2f} "
                    f"= {p['pnl_usd']:+.2f} USD"
                )

    await _send_info("\n".join(lines))
    return {"ran": True}
