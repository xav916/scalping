> 🚨 **ALERT VERDICT CHANGED** — direction_verdict = `neutral`, n_total = `4387`. Le veto a quitté le statut 'insufficient'.

# Track A × Veto géopolitique — analyse contrefactuelle

**Généré :** 2026-10-31T07:07:38+00:00
**Source :** `shadow_setups` filtre `outcome IS NOT NULL AND geopolitical_features_json IS NOT NULL`
**Échantillon :** 4387 setups réconciliés
**Groupe décisif (would VETO) :** 73 setups
**Confiance :** EXPLOITABLE — signal directionnel possible, intervalles larges

## Vue d'ensemble

| Groupe | n | n_tp | n_sl | n_timeout | win_rate | PF | mean PnL% | total PnL% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Tous | 4387 | 790 | 2071 | 1526 | 27.6% | 1.10 | +0.17% | +763.69% |
| Would VETO | 73 | 9 | 29 | 35 | 23.7% | 1.30 | +0.20% | +14.39% |
| Would PASS | 4314 | 781 | 2042 | 1491 | 27.7% | 1.10 | +0.17% | +749.30% |

## Verdict directionnel

**ÉGAL** : le veto n'aurait pas changé matériellement la performance moyenne par trade

## ⚠️ Paires au résultat invraisemblable

Ces paires gagnent (ou perdent) **100 % du temps**, alors que l'ensemble gagne 38.2 %. Presque sûrement un artefact de log, pas un résultat.

| Paire | n | mean PnL% |
|---|---:|---:|
| `DASH/USD` | 18 | -12.77% |

> Elles sont **conservées** dans les chiffres ci-dessus — écarter des données est une décision de méthode qui revient à l'humain. Mais toute moyenne les incluant est à lire avec ça en tête : le 22/08, quatre d'entre elles portaient les trois quarts de l'écart annoncé, et l'effet disparaissait sans elles.

## Détail par règle de veto

| Règle | n | n_tp | n_sl | mean PnL% |
|---|---:|---:|---:|---:|
| `gdelt_stress` | 66 | 9 | 23 | +0.42% |
| `iran_hormuz` | 7 | 0 | 6 | -1.86% |

## Détail par pair

| Pair | n | n_tp | n_sl | n_timeout | mean PnL% |
|---|---:|---:|---:|---:|---:|
| USD/CAD | 274 | 70 | 114 | 90 | +0.05% |
| GBP/USD | 268 | 52 | 115 | 101 | -0.01% |
| AUD/USD | 252 | 33 | 154 | 65 | -0.13% |
| EUR/USD | 248 | 34 | 150 | 64 | -0.13% |
| EUR/GBP | 217 | 44 | 128 | 45 | -0.11% |
| USD/CHF | 200 | 46 | 87 | 67 | +0.03% |
| USD/JPY | 200 | 20 | 112 | 68 | -0.15% |
| EUR/JPY | 194 | 23 | 102 | 69 | -0.16% |
| GBP/JPY | 188 | 16 | 100 | 72 | -0.13% |
| WTI/USD | 168 | 24 | 84 | 60 | -0.39% |
| XAU/USD | 166 | 36 | 68 | 62 | +0.08% |
| XAG/USD | 111 | 6 | 71 | 34 | -1.46% |
| UNI/USD | 88 | 32 | 26 | 30 | +6.13% |
| SEI/USD | 84 | 14 | 48 | 22 | +1.09% |
| XRP/USD | 78 | 24 | 36 | 18 | -0.45% |
| ARB/USD | 78 | 18 | 32 | 28 | +2.95% |
| ETH/USD | 74 | 8 | 28 | 38 | +0.02% |
| LINK/USD | 74 | 26 | 30 | 18 | +2.71% |
| HBAR/USD | 70 | 20 | 32 | 18 | +0.90% |
| LDO/USD | 70 | 20 | 18 | 32 | +2.45% |
| ENS/USD | 68 | 8 | 40 | 20 | -2.55% |
| XLM/USD | 66 | 10 | 38 | 18 | -1.69% |
| DOGE/USD | 64 | 22 | 26 | 16 | -0.20% |
| ALGO/USD | 62 | 2 | 30 | 30 | -0.83% |
| BTC/USD | 61 | 12 | 24 | 25 | +0.45% |
| PAXG/USD | 60 | 10 | 36 | 14 | -0.69% |
| LTC/USD | 60 | 14 | 18 | 28 | +1.57% |
| AAVE/USD | 58 | 14 | 24 | 20 | +0.62% |
| MANA/USD | 58 | 16 | 18 | 24 | +1.42% |
| SOL/USD | 56 | 10 | 22 | 24 | +2.54% |
| ETHFI/USD | 52 | 12 | 14 | 26 | +3.82% |
| BNB/USD | 50 | 4 | 14 | 32 | -0.04% |
| DOT/USD | 48 | 8 | 16 | 24 | -1.42% |
| ADA/USD | 48 | 10 | 22 | 16 | -1.92% |
| CRV/USD | 46 | 8 | 12 | 26 | +1.21% |
| XLK | 44 | 4 | 14 | 26 | -0.47% |
| XLE | 44 | 8 | 6 | 30 | +1.73% |
| ZEC/USD | 42 | 4 | 24 | 14 | -1.86% |
| SUI/USD | 42 | 8 | 22 | 12 | +4.01% |
| TAO/USD | 38 | 6 | 14 | 18 | -2.29% |
| XLRE | 36 | 8 | 24 | 4 | -0.14% |
| XLU | 34 | 6 | 16 | 12 | -0.10% |
| INJ/USD | 32 | 2 | 10 | 20 | -1.93% |
| XLF | 30 | 8 | 10 | 12 | +0.47% |
| AVAX/USD | 30 | 8 | 14 | 8 | +0.98% |
| XLB | 28 | 2 | 14 | 12 | -0.36% |
| DASH/USD | 18 | 0 | 14 | 4 | -12.77% |
| XLI | 10 | 0 | 0 | 10 | -0.40% |

## Notes méthodologiques

- `would_veto` est calculé au moment du log Track A (commit `3ac0d70`). Les seuils env vars `GEOPOLITICAL_VETO_*` au moment du log peuvent différer des seuils actuels.
- Les setups antérieurs au 2026-05-08 (commit du snapshot) sont exclus.
- Outcome `TIMEOUT` est compté dans `n_total` mais exclu du PF (pas de gain ni perte franche).
- Track A reste **lecture seule** — le veto n'affecte ni les setups loggés ni les outcomes ; cette analyse est purement contrefactuelle.
- Pour décision gate S6 (2026-06-06), viser `n ≥ 100` sur l'ensemble des systèmes Track A.
