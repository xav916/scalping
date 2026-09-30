"""Persistance partagée des pushes MT5 — dedup atomique multi-tenant.

Pour chaque tentative de push d'un setup vers une destination (admin_legacy
ou un user Premium), une ligne est insérée dans ``mt5_pushes`` avec une
contrainte ``UNIQUE(destination_id, date, pair, direction, entry_price_5dp)``.

Permet :
- Dedup atomique en cas de plusieurs process scoring en parallèle (V2+).
  V1 = single-process asyncio donc pas critique, mais la DB devient la
  source de vérité shared multi-process futur.
- Audit : qui a reçu quoi quand (compléments des logs structurés).

Le ``_sent_setups_today`` set in-memory de ``mt5_bridge`` est conservé en
parallèle pour rétro-compat des tests existants — il reflète l'état DB
mais n'est plus la source autoritaire.

Voir ``docs/superpowers/specs/2026-04-28-multi-tenant-bridge-routing.md``
(Phase B).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _db_path() -> str:
    from backend.services.trade_log_service import _DB_PATH

    return str(_DB_PATH)


def _ensure_schema() -> None:
    """Crée la table ``mt5_pushes`` si elle n'existe pas. Idempotent."""
    with sqlite3.connect(_db_path()) as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS mt5_pushes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                destination_id TEXT NOT NULL,
                date TEXT NOT NULL,
                pair TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price_5dp TEXT NOT NULL,
                pushed_at TEXT NOT NULL,
                ok INTEGER NOT NULL,
                bridge_response TEXT,
                UNIQUE(destination_id, date, pair, direction, entry_price_5dp)
            )
            """
        )
        c.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_mt5_pushes_lookup
            ON mt5_pushes(destination_id, date, pair)
            """
        )
        # risk_money (2026-08-25) : le risque VOULU, pour pouvoir le comparer
        # au risque réellement engagé. Le 25/08 il a fallu le reconstruire par
        # arithmétique inverse — journalctl ne tient qu'un jour et
        # bridge_response ne le porte pas.
        #
        # ⛔ NULLABLE, et ajouté par ALTER pour ne pas toucher aux lignes
        # existantes : `mt5_pushes` porte l'historique des ordres réels. Un
        # risk_money inconnu ne vaut pas zéro — les confondre rendrait tout
        # contrôle de réciprocité ininterprétable.
        try:
            c.execute("ALTER TABLE mt5_pushes ADD COLUMN risk_money REAL")
        except sqlite3.OperationalError:
            pass        # colonne déjà présente — migration idempotente


def try_register_push(
    destination_id: str,
    push_date: str,
    pair: str,
    direction: str,
    entry_price_5dp: str,
) -> bool:
    """Tente d'enregistrer un push (status PENDING / ok=0).

    Returns
    -------
    bool
        ``True`` si la ligne a été insérée (clé nouvelle pour aujourd'hui).
        ``False`` si la clé UNIQUE existait déjà (déjà pushé / déjà tenté).

    Notes
    -----
    Best-effort : toute erreur DB est loggée et retourne ``True`` (fallback
    safe : autorise le push, dédup éventuellement ratée mais pas de blocage
    fonctionnel).
    """
    try:
        _ensure_schema()
        with sqlite3.connect(_db_path()) as c:
            cur = c.execute(
                """
                INSERT OR IGNORE INTO mt5_pushes (
                    destination_id, date, pair, direction, entry_price_5dp,
                    pushed_at, ok, bridge_response
                ) VALUES (?, ?, ?, ?, ?, ?, 0, NULL)
                """,
                (
                    destination_id,
                    push_date,
                    pair,
                    direction,
                    entry_price_5dp,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.debug(f"mt5_pushes: try_register_push failed: {e}")
        return True  # fallback safe


def update_push_result(
    destination_id: str,
    push_date: str,
    pair: str,
    direction: str,
    entry_price_5dp: str,
    *,
    ok: bool,
    response: dict[str, Any] | None = None,
    risk_money: float | None = None,
) -> None:
    """Met à jour la ligne avec le résultat du push HTTP.

    Best-effort : toute erreur DB est loggée et silenced.

    ``risk_money`` est le risque VOULU, en devise du compte. ⛔ `COALESCE` :
    un appelant qui ne le fournit pas n'efface pas une valeur déjà écrite —
    les appelants qui n'ont pas le sizing en portée laissent donc la colonne
    à NULL, ce qui est la vérité, plutôt qu'à un zéro inventé.
    """
    try:
        body = json.dumps(response, default=str)[:500] if response else None
        with sqlite3.connect(_db_path()) as c:
            c.execute(
                """
                UPDATE mt5_pushes
                SET ok = ?, bridge_response = ?,
                    risk_money = COALESCE(?, risk_money)
                WHERE destination_id = ? AND date = ? AND pair = ?
                  AND direction = ? AND entry_price_5dp = ?
                """,
                (
                    1 if ok else 0,
                    body,
                    risk_money,
                    destination_id,
                    push_date,
                    pair,
                    direction,
                    entry_price_5dp,
                ),
            )
    except Exception as e:
        logger.debug(f"mt5_pushes: update_push_result failed: {e}")


def discard_push(
    destination_id: str,
    push_date: str,
    pair: str,
    direction: str,
    entry_price_5dp: str,
) -> None:
    """Supprime la ligne pour permettre un retry au cycle suivant.

    Utile quand un push HTTP échoue avec une erreur récupérable
    (timeout PC éteint, max_positions bridge à libérer).
    """
    try:
        with sqlite3.connect(_db_path()) as c:
            c.execute(
                """
                DELETE FROM mt5_pushes
                WHERE destination_id = ? AND date = ? AND pair = ?
                  AND direction = ? AND entry_price_5dp = ?
                """,
                (
                    destination_id,
                    push_date,
                    pair,
                    direction,
                    entry_price_5dp,
                ),
            )
    except Exception as e:
        logger.debug(f"mt5_pushes: discard_push failed: {e}")


def purge_old_pushes(retention_days: int = 30) -> int:
    """Supprime les pushes de plus de ``retention_days`` jours.

    Returns
    -------
    int
        Nombre de lignes supprimées (0 en cas d'erreur).
    """
    try:
        with sqlite3.connect(_db_path()) as c:
            cur = c.execute(
                "DELETE FROM mt5_pushes WHERE date < date('now', ?)",
                (f"-{int(retention_days)} days",),
            )
            return cur.rowcount or 0
    except Exception as e:
        logger.debug(f"mt5_pushes: purge_old_pushes failed: {e}")
        return 0
