"""Queue de pending orders pour les EA MQL5 polling-based.

Phase MQL.B du pivot bridge Python → EA MQL5
(cf. ``docs/superpowers/specs/2026-04-29-mql5-ea-pivot-spec.md``).

Le SaaS enqueue les ordres en attente côté DB. L'EA tournant chez le user
poll régulièrement (~30s) via HTTP : récupère les ordres PENDING, les
exécute via ``OrderSend()`` natif MT5, push le résultat avec mt5_ticket
+ status. Push → pull pattern qui élimine le besoin d'un bridge Python
local au user.

Cycle de vie d'un order :

    PENDING ──fetch──► SENT ──record_result──► EXECUTED  (OrderSend OK)
       │                  │                ──► FAILED    (OrderSend KO)
       │                  │
       └──TTL expiré──────┴──► EXPIRED   (purge job)

Note V1 sécurité : ``api_key`` est stocké en clair dans la table. Suffisant
sur HTTPS pour V1, à migrer vers hash SHA256 en MQL.G ou plus tard.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ─── Statuts du cycle de vie d'un order ───────────────────────────────

STATUS_PENDING = "PENDING"      # enqueué par le SaaS, pas encore lu
STATUS_SENT = "SENT"            # l'EA l'a fetch, exécution en cours
STATUS_EXECUTED = "EXECUTED"    # l'EA a confirmé OrderSend OK
STATUS_FAILED = "FAILED"        # l'EA a confirmé OrderSend KO (retcode)
STATUS_EXPIRED = "EXPIRED"      # TTL dépassé sans fetch (purge job)

VALID_STATUSES = (
    STATUS_PENDING,
    STATUS_SENT,
    STATUS_EXECUTED,
    STATUS_FAILED,
    STATUS_EXPIRED,
)


def _db_path() -> str:
    from backend.services.trade_log_service import _DB_PATH

    return str(_DB_PATH)


def _ensure_schema() -> None:
    """Crée la table ``mt5_pending_orders`` si elle n'existe pas. Idempotent."""
    with sqlite3.connect(_db_path()) as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS mt5_pending_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                api_key TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                fetched_at TEXT,
                executed_at TEXT,
                mt5_ticket INTEGER,
                mt5_error TEXT,
                expires_at TEXT NOT NULL
            )
            """
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_pending_user_status "
            "ON mt5_pending_orders(user_id, status)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_pending_apikey "
            "ON mt5_pending_orders(api_key, status)"
        )


# ─── Enqueue (côté SaaS, depuis _enqueue_for_destination) ────────────


def enqueue(
    user_id: int,
    api_key: str,
    payload: dict[str, Any],
    ttl_seconds: int = 300,
) -> int:
    """Insère un nouveau order en status PENDING. Retourne l'id inséré.

    Le ``payload`` contient le contrat ordre (pair, direction, entry, sl,
    tp, risk_money, etc. — exactement ce qu'envoyait l'ancien bridge HTTP).
    L'EA reçoit ce payload dans ``GET /api/ea/pending`` et le passe à
    ``OrderSend()`` MT5 en convertissant les types.
    """
    _ensure_schema()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=ttl_seconds)
    with sqlite3.connect(_db_path()) as c:
        cur = c.execute(
            """
            INSERT INTO mt5_pending_orders
                (user_id, api_key, payload, status, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                api_key,
                json.dumps(payload),
                STATUS_PENDING,
                now.isoformat(),
                expires.isoformat(),
            ),
        )
        return int(cur.lastrowid or 0)


# ─── Fetch (côté EA, polling) ─────────────────────────────────────────


def fetch_for_api_key(api_key: str, limit: int = 5) -> list[dict]:
    """Retourne les ordres PENDING pour cet ``api_key``, marqués SENT
    atomiquement.

    Implémente un race-safe pull : ``BEGIN IMMEDIATE`` prend un write
    lock dès le SELECT, ce qui sérialise les pulls concurrents. SQLite
    n'a pas ``RETURNING`` avant 3.35 → on fait SELECT + UPDATE en 2
    étapes dans la même transaction.

    Filtre TTL : seuls les orders ``expires_at > now`` sont retournés.
    Les expirés restent en PENDING tant que ``purge_expired()`` ne les
    flag pas — ils ne pollueront pas le pull car filtrés ici.
    """
    _ensure_schema()
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(_db_path()) as c:
        c.execute("BEGIN IMMEDIATE")
        try:
            rows = c.execute(
                """
                SELECT id, user_id, payload, created_at, expires_at
                FROM mt5_pending_orders
                WHERE api_key = ? AND status = ? AND expires_at > ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (api_key, STATUS_PENDING, now, limit),
            ).fetchall()

            if not rows:
                c.execute("ROLLBACK")
                return []

            ids = [r[0] for r in rows]
            placeholders = ",".join("?" * len(ids))
            c.execute(
                f"UPDATE mt5_pending_orders SET status = ?, fetched_at = ? "
                f"WHERE id IN ({placeholders})",
                [STATUS_SENT, now] + ids,
            )
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise

    result: list[dict] = []
    for row in rows:
        try:
            payload = json.loads(row[2])
        except (json.JSONDecodeError, TypeError):
            payload = {}
        result.append(
            {
                "order_id": row[0],
                "user_id": row[1],
                "payload": payload,
                "created_at": row[3],
                "expires_at": row[4],
            }
        )
    return result


# ─── Record result (côté EA, après OrderSend) ────────────────────────


def record_result(
    order_id: int,
    api_key: str,
    *,
    ok: bool,
    mt5_ticket: int | None = None,
    error: str | None = None,
) -> bool:
    """L'EA confirme l'exécution.

    Returns
    -------
    bool
        ``True`` si la ligne a été mise à jour (order trouvé + appartient à
        cet api_key + status était SENT). ``False`` sinon — l'EA peut
        considérer ça comme "déjà ack par un autre EA" ou "order pas valide".

    L'``api_key`` est exigé en plus de l'``order_id`` pour empêcher l'EA
    d'un user de marquer l'order d'un autre user (defense in depth contre
    une éventuelle fuite d'order_id).
    """
    _ensure_schema()
    now = datetime.now(timezone.utc).isoformat()
    new_status = STATUS_EXECUTED if ok else STATUS_FAILED
    with sqlite3.connect(_db_path()) as c:
        cur = c.execute(
            """
            UPDATE mt5_pending_orders
            SET status = ?, executed_at = ?, mt5_ticket = ?, mt5_error = ?
            WHERE id = ? AND api_key = ? AND status = ?
            """,
            (
                new_status,
                now,
                mt5_ticket,
                (error or "")[:500] or None,
                order_id,
                api_key,
                STATUS_SENT,
            ),
        )
        return cur.rowcount > 0


# ─── Maintenance ──────────────────────────────────────────────────────


def purge_expired() -> int:
    """Marque les PENDING/SENT expirés en EXPIRED. Retourne le nombre.

    À appeler par cron ou job admin (toutes les heures par exemple). Ne
    supprime pas les rows : on garde l'historique pour audit / debug
    (qui a expiré quand, pourquoi).
    """
    _ensure_schema()
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(_db_path()) as c:
        cur = c.execute(
            """
            UPDATE mt5_pending_orders
            SET status = ?
            WHERE status IN (?, ?) AND expires_at < ?
            """,
            (STATUS_EXPIRED, STATUS_PENDING, STATUS_SENT, now),
        )
        return cur.rowcount or 0


def count_by_status(user_id: int | None = None) -> dict[str, int]:
    """Stats par status. Filtre par ``user_id`` si fourni. Pour debug."""
    _ensure_schema()
    if user_id is not None:
        with sqlite3.connect(_db_path()) as c:
            rows = c.execute(
                "SELECT status, COUNT(*) FROM mt5_pending_orders "
                "WHERE user_id = ? GROUP BY status",
                (int(user_id),),
            ).fetchall()
    else:
        with sqlite3.connect(_db_path()) as c:
            rows = c.execute(
                "SELECT status, COUNT(*) FROM mt5_pending_orders GROUP BY status"
            ).fetchall()
    return {row[0]: int(row[1]) for row in rows}
