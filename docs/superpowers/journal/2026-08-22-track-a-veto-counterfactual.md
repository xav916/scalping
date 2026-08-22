# 2026-08-22 — Track A × veto contrefactuel (auto)

**Sample :** 879 réconciliés (CRÉDIBLE — analyse statistique fiable)
**Verdict :** veto_would_help

> ⚠️ **Signal détecté** : le veto géopolitique aiderait (réduction des pertes / amélioration du win rate).
> À intégrer dans la décision gate S6.

# Track A × Veto géopolitique — analyse contrefactuelle

**Généré :** 2026-08-22T06:01:23+00:00
**Source :** `shadow_setups` filtre `outcome IS NOT NULL AND geopolitical_features_json IS NOT NULL`
**Échantillon :** 879 setups réconciliés
**Confiance échantillon :** CRÉDIBLE — analyse statistique fiable

## Vue d'ensemble

| Groupe | n | n_tp | n_sl | n_timeout | win_rate | PF | mean PnL% | total PnL% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Tous | 879 | 236 | 385 | 258 | 38.0% | 1.75 | +0.79% | +694.03% |
| Would VETO | 27 | 4 | 9 | 14 | 30.8% | 0.88 | -0.13% | -3.64% |
| Would PASS | 852 | 232 | 376 | 244 | 38.2% | 1.78 | +0.82% | +697.67% |

## Verdict directionnel

**LE VETO AURAIT AIDÉ** : les setups que le veto aurait skip ont une mean PnL de -0.13% vs +0.82% pour les autres (écart +0.95% par trade en faveur du veto)

## Détail par règle de veto

| Règle | n | n_tp | n_sl | mean PnL% |
|---|---:|---:|---:|---:|
| `gdelt_stress` | 20 | 4 | 3 | +0.47% |
| `iran_hormuz` | 7 | 0 | 6 | -1.86% |

## Détail par pair

| Pair | n | n_tp | n_sl | n_timeout | mean PnL% |
|---|---:|---:|---:|---:|---:|
| XAU/USD | 152 | 32 | 64 | 56 | -0.02% |
| WTI/USD | 150 | 24 | 78 | 48 | -0.40% |
| USD/CAD | 44 | 2 | 40 | 2 | -0.15% |
| EUR/USD | 30 | 16 | 6 | 8 | +0.14% |
| GBP/USD | 28 | 12 | 2 | 14 | +0.21% |
| ETH/USD | 27 | 3 | 7 | 17 | +0.70% |
| USD/JPY | 26 | 0 | 14 | 12 | -0.23% |
| XLK | 24 | 0 | 8 | 16 | -1.19% |
| AUD/USD | 24 | 6 | 10 | 8 | -0.09% |
| XAG/USD | 22 | 0 | 14 | 8 | -1.19% |
| SEI/USD | 22 | 2 | 20 | 0 | -1.75% |
| XRP/USD | 20 | 12 | 8 | 0 | +1.42% |
| XLM/USD | 20 | 2 | 18 | 0 | -1.73% |
| GBP/JPY | 20 | 4 | 4 | 12 | +0.21% |
| EUR/GBP | 19 | 4 | 4 | 11 | +0.05% |
| HBAR/USD | 18 | 4 | 14 | 0 | -0.73% |
| LDO/USD | 18 | 14 | 0 | 4 | +9.86% |
| EUR/JPY | 18 | 3 | 5 | 10 | +0.14% |
| AAVE/USD | 18 | 8 | 10 | 0 | +0.23% |
| UNI/USD | 18 | 10 | 8 | 0 | +2.30% |
| LINK/USD | 16 | 16 | 0 | 0 | +14.48% |
| ARB/USD | 14 | 6 | 8 | 0 | -0.13% |
| ENS/USD | 12 | 0 | 12 | 0 | -2.34% |
| USD/CHF | 12 | 4 | 2 | 6 | +0.20% |
| ALGO/USD | 12 | 2 | 10 | 0 | -1.37% |
| BTC/USD | 11 | 4 | 5 | 2 | -0.18% |
| MANA/USD | 10 | 6 | 4 | 0 | +1.57% |
| DOT/USD | 10 | 6 | 4 | 0 | +2.25% |
| ETHFI/USD | 8 | 8 | 0 | 0 | +19.25% |
| CRV/USD | 8 | 2 | 0 | 6 | +15.68% |
| LTC/USD | 8 | 6 | 2 | 0 | +2.93% |
| XLI | 6 | 0 | 0 | 6 | +0.25% |
| XLU | 6 | 2 | 4 | 0 | -0.96% |
| PAXG/USD | 4 | 2 | 0 | 2 | +2.96% |
| BNB/USD | 4 | 0 | 0 | 4 | +3.75% |
| SOL/USD | 4 | 4 | 0 | 0 | +8.07% |
| XLF | 4 | 0 | 0 | 4 | -0.58% |
| XLRE | 4 | 4 | 0 | 0 | +1.57% |
| DOGE/USD | 4 | 4 | 0 | 0 | +7.47% |
| XLB | 2 | 0 | 0 | 2 | -0.62% |
| ADA/USD | 2 | 2 | 0 | 0 | +5.16% |

## Notes méthodologiques

- `would_veto` est calculé au moment du log Track A (commit `3ac0d70`). Les seuils env vars `GEOPOLITICAL_VETO_*` au moment du log peuvent différer des seuils actuels.
- Les setups antérieurs au 2026-05-08 (commit du snapshot) sont exclus.
- Outcome `TIMEOUT` est compté dans `n_total` mais exclu du PF (pas de gain ni perte franche).
- Track A reste **lecture seule** — le veto n'affecte ni les setups loggés ni les outcomes ; cette analyse est purement contrefactuelle.
- Pour décision gate S6 (2026-06-06), viser `n ≥ 100` sur l'ensemble des systèmes Track A.
