"""Service de tracking des trades fermés EA multi-tenant.

Stocke les trades fermés remontés par l'EA des users Premium (≥ v1.04).
Source de vérité pour le PnL réel par user, utilisée par pair_pnl_regulator
pour évaluer la santé d'un pair multi-tenant.

Pour Xavier admin, la source historique reste personal_trades (legacy).
Pour Cédric et futurs Premium, la source = cette table.

L'EA appelle POST /api/ea/closed-trade dans OnTradeTransaction quand un
deal de type OUT (= fermeture de position) avec magic=InpMagicNumber est
détecté. Ça inclut les fermetures par SL, TP, manuel via MT5, etc.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SCHEMA_ENSURED = False


def _db_path() -> str:
    from backend.services.trade_log_service import _DB_PATH
    return str(_DB_PATH)


def _ensure_schema() -> None:
    """Crée la table ea_closed_trades si pas déjà là. Idempotent."""
    global _SCHEMA_ENSURED
    if _SCHEMA_ENSURED:
        return
    with sqlite3.connect(_db_path()) as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS ea_closed_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                pair TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                pnl REAL NOT NULL,
                volume REAL,
                mt5_ticket INTEGER,
                mt5_deal_id INTEGER,
                magic INTEGER,
                opened_at TEXT,
                closed_at TEXT NOT NULL,
                reported_at TEXT NOT NULL,
                close_reason TEXT
            )
            """
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_eact_user_pair_closed ON ea_closed_trades(user_id, pair, closed_at DESC)"
        )
        c.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_eact_dedup ON ea_closed_trades(user_id, mt5_deal_id) WHERE mt5_deal_id IS NOT NULL"
        )
    _SCHEMA_ENSURED = True


def normalize_pair(broker_symbol: str, user_id: int, mt5_ticket: Optional[int] = None) -> str:
    """Convertit le symbole broker (USOIL, EURUSD, SPX500) en pair SaaS
    (WTI/USD, EUR/USD, SPX).

    1. Lookup ``mt5_pending_orders`` par ``mt5_ticket`` → récupère pair du payload
    2. Sinon heuristique sur le nom du symbole (oil, gold, silver, btc, eth,
       indices US, forex 6-char)
    3. Sinon retourne brut (unmappable, l'admin verra le brut dans la table)
    """
    # 1. JOIN avec mt5_pending_orders
    if mt5_ticket:
        try:
            import json
            with sqlite3.connect(_db_path()) as c:
                row = c.execute(
                    "SELECT payload FROM mt5_pending_orders WHERE user_id = ? AND mt5_ticket = ?",
                    (user_id, int(mt5_ticket)),
                ).fetchone()
                if row and row[0]:
                    p = json.loads(row[0])
                    if p.get("pair"):
                        return p["pair"]
        except Exception as e:
            logger.debug(f"ea_closed_trades: pair lookup via mt5_pending_orders failed: {e}")
    # 2. Heuristique sur le nom du symbole
    s = (broker_symbol or "").upper().strip()
    if not s:
        return broker_symbol
    if "OIL" in s or s in ("WTI", "WTIUSD", "XTIUSD"):
        return "WTI/USD"
    if "GOLD" in s or s.startswith("XAU"):
        return "XAU/USD"
    if "SILVER" in s or s.startswith("XAG"):
        return "XAG/USD"
    if s.startswith("BTC"):
        return "BTC/USD"
    if s.startswith("ETH"):
        return "ETH/USD"
    if s in ("US500", "SPX500", "SP500"):
        return "SPX"
    if s in ("NAS100", "US100", "USTECH100", "NDX100"):
        return "NDX"
    # 3. Forex : 6 chars sans slash → insère /
    if len(s) == 6 and s.isalpha():
        return s[:3] + "/" + s[3:]
    # 4. Forex avec suffixe broker (EURUSDm chez IC Markets, etc.) : retire le suffixe
    if len(s) >= 7 and s[:6].isalpha():
        return s[:3] + "/" + s[3:6]
    return broker_symbol  # unmappable, à investiguer manuellement


def record(
    *,
    user_id: int,
    pair: str,
    direction: str,
    entry_price: float,
    exit_price: float,
    pnl: float,
    volume: Optional[float] = None,
    mt5_ticket: Optional[int] = None,
    mt5_deal_id: Optional[int] = None,
    magic: Optional[int] = None,
    opened_at: Optional[str] = None,
    closed_at: Optional[str] = None,
    close_reason: Optional[str] = None,
) -> Optional[int]:
    """Persiste un trade fermé. Retourne l'id inséré, ou None si dédup hit.

    Dédup par (user_id, mt5_deal_id) — l'EA peut re-poster suite à un retry
    réseau, on ignore silencieusement le doublon.
    """
    _ensure_schema()
    if not closed_at:
        closed_at = datetime.now(timezone.utc).isoformat()
    reported_at = datetime.now(timezone.utc).isoformat()

    # Normalise pair : si l'EA envoie le symbole broker brut (USOIL, EURUSD),
    # on convertit en pair SaaS (WTI/USD, EUR/USD). Si déjà au format SaaS
    # avec "/", la heuristique le détecte et ne le modifie pas.
    if pair and "/" not in pair:
        pair = normalize_pair(pair, user_id, mt5_ticket)

    try:
        with sqlite3.connect(_db_path()) as c:
            cur = c.execute(
                """
                INSERT INTO ea_closed_trades
                    (user_id, pair, direction, entry_price, exit_price, pnl,
                     volume, mt5_ticket, mt5_deal_id, magic,
                     opened_at, closed_at, reported_at, close_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id, pair, direction, entry_price, exit_price, pnl,
                    volume, mt5_ticket, mt5_deal_id, magic,
                    opened_at, closed_at, reported_at, close_reason,
                ),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError as e:
        # UNIQUE constraint violated → dédup hit, ignore silencieusement
        logger.debug(f"ea_closed_trades: dedup hit user_id={user_id} deal={mt5_deal_id}: {e}")
        return None


def get_last_n_for_pair(user_id: int, pair: str, n: int) -> list[dict[str, Any]]:
    """Retourne les N derniers trades fermés du user sur ce pair."""
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            """
            SELECT pnl, closed_at FROM ea_closed_trades
             WHERE user_id = ? AND pair = ?
             ORDER BY closed_at DESC LIMIT ?
            """,
            (user_id, pair, n),
        ).fetchall()
    return [dict(r) for r in rows]


def get_distinct_pairs_for_user(user_id: int) -> list[str]:
    """Retourne les pairs sur lesquels le user a déjà des trades fermés."""
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        rows = c.execute(
            "SELECT DISTINCT pair FROM ea_closed_trades WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    return [r[0] for r in rows]
