"""Binance USDⓈ-M Futures bridge for Scalping Radar.

Mirror of mt5-bridge/bridge.py contract: same HTTP endpoints (`/health`,
`/account`, `/symbols`, `/tick/<pair>`, `/symbol_specs/<pair>`, `/order`,
`/positions`, `/deals`, `/kill`) so scalping-radar can route signals to
either bridge transparently via `bridge_destinations`.

Two environment switch via env var BINANCE_ENV={testnet,live}:
- testnet : https://testnet.binancefuture.com (no real money, free signup)
- live    : https://fapi.binance.com (real money, KYC required)

Pair convention: scalping-radar uses "BTC/USD", "ETH/USD", etc. Binance
USDⓈ-M uses "BTCUSDT", "ETHUSDT". Mapping is done in `_resolve_symbol()`.

Auth: HMAC-SHA256 of the URL-encoded query string + timestamp, sent as
`signature` param. API key in `X-MBX-APIKEY` header.

Margin mode: ISOLATED per position (set on first order per symbol).
Position mode: ONE-WAY (single position per symbol).

Stage R&D — single-tenant Xavier testnet. Multi-tenant routing à
ajouter quand on productize (cf. memory feedback_multi_tenant_by_default).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import os
import threading
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from flask import Flask, jsonify, request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("binance-bridge")

BINANCE_ENV = os.getenv("BINANCE_ENV", "testnet").lower()
_BASE_URLS = {
    "testnet": "https://testnet.binancefuture.com",
    "live": "https://fapi.binance.com",
}
BASE_URL = _BASE_URLS.get(BINANCE_ENV)
if BASE_URL is None:
    raise SystemExit(f"BINANCE_ENV invalid: {BINANCE_ENV} (testnet|live)")

API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BRIDGE_API_KEY = os.getenv("BINANCE_BRIDGE_API_KEY", "")  # protège ce bridge

# STOP_MARKET réels (Phase 2 Palier 2 — chantier #8). Testnet rejette via
# -4120 donc default false ; on bascule true en live ou explicit.
_USE_REAL_STOPS_RAW = os.getenv("BINANCE_USE_REAL_STOPS", "").strip().lower()
if _USE_REAL_STOPS_RAW in ("true", "1", "yes"):
    USE_REAL_STOPS = True
elif _USE_REAL_STOPS_RAW in ("false", "0", "no"):
    USE_REAL_STOPS = False
else:
    USE_REAL_STOPS = BINANCE_ENV == "live"  # auto-true en live, false sinon

# Maker orders post-only LIMIT (chantier #11) — fee 0.02% vs 0.05% taker +
# meilleur prix d'exécution. Fallback MARKET si non rempli dans le timeout.
USE_MAKER_ORDERS = os.getenv("BINANCE_USE_MAKER_ORDERS", "false").strip().lower() in ("true", "1", "yes")
MAKER_TIMEOUT_SEC = float(os.getenv("BINANCE_MAKER_TIMEOUT_SEC", "30"))
MAKER_POLL_SEC = float(os.getenv("BINANCE_MAKER_POLL_SEC", "2"))

# Mapping pair scalping-radar → symbole Binance USDⓈ-M futures.
# Convention : BASE/USD → BASEUSDT (Binance perp collatéralisé USDT).
_PAIR_TO_SYMBOL: dict[str, str] = {
    "BTC/USD": "BTCUSDT",
    "ETH/USD": "ETHUSDT",
    "SOL/USD": "SOLUSDT",
    "ADA/USD": "ADAUSDT",
    "XRP/USD": "XRPUSDT",
    "LTC/USD": "LTCUSDT",
    "BCH/USD": "BCHUSDT",
    "DOT/USD": "DOTUSDT",
    "DOGE/USD": "DOGEUSDT",
}


def _resolve_symbol(pair: str) -> str | None:
    """Convertit une pair scalping-radar en symbole Binance Futures."""
    return _PAIR_TO_SYMBOL.get(pair)


def _sign(params: dict[str, Any]) -> dict[str, Any]:
    """Ajoute timestamp + signature HMAC-SHA256. Mutation in-place."""
    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)
    query = urlencode(params, doseq=True)
    sig = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = sig
    return params


def _public_get(path: str, params: dict | None = None, timeout: float = 8.0) -> Any:
    """Appel non-signé (exchangeInfo, ping, ticker)."""
    url = f"{BASE_URL}{path}"
    with httpx.Client(timeout=timeout) as c:
        r = c.get(url, params=params or {})
        r.raise_for_status()
        return r.json()


def _signed_request(method: str, path: str, params: dict | None = None, timeout: float = 10.0) -> Any:
    """Appel signé (account, positions, order). Requires API_KEY + SECRET."""
    if not API_KEY or not API_SECRET:
        raise RuntimeError("BINANCE_API_KEY and BINANCE_API_SECRET must be set")
    params = _sign(params or {})
    url = f"{BASE_URL}{path}"
    headers = {"X-MBX-APIKEY": API_KEY}
    with httpx.Client(timeout=timeout) as c:
        if method == "GET":
            r = c.get(url, params=params, headers=headers)
        elif method == "POST":
            r = c.post(url, params=params, headers=headers)
        elif method == "DELETE":
            r = c.delete(url, params=params, headers=headers)
        else:
            raise ValueError(f"method {method} not supported")
        if r.status_code >= 400:
            logger.warning(f"binance {method} {path} → {r.status_code}: {r.text[:200]}")
        r.raise_for_status()
        return r.json()


# ─── Specs cache (exchangeInfo) ──────────────────────────────────────

_SPECS_CACHE: dict[str, dict[str, Any]] = {}
_SPECS_FETCHED_AT: float = 0.0
_SPECS_TTL_SEC: float = 3600.0  # 1h


def _refresh_specs_cache() -> None:
    global _SPECS_FETCHED_AT
    info = _public_get("/fapi/v1/exchangeInfo", timeout=15)
    _SPECS_CACHE.clear()
    for s in info.get("symbols", []):
        filters = {f["filterType"]: f for f in s.get("filters", [])}
        lot = filters.get("LOT_SIZE", {})
        price = filters.get("PRICE_FILTER", {})
        notional = filters.get("MIN_NOTIONAL", {}) or filters.get("NOTIONAL", {})
        _SPECS_CACHE[s["symbol"]] = {
            "minQty": float(lot.get("minQty", 0)),
            "maxQty": float(lot.get("maxQty", 0)),
            "stepSize": float(lot.get("stepSize", 0)),
            "tickSize": float(price.get("tickSize", 0)),
            "minNotional": float(notional.get("notional", notional.get("minNotional", 0))),
            "quantityPrecision": int(s.get("quantityPrecision", 0)),
            "pricePrecision": int(s.get("pricePrecision", 0)),
            "status": s.get("status"),
        }
    _SPECS_FETCHED_AT = time.time()
    logger.info(f"exchangeInfo cache refreshed: {len(_SPECS_CACHE)} symbols")


def _get_specs(symbol: str) -> dict[str, Any] | None:
    """Spécifications d'un symbole (cache 1h). Force le 1er refresh si vide."""
    if not _SPECS_CACHE or (time.time() - _SPECS_FETCHED_AT) > _SPECS_TTL_SEC:
        _refresh_specs_cache()
    return _SPECS_CACHE.get(symbol)


def _floor_to_step(value: float, step: float, precision: int) -> float:
    """Plancher value au multiple de step le plus proche par défaut."""
    if step <= 0:
        return round(value, precision)
    n = math.floor(value / step + 1e-12)
    return round(n * step, precision)


def _round_to_tick(value: float, tick: float, precision: int) -> float:
    """Arrondit value au multiple de tick le plus proche (pour prix SL/TP)."""
    if tick <= 0:
        return round(value, precision)
    n = round(value / tick)
    return round(n * tick, precision)


# ─── SL/TP émulés côté bridge ────────────────────────────────────────
# Binance Futures testnet rejette STOP_MARKET / TAKE_PROFIT_MARKET via
# /fapi/v1/order (error -4120). On émule donc SL/TP via un watcher
# thread qui polle le ticker et envoie MARKET reduceOnly au trigger.
# Le même code marche en prod (où STOP_MARKET fonctionne) : c'est une
# option de simplicité, à la prod on pourra basculer vers vrais
# STOP_MARKET si la latence du watcher pose souci.

_managed_positions: dict[str, dict[str, Any]] = {}  # keyed by symbol
_managed_lock = threading.Lock()
_WATCHER_POLL_SEC = 3.0


def _place_maker_or_market(
    sym: str, side: str, qty: float, entry_norm: float | None,
    client_order_id: str, specs: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Place un ordre d'entrée. Si USE_MAKER_ORDERS + entry_norm → tente LIMIT
    post-only (timeInForce=GTX), polle jusqu'à MAKER_TIMEOUT_SEC, fallback
    MARKET si pas rempli. Retourne (order_response, mode_used).

    mode_used ∈ {"maker_filled", "maker_partial_fallback_market", "market"}.
    """
    if USE_MAKER_ORDERS and entry_norm is not None:
        try:
            limit_resp = _signed_request("POST", "/fapi/v1/order", params={
                "symbol": sym, "side": side, "type": "LIMIT",
                "timeInForce": "GTX",  # post-only — rejette si match immédiat
                "price": entry_norm, "quantity": qty,
                "newClientOrderId": f"{client_order_id}_maker",
            })
            limit_order_id = limit_resp.get("orderId")
            deadline = time.time() + MAKER_TIMEOUT_SEC
            while time.time() < deadline:
                time.sleep(MAKER_POLL_SEC)
                try:
                    o = _signed_request("GET", "/fapi/v1/order",
                                        params={"symbol": sym, "orderId": limit_order_id})
                    status = o.get("status")
                    executed = float(o.get("executedQty", 0) or 0)
                    if status == "FILLED":
                        return o, "maker_filled"
                    if status in ("CANCELED", "REJECTED", "EXPIRED"):
                        logger.info(f"maker {sym} status={status} → fallback MARKET (executed={executed})")
                        break
                except Exception as e:
                    logger.warning(f"maker poll {sym}: {e}")
                    break
            # Timeout ou rejet : cancel le LIMIT restant + fallback MARKET avec
            # quantity = qty restant (= qty - executed sur partial fill).
            try:
                cancel_resp = _signed_request("DELETE", "/fapi/v1/order",
                                              params={"symbol": sym, "orderId": limit_order_id})
                executed_so_far = float(cancel_resp.get("executedQty", 0) or 0)
            except Exception as e:
                logger.warning(f"maker cancel {sym}: {e}")
                executed_so_far = 0.0
            remaining = _floor_to_step(qty - executed_so_far, specs["stepSize"], specs["quantityPrecision"])
            if remaining < specs["minQty"]:
                # Partial fill suffisant : ne pas re-MARKET, garder le partial
                logger.info(f"maker {sym} partial fill {executed_so_far}/{qty}, no fallback (remaining {remaining} < minQty)")
                return {"executedQty": executed_so_far, "avgPrice": entry_norm}, "maker_partial_no_fallback"
            mode = "maker_partial_fallback_market" if executed_so_far > 0 else "market"
            market_resp = _signed_request("POST", "/fapi/v1/order", params={
                "symbol": sym, "side": side, "type": "MARKET",
                "quantity": remaining,
                "newClientOrderId": f"{client_order_id}_mkt",
            })
            return market_resp, mode
        except httpx.HTTPStatusError as e:
            body = e.response.text[:300] if e.response else str(e)
            # GTX rejette avec -2021 si "Order would immediately match" — fallback silencieux
            if "-2021" in body or "would immediately" in body.lower():
                logger.info(f"maker {sym} would cross → MARKET fallback")
            else:
                logger.warning(f"maker {sym} HTTPError: {body}")
        except Exception as e:
            logger.warning(f"maker {sym} exception, fallback MARKET: {e}")

    # MARKET par défaut (ou fallback après échec maker)
    market_resp = _signed_request("POST", "/fapi/v1/order", params={
        "symbol": sym, "side": side, "type": "MARKET",
        "quantity": qty, "newClientOrderId": client_order_id,
    })
    return market_resp, "market"


def _place_real_stop_market(
    sym: str, opp_side: str, sl_norm: float | None, tp_norm: float | None,
    client_order_id: str,
) -> dict[str, Any]:
    """Place les vrais STOP_MARKET + TAKE_PROFIT_MARKET via /fapi/v1/order.

    Both use closePosition=true (Binance ferme la position complète au trigger,
    indépendamment du qty). Retourne {sl_order_id, tp_order_id, sl_error, tp_error}.
    Best-effort : si un échoue, l'autre est tenté. Errors loggées.
    """
    out: dict[str, Any] = {}
    if sl_norm is not None:
        try:
            r = _signed_request("POST", "/fapi/v1/order", params={
                "symbol": sym, "side": opp_side, "type": "STOP_MARKET",
                "stopPrice": sl_norm, "closePosition": "true",
                "newClientOrderId": f"{client_order_id}_sl",
                "workingType": "MARK_PRICE",  # trigger sur mark, plus stable vs spot wick
            })
            out["sl_order_id"] = r.get("orderId")
        except httpx.HTTPStatusError as e:
            body = e.response.text[:200] if e.response else str(e)
            logger.warning(f"STOP_MARKET {sym} failed: {body}")
            out["sl_error"] = body
        except Exception as e:
            out["sl_error"] = str(e)[:200]
    if tp_norm is not None:
        try:
            r = _signed_request("POST", "/fapi/v1/order", params={
                "symbol": sym, "side": opp_side, "type": "TAKE_PROFIT_MARKET",
                "stopPrice": tp_norm, "closePosition": "true",
                "newClientOrderId": f"{client_order_id}_tp",
                "workingType": "MARK_PRICE",
            })
            out["tp_order_id"] = r.get("orderId")
        except httpx.HTTPStatusError as e:
            body = e.response.text[:200] if e.response else str(e)
            logger.warning(f"TAKE_PROFIT_MARKET {sym} failed: {body}")
            out["tp_error"] = body
        except Exception as e:
            out["tp_error"] = str(e)[:200]
    return out


def _trigger_close(symbol: str, qty: float, side_to_close: str, reason: str) -> bool:
    """Envoie MARKET reduceOnly pour fermer une position. Retourne True si ok."""
    try:
        r = _signed_request("POST", "/fapi/v1/order", params={
            "symbol": symbol, "side": side_to_close, "type": "MARKET",
            "quantity": qty, "reduceOnly": "true",
        })
        logger.warning(f"emulated {reason} triggered for {symbol}: order {r.get('orderId')}")
        return True
    except Exception as e:
        logger.error(f"emulated {reason} close failed for {symbol}: {e}")
        return False


def _watcher_loop() -> None:
    """Daemon thread : polle les positions managées + ferme au touché SL/TP."""
    while True:
        try:
            time.sleep(_WATCHER_POLL_SEC)
            with _managed_lock:
                items = list(_managed_positions.items())
            for sym, m in items:
                try:
                    tick = _public_get("/fapi/v1/ticker/price", params={"symbol": sym})
                    price = float(tick["price"])
                except Exception as e:
                    logger.debug(f"watcher tick {sym} failed: {e}")
                    continue
                sl, tp = m.get("sl"), m.get("tp")
                qty, direction = m["qty"], m["direction"]
                close_side = "SELL" if direction == "buy" else "BUY"
                hit = None
                if direction == "buy":
                    if sl is not None and price <= sl:
                        hit = "SL"
                    elif tp is not None and price >= tp:
                        hit = "TP"
                else:
                    if sl is not None and price >= sl:
                        hit = "SL"
                    elif tp is not None and price <= tp:
                        hit = "TP"
                if hit:
                    ok = _trigger_close(sym, qty, close_side, hit)
                    if ok:
                        with _managed_lock:
                            _managed_positions.pop(sym, None)
        except Exception as e:
            logger.warning(f"watcher loop iter failed: {e}")


def _start_watcher() -> None:
    t = threading.Thread(target=_watcher_loop, daemon=True, name="bridge-sltp-watcher")
    t.start()
    logger.info(f"sltp watcher started (poll={_WATCHER_POLL_SEC}s)")


# ─── Flask app ────────────────────────────────────────────────────────

app = Flask(__name__)


def require_bridge_key(fn):
    """Décorateur : exige X-Bridge-Key header matching BRIDGE_API_KEY."""
    from functools import wraps

    @wraps(fn)
    def _wrapped(*args, **kwargs):
        if BRIDGE_API_KEY and request.headers.get("X-Bridge-Key") != BRIDGE_API_KEY:
            return jsonify({"error": "unauthorized"}), 401
        return fn(*args, **kwargs)

    return _wrapped


@app.route("/health", methods=["GET"])
def health():
    """Ping Binance + retourne config bridge (no auth nécessaire côté Binance)."""
    try:
        _public_get("/fapi/v1/ping")
        return jsonify({
            "ok": True,
            "env": BINANCE_ENV,
            "base_url": BASE_URL,
            "api_key_set": bool(API_KEY),
            "api_secret_set": bool(API_SECRET),
            "use_real_stops": USE_REAL_STOPS,
            "use_maker_orders": USE_MAKER_ORDERS,
            "maker_timeout_sec": MAKER_TIMEOUT_SEC,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 503


@app.route("/symbols", methods=["GET"])
@require_bridge_key
def symbols():
    """Liste les symboles USDⓈ-M actifs. Filtre via ?query=BTC."""
    try:
        info = _public_get("/fapi/v1/exchangeInfo")
        syms = [s["symbol"] for s in info.get("symbols", []) if s.get("status") == "TRADING"]
        q = request.args.get("query", "").strip().upper()
        if q:
            syms = [s for s in syms if q in s]
        return jsonify({"count": len(syms), "symbols": syms[:500]})
    except Exception as e:
        return jsonify({"error": str(e)}), 503


@app.route("/symbol_specs/<path:pair>", methods=["GET"])
@require_bridge_key
def symbol_specs(pair):
    """Specs Binance pour une pair : minQty/maxQty/stepSize + tickSize + minNotional.
    Équivalent du /symbol_specs côté MT5 (cf. mt5-bridge:1130) pour debugger sizing.
    """
    sym = _resolve_symbol(pair)
    if not sym:
        return jsonify({"error": f"unsupported pair {pair}"}), 404
    try:
        info = _public_get("/fapi/v1/exchangeInfo")
        s = next((x for x in info.get("symbols", []) if x["symbol"] == sym), None)
        if not s:
            return jsonify({"error": f"symbol {sym} not found in exchangeInfo"}), 404
        filters = {f["filterType"]: f for f in s.get("filters", [])}
        lot = filters.get("LOT_SIZE", {})
        price = filters.get("PRICE_FILTER", {})
        notional = filters.get("MIN_NOTIONAL", {}) or filters.get("NOTIONAL", {})
        return jsonify({
            "pair": pair,
            "symbol": sym,
            "status": s.get("status"),
            "minQty": float(lot.get("minQty", 0)),
            "maxQty": float(lot.get("maxQty", 0)),
            "stepSize": float(lot.get("stepSize", 0)),
            "tickSize": float(price.get("tickSize", 0)),
            "minNotional": float(notional.get("notional", notional.get("minNotional", 0))),
            "pricePrecision": s.get("pricePrecision"),
            "quantityPrecision": s.get("quantityPrecision"),
            "baseAsset": s.get("baseAsset"),
            "quoteAsset": s.get("quoteAsset"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 503


@app.route("/tick/<path:pair>", methods=["GET"])
@require_bridge_key
def tick(pair):
    """Dernier prix mark/index pour une pair."""
    sym = _resolve_symbol(pair)
    if not sym:
        return jsonify({"error": f"unsupported pair {pair}"}), 404
    try:
        r = _public_get("/fapi/v1/ticker/price", params={"symbol": sym})
        return jsonify({"pair": pair, "symbol": sym, "price": float(r["price"])})
    except Exception as e:
        return jsonify({"error": str(e)}), 503


@app.route("/account", methods=["GET"])
@require_bridge_key
def account():
    """Balance + marge disponible + positions agrégées."""
    try:
        a = _signed_request("GET", "/fapi/v2/account")
        return jsonify({
            "ok": True,
            "totalWalletBalance": float(a.get("totalWalletBalance", 0)),
            "totalUnrealizedProfit": float(a.get("totalUnrealizedProfit", 0)),
            "availableBalance": float(a.get("availableBalance", 0)),
            "maxWithdrawAmount": float(a.get("maxWithdrawAmount", 0)),
            "positions_count": sum(1 for p in a.get("positions", []) if float(p.get("positionAmt", 0)) != 0),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 503


@app.route("/positions", methods=["GET"])
@require_bridge_key
def positions():
    """Positions ouvertes (positionRisk filtré sur positionAmt != 0)."""
    try:
        rows = _signed_request("GET", "/fapi/v2/positionRisk")
        active = [
            {
                "symbol": r["symbol"],
                "positionAmt": float(r["positionAmt"]),
                "entryPrice": float(r["entryPrice"]),
                "markPrice": float(r["markPrice"]),
                "unrealizedProfit": float(r["unRealizedProfit"]),
                "liquidationPrice": float(r["liquidationPrice"]) if r.get("liquidationPrice") not in (None, "0") else None,
                "leverage": int(r["leverage"]),
                "marginType": r["marginType"],
            }
            for r in rows
            if float(r.get("positionAmt", 0)) != 0
        ]
        return jsonify({"count": len(active), "positions": active})
    except Exception as e:
        return jsonify({"error": str(e)}), 503


@app.route("/order", methods=["POST"])
@require_bridge_key
def place_order():
    """Place un ordre MARKET + SL (STOP_MARKET) + TP (TAKE_PROFIT_MARKET).

    Payload JSON :
    {
      "pair": "BTC/USD",
      "direction": "buy" | "sell",
      "qty": 0.001,            // base currency quantity (e.g. BTC)
      "sl": 64000.0,           // optional, prix absolu
      "tp": 67000.0,           // optional, prix absolu
      "leverage": 5,           // optional, set per symbol si fourni
      "margin_type": "ISOLATED"  // optional, default ISOLATED
    }

    SL/TP utilisent closePosition=true (clôture totale au trigger, pas de quantity).
    Best-effort sur SL/TP : si l'un fail, l'ordre MARKET reste intact, on
    log le détail dans la réponse (champs sl_error / tp_error).
    """
    payload = request.get_json(force=True, silent=True) or {}
    pair = payload.get("pair")
    direction = (payload.get("direction") or "").lower()
    qty_raw = payload.get("qty")
    sl_raw = payload.get("sl")
    tp_raw = payload.get("tp")
    entry_raw = payload.get("entry")  # optional — utilisé pour maker LIMIT post-only
    leverage = payload.get("leverage")
    margin_type = (payload.get("margin_type") or "ISOLATED").upper()

    if direction not in ("buy", "sell") or qty_raw is None:
        return jsonify({"ok": False, "error": "payload requires pair, direction (buy/sell), qty"}), 400
    sym = _resolve_symbol(pair or "")
    if not sym:
        return jsonify({"ok": False, "error": f"unsupported pair {pair}"}), 400

    try:
        specs = _get_specs(sym)
        if not specs or specs.get("status") != "TRADING":
            return jsonify({"ok": False, "error": f"no TRADING specs for {sym}"}), 503

        qty = _floor_to_step(float(qty_raw), specs["stepSize"], specs["quantityPrecision"])
        if qty < specs["minQty"]:
            return jsonify({"ok": False, "error": f"qty {qty} < minQty {specs['minQty']}"}), 400

        # Vérif notional vs prix courant
        tick = _public_get("/fapi/v1/ticker/price", params={"symbol": sym})
        mark_price = float(tick["price"])
        notional = qty * mark_price
        if notional < specs["minNotional"]:
            return jsonify({"ok": False,
                            "error": f"notional {notional:.2f} < minNotional {specs['minNotional']} (qty={qty}, price={mark_price})"}), 400

        # Margin type (idempotent ; ignore "no change needed" -4046)
        try:
            _signed_request("POST", "/fapi/v1/marginType",
                            params={"symbol": sym, "marginType": margin_type})
        except httpx.HTTPStatusError as e:
            if "-4046" not in (e.response.text if e.response else ""):
                logger.warning(f"marginType {sym}: {e.response.text[:200] if e.response else e}")

        # Leverage (idempotent)
        if leverage:
            try:
                _signed_request("POST", "/fapi/v1/leverage",
                                params={"symbol": sym, "leverage": int(leverage)})
            except httpx.HTTPStatusError as e:
                logger.warning(f"leverage {sym}: {e.response.text[:200] if e.response else e}")

        side = "BUY" if direction == "buy" else "SELL"
        opp_side = "SELL" if direction == "buy" else "BUY"
        client_order_id = f"sr_{int(time.time() * 1000)}"
        entry_norm = (_round_to_tick(float(entry_raw), specs["tickSize"], specs["pricePrecision"])
                      if entry_raw is not None else None)

        # Entry — MARKET ou maker LIMIT post-only (selon USE_MAKER_ORDERS)
        entry_resp, entry_mode = _place_maker_or_market(
            sym, side, qty, entry_norm, client_order_id, specs,
        )
        market_order_id = entry_resp.get("orderId")
        executed_qty = float(entry_resp.get("executedQty", 0) or 0)
        avg_price = float(entry_resp.get("avgPrice", 0) or 0)
        # Re-poll si NEW pas encore filled (peut arriver sur MARKET aussi).
        if (executed_qty == 0 or avg_price == 0) and market_order_id:
            time.sleep(0.2)
            try:
                o = _signed_request("GET", "/fapi/v1/order",
                                    params={"symbol": sym, "orderId": market_order_id})
                executed_qty = float(o.get("executedQty", 0) or 0) or qty
                avg_price = float(o.get("avgPrice", 0) or 0) or mark_price
            except Exception as e:
                logger.warning(f"order re-poll {sym}: {e}")
                executed_qty = qty
                avg_price = mark_price
        if avg_price == 0:
            avg_price = mark_price
        if executed_qty == 0:
            executed_qty = qty

        # SL/TP — 2 modes :
        # - USE_REAL_STOPS=true (prod live default) : STOP_MARKET + TAKE_PROFIT_MARKET
        #   via /fapi/v1/order avec closePosition=true. Trigger natif Binance ~50ms.
        # - USE_REAL_STOPS=false (testnet default, rejette -4120) : watcher thread
        #   qui polle le ticker et envoie MARKET reduceOnly au trigger (~3-6s).
        # En cas d'erreur STOP_MARKET (-4120 ou autre), fallback automatique watcher.
        sl_norm = (_round_to_tick(float(sl_raw), specs["tickSize"], specs["pricePrecision"])
                   if sl_raw is not None else None)
        tp_norm = (_round_to_tick(float(tp_raw), specs["tickSize"], specs["pricePrecision"])
                   if tp_raw is not None else None)

        sltp_mode = "watcher_emulated"
        real_stops_info: dict[str, Any] = {}
        if USE_REAL_STOPS and (sl_norm is not None or tp_norm is not None):
            real_stops_info = _place_real_stop_market(
                sym, opp_side, sl_norm, tp_norm, client_order_id,
            )
            sl_ok = "sl_order_id" in real_stops_info
            tp_ok = "tp_order_id" in real_stops_info
            sl_skipped = sl_norm is None
            tp_skipped = tp_norm is None
            # Si les ordres demandés sont tous placés, on s'appuie sur les
            # vrais stops Binance et on skip le watcher. Sinon fallback.
            if (sl_ok or sl_skipped) and (tp_ok or tp_skipped):
                sltp_mode = "real_stop_market"
            else:
                logger.warning(
                    f"real stops partial fail for {sym}, fallback to watcher: {real_stops_info}"
                )

        if sltp_mode == "watcher_emulated":
            with _managed_lock:
                _managed_positions[sym] = {
                    "qty": executed_qty,
                    "direction": direction,
                    "sl": sl_norm,
                    "tp": tp_norm,
                    "avg_price": avg_price,
                    "client_order_id": client_order_id,
                    "opened_at": time.time(),
                }

        return jsonify({
            "ok": True,
            "pair": pair, "symbol": sym, "direction": direction,
            "qty": executed_qty, "avg_price": avg_price,
            "market_order_id": market_order_id,
            "client_order_id": client_order_id,
            "sl_emulated": sl_norm, "tp_emulated": tp_norm,
            "sl_tp_mode": sltp_mode,
            "entry_mode": entry_mode,
            **real_stops_info,
        })
    except httpx.HTTPStatusError as e:
        body = e.response.text[:500] if e.response else str(e)
        logger.warning(f"order {sym} HTTPStatusError: {body}")
        return jsonify({"ok": False, "error": body}), 502
    except Exception as e:
        logger.exception(f"order {sym} failed")
        return jsonify({"ok": False, "error": str(e)[:300]}), 500


@app.route("/kill", methods=["POST"])
@require_bridge_key
def kill_all():
    """Cancel all open orders + close all positions. Emergency stop.
    Vide aussi le dict des positions managées par le watcher SL/TP."""
    with _managed_lock:
        _managed_positions.clear()
    out = {"cancelled_symbols": [], "closed_positions": [], "errors": []}
    try:
        positions = _signed_request("GET", "/fapi/v2/positionRisk")
        active = [p for p in positions if float(p.get("positionAmt", 0)) != 0]
        symbols_active: set[str] = {p["symbol"] for p in active}
        # Symboles avec open orders sans position
        try:
            open_orders = _signed_request("GET", "/fapi/v1/openOrders")
            symbols_active.update(o["symbol"] for o in open_orders)
        except Exception as e:
            out["errors"].append(f"openOrders fetch: {str(e)[:200]}")

        for sym in symbols_active:
            try:
                _signed_request("DELETE", "/fapi/v1/allOpenOrders", params={"symbol": sym})
                out["cancelled_symbols"].append(sym)
            except Exception as e:
                out["errors"].append(f"cancel {sym}: {str(e)[:150]}")

        for p in active:
            sym = p["symbol"]
            amt = float(p["positionAmt"])
            side = "SELL" if amt > 0 else "BUY"
            try:
                _signed_request("POST", "/fapi/v1/order", params={
                    "symbol": sym, "side": side, "type": "MARKET",
                    "quantity": abs(amt), "reduceOnly": "true",
                })
                out["closed_positions"].append({"symbol": sym, "qty": abs(amt)})
            except Exception as e:
                out["errors"].append(f"close {sym}: {str(e)[:150]}")

        return jsonify({"ok": True, **out})
    except Exception as e:
        logger.exception("kill failed")
        return jsonify({"ok": False, "error": str(e)[:200], **out}), 500


if __name__ == "__main__":
    port = int(os.getenv("BINANCE_BRIDGE_PORT", "8789"))
    logger.info(
        f"binance-bridge starting env={BINANCE_ENV} base={BASE_URL} port={port} "
        f"use_real_stops={USE_REAL_STOPS}"
    )
    _start_watcher()
    app.run(host="0.0.0.0", port=port, debug=False)
