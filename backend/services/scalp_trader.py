"""Scalping intraday RSI/ATR pour viser ~15-30 setups/jour.

Stratégie contre-trend sur extremes RSI, sur bougies 1min, avec SL/TP
basés sur ATR. Pensée pour tourner **en parallèle de meanrev momentum**
sur IC Markets demo (bridge 8787).

## Design

Sur chaque bougie 1min terminée, pour chaque paire de ``SCALP_UNIVERSE`` :
- Calcul RSI(14) et ATR(14) sur les 20 dernières bougies 1min
- **Signal LONG** : ``RSI < 30`` ET bougie courante haussière
  (``close > open``) — reversion après baisse
- **Signal SHORT** : ``RSI > 70`` ET bougie courante baissière — reversion
  après hausse

Entry = prix marché, SL = ``entry ± SL_ATR_MULT × ATR``,
TP = ``entry ± SL_ATR_MULT × TP_R_MULT × ATR`` (R:R 1.5 par défaut).

## Gates (fail-closed)

1. ``SCALP_ENABLED`` → skip silencieux
2. Forex hours (dim 22h UTC → ven 22h UTC)
3. Blackout vendredi ``SCALP_FRIDAY_LATE_BLOCK_UTC``
4. Kill switch global
5. Daily loss cap ``SCALP_MAX_DAILY_LOSS_EUR``
6. Max positions ``SCALP_MAX_POSITIONS``

## Mode & routing

- ``dry_run`` : positions virtuelles persistées, pas d'ordre MT5
- ``live`` : ordres MT5 via bridge ``SCALP_BRIDGE_URL``

Telegram :
- dry_run OR ``SCALP_ACCOUNT_IS_DEMO=true`` → canal demo 🟦
- live + account_is_demo=false → canal ic_markets 🟩
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import pathlib
from datetime import date, datetime, time, timedelta, timezone
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
    return _env_bool("SCALP_ENABLED", "false")


def _config_mode() -> str:
    mode = os.getenv("SCALP_MODE", "dry_run").strip().lower()
    return mode if mode in ("dry_run", "live") else "dry_run"


BRIDGE_URL = os.getenv("SCALP_BRIDGE_URL", "http://100.74.160.72:8787").rstrip("/")
# Fallback sur MT5_BRIDGE_API_KEY (cf PR #26 meanrev) si SCALP_BRIDGE_API_KEY vide.
BRIDGE_KEY = os.getenv("SCALP_BRIDGE_API_KEY") or os.getenv("MT5_BRIDGE_API_KEY", "")
ACCOUNT_IS_DEMO = _env_bool("SCALP_ACCOUNT_IS_DEMO", "true")
SCALP_DESTINATION_ID = "admin_legacy" if ACCOUNT_IS_DEMO else "admin_live"

UNIVERSE = [
    p.strip().upper() for p in os.getenv(
        "SCALP_UNIVERSE", "XAU/USD,EUR/USD,GBP/USD,USD/JPY"
    ).split(",") if p.strip()
]

MAX_DAILY_LOSS_EUR = _env_float("SCALP_MAX_DAILY_LOSS_EUR", 15.0)
MAX_POSITIONS = _env_int("SCALP_MAX_POSITIONS", 10)
RISK_PCT = _env_float("SCALP_RISK_PCT", 0.25) / 100.0  # 0.25% default
RSI_PERIOD = _env_int("SCALP_RSI_PERIOD", 14)
RSI_LONG_THR = _env_float("SCALP_RSI_LONG_THR", 30.0)
RSI_SHORT_THR = _env_float("SCALP_RSI_SHORT_THR", 70.0)
SL_ATR_MULT = _env_float("SCALP_SL_ATR_MULT", 1.0)
TP_R_MULT = _env_float("SCALP_TP_R_MULT", 1.5)
ATR_PERIOD = _env_int("SCALP_ATR_PERIOD", 14)
# Si ``true``, la direction détectée par ``_detect_signal`` est inversée
# (RSI oversold + bougie reversal haussière donne SELL au lieu de BUY).
# Transforme la logique mean reversion en momentum / continuation : on
# parie que le mouvement récent continue au lieu de retourner vers la
# moyenne. Flag miroir de ``MEANREV_INVERT_DIRECTION`` (PR #23).
INVERT_DIRECTION = _env_bool("SCALP_INVERT_DIRECTION", "false")
# Quand ``INVERT_DIRECTION=true``, le TP par défaut (atr × R_MULT) devient
# incohérent (il part du mauvais côté) : on utilise un R:R symétrique
# fixe depuis la distance SL. Multiplicateur configurable ici.
MOMENTUM_TP_R_MULT = _env_float("SCALP_MOMENTUM_TP_R_MULT", 2.0)
TIME_STOP_MINUTES = _env_int("SCALP_TIME_STOP_MINUTES", 60)
FRIDAY_LATE_BLOCK_UTC = os.getenv("SCALP_FRIDAY_LATE_BLOCK_UTC", "19:30")
SCAN_INTERVAL_SEC = _env_int("SCALP_SCAN_INTERVAL_SEC", 60)
POLL_INTERVAL_SEC = SCAN_INTERVAL_SEC  # alias exposé au scheduler
STATE_PATH = os.getenv("SCALP_STATE_PATH", "/app/data/scalp_state.json")
EUR_USD_RATE = _env_float("SCALP_EUR_USD_FIXED", 1.07)


# ─── Persistance JSON ───────────────────────────────────────────────────

def _load_state() -> dict:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning("scalp: load_state failed — %s", e)
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
        logger.warning("scalp: save_state failed — %s", e)


def _ensure_daily_reset(state: dict, today_utc: str) -> dict:
    if state.get("opening_date_utc") != today_utc:
        state["opening_date_utc"] = today_utc
        state["opening_balance_eur"] = None
        state["disabled_until_tomorrow"] = False
        state["bridge_alert_sent_today"] = False
    state.setdefault("open_positions", [])
    state.setdefault("closed_history", [])
    return state


def _open_positions(state: dict) -> list[dict]:
    return [p for p in state.get("open_positions", []) if p.get("status") == "open"]


def _closed_today(state: dict) -> list[dict]:
    today = state.get("opening_date_utc", "")
    return [
        p for p in state.get("closed_history", [])
        if (p.get("exit_time_utc") or "").startswith(today)
    ]


def _realized_pnl_today_usd(state: dict) -> float:
    return round(sum(float(p.get("pnl_usd") or 0) for p in _closed_today(state)), 4)


# ─── Safety gates ───────────────────────────────────────────────────────

def _is_forex_hours() -> bool:
    """Forex est ouvert dim 22h UTC → ven 22h UTC."""
    now = datetime.now(timezone.utc)
    wd = now.weekday()  # 0=lundi, 6=dimanche
    h = now.hour
    if wd == 5:  # samedi
        return False
    if wd == 6 and h < 22:  # dimanche avant 22h UTC
        return False
    if wd == 4 and h >= 22:  # vendredi après 22h UTC
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


# ─── Bridge calls (via meanrev helpers quand possible) ──────────────────

def _headers() -> dict[str, str]:
    if not BRIDGE_KEY:
        return {}
    # Compatible avec IBKR (X-Bridge-Key) et MT5 (X-API-Key) bridges.
    return {"X-API-Key": BRIDGE_KEY, "X-Bridge-Key": BRIDGE_KEY}


async def _mt5_fetch_balance() -> float | None:
    """GET /account → retourne balance (devise native du compte) ou None."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{BRIDGE_URL}/account", headers=_headers())
            if r.status_code != 200:
                logger.warning("scalp: /account HTTP %s", r.status_code)
                return None
            data = r.json()
            bal = data.get("balance") or data.get("Balance") or 0
            return float(bal) if bal else None
    except Exception as e:
        logger.warning("scalp: fetch_balance failed — %s", e)
        return None


async def _mt5_fetch_tick(pair: str) -> dict | None:
    """GET /tick/<pair> → retourne {bid, ask, ...} ou None."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{BRIDGE_URL}/tick/{pair}", headers=_headers())
            if r.status_code != 200:
                return None
            return r.json()
    except Exception as e:
        logger.warning("scalp: fetch_tick %s failed — %s", pair, e)
        return None


async def _mt5_submit_order(
    pair: str, direction: str, lots: float, sl: float, tp: float, entry: float,
) -> dict:
    """POST /order → retourne dict avec ok, ticket, fill_price."""
    payload = {
        "pair": pair, "direction": direction, "lots": lots,
        "entry": entry, "sl": sl, "tp": tp, "dry_run": False,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(f"{BRIDGE_URL}/order", json=payload, headers=_headers())
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:200]}
        return {
            "ok": r.status_code == 200 and bool(body.get("ok")),
            "status_code": r.status_code,
            "ticket": body.get("ticket") or body.get("order_id"),
            "avg_fill_price": body.get("avg_fill_price") or body.get("price") or body.get("fill_price"),
            "body": body,
        }
    except Exception as e:
        return {"ok": False, "exception": str(e)}


async def _mt5_close_position(ticket: int) -> dict:
    """POST /close → ferme une position par ticket."""
    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.post(
                f"{BRIDGE_URL}/close", json={"ticket": ticket},
                headers=_headers(),
            )
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:200]}
        return {
            "ok": r.status_code == 200 and bool(body.get("ok")),
            "exit_price": body.get("close_price") or body.get("price"),
            "body": body,
        }
    except Exception as e:
        return {"ok": False, "exception": str(e)}


# ─── Indicateurs RSI + ATR ──────────────────────────────────────────────

def _compute_rsi(candles, period: int = 14) -> float | None:
    """RSI classique de Wilder sur ``period`` bougies. None si < period+1 candles."""
    if len(candles) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        delta = candles[i].close - candles[i - 1].close
        if delta > 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(candles)):
        delta = candles[i].close - candles[i - 1].close
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _compute_atr(candles, period: int = 14) -> float | None:
    """ATR de Wilder. None si pas assez de bougies."""
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        high = candles[i].high
        low = candles[i].low
        prev_close = candles[i - 1].close
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if len(trs) < period:
        return None
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


# ─── Sizing + contract size (importés de meanrev) ───────────────────────

def _contract_size(pair: str) -> int:
    """Taille du contrat MT5 par classe d'asset. Importé de meanrev_trader
    pour éviter la duplication mais fallback local si meanrev pas chargé.
    """
    try:
        from backend.services.meanrev_trader import _contract_size as _cs
        return _cs(pair)
    except Exception:
        # Fallback minimal
        p = pair.upper()
        if any(m in p for m in ("XAU", "XAG", "XPT", "XPD")):
            return 100
        if any(c in p for c in ("BTC", "ETH", "SOL", "BNB")):
            return 1
        return 100000


def _size_lots_from_risk(balance_eur: float, entry: float, sl: float, pair: str) -> float:
    distance = abs(entry - sl)
    if distance <= 0 or balance_eur <= 0:
        return 0.0
    risk_money_eur = balance_eur * RISK_PCT
    risk_money_usd = risk_money_eur * EUR_USD_RATE
    cs = _contract_size(pair)
    lots_raw = risk_money_usd / (distance * cs)
    lots = math.floor(lots_raw * 100) / 100  # arrondi 0.01 (lot min MT5)
    return max(0.0, lots)


# ─── Détection signal ───────────────────────────────────────────────────

def _detect_signal(candles_1min: list, pair: str) -> dict | None:
    """Détecte un signal scalping à partir de bougies 1min.

    Returns dict ``{direction, entry, sl, tp, atr, rsi}`` ou None si pas de signal.
    """
    if len(candles_1min) < max(RSI_PERIOD, ATR_PERIOD) + 2:
        return None

    rsi = _compute_rsi(candles_1min, RSI_PERIOD)
    atr = _compute_atr(candles_1min, ATR_PERIOD)
    if rsi is None or atr is None or atr <= 0:
        return None

    last = candles_1min[-1]
    entry = float(last.close)

    # Direction MR (défaut) : RSI oversold + haussière → BUY (retour mean)
    # Direction momentum (INVERT) : même détection → SELL (continuation)
    mr_direction = None
    if rsi < RSI_LONG_THR and last.close > last.open:
        mr_direction = "buy"
    elif rsi > RSI_SHORT_THR and last.close < last.open:
        mr_direction = "sell"
    if mr_direction is None:
        return None

    direction = mr_direction
    if INVERT_DIRECTION:
        direction = "sell" if mr_direction == "buy" else "buy"

    if direction == "buy":
        sl = round(entry - SL_ATR_MULT * atr, 5)
        if INVERT_DIRECTION:
            # TP = R:R momentum depuis distance SL
            tp = round(entry + MOMENTUM_TP_R_MULT * (entry - sl), 5)
        else:
            tp = round(entry + SL_ATR_MULT * TP_R_MULT * atr, 5)
    else:  # sell
        sl = round(entry + SL_ATR_MULT * atr, 5)
        if INVERT_DIRECTION:
            tp = round(entry - MOMENTUM_TP_R_MULT * (sl - entry), 5)
        else:
            tp = round(entry - SL_ATR_MULT * TP_R_MULT * atr, 5)

    return {
        "direction": direction, "entry": entry, "sl": sl, "tp": tp, "sl_initial": sl,
        "atr": atr, "rsi": rsi, "pair": pair,
    }


# ─── Telegram helpers ───────────────────────────────────────────────────

async def _send_info(text: str) -> None:
    """Route selon mode + ACCOUNT_IS_DEMO (voir meanrev PR #28)."""
    try:
        from backend.services import telegram_service
        mode = _config_mode()
        route_to_real = (mode == "live") and (not ACCOUNT_IS_DEMO)
        if route_to_real:
            delivered = await telegram_service.send_sales_text(text, parse_mode="HTML")
            if not delivered:
                await telegram_service.send_info_text(text, parse_mode="HTML")
        else:
            await telegram_service.send_info_text(text, parse_mode="HTML")
    except Exception as e:
        logger.warning("scalp: send telegram failed — %s", e)


async def _send_trade_opened_rich(
    pair: str, direction: str, entry: float, sl: float, tp: float,
    volume: float, ticket: int | str,
) -> None:
    """Carte riche OPEN via telegram_service.send_trade_opened."""
    try:
        import types
        from backend.services import telegram_service
        setup = types.SimpleNamespace(
            pair=pair, direction=direction,
            entry_price=entry, stop_loss=sl, take_profit_1=tp,
        )
        await telegram_service.send_trade_opened(
            setup=setup, ticket=ticket, fill_price=entry, volume=volume,
            mode=_config_mode(), destination_id=SCALP_DESTINATION_ID,
        )
    except Exception as e:
        logger.warning("scalp: send_trade_opened failed — %s", e)


async def _send_close_rich(
    pair: str, direction: str, entry: float, close_price: float,
    profit_loss: float, volume: float, ticket: int | str, reason: str,
) -> None:
    """Carte riche CLOSE via telegram_service.send_close."""
    try:
        from backend.services import telegram_service
        trade = {
            "pair": pair, "direction": direction,
            "entry_price": entry, "close_price": close_price,
            "profit_loss": profit_loss, "volume": volume,
            "mt5_ticket": ticket, "close_reason": reason,
        }
        await telegram_service.send_close(
            trade=trade, destination_id=SCALP_DESTINATION_ID,
        )
    except Exception as e:
        logger.warning("scalp: send_close failed — %s", e)


# ─── Daily loss check ───────────────────────────────────────────────────

async def _check_daily_loss(state: dict, mode: str) -> tuple[bool, dict]:
    """Retourne (dépassé?, state). Daily loss sur PnL réalisé + non réalisé."""
    if state.get("disabled_until_tomorrow"):
        return True, state

    realized_usd = _realized_pnl_today_usd(state)
    unrealized_usd = 0.0
    for p in _open_positions(state):
        last = p.get("last_seen_price")
        if last is None:
            continue
        entry = float(p["entry"])
        lots = float(p["lots"])
        cs = _contract_size(p["pair"])
        if p["direction"] == "buy":
            unrealized_usd += (float(last) - entry) * cs * lots
        else:
            unrealized_usd += (entry - float(last)) * cs * lots

    total_usd = realized_usd + unrealized_usd
    total_eur = total_usd / EUR_USD_RATE
    if total_eur < -MAX_DAILY_LOSS_EUR:
        state["disabled_until_tomorrow"] = True
        await _send_info(
            f"🚨 <b>scalp</b> [{mode}] DÉSACTIVÉ auto\n"
            f"Daily PnL {total_eur:+.2f} EUR < seuil -{MAX_DAILY_LOSS_EUR:.2f}\n"
            f"Réalisé: {realized_usd:+.2f} USD, non réalisé: {unrealized_usd:+.2f} USD"
        )
        return True, state
    return False, state


# ─── Cycle principal ────────────────────────────────────────────────────

async def cycle() -> dict:
    """Un cycle scalp. Appelé toutes les SCAN_INTERVAL_SEC par le scheduler."""
    result = {"ran": False, "reason": None, "actions": []}

    if not _config_enabled():
        result["reason"] = "disabled"
        return result

    mode = _config_mode()
    today_utc = date.today().isoformat()
    state = _load_state()
    state = _ensure_daily_reset(state, today_utc)

    # Gate 1 : forex hours
    if not _is_forex_hours():
        result["reason"] = "forex_closed"
        _save_state(state)
        return result

    # Gate 2 : vendredi tardif
    if _is_friday_late():
        result["reason"] = "friday_late"
        _save_state(state)
        return result

    # Gate 3 : kill switch global
    if _is_kill_switch_active():
        result["reason"] = "kill_switch_active"
        _save_state(state)
        return result

    # Gate 4 : balance + daily loss
    balance = await _mt5_fetch_balance()
    if balance is None:
        if not state.get("bridge_alert_sent_today"):
            state["bridge_alert_sent_today"] = True
            await _send_info(
                f"🚨 <b>scalp</b> MT5 bridge unreachable ({BRIDGE_URL})\n"
                f"Cycles skip. Re-alerte demain si toujours down."
            )
        result["reason"] = "bridge_unreachable"
        _save_state(state)
        return result

    if state.get("opening_balance_eur") is None:
        state["opening_balance_eur"] = balance
        logger.info("scalp: baseline balance jour = %.2f", balance)

    killed, state = await _check_daily_loss(state, mode)
    if killed:
        result["reason"] = "daily_loss_exceeded"
        _save_state(state)
        return result

    # Gate 5 : max positions
    open_pairs = {p["pair"].upper() for p in _open_positions(state)}
    if len(open_pairs) >= MAX_POSITIONS:
        result["reason"] = f"max_positions_reached ({len(open_pairs)}/{MAX_POSITIONS})"
        _save_state(state)
        return result

    # Scan : pour chaque paire pas déjà ouverte, fetch candles + détection
    from backend.services import price_service
    actions: list[dict] = []
    for pair in UNIVERSE:
        if pair in open_pairs:
            continue
        try:
            candles, _sim = await price_service.fetch_candles(pair, "1min", 50)
        except Exception as e:
            logger.warning("scalp: fetch_candles %s failed — %s", pair, e)
            continue
        if not candles or len(candles) < max(RSI_PERIOD, ATR_PERIOD) + 2:
            continue

        signal = _detect_signal(candles, pair)
        if signal is None:
            continue

        entry = signal["entry"]
        sl = signal["sl"]
        tp = signal["tp"]
        direction = signal["direction"]
        lots = _size_lots_from_risk(balance, entry, sl, pair)
        if lots <= 0:
            continue

        action = {
            "pair": pair, "direction": direction, "lots": lots,
            "entry": entry, "sl": sl, "tp": tp, "sl_initial": sl,
            "rsi": signal["rsi"], "atr": signal["atr"], "mode": mode,
        }

        if mode == "live":
            resp = await _mt5_submit_order(pair, direction, lots, sl, tp, entry)
            if resp.get("ok"):
                # ─── Fill guard (défense entry=0.0, PR fill-guard) ────
                from backend.services.trader_fill_guard import is_fill_price_sane as _ifs
                _fill_ok, _fill_reason = _ifs(resp, entry)
                if not _fill_ok:
                    _tk = resp.get("ticket")
                    try:
                        _ck = int(_tk) if _tk is not None else None
                    except (TypeError, ValueError):
                        _ck = None
                    _close_resp = await _mt5_close_position(_ck) if _ck else {"ok": False}
                    logger.error(
                        "SCALP: fill REJETÉ ticket=%s reason=%s auto_close=%s",
                        _tk, _fill_reason, _close_resp.get("ok"),
                    )
                    await _send_info(
                        f"🚨 <b>SCALP</b> position ouverte avec fill corrompu\n"
                        f"ticket {_tk} {pair} {direction} lots={lots}\n"
                        f"motif: {_fill_reason}\n"
                        f"close auto: {'OK' if _close_resp.get('ok') else 'ÉCHEC — fermer MANUELLEMENT'}"
                    )
                    action["executed"] = False
                    action["reason"] = f"fill_rejected_closed: {_fill_reason}"
                    actions.append(action)
                    continue
                ticket = resp.get("ticket") or "unknown"
                fill = resp.get("avg_fill_price") or entry
                action["executed"] = True
                action["ticket"] = ticket
                state["open_positions"].append({
                    "pair": pair, "direction": direction, "lots": lots,
                    "entry": float(fill), "sl": sl, "tp": tp, "sl_initial": sl,
                    "entry_time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "mt5_ticket": ticket, "last_seen_price": float(fill),
                    "status": "open",
                })
                await _send_trade_opened_rich(
                    pair=pair, direction=direction, entry=fill, sl=sl, tp=tp,
                    volume=lots, ticket=ticket,
                )
            else:
                action["executed"] = False
                action["reason"] = str(resp)[:200]
        else:
            # dry_run : virtual position
            state["open_positions"].append({
                "pair": pair, "direction": direction, "lots": lots,
                "entry": entry, "sl": sl, "tp": tp, "sl_initial": sl,
                "entry_time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "mt5_ticket": None, "last_seen_price": entry,
                "status": "open",
            })
            action["executed"] = True
            action["reason"] = "dry_run_simulated_open"

        actions.append(action)

    _save_state(state)

    result["ran"] = True
    result["actions"] = actions
    return result


# ─── Check exits (SL/TP + time stop) ────────────────────────────────────

async def check_exits() -> dict:
    """Vérifie SL/TP + time stops sur les positions ouvertes. Toutes 30s."""
    if not _config_enabled():
        return {"ran": False, "reason": "disabled"}

    mode = _config_mode()
    state = _load_state()
    state = _ensure_daily_reset(state, date.today().isoformat())

    closed_this_run = []
    now_utc = datetime.now(timezone.utc)

    for p in state.get("open_positions", []):
        if p.get("status") != "open":
            continue

        pair = p["pair"]
        direction = p["direction"]
        entry = float(p["entry"])
        sl = float(p["sl"])
        tp = float(p["tp"])
        lots = float(p["lots"])

        # Fetch prix courant
        tick = await _mt5_fetch_tick(pair)
        if tick is None:
            continue
        bid = float(tick.get("bid") or tick.get("price") or 0)
        ask = float(tick.get("ask") or tick.get("price") or 0)
        last = (bid + ask) / 2.0 if (bid and ask) else (bid or ask)
        if not last:
            continue

        p["last_seen_price"] = last

        # ─── Trailing stop (ratchet one-way) ─────────────────────────────
        try:
            from backend.services.trader_trailing import update_trailing_sl
            new_sl = update_trailing_sl(p, last, "SCALP")
            if new_sl is not None:
                p["sl"] = new_sl
                sl = new_sl  # relu plus bas pour le check SL
        except Exception:
            pass

        # Determine exit
        exit_price = None
        reason = None
        if direction == "buy":
            if last <= sl:
                exit_price, reason = sl, "sl"
            elif last >= tp:
                exit_price, reason = tp, "tp"
        else:
            if last >= sl:
                exit_price, reason = sl, "sl"
            elif last <= tp:
                exit_price, reason = tp, "tp"

        # Time stop
        if exit_price is None:
            entry_time = datetime.fromisoformat(p["entry_time_utc"])
            age_min = (now_utc - entry_time).total_seconds() / 60.0
            if age_min >= TIME_STOP_MINUTES:
                exit_price, reason = last, "time_stop"

        if exit_price is None:
            continue

        # Fermer
        if mode == "live" and p.get("mt5_ticket") is not None:
            resp = await _mt5_close_position(int(p["mt5_ticket"]))
            if resp.get("ok"):
                actual_exit = resp.get("exit_price") or exit_price
                exit_price = float(actual_exit)
            else:
                logger.warning("scalp: close ticket %s failed — %s",
                               p.get("mt5_ticket"), resp.get("body"))

        cs = _contract_size(pair)
        if direction == "buy":
            pnl_usd = (exit_price - entry) * cs * lots
        else:
            pnl_usd = (entry - exit_price) * cs * lots

        p["status"] = f"closed_{reason}"
        p["exit_price"] = exit_price
        p["exit_time_utc"] = now_utc.isoformat(timespec="seconds")
        p["pnl_usd"] = round(pnl_usd, 4)
        p["close_reason"] = reason
        closed_this_run.append(p)

        # Déplacer vers closed_history
        state.setdefault("closed_history", []).append(dict(p))

        # Carte riche CLOSE
        if mode == "live" and p.get("mt5_ticket") is not None:
            await _send_close_rich(
                pair=pair, direction=direction, entry=entry,
                close_price=exit_price, profit_loss=pnl_usd, volume=lots,
                ticket=p["mt5_ticket"], reason=reason,
            )

    # Nettoyer les positions fermées de open_positions
    state["open_positions"] = [
        p for p in state.get("open_positions", []) if p.get("status") == "open"
    ]
    _save_state(state)

    return {"ran": True, "closed": len(closed_this_run)}


# ─── Friday force-close ─────────────────────────────────────────────────

async def friday_force_close() -> dict:
    """Vendredi 19:30 UTC : ferme toutes les positions scalp ouvertes."""
    if not _config_enabled():
        return {"ran": False, "reason": "disabled"}

    mode = _config_mode()
    state = _load_state()
    state = _ensure_daily_reset(state, date.today().isoformat())

    closed = []
    now_utc = datetime.now(timezone.utc)

    for p in state.get("open_positions", []):
        if p.get("status") != "open":
            continue
        pair = p["pair"]
        direction = p["direction"]
        entry = float(p["entry"])
        lots = float(p["lots"])

        tick = await _mt5_fetch_tick(pair)
        exit_price = entry
        if tick is not None:
            bid = float(tick.get("bid") or 0)
            ask = float(tick.get("ask") or 0)
            exit_price = (bid + ask) / 2.0 if (bid and ask) else entry

        if mode == "live" and p.get("mt5_ticket") is not None:
            resp = await _mt5_close_position(int(p["mt5_ticket"]))
            if resp.get("ok") and resp.get("exit_price"):
                exit_price = float(resp["exit_price"])

        cs = _contract_size(pair)
        pnl = ((exit_price - entry) if direction == "buy" else (entry - exit_price)) * cs * lots

        p["status"] = "closed_friday"
        p["exit_price"] = round(exit_price, 5)
        p["exit_time_utc"] = now_utc.isoformat(timespec="seconds")
        p["pnl_usd"] = round(pnl, 4)
        p["close_reason"] = "friday"
        closed.append(p)
        state.setdefault("closed_history", []).append(dict(p))

        if mode == "live" and p.get("mt5_ticket") is not None:
            await _send_close_rich(
                pair=pair, direction=direction, entry=entry,
                close_price=exit_price, profit_loss=pnl, volume=lots,
                ticket=p["mt5_ticket"], reason="friday",
            )

    state["open_positions"] = []
    _save_state(state)

    if closed:
        lines = [f"🔚 <b>scalp</b> [{mode}] Friday force-close"]
        for p in closed:
            lines.append(
                f"  🏁 {p['pair']} {p['direction']} qty {p['lots']} "
                f"exit {p['exit_price']:.5f} (entry {p['entry']:.5f}) "
                f"PnL {p['pnl_usd']:+.2f} USD"
            )
        await _send_info("\n".join(lines))

    return {"ran": True, "closed": len(closed)}


# ─── Daily recap ────────────────────────────────────────────────────────

async def daily_recap() -> dict:
    """Rapport Telegram quotidien 22h05 UTC."""
    if not _config_enabled():
        return {"ran": False, "reason": "disabled"}

    mode = _config_mode()
    state = _load_state()
    today_utc = date.today().isoformat()
    state = _ensure_daily_reset(state, today_utc)

    closed_today = _closed_today(state)
    open_pos = _open_positions(state)
    if not closed_today and not open_pos:
        return {"ran": False, "reason": "nothing_to_report"}

    realized_usd = _realized_pnl_today_usd(state)
    realized_eur = realized_usd / EUR_USD_RATE

    lines = [f"📊 <b>scalp</b> [{mode}] recap quotidien {today_utc}"]
    lines.append(f"Positions encore ouvertes : {len(open_pos)}")
    lines.append(f"Positions fermées aujourd'hui : {len(closed_today)}")
    lines.append(f"\nPnL réalisé : {realized_eur:+.2f} EUR ({realized_usd:+.2f} USD)")

    if closed_today:
        tp_n = sum(1 for p in closed_today if p.get("close_reason") == "tp")
        sl_n = sum(1 for p in closed_today if p.get("close_reason") == "sl")
        ts_n = sum(1 for p in closed_today if p.get("close_reason") == "time_stop")
        fr_n = sum(1 for p in closed_today if p.get("close_reason") == "friday")
        lines.append(f"\nBreakdown : TP={tp_n}, SL={sl_n}, time_stop={ts_n}, Friday={fr_n}")

    await _send_info("\n".join(lines))
    return {"ran": True}
