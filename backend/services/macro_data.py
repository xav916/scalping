"""Service Track B — fetch + cache + features macro/cross-asset.

Sources : Yahoo Finance (gratuit, 30+ ans d'history) via httpx direct.
Cache : SQLite local `data/macro.db` (peu volumineux, regenerable).

Symboles supportés :
    vix → ^VIX (CBOE Volatility Index, daily)
    dxy → DX-Y.NYB (US Dollar Index, daily)
    spx → ^GSPC (S&P 500, daily)
    tnx → ^TNX (US 10Y Treasury yield, daily)
    btc → BTC-USD (Bitcoin USD, daily — doublon BT cross-asset)

API principale :
    fetch_history(symbol, start_date, end_date)  → écrit en DB
    get_series(symbol, start, end)               → liste {date, close, ...}
    get_macro_features_at(timestamp)             → dict[str, float]

Pas de look-ahead : `get_macro_features_at(T)` ne retourne que des
observations daily *strictement antérieures* à la date de T.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx


# ─── Configuration ──────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "macro.db"

YAHOO_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"

# Mapping symbole logique → ticker Yahoo
SYMBOL_MAP: dict[str, str] = {
    "vix": "^VIX",
    "dxy": "DX-Y.NYB",
    "spx": "^GSPC",
    "tnx": "^TNX",
    "btc": "BTC-USD",
}

USER_AGENT = "Mozilla/5.0 (compatible; ScalpingResearch/1.0)"


# ─── Schéma DB ──────────────────────────────────────────────────────────────


def ensure_schema() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS macro_daily (
                symbol TEXT NOT NULL,
                date TEXT NOT NULL,           -- YYYY-MM-DD UTC
                open REAL,
                high REAL,
                low REAL,
                close REAL NOT NULL,
                volume INTEGER,
                PRIMARY KEY (symbol, date)
            )
        """)
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_macro_daily_date ON macro_daily(date)"
        )


# ─── Fetch Yahoo ────────────────────────────────────────────────────────────


def _to_unix_seconds(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def fetch_yahoo_daily(
    yahoo_ticker: str,
    start_date: date,
    end_date: date,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """Fetch daily OHLCV depuis Yahoo. Retourne list[dict] dans l'ordre temporel.

    Yahoo Finance v8 chart endpoint, period1/period2 en epoch seconds UTC.
    """
    url = f"{YAHOO_BASE}/{yahoo_ticker}"
    params = {
        "period1": str(_to_unix_seconds(start_date)),
        "period2": str(_to_unix_seconds(end_date)),
        "interval": "1d",
        "events": "history",
        "includeAdjustedClose": "true",
    }
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=timeout) as client:
        r = client.get(url, params=params, headers=headers)
        r.raise_for_status()
        data = r.json()

    result = data.get("chart", {}).get("result")
    if not result:
        raise RuntimeError(f"Yahoo: no chart result for {yahoo_ticker}: {data}")
    res = result[0]

    timestamps = res.get("timestamp", []) or []
    quote = (res.get("indicators", {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    obs: list[dict[str, Any]] = []
    for i, ts in enumerate(timestamps):
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        c_val = closes[i] if i < len(closes) else None
        if c_val is None:
            continue  # bar incomplet (holiday partiel)
        obs.append({
            "date": dt.isoformat(),
            "open": opens[i] if i < len(opens) else None,
            "high": highs[i] if i < len(highs) else None,
            "low": lows[i] if i < len(lows) else None,
            "close": c_val,
            "volume": int(volumes[i]) if i < len(volumes) and volumes[i] is not None else 0,
        })
    return obs


def upsert_observations(symbol: str, observations: list[dict[str, Any]]) -> int:
    """Insère/maj les obs daily. Retourne le nombre de lignes écrites."""
    if not observations:
        return 0
    ensure_schema()
    n = 0
    with sqlite3.connect(DB_PATH) as c:
        for obs in observations:
            c.execute(
                """
                INSERT INTO macro_daily (symbol, date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, date) DO UPDATE SET
                    open=excluded.open, high=excluded.high, low=excluded.low,
                    close=excluded.close, volume=excluded.volume
                """,
                (symbol, obs["date"], obs.get("open"), obs.get("high"),
                 obs.get("low"), obs["close"], obs.get("volume", 0)),
            )
            n += 1
    return n


def fetch_history(
    symbol: str,
    start_date: date,
    end_date: date,
) -> int:
    """Fetch + cache. Retourne le nombre d'obs écrites."""
    if symbol not in SYMBOL_MAP:
        raise ValueError(f"Unknown symbol: {symbol}. Supported: {list(SYMBOL_MAP)}")
    obs = fetch_yahoo_daily(SYMBOL_MAP[symbol], start_date, end_date)
    return upsert_observations(symbol, obs)


# ─── Lookups ────────────────────────────────────────────────────────────────


def get_series(
    symbol: str,
    start: date | None = None,
    end: date | None = None,
) -> list[dict[str, Any]]:
    """Charge le cache local pour symbol sur [start, end]. Trié temporellement."""
    ensure_schema()
    sql = "SELECT date, open, high, low, close, volume FROM macro_daily WHERE symbol = ?"
    args: list[Any] = [symbol]
    if start:
        sql += " AND date >= ?"
        args.append(start.isoformat())
    if end:
        sql += " AND date <= ?"
        args.append(end.isoformat())
    sql += " ORDER BY date ASC"
    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute(sql, tuple(args)).fetchall()
    return [
        {"date": r[0], "open": r[1], "high": r[2], "low": r[3],
         "close": r[4], "volume": r[5]}
        for r in rows
    ]


def get_close_at_or_before(symbol: str, target_date: date) -> dict[str, Any] | None:
    """Retourne le close le plus récent **strictement antérieur ou égal** à target_date.

    Pour `get_macro_features_at(T)` : on demande get_close_at_or_before(symbol, T-1)
    pour éviter tout look-ahead (la daily de T est connue seulement après close du jour).
    """
    ensure_schema()
    with sqlite3.connect(DB_PATH) as c:
        row = c.execute(
            """
            SELECT date, close FROM macro_daily
             WHERE symbol = ? AND date <= ?
             ORDER BY date DESC
             LIMIT 1
            """,
            (symbol, target_date.isoformat()),
        ).fetchone()
    if not row:
        return None
    return {"date": row[0], "close": row[1]}


# ─── Features dérivées ──────────────────────────────────────────────────────


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _vix_regime(vix_level: float) -> str:
    if vix_level < 15:
        return "low"
    if vix_level < 25:
        return "normal"
    return "high"


def get_macro_features_at(ts: datetime) -> dict[str, Any]:
    """Retourne les features macro alignées au timestamp T, sans look-ahead.

    Rule : on prend la dernière daily connue **strictement antérieure** à la
    date de T (T-1d ou plus tôt si holiday). Pour `vix_delta_1d` etc, on prend
    le close du jour précédent encore.

    Retourne un dict avec, pour chaque symbol présent dans le cache :
        {symbol}_level, {symbol}_delta_1d, {symbol}_dist_sma50, {symbol}_return_5d
    + des features synthétiques :
        vix_regime ∈ {"low","normal","high"}
    + des dates d'asof pour traçabilité.
    """
    target_date = ts.date() - timedelta(days=1)  # asof T-1d

    out: dict[str, Any] = {"asof_date": target_date.isoformat()}

    for symbol in SYMBOL_MAP:
        # Charger les 90 dernières observations avant target_date (besoin SMA50 + return_5d)
        start_window = target_date - timedelta(days=120)
        series = get_series(symbol, start=start_window, end=target_date)
        if not series:
            continue

        closes = [r["close"] for r in series]
        last = series[-1]
        out[f"{symbol}_level"] = last["close"]
        out[f"{symbol}_asof"] = last["date"]

        # delta 1d
        if len(closes) >= 2:
            prev = closes[-2]
            if prev:
                out[f"{symbol}_delta_1d"] = (closes[-1] - prev) / prev * 100  # en %
        # return 5d
        if len(closes) >= 6:
            base = closes[-6]
            if base:
                out[f"{symbol}_return_5d"] = (closes[-1] - base) / base * 100
        # dist SMA50 (en %)
        sma50 = _sma(closes, 50)
        if sma50 and sma50 > 0:
            out[f"{symbol}_dist_sma50"] = (closes[-1] - sma50) / sma50 * 100

    # Régime VIX (string discrétisé)
    if "vix_level" in out:
        out["vix_regime"] = _vix_regime(out["vix_level"])

    return out


# ─── CLI ────────────────────────────────────────────────────────────────────


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Track B macro_data — fetch & test")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser("fetch", help="Fetch + cache daily history")
    p_fetch.add_argument("--symbol", choices=list(SYMBOL_MAP), required=True)
    p_fetch.add_argument("--start", default="2020-01-01")
    p_fetch.add_argument("--end", default=None)

    p_fetch_all = sub.add_parser("fetch-all", help="Fetch les 5 symboles")
    p_fetch_all.add_argument("--start", default="2020-01-01")
    p_fetch_all.add_argument("--end", default=None)

    p_features = sub.add_parser("features", help="Test get_macro_features_at")
    p_features.add_argument("--at", default=None,
                             help="Timestamp ISO (défaut now UTC)")

    p_summary = sub.add_parser("summary", help="Stats du cache local")

    args = p.parse_args()

    if args.cmd in ("fetch", "fetch-all"):
        end_d = date.fromisoformat(args.end) if args.end else date.today()
        start_d = date.fromisoformat(args.start)
        symbols = [args.symbol] if args.cmd == "fetch" else list(SYMBOL_MAP)
        for sym in symbols:
            try:
                n = fetch_history(sym, start_d, end_d)
                print(f"{sym:>5}: {n} obs écrites ({SYMBOL_MAP[sym]} {start_d}→{end_d})")
            except Exception as e:
                print(f"{sym:>5}: ERROR — {e}")

    elif args.cmd == "features":
        ts = datetime.fromisoformat(args.at) if args.at else datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        feats = get_macro_features_at(ts)
        print(f"Features at {ts.isoformat()}:")
        for k, v in feats.items():
            if isinstance(v, float):
                print(f"  {k:<22} {v:>10.3f}")
            else:
                print(f"  {k:<22} {v}")

    elif args.cmd == "summary":
        ensure_schema()
        with sqlite3.connect(DB_PATH) as c:
            rows = c.execute("""
                SELECT symbol, COUNT(*), MIN(date), MAX(date)
                  FROM macro_daily GROUP BY symbol ORDER BY symbol
            """).fetchall()
        print(f"{'symbol':<6} {'n':>6}  {'min':<12} {'max':<12}")
        for r in rows:
            print(f"{r[0]:<6} {r[1]:>6}  {r[2]:<12} {r[3]:<12}")


if __name__ == "__main__":
    main()
