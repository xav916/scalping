> 🚨 **ALERT VERDICT CHANGED** — direction_verdict = `neutral`, n_total = `4441`. Le veto a quitté le statut 'insufficient'.

# Track A × Veto géopolitique — analyse contrefactuelle

**Généré :** 2026-11-07T08:10:41+00:00
**Source :** `shadow_setups` filtre `outcome IS NOT NULL AND geopolitical_features_json IS NOT NULL`
**Échantillon :** 4441 setups réconciliés
**Groupe décisif (would VETO) :** 73 setups
**Confiance :** EXPLOITABLE — signal directionnel possible, intervalles larges

## Vue d'ensemble

| Groupe | n | n_tp | n_sl | n_timeout | win_rate | PF | mean PnL% | total PnL% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Tous | 4441 | 802 | 2097 | 1542 | 27.7% | 1.10 | +0.17% | +748.33% |
| Would VETO | 73 | 9 | 29 | 35 | 23.7% | 1.30 | +0.20% | +14.39% |
| Would PASS | 4368 | 793 | 2068 | 1507 | 27.7% | 1.10 | +0.17% | +733.94% |

## Verdict directionnel

**ÉGAL** : le veto n'aurait pas changé matériellement la performance moyenne par trade

## ⚠️ Paires au résultat invraisemblable

Ces paires gagnent (ou perdent) **100 % du temps**, alors que l'ensemble gagne 38.1 %. Presque sûrement un artefact de log, pas un résultat.

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
| AUD/USD | 254 | 33 | 154 | 67 | -0.13% |
| EUR/USD | 250 | 34 | 150 | 66 | -0.13% |
| EUR/GBP | 219 | 44 | 130 | 45 | -0.11% |
| USD/JPY | 208 | 20 | 112 | 76 | -0.15% |
| USD/CHF | 200 | 46 | 87 | 67 | +0.03% |
| EUR/JPY | 194 | 23 | 102 | 69 | -0.16% |
| GBP/JPY | 188 | 16 | 100 | 72 | -0.13% |
| WTI/USD | 172 | 24 | 84 | 64 | -0.37% |
| XAU/USD | 166 | 36 | 68 | 62 | +0.08% |
| XAG/USD | 111 | 6 | 71 | 34 | -1.46% |
| UNI/USD | 90 | 34 | 26 | 30 | +6.21% |
| SEI/USD | 86 | 14 | 50 | 22 | +0.87% |
| XRP/USD | 80 | 24 | 38 | 18 | -0.57% |
| ARB/USD | 78 | 18 | 32 | 28 | +2.95% |
| LINK/USD | 76 | 28 | 30 | 18 | +2.90% |
| ETH/USD | 74 | 8 | 28 | 38 | +0.02% |
| HBAR/USD | 70 | 20 | 32 | 18 | +0.90% |
| LDO/USD | 70 | 20 | 18 | 32 | +2.45% |
| XLM/USD | 68 | 10 | 40 | 18 | -1.75% |
| ENS/USD | 68 | 8 | 40 | 20 | -2.55% |
| DOGE/USD | 66 | 22 | 28 | 16 | -0.35% |
| BTC/USD | 63 | 12 | 26 | 25 | +0.34% |
| PAXG/USD | 62 | 10 | 38 | 14 | -0.69% |
| LTC/USD | 62 | 14 | 20 | 28 | +1.34% |
| ALGO/USD | 62 | 2 | 30 | 30 | -0.83% |
| AAVE/USD | 60 | 16 | 24 | 20 | +1.03% |
| SOL/USD | 58 | 10 | 24 | 24 | +2.30% |
| MANA/USD | 58 | 16 | 18 | 24 | +1.42% |
| ETHFI/USD | 54 | 12 | 16 | 26 | +3.33% |
| BNB/USD | 50 | 4 | 14 | 32 | -0.04% |
| ADA/USD | 50 | 10 | 24 | 16 | -2.14% |
| DOT/USD | 48 | 8 | 16 | 24 | -1.42% |
| CRV/USD | 46 | 8 | 12 | 26 | +1.21% |
| XLK | 44 | 4 | 14 | 26 | -0.47% |
| XLE | 44 | 8 | 6 | 30 | +1.73% |
| ZEC/USD | 42 | 4 | 24 | 14 | -1.86% |
| SUI/USD | 42 | 8 | 22 | 12 | +4.01% |
| TAO/USD | 40 | 6 | 16 | 18 | -2.64% |
| XLRE | 36 | 8 | 24 | 4 | -0.14% |
| XLU | 34 | 6 | 16 | 12 | -0.10% |
| INJ/USD | 34 | 4 | 10 | 20 | -0.94% |
| AVAX/USD | 32 | 10 | 14 | 8 | +1.48% |
| XLB | 30 | 4 | 14 | 12 | -0.13% |
| XLF | 30 | 8 | 10 | 12 | +0.47% |
| DASH/USD | 18 | 0 | 14 | 4 | -12.77% |
| XLI | 12 | 0 | 2 | 10 | -1.04% |

## Notes méthodologiques

- `would_veto` est calculé au moment du log Track A (commit `3ac0d70`). Les seuils env vars `GEOPOLITICAL_VETO_*` au moment du log peuvent différer des seuils actuels.
- Les setups antérieurs au 2026-05-08 (commit du snapshot) sont exclus.
- Outcome `TIMEOUT` est compté dans `n_total` mais exclu du PF (pas de gain ni perte franche).
- Track A reste **lecture seule** — le veto n'affecte ni les setups loggés ni les outcomes ; cette analyse est purement contrefactuelle.
- Pour décision gate S6 (2026-06-06), viser `n ≥ 100` sur l'ensemble des systèmes Track A.
