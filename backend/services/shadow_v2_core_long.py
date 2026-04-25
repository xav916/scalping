"""Phase 4 — Shadow log V2_CORE_LONG XAU H4 (et XAG H4 secondaire).

Système recherche validé J1 (cf docs/superpowers/journal/INDEX.md exp 1-13) :
  - Sharpe annualisé 1.59 sur 24 mois backtest
  - maxDD 20%
  - Robuste cross-régime (PF 1.60 baseline 2023-24, 1.81 sur 2025-26)

Cette branche est en LECTURE SEULE :
  - Détecte les setups H4 V2_CORE_LONG via aggrégation H1 → H4
  - Persiste en DB pour observation post-hoc
  - **NE TOUCHE PAS** au scoring V1 ni à l'auto-exec démo Pepperstone

Spec : docs/superpowers/specs/2026-04-25-phase4-shadow-log-spec.md
"""
from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.models.schemas import Candle, TradeDirection
from backend.services.pattern_detector import calculate_trade_setup, detect_patterns

logger = logging.getLogger(__name__)


# ─── Configuration ──────────────────────────────────────────────────────────

# Paires à observer en shadow log (validées par recherche J1)
SHADOW_PAIRS: list[str] = ["XAU/USD", "XAG/USD"]

# Patterns retenus pour V2_CORE_LONG (apprentissage exp #2 + #3 + #4)
# Tous LONG only — les SHORTs sur XAG sont conditionnels au cycle (exp #11)
CORE_LONG_PATTERNS: set[str] = {"momentum_up", "engulfing_bullish", "breakout_up"}

# Sizing virtuel par défaut Phase 4 (prudence vs 1% backtest)
DEFAULT_CAPITAL_EUR: float = 10_000.0
DEFAULT_RISK_PCT: float = 0.005  # 0.5%

# DB partagée avec trade_log_service / users_service
DB_PATH = Path("/app/data/trades.db") if Path("/app").exists() else Path("trades.db")


# ─── Schéma DB ──────────────────────────────────────────────────────────────


def ensure_schema() -> None:
    """Crée la table shadow_setups si absente. Idempotent."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS shadow_setups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                detected_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                cycle_at TIMESTAMP NOT NULL,
                bar_timestamp TIMESTAMP NOT NULL,
                system_id TEXT NOT NULL,
                pair TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                direction TEXT NOT NULL,
                pattern TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit_1 REAL NOT NULL,
                take_profit_2 REAL,
                risk_pct REAL NOT NULL,
                rr REAL NOT NULL,
                sizing_capital_eur REAL NOT NULL DEFAULT 10000,
                sizing_risk_pct REAL NOT NULL DEFAULT 0.005,
                sizing_position_eur REAL NOT NULL,
                sizing_max_loss_eur REAL NOT NULL,
                macro_features_json TEXT,
                outcome TEXT,
                exit_at TIMESTAMP,
                exit_price REAL,
                pnl_pct_net REAL,
                pnl_eur REAL,
                UNIQUE (system_id, bar_timestamp)
            )
        """)
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_shadow_setups_pair_time "
            "ON shadow_setups (pair, bar_timestamp DESC)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_shadow_setups_system "
            "ON shadow_setups (system_id)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_shadow_setups_outcome "
            "ON shadow_setups (outcome)"
        )


# ─── Aggrégation H1 → H4 ────────────────────────────────────────────────────


def aggregate_to_h4(candles_1h: list[Candle]) -> list[Candle]:
    """Aggrège des bougies H1 en bougies H4 alignées 00/04/08/12/16/20 UTC.

    Méthode identique à scripts/research/track_a_backtest.aggregate_to_h4 :
    - timestamp bucket = floor(hour / 4) * 4
    - open = première candle, close = dernière, high = max, low = min
    - volumes sommés

    Les buckets non-fermés (4 H1 manquants) sont **exclus** pour éviter de
    déclencher un setup sur un H4 partiel.
    """
    if not candles_1h:
        return []

    buckets: dict[datetime, list[Candle]] = defaultdict(list)
    for c in candles_1h:
        bucket_hour = (c.timestamp.hour // 4) * 4
        bucket_ts = c.timestamp.replace(hour=bucket_hour, minute=0, second=0, microsecond=0)
        buckets[bucket_ts].append(c)

    h4_candles: list[Candle] = []
    for bucket_ts in sorted(buckets.keys()):
        bucket = sorted(buckets[bucket_ts], key=lambda x: x.timestamp)
        if len(bucket) < 4:
            # Bar H4 partiel : skipper pour éviter de déclencher un setup
            # sur des données incomplètes (live le bar courant n'est pas
            # encore fermé)
            continue
        h4_candles.append(Candle(
            timestamp=bucket_ts,
            open=bucket[0].open,
            high=max(c.high for c in bucket),
            low=min(c.low for c in bucket),
            close=bucket[-1].close,
            volume=sum(c.volume for c in bucket),
        ))
    return h4_candles


# ─── Détection + persistence ────────────────────────────────────────────────


def _persist_setup(
    setup,
    pair: str,
    pattern_name: str,
    bar_timestamp: datetime,
    cycle_at: datetime,
    macro_features: dict | None = None,
) -> bool:
    """Insert idempotent (UNIQUE system_id, bar_timestamp). Retourne True si nouveau."""
    system_id = f"V2_CORE_LONG_{pair.replace('/', '')}_4H"
    risk = abs(setup.entry_price - setup.stop_loss)
    risk_pct = risk / setup.entry_price if setup.entry_price > 0 else 0
    if risk_pct <= 0:
        logger.debug(f"shadow: setup avec risk_pct invalide, skip ({pair} {bar_timestamp})")
        return False
    reward = abs(setup.take_profit_1 - setup.entry_price)
    rr = reward / risk if risk > 0 else 0

    sizing_max_loss_eur = DEFAULT_CAPITAL_EUR * DEFAULT_RISK_PCT
    sizing_position_eur = sizing_max_loss_eur / risk_pct

    macro_json = json.dumps(macro_features) if macro_features else None

    with sqlite3.connect(DB_PATH) as c:
        try:
            c.execute(
                """
                INSERT INTO shadow_setups (
                    cycle_at, bar_timestamp, system_id, pair, timeframe,
                    direction, pattern, entry_price, stop_loss,
                    take_profit_1, take_profit_2, risk_pct, rr,
                    sizing_capital_eur, sizing_risk_pct,
                    sizing_position_eur, sizing_max_loss_eur,
                    macro_features_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cycle_at.isoformat(), bar_timestamp.isoformat(),
                    system_id, pair, "4h",
                    setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction),
                    pattern_name,
                    setup.entry_price, setup.stop_loss,
                    setup.take_profit_1,
                    getattr(setup, "take_profit_2", None),
                    risk_pct, rr,
                    DEFAULT_CAPITAL_EUR, DEFAULT_RISK_PCT,
                    sizing_position_eur, sizing_max_loss_eur,
                    macro_json,
                ),
            )
            return True
        except sqlite3.IntegrityError:
            # Setup déjà loggé pour ce (system_id, bar_timestamp) — normal,
            # le scheduler tourne toutes les 5 min, on revoit le même bar H4
            return False


async def run_shadow_log(
    h1_candles: dict[str, list[Candle]],
    cycle_at: datetime | None = None,
) -> dict[str, int]:
    """Détecte + persiste les setups V2_CORE_LONG sur les SHADOW_PAIRS.

    Args:
        h1_candles: dict {pair: list[Candle 1h]} fourni par le scheduler V1
        cycle_at: timestamp du cycle (défaut: now UTC)

    Returns:
        dict {pair: n_new_setups} pour observabilité

    Cette fonction est conçue pour être appelée depuis run_analysis_cycle
    avec try/except — si elle plante, le cycle V1 doit continuer.
    """
    ensure_schema()
    cycle_at = cycle_at or datetime.now(timezone.utc)

    counts: dict[str, int] = {}
    for pair in SHADOW_PAIRS:
        h1 = h1_candles.get(pair, [])
        if len(h1) < 30:
            counts[pair] = 0
            continue

        h4 = aggregate_to_h4(h1)
        if len(h4) < 30:
            counts[pair] = 0
            continue

        n_new = 0
        # Détection sur le DERNIER bar H4 fermé uniquement (pas la séquence
        # entière — ça créerait des doublons à chaque cycle)
        last_bar_ts = h4[-1].timestamp
        patterns = detect_patterns(h4, pair)

        for pattern in patterns:
            pattern_name = pattern.pattern.value if hasattr(pattern.pattern, "value") else str(pattern.pattern)
            if pattern_name not in CORE_LONG_PATTERNS:
                continue

            setup = calculate_trade_setup(pair, pattern, h4)
            if setup is None:
                continue
            if setup.direction != TradeDirection.BUY:
                continue

            # Snapshot macro features pour analyse post-hoc
            macro_features = None
            try:
                from backend.services.macro_data import get_macro_features_at
                macro_features = get_macro_features_at(last_bar_ts)
            except Exception as e:
                logger.debug(f"shadow: macro features fetch failed: {e}")

            if _persist_setup(
                setup, pair, pattern_name, last_bar_ts, cycle_at,
                macro_features=macro_features,
            ):
                n_new += 1
                logger.info(
                    f"shadow: nouveau setup V2_CORE_LONG {pair} 4H "
                    f"pattern={pattern_name} entry={setup.entry_price:.4f} "
                    f"SL={setup.stop_loss:.4f} TP1={setup.take_profit_1:.4f}"
                )

        counts[pair] = n_new

    return counts


# ─── Lookups ────────────────────────────────────────────────────────────────


def list_setups(
    since: datetime | None = None,
    until: datetime | None = None,
    system_id: str | None = None,
    outcome: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Liste les shadow setups avec filtres optionnels."""
    ensure_schema()
    sql = "SELECT * FROM shadow_setups WHERE 1=1"
    args: list[Any] = []
    if since:
        sql += " AND bar_timestamp >= ?"
        args.append(since.isoformat())
    if until:
        sql += " AND bar_timestamp <= ?"
        args.append(until.isoformat())
    if system_id:
        sql += " AND system_id = ?"
        args.append(system_id)
    if outcome is not None:
        if outcome == "pending":
            sql += " AND outcome IS NULL"
        else:
            sql += " AND outcome = ?"
            args.append(outcome)
    sql += " ORDER BY bar_timestamp DESC LIMIT ?"
    args.append(limit)

    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def summary() -> dict[str, Any]:
    """KPIs synthétiques sur les shadow setups."""
    ensure_schema()
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        # Counts par système
        rows = c.execute("""
            SELECT system_id,
                   COUNT(*) as n_total,
                   SUM(CASE WHEN outcome IS NULL THEN 1 ELSE 0 END) as n_pending,
                   SUM(CASE WHEN outcome = 'TP1' THEN 1 ELSE 0 END) as n_tp1,
                   SUM(CASE WHEN outcome = 'SL' THEN 1 ELSE 0 END) as n_sl,
                   SUM(CASE WHEN outcome = 'TIMEOUT' THEN 1 ELSE 0 END) as n_timeout,
                   SUM(CASE WHEN pnl_eur > 0 THEN pnl_eur ELSE 0 END) as gross_win_eur,
                   ABS(SUM(CASE WHEN pnl_eur < 0 THEN pnl_eur ELSE 0 END)) as gross_loss_eur,
                   SUM(pnl_eur) as net_pnl_eur,
                   MIN(bar_timestamp) as first_bar,
                   MAX(bar_timestamp) as last_bar
              FROM shadow_setups
             GROUP BY system_id
        """).fetchall()

    out_systems = []
    for r in rows:
        d = dict(r)
        d["pf"] = (d["gross_win_eur"] / d["gross_loss_eur"]) if d["gross_loss_eur"] else None
        d["wr_pct"] = (d["n_tp1"] / max(d["n_tp1"] + d["n_sl"], 1)) * 100 if (d["n_tp1"] + d["n_sl"]) > 0 else None
        out_systems.append(d)

    return {"systems": out_systems}
