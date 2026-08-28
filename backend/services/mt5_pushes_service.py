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
                horizon TEXT,
                pattern TEXT,
                mt5_ticket INTEGER,
                source TEXT,
                UNIQUE(destination_id, date, pair, direction, entry_price_5dp)
            )
            """
        )
        # Migration 2026-08-26 : l'horizon et le motif n'existaient nulle part
        # dans la chaîne persistée. Ils ne sont connus qu'ICI, au moment du
        # dispatch, et le ticket est le seul identifiant partagé avec le trade.
        cols = {r[1] for r in c.execute("PRAGMA table_info(mt5_pushes)")}
        for nom, typ in (("horizon", "TEXT"), ("pattern", "TEXT"),
                         ("mt5_ticket", "INTEGER"), ("source", "TEXT")):
            if nom not in cols:
                c.execute(f"ALTER TABLE mt5_pushes ADD COLUMN {nom} {typ}")
        c.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_mt5_pushes_lookup
            ON mt5_pushes(destination_id, date, pair)
            """
        )


def source_du_setup(setup) -> str:
    """Fournisseur d'un setup — ``interne`` par défaut.

    ⛔ Un seul point de lecture pour les quatre appelants de
    `try_register_push`. Recopier `getattr(setup, "source", None)` quatre fois
    garantissait qu'un des quatre l'oublie, et un push sans `source` fait
    disparaître un trade externe dans notre P&L sans rattrapage possible —
    c'est ce que l'horizon a démontré sur 390 676 signaux.

    ⚠️ Jamais `None` : la colonne sert à FILTRER (`source IN (...)` du banc
    d'essai). Un `NULL` échappe à tout filtre, y compris à celui qui
    chercherait nos propres trades.
    """
    valeur = str(getattr(setup, "source", "") or "").strip()
    return valeur or "interne"


def try_register_push(
    destination_id: str,
    push_date: str,
    pair: str,
    direction: str,
    entry_price_5dp: str,
    horizon: str | None = None,
    pattern: str | None = None,
    source: str | None = None,
) -> bool:
    """Tente d'enregistrer un push (status PENDING / ok=0).

    ``horizon`` et ``pattern`` viennent du setup, seul endroit de la chaîne où
    ils sont encore connus. Sans eux, aucune hypothèse par horizon n'est
    mesurable en aval — cf. `backend/tests/test_horizon_trace.py`.

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
                    pushed_at, ok, bridge_response, horizon, pattern, source
                ) VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, ?)
                """,
                (
                    destination_id,
                    push_date,
                    pair,
                    direction,
                    entry_price_5dp,
                    datetime.now(timezone.utc).isoformat(),
                    horizon,
                    pattern,
                    source,
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
) -> None:
    """Met à jour la ligne avec le résultat du push HTTP.

    Best-effort : toute erreur DB est loggée et silenced.
    """
    try:
        body = json.dumps(response, default=str)[:500] if response else None
        # Le ticket est rangé en COLONNE, pas laissé dans le JSON : une jointure
        # qui oblige à ré-analyser du texte à chaque lecture n'est jamais faite.
        ticket = None
        if response:
            try:
                ticket = int(response.get("ticket")) if response.get("ticket") else None
            except (TypeError, ValueError):
                ticket = None
        with sqlite3.connect(_db_path()) as c:
            c.execute(
                """
                UPDATE mt5_pushes
                SET ok = ?, bridge_response = ?,
                    mt5_ticket = COALESCE(?, mt5_ticket)
                WHERE destination_id = ? AND date = ? AND pair = ?
                  AND direction = ? AND entry_price_5dp = ?
                """,
                (
                    1 if ok else 0,
                    body,
                    ticket,
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

    ⛔ **Ne touche JAMAIS une ligne déjà confirmée** — `ok = 1` ou un ticket
    présent. Une telle ligne atteste d'un ordre RÉELLEMENT passé chez le
    courtier : l'effacer ferait deux dégâts, et le second est le pire.

    1. Elle autoriserait un retry d'un ordre déjà exécuté, donc un doublon.
    2. Elle effacerait la seule trace reliant l'ordre à son `horizon`, son
       motif et sa `source`. Aucun rattrapage n'existe — l'horizon l'a
       démontré sur 390 676 signaux.

    > **Une ligne qui atteste d'un ordre passé n'est pas une réservation à
    > libérer.** Les deux vivaient dans la même table et sous la même clé.

    Constaté le 2026-08-28 : `mt5_pushes` était tombé de 139 lignes le 20/08
    à ZÉRO les 27 et 28, pendant que des ordres partaient. La date n'est pas
    un hasard — c'est celle du plafond de risque, qui a fait exploser les
    refus, et **chaque refus efface sa ligne**.
    """
    try:
        with sqlite3.connect(_db_path()) as c:
            cur = c.execute(
                """
                DELETE FROM mt5_pushes
                WHERE destination_id = ? AND date = ? AND pair = ?
                  AND direction = ? AND entry_price_5dp = ?
                  AND COALESCE(ok, 0) = 0 AND mt5_ticket IS NULL
                """,
                (
                    destination_id,
                    push_date,
                    pair,
                    direction,
                    entry_price_5dp,
                ),
            )
            # ⛔ Trace au niveau INFO, pas DEBUG. Le 2026-08-28, la table etait
            # tombee de 139 lignes a zero sans qu'une seule ligne de journal ne
            # le dise : la suppression et le refus de supprimer se lisaient
            # pareil, c'est-a-dire pas du tout.
            #
            # `rowcount = 0` porte deux sens qu'il faut distinguer en lisant :
            # aucune ligne (deja liberee) OU une ligne CONFIRMEE que le
            # garde-fou vient de proteger.
            logger.info(
                "mt5_pushes: discard %s %s %s %s -> %d ligne(s) supprimee(s)",
                destination_id, push_date, pair, direction, cur.rowcount or 0)
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


def get_push(destination_id: str, push_date: str, pair: str, direction: str,
             entry_price_5dp: str) -> dict[str, Any] | None:
    """La ligne de poussée, ou ``None``. Sert au diagnostic et aux tests."""
    try:
        _ensure_schema()
        with sqlite3.connect(_db_path()) as c:
            c.row_factory = sqlite3.Row
            r = c.execute(
                """SELECT * FROM mt5_pushes
                    WHERE destination_id = ? AND date = ? AND pair = ?
                      AND direction = ? AND entry_price_5dp = ?""",
                (destination_id, push_date, pair, direction, entry_price_5dp),
            ).fetchone()
        return dict(r) if r else None
    except Exception as e:  # noqa: BLE001
        logger.debug(f"mt5_pushes: get_push failed: {e}")
        return None
