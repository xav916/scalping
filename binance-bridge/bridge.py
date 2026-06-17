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
import os
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
      "qty": 0.01,             // base currency quantity (e.g. BTC)
      "sl": 95800.0,           // optional
      "tp": 97500.0,           // optional
      "leverage": 5,           // optional, set per symbol if provided
      "margin_type": "ISOLATED"  // optional, default ISOLATED
    }

    Stub R&D : implémentation à compléter avec test sur testnet.
    """
    payload = request.get_json(force=True, silent=True) or {}
    return jsonify({
        "ok": False,
        "error": "not_implemented_yet",
        "received": payload,
        "next_step": "implement after testnet keys configured + manual cli test",
    }), 501


@app.route("/kill", methods=["POST"])
@require_bridge_key
def kill_all():
    """Cancel all open orders + close all positions. Emergency stop.
    Stub R&D."""
    return jsonify({"ok": False, "error": "not_implemented_yet"}), 501


if __name__ == "__main__":
    port = int(os.getenv("BINANCE_BRIDGE_PORT", "8789"))
    logger.info(f"binance-bridge starting env={BINANCE_ENV} base={BASE_URL} port={port}")
    app.run(host="0.0.0.0", port=port, debug=False)
