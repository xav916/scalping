"""Journal des trades personnels du user + mode silencieux journalier.

Distinct du backtest_service (qui track les signaux theoriques du radar).
Ici on enregistre les trades REELLEMENT pris par l'utilisateur, avec
son entry/SL/TP reels et ses notes.

SQLite persistant. Schema simple pour debuter.
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, date, timezone
from pathlib import Path

from config.settings import DAILY_LOSS_LIMIT_PCT, TRADING_CAPITAL

logger = logging.getLogger(__name__)

_DB_PATH = Path("/app/data/trades.db") if Path("/app").exists() else Path("trades.db")
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _init_schema() -> None:
    """Crée/migre le schéma SQLite.

    Ordre critique : on crée d'abord les TABLES (sans les INDEX), puis on
    migre les colonnes manquantes sur les bases existantes, et SEULEMENT
    ENSUITE on pose les INDEX (qui référencent ces colonnes).

    Avant ce fix : sur une DB pré-migration (sans colonne `user`), le
    `CREATE INDEX ... ON personal_trades(user)` du executescript plantait
    avec "no such column: user" et empêchait tout le reste de tourner.
    """
    with _conn() as c:
        # 1) Créer les tables si elles n'existent pas (no-op sur DB ancienne)
        c.executescript("""
            CREATE TABLE IF NOT EXISTS personal_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT NOT NULL DEFAULT 'anonymous',
                pair TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                size_lot REAL NOT NULL,
                signal_pattern TEXT,
                signal_confidence REAL,
                checklist_passed INTEGER DEFAULT 0,
                notes TEXT,
                status TEXT DEFAULT 'OPEN',
                exit_price REAL,
                pnl REAL DEFAULT 0,
                created_at TEXT NOT NULL,
                closed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS user_prefs (
                user TEXT PRIMARY KEY,
                silent_mode_manual INTEGER DEFAULT 0,
                updated_at TEXT
            );
        """)

        # 2) Migration : ajouter les colonnes manquantes sur DB pré-migration.
        # SQLite n'accepte pas ADD COLUMN NOT NULL sans DEFAULT, donc on
        # reste sur DEFAULT 'anonymous' (identique au CREATE TABLE).
        cols = [r[1] for r in c.execute("PRAGMA table_info(personal_trades)").fetchall()]
        if "user" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN user TEXT NOT NULL DEFAULT 'anonymous'")
        if "post_entry_sl" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN post_entry_sl INTEGER DEFAULT 0")
        if "post_entry_tp" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN post_entry_tp INTEGER DEFAULT 0")
        if "post_entry_size" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN post_entry_size INTEGER DEFAULT 0")
        if "post_entry_alarm" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN post_entry_alarm INTEGER DEFAULT 0")
        # Traçabilité auto-exec : lien vers le ticket MT5 + flag 'ordre automatique'
        if "mt5_ticket" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN mt5_ticket INTEGER")
        if "is_auto" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN is_auto INTEGER DEFAULT 0")
        if "context_macro" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN context_macro TEXT")
        # Traçabilité ML-ready : lien vers le signal d'origine, prix
        # d'exécution réel (vs entry théorique), slippage calculé, raison
        # de fermeture. Ces colonnes alimenteront le futur dataset ML.
        if "signal_id" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN signal_id INTEGER")
        if "fill_price" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN fill_price REAL")
        if "slippage_pips" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN slippage_pips REAL")
        if "close_reason" not in cols:
            # TP1 | TP2 | SL | MANUAL | TIMEOUT | UNKNOWN — remonte depuis
            # le bridge si disponible, sinon reste NULL.
            c.execute("ALTER TABLE personal_trades ADD COLUMN close_reason TEXT")

        # 3) Poser les INDEX une fois toutes les colonnes présentes
        c.executescript("""
            CREATE INDEX IF NOT EXISTS idx_pt_user ON personal_trades(user);
            CREATE INDEX IF NOT EXISTS idx_pt_status ON personal_trades(status);
            CREATE INDEX IF NOT EXISTS idx_pt_created ON personal_trades(created_at);
            CREATE INDEX IF NOT EXISTS idx_pt_ticket ON personal_trades(mt5_ticket);
            CREATE INDEX IF NOT EXISTS idx_pt_signal ON personal_trades(signal_id);
        """)
        # Unicité (mt5_ticket, direction). C'est ELLE qui donne son effet au
        # `INSERT OR IGNORE` de `mt5_sync._upsert_open_trade` : sans contrainte
        # à violer, `OR IGNORE` n'ignore rien et insère le doublon. Ce garde
        # était écrit depuis le début mais sans prise — 544 doublons accumulés
        # entre avril et juin 2026, purgés le 2026-08-13.
        #
        # La clé porte sur (ticket, sens) et non sur le ticket seul : une
        # position a parfois une patte de clôture (`close-sell`, `close-buy`)
        # qui partage son ticket. `UNIQUE(mt5_ticket)` les rendrait impossibles.
        #
        # ⚠️ Le repli est OBLIGATOIRE : une autre base (autre locataire, clone,
        # sauvegarde ancienne) peut encore contenir des doublons. `_init_schema`
        # est appelé à chaque opération — y laisser remonter l'exception
        # arrêterait le service pour une question d'hygiène. Même principe que
        # la porte d'heure : une contrainte qui ne peut pas se poser se tait.
        try:
            c.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_pt_ticket_dir "
                "  ON personal_trades(mt5_ticket, direction)"
            )
        except sqlite3.IntegrityError:
            logger.warning(
                "personal_trades: doublons (mt5_ticket, direction) presents, "
                "index unique NON pose. Purger avant de compter quoi que ce soit."
            )


def get_manual_silent(user: str) -> bool:
    _init_schema()
    with _conn() as c:
        row = c.execute(
            "SELECT silent_mode_manual FROM user_prefs WHERE user=?", (user,)
        ).fetchone()
        return bool(row["silent_mode_manual"]) if row else False


def set_manual_silent(user: str, active: bool) -> bool:
    _init_schema()
    with _conn() as c:
        c.execute(
            "INSERT INTO user_prefs (user, silent_mode_manual, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user) DO UPDATE SET silent_mode_manual=excluded.silent_mode_manual, "
            "updated_at=excluded.updated_at",
            (user, 1 if active else 0, datetime.now(timezone.utc).isoformat()),
        )
    return active


@contextmanager
def _conn():
    conn = sqlite3.connect(str(_DB_PATH), isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _scope_clause(user: str, user_id: int | None) -> tuple[str, tuple]:
    """Chantier 3 SaaS : retourne (SQL fragment, params) pour scoper par user.

    - Si `user_id` est fourni (user DB) : scope par colonne `user_id` (exact,
      isolation multi-tenant garantie).
    - Sinon (user env legacy) : scope par colonne `user` TEXT (back-compat).

    Garde invariable : une seule des deux colonnes est interrogée, évite les
    OR ambigus.
    """
    if user_id is not None:
        return "user_id = ?", (user_id,)
    return "user = ?", (user,)


def list_trades(
    status: str | None = None,
    limit: int = 100,
    user: str = "anonymous",
    user_id: int | None = None,
) -> list[dict]:
    _init_schema()
    scope_sql, scope_params = _scope_clause(user, user_id)
    with _conn() as c:
        if status:
            rows = c.execute(
                f"SELECT * FROM personal_trades WHERE {scope_sql} AND status=? "
                "ORDER BY created_at DESC LIMIT ?",
                (*scope_params, status, limit),
            ).fetchall()
        else:
            rows = c.execute(
                f"SELECT * FROM personal_trades WHERE {scope_sql} "
                "ORDER BY created_at DESC LIMIT ?",
                (*scope_params, limit),
            ).fetchall()
        return [dict(r) for r in rows]


def get_trade(
    trade_id: int,
    user: str = "anonymous",
    user_id: int | None = None,
) -> dict | None:
    _init_schema()
    scope_sql, scope_params = _scope_clause(user, user_id)
    with _conn() as c:
        row = c.execute(
            f"SELECT * FROM personal_trades WHERE id=? AND {scope_sql}",
            (trade_id, *scope_params),
        ).fetchone()
        return dict(row) if row else None


def get_daily_status(user: str = "anonymous", user_id: int | None = None) -> dict:
    """Stats du jour pour `user` (ou `user_id` si fourni, préféré).

    Retourne :
    - silent_mode : ON/OFF selon le choix manuel du user (source unique de verite)
    - loss_alert : True si -X% atteint (informatif, non contraignant)
    """
    _init_schema()
    today_iso = date.today().isoformat()
    scope_sql, scope_params = _scope_clause(user, user_id)
    with _conn() as c:
        rows = c.execute(
            f"SELECT pnl, status FROM personal_trades "
            f"WHERE {scope_sql} AND created_at >= ?",
            (*scope_params, today_iso + "T00:00:00"),
        ).fetchall()

    n_total = len(rows)
    n_open = sum(1 for r in rows if r["status"] == "OPEN")
    pnl_today = sum(r["pnl"] or 0 for r in rows if r["status"] == "CLOSED")
    pnl_pct = (pnl_today / TRADING_CAPITAL * 100) if TRADING_CAPITAL > 0 else 0.0
    loss_alert = pnl_pct <= -DAILY_LOSS_LIMIT_PCT
    silent_mode = get_manual_silent(user)

    return {
        "date": today_iso,
        "n_trades_today": n_total,
        "n_open": n_open,
        "n_closed_today": n_total - n_open,
        "pnl_today": round(pnl_today, 2),
        "pnl_pct": round(pnl_pct, 2),
        "silent_mode": silent_mode,
        "loss_alert": loss_alert,
        "daily_loss_limit_pct": DAILY_LOSS_LIMIT_PCT,
        "capital": TRADING_CAPITAL,
    }


def silent_mode_active_for_user(user: str) -> bool:
    """True si CE user a atteint sa limite journaliere."""
    try:
        return get_daily_status(user=user)["silent_mode"]
    except Exception:
        return False


def _destinations_reelles() -> frozenset[str]:
    """Identifiants des destinations qui engagent de l'ARGENT REEL.

    Lu dans le registre (`Destination.reel`) plutot que recopie ici : c'est la
    duplication d'une table de ce genre qui avait fait afficher « Demo » sur
    des trades Kraken engageant de l'argent reel.
    """
    try:
        from backend.services.destinations_registry import DESTINATIONS
        return frozenset(k for k, d in DESTINATIONS.items()
                         if getattr(d, "reel", False))
    except Exception:
        return frozenset()


def silent_mode_active_any_user() -> bool:
    """True si AU MOINS UN user a atteint sa limite aujourd'hui.

    ⚠️ **Ne compte que l'argent REEL** (2026-08-20). `personal_trades` ne
    porte pas de `destination_id` : demo et reel s'additionnaient donc sous le
    meme utilisateur, et une perte sur le demo — de l'argent qui n'existe
    pas — coupait le trading reel.

    Mesure sur 30 jours avant correction : le seuil se serait declenche le
    12/08 sur **−101,98 EUR de DEMO**, alors que la seule journee reellement
    mauvaise (05/08, −271,88 EUR de reel) etait noyee dans le meme total.

    La destination se resout depuis `mt5_pushes` via le ticket — **exact
    plutot qu'heuristique**, comme `destination_for_ticket` : deviner d'apres
    le format du numero serait fragile, et c'est de l'argent reel.

    ⚠️ Une destination **non resolue compte comme reelle**. Quand on ne sait
    pas, on protege : l'inverse laisserait un trade inconnu echapper au
    garde-fou.

    ⚠️ Sous-requete correlee et non jointure : un `LEFT JOIN` sur `LIKE`
    pourrait apparier plusieurs pushes pour un meme ticket et **gonfler la
    somme**, donc declencher a tort.
    """
    _init_schema()
    reelles = _destinations_reelles()
    if not reelles:
        # Registre illisible : on ne filtre pas plutot que de tout ignorer.
        # Se taire ici reviendrait a desarmer le garde-fou en silence.
        logger.warning(
            "silent_mode: registre des destinations illisible — "
            "le plafond journalier compte TOUTES les destinations")
        clause = ""
        params: tuple = (date.today().isoformat() + "T00:00:00",)
    else:
        trous = ",".join("?" * len(reelles))
        clause = (
            " AND COALESCE(CASE WHEN t.mt5_ticket IS NULL THEN NULL ELSE ("
            "   SELECT p.destination_id FROM mt5_pushes p"
            "    WHERE p.bridge_response LIKE '%' || t.mt5_ticket || '%'"
            "    ORDER BY p.id DESC LIMIT 1) END, '?')"
            f" IN ({trous}, '?')"
        )
        params = (date.today().isoformat() + "T00:00:00",
                  *sorted(reelles))

    with _conn() as c:
        rows = c.execute(
            "SELECT t.user AS user, SUM(t.pnl) AS pnl FROM personal_trades t "
            "WHERE t.status='CLOSED' AND t.created_at >= ?" + clause +
            " GROUP BY t.user",
            params,
        ).fetchall()
    if not rows:
        return False
    limit_usd = -TRADING_CAPITAL * DAILY_LOSS_LIMIT_PCT / 100
    return any((r["pnl"] or 0) <= limit_usd for r in rows)


# Backward compat
def silent_mode_active() -> bool:
    return silent_mode_active_any_user()
