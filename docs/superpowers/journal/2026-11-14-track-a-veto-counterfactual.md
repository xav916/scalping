# 2026-11-14 — Track A × veto contrefactuel (auto)

**Sample :** 5376 réconciliés (EXPLOITABLE — signal directionnel possible, intervalles larges)
**Verdict :** veto_would_hurt

> ⚠️ **Signal détecté** : le veto géopolitique aurait nui.
> À intégrer dans la décision gate S6.

# Track A × Veto géopolitique — analyse contrefactuelle

**Généré :** 2026-11-14T07:03:25+00:00
**Source :** `shadow_setups` filtre `outcome IS NOT NULL AND geopolitical_features_json IS NOT NULL`
**Échantillon :** 5376 setups réconciliés
**Groupe décisif (would VETO) :** 73 setups
**Confiance :** EXPLOITABLE — signal directionnel possible, intervalles larges

## Vue d'ensemble

| Groupe | n | n_tp | n_sl | n_timeout | win_rate | PF | mean PnL% | total PnL% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Tous | 5376 | 957 | 2722 | 1697 | 26.0% | 0.89 | -0.20% | -1093.17% |
| Would VETO | 73 | 9 | 29 | 35 | 23.7% | 1.30 | +0.20% | +14.39% |
| Would PASS | 5303 | 948 | 2693 | 1662 | 26.0% | 0.89 | -0.21% | -1107.55% |

## Verdict directionnel

**LE VETO AURAIT NUIT** : les setups que le veto aurait skip ont une mean PnL de +0.20% vs -0.21% pour les autres (écart -0.41% par trade — le veto retire des trades gagnants)

## Détail par règle de veto

| Règle | n | n_tp | n_sl | mean PnL% |
|---|---:|---:|---:|---:|
| `gdelt_stress` | 66 | 9 | 23 | +0.42% |
| `iran_hormuz` | 7 | 0 | 6 | -1.86% |

## Détail par pair

| Pair | n | n_tp | n_sl | n_timeout | mean PnL% |
|---|---:|---:|---:|---:|---:|
| USD/CAD | 317 | 77 | 124 | 116 | +0.08% |
| AUD/USD | 316 | 55 | 194 | 67 | -0.14% |
| GBP/USD | 312 | 64 | 135 | 113 | -0.04% |
| EUR/USD | 301 | 61 | 168 | 72 | -0.11% |
| EUR/GBP | 239 | 46 | 140 | 53 | -0.11% |
| EUR/JPY | 238 | 27 | 126 | 85 | -0.16% |
| GBP/JPY | 234 | 22 | 120 | 92 | -0.14% |
| WTI/USD | 230 | 28 | 134 | 68 | -0.86% |
| USD/CHF | 230 | 50 | 104 | 76 | +0.02% |
| USD/JPY | 227 | 28 | 116 | 83 | -0.12% |
| XAU/USD | 215 | 42 | 111 | 62 | +0.01% |
| XAG/USD | 138 | 12 | 81 | 45 | -1.14% |
| SEI/USD | 104 | 14 | 68 | 22 | -0.41% |
| ETH/USD | 94 | 12 | 44 | 38 | -0.49% |
| XRP/USD | 94 | 24 | 52 | 18 | -1.00% |
| UNI/USD | 94 | 34 | 28 | 32 | +5.42% |
| HBAR/USD | 90 | 20 | 52 | 18 | -0.59% |
| LDO/USD | 86 | 20 | 34 | 32 | +0.62% |
| LINK/USD | 86 | 28 | 40 | 18 | +1.91% |
| ARB/USD | 86 | 24 | 32 | 30 | +3.73% |
| ENS/USD | 86 | 8 | 58 | 20 | -3.55% |
| ALGO/USD | 84 | 4 | 46 | 34 | -1.71% |
| BTC/USD | 83 | 13 | 45 | 25 | -0.25% |
| XLM/USD | 82 | 10 | 54 | 18 | -2.11% |
| DOGE/USD | 82 | 22 | 44 | 16 | -1.20% |
| MANA/USD | 78 | 16 | 30 | 32 | -0.12% |
| SOL/USD | 76 | 12 | 40 | 24 | +1.02% |
| LTC/USD | 76 | 16 | 32 | 28 | +0.51% |
| PAXG/USD | 74 | 18 | 42 | 14 | -0.61% |
| ADA/USD | 70 | 10 | 44 | 16 | -3.15% |
| BNB/USD | 68 | 4 | 30 | 34 | -0.84% |
| DOT/USD | 66 | 8 | 34 | 24 | -2.63% |
| AAVE/USD | 64 | 16 | 26 | 22 | +0.29% |
| ETHFI/USD | 60 | 16 | 18 | 26 | +3.49% |
| CRV/USD | 60 | 8 | 26 | 26 | -0.96% |
| TAO/USD | 56 | 8 | 30 | 18 | -3.19% |
| XLE | 52 | 10 | 12 | 30 | +1.31% |
| SUI/USD | 52 | 8 | 32 | 12 | +2.11% |
| XLK | 50 | 4 | 20 | 26 | -0.73% |
| ZEC/USD | 46 | 4 | 28 | 14 | -2.69% |
| INJ/USD | 46 | 14 | 12 | 20 | +1.43% |
| AVAX/USD | 46 | 12 | 26 | 8 | -0.20% |
| XLU | 40 | 6 | 16 | 18 | -0.05% |
| XLRE | 40 | 8 | 24 | 8 | -0.01% |
| XLB | 36 | 4 | 14 | 18 | -0.44% |
| XLF | 30 | 8 | 10 | 12 | +0.47% |
| DASH/USD | 30 | 2 | 24 | 4 | -9.56% |
| XLI | 12 | 0 | 2 | 10 | -1.04% |

## Notes méthodologiques

- `would_veto` est calculé au moment du log Track A (commit `3ac0d70`). Les seuils env vars `GEOPOLITICAL_VETO_*` au moment du log peuvent différer des seuils actuels.
- Les setups antérieurs au 2026-05-08 (commit du snapshot) sont exclus.
- Outcome `TIMEOUT` est compté dans `n_total` mais exclu du PF (pas de gain ni perte franche).
- Track A reste **lecture seule** — le veto n'affecte ni les setups loggés ni les outcomes ; cette analyse est purement contrefactuelle.
- Pour décision gate S6 (2026-06-06), viser `n ≥ 100` sur l'ensemble des systèmes Track A.
