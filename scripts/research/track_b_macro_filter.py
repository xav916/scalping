"""Track B exp #9 — Filtre macro ad-hoc sur V2_CORE_LONG, walk-forward split.

Apprend les seuils macro favorables sur TRAIN (2024-04-25 → 2025-04-25)
et applique le filtre sur TEST (2025-04-25 → 2026-04-25). Out-of-sample
strict pour éviter l'in-sample bias d'exp #8.

Critère go/no-go (FIXÉ AVANT) :
  - **Robuste** : PF filtre TEST ≥ 1.80 ET ≥ PF baseline TEST + 0.30
  - **Marginal** : PF filtre TEST ≥ baseline + 0.10
  - **Overfit** : PF filtre TEST < baseline TEST → les seuils TRAIN ne
    généralisent pas, abandonner ce filtre

Filtre construit : OR de 5 conditions individuelles ayant un PF TRAIN > 1.80
avec n_train ≥ 30. Un setup passe le filtre si AU MOINS UNE condition est vraie.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.research.track_b_macro_buckets import collect_trades_with_macro


# Définitions des features candidates et leur direction présumée favorable
# (basé sur lecture économique d'exp #8)
FEATURE_KEYS = [
    "btc_return_5d", "dxy_dist_sma50", "spx_dist_sma50",
    "spx_return_5d", "tnx_level", "vix_level",
    "tnx_delta_1d", "dxy_delta_1d",
]


def stats(trades: list[dict]) -> tuple[float, int, float]:
    """Retourne (PF, n, total_pnl_pct). PF = inf si pas de losses."""
    if not trades:
        return (0.0, 0, 0.0)
    n = len(trades)
    total = sum(t["pct"] for t in trades)
    gw = sum(t["pct"] for t in trades if t["pct"] > 0)
    gl = abs(sum(t["pct"] for t in trades if t["pct"] < 0))
    pf = gw / gl if gl > 0 else 99.0
    return (pf, n, total)


def find_favorable_bins(
    trades: list[dict],
    key: str,
    n_bins: int = 4,
    pf_threshold: float = 1.80,
    min_n: int = 30,
) -> list[tuple[float, float]]:
    """Trouve les bins de la dimension `key` avec PF ≥ pf_threshold sur les trades fournis.

    Retourne list[(lower, upper)] — les bornes inclusives (sauf la dernière qui est upper exclusive).
    """
    valued = [(t[key], t) for t in trades if t.get(key) is not None]
    if len(valued) < min_n * n_bins:
        return []
    valued.sort(key=lambda x: x[0])
    chunk = len(valued) // n_bins
    bins: list[tuple[float, float]] = []
    for i in range(n_bins):
        start_idx = i * chunk
        end_idx = (i + 1) * chunk if i < n_bins - 1 else len(valued)
        chunk_trades = [t for v, t in valued[start_idx:end_idx]]
        pf, n, _ = stats(chunk_trades)
        if pf >= pf_threshold and n >= min_n:
            lower = valued[start_idx][0]
            upper = valued[end_idx - 1][0] + 1e-9  # inclusive upper
            bins.append((lower, upper))
    return bins


def build_or_filter_from_train(train_trades: list[dict]) -> list[tuple[str, float, float, float, int]]:
    """Pour chaque feature, identifie les bins favorables (PF ≥ 1.80, n ≥ 30) sur TRAIN.
    Retourne list[(feature_key, lower, upper, pf_train, n_train)].
    """
    rules: list[tuple[str, float, float, float, int]] = []
    for key in FEATURE_KEYS:
        bins = find_favorable_bins(train_trades, key, n_bins=4, pf_threshold=1.80, min_n=30)
        for (lo, hi) in bins:
            # Mesurer le PF du bin sur TRAIN pour traçabilité
            in_bin = [t for t in train_trades if t.get(key) is not None and lo <= t[key] < hi]
            pf_train, n_train, _ = stats(in_bin)
            rules.append((key, lo, hi, pf_train, n_train))
    return rules


def apply_or_filter(trades: list[dict], rules: list[tuple[str, float, float, float, int]]) -> list[dict]:
    """Garde un trade si AU MOINS UNE des règles est vraie pour lui."""
    out: list[dict] = []
    for t in trades:
        for (key, lo, hi, _pf_train, _n_train) in rules:
            v = t.get(key)
            if v is not None and lo <= v < hi:
                out.append(t)
                break
    return out


def main() -> None:
    train_start = datetime(2024, 4, 25, tzinfo=timezone.utc)
    train_end = datetime(2025, 4, 25, tzinfo=timezone.utc)
    test_start = datetime(2025, 4, 25, tzinfo=timezone.utc)
    test_end = datetime(2026, 4, 25, tzinfo=timezone.utc)

    print("=== Track B exp #9 — Walk-forward filtre macro ===\n")

    # 1. Collect trades on TRAIN and TEST separately
    train_trades: list[dict] = []
    test_trades: list[dict] = []
    for pair in ["XAU/USD", "XAG/USD"]:
        print(f"  Collecting {pair} TRAIN ({train_start.date()} → {train_end.date()})...")
        train_trades.extend(collect_trades_with_macro(pair, "4h", train_start, train_end))
        print(f"  Collecting {pair} TEST ({test_start.date()} → {test_end.date()})...")
        test_trades.extend(collect_trades_with_macro(pair, "4h", test_start, test_end))

    print(f"\nTRAIN : {len(train_trades)} trades")
    print(f"TEST  : {len(test_trades)} trades")
    print()

    # 2. Build rules from TRAIN
    print("=== Règles favorables identifiées sur TRAIN (PF ≥ 1.80, n ≥ 30) ===")
    rules = build_or_filter_from_train(train_trades)
    if not rules:
        print("  Aucune règle qualifiée. Filtrage impossible.")
        return
    for (key, lo, hi, pf_train, n_train) in rules:
        print(f"  {key:<22} ∈ [{lo:>8.3f}, {hi:>8.3f})  PF_train={pf_train:>4.2f}  n_train={n_train:>4}")
    print(f"\nTotal règles : {len(rules)} (filtre OR — un setup passe si ≥1 règle vraie)")
    print()

    # 3. Apply filter to TRAIN (sanity check) and TEST (verdict)
    train_filtered = apply_or_filter(train_trades, rules)
    test_filtered = apply_or_filter(test_trades, rules)

    pf_train_base, n_train_base, pnl_train_base = stats(train_trades)
    pf_train_filt, n_train_filt, pnl_train_filt = stats(train_filtered)
    pf_test_base, n_test_base, pnl_test_base = stats(test_trades)
    pf_test_filt, n_test_filt, pnl_test_filt = stats(test_filtered)

    print("=== Résultats ===\n")
    print(f"  {'Subset':<24} {'n':>5}  {'PF':>5}  {'PnL%':>10}  {'kept%':>7}")
    print(f"  {'-'*54}")
    print(f"  {'TRAIN baseline':<24} {n_train_base:>5}  {pf_train_base:>5.2f}  {pnl_train_base:>+10.2f}  {'100%':>7}")
    print(f"  {'TRAIN filtered (OR)':<24} {n_train_filt:>5}  {pf_train_filt:>5.2f}  {pnl_train_filt:>+10.2f}  {n_train_filt/max(n_train_base,1)*100:>6.1f}%")
    print(f"  {'TEST baseline':<24} {n_test_base:>5}  {pf_test_base:>5.2f}  {pnl_test_base:>+10.2f}  {'100%':>7}")
    print(f"  {'TEST filtered (OR)':<24} {n_test_filt:>5}  {pf_test_filt:>5.2f}  {pnl_test_filt:>+10.2f}  {n_test_filt/max(n_test_base,1)*100:>6.1f}%")
    print()

    delta_test = pf_test_filt - pf_test_base
    print(f"=== Verdict ===")
    print(f"  Δ PF TEST (filtered - baseline) = {delta_test:+.2f}")
    if pf_test_filt >= 1.80 and delta_test >= 0.30:
        print(f"  ✓ ROBUSTE : PF TEST {pf_test_filt:.2f} ≥ 1.80 ET amélioration ≥ +0.30")
        print(f"  → Filtre généralise hors TRAIN. Candidat shadow log.")
    elif delta_test >= 0.10:
        print(f"  ~ MARGINAL : amélioration {delta_test:+.2f} > 0.10 mais < 0.30")
        print(f"  → Le filtre apporte une amélioration faible — affiner les seuils ou abandonner.")
    elif delta_test >= -0.10:
        print(f"  ≈ Neutre — le filtre n'apporte pas d'amélioration nette en TEST.")
    else:
        print(f"  ✗ OVERFIT : PF TEST {pf_test_filt:.2f} < baseline {pf_test_base:.2f} (Δ {delta_test:+.2f})")
        print(f"  → Les seuils TRAIN ne généralisent pas. Abandonner ce filtre.")


if __name__ == "__main__":
    main()
