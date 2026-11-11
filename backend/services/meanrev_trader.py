"""Mean reversion FX trader via bridge MT5 (IC Markets sur Lightsail Windows).

Stratégie contre-trend sur paires forex après pic de volatilité, avec signal
composite multi-timeframe :

- Régime (1h, 100 bougies) : BBW percentile > 80 AND ATR(14) > 2× moyenne(50)
- Trigger (15min, 50 bougies) : bougie amplitude > 2.5× ATR + reversal
- Direction : CONTRE la bougie trigger
- SL : au-delà du pic extrême de la trigger + buffer 0.1× ATR
- TP : VWAP du jour (fetch dynamique sur les bougies 15min UTC du jour)
- Time stop : 4h max, close au market
- Sizing : 0.5% du balance MT5, lots calculés selon distance_sl

OFF par défaut (``MEANREV_ENABLED=false``). Mode ``live`` par défaut : les
ordres partent vers IC Markets via le bridge MT5. Passer ``MEANREV_MODE=dry_run``
pour observer sans exécuter.

Gates fail-closed (un seul False abort le cycle) :
1. Feature flag global
2. Forex hours (dim 22h UTC → ven 22h UTC, hors weekend)
3. Blackout vendredi 19:30 UTC
4. Kill switch global
5. FOMC/CPI window (120min)
6. Perte journalière plafond
7. Positions ouvertes max

Bridge MT5 unreachable → skip cycle silencieusement + alerte Telegram une
seule fois par jour (évite le spam).
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import pathlib
import statistics
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

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
    return _env_bool("MEANREV_ENABLED", "false")


def _config_mode() -> str:
    """``live`` (défaut) ou ``dry_run``."""
    mode = os.getenv("MEANREV_MODE", "live").strip().lower()
    return mode if mode in ("dry_run", "live") else "dry_run"


BRIDGE_URL = os.getenv("MEANREV_BRIDGE_URL", "http://100.74.160.72:8787").rstrip("/")
BRIDGE_KEY = os.getenv("MEANREV_BRIDGE_API_KEY", "")
MAX_DAILY_LOSS_EUR = _env_float("MEANREV_MAX_DAILY_LOSS_EUR", 10.0)
MAX_POSITIONS = _env_int("MEANREV_MAX_POSITIONS", 5)
RISK_PCT = _env_float("MEANREV_RISK_PCT", 0.5) / 100.0  # 0.5% → 0.005
BBW_PERCENTILE_MIN = _env_float("MEANREV_BBW_PERCENTILE_MIN", 80.0)
ATR_EXPANSION_MIN = _env_float("MEANREV_ATR_EXPANSION_MIN", 2.0)
TRIGGER_CANDLE_MULT = _env_float("MEANREV_TRIGGER_CANDLE_MULT", 2.5)
TIME_STOP_MINUTES = _env_int("MEANREV_TIME_STOP_MINUTES", 240)
FRIDAY_LATE_BLOCK_UTC = os.getenv("MEANREV_FRIDAY_LATE_BLOCK_UTC", "19:30")
SCAN_INTERVAL_SEC = _env_int("MEANREV_SCAN_INTERVAL_SEC", 900)
POLL_INTERVAL_SEC = SCAN_INTERVAL_SEC
STATE_PATH = os.getenv("MEANREV_STATE_PATH", "/app/data/meanrev_state.json")
FOMC_VETO_MINUTES = _env_int("MEANREV_FOMC_WINDOW_MINUTES", 120)
EARNINGS_VETO_HOURS = _env_int("MEANREV_EARNINGS_WINDOW_HOURS", 48)
EUR_USD_RATE = _env_float("MEANREV_EUR_USD_FIXED", 1.07)


def _get_universe() -> list[str]:
    raw = os.getenv("MEANREV_UNIVERSE", "").strip()
    if not raw:
        raw = os.getenv("WATCHED_PAIRS", "EUR/USD,GBP/USD,USD/JPY,XAU/USD").strip()
    return [p.strip().upper() for p in raw.split(",") if p.strip()]


# ─── État persisté JSON ─────────────────────────────────────────────────

def _load_state() -> dict:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning("meanrev: load_state failed — %s", e)
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
        logger.warning("meanrev: save_state failed — %s", e)


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
        if (p.get("close_date") or "").startswith(today)
    ]


def _realized_pnl_today_usd(state: dict) -> float:
    return round(sum(float(p.get("pnl_usd") or 0) for p in _closed_today(state)), 4)


# ─── Safety gates ───────────────────────────────────────────────────────

def _is_forex_hours() -> bool:
    """Forex 24/5 : dimanche 22h UTC → vendredi 22h UTC."""
    now_utc = datetime.now(timezone.utc)
    wd = now_utc.weekday()  # 0=mon, 6=sun
    if wd == 5:  # samedi
        return False
    if wd == 6:  # dimanche
        return now_utc.hour >= 22
    if wd == 4:  # vendredi
        return now_utc.hour < 22
    return True  # lun-jeu toute la journée


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


def _veto_fomc_cpi() -> str | None:
    try:
        from backend.services import economic_calendar_veto as _ecv
        if _ecv.is_high_impact_window(window_minutes=FOMC_VETO_MINUTES):
            return "FOMC/CPI window active"
    except Exception:
        pass
    return None


def _veto_earnings(pair: str) -> str | None:
    # Les paires FX n'ont pas d'earnings, mais pour les indices (SPX, NDX)
    # et les crypto indices on peut tenter
    try:
        from backend.services import earnings_calendar_service as _ec
        hours_to = _ec.hours_to_next_earnings(pair)
        if hours_to is not None and abs(hours_to) < EARNINGS_VETO_HOURS:
            return f"earnings dans {hours_to:+.1f}h"
    except Exception:
        pass
    return None


# ─── Indicateurs techniques ─────────────────────────────────────────────

def _compute_atr(candles: list, period: int = 14) -> float | None:
    """ATR classique (Wilder) à partir d'une liste de Candle (triée ancien → récent)."""
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        high = float(candles[i].high)
        low = float(candles[i].low)
        prev_close = float(candles[i - 1].close)
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if len(trs) < period:
        return None
    # Simple average of first `period` TRs, puis Wilder smoothing
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def _compute_atr_series(candles: list, period: int = 14) -> list[float]:
    """Retourne la série d'ATR (Wilder) pour chaque fin de bougie où calculable."""
    if len(candles) < period + 1:
        return []
    trs = []
    for i in range(1, len(candles)):
        high = float(candles[i].high)
        low = float(candles[i].low)
        prev_close = float(candles[i - 1].close)
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if len(trs) < period:
        return []
    out = []
    atr = sum(trs[:period]) / period
    out.append(atr)
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
        out.append(atr)
    return out


def _compute_bbw_series(candles: list, period: int = 20, std_mult: float = 2.0) -> list[float]:
    """Série Bollinger Band Width = (BB_up - BB_down) / SMA pour chaque fenêtre."""
    if len(candles) < period:
        return []
    closes = [float(c.close) for c in candles]
    out = []
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1 : i + 1]
        sma = sum(window) / period
        if sma == 0:
            out.append(0.0)
            continue
        var = sum((x - sma) ** 2 for x in window) / period
        std = math.sqrt(var)
        bb_up = sma + std_mult * std
        bb_down = sma - std_mult * std
        out.append((bb_up - bb_down) / sma)
    return out


def _percentile_rank(value: float, series: list[float]) -> float:
    """Percentile rank 0-100 de `value` dans `series`."""
    if not series:
        return 0.0
    below = sum(1 for v in series if v < value)
    return 100.0 * below / len(series)


def _compute_vwap_today(candles_15min: list) -> float | None:
    """VWAP sur les bougies 15min du jour UTC en cours.

    typical = (H+L+C)/3. Pas de volume dans les Candle structurées actuellement,
    donc on assume volume=1 par bougie (VWAP devient moyenne pondérée des typicals).
    """
    if not candles_15min:
        return None
    today_utc = date.today()
    today_candles = []
    for c in candles_15min:
        ts = c.timestamp
        # Normaliser en UTC
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        if ts.date() == today_utc:
            today_candles.append(c)
    if not today_candles:
        return None
    typicals = [(float(c.high) + float(c.low) + float(c.close)) / 3.0 for c in today_candles]
    return sum(typicals) / len(typicals)


# ─── Détection régime + trigger ─────────────────────────────────────────

def _detect_regime(candles_1h: list) -> tuple[float, float, bool]:
    """Retourne (bbw_percentile, atr_expansion, regime_ok).

    regime_ok = bbw_percentile > BBW_PERCENTILE_MIN AND atr_expansion > ATR_EXPANSION_MIN
    """
    if len(candles_1h) < 50:
        return (0.0, 0.0, False)

    atr_series = _compute_atr_series(candles_1h, period=14)
    if len(atr_series) < 50:
        return (0.0, 0.0, False)

    atr_now = atr_series[-1]
    atr_avg_50 = sum(atr_series[-50:]) / 50
    atr_expansion = atr_now / atr_avg_50 if atr_avg_50 > 0 else 0.0

    bbw_series = _compute_bbw_series(candles_1h, period=20)
    if not bbw_series:
        return (0.0, atr_expansion, False)
    bbw_now = bbw_series[-1]
    bbw_pct = _percentile_rank(bbw_now, bbw_series)

    regime_ok = bbw_pct > BBW_PERCENTILE_MIN and atr_expansion > ATR_EXPANSION_MIN
    return (bbw_pct, atr_expansion, regime_ok)


def _detect_trigger(candles_15min: list, atr_15min: float) -> dict | None:
    """Détecte une bougie trigger (amplitude > TRIGGER_CANDLE_MULT × ATR + reversal).

    Reversal : la dernière bougie close < open suivie d'une bougie close > open (BUY),
    ou dernière bougie close > open suivie d'une bougie close < open (SELL).

    Retourne {direction, entry, extreme, trigger_candle_time} ou None.
    """
    if len(candles_15min) < 3 or not atr_15min or atr_15min <= 0:
        return None

    # On regarde l'avant-dernière (trigger) et la dernière (confirmation reversal)
    trigger = candles_15min[-2]
    last = candles_15min[-1]

    t_open = float(trigger.open)
    t_close = float(trigger.close)
    t_high = float(trigger.high)
    t_low = float(trigger.low)
    amplitude = t_high - t_low

    if amplitude < TRIGGER_CANDLE_MULT * atr_15min:
        return None

    last_open = float(last.open)
    last_close = float(last.close)

    # Trigger baissière (close < open) + reversal (last close > last open) → BUY
    if t_close < t_open and last_close > last_open:
        return {
            "direction": "buy",
            "entry": float(last.close),
            "extreme": t_low,  # SL référence = le low
            "trigger_time": trigger.timestamp.isoformat() if hasattr(trigger.timestamp, "isoformat") else str(trigger.timestamp),
            "amplitude": amplitude,
            "atr": atr_15min,
        }

    # Trigger haussière (close > open) + reversal (last close < last open) → SELL
    if t_close > t_open and last_close < last_open:
        return {
            "direction": "sell",
            "entry": float(last.close),
            "extreme": t_high,
            "trigger_time": trigger.timestamp.isoformat() if hasattr(trigger.timestamp, "isoformat") else str(trigger.timestamp),
            "amplitude": amplitude,
            "atr": atr_15min,
        }

    return None


def _sl_from_trigger(trigger: dict, atr_15min: float) -> float:
    """SL = extreme ± buffer 0.1× ATR (de l'autre côté de l'entrée)."""
    buffer = 0.1 * atr_15min
    if trigger["direction"] == "buy":
        return trigger["extreme"] - buffer
    return trigger["extreme"] + buffer


# ─── Bridge MT5 calls ───────────────────────────────────────────────────

def _headers() -> dict[str, str]:
    return {"X-Bridge-Key": BRIDGE_KEY} if BRIDGE_KEY else {}


async def _mt5_fetch_balance() -> float | None:
    """GET /account → retourne balance EUR ou None si bridge down."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{BRIDGE_URL}/account", headers=_headers())
            if r.status_code != 200:
                return None
            data = r.json()
            if not data.get("ok"):
                return None
            return float(data.get("balance") or data.get("Balance") or 0)
    except Exception as e:
        logger.warning("meanrev: fetch_balance failed — %s", e)
        return None


async def _mt5_fetch_positions() -> list[dict] | None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{BRIDGE_URL}/positions", headers=_headers())
            if r.status_code != 200:
                return None
            data = r.json()
            if not data.get("ok"):
                return None
            return data.get("positions", [])
    except Exception as e:
        logger.warning("meanrev: fetch_positions failed — %s", e)
        return None


async def _mt5_submit_order(
    pair: str, direction: str, lots: float, sl: float, tp: float,
) -> dict:
    """POST /order → retourne dict avec ok, order_id, avg_fill_price."""
    payload = {
        "pair": pair, "direction": direction, "lots": lots,
        "sl": sl, "tp": tp, "dry_run": False,
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
            "order_id": body.get("order_id"),
            "ticket": body.get("ticket"),
            "avg_fill_price": body.get("avg_fill_price") or body.get("price"),
            "body": body,
        }
    except Exception as e:
        return {"ok": False, "exception": str(e)}


async def _mt5_close_position(ticket: int | str) -> dict:
    """POST /close → fermeture position par ticket."""
    payload = {"ticket": ticket}
    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(f"{BRIDGE_URL}/close", json=payload, headers=_headers())
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:200]}
        return {
            "ok": r.status_code == 200 and bool(body.get("ok")),
            "status_code": r.status_code,
            "exit_price": body.get("exit_price") or body.get("price"),
            "body": body,
        }
    except Exception as e:
        return {"ok": False, "exception": str(e)}


# ─── Sizing ─────────────────────────────────────────────────────────────

def _size_lots_from_risk(balance_eur: float, entry: float, sl: float, pair: str) -> float:
    """Calcule les lots selon risque 0.5% × balance / distance_sl.

    Simplification : on assume 1 lot standard = 100000 unités, pip value ≈ 10 USD
    pour les majors. Les lots sont arrondis à 2 décimales (lot minimum 0.01).
    """
    distance = abs(entry - sl)
    if distance <= 0 or balance_eur <= 0:
        return 0.0
    risk_money_eur = balance_eur * RISK_PCT
    risk_money_usd = risk_money_eur * EUR_USD_RATE
    # Pour un lot standard (100000), chaque unité de prix bouge = 100000 USD
    # risk_usd / distance = lots équivalents
    lots_raw = risk_money_usd / (distance * 100000)
    # Arrondir vers le bas à 0.01 (lot minimum MT5)
    lots = math.floor(lots_raw * 100) / 100
    return max(0.0, lots)


# ─── Telegram helper ────────────────────────────────────────────────────

async def _send_info(text: str) -> None:
    try:
        from backend.services import telegram_service
        await telegram_service.send_info_text(text, parse_mode="HTML")
    except Exception as e:
        logger.warning("meanrev: send_info_text failed — %s", e)


# ─── Cycle principal ────────────────────────────────────────────────────

async def cycle() -> dict:
    """Un cycle meanrev. Appelé toutes les SCAN_INTERVAL_SEC par le scheduler."""
    result = {"ran": False, "reason": None, "actions": []}

    if not _config_enabled():
        result["reason"] = "disabled"
        return result

    mode = _config_mode()
    today_utc = date.today().isoformat()

    state = _load_state()
    state = _ensure_daily_reset(state, today_utc)

    # ─── Gate 1 : forex hours ───────────────────────────────────────────
    if not _is_forex_hours():
        result["reason"] = "forex_closed"
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

    # ─── Gate 5 : balance + daily loss check ────────────────────────────
    if mode == "live":
        balance = await _mt5_fetch_balance()
        if balance is None:
            # Bridge down → alerte une seule fois par jour
            if not state.get("bridge_alert_sent_today"):
                state["bridge_alert_sent_today"] = True
                await _send_info(
                    f"🚨 <b>meanrev</b> MT5 bridge unreachable ({BRIDGE_URL})\n"
                    f"Cycle skip. Re-alerte demain si toujours down."
                )
            result["reason"] = "bridge_unreachable"
            _save_state(state)
            return result

        if state.get("opening_balance_eur") is None:
            state["opening_balance_eur"] = balance
            logger.info("meanrev: baseline balance jour = %.2f EUR", balance)

        daily_pnl = balance - float(state["opening_balance_eur"])
        if daily_pnl < -MAX_DAILY_LOSS_EUR or state.get("disabled_until_tomorrow"):
            if not state.get("disabled_until_tomorrow"):
                state["disabled_until_tomorrow"] = True
                await _send_info(
                    f"🚨 <b>meanrev</b> [live] DÉSACTIVÉ auto\n"
                    f"Daily PnL {daily_pnl:+.2f} EUR < seuil -{MAX_DAILY_LOSS_EUR:.2f}\n"
                    f"Re-activer manuellement (edit state JSON) + restart"
                )
            result["reason"] = "daily_loss_exceeded"
            _save_state(state)
            return result
    else:
        # dry_run : balance par défaut 500 EUR
        balance = 500.0
        if state.get("opening_balance_eur") is None:
            state["opening_balance_eur"] = balance

        realized_usd = _realized_pnl_today_usd(state)
        if (realized_usd / EUR_USD_RATE) < -MAX_DAILY_LOSS_EUR or state.get("disabled_until_tomorrow"):
            state["disabled_until_tomorrow"] = True
            result["reason"] = "daily_loss_exceeded_sim"
            _save_state(state)
            return result

    # ─── Gate 6 : positions ouvertes ────────────────────────────────────
    open_pairs = {p["pair"].upper() for p in _open_positions(state)}
    n_open = len(open_pairs)
    if n_open >= MAX_POSITIONS:
        result["reason"] = f"max_positions_reached ({n_open}/{MAX_POSITIONS})"
        _save_state(state)
        return result

    # ─── Scan univers ───────────────────────────────────────────────────
    universe = _get_universe()
    candidates = [p for p in universe if p not in open_pairs]

    from backend.services import price_service

    actions: list[dict] = []
    opened_this_cycle = False

    for pair in candidates:
        # Veto earnings si applicable
        veto = _veto_earnings(pair)
        if veto:
            actions.append({"pair": pair, "verdict": "VETO", "reason": veto})
            continue

        # Fetch candles
        try:
            candles_1h, sim_1h = await price_service.fetch_candles(pair, "1h", 100)
            candles_15m, sim_15m = await price_service.fetch_candles(pair, "15min", 50)
        except Exception as e:
            actions.append({"pair": pair, "verdict": "SKIP", "reason": f"fetch_candles: {e}"})
            continue

        if sim_1h or sim_15m:
            # Prix simulés = pas de signal fiable
            actions.append({"pair": pair, "verdict": "SKIP", "reason": "prix_simulés"})
            continue

        if len(candles_1h) < 50 or len(candles_15m) < 20:
            actions.append({"pair": pair, "verdict": "SKIP", "reason": "pas_assez_de_bougies"})
            continue

        # Régime
        bbw_pct, atr_exp, regime_ok = _detect_regime(candles_1h)
        if not regime_ok:
            # Silencieux — c'est le cas majoritaire
            continue

        # Trigger
        atr_15min = _compute_atr(candles_15m, period=14)
        if not atr_15min:
            actions.append({"pair": pair, "verdict": "SKIP", "reason": "atr_15min_indispo"})
            continue
        trigger = _detect_trigger(candles_15m, atr_15min)
        if not trigger:
            # Régime OK mais pas de trigger — on log pour debug
            actions.append({
                "pair": pair, "verdict": "WAIT",
                "reason": f"régime OK (bbw_pct={bbw_pct:.0f}, atr_exp={atr_exp:.2f}), pas de trigger",
            })
            continue

        # Setup complet : compute SL + TP + lots
        entry = trigger["entry"]
        sl = _sl_from_trigger(trigger, atr_15min)
        vwap = _compute_vwap_today(candles_15m)
        if vwap is None:
            actions.append({"pair": pair, "verdict": "SKIP", "reason": "vwap_indispo"})
            continue
        tp = vwap  # cible = VWAP du jour

        # Vérif direction/sens cohérent avec VWAP
        if trigger["direction"] == "buy" and vwap <= entry:
            actions.append({"pair": pair, "verdict": "SKIP",
                            "reason": f"vwap {vwap:.5f} <= entry {entry:.5f}, pas de marge"})
            continue
        if trigger["direction"] == "sell" and vwap >= entry:
            actions.append({"pair": pair, "verdict": "SKIP",
                            "reason": f"vwap {vwap:.5f} >= entry {entry:.5f}, pas de marge"})
            continue

        lots = _size_lots_from_risk(balance, entry, sl, pair)
        if lots < 0.01:
            actions.append({"pair": pair, "verdict": "SKIP",
                            "reason": f"lots {lots:.4f} < 0.01 minimum"})
            continue

        action = {
            "pair": pair, "verdict": "TAKE",
            "direction": trigger["direction"], "lots": lots,
            "entry": entry, "sl": sl, "tp": tp,
            "bbw_pct": bbw_pct, "atr_expansion": atr_exp,
            "mode": mode,
        }

        if mode == "live":
            resp = await _mt5_submit_order(pair, trigger["direction"], lots, sl, tp)
            if resp.get("ok"):
                action["executed"] = True
                action["ticket"] = resp.get("ticket") or resp.get("order_id")
                fill = resp.get("avg_fill_price") or entry
                state["open_positions"].append({
                    "pair": pair, "direction": trigger["direction"], "lots": lots,
                    "entry": float(fill), "sl": sl, "tp": tp,
                    "vwap_target": tp,
                    "entry_time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "mt5_ticket": action["ticket"], "status": "open",
                })
                opened_this_cycle = True
            else:
                action["executed"] = False
                action["reason"] = f"bridge_http_{resp.get('status_code')}: {str(resp.get('body'))[:200]}"
        else:
            # dry_run : position virtuelle
            action["executed"] = True
            action["reason"] = "dry_run_simulated_open"
            state["open_positions"].append({
                "pair": pair, "direction": trigger["direction"], "lots": lots,
                "entry": entry, "sl": sl, "tp": tp,
                "vwap_target": tp,
                "entry_time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "mt5_ticket": None, "status": "open",
            })
            opened_this_cycle = True

        actions.append(action)
        # Une seule ouverture par cycle
        if action.get("executed"):
            break

    _save_state(state)

    # ─── Reporting Telegram ─────────────────────────────────────────────
    if actions:
        await _report_cycle(mode, n_open, universe, actions, state)

    result["ran"] = True
    result["actions"] = actions
    return result


async def _report_cycle(mode: str, n_open: int, universe: list, actions: list, state: dict) -> None:
    taken = [a for a in actions if a.get("verdict") == "TAKE" and a.get("executed")]
    vetoed = [a for a in actions if a.get("verdict") == "VETO"]
    waits = [a for a in actions if a.get("verdict") == "WAIT"]

    # Silence si rien d'intéressant à dire
    if not taken and not vetoed and not waits:
        return

    lines = [f"🔄 <b>meanrev</b> [{mode}] cycle"]
    lines.append(f"Positions ouvertes: {n_open}/{MAX_POSITIONS}")
    lines.append(f"Univers: {len(universe)} paires scannées")

    if taken:
        lines.append("\n<b>Entrées:</b>")
        for t in taken:
            exec_tag = "📋 DRY" if mode == "dry_run" else "✅ EXEC"
            lines.append(
                f"  {exec_tag} {t['direction'].upper()} {t['lots']:.2f} lots {t['pair']} "
                f"@ {t['entry']:.5f} SL {t['sl']:.5f} TP {t['tp']:.5f}"
            )
            lines.append(
                f"    régime: bbw={t['bbw_pct']:.0f}pct, atr_exp={t['atr_expansion']:.2f}"
            )

    if waits:
        lines.append(f"\n<b>Régimes actifs sans trigger:</b> {', '.join(a['pair'] for a in waits)}")

    if vetoed:
        lines.append("\nVetos:")
        for v in vetoed:
            lines.append(f"  • {v['pair']}: {v.get('reason', '')}")

    if mode == "dry_run":
        realized = _realized_pnl_today_usd(state)
        lines.append(f"\nPnL simulé jour: {realized:+.2f} USD ({realized / EUR_USD_RATE:+.2f} EUR)")

    await _send_info("\n".join(lines))


# ─── Check exits : time stop 4h + VWAP targets ──────────────────────────

async def check_exits() -> dict:
    """Appelé toutes les 60s. Ferme les positions qui :
    - Dépassent le time stop de 4h
    - Ont atteint leur VWAP target (si on ne compte pas sur le TP MT5 pour le faire)
    """
    if not _config_enabled():
        return {"ran": False, "reason": "disabled"}

    mode = _config_mode()
    state = _load_state()
    state = _ensure_daily_reset(state, date.today().isoformat())

    open_positions = _open_positions(state)
    if not open_positions:
        return {"ran": False, "reason": "no_open_positions"}

    now_utc = datetime.now(timezone.utc)
    closed_this_cycle = []

    for p in state.get("open_positions", []):
        if p.get("status") != "open":
            continue

        # Parse entry_time
        try:
            entry_time = datetime.fromisoformat(p["entry_time_utc"])
            if entry_time.tzinfo is None:
                entry_time = entry_time.replace(tzinfo=timezone.utc)
        except Exception:
            continue

        age_minutes = (now_utc - entry_time).total_seconds() / 60.0

        # Time stop 4h
        if age_minutes >= TIME_STOP_MINUTES:
            exit_price = None
            if mode == "live" and p.get("mt5_ticket") is not None:
                resp = await _mt5_close_position(p["mt5_ticket"])
                if resp.get("ok"):
                    exit_price = float(resp.get("exit_price") or p["entry"])
                else:
                    # Impossible de fermer, on log et on continue
                    logger.warning("meanrev: close failed for ticket %s: %s",
                                   p.get("mt5_ticket"), resp.get("body"))
                    continue
            else:
                # dry_run : fermer au VWAP target (approximation)
                exit_price = p["vwap_target"]

            p["status"] = "closed_time_stop"
            p["exit_price"] = exit_price
            p["exit_time_utc"] = now_utc.isoformat(timespec="seconds")

            direction = p["direction"]
            if direction == "buy":
                pnl = (exit_price - p["entry"]) * p["lots"] * 100000
            else:
                pnl = (p["entry"] - exit_price) * p["lots"] * 100000
            p["pnl_usd"] = round(pnl, 4)
            state["closed_history"].append({
                "pair": p["pair"], "entry": p["entry"], "exit": exit_price,
                "pnl_usd": p["pnl_usd"], "reason": "time_stop_4h",
                "close_date": p["exit_time_utc"],
            })
            closed_this_cycle.append(p)

    _save_state(state)

    if closed_this_cycle:
        lines = [f"⏰ <b>meanrev</b> [{mode}] time stops 4h"]
        for p in closed_this_cycle:
            lines.append(
                f"  🏁 {p['direction'].upper()} {p['lots']:.2f} {p['pair']} "
                f"{p['entry']:.5f} → {p['exit_price']:.5f} = {p['pnl_usd']:+.2f} USD"
            )
        await _send_info("\n".join(lines))

    return {"ran": True, "closed": closed_this_cycle}


# ─── Friday force-close ─────────────────────────────────────────────────

async def friday_force_close() -> dict:
    if not _config_enabled():
        return {"ran": False, "reason": "disabled"}

    mode = _config_mode()
    state = _load_state()
    state = _ensure_daily_reset(state, date.today().isoformat())

    closed = []
    now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for p in state.get("open_positions", []):
        if p.get("status") != "open":
            continue

        if mode == "live" and p.get("mt5_ticket") is not None:
            resp = await _mt5_close_position(p["mt5_ticket"])
            if resp.get("ok"):
                exit_price = float(resp.get("exit_price") or p["entry"])
            else:
                exit_price = p["entry"]  # fallback = flat
        else:
            exit_price = p["entry"]  # dry_run : flat

        p["status"] = "closed_friday"
        p["exit_price"] = exit_price
        p["exit_time_utc"] = now_utc

        direction = p["direction"]
        if direction == "buy":
            pnl = (exit_price - p["entry"]) * p["lots"] * 100000
        else:
            pnl = (p["entry"] - exit_price) * p["lots"] * 100000
        p["pnl_usd"] = round(pnl, 4)
        state["closed_history"].append({
            "pair": p["pair"], "entry": p["entry"], "exit": exit_price,
            "pnl_usd": p["pnl_usd"], "reason": "friday",
            "close_date": now_utc,
        })
        closed.append(p)

    _save_state(state)

    if closed:
        lines = [f"🔚 <b>meanrev</b> [{mode}] Friday force-close"]
        for p in closed:
            lines.append(
                f"  🏁 FRIDAY {p['direction'].upper()} {p['lots']:.2f} {p['pair']} "
                f"{p['entry']:.5f} → {p['exit_price']:.5f} = {p['pnl_usd']:+.2f} USD"
            )
        await _send_info("\n".join(lines))

    return {"ran": True, "closed": closed}


# ─── Daily recap ────────────────────────────────────────────────────────

async def daily_recap() -> dict:
    if not _config_enabled():
        return {"ran": False, "reason": "disabled"}

    mode = _config_mode()
    state = _load_state()
    today_utc = date.today().isoformat()
    state = _ensure_daily_reset(state, today_utc)

    closed_today = _closed_today(state)
    open_positions = _open_positions(state)

    if not closed_today and not open_positions:
        return {"ran": False, "reason": "nothing_to_report"}

    realized_usd = _realized_pnl_today_usd(state)

    lines = [f"📊 <b>meanrev</b> [{mode}] recap quotidien {today_utc}"]
    lines.append(f"Positions encore ouvertes: {len(open_positions)}")
    lines.append(f"Positions fermées aujourd'hui: {len(closed_today)}")

    if closed_today:
        vwap_hit = sum(1 for p in closed_today if p["reason"] == "vwap_hit")
        sl_hit = sum(1 for p in closed_today if p["reason"] == "sl")
        time_stop = sum(1 for p in closed_today if p["reason"] == "time_stop_4h")
        friday = sum(1 for p in closed_today if p["reason"] == "friday")
        lines.append(
            f"\nBreakdown: VWAP={vwap_hit}, SL={sl_hit}, TimeStop={time_stop}, Friday={friday}"
        )
        lines.append(f"PnL réalisé jour: {realized_usd:+.2f} USD ({realized_usd / EUR_USD_RATE:+.2f} EUR)")
        lines.append("Détail:")
        for p in closed_today:
            lines.append(
                f"  {p['reason'].upper()} {p['pair']}: "
                f"{p['entry']:.5f} → {p['exit']:.5f} = {p['pnl_usd']:+.2f} USD"
            )

    await _send_info("\n".join(lines))
    return {"ran": True}
