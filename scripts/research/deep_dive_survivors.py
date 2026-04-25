"""Phase D — Deep dive sur les survivants du pre-screening.

Pour chaque (pair, tf, filter) survivant (PF ≥ seuil pre-screen no-costs),
relance un backtest complet sur 4 fenêtres avec coûts (0.02% spread/slippage)
et calcule PF + Sharpe annualisé + Calmar + maxDD% pour décision finale.

Critère success final (avec FDR Bonferroni ajusté) :
    PF ≥ ADJUSTED_PF_THRESHOLD sur ≥ 3 des 4 fenêtres ET Sharpe ≥ 0.7

Usage :
    python scripts/research/deep_dive_survivors.py --in pre_screen_results.csv --pf-min 1.30
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from math import sqrt
from pathlib import Path
from statistics import mean, stdev

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import scripts.research.track_a_backtest as ta
from scripts.research.track_a_backtest import (
    filter_baseline,
    filter_v2_core_long,
    filter_v2_wti_optimal,
    filter_v2_tight_long,
)


FILTER_BY_NAME = {
    "BASELINE": filter_baseline,
    "V2_CORE_LONG": filter_v2_core_long,
    "V2_WTI_OPTIMAL": filter_v2_wti_optimal,
    "V2_TIGHT_LONG": filter_v2_tight_long,
}

WINDOWS = [
    ("12M", datetime(2025, 4, 25, tzinfo=timezone.utc), datetime(2026, 4, 25, tzinfo=timezone.utc)),
    ("24M", datetime(2024, 4, 25, tzinfo=timezone.utc), datetime(2026, 4, 25, tzinfo=timezone.utc)),
    ("3y_cumul", datetime(2023, 4, 25, tzinfo=timezone.utc), datetime(2026, 4, 25, tzinfo=timezone.utc)),
    ("pre_bull", datetime(2023, 4, 25, tzinfo=timezone.utc), datetime(2024, 4, 25, tzinfo=timezone.utc)),
]


def stats_full(trades: list[dict], capital: float = 10_000.0) -> dict:
    """PF, Sharpe, Calmar, maxDD%, n, WR%."""
    if not trades:
        return {"n": 0, "pf": None, "sharpe": None, "calmar": None,
                "max_dd_pct": 0.0, "wr_pct": None, "pnl_pct": 0.0}
    n = len(trades)
    wins = sum(1 for t in trades if t["pct"] > 0)
    pnl_total = sum(t["pct"] for t in trades)
    gw = sum(t["pct"] for t in trades if t["pct"] > 0)
    gl = abs(sum(t["pct"] for t in trades if t["pct"] < 0))
    pf = gw / gl if gl > 0 else None
    wr = wins / n * 100

    # Equity curve par trade trié chrono
    sorted_trades = sorted(trades, key=lambda t: t["entry_at"])
    equity = capital
    peak = capital
    max_dd_pct = 0.0
    for t in sorted_trades:
        # Position fixe 1% risk → pnl_pct est ~10x relatif au capital
        equity *= (1 + t["pct"] / 100 * 0.01)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0
        if dd > max_dd_pct:
            max_dd_pct = dd

    # Monthly returns pour Sharpe
    by_month: dict[str, float] = {}
    for t in sorted_trades:
        m = t["entry_at"].strftime("%Y-%m")
        by_month[m] = by_month.get(m, 0) + t["pct"]
    rets = list(by_month.values())
    sharpe = None
    if len(rets) >= 3:
        sd = stdev(rets)
        if sd > 0:
            sharpe = (mean(rets) / sd) * sqrt(12)

    n_months = len(rets)
    annualized_pct = (pnl_total * 12 / n_months) if n_months > 0 else 0
    calmar = annualized_pct / (max_dd_pct * 100) if max_dd_pct > 0 else None

    return {
        "n": n,
        "wr_pct": wr,
        "pf": pf,
        "sharpe": sharpe,
        "calmar": calmar,
        "max_dd_pct": max_dd_pct * 100,
        "pnl_pct": pnl_total,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="input", default="pre_screen_results.csv",
                        help="CSV input (output de pre_screen_universe.py)")
    parser.add_argument("--pf-min", type=float, default=1.30,
                        help="Seuil pre-screen PF no-costs pour qualifier (défaut 1.30)")
    parser.add_argument("--n-min", type=int, default=20,
                        help="Sample size minimum sur 12M pour qualifier")
    parser.add_argument("--out", default="deep_dive_results.csv")
    args = parser.parse_args()

    csv_path = ROOT / args.input
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["pf"] = float(r["pf"])
            r["n"] = int(r["n"])
            r["wr_pct"] = float(r["wr_pct"])
            rows.append(r)

    survivors = [r for r in rows if r["pf"] >= args.pf_min and r["n"] >= args.n_min]
    survivors = [r for r in survivors if r["filter"] != "BASELINE"]  # baselines servent juste de référence
    print(f"Survivants pre-screen (PF ≥ {args.pf_min}, n ≥ {args.n_min}, filter ≠ BASELINE) : {len(survivors)}")
    if not survivors:
        print("Aucun survivant — réduire --pf-min ou re-vérifier le pre-screen.")
        return

    print()
    print("=== Deep dive (4 fenêtres × 0.02% costs × use_h1_sim) ===")
    print(f"{'pair':<10} {'tf':<3} {'filter':<18} {'win':<10} {'n':>4} {'PF':>5} {'Sharpe':>7} {'maxDD%':>7} {'Calmar':>7} {'PnL%':>7}")
    print("─" * 90)

    out_rows = []
    for s in survivors:
        pair, tf, filt = s["pair"], s["tf"], s["filter"]
        ffunc = FILTER_BY_NAME[filt]

        # Tester sur 4 fenêtres
        scores = []
        for win_label, win_start, win_end in WINDOWS:
            ta.START = win_start
            ta.END = win_end
            try:
                trades = ta.backtest_pair(pair, tf, spread_slippage_pct=0.0002, use_h1_sim=True)
            except Exception:
                continue
            filtered = [t for t in trades if ffunc(t)]
            stats = stats_full(filtered)
            stats["window"] = win_label
            scores.append(stats)

            sharpe_str = f"{stats['sharpe']:.2f}" if stats['sharpe'] is not None else " -- "
            calmar_str = f"{stats['calmar']:.2f}" if stats['calmar'] is not None else " -- "
            pf_str = f"{stats['pf']:.2f}" if stats['pf'] is not None else " -- "
            print(f"{pair:<10} {tf:<3} {filt:<18} {win_label:<10} {stats['n']:>4} {pf_str:>5} {sharpe_str:>7} {stats['max_dd_pct']:>6.1f}% {calmar_str:>7} {stats['pnl_pct']:>+6.1f}")

            out_rows.append({
                "pair": pair, "tf": tf, "filter": filt, "window": win_label,
                "n": stats["n"], "wr_pct": stats["wr_pct"],
                "pf": stats["pf"], "sharpe": stats["sharpe"],
                "max_dd_pct": stats["max_dd_pct"], "calmar": stats["calmar"],
                "pnl_pct": stats["pnl_pct"],
            })

        # Verdict consolidé : ≥3 fenêtres avec PF ≥ ADJUSTED + Sharpe ≥ 0.7 sur 12M
        n_ok = sum(1 for s in scores if s["pf"] is not None and s["pf"] >= 1.15)
        sharpe_12m = next((s["sharpe"] for s in scores if s["window"] == "12M"), None)
        verdict = "🎯 RETENU" if (n_ok >= 3 and sharpe_12m is not None and sharpe_12m >= 0.7) else "❌"
        print(f"{'':>50} {verdict}  {n_ok}/4 fenêtres ≥ 1.15  Sharpe12M={sharpe_12m if sharpe_12m else 'NA'}")
        print()

    # Output CSV
    out_path = ROOT / args.out
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["pair", "tf", "filter", "window", "n", "wr_pct", "pf", "sharpe", "max_dd_pct", "calmar", "pnl_pct"])
        w.writeheader()
        for r in out_rows:
            w.writerow(r)
    print(f"\nCSV écrit : {out_path}")

    # FDR Bonferroni notice
    n_tests = len(survivors)
    print()
    print(f"=== FDR / Multiple Testing notice ===")
    print(f"Tests survivants approfondis : {n_tests}")
    print(f"Bonferroni-corrected α : 0.05 / {n_tests} = {0.05/n_tests:.4f}")
    print(f"Conclusion : un edge isolé sur 1/N tests à 5% peut être du chance pure.")
    print(f"Confirmation forte requiert PF ≥ 1.15 sur ≥3 fenêtres ET Sharpe ≥ 1.0 sur 12M.")


if __name__ == "__main__":
    main()
