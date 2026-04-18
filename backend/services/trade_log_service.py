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
    with _conn() as c:
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
            CREATE INDEX IF NOT EXISTS idx_pt_user ON personal_trades(user);
            CREATE INDEX IF NOT EXISTS idx_pt_status ON personal_trades(status);
            CREATE INDEX IF NOT EXISTS idx_pt_created ON personal_trades(created_at);

            CREATE TABLE IF NOT EXISTS user_prefs (
                user TEXT PRIMARY KEY,
                silent_mode_manual INTEGER DEFAULT 0,
                updated_at TEXT
            );
        """)
        # Migration : ajoute les colonnes manquantes si DB existante
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


def record_trade(data: dict, user: str = "anonymous") -> int:
    """Enregistre un trade pris par l'utilisateur `user`."""
    _init_schema()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO personal_trades "
            "(user, pair, direction, entry_price, stop_loss, take_profit, size_lot, "
            "signal_pattern, signal_confidence, checklist_passed, notes, created_at, "
            "post_entry_sl, post_entry_tp, post_entry_size, post_entry_alarm) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user, data["pair"], data["direction"], float(data["entry_price"]),
                float(data["stop_loss"]), float(data["take_profit"]),
                float(data["size_lot"]),
                data.get("signal_pattern"),
                float(data["signal_confidence"]) if data.get("signal_confidence") else None,
                1 if data.get("checklist_passed") else 0,
                data.get("notes"),
                datetime.now(timezone.utc).isoformat(),
                1 if data.get("post_entry_sl") else 0,
                1 if data.get("post_entry_tp") else 0,
                1 if data.get("post_entry_size") else 0,
                1 if data.get("post_entry_alarm") else 0,
            ),
        )
        return cur.lastrowid


def close_trade(trade_id: int, exit_price: float, notes: str | None = None, user: str = "anonymous") -> bool:
    """Cloture un trade : calcule le PnL. Le trade doit appartenir a `user`."""
    _init_schema()
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM personal_trades WHERE id=? AND user=?", (trade_id, user)
        ).fetchone()
        if not row or row["status"] != "OPEN":
            return False
        pnl = _compute_pnl(row, exit_price)
        extra_notes = row["notes"] or ""
        if notes:
            extra_notes = (extra_notes + "\n" if extra_notes else "") + notes
        c.execute(
            "UPDATE personal_trades SET status='CLOSED', exit_price=?, pnl=?, notes=?, closed_at=? "
            "WHERE id=? AND user=?",
            (exit_price, pnl, extra_notes, datetime.now(timezone.utc).isoformat(), trade_id, user),
        )
    return True


def _compute_pnl(row: sqlite3.Row, exit_price: float) -> float:
    """PnL approximatif en unites de devise de cotation (USD pour XXX/USD)."""
    entry = row["entry_price"]
    size = row["size_lot"]
    # 1 lot standard = 100k units. Pour XAU/USD, 1 lot = 100 onces.
    # On reste simple : PnL = (exit - entry) * 100000 * size (forex)
    # Pour metaux c'est different mais on approxime.
    units = 100000 * size
    if row["direction"] == "buy":
        return round((exit_price - entry) * units, 2)
    return round((entry - exit_price) * units, 2)


def list_trades(status: str | None = None, limit: int = 100, user: str = "anonymous") -> list[dict]:
    _init_schema()
    with _conn() as c:
        if status:
            rows = c.execute(
                "SELECT * FROM personal_trades WHERE user=? AND status=? "
                "ORDER BY created_at DESC LIMIT ?",
                (user, status, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM personal_trades WHERE user=? "
                "ORDER BY created_at DESC LIMIT ?",
                (user, limit),
            ).fetchall()
        return [dict(r) for r in rows]


def get_trade(trade_id: int, user: str = "anonymous") -> dict | None:
    _init_schema()
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM personal_trades WHERE id=? AND user=?", (trade_id, user)
        ).fetchone()
        return dict(row) if row else None


def get_daily_status(user: str = "anonymous") -> dict:
    """Stats du jour pour `user`.

    Retourne :
    - silent_mode : ON/OFF selon le choix manuel du user (source unique de verite)
    - loss_alert : True si -X% atteint (informatif, non contraignant)
    """
    _init_schema()
    today_iso = date.today().isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT pnl, status FROM personal_trades "
            "WHERE user=? AND created_at >= ?",
            (user, today_iso + "T00:00:00"),
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


def silent_mode_active_any_user() -> bool:
    """True si AU MOINS UN user a atteint sa limite aujourd'hui."""
    _init_schema()
    today_iso = date.today().isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT user, SUM(pnl) as pnl FROM personal_trades "
            "WHERE status='CLOSED' AND created_at >= ? GROUP BY user",
            (today_iso + "T00:00:00",),
        ).fetchall()
    if not rows:
        return False
    limit_usd = -TRADING_CAPITAL * DAILY_LOSS_LIMIT_PCT / 100
    return any((r["pnl"] or 0) <= limit_usd for r in rows)


# Backward compat
def silent_mode_active() -> bool:
    return silent_mode_active_any_user()
