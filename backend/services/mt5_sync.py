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
    try:
        import json
        if _STATE_PATH.exists():
            return int(json.loads(_STATE_PATH.read_text())["last_id"])
    except Exception:
        pass
    return 0


def _save_last_synced_id(last_id: int) -> None:
    import json
    try:
        _STATE_PATH.write_text(json.dumps({"last_id": last_id}))
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
            "vix_level": snap.vix_level.value,
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

    slippage_pips = None
    if fill_price and entry_price:
        pip = _pip_size(pair)
        # Slippage signe : positif = en faveur du trade, négatif = défavorable.
        if direction == "buy":
            raw = entry_price - fill_price  # on a acheté plus bas = favorable
        else:
            raw = fill_price - entry_price  # on a vendu plus haut = favorable
        if pip:
            slippage_pips = round(raw / pip, 1)

    # Matching signal_id : on cherche un signal recent qui correspond a ce
    # fill (pair + direction + entry a +/-0.1% pres, dans les 30 dernieres
    # minutes). Best-effort : si aucun match, reste NULL.
    signal_id = None
    try:
        from backend.services.backtest_service import find_signal_for_order
        signal_id = find_signal_for_order(pair, direction, float(entry_price or 0))
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, 1, ?, 'OPEN', ?, ?, 1, 1, 1, 1, ?, ?, ?, ?)
        """, (
            user,
            pair,
            direction,
            entry_price,
            row.get("sl") or 0,
            row.get("tp") or 0,
            row.get("lots") or 0.01,
            row.get("risk_money"),
            f"Auto-exec via bridge MT5 (ticket #{ticket}, comment: {row.get('client_comment', '')})",
            row.get("created_at") or datetime.now(timezone.utc).isoformat(),
            ticket,
            ctx_json,
            signal_id,
            fill_price,
            slippage_pips,
        ))


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


async def sync_from_bridge() -> None:
    """Pull incrémental des événements audit du bridge et sync vers personal_trades.

    Appelé périodiquement par le scheduler. No-op si MT5_SYNC_ENABLED=false
    ou si le bridge n'est pas configuré."""
    if not (MT5_SYNC_ENABLED and MT5_BRIDGE_URL and MT5_BRIDGE_API_KEY):
        return

    last_id = _load_last_synced_id()
    url = f"{MT5_BRIDGE_URL.rstrip('/')}/audit"
    headers = {"X-API-Key": MT5_BRIDGE_API_KEY}

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                url,
                headers=headers,
                params={"since_id": last_id, "limit": 100},
            )
        if r.status_code != 200:
            logger.warning(f"mt5_sync: bridge /audit {r.status_code}: {r.text[:200]}")
            return
        orders = r.json().get("orders", [])
    except Exception as e:
        # Bridge joignable est optionnel — PC éteint = no-op silencieux
        logger.debug(f"mt5_sync: bridge unreachable: {e}")
        return

    if not orders:
        return

    user = _resolve_auto_user()
    new_open = 0
    new_closed = 0
    max_id = last_id

    for row in orders:
        rid = row.get("id", 0)
        if rid > max_id:
            max_id = rid
        status = row.get("status")
        mode = row.get("mode")
        # Ne sync que les events LIVE (paper reste local au bridge)
        if mode != "live":
            continue
        if status == "filled":
            _upsert_open_trade(row, user)
            new_open += 1
        elif status == "closed":
            _update_closed_trade(row)
            new_closed += 1

    if new_open or new_closed:
        logger.info(
            f"mt5_sync: {new_open} nouveaux trades auto, {new_closed} fermés "
            f"(user={user}, last_id={max_id})"
        )
    _save_last_synced_id(max_id)
