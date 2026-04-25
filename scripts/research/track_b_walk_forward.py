"""Track B exp #24 — Walk-forward expansif du filtre macro.

Au lieu d'un TRAIN fixe (exp #9 : 2024-04 → 2025-04), refit du filtre
macro sur **fenêtre glissante** : à chaque mois M, on refit sur les
12 mois [M-12, M-1], puis on applique le filtre au mois M (out-of-sample
strict).

Objectif : tester si un filtre adaptatif au régime courant performe mieux
qu'un filtre fixe (qui dégradait en pré-bull cycle, exp #10).

Critère go/no-go (FIXÉ AVANT) :
  - **Walk-forward justifié** : PF cumulé walk-forward ≥ PF baseline + 0.20
    sur la fenêtre out-of-sample (2024-04 → 2026-04, 24 mois)
  - **Égale au fixe** : Δ entre -0.10 et +0.10 vs filtre fixe exp #9 (2.28)
    → garder fixe pour simplicité opérationnelle
  - **Pire** : Δ < -0.10 → confirmer que walk-forward sur-fitte au noise
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.research.track_b_macro_buckets import collect_trades_with_macro
from scripts.research.track_b_macro_filter import (
    build_or_filter_from_train,
    apply_or_filter,
    stats,
)


def month_start(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def add_months(dt: datetime, n: int) -> datetime:
    """Ajoute n mois à dt (peut être négatif)."""
    y = dt.year + (dt.month - 1 + n) // 12
    m = (dt.month - 1 + n) % 12 + 1
    return dt.replace(year=y, month=m)


def main() -> None:
    # Out-of-sample window : 2024-04 → 2026-04 (24 mois)
    test_start = datetime(2024, 4, 1, tzinfo=timezone.utc)
    test_end = datetime(2026, 4, 1, tzinfo=timezone.utc)

    # Pour walk-forward, on doit charger TRAIN window pour chaque mois.
    # Plus simple : charger toutes les données 2023-04 → 2026-04 d'un coup
    # (3 ans × 2 paires) et slicer en mémoire.
    full_start = datetime(2023, 4, 1, tzinfo=timezone.utc)
    full_end = test_end

    print(f"=== Track B exp #24 — Walk-forward expansif ===\n")
    print(f"Out-of-sample window : {test_start.date()} → {test_end.date()} (24 mois)")
    print(f"TRAIN glissant : 12 mois précédents pour chaque mois OOS\n")

    all_trades: list[dict] = []
    for pair in ["XAU/USD", "XAG/USD"]:
        print(f"  Loading {pair} {full_start.date()} → {full_end.date()}...")
        all_trades.extend(collect_trades_with_macro(pair, "4h", full_start, full_end))
    print(f"\nTotal trades enrichis : {len(all_trades)}\n")

    # Boucle walk-forward : à chaque mois M, refit sur [M-12, M-1], apply à M
    cur = test_start
    selected_trades: list[dict] = []
    baseline_trades_oos: list[dict] = []
    n_months = 0
    rules_history: list[tuple[str, int]] = []  # (month, n_rules)

    while cur < test_end:
        next_month = add_months(cur, 1)
        train_window_end = cur
        train_window_start = add_months(cur, -12)

        # Filtrer trades dans la TRAIN window
        train_trades = [
            t for t in all_trades
            if train_window_start <= t["entry_at"] < train_window_end
        ]
        # Filtrer trades dans la fenêtre OOS du mois courant
        oos_trades = [
            t for t in all_trades
            if cur <= t["entry_at"] < next_month
        ]
        baseline_trades_oos.extend(oos_trades)

        if len(train_trades) >= 100:
            rules = build_or_filter_from_train(train_trades)
            rules_history.append((cur.strftime("%Y-%m"), len(rules)))
            if rules:
                filtered_oos = apply_or_filter(oos_trades, rules)
                selected_trades.extend(filtered_oos)
        # Sinon : pas assez de TRAIN data, on n'apply pas (skip ce mois)

        n_months += 1
        cur = next_month

    print(f"Walk-forward terminé : {n_months} mois traités")
    print(f"Trades baseline OOS : {len(baseline_trades_oos)}")
    print(f"Trades retenus walk-forward : {len(selected_trades)}")
    print(f"Rétention : {len(selected_trades)/max(len(baseline_trades_oos),1)*100:.1f}%\n")

    # Stats walk-forward vs baseline OOS vs filtre fixe (rappel exp #9)
    pf_baseline, n_baseline, pnl_baseline = stats(baseline_trades_oos)
    pf_wf, n_wf, pnl_wf = stats(selected_trades)

    # Pour comparer au filtre fixe exp #9 : refit sur 2024-04 → 2025-04
    train_fixed_start = datetime(2024, 4, 1, tzinfo=timezone.utc)
    train_fixed_end = datetime(2025, 4, 1, tzinfo=timezone.utc)
    test_fixed_start = train_fixed_end
    train_fixed_trades = [
        t for t in all_trades
        if train_fixed_start <= t["entry_at"] < train_fixed_end
    ]
    test_fixed_trades = [
        t for t in all_trades
        if test_fixed_start <= t["entry_at"] < test_end
    ]
    fixed_rules = build_or_filter_from_train(train_fixed_trades)
    test_fixed_filtered = apply_or_filter(test_fixed_trades, fixed_rules)
    pf_fixed, n_fixed, pnl_fixed = stats(test_fixed_filtered)
    pf_fixed_baseline, _, _ = stats(test_fixed_trades)

    print("=== Résultats ===\n")
    print(f"  {'Stratégie':<32} {'n':>5}  {'PF':>5}  {'PnL%':>10}  {'kept%':>7}")
    print(f"  {'-'*64}")
    print(f"  {'BASELINE OOS (no filter, 24M)':<32} {n_baseline:>5}  {pf_baseline:>5.2f}  {pnl_baseline:>+10.2f}  {'100%':>7}")
    print(f"  {'WALK-FWD (refit chaque mois)':<32} {n_wf:>5}  {pf_wf:>5.2f}  {pnl_wf:>+10.2f}  {n_wf/max(n_baseline,1)*100:>6.1f}%")
    print(f"  {'FIXE (TRAIN 24-25 → TEST 25-26)':<32} {n_fixed:>5}  {pf_fixed:>5.2f}  {pnl_fixed:>+10.2f}  {n_fixed/max(len(test_fixed_trades),1)*100:>6.1f}%")
    print()

    # Décision
    delta_wf_vs_baseline = pf_wf - pf_baseline
    delta_wf_vs_fixed = pf_wf - pf_fixed
    print(f"=== Verdict ===")
    print(f"  Δ Walk-Forward vs Baseline OOS = {delta_wf_vs_baseline:+.2f}")
    print(f"  Δ Walk-Forward vs Filtre Fixe = {delta_wf_vs_fixed:+.2f}")
    print()
    if delta_wf_vs_fixed >= 0.10:
        print(f"  ✓ WALK-FORWARD SUPÉRIEUR : refit dynamique apporte +{delta_wf_vs_fixed:.2f} PF")
        print(f"  → migrer le système live vers refit mensuel")
    elif delta_wf_vs_fixed >= -0.10:
        print(f"  ≈ ÉGAL : Δ {delta_wf_vs_fixed:+.2f} négligeable")
        print(f"  → garder filtre fixe pour simplicité opérationnelle (KISS)")
    else:
        print(f"  ✗ FIXE SUPÉRIEUR : Δ {delta_wf_vs_fixed:+.2f}")
        print(f"  → walk-forward sur-fitte au noise mensuel, garder fixe")

    # Log historique des règles trouvées
    print(f"\n=== Évolution du nombre de règles trouvées par mois ===")
    for month, n in rules_history:
        print(f"  {month}: {n} règle{'s' if n != 1 else ''}")


if __name__ == "__main__":
    main()
