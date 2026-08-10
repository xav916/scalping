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

from ib_async import IB, Forex, LimitOrder, MarketOrder, Order, StopOrder, Stock

# IBKR encode « valeur non disponible » par DBL_MAX sur les champs numériques
# des OrderState (commission notamment) — cousin du -1 sur les prix. Vu le
# 2026-08-04 : commission = 1.7976931348623157e+308 sur tous les whatIf forex.
_DBL_MAX = 1.7976931348623157e308

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
# Interface d'ecoute. Defaut 127.0.0.1 : un bridge qui ecoute large par defaut
# est un bridge qu'on expose sans l'avoir decide.
#
# Le radar tourne sur l'EC2 et n'atteindrait jamais une boucle locale : la
# machine hote doit donc ouvrir explicitement. Preferer l'IP Tailscale de la
# machine (ex. 100.122.188.8) a 0.0.0.0 — l'ecoute reste alors bornee au
# reseau prive, meme si le pare-feu local venait a tomber.
BRIDGE_HOST = os.getenv("IBKR_BRIDGE_HOST", "127.0.0.1")
ALLOW_ORDERS = os.getenv("IBKR_ALLOW_ORDERS", "false").lower() in ("1", "true", "yes", "on")
MARKET_DATA_TYPE = int(os.getenv("IBKR_MARKET_DATA_TYPE", "3"))

# readonly=True demande au Gateway de refuser tout ordre au niveau session.
# C'est la garde-fou n°2 : elle survit à un bug applicatif côté bridge.
IB_READONLY = not ALLOW_ORDERS

REQUEST_TIMEOUT_SEC = 45.0
# Attente du fill après envoi réel, pour remonter la commission.
FILL_WAIT_SEC = float(os.getenv("IBKR_FILL_WAIT_SEC", "20"))

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

    def call_sync(self, fn) -> Any:
        """Comme ``call``, pour les méthodes **synchrones** d'``ib_async``.

        ``placeOrder`` et ``client.getReqId()`` ne sont pas des coroutines,
        mais touchent la socket et l'état interne d'``ib_async`` : les
        appeler depuis un thread Flask corromprait la séquence d'orderId.
        On les fait donc exécuter par le thread propriétaire de la loop.
        """

        async def _invoke():
            return fn()

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


def _num(x):
    """Normalise un champ numérique d'OrderState, en filtrant la sentinelle."""
    if x is None or x == "":
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return x
    return None if v >= _DBL_MAX else v


def _build_bracket(direction: str, qty: float, sl: float, tp: float,
                   parent_id: int, entry_limit: float | None = None) -> list[Order]:
    """Entrée + SL stop + TP limite, liés par ``parentId``.

    L'entrée est au marché par défaut. ``entry_limit`` la passe en ordre
    limite — utile pour **valider la mécanique sans payer** : une limite
    placée loin du marché ne se remplit pas, donc ne génère aucune
    commission, tout en permettant de vérifier que la grappe est acceptée et
    correctement liée.

    ``ib.bracketOrder()`` impose une entrée LIMIT ; on veut les deux modes,
    donc on assemble à la main. Seul le dernier ordre porte ``transmit=True``
    : IBKR ne libère la grappe qu'à ce moment, ce qui évite qu'un parent
    parte seul si la construction échoue en cours de route (le piège des
    positions nues déjà vécu côté MT5).

    ``tif`` est fixé explicitement sur les trois ordres. Sans ça, IBKR
    applique un preset et émet l'avertissement 10349 — qui **avale la
    réponse whatIf** et fait échouer silencieusement tout le dry-run.
    """
    entry_action = "BUY" if direction.lower() == "buy" else "SELL"
    exit_action = "SELL" if entry_action == "BUY" else "BUY"

    if entry_limit is not None:
        parent = LimitOrder(entry_action, qty, float(entry_limit))
    else:
        parent = MarketOrder(entry_action, qty)
    parent.orderId = parent_id
    parent.tif = "DAY"
    parent.transmit = False

    take_profit = LimitOrder(exit_action, qty, tp)
    take_profit.orderId = parent_id + 1
    take_profit.parentId = parent_id
    take_profit.tif = "GTC"
    take_profit.transmit = False

    stop_loss = StopOrder(exit_action, qty, sl)
    stop_loss.orderId = parent_id + 2
    stop_loss.parentId = parent_id
    stop_loss.tif = "GTC"
    stop_loss.transmit = True  # libère la grappe entière

    return [parent, take_profit, stop_loss]


@app.route("/order", methods=["POST"])
@require_bridge_key
def order():
    """Passe un ordre bracket, ou le simule.

    Payload : ``{pair, direction, qty, sl, tp, dry_run}``.

    ``dry_run`` vaut **true par défaut**. En dry-run on interroge le
    pré-contrôle natif d'IBKR (``whatIfOrder``) : il renvoie l'impact marge
    et refuse si l'ordre est irrecevable, **sans rien placer**. C'est le
    substitut au paper account, indisponible sur ce compte tant que les
    Actions US ne sont pas approuvées.

    Le dry-run fonctionne en session ``readonly=True`` — vérifié le
    2026-08-04. La garantie forte du Gateway n'a donc pas à être levée pour
    simuler.
    """
    payload = request.get_json(silent=True) or {}
    pair = payload.get("pair")
    direction = (payload.get("direction") or "").lower()
    qty = payload.get("qty")
    sl = payload.get("sl")
    tp = payload.get("tp")
    dry_run = payload.get("dry_run", True)

    if not pair or direction not in ("buy", "sell") or not qty:
        return jsonify({
            "ok": False,
            "error": "payload requires pair, direction (buy/sell), qty",
        }), 400

    contract = contract_for(pair)
    if contract is None:
        return jsonify({"ok": False, "error": f"unsupported pair {pair}"}), 400

    if not dry_run and not ALLOW_ORDERS:
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

    try:
        worker.ensure_connected()
        qualified = worker.call(lambda: worker.ib.qualifyContractsAsync(contract))
        if not qualified:
            return jsonify({
                "ok": False,
                "error": f"contrat non résolu pour {pair} — permission marché manquante ?",
            }), 404
        c = qualified[0]

        # ─── Dry-run : pré-contrôle IBKR, rien n'est placé ──────────────
        if dry_run:
            probe = MarketOrder("BUY" if direction == "buy" else "SELL", qty)
            probe.tif = "DAY"
            state = worker.call(lambda: worker.ib.whatIfOrderAsync(c, probe))
            # whatIfOrderAsync rend une liste vide quand IBKR ne répond pas
            # (ordre irrecevable, ou avertissement ayant avalé la réponse).
            if isinstance(state, list) or state is None:
                return jsonify({
                    "ok": False,
                    "dry_run": True,
                    "error": "IBKR n'a pas répondu au pré-contrôle",
                    "detail": (
                        "Ordre probablement irrecevable : permission de marché "
                        "manquante, taille invalide, ou marché fermé."
                    ),
                }), 422
            init_margin = _num(state.initMarginChange)

            # IBKR rapporte la marge sans juger si le compte peut la couvrir :
            # un whatIf à 25 000 EUR/USD renvoie 752.95 de marge sur un compte
            # de 100 € sans le moindre avertissement. C'est au bridge de
            # trancher, sinon un ordre voué au rejet partirait quand même.
            available = None
            affordable = None
            try:
                values = worker.call(lambda: worker.ib.accountSummaryAsync())
                for v in values:
                    if v.tag == "AvailableFunds":
                        available = float(v.value)
                        break
                if available is not None and init_margin is not None:
                    affordable = init_margin <= available
            except Exception as e:
                logger.debug(f"available funds lookup: {e}")

            return jsonify({
                "ok": True,
                "dry_run": True,
                "placed": False,
                "pair": pair.upper(),
                "direction": direction,
                "qty": qty,
                "init_margin": init_margin,
                "maint_margin": _num(state.maintMarginChange),
                "equity_after": _num(state.equityWithLoanChange),
                "commission": _num(state.commission),
                "commission_currency": state.commissionCurrency or None,
                "available_funds": available,
                "affordable": affordable,
                "warning": state.warningText or None,
            })

        # ─── Envoi réel ─────────────────────────────────────────────────
        if sl is None or tp is None:
            return jsonify({
                "ok": False,
                "error": "sl et tp obligatoires en envoi réel",
                "detail": "Aucune position ne part sans stop — cf. incident MT5 positions nues.",
            }), 400

        base_id = worker.call_sync(lambda: worker.ib.client.getReqId())
        orders = _build_bracket(
            direction, qty, float(sl), float(tp), base_id,
            entry_limit=payload.get("entry_limit"),
        )
        trades = worker.call_sync(
            lambda: [worker.ib.placeOrder(c, o) for o in orders]
        )
        parent_trade = trades[0]

        # Attendre le fill du parent pour remonter prix moyen et commission.
        # whatIf ne donne jamais la commission (DBL_MAX) : le fill est la
        # seule source. Sans ça, impossible de juger si le coût par ordre
        # rend l'opération viable au capital courant.
        async def _await_fill():
            for _ in range(int(FILL_WAIT_SEC * 2)):
                if parent_trade.orderStatus.status in (
                    "Filled", "Cancelled", "ApiCancelled", "Inactive"
                ):
                    break
                await asyncio.sleep(0.5)
            return parent_trade.orderStatus.status

        status = worker.call(_await_fill)

        commission = None
        commission_ccy = None
        realized_pnl = None
        avg_price = _num(parent_trade.orderStatus.avgFillPrice)
        for fill in parent_trade.fills:
            report = getattr(fill, "commissionReport", None)
            if report and report.commission is not None:
                commission = (commission or 0.0) + _num(report.commission or 0)
                commission_ccy = report.currency or commission_ccy
                if report.realizedPNL is not None:
                    realized_pnl = _num(report.realizedPNL)

        return jsonify({
            "ok": True,
            "dry_run": False,
            "placed": True,
            "pair": pair.upper(),
            "direction": direction,
            "qty": qty,
            "sl": sl,
            "tp": tp,
            "status": status,
            "avg_fill_price": avg_price,
            "commission": commission,
            "commission_currency": commission_ccy,
            "realized_pnl": realized_pnl,
            "orders": [
                {"order_id": t.order.orderId, "type": t.order.orderType,
                 "status": t.orderStatus.status}
                for t in trades
            ],
        })
    except Exception as e:
        logger.warning(f"order error {pair}: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/kill", methods=["POST"])
@require_bridge_key
def kill():
    """Arrêt d'urgence : annule tous les ordres et solde toutes les positions.

    Contrepartie indispensable de ``/order``. Ouvrir une position sans moyen
    programmatique de la refermer, c'est le scénario des positions nues déjà
    vécu côté MT5 ([[project_incident_bridge_no_sltp_2026_06_14]]).

    Ordre des opérations : annuler d'abord, solder ensuite. L'inverse ferait
    déclencher les brackets encore actifs sur la position en cours de
    fermeture, ce qui ouvrirait une position inverse.
    """
    if not ALLOW_ORDERS:
        return jsonify({
            "ok": False,
            "error": "orders disabled",
            "detail": "Bridge en lecture seule — rien à annuler ni à solder.",
        }), 403
    try:
        worker.ensure_connected()

        cancelled = worker.call_sync(lambda: [
            (worker.ib.cancelOrder(t.order), t.order.orderId)[1]
            for t in worker.ib.openTrades()
        ])

        positions = worker.call(lambda: worker.ib.reqPositionsAsync())
        closed = []
        for p in positions:
            size = float(p.position)
            if size == 0:
                continue
            action = "SELL" if size > 0 else "BUY"
            closing = MarketOrder(action, abs(size))
            closing.tif = "DAY"  # sinon avertissement 10349, cf. /order
            trade = worker.call_sync(
                lambda c=p.contract, o=closing: worker.ib.placeOrder(c, o)
            )
            closed.append({
                "symbol": p.contract.symbol,
                "was": size,
                "action": action,
                "order_id": trade.order.orderId,
            })

        logger.warning(f"KILL — {len(cancelled)} ordres annulés, {len(closed)} positions soldées")
        return jsonify({
            "ok": True,
            "cancelled_orders": cancelled,
            "closed_positions": closed,
        })
    except Exception as e:
        logger.warning(f"kill error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    logger.info(
        f"IBKR bridge démarrage {BRIDGE_HOST}:{BRIDGE_PORT} "
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
    app.run(host=BRIDGE_HOST, port=BRIDGE_PORT, threaded=False)
