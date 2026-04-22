#!/usr/bin/env python3
"""Fetch historique OHLC pour le moteur de backtest.

Pull depuis Twelve Data par fenêtres glissantes, respecte le rate limit
Grow (55 req/min), dédoublonne via PK composite. Resume-friendly : on
peut interrompre/relancer, les candles déjà en base sont skipped.

Usage typique (EC2) :
    cd /home/ec2-user/scalping
    # Dry-run 1 pair pour valider la connexion API
    sudo python3 scripts/fetch_historical_backtest.py \
        --pair EUR/USD --interval 1h --days 30 --dry-run

    # Full fetch : 16 pairs × 3 ans × (1h + 5min)
    sudo python3 scripts/fetch_historical_backtest.py --full
"""
from __future__ import annotations
import argparse
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

# Chemin par défaut (EC2). Override possible via --db
DEFAULT_DB = "/opt/scalping/data/backtest_candles.db"

# Fichier env du système live (charge TWELVEDATA_API_KEY + WATCHED_PAIRS)
DEFAULT_ENV = "/opt/scalping/.env"

TWELVEDATA_BASE = "https://api.twelvedata.com"

# Twelve Data Grow : 55 req/min. On se lock à 50/min pour marge.
RATE_LIMIT_PER_MIN = 50
SLEEP_BETWEEN_REQ = 60.0 / RATE_LIMIT_PER_MIN  # ~1.2s

# Taille max d'une requête Twelve Data
MAX_CANDLES_PER_REQUEST = 5000

# Intervalles qu'on fetch par défaut. 1h = scoring principal, 5min = simulation
# intra-bar précise pour SL/TP hit detection.
DEFAULT_INTERVALS = ["1h", "5min"]

# Mapping pair → symbol Twelve Data (copié de config/settings.py pour éviter
# le coupling avec le runtime Python du container)
DEFAULT_SYMBOL_MAP = {
    "SPX": "SPX",
    "NDX": "NDX",
    "WTI": "WTI/USD",
}


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fetch_hist")


# ─── Config loader ──────────────────────────────────────────────────────────


def load_env(env_path: str) -> dict[str, str]:
    """Lit un fichier .env sans dépendance externe. Gère VAR=val, quotes,
    lignes vides/commentaires."""
    result: dict[str, str] = {}
    if not os.path.exists(env_path):
        return result
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            val = val.strip()
            # Retire quotes si présentes
            if (val.startswith('"') and val.endswith('"')) or (
                val.startswith("'") and val.endswith("'")
            ):
                val = val[1:-1]
            result[key.strip()] = val
    return result


# ─── Schema DB ──────────────────────────────────────────────────────────────


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candles_historical (
            pair      TEXT NOT NULL,
            interval  TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            open      REAL NOT NULL,
            high      REAL NOT NULL,
            low       REAL NOT NULL,
            close     REAL NOT NULL,
            volume    REAL,
            PRIMARY KEY (pair, interval, timestamp)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ch_pair_interval "
        "ON candles_historical(pair, interval)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ch_timestamp "
        "ON candles_historical(timestamp)"
    )


# ─── Window planner ─────────────────────────────────────────────────────────


def _interval_to_minutes(interval: str) -> int:
    mapping = {"1min": 1, "5min": 5, "15min": 15, "30min": 30,
               "1h": 60, "2h": 120, "4h": 240, "1day": 1440}
    if interval not in mapping:
        raise ValueError(f"interval non supporté: {interval}")
    return mapping[interval]


def plan_windows(
    start: datetime, end: datetime, interval: str
) -> list[tuple[datetime, datetime]]:
    """Découpe [start, end] en fenêtres de <= MAX_CANDLES_PER_REQUEST bougies."""
    minutes = _interval_to_minutes(interval)
    max_span_minutes = MAX_CANDLES_PER_REQUEST * minutes
    windows = []
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(minutes=max_span_minutes), end)
        windows.append((cur, nxt))
        cur = nxt
    return windows


# ─── Twelve Data fetch ──────────────────────────────────────────────────────


def symbol_for_pair(pair: str, sym_map: dict[str, str]) -> str:
    """Map interne pair → symbole Twelve Data."""
    return sym_map.get(pair, pair)


def fetch_window(
    pair: str,
    interval: str,
    start: datetime,
    end: datetime,
    api_key: str,
    sym_map: dict[str, str],
    timeout: float = 30.0,
) -> list[dict]:
    """Tire une fenêtre de candles. Retourne liste de dicts normalisés."""
    symbol = symbol_for_pair(pair, sym_map)
    params = {
        "symbol": symbol,
        "interval": interval,
        "start_date": start.strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": end.strftime("%Y-%m-%d %H:%M:%S"),
        "outputsize": MAX_CANDLES_PER_REQUEST,
        "timezone": "UTC",
        "apikey": api_key,
    }
    with httpx.Client(timeout=timeout) as client:
        r = client.get(f"{TWELVEDATA_BASE}/time_series", params=params)
    if r.status_code != 200:
        log.warning(f"{pair} {interval} {start}→{end}: HTTP {r.status_code} {r.text[:120]}")
        return []
    data = r.json()
    if "values" not in data:
        code = data.get("code") or data.get("status")
        msg = data.get("message", "")
        log.warning(f"{pair} {interval} {start}→{end}: {code} {msg[:120]}")
        return []
    out: list[dict] = []
    for item in data["values"]:
        try:
            out.append({
                "pair": pair,
                "interval": interval,
                "timestamp": item["datetime"],
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
                "volume": float(item.get("volume") or 0),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return out


# ─── Persistence ────────────────────────────────────────────────────────────


def insert_candles(conn: sqlite3.Connection, candles: list[dict]) -> int:
    """INSERT OR IGNORE pour dédup idempotent. Retourne nb inserts effectifs."""
    if not candles:
        return 0
    before = conn.execute("SELECT COUNT(*) FROM candles_historical").fetchone()[0]
    conn.executemany(
        """
        INSERT OR IGNORE INTO candles_historical
            (pair, interval, timestamp, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [(c["pair"], c["interval"], c["timestamp"], c["open"], c["high"],
          c["low"], c["close"], c["volume"]) for c in candles],
    )
    conn.commit()
    after = conn.execute("SELECT COUNT(*) FROM candles_historical").fetchone()[0]
    return after - before


def existing_range(
    conn: sqlite3.Connection, pair: str, interval: str
) -> tuple[str | None, str | None, int]:
    """Retourne (min_ts, max_ts, count) déjà en base pour cette pair/interval."""
    row = conn.execute(
        """
        SELECT MIN(timestamp), MAX(timestamp), COUNT(*)
          FROM candles_historical
         WHERE pair = ? AND interval = ?
        """,
        (pair, interval),
    ).fetchone()
    return row[0], row[1], row[2]


# ─── Orchestration ──────────────────────────────────────────────────────────


def fetch_pair_interval(
    conn: sqlite3.Connection,
    pair: str,
    interval: str,
    start: datetime,
    end: datetime,
    api_key: str,
    sym_map: dict[str, str],
    dry_run: bool,
) -> tuple[int, int]:
    """Tire pair × interval sur la plage [start, end]. Retourne (requêtes, nouvelles lignes)."""
    min_ts, max_ts, count = existing_range(conn, pair, interval)
    log.info(f"[{pair:8s} {interval:5s}] existant: {count} candles "
             f"({min_ts}..{max_ts})")

    windows = plan_windows(start, end, interval)
    log.info(f"[{pair:8s} {interval:5s}] {len(windows)} fenêtres planifiées")

    requests = 0
    inserted = 0
    for win_start, win_end in windows:
        if dry_run:
            log.info(f"[DRY] {pair} {interval} {win_start.date()} → {win_end.date()}")
            requests += 1
            continue

        t0 = time.time()
        candles = fetch_window(pair, interval, win_start, win_end, api_key, sym_map)
        dt = time.time() - t0
        requests += 1

        n = insert_candles(conn, candles)
        inserted += n
        log.info(
            f"[{pair:8s} {interval:5s}] {win_start.date()} → {win_end.date()}: "
            f"+{n}/{len(candles)} en {dt:.1f}s"
        )

        # Rate limit
        if SLEEP_BETWEEN_REQ > 0:
            time.sleep(SLEEP_BETWEEN_REQ)

    return requests, inserted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB, help=f"chemin DB (défaut {DEFAULT_DB})")
    ap.add_argument("--env", default=DEFAULT_ENV, help=f"fichier .env (défaut {DEFAULT_ENV})")
    ap.add_argument("--days", type=int, default=365 * 3, help="nb de jours d'historique (défaut 3 ans)")
    ap.add_argument("--interval", help="un seul intervalle (sinon tous les default)")
    ap.add_argument("--pair", help="une seule pair (sinon WATCHED_PAIRS)")
    ap.add_argument("--full", action="store_true", help="full fetch 16 pairs × 3 ans × tous intervals")
    ap.add_argument("--dry-run", action="store_true", help="plan les requêtes, ne fetch rien")
    args = ap.parse_args()

    env = load_env(args.env)
    api_key = env.get("TWELVEDATA_API_KEY", "")
    if not api_key and not args.dry_run:
        log.error(f"TWELVEDATA_API_KEY absente de {args.env}")
        sys.exit(1)

    # Pairs
    if args.pair:
        pairs = [args.pair]
    else:
        watched = env.get("WATCHED_PAIRS", "")
        pairs = [p.strip() for p in watched.split(",") if p.strip()]
        if not pairs:
            pairs = ["EUR/USD"]  # fallback
    if not args.full and not args.pair:
        log.warning("Ni --full ni --pair fourni : utilise WATCHED_PAIRS depuis .env")

    # Symbol map (exotiques éventuels)
    sym_map_raw = env.get("MT5_SYMBOL_MAP", "") or ""
    # MT5_SYMBOL_MAP est pour MT5 broker mapping, pas pour Twelve Data.
    # Pour Twelve Data on a seulement besoin de gérer les symboles "spéciaux"
    # comme SPX/NDX/WTI qui ne sont pas en format pair A/B
    sym_map = dict(DEFAULT_SYMBOL_MAP)

    # Intervals
    intervals = [args.interval] if args.interval else DEFAULT_INTERVALS

    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=args.days)

    log.info(f"Fenêtre: {start} → {end} ({args.days} jours)")
    log.info(f"Pairs ({len(pairs)}): {pairs}")
    log.info(f"Intervals: {intervals}")
    log.info(f"DB: {args.db}")
    log.info(f"Dry-run: {args.dry_run}")

    conn = sqlite3.connect(args.db)
    ensure_schema(conn)

    total_req = 0
    total_ins = 0
    for pair in pairs:
        for interval in intervals:
            try:
                req, ins = fetch_pair_interval(
                    conn, pair, interval, start, end, api_key, sym_map, args.dry_run
                )
                total_req += req
                total_ins += ins
            except Exception:
                log.exception(f"[{pair} {interval}] crash")

    conn.close()

    log.info(f"═════ TERMINÉ ═════")
    log.info(f"Requêtes : {total_req}")
    log.info(f"Nouvelles candles insérées : {total_ins}")


if __name__ == "__main__":
    main()
