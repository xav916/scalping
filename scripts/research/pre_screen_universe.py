"""Pre-screening systématique de l'univers — phase 1 méthode rigoureuse.

Pour chaque (pair × timeframe × filter) dans la matrice, lance un backtest
12M no-costs use_h1_sim=True et calcule PF + WR + n. Output ranking pour
identifier le top 5-10% candidats à approfondir.

Usage :
    python scripts/research/pre_screen_universe.py
        → écrit pre_screen_results.csv et imprime top 30

Pourquoi no-costs : edge brut sur 12M, on cherche les diamants. L'ajustement
costs (PF -0.10 typique) sera appliqué en phase 2 pour les survivants.

Pourquoi use_h1_sim=True : pas de 5min pour les 41 nouveaux instruments,
on simule en H1. Moins précis mais cohérent pour comparer.
"""
from __future__ import annotations

import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import scripts.research.track_a_backtest as ta
from scripts.research.track_a_backtest import (
    filter_baseline,
    filter_v2_core_long,
    filter_v2_wti_optimal,
    filter_v2_tight_long,
)


# ─── Univers ────────────────────────────────────────────────────────────────

# 16 instruments déjà fetchés depuis Track A original
EXISTING = [
    "AUD/USD", "BTC/USD", "ETH/USD", "EUR/GBP", "EUR/USD", "GBP/JPY",
    "GBP/USD", "USD/CAD", "USD/CHF", "USD/JPY", "XAG/USD", "XAU/USD",
    "WTI/USD", "XBR/USD", "XPT/USD", "XPD/USD",
]
# 41 nouveaux fetched par scripts/fetch_universe.sh
NEW = [
    # Forex emerging (11)
    "USD/ZAR", "USD/TRY", "USD/SGD", "USD/NOK", "USD/SEK", "USD/PLN",
    "USD/HUF", "USD/CZK", "NZD/USD", "AUD/JPY", "EUR/AUD",
    # Crypto majors (8)
    "SOL/USD", "ADA/USD", "XRP/USD", "BNB/USD", "DOGE/USD", "DOT/USD",
    "AVAX/USD", "LINK/USD",
    # Indices intl (8)
    "DAX", "FTSE", "CAC", "SMI", "ASX", "IBEX", "MIB", "AEX",
    # Sector ETFs (13)
    "XLE", "XLF", "XLV", "XLK", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE",
    "SLV", "USO", "UNG",
    # Soft commodity (1)
    "CORN",
]
UNIVERSE = EXISTING + NEW  # 57 instruments

TIMEFRAMES = ["4h", "1d"]

FILTERS = [
    ("BASELINE", filter_baseline),
    ("V2_CORE_LONG", filter_v2_core_long),
    ("V2_WTI_OPTIMAL", filter_v2_wti_optimal),
    ("V2_TIGHT_LONG", filter_v2_tight_long),
]


def compact_stats(trades: list[dict]) -> dict | None:
    """PF, WR, n, PnL% sur la liste filtrée."""
    if not trades:
        return None
    n = len(trades)
    wins = sum(1 for t in trades if t["pct"] > 0)
    pnl = sum(t["pct"] for t in trades)
    gw = sum(t["pct"] for t in trades if t["pct"] > 0)
    gl = abs(sum(t["pct"] for t in trades if t["pct"] < 0))
    pf = (gw / gl) if gl > 0 else None
    wr = (wins / n) * 100
    return {"n": n, "wr_pct": wr, "pf": pf, "pnl_pct": pnl}


def main() -> None:
    # Fenêtre 12M récent
    ta.START = datetime(2025, 4, 25, tzinfo=timezone.utc)
    ta.END = datetime(2026, 4, 25, tzinfo=timezone.utc)

    print(f"=== Pre-screen univers — 12M no-costs use_h1_sim ===")
    print(f"Pairs : {len(UNIVERSE)} | TFs : {TIMEFRAMES} | Filters : {len(FILTERS)}")
    print(f"Cellules totales : {len(UNIVERSE) * len(TIMEFRAMES) * len(FILTERS)}")
    print()

    rows: list[dict] = []
    skipped: list[str] = []

    t_start = time.time()
    for pair in UNIVERSE:
        for tf in TIMEFRAMES:
            try:
                trades = ta.backtest_pair(pair, tf, spread_slippage_pct=0.0, use_h1_sim=True)
            except Exception as e:
                skipped.append(f"{pair} {tf}: {e}")
                continue

            if not trades:
                # Pas assez de data ou rien détecté
                skipped.append(f"{pair} {tf}: no trades")
                continue

            for fname, ffunc in FILTERS:
                filtered = [t for t in trades if ffunc(t)]
                s = compact_stats(filtered)
                if s and s["pf"] is not None:
                    rows.append({
                        "pair": pair,
                        "tf": tf,
                        "filter": fname,
                        **s,
                    })

        elapsed = time.time() - t_start
        n_done = UNIVERSE.index(pair) + 1
        print(f"  [{n_done:>2}/{len(UNIVERSE)}] {pair:<10} ({elapsed:>5.1f}s elapsed)")

    elapsed = time.time() - t_start
    print()
    print(f"Terminé en {elapsed:.0f}s. Cellules avec PF : {len(rows)}, skipped : {len(skipped)}")

    # Output CSV
    csv_path = ROOT / "pre_screen_results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["pair", "tf", "filter", "n", "wr_pct", "pf", "pnl_pct"])
        for r in sorted(rows, key=lambda x: -x["pf"]):
            w.writerow([
                r["pair"], r["tf"], r["filter"],
                r["n"], f"{r['wr_pct']:.1f}", f"{r['pf']:.2f}", f"{r['pnl_pct']:+.1f}"
            ])
    print(f"CSV écrit : {csv_path}")

    # Top 30 (n>=20 pour fiabilité statistique minimale)
    top = [r for r in rows if r["n"] >= 20]
    top.sort(key=lambda x: -x["pf"])

    print()
    print(f"=== Top 30 PF (12M no-costs, n≥20) — {len(top)} cellules au-dessus du seuil ===")
    print(f"{'pair':<10} {'tf':<3} {'filter':<18} {'n':>4} {'wr%':>6} {'PF':>5} {'PnL%':>8}")
    print("─" * 60)
    for r in top[:30]:
        print(f"{r['pair']:<10} {r['tf']:<3} {r['filter']:<18} {r['n']:>4} {r['wr_pct']:>5.1f}% {r['pf']:>5.2f} {r['pnl_pct']:>+7.1f}%")

    # Top par classe d'actif (pour repérer les nouveautés)
    print()
    print(f"=== Bottom 10 (perdants extrêmes pour info) ===")
    print(f"{'pair':<10} {'tf':<3} {'filter':<18} {'n':>4} {'wr%':>6} {'PF':>5} {'PnL%':>8}")
    print("─" * 60)
    bot = sorted([r for r in rows if r["n"] >= 20], key=lambda x: x["pf"])[:10]
    for r in bot:
        print(f"{r['pair']:<10} {r['tf']:<3} {r['filter']:<18} {r['n']:>4} {r['wr_pct']:>5.1f}% {r['pf']:>5.2f} {r['pnl_pct']:>+7.1f}%")

    if skipped:
        print()
        print(f"=== Skipped ({len(skipped)}) ===")
        for s in skipped[:20]:
            print(f"  {s}")
        if len(skipped) > 20:
            print(f"  ... +{len(skipped)-20} more")


if __name__ == "__main__":
    main()
