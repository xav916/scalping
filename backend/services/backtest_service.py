"""Backtest des signaux emis : stocke chaque trade setup et son issue.

Utilise SQLite pour la persistance (fichier sqlite unique, pas de serveur).
Chaque setup emis est enregistre avec entry/SL/TP1/TP2. Un job periodique
verifie le prix courant et marque l'issue : WIN (TP1 ou TP2 atteint), LOSS
(SL atteint), ou OPEN (en attente).

Table `signals` (archive ML-ready)
- Contient TOUS les signaux generes (y compris rejetes par le filtre de
  confiance), avec metadata riche : confidence_factors, pattern, volatilite,
  tendance, contexte macro, events proches, verdict.
- Chaque ligne a un `id` auto-incremente qui sert de cle vers le trade
  execute correspondant (personal_trades.signal_id).
- Sert de dataset d'entrainement pour un futur modele ML : "quels signaux
  gagnent / perdent selon leurs features ?"

Table `trades` (backtest outcome)
- Contient les setups haute-confiance dont on suit l'issue jusqu'a SL/TP.
- Deux vies distinctes : un setup peut etre archive dans `signals` sans
  etre backteste si son verdict est SKIP.

Statistiques exposees : taux de reussite, R:R moyen, PnL cumule.
"""

import asyncio
import json
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

            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                emitted_at TEXT NOT NULL,
                pair TEXT NOT NULL,
                direction TEXT NOT NULL,
                asset_class TEXT,
                signal_strength TEXT,
                confidence_score REAL,
                verdict_action TEXT,
                entry_price REAL,
                stop_loss REAL,
                take_profit_1 REAL,
                take_profit_2 REAL,
                risk_pips REAL,
                reward_pips_1 REAL,
                risk_reward_1 REAL,
                pattern TEXT,
                pattern_confidence REAL,
                volatility_level TEXT,
                volatility_ratio REAL,
                trend_direction TEXT,
                trend_strength REAL,
                confidence_factors TEXT,
                verdict_reasons TEXT,
                verdict_warnings TEXT,
                verdict_blockers TEXT,
                macro_context TEXT,
                nearby_events TEXT,
                is_simulated INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_signals_emitted ON signals(emitted_at);
            CREATE INDEX IF NOT EXISTS idx_signals_pair_dir_emitted
                ON signals(pair, direction, emitted_at);
        """)


@contextmanager
def _conn():
    conn = sqlite3.connect(str(_DB_PATH), isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def record_signals(
    setups: list[TradeSetup],
    volatility_by_pair: dict | None = None,
    trend_by_pair: dict | None = None,
    events_by_currency: dict | None = None,
) -> None:
    """Archive chaque setup genere dans la table `signals` (ML-ready).

    Tous les setups sont persistes, y compris ceux que le filtre de
    confiance ou le verdict rejettera ensuite : c'est justement ces
    "faux negatifs potentiels" qu'on veut pouvoir etudier plus tard.

    La liaison signal -> trade execute est gere en aval via
    `find_signal_for_order` (matching pair + direction + entry_price dans
    une fenetre temporelle courte), ce qui evite de devoir propager un
    signal_id a travers le bridge MT5.

    Les parametres optionnels (vol/trend/events) permettent d'enrichir
    les features sans avoir a refaire les calculs cote scheduler.
    """
    _init_schema()
    from backend.services import macro_context_service

    macro_json: str | None = None
    snap = macro_context_service.get_macro_snapshot()
    if snap is not None and macro_context_service.is_fresh(snap.fetched_at):
        macro_json = json.dumps({
            "dxy": snap.dxy_direction.value,
            "spx": snap.spx_direction.value,
            "vix_level": snap.vix_level.value,
            "vix_value": snap.vix_value,
            "risk_regime": snap.risk_regime.value,
            "fetched_at": snap.fetched_at.isoformat(),
        })

    with _conn() as c:
        for s in setups:
            factors = [
                {"name": f.name, "score": f.score, "detail": f.detail}
                for f in (s.confidence_factors or [])
            ]
            vol = (volatility_by_pair or {}).get(s.pair)
            tr = (trend_by_pair or {}).get(s.pair)
            # Events pertinents : ceux sur la devise de base OU de cotation.
            nearby: list[dict] = []
            if events_by_currency:
                parts = s.pair.split("/") if "/" in s.pair else [s.pair]
                for ccy in parts:
                    for e in events_by_currency.get(ccy.upper(), []):
                        nearby.append({
                            "time": getattr(e, "time", None),
                            "currency": getattr(e, "currency", None),
                            "impact": (
                                e.impact.value if hasattr(e.impact, "value") else str(e.impact)
                            ) if hasattr(e, "impact") else None,
                            "name": getattr(e, "event_name", None),
                        })

            c.execute(
                """
                INSERT INTO signals (
                    emitted_at, pair, direction, asset_class, signal_strength,
                    confidence_score, verdict_action, entry_price, stop_loss,
                    take_profit_1, take_profit_2, risk_pips, reward_pips_1,
                    risk_reward_1, pattern, pattern_confidence,
                    volatility_level, volatility_ratio, trend_direction,
                    trend_strength, confidence_factors, verdict_reasons,
                    verdict_warnings, verdict_blockers, macro_context,
                    nearby_events, is_simulated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    s.pair,
                    s.direction.value,
                    getattr(s, "asset_class", None),
                    None,  # signal_strength : pose par detect_signals, non present ici
                    s.confidence_score,
                    getattr(s, "verdict_action", None),
                    s.entry_price,
                    s.stop_loss,
                    s.take_profit_1,
                    s.take_profit_2,
                    s.risk_pips,
                    s.reward_pips_1,
                    s.risk_reward_1,
                    s.pattern.pattern.value if s.pattern else None,
                    s.pattern.confidence if s.pattern else None,
                    vol.level.value if vol and hasattr(vol, "level") else None,
                    getattr(vol, "volatility_ratio", None),
                    tr.direction.value if tr and hasattr(tr, "direction") else None,
                    getattr(tr, "strength", None),
                    json.dumps(factors) if factors else None,
                    json.dumps(list(s.verdict_reasons or [])) or None,
                    json.dumps(list(s.verdict_warnings or [])) or None,
                    json.dumps(list(s.verdict_blockers or [])) or None,
                    macro_json,
                    json.dumps(nearby) if nearby else None,
                    1 if getattr(s, "is_simulated", False) else 0,
                ),
            )


def find_signal_for_order(
    pair: str,
    direction: str,
    entry_price: float,
    price_tolerance_pct: float = 0.1,
    within_minutes: int = 30,
) -> int | None:
    """Retrouve le signal_id le plus recent correspondant a un ordre execute.

    Matching : meme pair + direction, entry_price a +/- tolerance_pct pres,
    emis dans la fenetre temporelle donnee. Utilise par mt5_sync pour lier
    un fill bridge a son signal d'origine quand le comment du ticket ne le
    transporte pas."""
    _init_schema()
    if entry_price <= 0:
        return None
    from datetime import timedelta as _td

    tol = entry_price * (price_tolerance_pct / 100.0)
    low, high = entry_price - tol, entry_price + tol
    since = (datetime.now(timezone.utc) - _td(minutes=within_minutes)).isoformat()
    with _conn() as c:
        row = c.execute(
            """
            SELECT id FROM signals
             WHERE pair = ? AND direction = ?
               AND entry_price BETWEEN ? AND ?
               AND emitted_at >= ?
             ORDER BY emitted_at DESC
             LIMIT 1
            """,
            (pair, direction.lower(), low, high, since),
        ).fetchone()
    return row["id"] if row else None


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
