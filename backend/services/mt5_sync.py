"""Synchronisation bridge MT5 → table personal_trades.

Pull périodique depuis le bridge (/audit?since_id=...) pour :
- Détecter les ordres LIVE fills → INSERT dans personal_trades (status=OPEN)
- Détecter les fermetures (status='closed' dans le bridge) → UPDATE du
  personal_trade correspondant (exit_price, pnl, closed_at, status=CLOSED)

Conséquence : tout ordre auto placé par le bridge apparaît dans les sections
Mes trades / Risque / Equity / Détecteur d'erreurs du dashboard — même si
l'utilisateur n'a jamais cliqué sur "J'ai pris ce signal".

Schéma de dédup : `mt5_ticket` dans personal_trades est unique par trade.
Si la sync rejoue (crash, re-pull), les INSERT sont UPSERT (pas de doublons).
"""

import asyncio
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from backend.services import macro_context_service

from config.settings import (
    AUTH_USERS,
    AUTO_TRADE_USER,
    MT5_BRIDGE_API_KEY,
    MT5_BRIDGE_URL,
    MT5_SYNC_ENABLED,
)

logger = logging.getLogger(__name__)

# Persisté sur disque pour survivre au restart du backend
_STATE_PATH = Path("/app/data/mt5_sync_state.json") if Path("/app").exists() else Path("mt5_sync_state.json")
_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_last_synced_id() -> int:
    """Compat legacy : retourne last_id du bridge admin_legacy uniquement."""
    return _load_state().get("bridges", {}).get("legacy", 0)


def _save_last_synced_id(last_id: int) -> None:
    """Compat legacy : écrit last_id pour admin_legacy uniquement."""
    state = _load_state()
    state.setdefault("bridges", {})["legacy"] = int(last_id)
    _save_state(state)


def _load_state() -> dict:
    """Charge l'état multi-bridge {bridges: {<name>: last_id}}.

    Migre transparent l'ancien format {'last_id': N} → {'bridges': {'legacy': N}}.
    """
    try:
        if _STATE_PATH.exists():
            data = json.loads(_STATE_PATH.read_text())
            if isinstance(data, dict):
                if "bridges" not in data and "last_id" in data:
                    return {"bridges": {"legacy": int(data["last_id"])}}
                return data
    except Exception:
        pass
    return {"bridges": {}}


def _save_state(state: dict) -> None:
    try:
        _STATE_PATH.write_text(json.dumps(state))
    except Exception as e:
        logger.warning(f"mt5_sync: write state failed: {e}")


def _resolve_auto_user() -> str:
    """Retourne l'user auquel attribuer les trades auto.

    - AUTO_TRADE_USER si défini
    - sinon le 1er user de AUTH_USERS
    - sinon 'anonymous' (auth désactivée)
    """
    if AUTO_TRADE_USER:
        return AUTO_TRADE_USER
    if AUTH_USERS:
        return next(iter(AUTH_USERS.keys()))
    return "anonymous"


def _db_path():
    from backend.services.trade_log_service import _DB_PATH
    return _DB_PATH


def _pip_size(pair: str) -> float:
    """Approx cohérente avec le reste du code (XAU/XAG = 0.01, JPY = 0.01,
    forex standard = 0.0001). Utilisé uniquement pour afficher le slippage."""
    base = pair.split("/")[0].upper() if "/" in pair else pair.upper()
    quote = pair.split("/")[1].upper() if "/" in pair else ""
    if base in {"XAU", "XAG", "XPT", "XPD"}:
        return 0.01
    if quote == "JPY":
        return 0.01
    return 0.0001


def _upsert_open_trade(row: dict[str, Any], user: str) -> None:
    """INSERT un ordre auto comme personal_trade. Silencieusement ignoré si
    le mt5_ticket existe déjà (dedup rejouable)."""
    ticket = row.get("ticket")
    if not ticket:
        return

    ctx_json = None
    snap = macro_context_service.get_macro_snapshot()
    if snap is not None and macro_context_service.is_fresh(snap.fetched_at):
        ctx_json = json.dumps({
            "dxy": snap.dxy_direction.value,
            "spx": snap.spx_direction.value,
            "vix_level": snap.vix_level.value if snap.vix_level is not None else None,
            "vix_value": snap.vix_value,
            "risk_regime": snap.risk_regime.value,
            "fetched_at": snap.fetched_at.isoformat(),
        })

    # Prix planifié (entry) vs prix réellement exécuté (fill). Le bridge
    # peut remonter plusieurs conventions selon sa version — on regarde
    # les noms habituels.
    pair = row.get("pair") or row.get("symbol") or "?"
    direction = (row.get("direction") or "").lower()
    entry_price = row.get("entry") or 0
    fill_price = (
        row.get("fill_price")
        or row.get("price_open")
        or row.get("open_price")
    )

    # Référence du glissement : le prix DEMANDÉ, jamais `entry`.
    #
    # ⚠️ Le bridge écrit le prix OBTENU dans sa colonne `entry` (le planifié y
    # était écrasé). Comparer `entry` au fill revient donc à comparer le fill à
    # lui-même — c'est ce qui laissait `slippage_pips` vide sur 1581/1581
    # trades avant le 2026-08-06. `entry_requested` porte le prix demandé.
    planned_price = row.get("entry_requested")

    # `requested` = le bridge n'a pas pu observer le fill et s'est replié sur
    # le prix demandé. Le glissement vaudrait alors zéro PAR CONSTRUCTION.
    # Mieux vaut ne rien mesurer que d'injecter de faux zéros qui tireraient la
    # moyenne vers l'absence de coût. Absent (ancien bridge) ⇒ pas de
    # `entry_requested` non plus, donc pas de calcul : rétrocompatible.
    fill_source = row.get("fill_source")

    slippage_pips = None
    if fill_price and planned_price and fill_source != "requested":
        pip = _pip_size(pair)
        # Slippage signé : positif = en faveur du trade, négatif = défavorable.
        if direction == "buy":
            raw = planned_price - fill_price  # acheté plus bas = favorable
        else:
            raw = fill_price - planned_price  # vendu plus haut = favorable
        if pip:
            slippage_pips = round(raw / pip, 1)

    # Matching signal_id : on cherche un signal recent qui correspond a ce
    # fill (pair + direction + entry a +/-0.1% pres, dans les 30 dernieres
    # minutes). Best-effort : si aucun match, reste NULL.
    signal_id = None
    signal_pattern = None
    try:
        from backend.services.backtest_service import find_signal_for_order, _DB_PATH as _SIGNALS_DB
        signal_id = find_signal_for_order(pair, direction, float(entry_price or 0))
        # Récupère le pattern du signal matché pour le persister sur le trade.
        # Permet au diagnostic de ventiler les trades par pattern gagnant/perdant
        # (avant ce fix, signal_pattern était hardcodé NULL → diag aveugle).
        if signal_id:
            try:
                with sqlite3.connect(str(_SIGNALS_DB)) as sc:
                    r = sc.execute(
                        "SELECT pattern FROM signals WHERE id = ?", (signal_id,)
                    ).fetchone()
                    if r and r[0]:
                        signal_pattern = r[0]
            except Exception as e:
                logger.debug(f"mt5_sync: lookup pattern for signal_id={signal_id} failed: {e}")
    except Exception as e:
        logger.debug(f"mt5_sync: find_signal_for_order failed: {e}")

    with sqlite3.connect(_db_path()) as c:
        c.execute("""
            INSERT OR IGNORE INTO personal_trades (
                user, pair, direction, entry_price, stop_loss, take_profit,
                size_lot, signal_pattern, signal_confidence, checklist_passed,
                notes, status, created_at, mt5_ticket, is_auto,
                post_entry_sl, post_entry_tp, post_entry_size, context_macro,
                signal_id, fill_price, slippage_pips
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 'OPEN', ?, ?, 1, 1, 1, 1, ?, ?, ?, ?)
        """, (
            user,
            pair,
            direction,
            entry_price,
            row.get("sl") or 0,
            row.get("tp") or 0,
            row.get("lots") or 0.01,
            # signal_pattern = récupéré depuis signals via signal_id matché
            # (NULL si aucun match, ex: trade manuel ou signal_id introuvable).
            signal_pattern,
            # signal_confidence = score de confidence envoyé par le radar au moment du /order
            # (bridge a une colonne audit dédiée depuis 2026-04-21 pour capturer la valeur).
            # Les anciens trades auto ont NULL ici car bridge ne la persistait pas.
            row.get("confidence"),
            f"Auto-exec via bridge MT5 (ticket #{ticket}, risk_money={row.get('risk_money')}, comment: {row.get('client_comment', '')})",
            row.get("created_at") or datetime.now(timezone.utc).isoformat(),
            ticket,
            ctx_json,
            signal_id,
            fill_price,
            slippage_pips,
        ))


def _derive_close_reason_from_exit(
    ticket: int, exit_price: float | None
) -> str | None:
    """Heuristique : le bridge ne remonte pas `close_reason` dans /deals.
    On compare `exit_price` aux SL/TP stockés en DB :
    - exit ≈ SL → SL
    - exit ≈ TP1 → TP1
    - exit ≈ TP2 (si présent) → TP2
    - sinon → MANUAL

    Tolérance par asset class pour absorber le slippage (~2 pips forex,
    0.3$ sur XAU, etc.).
    """
    if exit_price is None:
        return None
    with sqlite3.connect(_db_path()) as c:
        row = c.execute(
            """
            SELECT stop_loss, take_profit, pair
              FROM personal_trades
             WHERE mt5_ticket = ?
            """,
            (ticket,),
        ).fetchone()
    if not row:
        return None
    sl, tp, pair = row
    if sl is None and tp is None:
        return None

    base = pair.split("/")[0].upper() if pair and "/" in pair else (pair or "").upper()
    # Tolérances de fermeture (en unités de prix) — couvrent le slippage
    # broker et les approximations de rounding côté MT5.
    if base == "XAU":
        tol = 0.3   # ~3 pips or
    elif base == "XAG":
        tol = 0.02
    elif base in {"BTC", "ETH"}:
        tol = 15.0
    elif base in {"BCH", "LTC"}:
        # 2026-06-29 — fix observabilite altcoins range 100-500 USD.
        # Sans cette branche, fallback tol=0.0002 (forex) -> 100% MANUAL
        # sur l'analyse historique. Cf. audit BCH 209/217 = MANUAL alors
        # qu'il s'agissait majoritairement de SL touches au sizing minimum.
        tol = 5.0
    elif base in {"DOT", "ADA", "XRP", "SOL"}:
        # Idem pour altcoins petite cap (range 0.5-5 USD).
        tol = 0.05
    elif base in {"SPX", "NDX"}:
        tol = 2.0
    elif base == "WTI":
        tol = 0.05
    else:
        tol = 0.0002  # 2 pips sur 5-dp forex

    if sl is not None and abs(exit_price - sl) <= tol:
        return "SL"
    if tp is not None and abs(exit_price - tp) <= tol:
        return "TP1"
    return "MANUAL"


def _normalize_close_reason(raw: str | None) -> str | None:
    """Le bridge peut remonter des libelles variables selon la version MT5
    (deal.reason, position.close_reason, etc.). On normalise en un set
    reduit et stable pour l'analyse ML downstream."""
    if not raw:
        return None
    r = str(raw).strip().lower()
    if "tp2" in r or "take_profit_2" in r:
        return "TP2"
    if "tp" in r or "take_profit" in r:
        return "TP1"
    if "sl" in r or "stop" in r:
        return "SL"
    if "manual" in r or "client" in r:
        return "MANUAL"
    if "timeout" in r or "expiry" in r:
        return "TIMEOUT"
    return raw.upper()[:16]


def _update_closed_trade(row: dict[str, Any]) -> None:
    """Quand le bridge log une fermeture (status='closed'), met à jour la
    ligne personal_trades correspondante (par mt5_ticket).

    Idempotent : on accepte aussi d'enrichir une ligne déjà CLOSED tant que
    les nouvelles colonnes (exit_price, pnl) sont non-null. Utile quand le
    status a été forcé manuellement avant que le sync ait remonté les valeurs
    finales du broker. closed_at est protégé par COALESCE pour ne pas écraser
    une date de fermeture déjà enregistrée."""
    ticket = row.get("ticket")
    if not ticket:
        return
    close_reason = _normalize_close_reason(
        row.get("close_reason") or row.get("reason") or row.get("deal_reason")
    )
    # Fallback : bridge `/deals` ne remonte pas le reason → heuristique
    # par proximité de l'exit price aux SL/TP stockés en DB.
    if not close_reason:
        close_reason = _derive_close_reason_from_exit(ticket, row.get("exit_price"))
    with sqlite3.connect(_db_path()) as c:
        c.execute("""
            UPDATE personal_trades
               SET status       = 'CLOSED',
                   exit_price   = COALESCE(?, exit_price),
                   pnl          = COALESCE(?, pnl),
                   closed_at    = COALESCE(closed_at, ?),
                   close_reason = COALESCE(close_reason, ?)
             WHERE mt5_ticket = ?
        """, (
            row.get("exit_price"),
            row.get("pnl"),
            row.get("created_at") or datetime.now(timezone.utc).isoformat(),
            close_reason,
            ticket,
        ))


def _fetch_closed_trade_for_notify(ticket: int) -> dict[str, Any] | None:
    """Charge la ligne personal_trades complète pour préparer une notif
    Telegram de fermeture. Retourne None si introuvable."""
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT pair, direction, entry_price, exit_price, pnl, "
            "close_reason, signal_pattern, signal_confidence, mt5_ticket, "
            "created_at, closed_at, size_lot FROM personal_trades WHERE mt5_ticket=?",
            (ticket,),
        ).fetchone()
    return dict(row) if row else None


async def _notify_close_telegram(ticket: int) -> None:
    """Envoie la notif Telegram pédagogique de fermeture pour ce ticket.

    Best-effort : tout échec est loggé, jamais propagé (ne doit pas
    casser la réconciliation).
    """
    try:
        trade = _fetch_closed_trade_for_notify(ticket)
        if not trade:
            return
        from backend.services.telegram_service import send_close
        await send_close(trade)
    except Exception as e:
        logger.warning(f"mt5_sync: notify_close_telegram ticket={ticket} failed: {e}")


def _select_open_auto_tickets() -> set[int]:
    """Tickets **MT5** des personal_trades auto encore OPEN.

    ⚠️ Les identifiants non MT5 sont ecartes, et ce n'est pas defensif : ces
    tickets servent a interroger le ``/positions`` du bridge **MT5**. Un ordre
    Kraken y est etranger — il a sa propre reconciliation, toutes les 2 min.

    Incident du 2026-08-09. Le premier trade de l'univers Kraken elargi
    (ETHFI, 08-08 a 23:58) a ete materialise dans ``personal_trades`` avec un
    UUID pour ``mt5_ticket``. Le ``int()`` qui suivait levait, et comme
    ``_reconcile_open_trades`` est le DERNIER appel de ``sync_from_bridge``,
    la reconciliation des cloturees naturelles MT5 est morte pendant dix
    heures : 59 echecs par heure, zero succes, avec une position or ouverte.

    ``mt5_ticket`` est declare ``INTEGER``, mais SQLite est type
    dynamiquement : la colonne a accepte le texte sans broncher. Le filtre
    porte donc sur la FORME de la valeur, pas sur son type de stockage — un
    ticket MT5 arrive parfois en TEXT et doit rester lu.
    """
    with sqlite3.connect(_db_path()) as c:
        rows = c.execute(
            "SELECT mt5_ticket FROM personal_trades "
            "WHERE status='OPEN' AND is_auto=1 AND mt5_ticket IS NOT NULL"
        ).fetchall()
    tickets: set[int] = set()
    ecartes = 0
    for (valeur,) in rows:
        try:
            tickets.add(int(valeur))
        except (TypeError, ValueError):
            ecartes += 1
    if ecartes:
        # Journalise : ecarter en silence rejouerait le defaut sous une autre
        # forme — on saurait que la reconciliation ne trouve rien, jamais
        # pourquoi.
        logger.debug(
            "mt5_sync: %d ticket(s) non MT5 ecarte(s) de la reconciliation "
            "(identifiants d'une autre destination), %d conserve(s)",
            ecartes, len(tickets),
        )
    return tickets


def _mark_ticket_closed_no_deal(ticket: int) -> None:
    """Fallback quand le deal MT5 est introuvable (history purgée) :
    status=CLOSED seul, sans exit_price ni pnl. closed_at est protégé
    par COALESCE pour préserver une date déjà enregistrée."""
    with sqlite3.connect(_db_path()) as c:
        c.execute(
            "UPDATE personal_trades "
            "SET status='CLOSED', closed_at=COALESCE(closed_at, ?) "
            "WHERE mt5_ticket=?",
            (datetime.now(timezone.utc).isoformat(), ticket),
        )


async def _reconcile_open_trades() -> None:
    """Compare les tickets DB OPEN vs /positions du bridge et réconcilie
    les fermetures naturelles (SL/TP touchés par le marché).

    Appelé à la fin de sync_from_bridge. No-op si bridge non configuré
    ou s'il n'y a aucun ticket OPEN en DB."""
    if not (MT5_SYNC_ENABLED and MT5_BRIDGE_URL and MT5_BRIDGE_API_KEY):
        return

    open_tickets = _select_open_auto_tickets()
    if not open_tickets:
        return

    base = MT5_BRIDGE_URL.rstrip("/")
    headers = {"X-API-Key": MT5_BRIDGE_API_KEY}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{base}/positions", headers=headers)
            if r.status_code != 200:
                logger.warning(f"mt5_sync: /positions {r.status_code}")
                return
            positions = r.json().get("positions", []) or []
            live_tickets = {int(p["ticket"]) for p in positions if "ticket" in p}
    except Exception as e:
        logger.debug(f"mt5_sync: /positions unreachable: {e}")
        return

    closed_tickets = open_tickets - live_tickets
    if not closed_tickets:
        return

    n_full = 0
    n_partial = 0
    for ticket in closed_tickets:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(
                    f"{base}/deals", headers=headers,
                    params={"ticket": ticket},
                )
                if r.status_code != 200:
                    continue
                data = r.json()
        except Exception as e:
            logger.debug(f"mt5_sync: /deals ticket={ticket} failed: {e}")
            continue

        if data.get("closed") is True:
            _update_closed_trade({
                "ticket": ticket,
                "exit_price": data.get("exit_price"),
                "pnl": data.get("pnl"),
                "created_at": data.get("closed_at"),
            })
            n_full += 1
            await _notify_close_telegram(int(ticket))
        elif data.get("closed") is None:
            logger.warning(
                f"mt5_sync: ticket {ticket} history introuvable, status=CLOSED sans pnl"
            )
            _mark_ticket_closed_no_deal(ticket)
            n_partial += 1
            await _notify_close_telegram(int(ticket))

    if n_full or n_partial:
        logger.info(
            f"mt5_sync: {n_full} closures reconciled (full), {n_partial} partial"
        )


async def _sync_one(name: str, base_url: str, api_key: str) -> tuple[int, int]:
    """Pull /audit d'un bridge MT5 + applique à personal_trades. Retourne (n_open, n_closed).

    Le bridge non-joignable est silencieux (PC éteint, VPS down — no-op).
    """
    state = _load_state()
    last_id = int(state.get("bridges", {}).get(name, 0))
    url = f"{base_url.rstrip('/')}/audit"
    headers = {"X-API-Key": api_key} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                url, headers=headers,
                params={"since_id": last_id, "limit": 100},
            )
        if r.status_code != 200:
            logger.warning(f"mt5_sync[{name}]: /audit {r.status_code}: {r.text[:200]}")
            return (0, 0)
        orders = r.json().get("orders", [])
    except Exception as e:
        logger.debug(f"mt5_sync[{name}]: unreachable: {e}")
        return (0, 0)

    if not orders:
        return (0, 0)

    user = _resolve_auto_user()
    new_open = 0
    new_closed = 0
    max_id = last_id
    for row in orders:
        rid = row.get("id", 0)
        if rid > max_id:
            max_id = rid
        if row.get("mode") != "live":
            continue
        status = row.get("status")
        if status == "filled":
            _upsert_open_trade(row, user)
            new_open += 1
        elif status == "closed":
            _update_closed_trade(row)
            new_closed += 1
            ticket = row.get("ticket")
            if ticket:
                await _notify_close_telegram(int(ticket))

    state.setdefault("bridges", {})[name] = max_id
    _save_state(state)
    if new_open or new_closed:
        logger.info(
            f"mt5_sync[{name}]: {new_open} nouveaux open, {new_closed} closed "
            f"(user={user}, last_id={max_id})"
        )
    return (new_open, new_closed)


async def sync_from_bridge() -> None:
    """Pull incrémental des événements audit des bridges MT5 configurés.

    Itère sur :
    - legacy : MT5_BRIDGE_URL + MT5_BRIDGE_API_KEY (Pepperstone Demo)
    - live   : MT5_BRIDGE_LIVE_URL + MT5_BRIDGE_LIVE_API_KEY (IC Markets Live)

    Chaque bridge a son propre last_id dans state['bridges'][name]. Un bridge
    injoignable est silencieux (no-op pour ce cycle).
    """
    if not MT5_SYNC_ENABLED:
        return

    if MT5_BRIDGE_URL and MT5_BRIDGE_API_KEY:
        await _sync_one("legacy", MT5_BRIDGE_URL, MT5_BRIDGE_API_KEY)

    live_url = os.getenv("MT5_BRIDGE_LIVE_URL", "")
    live_key = os.getenv("MT5_BRIDGE_LIVE_API_KEY", "")
    if live_url and live_key:
        await _sync_one("live", live_url, live_key)

    await _reconcile_open_trades()
