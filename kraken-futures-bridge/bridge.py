"""Kraken Futures bridge — trading perpetuals USD-margined pour scalping-radar.

Fork indépendant du binance-bridge (créé 2026-08-02) — API Kraken Futures v3
est trop différente de Binance pour justifier un bridge unifié.

## Différences clés vs Binance bridge

- **Auth** : HMAC-SHA512 nonce-based avec secret Base64-decoded.
  Signature = base64(HMAC_SHA512(base64decode(secret), sha256(postData + nonce + endpoint_path)))
- **Endpoints** : /derivatives/api/v3/{accounts,openpositions,sendorder,cancelorder,tickers,instruments}
- **Symbols** : PF_XBTUSD (perpetual linear USD-margined), PF_ETHUSD, PF_SOLUSD...
  Format "PF_" = Perpetual Fixed maturity? Non — "Perpetual" USD-vanilla-margined (comme USDT-M chez Binance).
  Format "PI_" = Perpetual Inverse (coin-margined) — on ne trade PAS PI_*.
- **Sizing** : "size" en base asset direct (ex 0.01 BTC pour PF_XBTUSD). Cohérent avec Binance USDT-M.
- **Order type** : "mkt" (market) ; SL/TP via ordres séparés reduceOnly=true avec triggerPrice.
- **Response format** : {"result": "success", "openPositions": [...], "sendStatus": {...}}

## Safety gates (miroir du binance-bridge commit 0b60261)

- KRAKEN_MAX_DAILY_LOSS_PCT (default 3%) — kill-switch avec anti-drift built-in
- KRAKEN_LIVE_WHITELIST_SYMBOLS — opt-in strict (default vide = tous supportés)

## Env vars requises

- KRAKEN_API_KEY (~56 chars, format base64-like)
- KRAKEN_API_SECRET (~88 chars base64 avec ==)
- KRAKEN_BRIDGE_API_KEY (auth interne bridge↔radar, générée à l'init)
- KRAKEN_BRIDGE_PORT (default 8790, pour ne pas collision Binance 8789)

Cf. mémoire project_session_summary_2026_08_02.md
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import threading
import time
from datetime import date, datetime, timezone
from functools import wraps
from typing import Any
from urllib.parse import urlencode

import httpx
from flask import Flask, jsonify, request

# ─── Config ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("kraken-bridge")

BASE_URL = "https://futures.kraken.com/derivatives"
KRAKEN_API_KEY = os.getenv("KRAKEN_API_KEY", "")
KRAKEN_API_SECRET = os.getenv("KRAKEN_API_SECRET", "")
BRIDGE_API_KEY = os.getenv("KRAKEN_BRIDGE_API_KEY", "")
BRIDGE_PORT = int(os.getenv("KRAKEN_BRIDGE_PORT", "8790"))

# ─── Safety gates ──────────────────────────────────────────────────────
MAX_DAILY_LOSS_PCT = float(os.getenv("KRAKEN_MAX_DAILY_LOSS_PCT", "3.0"))
LIVE_WHITELIST_SYMBOLS = frozenset(
    s.strip().upper()
    for s in os.getenv("KRAKEN_LIVE_WHITELIST_SYMBOLS", "").split(",")
    if s.strip()
)
MAX_OPEN_POSITIONS = int(os.getenv("KRAKEN_MAX_OPEN_POSITIONS", "10"))

_start_of_day_balance: float | None = None
_start_of_day_date: date | None = None
_nonce_lock = threading.Lock()
_last_nonce = 0

# ─── Symbol mapping ────────────────────────────────────────────────────
# scalping-radar pair → Kraken Futures symbol (PF_ = Perpetual USD-margined)
_PAIR_TO_SYMBOL: dict[str, str] = {
    "BTC/USD": "PF_XBTUSD",
    "ETH/USD": "PF_ETHUSD",
    "SOL/USD": "PF_SOLUSD",
    "ADA/USD": "PF_ADAUSD",
    "XRP/USD": "PF_XRPUSD",
    "LTC/USD": "PF_LTCUSD",
    "BCH/USD": "PF_BCHUSD",
    "DOT/USD": "PF_DOTUSD",
    "DOGE/USD": "PF_DOGEUSD",
    "AVAX/USD": "PF_AVAXUSD",
    "MATIC/USD": "PF_MATICUSD",
    "LINK/USD": "PF_LINKUSD",
    # xStocks Backed Finance (tokens perpetuels backés par vraies actions/ETFs)
    # UI Kraken FR cache la recherche, MAIS API accepte les ordres (validé 2026-08-02).
    # Trading 24/7 avec levier ~10x auto, prix decouplé des vrais marchés NYSE.
    "AAPL": "PF_AAPLXUSD",
    "TSLA": "PF_TSLAXUSD",
    "NVDA": "PF_NVDAXUSD",
    "MSFT": "PF_MSFTXUSD",
    "GOOGL": "PF_GOOGLXUSD",
    "AMZN": "PF_AMZNXUSD",
    "MSTR": "PF_MSTRXUSD",
    "COIN": "PF_COINXUSD",
    "HOOD": "PF_HOODXUSD",
    "SPY": "PF_SPYXUSD",
    "QQQ": "PF_QQQXUSD",
    "GLD": "PF_GLDXUSD",
}


def _resolve_symbol(pair: str) -> str | None:
    return _PAIR_TO_SYMBOL.get(pair)


# ─── Auth Kraken Futures v3 ────────────────────────────────────────────

def _get_nonce() -> str:
    """Nonce unique croissant (millisecond timestamp + counter en cas de collision)."""
    global _last_nonce
    with _nonce_lock:
        candidate = int(time.time() * 1000)
        if candidate <= _last_nonce:
            candidate = _last_nonce + 1
        _last_nonce = candidate
        return str(candidate)


def _sign(endpoint_path: str, post_data: str, nonce: str) -> str:
    """Signature Kraken Futures v3.

    Formule officielle :
      Authent = Base64(HMAC_SHA512(
                        Base64Decode(API_SECRET),
                        SHA256(postData + nonce + endpoint_path_without_api_prefix)
                      ))

    Note : "endpoint_path" doit être SANS le préfixe "/derivatives" mais AVEC
    "/api/v3/xxx". Ex: pour /derivatives/api/v3/accounts, passer "/api/v3/accounts".
    """
    if not KRAKEN_API_SECRET:
        raise RuntimeError("KRAKEN_API_SECRET not set")
    message = (post_data + nonce + endpoint_path).encode()
    sha256_hash = hashlib.sha256(message).digest()
    secret_decoded = base64.b64decode(KRAKEN_API_SECRET)
    signature = hmac.new(secret_decoded, sha256_hash, hashlib.sha512).digest()
    return base64.b64encode(signature).decode()


def _signed_request(
    method: str, endpoint_path: str, params: dict | None = None, timeout: float = 10.0
) -> Any:
    """Appel signé Kraken Futures (nécessite API_KEY + SECRET).

    endpoint_path = chemin sans /derivatives, ex '/api/v3/accounts'.
    """
    if not KRAKEN_API_KEY or not KRAKEN_API_SECRET:
        raise RuntimeError("KRAKEN_API_KEY and KRAKEN_API_SECRET must be set")
    nonce = _get_nonce()
    # postData = query string (sorted for signature stability)
    params = params or {}
    post_data = urlencode(sorted(params.items()))
    signature = _sign(endpoint_path, post_data, nonce)
    headers = {
        "APIKey": KRAKEN_API_KEY,
        "Authent": signature,
        "Nonce": nonce,
        "Accept": "application/json",
    }
    url = f"{BASE_URL}{endpoint_path}"
    with httpx.Client(timeout=timeout) as c:
        if method.upper() == "GET":
            r = c.get(url, params=params, headers=headers)
        elif method.upper() == "POST":
            # Send the exact signed string as body (dict reordering by httpx breaks HMAC)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            r = c.post(url, content=post_data, headers=headers)
        else:
            raise ValueError(f"Unsupported method: {method}")
        r.raise_for_status()
        return r.json()


def _public_get(endpoint_path: str, params: dict | None = None, timeout: float = 8.0) -> Any:
    """Appel non-signé Kraken Futures (tickers, instruments)."""
    url = f"{BASE_URL}{endpoint_path}"
    with httpx.Client(timeout=timeout) as c:
        r = c.get(url, params=params or {})
        r.raise_for_status()
        return r.json()


# ─── Balance / safety refresh ──────────────────────────────────────────

def _get_current_balance_usd() -> float | None:
    """Retourne portefeuille USD (Trading account) sur Kraken Futures.

    Kraken renvoie plusieurs accounts (flex, cash, futures wallet). On agrège
    portfolioValue du 'flex' account (ou 'cash' fallback). Style USDⓈ-M.
    """
    try:
        data = _signed_request("GET", "/api/v3/accounts")
        if data.get("result") != "success":
            logger.warning(f"_get_current_balance_usd: response not success: {data}")
            return None
        accounts = data.get("accounts", {}) or {}
        # Kraken structure : accounts.cash, accounts.flex, accounts.futures
        # Le "cash" account contient les USD depositables ; le "flex" contient
        # les collaterals utilisables pour perpetuals.
        # Try flex first, fallback cash
        flex = accounts.get("flex") or {}
        cash = accounts.get("cash") or {}
        # portfolioValue = total collateral value in USD
        if flex.get("portfolioValue") is not None:
            return float(flex["portfolioValue"])
        if cash.get("balances", {}).get("USD") is not None:
            return float(cash["balances"]["USD"])
        return None
    except Exception as e:
        logger.debug(f"_get_current_balance_usd error: {e}")
        return None


def _refresh_start_of_day() -> None:
    """Miroir du bridge MT5/Binance : refresh au changement de jour + anti-drift."""
    global _start_of_day_balance, _start_of_day_date
    today = date.today()
    current = _get_current_balance_usd()
    if current is None:
        return
    if _start_of_day_date != today:
        _start_of_day_balance = current
        _start_of_day_date = today
        logger.info(
            f"Kraken start-of-day balance = {_start_of_day_balance:.2f} USD "
            f"(date={today.isoformat()})"
        )
        return
    if _start_of_day_balance is not None and current > 0:
        ratio = _start_of_day_balance / current
        if ratio > 1.5 or ratio < 0.667:
            logger.warning(
                f"Kraken start-of-day drift: cached={_start_of_day_balance:.2f} "
                f"actual={current:.2f} ratio={ratio:.2f} - resync"
            )
            _start_of_day_balance = current


def _check_daily_drawdown() -> tuple[bool, str]:
    """Retourne (ok, reason). ok=False → refuser /order (429)."""
    _refresh_start_of_day()
    if _start_of_day_balance is None or _start_of_day_balance <= 0:
        return True, ""
    current = _get_current_balance_usd()
    if current is None:
        return True, ""
    loss = _start_of_day_balance - current
    loss_limit = _start_of_day_balance * MAX_DAILY_LOSS_PCT / 100.0
    if loss >= loss_limit:
        return False, (
            f"Daily drawdown reached: loss={loss:.2f} >= limit={loss_limit:.2f} "
            f"({MAX_DAILY_LOSS_PCT}% of {_start_of_day_balance:.2f})"
        )
    return True, ""


# ─── Instruments cache ─────────────────────────────────────────────────
_specs_cache: dict[str, dict[str, Any]] = {}
_specs_cache_ts = 0.0
_SPECS_TTL_SEC = 3600  # 1h


def _refresh_specs_cache() -> None:
    """Charge la liste des instruments Kraken Futures (tickers actifs)."""
    global _specs_cache, _specs_cache_ts
    try:
        data = _public_get("/api/v3/instruments")
        if data.get("result") != "success":
            return
        cache = {}
        for inst in data.get("instruments", []):
            symbol = inst.get("symbol", "").upper()
            if not symbol or not inst.get("tradeable", False):
                continue
            cache[symbol] = {
                "symbol": symbol,
                "tickSize": float(inst.get("tickSize", 0.01)),
                "contractSize": float(inst.get("contractSize", 1.0)),
                "type": inst.get("type", ""),
                "tradeable": True,
            }
        _specs_cache = cache
        _specs_cache_ts = time.time()
        logger.info(f"Kraken specs cache refreshed: {len(cache)} tradeable instruments")
    except Exception as e:
        logger.warning(f"_refresh_specs_cache failed: {e}")


def _get_specs(symbol: str) -> dict | None:
    """Retourne les specs pour un symbol Kraken. Refresh cache si stale."""
    if time.time() - _specs_cache_ts > _SPECS_TTL_SEC:
        _refresh_specs_cache()
    return _specs_cache.get(symbol.upper())


# ─── Flask app + auth decorator ────────────────────────────────────────
app = Flask(__name__)


def require_bridge_key(fn):
    """Décorateur : exige X-Bridge-Key header matching BRIDGE_API_KEY."""

    @wraps(fn)
    def _wrapped(*args, **kwargs):
        if BRIDGE_API_KEY and request.headers.get("X-Bridge-Key") != BRIDGE_API_KEY:
            return jsonify({"error": "unauthorized"}), 401
        return fn(*args, **kwargs)

    return _wrapped


# ─── Routes ────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    """Ping Kraken public + config bridge. Pas d'auth requise côté Kraken."""
    try:
        # Test public reachability
        _public_get("/api/v3/instruments", timeout=5)
        return jsonify({
            "ok": True,
            "base_url": BASE_URL,
            "api_key_set": bool(KRAKEN_API_KEY),
            "api_secret_set": bool(KRAKEN_API_SECRET),
            "bridge_api_key_set": bool(BRIDGE_API_KEY),
            "port": BRIDGE_PORT,
            "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
            "live_whitelist_symbols": sorted(LIVE_WHITELIST_SYMBOLS) if LIVE_WHITELIST_SYMBOLS else [],
            "max_open_positions": MAX_OPEN_POSITIONS,
            "start_of_day_balance": _start_of_day_balance,
            "supported_pairs": len(_PAIR_TO_SYMBOL),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 503


@app.route("/account", methods=["GET"])
@require_bridge_key
def account():
    """Retourne les infos du compte Kraken Futures (balance, margin, PnL)."""
    try:
        data = _signed_request("GET", "/api/v3/accounts")
        if data.get("result") != "success":
            return jsonify({"ok": False, "error": "kraken response not success", "raw": data}), 503
        accounts = data.get("accounts", {}) or {}
        flex = accounts.get("flex") or {}
        return jsonify({
            "ok": True,
            "portfolio_value_usd": float(flex.get("portfolioValue", 0.0)),
            "available_margin_usd": float(flex.get("availableMargin", 0.0)),
            "initial_margin_usd": float(flex.get("initialMargin", 0.0)),
            "maintenance_margin_usd": float(flex.get("maintenanceMargin", 0.0)),
            "unrealized_pnl_usd": float(flex.get("unrealizedFunding", 0.0)),
            "raw_flex": flex,
            "raw_cash": accounts.get("cash", {}),
        })
    except Exception as e:
        logger.exception("account failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/positions", methods=["GET"])
@require_bridge_key
def positions():
    """Retourne les positions ouvertes sur Kraken Futures."""
    try:
        data = _signed_request("GET", "/api/v3/openpositions")
        if data.get("result") != "success":
            return jsonify({"ok": False, "error": "kraken response not success", "raw": data}), 503
        raw_positions = data.get("openPositions", []) or []
        cleaned = []
        for p in raw_positions:
            cleaned.append({
                "symbol": p.get("symbol"),
                "side": p.get("side"),  # "long" ou "short"
                "size": float(p.get("size", 0.0)),
                "price": float(p.get("price", 0.0)),
                "unrealizedFunding": float(p.get("unrealizedFunding", 0.0)),
                "fillTime": p.get("fillTime"),
            })
        return jsonify({"ok": True, "count": len(cleaned), "positions": cleaned})
    except Exception as e:
        logger.exception("positions failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/tick/<path:pair>", methods=["GET"])
@require_bridge_key
def tick(pair):
    """Retourne prix bid/ask/last pour une pair scalping-radar."""
    sym = _resolve_symbol(pair)
    if not sym:
        return jsonify({"ok": False, "error": f"unsupported pair {pair}"}), 400
    try:
        data = _public_get("/api/v3/tickers")
        if data.get("result") != "success":
            return jsonify({"ok": False, "error": "kraken tickers not success"}), 503
        for t in data.get("tickers", []):
            if t.get("symbol", "").upper() == sym:
                return jsonify({
                    "ok": True,
                    "pair": pair,
                    "symbol": sym,
                    "bid": float(t.get("bid", 0.0)),
                    "ask": float(t.get("ask", 0.0)),
                    "last": float(t.get("last", 0.0)),
                    "markPrice": float(t.get("markPrice", 0.0)),
                    "indexPrice": float(t.get("indexPrice", 0.0)),
                    "fundingRate": float(t.get("fundingRate", 0.0)),
                })
        return jsonify({"ok": False, "error": f"symbol {sym} not found in tickers"}), 404
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/symbols", methods=["GET"])
@require_bridge_key
def symbols():
    """Liste les symbols Kraken Futures tradeable (PF_ + PI_)."""
    try:
        data = _public_get("/api/v3/instruments")
        if data.get("result") != "success":
            return jsonify({"ok": False}), 503
        syms = [
            i["symbol"] for i in data.get("instruments", [])
            if i.get("tradeable") and i.get("symbol", "").startswith(("PF_", "PI_"))
        ]
        return jsonify({"ok": True, "count": len(syms), "symbols": sorted(syms)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/order", methods=["POST"])
@require_bridge_key
def place_order():
    """Place un ordre MARKET + optionnellement SL/TP (via 2 ordres separes reduceOnly).

    Payload JSON attendu (miroir binance-bridge) :
    {
      "pair": "BTC/USD",           # scalping-radar pair
      "direction": "buy" | "sell",
      "qty": 0.001,                # base asset quantity (BTC)
      "sl": 60000.0,               # optional SL trigger price
      "tp": 68000.0,               # optional TP trigger price
    }

    Réponse succès :
    {
      "ok": true, "mode": "live", "symbol": "PF_XBTUSD",
      "market_order_id": "...", "avg_price": 63000.0, "volume": 0.001,
      "sl_order_id": "..." | null, "tp_order_id": "..." | null,
    }
    """
    payload = request.get_json(force=True, silent=True) or {}
    pair = payload.get("pair")
    direction = (payload.get("direction") or "").lower()
    qty_raw = payload.get("qty")
    sl_raw = payload.get("sl")
    tp_raw = payload.get("tp")

    # Validation basique
    if direction not in ("buy", "sell") or qty_raw is None:
        return jsonify({"ok": False, "error": "payload requires pair, direction (buy/sell), qty"}), 400
    sym = _resolve_symbol(pair or "")
    if not sym:
        return jsonify({"ok": False, "error": f"unsupported pair {pair}"}), 400

    # Safety gate #1 : whitelist symbols opt-in strict
    if LIVE_WHITELIST_SYMBOLS and sym not in LIVE_WHITELIST_SYMBOLS:
        return jsonify({
            "ok": False, "blocked": True,
            "reason": f"symbol {sym} not in KRAKEN_LIVE_WHITELIST_SYMBOLS",
        }), 429

    # Safety gate #2 : daily drawdown
    ok, reason = _check_daily_drawdown()
    if not ok:
        return jsonify({"ok": False, "blocked": True, "reason": reason}), 429

    # Safety gate #3 : max positions ouvertes
    try:
        pos_data = _signed_request("GET", "/api/v3/openpositions")
        open_count = len(pos_data.get("openPositions", []) or [])
        if open_count >= MAX_OPEN_POSITIONS:
            return jsonify({
                "ok": False, "blocked": True,
                "reason": f"Max open positions reached: {open_count} >= {MAX_OPEN_POSITIONS}",
            }), 429
    except Exception as e:
        logger.warning(f"max positions check failed: {e}")

    # Get specs pour valider tickSize et size min
    specs = _get_specs(sym)
    if not specs:
        return jsonify({"ok": False, "error": f"no specs for {sym}"}), 503

    try:
        qty = float(qty_raw)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": f"invalid qty {qty_raw}"}), 400

    # ── Place market order ──
    market_params = {
        "orderType": "mkt",
        "symbol": sym,
        "side": direction,
        "size": qty,
    }
    try:
        market_resp = _signed_request("POST", "/api/v3/sendorder", market_params)
    except Exception as e:
        logger.exception("market order failed")
        return jsonify({"ok": False, "error": str(e), "step": "market_order"}), 500

    market_send_status = market_resp.get("sendStatus", {}) or {}
    market_order_id = market_send_status.get("order_id") or market_send_status.get("orderId")
    market_status = market_send_status.get("status", "unknown")

    if market_status not in ("placed", "partiallyFilled", "filled"):
        return jsonify({
            "ok": False,
            "error": f"market order rejected: status={market_status}",
            "raw": market_resp,
        }), 500

    # Extract avg price from fills if available
    fills = market_send_status.get("orderEvents", []) or []
    avg_price = 0.0
    total_filled_qty = 0.0
    total_notional = 0.0
    for f in fills:
        if f.get("type") == "EXECUTION":
            fill_qty = float(f.get("amount", 0.0))
            fill_price = float(f.get("price", 0.0))
            total_filled_qty += fill_qty
            total_notional += fill_qty * fill_price
    if total_filled_qty > 0:
        avg_price = total_notional / total_filled_qty

    # Round SL/TP to instrument tickSize (Kraken rejects off-tick prices with invalidPrice)
    tick = float(specs.get("tickSize", 0.01))

    def _round_to_tick(p: float) -> float:
        return round(round(p / tick) * tick, 8)

    # ── Place SL order (optional, reduceOnly) ──
    sl_order_id = None
    sl_error = None
    if sl_raw is not None:
        try:
            sl_price = _round_to_tick(float(sl_raw))
            sl_side = "sell" if direction == "buy" else "buy"
            sl_params = {
                "orderType": "stp",           # stop order
                "symbol": sym,
                "side": sl_side,
                "size": qty,
                "stopPrice": sl_price,
                "triggerSignal": "mark",      # trigger on mark price (plus stable que last)
                "reduceOnly": "true",
            }
            sl_resp = _signed_request("POST", "/api/v3/sendorder", sl_params)
            sl_status = (sl_resp.get("sendStatus", {}) or {})
            sl_order_id = sl_status.get("order_id") or sl_status.get("orderId")
            if sl_status.get("status") not in ("placed",):
                sl_error = f"SL status={sl_status.get('status')}"
        except Exception as e:
            sl_error = str(e)
            logger.warning(f"SL order failed for {sym}: {e}")

    # ── Place TP order (optional, reduceOnly) ──
    tp_order_id = None
    tp_error = None
    if tp_raw is not None:
        try:
            tp_price = _round_to_tick(float(tp_raw))
            tp_side = "sell" if direction == "buy" else "buy"
            tp_params = {
                "orderType": "take_profit",
                "symbol": sym,
                "side": tp_side,
                "size": qty,
                "stopPrice": tp_price,
                "triggerSignal": "mark",
                "reduceOnly": "true",
            }
            tp_resp = _signed_request("POST", "/api/v3/sendorder", tp_params)
            tp_status = (tp_resp.get("sendStatus", {}) or {})
            tp_order_id = tp_status.get("order_id") or tp_status.get("orderId")
            if tp_status.get("status") not in ("placed",):
                tp_error = f"TP status={tp_status.get('status')}"
        except Exception as e:
            tp_error = str(e)
            logger.warning(f"TP order failed for {sym}: {e}")

    return jsonify({
        "ok": True,
        "mode": "live",
        "symbol": sym,
        "pair": pair,
        "direction": direction,
        "volume": qty,
        "market_order_id": market_order_id,
        "avg_price": avg_price,
        "sl_order_id": sl_order_id,
        "sl_error": sl_error,
        "tp_order_id": tp_order_id,
        "tp_error": tp_error,
    })


@app.route("/kill", methods=["POST"])
@require_bridge_key
def kill_all():
    """Cancel all open orders + close all positions (kill-switch manuel)."""
    try:
        # Cancel all open orders
        cancel_resp = _signed_request("POST", "/api/v3/cancelallorders")
        # Close positions via market orders reduceOnly
        pos_data = _signed_request("GET", "/api/v3/openpositions")
        closed = []
        for p in pos_data.get("openPositions", []) or []:
            sym = p.get("symbol")
            side = p.get("side")
            size = float(p.get("size", 0.0))
            close_side = "sell" if side == "long" else "buy"
            close_params = {
                "orderType": "mkt",
                "symbol": sym,
                "side": close_side,
                "size": size,
                "reduceOnly": "true",
            }
            close_resp = _signed_request("POST", "/api/v3/sendorder", close_params)
            closed.append({"symbol": sym, "resp": close_resp})
        return jsonify({
            "ok": True,
            "cancel_all_orders": cancel_resp,
            "closed_positions": closed,
        })
    except Exception as e:
        logger.exception("kill_all failed")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─── Boot ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info(f"kraken-bridge starting port={BRIDGE_PORT} base={BASE_URL}")
    logger.info(f"  MAX_DAILY_LOSS_PCT       : {MAX_DAILY_LOSS_PCT}%")
    logger.info(f"  LIVE_WHITELIST_SYMBOLS   : {sorted(LIVE_WHITELIST_SYMBOLS) if LIVE_WHITELIST_SYMBOLS else 'ALL ALLOWED'}")
    logger.info(f"  MAX_OPEN_POSITIONS       : {MAX_OPEN_POSITIONS}")
    logger.info(f"  Supported pairs          : {len(_PAIR_TO_SYMBOL)}")
    try:
        _refresh_specs_cache()
    except Exception as e:
        logger.warning(f"initial specs cache refresh failed: {e}")
    app.run(host="0.0.0.0", port=BRIDGE_PORT, threaded=True)
