"""Calibration analysis du V1 scoring : confidence_score prédit-il le win rate ?

Lit `_macro_veto_analysis/backtest.db` (5674 trades V1 backtestés) et
mesure la qualité de calibration via :

1. Win rate observé par bucket de confidence (25-30, 30-40, ..., 70-80)
2. Brier score global = mean((p_pred - outcome)²)
3. Calibration plot data : p_pred_bucket vs win_rate_observed
4. Réfutation/confirmation du verdict "V1 no edge"

Si confidence_score est calibré : bucket 60-70 a ~65% win rate.
Si decorrelé : tous les buckets ont ~44% (moyenne globale) → confidence
n'est qu'une décoration.

Usage : python scripts/research/v1_calibration_brier.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "_macro_veto_analysis" / "backtest.db"

BUCKETS: list[tuple[int, int]] = [
    (25, 30), (30, 40), (40, 50), (50, 55),
    (55, 60), (60, 65), (65, 70), (70, 75),
]


def main() -> None:
    con = sqlite3.connect(str(DB))
    rows = con.execute(
        "SELECT confidence_score, outcome FROM trades "
        "WHERE outcome IN ('WIN_TP1', 'WIN_TP2', 'LOSS')"
    ).fetchall()
    con.close()

    n = len(rows)
    if n == 0:
        print("ERR: 0 trades fermés en DB")
        return

    pairs = [(c / 100.0, 1 if o.startswith("WIN") else 0) for c, o in rows]
    p_preds = [p for p, _ in pairs]
    outcomes = [o for _, o in pairs]

    wins = sum(outcomes)
    win_rate = wins / n
    avg_conf = sum(p_preds) / n
    brier = sum((p - o) ** 2 for p, o in pairs) / n

    print(f"=== V1 Calibration Brier — backtest 5342 trades fermés ===\n")
    print(f"Total trades fermés : {n}")
    print(f"Wins (TP1+TP2)      : {wins} ({win_rate*100:.2f}%)")
    print(f"Losses              : {n - wins} ({(1-win_rate)*100:.2f}%)")
    print(f"Avg confidence pred : {avg_conf*100:.2f}%")
    print(f"Brier score global  : {brier:.4f}")
    print()

    print("Calibration par bucket de confidence :")
    print(f"{'Bucket':<10} {'n':>6} {'Mean p_pred':>12} {'Win rate obs':>14} {'Δ (obs-pred)':>14} {'Brier':>8}")
    print("-" * 70)
    for lo, hi in BUCKETS:
        bucket = [(p, o) for p, o in pairs if lo / 100.0 <= p < hi / 100.0]
        if not bucket:
            continue
        bn = len(bucket)
        mean_p = sum(p for p, _ in bucket) / bn
        obs = sum(o for _, o in bucket) / bn
        delta = obs - mean_p
        bbrier = sum((p - o) ** 2 for p, o in bucket) / bn
        print(f"{lo}-{hi:<6} {bn:>6} {mean_p*100:>11.2f}% {obs*100:>13.2f}% {delta*100:>+13.2f}pp {bbrier:>8.4f}")

    print()

    if abs(win_rate - avg_conf) < 0.02:
        verdict = "CALIBRÉ (écart global < 2pp)"
    elif win_rate > avg_conf:
        verdict = f"SOUS-CONFIANT (système gagne {(win_rate-avg_conf)*100:.1f}pp de plus que prédit)"
    else:
        verdict = f"SUR-CONFIANT (système gagne {(avg_conf-win_rate)*100:.1f}pp de moins que prédit)"
    print(f"Verdict global : {verdict}")

    monotonic = True
    prev_obs: float | None = None
    for lo, hi in BUCKETS:
        bucket = [(p, o) for p, o in pairs if lo / 100.0 <= p < hi / 100.0]
        if len(bucket) < 30:
            continue
        obs = sum(o for _, o in bucket) / len(bucket)
        if prev_obs is not None and obs < prev_obs - 0.03:
            monotonic = False
            break
        prev_obs = obs
    print(f"Monotonicité confidence→win_rate : {'OUI' if monotonic else 'NON (le score n inverse l ordre)'}")

    print()
    print("Baseline naïve (toujours prédire win_rate global) :")
    naive_brier = sum((win_rate - o) ** 2 for o in outcomes) / n
    print(f"  Brier baseline = {naive_brier:.4f}")
    print(f"  V1 Brier       = {brier:.4f}")
    if brier < naive_brier - 0.001:
        print(f"  Skill score    = {(naive_brier-brier)/naive_brier*100:.2f}% (V1 bat la baseline)")
    elif brier > naive_brier + 0.001:
        print(f"  Skill score    = {(brier-naive_brier)/naive_brier*100:.2f}% PIRE (V1 sous baseline) — score décoratif")
    else:
        print(f"  Skill score    = ~0% (V1 = baseline, pas d'info dans confidence)")


if __name__ == "__main__":
    main()
