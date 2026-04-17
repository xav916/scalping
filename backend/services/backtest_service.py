"""Backtest des signaux emis : stocke chaque trade setup et son issue.

Utilise SQLite pour la persistance (fichier sqlite unique, pas de serveur).
Chaque setup emis est enregistre avec entry/SL/TP1/TP2. Un job periodique
verifie le prix courant et marque l'issue : WIN (TP1 ou TP2 atteint), LOSS
(SL atteint), ou OPEN (en attente).

Statistiques exposees : taux de reussite, R:R moyen, PnL cumule.
"""

import asyncio
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from backend.models.schemas import TradeDirection, TradeSetup
from backend.services.price_service import fetch_current_price

logger = logging.getLogger(__name__)

_DB_PATH = Path("/app/data/backtest.db") if Path("/app").exists() else Path("backtest.db")
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _init_schema() -> None:
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit_1 REAL NOT NULL,
                take_profit_2 REAL NOT NULL,
                confidence_score REAL,
                pattern TEXT,
                emitted_at TEXT NOT NULL,
                checked_at TEXT,
                outcome TEXT DEFAULT 'OPEN',
                exit_price REAL,
                rr_realized REAL
            );
            CREATE INDEX IF NOT EXISTS idx_trades_outcome ON trades(outcome);
            CREATE INDEX IF NOT EXISTS idx_trades_emitted ON trades(emitted_at);
        """)


@contextmanager
def _conn():
    conn = sqlite3.connect(str(_DB_PATH), isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def record_setups(setups: list[TradeSetup]) -> None:
    """Enregistre chaque setup emis (dedup par pair+direction+entry+timestamp)."""
    _init_schema()
    with _conn() as c:
        for s in setups:
            # Deduplication : meme setup deja enregistre dans la derniere heure ?
            cur = c.execute(
                "SELECT id FROM trades WHERE pair=? AND direction=? AND entry_price=? "
                "AND emitted_at >= datetime('now', '-1 hour') LIMIT 1",
                (s.pair, s.direction.value, s.entry_price),
            )
            if cur.fetchone():
                continue
            c.execute(
                "INSERT INTO trades (pair, direction, entry_price, stop_loss, "
                "take_profit_1, take_profit_2, confidence_score, pattern, emitted_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    s.pair, s.direction.value, s.entry_price, s.stop_loss,
                    s.take_profit_1, s.take_profit_2, s.confidence_score,
                    s.pattern.pattern.value if s.pattern else None,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )


async def check_open_trades() -> None:
    """Pour chaque trade OPEN, verifie si SL ou TP a ete touche. MAJ en base."""
    _init_schema()
    with _conn() as c:
        cur = c.execute("SELECT * FROM trades WHERE outcome='OPEN'")
        open_trades = cur.fetchall()

    for row in open_trades:
        current = await fetch_current_price(row["pair"])
        if current is None:
            continue
        outcome, rr = _evaluate(row, current)
        if outcome == "OPEN":
            continue
        with _conn() as c:
            c.execute(
                "UPDATE trades SET outcome=?, exit_price=?, rr_realized=?, checked_at=? WHERE id=?",
                (outcome, current, rr, datetime.now(timezone.utc).isoformat(), row["id"]),
            )
        logger.info(f"Backtest: trade #{row['id']} {row['pair']} -> {outcome} (R:R {rr:.2f})")


def _evaluate(row: sqlite3.Row, price: float) -> tuple[str, float]:
    """Decide si le trade a atteint SL, TP1, TP2 ou reste OPEN."""
    entry, sl = row["entry_price"], row["stop_loss"]
    tp1, tp2 = row["take_profit_1"], row["take_profit_2"]
    risk = abs(entry - sl)
    if row["direction"] == "buy":
        if price <= sl:
            return "LOSS", -1.0
        if price >= tp2:
            return "WIN_TP2", abs(tp2 - entry) / risk if risk else 0.0
        if price >= tp1:
            return "WIN_TP1", abs(tp1 - entry) / risk if risk else 0.0
    else:  # sell
        if price >= sl:
            return "LOSS", -1.0
        if price <= tp2:
            return "WIN_TP2", abs(entry - tp2) / risk if risk else 0.0
        if price <= tp1:
            return "WIN_TP1", abs(entry - tp1) / risk if risk else 0.0
    return "OPEN", 0.0


def get_stats() -> dict:
    """Statistiques globales du backtest."""
    _init_schema()
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        closed = c.execute("SELECT COUNT(*) FROM trades WHERE outcome != 'OPEN'").fetchone()[0]
        wins = c.execute(
            "SELECT COUNT(*) FROM trades WHERE outcome IN ('WIN_TP1', 'WIN_TP2')"
        ).fetchone()[0]
        losses = c.execute("SELECT COUNT(*) FROM trades WHERE outcome='LOSS'").fetchone()[0]
        avg_rr = c.execute(
            "SELECT AVG(rr_realized) FROM trades WHERE outcome != 'OPEN'"
        ).fetchone()[0] or 0.0
        by_pair = c.execute(
            "SELECT pair, "
            "SUM(CASE WHEN outcome IN ('WIN_TP1','WIN_TP2') THEN 1 ELSE 0 END) as wins, "
            "SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses, "
            "COUNT(*) as total "
            "FROM trades WHERE outcome != 'OPEN' GROUP BY pair"
        ).fetchall()

    win_rate = (wins / closed * 100) if closed else 0.0
    return {
        "total_trades": total,
        "open_trades": total - closed,
        "closed_trades": closed,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(win_rate, 1),
        "avg_rr_realized": round(avg_rr, 2),
        "by_pair": [
            {
                "pair": row["pair"],
                "wins": row["wins"],
                "losses": row["losses"],
                "total": row["total"],
                "win_rate_pct": round(row["wins"] / row["total"] * 100, 1) if row["total"] else 0.0,
            }
            for row in by_pair
        ],
    }


def get_recent_trades(limit: int = 50) -> list[dict]:
    _init_schema()
    with _conn() as c:
        cur = c.execute(
            "SELECT id, pair, direction, entry_price, stop_loss, take_profit_1, "
            "take_profit_2, outcome, exit_price, rr_realized, emitted_at, checked_at "
            "FROM trades ORDER BY emitted_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]
