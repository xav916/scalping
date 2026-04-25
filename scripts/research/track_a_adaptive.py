"""Exp #25 — V2_ADAPTIVE régime-aware TIGHT/CORE.

Insight d'exp #17 : V2_TIGHT (2 patterns BUY) bat V2_CORE (3 patterns) en
marché calme (Δ +0.05 PF, maxDD ÷1.5). V2_CORE bat TIGHT en bull cycle
(Δ +0.10 à +0.15 PF). L'idée : switcher automatiquement selon régime.

Détecteur régime simple basé sur features macro Track B :
- "BULL_CYCLE" si XAU rallye récent (e.g. spx_dist_sma50 dans Q1-Q3
  d'exp #8 où PF V2_CORE > 1.5) → use V2_CORE
- "CALM" sinon → use V2_TIGHT

Hypothèse régime simple à tester :
- BULL_CYCLE : tnx_level < 4.5 ET dxy_dist_sma50 dans [-2, +2]
- CALM : sinon

Critère go/no-go (FIXÉ AVANT) :
- **Adaptive justifié** : PF ADAPTIVE ≥ max(CORE, TIGHT) + 0.05 sur 6 ans
- **Égal** : Δ entre -0.05 et +0.05 → garder CORE
- **Pire** : régime detector trop crude
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.research.track_b_macro_buckets import collect_trades_with_macro
from scripts.research.track_b_macro_filter import stats
from scripts.research.track_a_backtest import (
    CORE_LONG_PATTERNS, TIGHT_LONG_PATTERNS,
)


def detect_regime(macro: dict) -> str:
    """Retourne 'BULL_CYCLE' ou 'CALM' selon les features macro.

    BULL_CYCLE : tnx_level < 4.5 ET |dxy_dist_sma50| < 2
    Sinon : CALM

    Hypothèse : en bull cycle, real yields bas + dollar proche de sa
    moyenne = environnement haussier pour métaux où breakout_up est
    productif. Sinon, les breakouts donnent des whipsaws.
    """
    tnx = macro.get("tnx_level")
    dxy_dist = macro.get("dxy_dist_sma50")

    if tnx is None or dxy_dist is None:
        # Pas de macro disponible → fallback CORE (le plus general)
        return "BULL_CYCLE"

    if tnx < 4.5 and abs(dxy_dist) < 2.0:
        return "BULL_CYCLE"
    return "CALM"


def filter_v2_adaptive(t: dict) -> bool:
    """Apply pattern selection selon régime détecté."""
    if t["direction"] != "buy":
        return False
    regime = detect_regime(t)
    if regime == "BULL_CYCLE":
        return t["pattern"] in CORE_LONG_PATTERNS
    else:  # CALM
        return t["pattern"] in TIGHT_LONG_PATTERNS


def filter_v2_core(t: dict) -> bool:
    return t["direction"] == "buy" and t["pattern"] in CORE_LONG_PATTERNS


def filter_v2_tight(t: dict) -> bool:
    return t["direction"] == "buy" and t["pattern"] in TIGHT_LONG_PATTERNS


def main() -> None:
    full_start = datetime(2020, 4, 25, tzinfo=timezone.utc)
    full_end = datetime(2026, 4, 25, tzinfo=timezone.utc)

    print(f"=== Exp #25 — V2_ADAPTIVE régime-aware ===\n")
    print(f"Window : {full_start.date()} → {full_end.date()} (6 ans)")
    print(f"Régime BULL_CYCLE : tnx < 4.5 ET |dxy_dist_sma50| < 2")
    print(f"  → use CORE (3 patterns)")
    print(f"Régime CALM : sinon → use TIGHT (2 patterns)\n")

    all_trades: list[dict] = []
    for pair in ["XAU/USD", "XAG/USD"]:
        print(f"  Loading {pair}...")
        # Note : collect_trades_with_macro n'utilise pas use_h1_sim, donc 5min
        # data limited to 2023-04. On bornre ici à cette window pour avoir des
        # outcomes valides (sinon trades à entry 2020 mais simulate forward
        # fail).
        # Pour couvrir 2020-2023, on aurait besoin de modifier
        # collect_trades_with_macro pour use_h1_sim. Plus court : limiter à
        # 2023-04 → 2026-04 (3 ans, encore solide).
        sub_start = datetime(2023, 4, 25, tzinfo=timezone.utc)
        all_trades.extend(collect_trades_with_macro(pair, "4h", sub_start, full_end))

    print(f"\nTotal trades enrichis : {len(all_trades)}")
    print(f"Window effective : 2023-04-25 → 2026-04-25 (3 ans)\n")

    # Compter les régimes détectés
    regime_counts = {"BULL_CYCLE": 0, "CALM": 0}
    for t in all_trades:
        regime_counts[detect_regime(t)] += 1
    total = max(sum(regime_counts.values()), 1)
    print(f"Distribution des régimes :")
    print(f"  BULL_CYCLE: {regime_counts['BULL_CYCLE']:>5} trades ({regime_counts['BULL_CYCLE']/total*100:.0f}%)")
    print(f"  CALM      : {regime_counts['CALM']:>5} trades ({regime_counts['CALM']/total*100:.0f}%)\n")

    # 3 stratégies en compétition
    core_trades = [t for t in all_trades if filter_v2_core(t)]
    tight_trades = [t for t in all_trades if filter_v2_tight(t)]
    adaptive_trades = [t for t in all_trades if filter_v2_adaptive(t)]

    pf_core, n_core, pnl_core = stats(core_trades)
    pf_tight, n_tight, pnl_tight = stats(tight_trades)
    pf_adapt, n_adapt, pnl_adapt = stats(adaptive_trades)

    print("=== Résultats ===\n")
    print(f"  {'Stratégie':<32} {'n':>5}  {'PF':>5}  {'PnL%':>10}")
    print(f"  {'-'*54}")
    print(f"  {'V2_CORE (3pat BUY)':<32} {n_core:>5}  {pf_core:>5.2f}  {pnl_core:>+10.2f}")
    print(f"  {'V2_TIGHT (2pat BUY)':<32} {n_tight:>5}  {pf_tight:>5.2f}  {pnl_tight:>+10.2f}")
    print(f"  {'V2_ADAPTIVE (TIGHT/CORE)':<32} {n_adapt:>5}  {pf_adapt:>5.2f}  {pnl_adapt:>+10.2f}")
    print()

    best_static = max(pf_core, pf_tight)
    delta = pf_adapt - best_static

    print(f"=== Verdict ===")
    print(f"  Δ ADAPTIVE vs max(CORE, TIGHT) = {delta:+.2f}")
    print()
    if delta >= 0.05:
        print(f"  ✓ ADAPTIVE SUPÉRIEUR : régime detector apporte +{delta:.2f} PF")
        print(f"  → migrer le système live vers V2_ADAPTIVE")
    elif delta >= -0.05:
        print(f"  ≈ NEUTRE : Δ {delta:+.2f} négligeable")
        print(f"  → garder V2_CORE pour simplicité (pas besoin du detector)")
    else:
        print(f"  ✗ ADAPTIVE INFÉRIEUR : Δ {delta:+.2f}")
        print(f"  → le detector simple ne capture pas correctement le régime")

    # Breakdown PF par régime pour comprendre
    print(f"\n=== Breakdown ADAPTIVE par régime détecté ===")
    bull_trades = [t for t in adaptive_trades if detect_regime(t) == "BULL_CYCLE"]
    calm_trades = [t for t in adaptive_trades if detect_regime(t) == "CALM"]
    pf_bull, n_bull, _ = stats(bull_trades)
    pf_calm, n_calm, _ = stats(calm_trades)
    print(f"  BULL_CYCLE selected: n={n_bull}  PF={pf_bull:.2f}  (apply CORE)")
    print(f"  CALM selected      : n={n_calm}  PF={pf_calm:.2f}  (apply TIGHT)")


if __name__ == "__main__":
    main()
