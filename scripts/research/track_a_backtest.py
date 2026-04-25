"""Track A — Backtest multi-timeframe (H1 / H4 / Daily) — Spike de phase 1.

Spec : `docs/superpowers/specs/2026-04-25-track-a-horizon-h4.md`
Hypothèse : l'edge sur retail forex existe à H4/Daily car le coût
spread/slippage est amorti sur des mouvements 5-10× plus larges.
Critère succès : PF ≥ 1.15 sur ≥1 paire×stratégie en H4 ou Daily,
avec coûts 0.02% et ≥ 50 trades.

Réutilise `_macro_veto_analysis/backtest_v2.py` comme baseline H1, et
étend avec :
  - aggregation locale H1 → H4 / Daily (pas de fetch Twelve Data, pour
    garantir que les ticks H1 et H4 dérivent strictement des mêmes prix
    historiques — la comparaison "edge à H1 vs H4" est ainsi non polluée
    par un feed différent)
  - argument --timeframe {1h,4h,1d}
  - timeout simulation forward scalé proportionnellement à la taille
    de bougie (24h pour H1, 96h pour H4, 240h pour Daily)

Usage :
    python scripts/research/track_a_backtest.py --timeframe 1h
    python scripts/research/track_a_backtest.py --timeframe 4h
    python scripts/research/track_a_backtest.py --timeframe 1d

Sortie : tableau comparant BASELINE / V2_LIGHT / V2_PATTERN / V2_FULL /
RB_DOWN_SELL avec n, win rate, PnL%, PF, max drawdown.

Coûts : 0.02% spread+slippage par défaut (réaliste retail forex sur
Pepperstone/IC Markets). Pour mesurer l'edge brut, passer --no-costs.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from backend.models.schemas import Candle, TradeDirection
from backend.services import backtest_engine as _bte
from backend.services.backtest_engine import simulate_trade_forward
from backend.services.pattern_detector import detect_patterns, calculate_trade_setup


CANDLES_DB = ROOT / "_macro_veto_analysis" / "backtest_candles.db"

# Fenêtre par défaut : 12 mois jusqu'à aujourd'hui
DEFAULT_START = datetime(2025, 4, 25, tzinfo=timezone.utc)
DEFAULT_END = datetime(2026, 4, 25, tzinfo=timezone.utc)

# Variables runtime modifiées par main() selon les args
START = DEFAULT_START
END = DEFAULT_END

PAIRS = [
    "AUD/USD", "BTC/USD", "ETH/USD", "EUR/GBP", "EUR/USD",
    "GBP/JPY", "GBP/USD", "USD/CAD", "USD/CHF", "USD/JPY",
    "XAG/USD", "XAU/USD",
]

# Forward window timeout par timeframe — proportionnel à la taille de bougie.
# Logique : à H1 on tient 24h (≈24 bougies). À H4 on tient ~24 bougies = 96h.
# À Daily on relâche un peu (10 bougies = 10 jours) pour rester dans la
# couverture 5min (qui démarre en 2023-04, la fenêtre 2025-2026 est OK).
TIMEOUT_HOURS_BY_TF = {
    "1h": 24,
    "4h": 96,    # 4 jours
    "1d": 240,   # 10 jours
}

# Dedup : 1 setup max par fenêtre temporelle de cette taille (pour ne pas
# enregistrer 5 setups consécutifs sur la même candle 4h ou daily).
DEDUP_HOURS_BY_TF = {
    "1h": 1.0,
    "4h": 4.0,
    "1d": 24.0,
}


def load_h1_candles(pair: str) -> list[Candle]:
    """Charge les candles 1h depuis la DB pour la fenêtre backtest."""
    with sqlite3.connect(CANDLES_DB) as c:
        rows = c.execute(
            """
            SELECT timestamp, open, high, low, close, volume
              FROM candles_historical
             WHERE pair = ? AND interval = '1h'
               AND timestamp >= ? AND timestamp <= ?
             ORDER BY timestamp
            """,
            (pair, START.strftime("%Y-%m-%d %H:%M:%S"),
             END.strftime("%Y-%m-%d %H:%M:%S")),
        ).fetchall()
    return [
        Candle(
            timestamp=datetime.fromisoformat(r[0]).replace(tzinfo=timezone.utc),
            open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5] or 0,
        )
        for r in rows
    ]


def load_5min_candles(pair: str) -> list[Candle]:
    """Charge les 5min pour la simulation forward. On charge avec une marge
    pour les timeouts longs (240h = 10j) en arrière de START et après END."""
    margin = timedelta(days=15)
    with sqlite3.connect(CANDLES_DB) as c:
        rows = c.execute(
            """
            SELECT timestamp, open, high, low, close, volume
              FROM candles_historical
             WHERE pair = ? AND interval = '5min'
               AND timestamp >= ? AND timestamp <= ?
             ORDER BY timestamp
            """,
            (pair,
             (START - margin).strftime("%Y-%m-%d %H:%M:%S"),
             (END + margin).strftime("%Y-%m-%d %H:%M:%S")),
        ).fetchall()
    return [
        Candle(
            timestamp=datetime.fromisoformat(r[0]).replace(tzinfo=timezone.utc),
            open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5] or 0,
        )
        for r in rows
    ]


def aggregate_to_h4(candles_1h: list[Candle]) -> list[Candle]:
    """Aggrège des bougies H1 en bougies H4 alignées 00/04/08/12/16/20 UTC.

    Méthode : group by (date, hour // 4). Pour chaque bucket :
    - timestamp = floor(hour / 4) * 4 (l'heure de début du bucket UTC)
    - open = open de la première candle H1 du bucket
    - close = close de la dernière candle H1 du bucket
    - high = max des high
    - low = min des low
    - volume = somme des volumes

    Les buckets incomplets (< 4 H1 candles) sont gardés tels quels — pour
    backtest c'est conservateur (pas de surestimation de range).
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
        h4_candles.append(Candle(
            timestamp=bucket_ts,
            open=bucket[0].open,
            high=max(c.high for c in bucket),
            low=min(c.low for c in bucket),
            close=bucket[-1].close,
            volume=sum(c.volume for c in bucket),
        ))
    return h4_candles


def aggregate_to_daily(candles_1h: list[Candle]) -> list[Candle]:
    """Aggrège des bougies H1 en bougies Daily alignées 00 UTC.

    Note : pour le forex, la "vraie" daily commence à 22 UTC (Sydney). On
    aligne ici 00 UTC pour simplicité ; ça décale la définition de la
    journée mais ne biaise pas la comparaison cross-paire.
    """
    if not candles_1h:
        return []

    buckets: dict[datetime, list[Candle]] = defaultdict(list)
    for c in candles_1h:
        bucket_ts = c.timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
        buckets[bucket_ts].append(c)

    d_candles: list[Candle] = []
    for bucket_ts in sorted(buckets.keys()):
        bucket = sorted(buckets[bucket_ts], key=lambda x: x.timestamp)
        d_candles.append(Candle(
            timestamp=bucket_ts,
            open=bucket[0].open,
            high=max(c.high for c in bucket),
            low=min(c.low for c in bucket),
            close=bucket[-1].close,
            volume=sum(c.volume for c in bucket),
        ))
    return d_candles


def get_signal_candles(candles_1h: list[Candle], timeframe: str) -> list[Candle]:
    """Retourne les candles utilisées pour la détection de pattern selon
    le timeframe demandé. Pour H1 : passthrough. Pour H4/Daily : aggrège."""
    if timeframe == "1h":
        return candles_1h
    if timeframe == "4h":
        return aggregate_to_h4(candles_1h)
    if timeframe == "1d":
        return aggregate_to_daily(candles_1h)
    raise ValueError(f"Unknown timeframe: {timeframe}")


def backtest_pair(
    pair: str,
    timeframe: str,
    spread_slippage_pct: float,
    use_h1_sim: bool = False,
) -> list[dict]:
    """Backtest d'une paire pour un timeframe donné.

    Logique :
    1. Charge H1 brutes + 5min (5min sert toujours pour la simu intra-bar).
       Si use_h1_sim=True, skip le 5min et utilise H1 pour la simu — moins
       précis mais permet le backtest 2020-2023 où 5min n'existe pas.
    2. Aggrège H1 → signal_candles selon timeframe.
    3. Pour chaque bar i ≥ 30 (warmup ATR) :
       - history = signal_candles[:i+1]
       - detect_patterns + calculate_trade_setup
       - simulate_trade_forward sur 5min (ou H1 fallback) avec timeout scalé
    4. Dedup : 1 setup max par dedup_hours.
    """
    candles_1h = load_h1_candles(pair)
    candles_for_sim = candles_1h if use_h1_sim else load_5min_candles(pair)
    if len(candles_1h) < 50:
        return []

    signal_candles = get_signal_candles(candles_1h, timeframe)
    if len(signal_candles) < 50:
        return []

    timeout_hours = TIMEOUT_HOURS_BY_TF[timeframe]
    dedup = timedelta(hours=DEDUP_HOURS_BY_TF[timeframe])

    trades: list[dict] = []
    last_at: datetime | None = None

    for i in range(30, len(signal_candles)):
        now = signal_candles[i].timestamp
        history = signal_candles[: i + 1]

        if last_at and (now - last_at) < dedup:
            continue

        patterns = detect_patterns(history, pair)
        if not patterns:
            continue
        best = patterns[0]
        setup = calculate_trade_setup(pair, best, history)
        if not setup:
            continue

        outcome, exit_time, exit_price = simulate_trade_forward(
            setup, candles_for_sim, now, timeout_hours=timeout_hours,
        )
        pips, pct = _bte.compute_pnl(
            setup, exit_price, spread_slippage_pct=spread_slippage_pct,
        )

        risk = abs(setup.entry_price - setup.stop_loss)
        reward = abs(setup.take_profit_1 - setup.entry_price)
        rr = reward / risk if risk > 0 else 0
        is_win = (outcome == "TP1") or (outcome == "TIMEOUT" and pct > 0)

        trades.append({
            "pair": pair,
            "direction": setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction),
            "pattern": best.pattern.value if hasattr(best.pattern, "value") else str(best.pattern),
            "entry_at": now,
            "exit_at": exit_time,
            "hour_utc": now.hour,
            "outcome": outcome,
            "is_win": is_win,
            "pips": pips,
            "pct": pct,
            "rr": rr,
            "entry_price": setup.entry_price,
            "stop_loss": setup.stop_loss,
            "exit_price": exit_price,
            "risk_pct": risk / setup.entry_price if setup.entry_price > 0 else 0,
        })
        last_at = now

    return trades


# ─── Filtres stratégies (identiques au backtest_v2 baseline) ────────────────

WHITELIST_PATTERNS = {"range_bounce_down", "engulfing_bearish", "range_bounce_up"}
GOOD_PAIRS = {"USD/CHF", "EUR/GBP", "EUR/USD", "USD/CAD", "GBP/USD"}
GOOD_HOURS = {1, 2, 4, 14, 15}


def filter_baseline(t: dict) -> bool:
    return True


def filter_v2_light(t: dict) -> bool:
    return t["direction"] == "sell"


def filter_v2_pattern(t: dict) -> bool:
    return t["pattern"] in WHITELIST_PATTERNS


def filter_v2_full(t: dict) -> bool:
    return (
        t["pattern"] in WHITELIST_PATTERNS
        and t["pair"] in GOOD_PAIRS
        and t["hour_utc"] in GOOD_HOURS
    )


def filter_rb_down_sell(t: dict) -> bool:
    return t["pattern"] == "range_bounce_down" and t["direction"] == "sell"


# ─── V2_CORE_LONG : filtre dérivé des exp #2/#3 ────────────────────────────
# Patterns LONG robustes sur métaux 24M :
#   momentum_up         (XAU 1.22 / XAG 2.09)
#   engulfing_bullish   (XAU 1.68 / XAG 1.10)
#   breakout_up         (XAU 1.84 / XAG 1.19)
# SHORTs exclus pour éviter le carry XAG (SELL PF 0.83 sur 24M).
CORE_LONG_PATTERNS = {"momentum_up", "engulfing_bullish", "breakout_up"}


def filter_v2_core_long(t: dict) -> bool:
    return t["direction"] == "buy" and t["pattern"] in CORE_LONG_PATTERNS


# ─── Stats ──────────────────────────────────────────────────────────────────

def stats(label: str, trades: list[dict]) -> dict | None:
    if not trades:
        print(f"  {label:<24} (vide)")
        return None
    n = len(trades)
    wins = sum(1 for t in trades if t["is_win"])
    wr = wins / n * 100
    total_pct = sum(t["pct"] for t in trades)
    avg_pct = total_pct / n
    gross_win = sum(t["pct"] for t in trades if t["pct"] > 0)
    gross_loss = abs(sum(t["pct"] for t in trades if t["pct"] < 0))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in sorted(trades, key=lambda x: x["entry_at"]):
        equity += t["pct"]
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    pf_str = f"{pf:>4.2f}" if pf != float("inf") else "  ∞ "
    print(
        f"  {label:<24} n={n:>5}  wr={wr:>5.1f}%  "
        f"PnL={total_pct:>+8.2f}%  avg={avg_pct:>+5.3f}%  "
        f"PF={pf_str}  maxDD={max_dd:>5.2f}%"
    )
    return {
        "label": label, "n": n, "wr": wr, "pnl_pct": total_pct,
        "avg_pct": avg_pct, "pf": pf, "max_dd": max_dd,
    }


def main() -> None:
    global START, END
    parser = argparse.ArgumentParser(description="Track A multi-TF backtest")
    parser.add_argument("--timeframe", "-t", choices=["1h", "4h", "1d"],
                        required=True, help="Timeframe pour la détection de pattern")
    parser.add_argument("--no-costs", action="store_true",
                        help="Backtest sans coûts spread/slippage (edge brut)")
    parser.add_argument("--pair", default=None,
                        help="Tester une seule paire (au lieu de toutes)")
    parser.add_argument("--start", default=None,
                        help="Date de début YYYY-MM-DD (défaut 2025-04-25)")
    parser.add_argument("--end", default=None,
                        help="Date de fin YYYY-MM-DD (défaut 2026-04-25)")
    parser.add_argument("--deep", action="store_true",
                        help="Avec --pair : breakdown par direction et par pattern")
    parser.add_argument("--use-h1-sim", action="store_true",
                        help="Utilise H1 candles pour la simulation forward "
                             "(au lieu de 5min). Moins précis mais permet "
                             "backtest 2020-2023 où 5min DB n'existe pas.")
    args = parser.parse_args()

    if args.start:
        START = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if args.end:
        END = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    spread = 0.0 if args.no_costs else 0.0002

    pairs = [args.pair] if args.pair else PAIRS

    print(f"=== Track A backtest — TF={args.timeframe} ===")
    print(f"Fenêtre : {START.date()} → {END.date()}")
    print(f"Paires : {len(pairs)}")
    print(f"Timeout forward : {TIMEOUT_HOURS_BY_TF[args.timeframe]}h "
          f"(dedup ≥{DEDUP_HOURS_BY_TF[args.timeframe]:.0f}h)")
    print(f"Spread/slippage : {spread*100:.3f}% "
          f"({'pas de coûts' if args.no_costs else 'standard retail'})")
    print()

    all_trades: list[dict] = []
    for pair in pairs:
        print(f"  {pair}...", end=" ", flush=True)
        trades = backtest_pair(pair, args.timeframe, spread, use_h1_sim=args.use_h1_sim)
        print(f"{len(trades)} trades")
        all_trades.extend(trades)

    print(f"\nTotal trades simulés : {len(all_trades)}")
    print()

    print(f"=== Comparaison stratégies (TF={args.timeframe}) ===")
    stats("BASELINE (no filter)", [t for t in all_trades if filter_baseline(t)])
    stats("V2_LIGHT (sell only)", [t for t in all_trades if filter_v2_light(t)])
    stats("V2_PATTERN (whitelist)", [t for t in all_trades if filter_v2_pattern(t)])
    stats("V2_FULL (all filters)", [t for t in all_trades if filter_v2_full(t)])
    stats("V2_CORE_LONG (3pat BUY)", [t for t in all_trades if filter_v2_core_long(t)])
    stats("RB_DOWN_SELL only", [t for t in all_trades if filter_rb_down_sell(t)])
    print()

    # Breakdown BASELINE par paire (pour repérer les "porteurs" éventuels)
    print(f"=== BASELINE — breakdown par paire (TF={args.timeframe}) ===")
    by_pair: dict[str, list[dict]] = defaultdict(list)
    for t in all_trades:
        by_pair[t["pair"]].append(t)
    for pair, ts in sorted(by_pair.items()):
        stats(f"{pair}", ts)

    # Mode --deep : décomposition direction + pattern, utile sur --pair X
    if args.deep:
        print(f"\n=== BASELINE — breakdown par direction (TF={args.timeframe}) ===")
        by_dir: dict[str, list[dict]] = defaultdict(list)
        for t in all_trades:
            by_dir[t["direction"]].append(t)
        for d, ts in sorted(by_dir.items()):
            stats(f"{d}", ts)

        print(f"\n=== BASELINE — breakdown par pattern (TF={args.timeframe}) ===")
        by_pat: dict[str, list[dict]] = defaultdict(list)
        for t in all_trades:
            by_pat[t["pattern"]].append(t)
        for pat, ts in sorted(by_pat.items(), key=lambda x: -len(x[1])):
            stats(f"{pat}", ts)

        print(f"\n=== BASELINE — breakdown direction × pattern (TF={args.timeframe}) ===")
        by_dp: dict[tuple, list[dict]] = defaultdict(list)
        for t in all_trades:
            by_dp[(t["direction"], t["pattern"])].append(t)
        for (d, p), ts in sorted(by_dp.items(), key=lambda x: -len(x[1])):
            stats(f"{d:<5} {p}", ts)


if __name__ == "__main__":
    main()
