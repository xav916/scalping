"""Exp #12 — Sharpe analysis sur les 4 candidats systèmes.

Compare risk-adjusted return (Sharpe annualisé, Calmar, max DD) entre :
  - Track A V2_CORE_LONG sur XAU H4
  - Track A V2_CORE_LONG sur XAG H4
  - Track C TF LONG sur XAU H4
  - Track C TF LONG sur XAG H4

Sur la fenêtre 24M (2024-04 → 2026-04) avec vol target sizing à 1% par
trade sur capital 10 000 €.

Critère go/no-go (FIXÉ AVANT) :
  - **Excellent** : Sharpe ≥ 1.5 ET maxDD ≤ 20% sur ≥1 candidat
  - **Bon** : Sharpe ≥ 1.0 sur ≥1 candidat
  - **Faible** : Sharpe < 0.7 sur les 4 candidats
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import scripts.research.track_a_backtest as ta
from scripts.research.track_a_backtest import backtest_pair, filter_v2_core_long
from scripts.research.track_c_trend_following import backtest_tf_pair
from scripts.research.risk_metrics import print_risk_report


def normalize_track_c_trade(t: dict) -> dict:
    """Convertit un trade Track C dict en format compatible avec
    apply_vol_target_sizing (ajoute risk_pct depuis entry_price/stop)."""
    entry = t["entry_price"]
    stop = t["stop"]
    risk_pct = abs(entry - stop) / entry if entry > 0 else 0.01
    out = dict(t)
    out["risk_pct"] = risk_pct
    return out


def main() -> None:
    capital = 10_000.0
    risk_pct = 0.01  # 1% par trade
    start = datetime(2024, 4, 25, tzinfo=timezone.utc)
    end = datetime(2026, 4, 25, tzinfo=timezone.utc)

    print(f"=== Exp #12 — Sharpe analysis 24M ===")
    print(f"Window     : {start.date()} → {end.date()}")
    print(f"Capital    : {capital:,.0f} €")
    print(f"Risk/trade : {risk_pct*100:.1f} % ({capital*risk_pct:.0f} € max loss attendu par trade)")

    results = {}

    # --- Track A V2_CORE_LONG ---
    for pair in ["XAU/USD", "XAG/USD"]:
        ta.START = start
        ta.END = end
        raw = backtest_pair(pair, "4h", spread_slippage_pct=0.0002)
        core = [t for t in raw if filter_v2_core_long(t)]
        label = f"Track A V2_CORE_LONG {pair} H4"
        results[label] = print_risk_report(label, core, capital, risk_pct)

    # --- Track C TF LONG ---
    for pair in ["XAU/USD", "XAG/USD"]:
        c_trades = backtest_tf_pair(pair, start=start, end=end, timeframe="4h")
        c_long = [normalize_track_c_trade(t) for t in c_trades if t["direction"] == "long"]
        label = f"Track C TF LONG {pair} H4"
        results[label] = print_risk_report(label, c_long, capital, risk_pct)

    # --- Synthèse ---
    print("\n\n=== Synthèse ===")
    print(f"  {'System':<40} {'n':>4}  {'Sharpe':>7}  {'maxDD%':>7}  {'Calmar':>7}  {'Annual':>8}  {'TotRet':>8}")
    print(f"  {'-'*92}")
    for label, m in results.items():
        if not m:
            continue
        print(
            f"  {label:<40} {m['n_trades']:>4}  "
            f"{m['sharpe']:>7.2f}  {m['max_dd_pct']:>7.1f}  "
            f"{m['calmar']:>7.2f}  {m['annualized_return_pct']:>+7.1f}%  "
            f"{m['total_return_pct']:>+7.1f}%"
        )

    # Verdict
    print("\n=== Verdict ===")
    sharpes = [(label, m["sharpe"], m["max_dd_pct"]) for label, m in results.items() if m]
    sharpes.sort(key=lambda x: -x[1])
    if not sharpes:
        print("  Aucune mesure obtenue.")
        return
    best_label, best_sharpe, best_dd = sharpes[0]
    if best_sharpe >= 1.5 and best_dd <= 20:
        print(f"  ✓ EXCELLENT : {best_label} → Sharpe {best_sharpe:.2f}, maxDD {best_dd:.1f}%")
        print(f"  → candidat shadow log très solide")
    elif best_sharpe >= 1.0:
        print(f"  ✓ BON : {best_label} → Sharpe {best_sharpe:.2f}, maxDD {best_dd:.1f}%")
        print(f"  → candidat shadow log acceptable, à monitorer")
    elif best_sharpe >= 0.7:
        print(f"  ~ MARGINAL : meilleur Sharpe {best_sharpe:.2f}, en-dessous des standards retail")
        print(f"  → utilisation prudente avec position size réduite")
    else:
        print(f"  ✗ FAIBLE : meilleur Sharpe {best_sharpe:.2f} < 0.7")
        print(f"  → systèmes pas assez risk-efficient pour shadow log live")


if __name__ == "__main__":
    main()
