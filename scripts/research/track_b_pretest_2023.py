"""Track B exp #10 — Robustesse temporelle pré-bull cycle.

Applique les règles macro apprises sur TRAIN (2024-04 → 2025-04) à une
fenêtre PRE_TEST chronologiquement *antérieure* (2023-04 → 2024-04),
soit avant le bull cycle métaux qui s'est intensifié mi-2024.

C'est un test out-of-sample temporel inversé : si les règles tiennent
à la fois en avant (TEST 2025-2026) et en arrière (PRE_TEST 2023-2024)
de la fenêtre TRAIN, on a une preuve forte de robustesse cross-régime.

Critère go/no-go (FIXÉ AVANT) :
  - **Robuste cross-régime** : PF PRE_TEST filtered ≥ 1.50 ET ≥ baseline + 0.20
  - **Conditionnel régime** : PF filtered ≥ baseline mais < +0.20
  - **Régime-spécifique** : PF filtered < baseline → l'edge est conditionnel
    au régime macro 2024-2026, pas une mécanique universelle
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.research.track_b_macro_buckets import collect_trades_with_macro
from scripts.research.track_b_macro_filter import (
    build_or_filter_from_train,
    apply_or_filter,
    stats,
)


def main() -> None:
    train_start = datetime(2024, 4, 25, tzinfo=timezone.utc)
    train_end = datetime(2025, 4, 25, tzinfo=timezone.utc)
    pretest_start = datetime(2023, 4, 25, tzinfo=timezone.utc)
    pretest_end = datetime(2024, 4, 25, tzinfo=timezone.utc)
    test_start = datetime(2025, 4, 25, tzinfo=timezone.utc)
    test_end = datetime(2026, 4, 25, tzinfo=timezone.utc)

    print("=== Track B exp #10 — Robustesse pré-bull cycle ===\n")
    print("Hypothèse : les règles macro apprises sur 2024-2025 (TRAIN)")
    print("tiennent aussi avant cette fenêtre (PRE_TEST 2023-2024).")
    print()

    # 1. Re-collect TRAIN trades (pour réapprendre les règles)
    train_trades: list[dict] = []
    pretest_trades: list[dict] = []
    test_trades: list[dict] = []
    for pair in ["XAU/USD", "XAG/USD"]:
        print(f"  Loading {pair} TRAIN, PRE_TEST, TEST...")
        train_trades.extend(collect_trades_with_macro(pair, "4h", train_start, train_end))
        pretest_trades.extend(collect_trades_with_macro(pair, "4h", pretest_start, pretest_end))
        test_trades.extend(collect_trades_with_macro(pair, "4h", test_start, test_end))

    print(f"\n  TRAIN     : {len(train_trades)} trades  ({train_start.date()} → {train_end.date()})")
    print(f"  PRE_TEST  : {len(pretest_trades)} trades  ({pretest_start.date()} → {pretest_end.date()})")
    print(f"  TEST      : {len(test_trades)} trades  ({test_start.date()} → {test_end.date()})")
    print()

    # 2. Build rules from TRAIN (idem exp #9)
    rules = build_or_filter_from_train(train_trades)
    print(f"=== Règles apprises sur TRAIN ({len(rules)}) ===")
    for (key, lo, hi, pf_train, n_train) in rules:
        print(f"  {key:<22} ∈ [{lo:>8.3f}, {hi:>8.3f})  PF_train={pf_train:>4.2f}")
    print()

    # 3. Apply to PRE_TEST and TEST
    pretest_filtered = apply_or_filter(pretest_trades, rules)
    test_filtered = apply_or_filter(test_trades, rules)

    pf_pretest_base, n_pretest_base, pnl_pretest_base = stats(pretest_trades)
    pf_pretest_filt, n_pretest_filt, pnl_pretest_filt = stats(pretest_filtered)
    pf_test_base, n_test_base, pnl_test_base = stats(test_trades)
    pf_test_filt, n_test_filt, pnl_test_filt = stats(test_filtered)
    pf_train_base, n_train_base, pnl_train_base = stats(train_trades)
    train_filtered = apply_or_filter(train_trades, rules)
    pf_train_filt, n_train_filt, pnl_train_filt = stats(train_filtered)

    print(f"{'Subset':<28} {'n':>5}  {'PF':>5}  {'PnL%':>10}  {'kept%':>7}")
    print(f"{'-'*60}")
    print(f"{'PRE_TEST baseline (2023-24)':<28} {n_pretest_base:>5}  {pf_pretest_base:>5.2f}  {pnl_pretest_base:>+10.2f}  {'100%':>7}")
    print(f"{'PRE_TEST filtered':<28} {n_pretest_filt:>5}  {pf_pretest_filt:>5.2f}  {pnl_pretest_filt:>+10.2f}  {n_pretest_filt/max(n_pretest_base,1)*100:>6.1f}%")
    print()
    print(f"{'TRAIN baseline (2024-25)':<28} {n_train_base:>5}  {pf_train_base:>5.2f}  {pnl_train_base:>+10.2f}  {'100%':>7}")
    print(f"{'TRAIN filtered':<28} {n_train_filt:>5}  {pf_train_filt:>5.2f}  {pnl_train_filt:>+10.2f}  {n_train_filt/max(n_train_base,1)*100:>6.1f}%")
    print()
    print(f"{'TEST baseline (2025-26)':<28} {n_test_base:>5}  {pf_test_base:>5.2f}  {pnl_test_base:>+10.2f}  {'100%':>7}")
    print(f"{'TEST filtered':<28} {n_test_filt:>5}  {pf_test_filt:>5.2f}  {pnl_test_filt:>+10.2f}  {n_test_filt/max(n_test_base,1)*100:>6.1f}%")
    print()

    delta_pretest = pf_pretest_filt - pf_pretest_base
    print(f"=== Verdict ===")
    print(f"  Δ PF PRE_TEST (filtered - baseline) = {delta_pretest:+.2f}")
    if pf_pretest_filt >= 1.50 and delta_pretest >= 0.20:
        print(f"  ✓ ROBUSTE CROSS-RÉGIME : PF PRE_TEST {pf_pretest_filt:.2f} ≥ 1.50 ET Δ ≥ +0.20")
        print(f"  → Les règles tiennent AVANT et APRÈS le TRAIN. Edge méthodologique solide.")
    elif delta_pretest >= 0:
        print(f"  ~ CONDITIONNEL : amélioration {delta_pretest:+.2f}, mais soit PF<1.50 soit Δ<0.20")
        print(f"  → Edge faiblement présent pré-bull cycle. À surveiller.")
    else:
        print(f"  ✗ RÉGIME-SPÉCIFIQUE : Δ {delta_pretest:+.2f} < 0")
        print(f"  → Le filtre dégrade en PRE_TEST. L'edge est conditionnel au régime 2024-2026.")
        print(f"  → Implication shadow log : édge probablement présent en 2026-2027")
        print(f"     (extension du bull cycle), mais à surveiller en cas de bear cycle.")


if __name__ == "__main__":
    main()
