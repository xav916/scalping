"""Track B exp #8 — Analyse macro-conditionnelle des trades V2_CORE_LONG.

Question : le PF des trades V2_CORE_LONG (Track A) varie-t-il
significativement selon le régime macro à l'entrée ? Si oui → un classifier
ML utilisant les features macro pourrait améliorer l'edge.

Pour chaque trade existant on calcule les features macro asof T-1d, puis on
bucketise par :
  - vix_regime (low/normal/high)
  - dxy_dist_sma50 (4 quartiles)
  - tnx_level (4 quartiles)
  - spx_return_5d (4 quartiles)

Critère go/no-go (FIXÉ AVANT) :
  - **Signal** : spread PF entre meilleur et pire bucket ≥ 0.40 sur ≥1 dimension
    avec ≥30 trades par bucket extrême
  - **Pas de signal** : spread < 0.25 sur toutes les dimensions
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import scripts.research.track_a_backtest as ta
from scripts.research.track_a_backtest import (
    backtest_pair,
    filter_v2_core_long,
)
from backend.services.macro_data import get_macro_features_at


def collect_trades_with_macro(
    pair: str,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Lance le backtest Track A V2_CORE_LONG, enrichit chaque trade avec
    les features macro à l'entry timestamp."""
    ta.START = start
    ta.END = end
    raw = backtest_pair(pair, timeframe, spread_slippage_pct=0.0002)
    core = [t for t in raw if filter_v2_core_long(t)]
    enriched: list[dict] = []
    for t in core:
        macro = get_macro_features_at(t["entry_at"])
        merged = dict(t)
        # On ne garde que les clés qu'on va bucketer
        for k in ("vix_level", "vix_regime", "vix_delta_1d", "vix_return_5d",
                  "dxy_level", "dxy_dist_sma50", "dxy_delta_1d",
                  "tnx_level", "tnx_delta_1d",
                  "spx_dist_sma50", "spx_return_1d", "spx_return_5d",
                  "btc_return_1d", "btc_return_5d", "btc_dist_sma50"):
            merged[k] = macro.get(k)
        enriched.append(merged)
    return enriched


def stats_bucket(label: str, trades: list[dict]) -> tuple[float, int] | None:
    """Retourne (PF, n) ou None si vide."""
    if not trades:
        print(f"    {label:<32} (vide)")
        return None
    n = len(trades)
    wins = sum(1 for t in trades if t["is_win"])
    wr = wins / n * 100
    total = sum(t["pct"] for t in trades)
    gw = sum(t["pct"] for t in trades if t["pct"] > 0)
    gl = abs(sum(t["pct"] for t in trades if t["pct"] < 0))
    pf = gw / gl if gl > 0 else float("inf")
    pf_str = f"{pf:5.2f}" if pf != float("inf") else "  ∞ "
    print(f"    {label:<32} n={n:>4}  wr={wr:>5.1f}%  PnL={total:>+8.2f}%  PF={pf_str}")
    return (pf if pf != float("inf") else 99.0, n)


def quartile_buckets(trades: list[dict], key: str) -> list[tuple[str, list[dict]]]:
    """Split en 4 quartiles sur la valeur `key`. Skip les trades sans valeur."""
    valued = [(t[key], t) for t in trades if t.get(key) is not None]
    if not valued:
        return []
    valued.sort(key=lambda x: x[0])
    n = len(valued)
    q1, q2, q3 = n // 4, n // 2, (3 * n) // 4
    if n < 4:
        return []
    edges = [valued[q1][0], valued[q2][0], valued[q3][0]]
    buckets = [
        (f"Q1 {key}<{edges[0]:.2f}", [t for v, t in valued[:q1]]),
        (f"Q2 {edges[0]:.2f}↔{edges[1]:.2f}", [t for v, t in valued[q1:q2]]),
        (f"Q3 {edges[1]:.2f}↔{edges[2]:.2f}", [t for v, t in valued[q2:q3]]),
        (f"Q4 {key}>{edges[2]:.2f}", [t for v, t in valued[q3:]]),
    ]
    return buckets


def analyze_dimension(trades: list[dict], dim_label: str, key: str, mode: str = "quartile") -> float:
    """Print stats par bucket et retourne le spread PF max-min sur ≥30 trades.

    mode = 'quartile' ou 'categorical'
    """
    print(f"\n  --- bucketed by {dim_label} ---")
    if mode == "categorical":
        groups: dict[str, list[dict]] = defaultdict(list)
        for t in trades:
            v = t.get(key)
            if v is not None:
                groups[str(v)].append(t)
        labelled = [(g, ts) for g, ts in sorted(groups.items())]
    else:
        labelled = quartile_buckets(trades, key)

    pfs: list[float] = []
    for label, ts in labelled:
        result = stats_bucket(label, ts)
        if result:
            pf, n = result
            if n >= 30:  # filtre stat
                pfs.append(pf)
    if len(pfs) >= 2:
        spread = max(pfs) - min(pfs)
        print(f"  → spread PF (n≥30) = {spread:+.2f}")
        return spread
    return 0.0


def main() -> None:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--pair", default=None, help="Single pair (default: XAU+XAG)")
    p.add_argument("--start", default="2024-04-25")
    p.add_argument("--end", default="2026-04-25")
    args = p.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    pairs = [args.pair] if args.pair else ["XAU/USD", "XAG/USD"]
    print(f"=== Macro-bucket analysis V2_CORE_LONG H4 ===")
    print(f"Window: {start.date()} → {end.date()}")
    print(f"Pairs : {pairs}\n")

    all_trades: list[dict] = []
    for pair in pairs:
        print(f"  Loading {pair}...")
        trades = collect_trades_with_macro(pair, "4h", start, end)
        print(f"    {len(trades)} trades V2_CORE_LONG enrichis")
        all_trades.extend(trades)

    print(f"\nTotal : {len(all_trades)} trades")
    print()
    print("=== Stats globales (ALL trades) ===")
    stats_bucket("ALL", all_trades)

    spreads: dict[str, float] = {}
    spreads["vix_regime"] = analyze_dimension(all_trades, "VIX regime", "vix_regime", mode="categorical")
    spreads["vix_level"] = analyze_dimension(all_trades, "VIX level (quartiles)", "vix_level")
    spreads["dxy_dist_sma50"] = analyze_dimension(all_trades, "DXY dist SMA50 (quartiles)", "dxy_dist_sma50")
    spreads["dxy_delta_1d"] = analyze_dimension(all_trades, "DXY delta 1d (quartiles)", "dxy_delta_1d")
    spreads["tnx_level"] = analyze_dimension(all_trades, "TNX yield (quartiles)", "tnx_level")
    spreads["tnx_delta_1d"] = analyze_dimension(all_trades, "TNX delta 1d (quartiles)", "tnx_delta_1d")
    spreads["spx_return_5d"] = analyze_dimension(all_trades, "SPX return 5d (quartiles)", "spx_return_5d")
    spreads["spx_dist_sma50"] = analyze_dimension(all_trades, "SPX dist SMA50 (quartiles)", "spx_dist_sma50")
    spreads["btc_return_5d"] = analyze_dimension(all_trades, "BTC return 5d (quartiles)", "btc_return_5d")

    # Synthèse
    print("\n=== Synthèse spreads PF (max - min, n≥30) ===")
    for dim, sp in sorted(spreads.items(), key=lambda x: -x[1]):
        flag = "🔥 SIGNAL" if sp >= 0.40 else ("→ marginal" if sp >= 0.25 else "  flat")
        print(f"  {dim:<22} spread={sp:+.2f}  {flag}")

    best = max(spreads.values())
    print(f"\n=== Verdict ===")
    if best >= 0.40:
        print(f"  ✓ SIGNAL macro-conditionnel détecté (spread max {best:+.2f})")
        print(f"  → re-extraction ML avec features macro = JUSTIFIÉE")
    elif best >= 0.25:
        print(f"  ~ Spread marginal {best:+.2f} — signal faible mais non-nul")
        print(f"  → tester re-extraction ciblée ou abandonner")
    else:
        print(f"  ✗ Aucun spread significatif (max {best:+.2f})")
        print(f"  → macro features n'apportent pas d'edge sur V2_CORE_LONG. Bascule vers Phase 2 Track C ou A out-of-sample.")


if __name__ == "__main__":
    main()
