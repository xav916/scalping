> 🚨 **ALERT VERDICT CHANGED** — direction_verdict = `veto_would_help`, n_total = `390`. Le veto a quitté le statut 'insufficient'.

# Track A × Veto géopolitique — analyse contrefactuelle

**Généré :** 2026-08-15T07:09:26+00:00
**Source :** `shadow_setups` filtre `outcome IS NOT NULL AND geopolitical_features_json IS NOT NULL`
**Échantillon :** 390 setups réconciliés
**Confiance échantillon :** CRÉDIBLE — analyse statistique fiable

## Vue d'ensemble

| Groupe | n | n_tp | n_sl | n_timeout | win_rate | PF | mean PnL% | total PnL% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Tous | 390 | 66 | 182 | 142 | 26.6% | 0.84 | -0.24% | -95.40% |
| Would VETO | 10 | 0 | 6 | 4 | 0.0% | 0.60 | -0.75% | -7.51% |
| Would PASS | 380 | 66 | 176 | 138 | 27.3% | 0.85 | -0.23% | -87.89% |

## Verdict directionnel

**LE VETO AURAIT AIDÉ** : les setups que le veto aurait skip ont une mean PnL de -0.75% vs -0.23% pour les autres (écart +0.52% par trade en faveur du veto)

## Détail par règle de veto

| Règle | n | n_tp | n_sl | mean PnL% |
|---|---:|---:|---:|---:|
| `iran_hormuz` | 7 | 0 | 6 | -1.86% |
| `gdelt_stress` | 3 | 0 | 0 | +1.85% |

## Détail par pair

| Pair | n | n_tp | n_sl | n_timeout | mean PnL% |
|---|---:|---:|---:|---:|---:|
| WTI/USD | 130 | 20 | 78 | 32 | -0.75% |
| XAU/USD | 124 | 32 | 44 | 48 | +0.16% |
| XLK | 24 | 0 | 8 | 16 | -1.19% |
| ETH/USD | 22 | 0 | 6 | 16 | +0.42% |
| XAG/USD | 22 | 0 | 14 | 8 | -1.19% |
| USD/CAD | 10 | 2 | 6 | 2 | -0.09% |
| XLI | 6 | 0 | 0 | 6 | +0.25% |
| EUR/USD | 6 | 0 | 0 | 6 | -0.21% |
| AUD/USD | 6 | 0 | 2 | 4 | -0.12% |
| XRP/USD | 6 | 0 | 6 | 0 | -2.94% |
| SEI/USD | 6 | 0 | 6 | 0 | -2.88% |
| XLM/USD | 4 | 0 | 4 | 0 | -3.51% |
| HBAR/USD | 4 | 0 | 4 | 0 | -3.04% |
| EUR/GBP | 4 | 4 | 0 | 0 | +0.27% |
| ARB/USD | 4 | 2 | 2 | 0 | +0.20% |
| GBP/USD | 2 | 0 | 0 | 2 | +0.07% |
| LINK/USD | 2 | 2 | 0 | 0 | +6.46% |
| ETHFI/USD | 2 | 2 | 0 | 0 | +17.88% |
| EUR/JPY | 2 | 0 | 0 | 2 | +0.75% |
| CRV/USD | 2 | 2 | 0 | 0 | +21.09% |
| ENS/USD | 2 | 0 | 2 | 0 | -2.70% |

## Notes méthodologiques

- `would_veto` est calculé au moment du log Track A (commit `3ac0d70`). Les seuils env vars `GEOPOLITICAL_VETO_*` au moment du log peuvent différer des seuils actuels.
- Les setups antérieurs au 2026-05-08 (commit du snapshot) sont exclus.
- Outcome `TIMEOUT` est compté dans `n_total` mais exclu du PF (pas de gain ni perte franche).
- Track A reste **lecture seule** — le veto n'affecte ni les setups loggés ni les outcomes ; cette analyse est purement contrefactuelle.
- Pour décision gate S6 (2026-06-06), viser `n ≥ 100` sur l'ensemble des systèmes Track A.
