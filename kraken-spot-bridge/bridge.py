"""Kraken Spot bridge — trading BTC/ETH au comptant (long-only) pour scalping-radar.

Fork du kraken-futures-bridge (2026-08-02). API Kraken Spot est différente de
Kraken Futures sur tous les points critiques :
- Endpoint : api.kraken.com/0/private/* (vs futures.kraken.com/derivatives/api/v3/*)
- Auth : HMAC-SHA512(urlpath + SHA256(nonce + POST body), base64_decode(secret))
  vs Futures : HMAC-SHA512(base64_decode(secret), SHA256(postData + nonce + endpoint))
- Pas de short (long-only), pas de levier, pas d'OCO natif
- Symboles : XBT pas BTC (XBTUSD, ETHUSD)
- Watcher SL/TP émulé via thread poll toutes les 5s

## Safety gates (miroir Futures + Binance commit 0b60261)

- KRAKEN_SPOT_MAX_DAILY_LOSS_PCT (default 3%) — kill-switch avec anti-drift built-in
- KRAKEN_SPOT_MAX_OPEN_POSITIONS (default 5)
- KRAKEN_SPOT_LIVE_WHITELIST_SYMBOLS — opt-in strict (default XBTUSD,ETHUSD)

## Env vars requises

- KRAKEN_SPOT_API_KEY
- KRAKEN_SPOT_API_SECRET
- KRAKEN_SPOT_BRIDGE_API_KEY (auth interne bridge↔radar)
- KRAKEN_SPOT_BRIDGE_PORT (default 8791, evite collision Futures 8790)

## Pièges signature Spot (CRITIQUES)

1. Envoyer body en content=postdata (string urlencodée exacte), pas data=dict
   — httpx réordonne le dict et casse le HMAC
2. Nonce DANS le POST body (pas dans headers comme Futures)
3. SHA256(nonce + POST body) puis HMAC-SHA512 du message = urlpath + sha256_digest
   Direction des opérations est l'inverse de Futures

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


# ─── Empreinte de la source ────────────────────────────────────────────
# ⛔ Calculee A L'IMPORT, jamais a la requete. Un fichier edite sur disque
# n'est pas le code que le processus execute : hacher a la requete
# annoncerait la NOUVELLE version tout en faisant tourner l'ANCIENNE, ce qui
# est pire que pas d'empreinte du tout.
#
# Pourquoi elle existe (2026-08-25) : le repli de resolution de symbole ajoute
# le 08/08 a disparu sans que personne le voie, faute de pouvoir comparer ce
# qui tourne a ce qui est versionne. Comparer avec :
#     sha256sum <fichier du depot> | cut -c1-12
def _empreinte_source() -> str:
    try:
        with open(__file__, "rb") as fichier:
            octets = fichier.read()
    except Exception:  # noqa: BLE001 — une empreinte absente ne casse rien
        return "inconnue"
    # ⚠️ Fins de ligne normalisees AVANT le hachage. Les fichiers du VPS sont
    # en CRLF, le depot est stocke en LF, et git reconvertit a la sortie : sans
    # cela, deux copies au contenu IDENTIQUE annonceraient des empreintes
    # differentes, et la comparaison — seule raison d'etre de ce champ —
    # crierait a la derive en permanence.
    # Sequences construites par code : ecrire une sequence d echappement
    # dans un fichier qui en contient deja est une source d erreur inutile.
    return hashlib.sha256(
        octets.replace(bytes([13, 10]), bytes([10]))
    ).hexdigest()[:12]


SOURCE_SHA = _empreinte_source()
DEMARRE_A = datetime.now(timezone.utc).isoformat(timespec="seconds")


# ─── Config ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("kraken-spot-bridge")

BASE_URL = "https://api.kraken.com"
KRAKEN_SPOT_API_KEY = os.getenv("KRAKEN_SPOT_API_KEY", "")
KRAKEN_SPOT_API_SECRET = os.getenv("KRAKEN_SPOT_API_SECRET", "")
BRIDGE_API_KEY = os.getenv("KRAKEN_SPOT_BRIDGE_API_KEY", "")
BRIDGE_PORT = int(os.getenv("KRAKEN_SPOT_BRIDGE_PORT", "8791"))

# ─── Safety gates ──────────────────────────────────────────────────────
MAX_DAILY_LOSS_PCT = float(os.getenv("KRAKEN_SPOT_MAX_DAILY_LOSS_PCT", "3.0"))
MAX_OPEN_POSITIONS = int(os.getenv("KRAKEN_SPOT_MAX_OPEN_POSITIONS", "5"))
LIVE_WHITELIST_SYMBOLS = frozenset(
    s.strip().upper()
    for s in os.getenv("KRAKEN_SPOT_LIVE_WHITELIST_SYMBOLS", "XBTUSD,ETHUSD").split(",")
    if s.strip()
)

_start_of_day_balance: float | None = None
_start_of_day_date: date | None = None
_nonce_lock = threading.Lock()
_last_nonce = 0

# ─── Symbol mapping ────────────────────────────────────────────────────
# scalping-radar pair → Kraken Spot symbol
# Kraken Spot utilise XBT pas BTC
_PAIR_TO_SYMBOL: dict[str, str] = {
    "BTC/USD": "XBTUSD",
    "ETH/USD": "ETHUSD",
}


def _resolve_symbol(pair: str) -> str | None:
    return _PAIR_TO_SYMBOL.get(pair)


# ─── Auth Kraken Spot ──────────────────────────────────────────────────

def _get_nonce() -> str:
    """Nonce unique croissant (millisecond timestamp + counter en cas de collision).

    Thread-safe via _nonce_lock — le watcher SL/TP tourne dans un thread
    séparé et peut appeler _signed_post en parallèle.
    """
    global _last_nonce
    with _nonce_lock:
        candidate = int(time.time() * 1000)
        if candidate <= _last_nonce:
            candidate = _last_nonce + 1
        _last_nonce = candidate
        return str(candidate)


def _sign(urlpath: str, data: dict, nonce: str) -> str:
    """Signature Kraken Spot.

    Formule officielle :
      API-Sign = base64(HMAC-SHA512(
                          base64_decode(api_secret),
                          urlpath + SHA256(nonce + POST body)
                        ))

    Note :
    - Le nonce EST dans data (pas dans les headers comme Futures).
    - POST body = urlencode(data) incluant nonce.
    - SHA256 digest appliqué sur (nonce + POST body) en bytes.
    - HMAC-SHA512 sur (urlpath_bytes + sha256_digest_bytes).

    PIÈGE : ne PAS passer data à httpx comme dict (réordonnancement).
    Utiliser content=postdata (string exacte déjà urlencodée).
    """
    if not KRAKEN_SPOT_API_SECRET:
        raise RuntimeError("KRAKEN_SPOT_API_SECRET not set")
    postdata = urlencode(data)  # data inclut déjà nonce
    encoded = (nonce + postdata).encode()
    sha256_hash = hashlib.sha256(encoded).digest()
    message = urlpath.encode() + sha256_hash
    secret_decoded = base64.b64decode(KRAKEN_SPOT_API_SECRET)
    mac = hmac.new(secret_decoded, message, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


def _signed_post(endpoint: str, params: dict) -> dict:
    """POST signé vers Kraken Spot API.

    endpoint ex: '/0/private/Balance'
    params = dict sans nonce (nonce ajouté ici)

    Retourne le JSON Kraken. Vérifie response.error[].
    """
    if not KRAKEN_SPOT_API_KEY or not KRAKEN_SPOT_API_SECRET:
        raise RuntimeError("KRAKEN_SPOT_API_KEY and KRAKEN_SPOT_API_SECRET must be set")
    nonce = _get_nonce()
    params_with_nonce = {**params, "nonce": nonce}
    # Build exact POST body string — ne pas laisser httpx réordonner
    postdata = urlencode(params_with_nonce)
    sig = _sign(endpoint, params_with_nonce, nonce)
    headers = {
        "API-Key": KRAKEN_SPOT_API_KEY,
        "API-Sign": sig,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    with httpx.Client(timeout=10.0) as c:
        r = c.post(f"{BASE_URL}{endpoint}", content=postdata, headers=headers)
        r.raise_for_status()
    return r.json()


def _public_get(path: str, params: dict | None = None, timeout: float = 8.0) -> Any:
    """GET non-signé Kraken Spot (ticker, asset pairs)."""
    with httpx.Client(timeout=timeout) as c:
        r = c.get(f"{BASE_URL}{path}", params=params or {})
        r.raise_for_status()
    return r.json()


# ─── Asset specs cache ─────────────────────────────────────────────────
_specs_cache: dict[str, dict[str, Any]] = {}
_specs_cache_ts = 0.0
_SPECS_TTL_SEC = 3600  # 1h


def _refresh_specs_cache() -> None:
    """Charge les specs des paires Kraken Spot (lot_decimals, tick_size, ordermin)."""
    global _specs_cache, _specs_cache_ts
    try:
        data = _public_get("/0/public/AssetPairs")
        if data.get("error"):
            logger.warning(f"_refresh_specs_cache error: {data['error']}")
            return
        cache = {}
        for pair_name, info in (data.get("result") or {}).items():
            # Inclure seulement les pairs USD (altname propre ex XBTUSD)
            altname = info.get("altname", pair_name)
            cache[altname.upper()] = {
                "altname": altname,
                "lot_decimals": int(info.get("lot_decimals", 8)),
                "pair_decimals": int(info.get("pair_decimals", 1)),  # tick size decimals
                "ordermin": float(info.get("ordermin", 0.0001)),
            }
        _specs_cache = cache
        _specs_cache_ts = time.time()
        logger.info(f"Kraken Spot specs cache refreshed: {len(cache)} pairs")
    except Exception as e:
        logger.warning(f"_refresh_specs_cache failed: {e}")


def _get_specs(symbol: str) -> dict | None:
    """Retourne specs pour un symbol Kraken Spot. Refresh si stale."""
    if time.time() - _specs_cache_ts > _SPECS_TTL_SEC:
        _refresh_specs_cache()
    return _specs_cache.get(symbol.upper())


# ─── Balance helpers ───────────────────────────────────────────────────

def _get_last_price(kraken_pair: str) -> float | None:
    """Retourne le dernier prix d'une pair Kraken Spot via /0/public/Ticker."""
    try:
        data = _public_get("/0/public/Ticker", {"pair": kraken_pair}, timeout=5)
        if data.get("error"):
            return None
        result = data.get("result") or {}
        # La clé dans result peut différer légèrement de la pair demandée
        # (ex: XXBTZUSD vs XBTUSD) — prendre la première valeur
        if not result:
            return None
        ticker = next(iter(result.values()))
        return float(ticker["c"][0])  # c = last trade closed [price, lot_volume]
    except Exception as e:
        logger.debug(f"_get_last_price({kraken_pair}) error: {e}")
        return None


def _get_spot_balances_usd() -> float | None:
    """Retourne la valeur totale du portefeuille en USD (balance USD + cryptos valorisées).

    Agrège :
    - Balance USD (ZUSD sur Kraken)
    - Balance XBT (XXBT) * prix XBTUSD
    - Balance ETH (XETH) * prix ETHUSD

    Utilisé pour les safety gates (drawdown journalier).
    """
    try:
        data = _signed_post("/0/private/Balance", {})
        if data.get("error"):
            logger.warning(f"_get_spot_balances_usd error: {data['error']}")
            return None
        balances = data.get("result") or {}
        total = 0.0
        usd = float(balances.get("ZUSD", 0.0))
        total += usd
        xbt = float(balances.get("XXBT", 0.0))
        if xbt > 0:
            p = _get_last_price("XBTUSD")
            if p:
                total += xbt * p
        eth = float(balances.get("XETH", 0.0))
        if eth > 0:
            p = _get_last_price("ETHUSD")
            if p:
                total += eth * p
        return total
    except Exception as e:
        logger.debug(f"_get_spot_balances_usd error: {e}")
        return None


def _refresh_start_of_day() -> None:
    """Miroir du bridge MT5/Binance/Futures : refresh au changement de jour + anti-drift."""
    global _start_of_day_balance, _start_of_day_date
    today = date.today()
    current = _get_spot_balances_usd()
    if current is None:
        return
    if _start_of_day_date != today:
        _start_of_day_balance = current
        _start_of_day_date = today
        logger.info(
            f"Kraken Spot start-of-day balance = {_start_of_day_balance:.2f} USD "
            f"(date={today.isoformat()})"
        )
        return
    if _start_of_day_balance is not None and current > 0:
        ratio = _start_of_day_balance / current
        if ratio > 1.5 or ratio < 0.667:
            logger.warning(
                f"Kraken Spot start-of-day drift: cached={_start_of_day_balance:.2f} "
                f"actual={current:.2f} ratio={ratio:.2f} - resync"
            )
            _start_of_day_balance = current


def _check_daily_drawdown() -> tuple[bool, str]:
    """Retourne (ok, reason). ok=False → refuser /order (429)."""
    _refresh_start_of_day()
    if _start_of_day_balance is None or _start_of_day_balance <= 0:
        return True, ""
    current = _get_spot_balances_usd()
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


# ─── Watcher SL/TP émulé ──────────────────────────────────────────────
# Kraken Spot n'a pas d'OCO natif. On poll le prix toutes les 5s.
# Si SL ou TP atteint, on vend au market.

_watchers: dict[str, dict] = {}  # {entry_txid: {pair, kraken_pair, qty, sl, tp, thread}}
_watchers_lock = threading.Lock()


def _watcher_loop(
    txid: str,
    pair: str,
    kraken_pair: str,
    qty: float,
    sl: float,
    tp: float,
) -> None:
    """Poll prix toutes les 5s. Long-only : SL si last<=sl, TP si last>=tp."""
    logger.info(
        f"watcher started txid={txid} pair={pair} qty={qty} sl={sl} tp={tp}"
    )
    while True:
        try:
            data = _public_get("/0/public/Ticker", {"pair": kraken_pair}, timeout=5)
            if not data.get("error"):
                result = data.get("result") or {}
                if result:
                    ticker = next(iter(result.values()))
                    last = float(ticker["c"][0])
                    hit_sl = last <= sl
                    hit_tp = last >= tp
                    if hit_sl or hit_tp:
                        reason = "SL" if hit_sl else "TP"
                        logger.warning(
                            f"watcher {txid} {reason} triggered @ {last} "
                            f"(sl={sl} tp={tp}), selling {qty} {kraken_pair}"
                        )
                        sell_params = {
                            "pair": kraken_pair,
                            "type": "sell",
                            "ordertype": "market",
                            "volume": str(qty),
                        }
                        try:
                            resp = _signed_post("/0/private/AddOrder", sell_params)
                            if resp.get("error"):
                                logger.warning(
                                    f"watcher {txid} sell error: {resp['error']}"
                                )
                            else:
                                logger.info(f"watcher {txid} sold: {resp.get('result')}")
                        except Exception as sell_ex:
                            logger.warning(f"watcher {txid} sell exception: {sell_ex}")
                        with _watchers_lock:
                            _watchers.pop(txid, None)
                        return
        except Exception as e:
            logger.warning(f"watcher {txid} poll error: {e}")
        time.sleep(5)


def _start_watcher(txid: str, pair: str, kraken_pair: str, qty: float, sl: float, tp: float) -> None:
    """Démarre le watcher SL/TP dans un daemon thread."""
    t = threading.Thread(
        target=_watcher_loop,
        args=(txid, pair, kraken_pair, qty, sl, tp),
        name=f"watcher-{txid}",
        daemon=True,
    )
    with _watchers_lock:
        _watchers[txid] = {
            "pair": pair,
            "kraken_pair": kraken_pair,
            "qty": qty,
            "sl": sl,
            "tp": tp,
            "thread": t,
        }
    t.start()


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
    """Ping Kraken Spot public (Ticker) + config bridge. Pas d'auth."""
    try:
        _public_get("/0/public/Ticker", {"pair": "XBTUSD"}, timeout=5)
        with _watchers_lock:
            active_watchers = len(_watchers)
        return jsonify({
            "source_sha": SOURCE_SHA,
            "demarre_a": DEMARRE_A,
            "ok": True,
            "base_url": BASE_URL,
            "api_key_set": bool(KRAKEN_SPOT_API_KEY),
            "api_secret_set": bool(KRAKEN_SPOT_API_SECRET),
            "bridge_api_key_set": bool(BRIDGE_API_KEY),
            "port": BRIDGE_PORT,
            "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
            "max_open_positions": MAX_OPEN_POSITIONS,
            "live_whitelist_symbols": sorted(LIVE_WHITELIST_SYMBOLS),
            "start_of_day_balance": _start_of_day_balance,
            "supported_pairs": list(_PAIR_TO_SYMBOL.keys()),
            "active_watchers": active_watchers,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 503


@app.route("/account", methods=["GET"])
@require_bridge_key
def account():
    """Balance USD + valeur crypto du portefeuille Spot."""
    try:
        data = _signed_post("/0/private/Balance", {})
        if data.get("error"):
            return jsonify({"ok": False, "error": str(data["error"])}), 503
        balances = data.get("result") or {}

        # Valoriser chaque position
        usd = float(balances.get("ZUSD", 0.0))
        xbt = float(balances.get("XXBT", 0.0))
        eth = float(balances.get("XETH", 0.0))
        xbt_price = _get_last_price("XBTUSD") or 0.0
        eth_price = _get_last_price("ETHUSD") or 0.0
        total = usd + xbt * xbt_price + eth * eth_price

        return jsonify({
            "ok": True,
            "usd_balance": usd,
            "xbt_balance": xbt,
            "eth_balance": eth,
            "xbt_price_usd": xbt_price,
            "eth_price_usd": eth_price,
            "portfolio_value_usd": total,
            "raw_balances": balances,
        })
    except Exception as e:
        logger.exception("account failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/positions", methods=["GET"])
@require_bridge_key
def positions():
    """Positions Spot ouvertes = balances crypto non-USD * prix courant."""
    try:
        data = _signed_post("/0/private/Balance", {})
        if data.get("error"):
            return jsonify({"ok": False, "error": str(data["error"])}), 503
        balances = data.get("result") or {}

        pos = []
        # XBT
        xbt = float(balances.get("XXBT", 0.0))
        if xbt > 0.00001:
            price = _get_last_price("XBTUSD") or 0.0
            pos.append({
                "asset": "XBT",
                "pair": "BTC/USD",
                "kraken_pair": "XBTUSD",
                "qty": xbt,
                "price_usd": price,
                "value_usd": xbt * price,
            })
        # ETH
        eth = float(balances.get("XETH", 0.0))
        if eth > 0.0001:
            price = _get_last_price("ETHUSD") or 0.0
            pos.append({
                "asset": "ETH",
                "pair": "ETH/USD",
                "kraken_pair": "ETHUSD",
                "qty": eth,
                "price_usd": price,
                "value_usd": eth * price,
            })

        # Watchers actifs
        with _watchers_lock:
            watcher_list = [
                {k: v for k, v in w.items() if k != "thread"}
                for w in _watchers.values()
            ]

        return jsonify({
            "ok": True,
            "count": len(pos),
            "positions": pos,
            "active_watchers": watcher_list,
        })
    except Exception as e:
        logger.exception("positions failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/tick/<path:pair>", methods=["GET"])
@require_bridge_key
def tick(pair):
    """Prix bid/ask/last pour une pair scalping-radar (BTC/USD, ETH/USD)."""
    sym = _resolve_symbol(pair)
    if not sym:
        return jsonify({"ok": False, "error": f"unsupported pair {pair}"}), 400
    try:
        data = _public_get("/0/public/Ticker", {"pair": sym})
        if data.get("error"):
            return jsonify({"ok": False, "error": str(data["error"])}), 503
        result = data.get("result") or {}
        if not result:
            return jsonify({"ok": False, "error": f"no ticker data for {sym}"}), 404
        ticker = next(iter(result.values()))
        return jsonify({
            "ok": True,
            "pair": pair,
            "symbol": sym,
            "bid": float(ticker["b"][0]),
            "ask": float(ticker["a"][0]),
            "last": float(ticker["c"][0]),
            "volume_24h": float(ticker["v"][1]),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/symbols", methods=["GET"])
@require_bridge_key
def symbols():
    """Liste les pairs Spot supportés par ce bridge (whitelist)."""
    return jsonify({
        "ok": True,
        "whitelist_symbols": sorted(LIVE_WHITELIST_SYMBOLS),
        "supported_pairs": list(_PAIR_TO_SYMBOL.keys()),
    })


@app.route("/order", methods=["POST"])
@require_bridge_key
def place_order():
    """Place un ordre market BUY (long-only) + démarre watcher SL/TP.

    Payload JSON attendu (miroir kraken-futures-bridge) :
    {
      "pair": "BTC/USD",
      "direction": "buy",      # obligatoirement "buy" — spot = long-only
      "qty": 0.0001,           # base asset quantity (XBT)
      "sl": 60000.0,           # optional — watcher sell si last<=sl
      "tp": 68000.0,           # optional — watcher sell si last>=tp
    }

    Réponse succès :
    {
      "ok": true, "mode": "live", "symbol": "XBTUSD",
      "txid": "OABCD-...", "descr": "buy 0.0001 XBTUSD @ market",
      "watcher_started": true,
    }
    """
    payload = request.get_json(force=True, silent=True) or {}
    pair = payload.get("pair")
    direction = (payload.get("direction") or "").lower()
    qty_raw = payload.get("qty")
    sl_raw = payload.get("sl")
    tp_raw = payload.get("tp")

    # Long-only enforce
    if direction == "sell":
        return jsonify({
            "ok": False,
            "error": "spot bridge is long-only, sell direction rejected",
        }), 400

    if direction not in ("buy",) or qty_raw is None:
        return jsonify({
            "ok": False,
            "error": "payload requires pair, direction=buy, qty",
        }), 400

    sym = _resolve_symbol(pair or "")
    if not sym:
        return jsonify({"ok": False, "error": f"unsupported pair {pair}"}), 400

    # Safety gate #1 : whitelist symbols opt-in strict
    if LIVE_WHITELIST_SYMBOLS and sym not in LIVE_WHITELIST_SYMBOLS:
        return jsonify({
            "ok": False, "blocked": True,
            "reason": f"symbol {sym} not in KRAKEN_SPOT_LIVE_WHITELIST_SYMBOLS",
        }), 429

    # Safety gate #2 : daily drawdown
    ok, reason = _check_daily_drawdown()
    if not ok:
        return jsonify({"ok": False, "blocked": True, "reason": reason}), 429

    # Safety gate #3 : max positions ouvertes (nombre de watchers actifs = proxy)
    with _watchers_lock:
        active_count = len(_watchers)
    if active_count >= MAX_OPEN_POSITIONS:
        return jsonify({
            "ok": False, "blocked": True,
            "reason": f"Max open positions reached: {active_count} >= {MAX_OPEN_POSITIONS}",
        }), 429

    # Get specs pour lot_decimals (arrondi volume requis par Kraken)
    specs = _get_specs(sym)
    lot_decimals = specs["lot_decimals"] if specs else 8

    try:
        qty = float(qty_raw)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": f"invalid qty {qty_raw}"}), 400

    # Arrondi volume au lot_decimals de l'instrument
    qty = round(qty, lot_decimals)
    if qty <= 0:
        return jsonify({"ok": False, "error": "qty rounds to 0 after lot_decimals truncation"}), 400

    # Vérifier ordermin
    if specs and qty < specs.get("ordermin", 0.0):
        return jsonify({
            "ok": False,
            "error": f"qty {qty} below ordermin {specs['ordermin']} for {sym}",
        }), 400

    # ── Place market buy ──
    market_params = {
        "pair": sym,
        "type": "buy",
        "ordertype": "market",
        "volume": str(qty),
    }
    try:
        resp = _signed_post("/0/private/AddOrder", market_params)
    except Exception as e:
        logger.exception("market buy failed")
        return jsonify({"ok": False, "error": str(e), "step": "market_order"}), 500

    errors = resp.get("error") or []
    if errors:
        return jsonify({
            "ok": False,
            "error": f"AddOrder rejected: {errors}",
            "raw": resp,
        }), 500

    result = resp.get("result") or {}
    txids = result.get("txid") or []
    txid = txids[0] if txids else None
    descr = (result.get("descr") or {}).get("order", "")

    # ── Démarrer watcher SL/TP si sl ou tp fournis ──
    watcher_started = False
    if txid and (sl_raw is not None or tp_raw is not None):
        # Valeurs SL/TP — si l'une est absente, utiliser 0 / infini
        sl_val = float(sl_raw) if sl_raw is not None else 0.0
        tp_val = float(tp_raw) if tp_raw is not None else float("inf")
        # Arrondir sl/tp au pair_decimals (tick_size)
        if specs:
            decimals = specs.get("pair_decimals", 1)
            sl_val = round(sl_val, decimals)
            tp_val = round(tp_val, decimals)
        _start_watcher(txid, pair, sym, qty, sl_val, tp_val)
        watcher_started = True

    logger.warning(
        f"kraken-spot-bridge order placed: {pair} buy {qty} txid={txid} descr={descr!r}"
    )

    return jsonify({
        "ok": True,
        "mode": "live",
        "symbol": sym,
        "pair": pair,
        "direction": "buy",
        "volume": qty,
        "txid": txid,
        "descr": descr,
        "watcher_started": watcher_started,
        "sl": sl_raw,
        "tp": tp_raw,
    })


@app.route("/kill", methods=["POST"])
@require_bridge_key
def kill_all():
    """Cancel all open orders + vend toutes les positions crypto au market.

    Arrête aussi tous les watchers actifs avant de vendre.
    """
    results = {}
    try:
        # 1. Cancel tous les ordres ouverts
        cancel_resp = _signed_post("/0/private/CancelAll", {})
        results["cancel_all"] = cancel_resp

        # 2. Arrêter les watchers (ils ne doivent pas re-vendre après le kill)
        with _watchers_lock:
            watcher_txids = list(_watchers.keys())
            _watchers.clear()
        results["watchers_stopped"] = len(watcher_txids)

        # 3. Vendre toutes les crypto au market
        sell_results = []
        bal_data = _signed_post("/0/private/Balance", {})
        balances = (bal_data.get("result") or {}) if not bal_data.get("error") else {}

        for asset, kraken_sym in [("XXBT", "XBTUSD"), ("XETH", "ETHUSD")]:
            qty_raw = float(balances.get(asset, 0.0))
            if qty_raw < 0.00001:
                continue
            specs = _get_specs(kraken_sym)
            lot_decimals = specs["lot_decimals"] if specs else 8
            qty = round(qty_raw, lot_decimals)
            if qty <= 0:
                continue
            sell_params = {
                "pair": kraken_sym,
                "type": "sell",
                "ordertype": "market",
                "volume": str(qty),
            }
            try:
                sell_resp = _signed_post("/0/private/AddOrder", sell_params)
                sell_results.append({"asset": asset, "qty": qty, "resp": sell_resp})
            except Exception as se:
                sell_results.append({"asset": asset, "qty": qty, "error": str(se)})

        results["sell_positions"] = sell_results
        return jsonify({"ok": True, **results})
    except Exception as e:
        logger.exception("kill_all failed")
        return jsonify({"ok": False, "error": str(e), "partial": results}), 500


# ─── Boot ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info(f"kraken-spot-bridge starting port={BRIDGE_PORT} base={BASE_URL}")
    logger.info(f"  MAX_DAILY_LOSS_PCT       : {MAX_DAILY_LOSS_PCT}%")
    logger.info(f"  MAX_OPEN_POSITIONS       : {MAX_OPEN_POSITIONS}")
    logger.info(f"  LIVE_WHITELIST_SYMBOLS   : {sorted(LIVE_WHITELIST_SYMBOLS)}")
    logger.info(f"  Supported pairs          : {list(_PAIR_TO_SYMBOL.keys())}")
    try:
        _refresh_specs_cache()
    except Exception as e:
        logger.warning(f"initial specs cache refresh failed: {e}")
    app.run(host="0.0.0.0", port=BRIDGE_PORT, threaded=True)
