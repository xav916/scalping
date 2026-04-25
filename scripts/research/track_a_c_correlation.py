"""Exp #13 — Corrélation entre Track A V2_CORE_LONG et Track C TF LONG.

Question : les 2 systèmes captent-ils le *même* signal (corrélation
forte → redondance) ou des angles différents (corrélation faible →
diversification réelle, Sharpe combiné > Sharpe individuel) ?

Mesure : corrélation Pearson sur les monthly returns en €, sous vol
target sizing identique (capital 10k€, 1% risk/trade).

Critère go/no-go (FIXÉ AVANT) :
  - **Diversification réelle** : |corr| < 0.5 → portefeuille combiné
    apporte un boost Sharpe significatif
  - **Corrélation modérée** : 0.5 ≤ |corr| < 0.75 → bénéfice diversif modéré
  - **Redondance** : |corr| ≥ 0.75 → les 2 systèmes captent le même
    signal, simplification possible (prendre un seul)
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from math import sqrt
from pathlib import Path
from statistics import mean, stdev
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import scripts.research.track_a_backtest as ta
from scripts.research.track_a_backtest import backtest_pair, filter_v2_core_long
from scripts.research.track_c_trend_following import backtest_tf_pair
from scripts.research.risk_metrics import apply_vol_target_sizing
from scripts.research.track_a_c_sharpe import normalize_track_c_trade


def monthly_pnl_eur(trades_sized: list[dict]) -> dict[str, float]:
    """Group trades by YYYY-MM, sum pnl_eur."""
    out: dict[str, float] = defaultdict(float)
    for t in trades_sized:
        m = t["entry_at"].strftime("%Y-%m")
        out[m] += t["pnl_eur"]
    return dict(out)


def pearson_correlation(xs: list[float], ys: list[float]) -> float:
    """Coefficient de corrélation Pearson entre 2 séries de même taille."""
    if len(xs) != len(ys) or len(xs) < 3:
        return 0.0
    n = len(xs)
    mx, my = mean(xs), mean(ys)
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / (n - 1)
    sx = stdev(xs)
    sy = stdev(ys)
    if sx == 0 or sy == 0:
        return 0.0
    return cov / (sx * sy)


def aligned_monthly(
    a_pnl: dict[str, float],
    c_pnl: dict[str, float],
) -> tuple[list[str], list[float], list[float]]:
    """Aligne les 2 séries sur les mois communs. Retourne (months, a_returns, c_returns)."""
    common_months = sorted(set(a_pnl.keys()) | set(c_pnl.keys()))
    a_ret = [a_pnl.get(m, 0.0) for m in common_months]
    c_ret = [c_pnl.get(m, 0.0) for m in common_months]
    return common_months, a_ret, c_ret


def main() -> None:
    start = datetime(2024, 4, 25, tzinfo=timezone.utc)
    end = datetime(2026, 4, 25, tzinfo=timezone.utc)
    capital = 10_000.0
    risk_pct = 0.01

    print(f"=== Exp #13 — Corrélation Track A × Track C ===")
    print(f"Window  : {start.date()} → {end.date()}")
    print(f"Sizing  : capital {capital:.0f}€, {risk_pct*100:.1f}% risk/trade")
    print()

    for pair in ["XAU/USD", "XAG/USD"]:
        # Track A V2_CORE_LONG
        ta.START = start
        ta.END = end
        a_raw = backtest_pair(pair, "4h", spread_slippage_pct=0.0002)
        a_core = [t for t in a_raw if filter_v2_core_long(t)]
        a_sized = apply_vol_target_sizing(a_core, capital, risk_pct)

        # Track C TF LONG
        c_raw = backtest_tf_pair(pair, start=start, end=end, timeframe="4h")
        c_long = [normalize_track_c_trade(t) for t in c_raw if t["direction"] == "long"]
        c_sized = apply_vol_target_sizing(c_long, capital, risk_pct)

        a_pnl = monthly_pnl_eur(a_sized)
        c_pnl = monthly_pnl_eur(c_sized)

        months, a_ret, c_ret = aligned_monthly(a_pnl, c_pnl)
        corr = pearson_correlation(a_ret, c_ret)

        print(f"=== {pair} ===")
        print(f"  Months avec data     : {len(months)}")
        print(f"  Track A monthly avg  : {mean(a_ret):>+8.1f} €  (std {stdev(a_ret) if len(a_ret)>=2 else 0:>6.1f})")
        print(f"  Track C monthly avg  : {mean(c_ret):>+8.1f} €  (std {stdev(c_ret) if len(c_ret)>=2 else 0:>6.1f})")
        print(f"  → Corrélation Pearson  : {corr:>+6.3f}")

        # Combined : sum of both per month
        combined = [a + c for a, c in zip(a_ret, c_ret)]
        comb_mean = mean(combined)
        comb_std = stdev(combined) if len(combined) >= 2 else 0
        if comb_std > 0:
            sharpe_comb = (comb_mean / capital * 100) / (comb_std / capital * 100) * sqrt(12)
        else:
            sharpe_comb = 0
        print(f"  Combined monthly avg : {comb_mean:>+8.1f} €  (std {comb_std:>6.1f})")
        print(f"  Combined Sharpe (50/50 PnL sum) : {sharpe_comb:>5.2f}")

        # Verdict
        if abs(corr) < 0.5:
            v = "DIVERSIFICATION RÉELLE — Sharpe combiné boost significatif"
        elif abs(corr) < 0.75:
            v = "Corrélation modérée — bénéfice diversif partiel"
        else:
            v = "REDONDANCE — les 2 systèmes captent le même signal"
        print(f"  Verdict : {v}")
        print()

    # Cross-pair correlation aussi : XAU A vs XAG A, XAU C vs XAG C
    print("=== Corrélations cross-pair (intra-track) ===")
    for label, sys in [("Track A V2_CORE_LONG", "A"), ("Track C TF LONG", "C")]:
        all_pnl: dict[str, dict[str, float]] = {}
        for pair in ["XAU/USD", "XAG/USD"]:
            if sys == "A":
                ta.START = start
                ta.END = end
                raw = backtest_pair(pair, "4h", spread_slippage_pct=0.0002)
                trades = [t for t in raw if filter_v2_core_long(t)]
            else:
                raw = backtest_tf_pair(pair, start=start, end=end, timeframe="4h")
                trades = [normalize_track_c_trade(t) for t in raw if t["direction"] == "long"]
            sized = apply_vol_target_sizing(trades, capital, risk_pct)
            all_pnl[pair] = monthly_pnl_eur(sized)
        months, xau_ret, xag_ret = aligned_monthly(all_pnl["XAU/USD"], all_pnl["XAG/USD"])
        corr = pearson_correlation(xau_ret, xag_ret)
        print(f"  {label:<24} XAU vs XAG corr : {corr:>+6.3f}")


if __name__ == "__main__":
    main()
