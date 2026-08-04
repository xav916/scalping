"""IBKR bridge — Voie C, vraies actions US en DMA via Interactive Brokers.

Squelette **lecture seule** monté le 2026-08-04. Complète les Voies A
(xStocks Kraken, tokens) et B (CFD IC Markets) par de vraies actions
détenues au nom de Xavier, avec prix NYSE/NASDAQ en direct.

## État au 2026-08-04

- ✅ Endpoints lecture : /health, /account, /positions, /tick, /symbols
- ⛔ /order **désactivé par défaut** — renvoie 403 tant que
  `IBKR_ALLOW_ORDERS=true` n'est pas posé explicitement
- 🟡 Permission « US Stocks & ETFs » en attente d'approbation IBKR : sans
  elle, /tick et /order échouent sur les actions (le reste fonctionne)

## Double garde-fou sur les ordres

1. `IBKR_ALLOW_ORDERS` (défaut false) → /order renvoie 403 côté bridge
2. Quand ce flag est false, la connexion est ouverte avec `readonly=True`,
   donc **IB Gateway lui-même** refuse tout ordre. Une erreur de code ne
   peut pas contourner la couche 2.

Motif : le Gateway de Xavier tourne en mode **Live avec 100 EUR réels** et
sans paper account disponible (création bloquée tant que les Actions US ne
sont pas approuvées). Aucun filet en dessous.

## Différences structurelles vs les bridges Kraken / Binance

| Aspect | Kraken / Binance | IBKR |
|---|---|---|
| Transport | REST + HMAC | socket TCP propriétaire vers Gateway local |
| Auth | clé API + secret | session Gateway (login humain ou IBC) |
| Modèle | requête/réponse | asyncio event-driven, connexion longue |
| Symboles | PF_XBTUSD | `Stock('AAPL', 'SMART', 'USD')` |

Le point délicat : Flask est synchrone, `ib_async` est asyncio avec une
connexion persistante. On fait tourner une event loop dédiée dans un
thread daemon et les handlers Flask y soumettent leurs coroutines via
`asyncio.run_coroutine_threadsafe`. Un seul thread parle à IB, ce qui
évite les courses sur la socket.

## Env vars

- `IBKR_GATEWAY_HOST` (défaut 127.0.0.1)
- `IBKR_GATEWAY_PORT` (défaut 4001 = Gateway Live ; 4002 = Paper)
- `IBKR_CLIENT_ID` (défaut 17 — doit être unique par client connecté)
- `IBKR_BRIDGE_API_KEY` — auth interne bridge↔radar (header X-Bridge-Key)
- `IBKR_BRIDGE_PORT` (défaut 8792 — après Kraken Spot 8791)
- `IBKR_ALLOW_ORDERS` (défaut false)
- `IBKR_MARKET_DATA_TYPE` (défaut 3 = delayed ; 1 = live, nécessite un
  abonnement data payant que Xavier n'a pas encore)

Cf. mémoire project_voie_c_ibkr_roadmap.md
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from functools import wraps
from typing import Any

from flask import Flask, jsonify, request

from ib_async import IB, Forex, Stock

# ─── Config ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ibkr-bridge")

GATEWAY_HOST = os.getenv("IBKR_GATEWAY_HOST", "127.0.0.1")
GATEWAY_PORT = int(os.getenv("IBKR_GATEWAY_PORT", "4001"))
CLIENT_ID = int(os.getenv("IBKR_CLIENT_ID", "17"))
BRIDGE_API_KEY = os.getenv("IBKR_BRIDGE_API_KEY", "")
BRIDGE_PORT = int(os.getenv("IBKR_BRIDGE_PORT", "8792"))
ALLOW_ORDERS = os.getenv("IBKR_ALLOW_ORDERS", "false").lower() in ("1", "true", "yes", "on")
MARKET_DATA_TYPE = int(os.getenv("IBKR_MARKET_DATA_TYPE", "3"))

# readonly=True demande au Gateway de refuser tout ordre au niveau session.
# C'est la garde-fou n°2 : elle survit à un bug applicatif côté bridge.
IB_READONLY = not ALLOW_ORDERS

REQUEST_TIMEOUT_SEC = 20.0

# ─── Symbol mapping ────────────────────────────────────────────────────
# pair scalping-radar → contrat IBKR.
#
# SMART routing : IBKR choisit la meilleure venue (NYSE / NASDAQ / ARCA /
# BATS...). C'est la différence avec la Voie B, où IC Markets impose le
# suffixe .NAS, et avec la Voie A où Kraken utilise PF_AAPLXUSD.
_EQUITY_SYMBOLS = (
    "AAPL", "TSLA", "NVDA", "MSFT", "GOOGL", "AMZN", "META", "AMD", "NFLX",
)

_FOREX_PAIRS: dict[str, str] = {
    "EUR/USD": "EURUSD",
    "GBP/USD": "GBPUSD",
    "USD/JPY": "USDJPY",
    "USD/CHF": "USDCHF",
    "AUD/USD": "AUDUSD",
    "USD/CAD": "USDCAD",
}


def contract_for(pair: str):
    """Traduit une pair scalping-radar en contrat IBKR, ou None si non supportée."""
    p = pair.strip().upper()
    if p in _EQUITY_SYMBOLS:
        return Stock(p, "SMART", "USD")
    if p in _FOREX_PAIRS:
        return Forex(_FOREX_PAIRS[p])
    return None


def supported_pairs() -> list[str]:
    return sorted([*_EQUITY_SYMBOLS, *_FOREX_PAIRS])


# ─── Worker asyncio dédié ──────────────────────────────────────────────


class IBWorker:
    """Détient l'event loop et la connexion IB dans un thread unique.

    Toutes les interactions avec le Gateway passent par ``submit`` : la
    socket IB n'est donc jamais touchée par deux threads Flask à la fois.
    """

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.ib = IB()
        self._lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run_loop, name="ibkr-worker", daemon=True
        )
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro) -> Any:
        """Exécute une coroutine sur la loop du worker et rend son résultat."""
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout=REQUEST_TIMEOUT_SEC)

    def call(self, fn) -> Any:
        """Invoque ``fn()`` **depuis** la loop du worker et attend son résultat.

        Indispensable : certaines méthodes d'``ib_async`` (``reqPositionsAsync``
        notamment) ne sont pas de simples ``async def`` — elles touchent
        l'event loop dès l'appel, avant tout ``await``. Les invoquer depuis un
        thread Flask lève « There is no current event loop in thread
        'MainThread' ». Passer par un lambda garantit que l'appel lui-même a
        lieu dans le thread qui possède la loop.
        """

        async def _invoke():
            return await fn()

        return self.submit(_invoke())

    async def _ensure_connected(self) -> None:
        if self.ib.isConnected():
            return
        logger.info(
            f"connexion Gateway {GATEWAY_HOST}:{GATEWAY_PORT} "
            f"clientId={CLIENT_ID} readonly={IB_READONLY}"
        )
        await self.ib.connectAsync(
            GATEWAY_HOST, GATEWAY_PORT, clientId=CLIENT_ID, readonly=IB_READONLY
        )
        # 3 = delayed. Sans abonnement data payant, un type 1 (live) renvoie
        # des ticks vides sans lever d'erreur — piège classique.
        self.ib.reqMarketDataType(MARKET_DATA_TYPE)
        logger.info(
            f"connecté — serverVersion={self.ib.client.serverVersion()} "
            f"accounts={self.ib.managedAccounts()}"
        )

    def ensure_connected(self) -> None:
        # Sérialisé : deux requêtes Flask concurrentes sur un bridge
        # déconnecté ne doivent pas ouvrir deux sessions.
        with self._lock:
            self.call(self._ensure_connected)


worker = IBWorker()

# ─── Flask ─────────────────────────────────────────────────────────────

app = Flask(__name__)


def require_bridge_key(fn):
    """Décorateur : exige X-Bridge-Key header matching BRIDGE_API_KEY."""

    @wraps(fn)
    def _wrapped(*args, **kwargs):
        if BRIDGE_API_KEY and request.headers.get("X-Bridge-Key") != BRIDGE_API_KEY:
            return jsonify({"error": "unauthorized"}), 401
        return fn(*args, **kwargs)

    return _wrapped


@app.route("/health", methods=["GET"])
def health():
    try:
        worker.ensure_connected()
        ib = worker.ib
        return jsonify({
            "ok": True,
            "connected": ib.isConnected(),
            "gateway": f"{GATEWAY_HOST}:{GATEWAY_PORT}",
            "server_version": ib.client.serverVersion(),
            "accounts": list(ib.managedAccounts()),
            "client_id": CLIENT_ID,
            "read_only": IB_READONLY,
            "orders_allowed": ALLOW_ORDERS,
            "market_data_type": MARKET_DATA_TYPE,
            "port": BRIDGE_PORT,
            "supported_pairs": supported_pairs(),
        })
    except Exception as e:
        logger.warning(f"health error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 503


@app.route("/account", methods=["GET"])
@require_bridge_key
def account():
    try:
        worker.ensure_connected()
        values = worker.call(lambda: worker.ib.accountSummaryAsync())
        wanted = {
            "NetLiquidation", "TotalCashValue", "AvailableFunds",
            "BuyingPower", "GrossPositionValue", "MaintMarginReq",
        }
        summary: dict[str, Any] = {}
        currency = None
        for v in values:
            if v.tag in wanted:
                try:
                    summary[v.tag] = float(v.value)
                except (TypeError, ValueError):
                    summary[v.tag] = v.value
                # Les tags monétaires portent tous la même devise de base.
                currency = currency or (v.currency or None)
        return jsonify({
            "ok": True,
            "account": (worker.ib.managedAccounts() or [None])[0],
            "currency": currency,
            **summary,
        })
    except Exception as e:
        logger.warning(f"account error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/positions", methods=["GET"])
@require_bridge_key
def positions():
    try:
        worker.ensure_connected()
        rows = worker.call(lambda: worker.ib.reqPositionsAsync())
        cleaned = [
            {
                "account": p.account,
                "symbol": p.contract.symbol,
                "sec_type": p.contract.secType,
                "currency": p.contract.currency,
                "exchange": p.contract.exchange or p.contract.primaryExchange,
                "position": float(p.position),
                "avg_cost": float(p.avgCost),
            }
            for p in rows
            if float(p.position) != 0.0
        ]
        return jsonify({"ok": True, "count": len(cleaned), "positions": cleaned})
    except Exception as e:
        logger.warning(f"positions error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/tick/<path:pair>", methods=["GET"])
@require_bridge_key
def tick(pair):
    contract = contract_for(pair)
    if contract is None:
        return jsonify({"ok": False, "error": f"unsupported pair {pair}"}), 400
    try:
        worker.ensure_connected()
        qualified = worker.call(lambda: worker.ib.qualifyContractsAsync(contract))
        if not qualified:
            # Cas typique tant que la permission « US Stocks » est en
            # attente : IBKR ne résout pas le contrat.
            return jsonify({
                "ok": False,
                "error": f"contrat non résolu pour {pair} — permission marché manquante ?",
            }), 404
        tickers = worker.call(lambda: worker.ib.reqTickersAsync(qualified[0]))
        if not tickers:
            return jsonify({"ok": False, "error": f"aucun tick pour {pair}"}), 503
        t = tickers[0]

        def _px(x):
            """Normalise un champ prix IB en float positif ou None.

            IB signale « pas de donnée » de trois façons différentes selon le
            champ et le contexte : ``None``, ``NaN``, et surtout **-1** (ou 0
            sur ``last``). Vu le 2026-08-04 sur AAPL hors séance NYSE : bid et
            ask à -1.0 alors que close portait le vrai dernier cours. Laisser
            passer -1 produirait un mid de -1.0 et un SL/TP calculés sur un
            prix négatif.
            """
            if x is None or x != x:  # None ou NaN
                return None
            v = float(x)
            return v if v > 0 else None

        bid, ask, last, close = _px(t.bid), _px(t.ask), _px(t.last), _px(t.close)
        mid = (bid + ask) / 2 if bid is not None and ask is not None else None
        # Ordre de préférence : mid (le plus fiable en séance) → last → close
        # (dernière clôture, seule valeur disponible hors séance).
        price = mid if mid is not None else (last if last is not None else close)
        return jsonify({
            "ok": price is not None,
            "pair": pair.upper(),
            "bid": bid,
            "ask": ask,
            "last": last,
            "close": close,
            "mid": mid,
            "price": price,
            "price_source": (
                "mid" if mid is not None
                else "last" if last is not None
                else "close" if close is not None
                else None
            ),
            "live_quote": mid is not None,
            "market_data_type": MARKET_DATA_TYPE,
            "delayed": MARKET_DATA_TYPE in (3, 4),
        })
    except Exception as e:
        logger.warning(f"tick error {pair}: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/symbols", methods=["GET"])
@require_bridge_key
def symbols():
    pairs = supported_pairs()
    return jsonify({
        "ok": True,
        "count": len(pairs),
        "symbols": pairs,
        "equity": sorted(_EQUITY_SYMBOLS),
        "forex": sorted(_FOREX_PAIRS),
    })


@app.route("/order", methods=["POST"])
@require_bridge_key
def order():
    """Placeholder — refuse tant que IBKR_ALLOW_ORDERS n'est pas activé.

    L'implémentation viendra en Phase 2 avec des bracket orders natifs
    (`ib.bracketOrder`), plus propres que le watcher SL/TP émulé du bridge
    Kraken Spot. Rien n'est branché ici tant que la Voie C n'a pas été
    validée en lecture.
    """
    if not ALLOW_ORDERS:
        return jsonify({
            "ok": False,
            "error": "orders disabled",
            "detail": (
                "Bridge en lecture seule. La session IB est ouverte avec "
                "readonly=True : le Gateway refuserait l'ordre même si ce "
                "garde-fou sautait. Poser IBKR_ALLOW_ORDERS=true et "
                "redémarrer pour activer."
            ),
        }), 403
    return jsonify({
        "ok": False,
        "error": "not implemented",
        "detail": "Envoi d'ordres prévu en Phase 2 (bracket orders natifs IBKR).",
    }), 501


if __name__ == "__main__":
    logger.info(
        f"IBKR bridge démarrage port={BRIDGE_PORT} "
        f"gateway={GATEWAY_HOST}:{GATEWAY_PORT} "
        f"orders_allowed={ALLOW_ORDERS} read_only={IB_READONLY}"
    )
    if ALLOW_ORDERS:
        logger.warning(
            "⚠️ IBKR_ALLOW_ORDERS=true — la session IB n'est PAS en lecture "
            "seule. Sur un compte Live, des ordres réels sont possibles."
        )
    # threaded=False : les handlers Flask délèguent déjà tout au worker,
    # mais on évite d'empiler des requêtes concurrentes sur une socket IB
    # qui ne gère qu'une conversation à la fois.
    app.run(host="127.0.0.1", port=BRIDGE_PORT, threaded=False)
