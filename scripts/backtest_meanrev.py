#!/usr/bin/env python3
"""Backtest meanrev depuis la ligne de commande.

Usage (dans le container radar) :
    sudo docker exec scalping-radar python3 /app/scripts/backtest_meanrev.py \
        --pair XAU/USD --from 2026-09-21 --to 2026-11-12

Options :
    --pair         Ex: XAU/USD (obligatoire)
    --from         Date début YYYY-MM-DD (obligatoire)
    --to           Date fin YYYY-MM-DD (obligatoire)
    --db           Chemin sqlite (défaut /app/data/ticks_courtier.db)
    --capital      Capital en EUR pour sizing (défaut 1600)
    --risk-pct     Risque par trade en % (défaut = RISK_PCT du live, 0.5%)
    --export       Chemin JSON pour export complet des trades
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime, timezone


def _ensure_sys_path() -> None:
    """Rendre le backend importable selon qu'on tourne dans le container ou hors."""
    import os
    for candidate in ("/app", "/home/user/scalping", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))):
        if os.path.isdir(os.path.join(candidate, "backend")):
            if candidate not in sys.path:
                sys.path.insert(0, candidate)
            return


_ensure_sys_path()

from backend.services.meanrev_backtest import run_backtest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pair", required=True, help="Ex: XAU/USD")
    parser.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--db", default="/app/data/ticks_courtier.db")
    parser.add_argument("--capital", type=float, default=1600.0, help="Capital EUR (défaut 1600)")
    parser.add_argument("--risk-pct", type=float, default=None,
                        help="Risque %% par trade (défaut = RISK_PCT du live, 0.5%%)")
    parser.add_argument("--export", help="Chemin JSON pour export complet")
    parser.add_argument("--debug", action="store_true",
                        help="Diagnostic funnel + distributions + suggestions de seuils")
    args = parser.parse_args()

    from_dt = datetime.fromisoformat(args.from_date).replace(tzinfo=timezone.utc)
    to_dt = datetime.fromisoformat(args.to_date).replace(tzinfo=timezone.utc)

    print(f"=== BACKTEST MEANREV {args.pair} ===")
    print(f"Période : {args.from_date} → {args.to_date}")
    print(f"DB      : {args.db}")
    print(f"Capital : {args.capital} EUR | Risque : {args.risk_pct if args.risk_pct is not None else 'défaut 0.5'}%\n")
    print("Chargement des ticks + agrégation + replay…\n")

    results = run_backtest(
        pair=args.pair,
        from_dt=from_dt,
        to_dt=to_dt,
        db_path=args.db,
        capital_eur=args.capital,
        risk_pct=args.risk_pct,
        debug=args.debug,
    )

    print(f"Ticks lus     : {results.n_ticks:,}")
    print(f"Candles 1h    : {results.n_candles_1h:,}")
    print(f"Candles 15min : {results.n_candles_15m:,}\n")

    print(f"Setups détectés : {results.n_setups_detected}")
    print(f"Trades fermés   : {len(results.trades)}\n")

    breakdown = results.breakdown
    if results.trades:
        print("Breakdown des exits :")
        for k in ("tp", "sl", "time_stop_4h", "data_end"):
            v = breakdown.get(k, 0)
            pct = (v / len(results.trades) * 100) if results.trades else 0
            print(f"  {k:<15} : {v:>4} ({pct:>5.1f}%)")

        print(f"\nPnL total       : {results.pnl_total_usd:+.2f} USD")
        print(f"Winrate         : {results.winrate * 100:.1f}%")
        pf = results.profit_factor
        print(f"Profit factor   : {'inf' if pf == float('inf') else f'{pf:.2f}'}")
        print(f"Max drawdown    : {results.max_drawdown_usd:+.2f} USD")
        print(f"Sharpe (brut)   : {results.sharpe_ratio:.2f}")
    else:
        print("Aucun trade exécuté sur cette période.")

    # ─── Mode --debug : funnel diagnostic ───────────────────────────────
    if args.debug and results.funnel is not None:
        f = results.funnel
        total = f.n_candles_15m_evaluated
        print(f"\n=== FUNNEL DIAGNOSTIC ===")
        print(f"Bougies 15m évaluées     : {total:,}")

        def _pct(n: int) -> str:
            return f"{(n / total * 100):>5.1f}%" if total else "  N/A"

        print(f"\nPass par critère seul :")
        print(f"  BBW percentile > {f.bbw_threshold_used:<4}  : {f.n_pass_bbw:>5} ({_pct(f.n_pass_bbw)})")
        print(f"  ATR > {f.atr_threshold_used:.2f}× moyenne     : {f.n_pass_atr:>5} ({_pct(f.n_pass_atr)})")
        print(f"  Trigger > {f.trigger_threshold_used:.2f}× ATR     : {f.n_pass_trigger:>5} ({_pct(f.n_pass_trigger)})")

        print(f"\nPass combinés :")
        print(f"  BBW ∩ ATR              : {f.n_pass_bbw_and_atr:>5} ({_pct(f.n_pass_bbw_and_atr)})")
        print(f"  BBW ∩ trigger          : {f.n_pass_bbw_and_trigger:>5} ({_pct(f.n_pass_bbw_and_trigger)})")
        print(f"  ATR ∩ trigger          : {f.n_pass_atr_and_trigger:>5} ({_pct(f.n_pass_atr_and_trigger)})")
        print(f"  BBW ∩ ATR ∩ trigger    : {f.n_pass_all_three:>5} ({_pct(f.n_pass_all_three)})  ← TRIPLE AND actuel")

        def _fmt_q(q: dict) -> str:
            return "  ".join(
                f"p{p}={q[p]:.2f}" if p < 100 else f"max={q[p]:.2f}"
                for p in (10, 25, 50, 75, 90, 95, 99, 100)
            )

        print(f"\nDistribution observée :")
        print(f"  BBW percentile :")
        print(f"    {_fmt_q(f.bbw_percentile_quantiles)}")
        print(f"  ATR expansion :")
        print(f"    {_fmt_q(f.atr_expansion_quantiles)}")
        print(f"  Trigger amplitude/ATR :")
        print(f"    {_fmt_q(f.trigger_mult_quantiles)}")

        if f.suggested_thresholds:
            print(f"\nSuggestions de seuils pour atteindre N setups :")
            for n_target in sorted(f.suggested_thresholds.keys()):
                s = f.suggested_thresholds[n_target]
                print(
                    f"  N={n_target:<3} : BBW>{s['bbw_pct']:<5}  ATR>{s['atr_mult']:<4}  "
                    f"TRIG>{s['trigger_mult']:<4}  (estim ≈{s['expected_setups']} setups)"
                )

    if args.export:
        payload = {
            "pair": args.pair,
            "from": args.from_date,
            "to": args.to_date,
            "n_ticks": results.n_ticks,
            "n_candles_1h": results.n_candles_1h,
            "n_candles_15m": results.n_candles_15m,
            "n_setups": results.n_setups_detected,
            "pnl_usd": results.pnl_total_usd,
            "winrate": results.winrate,
            "profit_factor": None if results.profit_factor == float("inf") else results.profit_factor,
            "max_drawdown_usd": results.max_drawdown_usd,
            "sharpe_ratio": results.sharpe_ratio,
            "breakdown": breakdown,
            "trades": [dataclasses.asdict(t) for t in results.trades],
        }
        if results.funnel is not None:
            payload["funnel"] = dataclasses.asdict(results.funnel)
        with open(args.export, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        print(f"\nExport JSON : {args.export}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
