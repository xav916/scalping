> 🚨 **ALERT VERDICT CHANGED** — direction_verdict = `veto_would_help`, n_total = `124`. Le veto a quitté le statut 'insufficient'.

# Track A × Veto géopolitique — analyse contrefactuelle

**Généré :** 2026-06-27T07:01:59+00:00
**Source :** `shadow_setups` filtre `outcome IS NOT NULL AND geopolitical_features_json IS NOT NULL`
**Échantillon :** 124 setups réconciliés
**Confiance échantillon :** CRÉDIBLE — analyse statistique fiable

## Vue d'ensemble

| Groupe | n | n_tp | n_sl | n_timeout | win_rate | PF | mean PnL% | total PnL% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Tous | 124 | 10 | 80 | 34 | 11.1% | 0.37 | -1.58% | -195.73% |
| Would VETO | 7 | 0 | 6 | 1 | 0.0% | 0.26 | -1.86% | -13.04% |
| Would PASS | 117 | 10 | 74 | 33 | 11.9% | 0.38 | -1.56% | -182.69% |

## Verdict directionnel

**LE VETO AURAIT AIDÉ** : les setups que le veto aurait skip ont une mean PnL de -1.86% vs -1.56% pour les autres (écart +0.30% par trade en faveur du veto)

## Détail par règle de veto

| Règle | n | n_tp | n_sl | mean PnL% |
|---|---:|---:|---:|---:|
| `iran_hormuz` | 7 | 0 | 6 | -1.86% |

## Détail par pair

| Pair | n | n_tp | n_sl | n_timeout | mean PnL% |
|---|---:|---:|---:|---:|---:|
| WTI/USD | 42 | 6 | 36 | 0 | -2.45% |
| XAU/USD | 34 | 4 | 22 | 8 | -0.74% |
| XAG/USD | 22 | 0 | 14 | 8 | -1.19% |
| XLK | 14 | 0 | 4 | 10 | -2.32% |
| ETH/USD | 6 | 0 | 4 | 2 | -1.79% |
| XLI | 6 | 0 | 0 | 6 | +0.25% |

## Notes méthodologiques

- `would_veto` est calculé au moment du log Track A (commit `3ac0d70`). Les seuils env vars `GEOPOLITICAL_VETO_*` au moment du log peuvent différer des seuils actuels.
- Les setups antérieurs au 2026-05-08 (commit du snapshot) sont exclus.
- Outcome `TIMEOUT` est compté dans `n_total` mais exclu du PF (pas de gain ni perte franche).
- Track A reste **lecture seule** — le veto n'affecte ni les setups loggés ni les outcomes ; cette analyse est purement contrefactuelle.
- Pour décision gate S6 (2026-06-06), viser `n ≥ 100` sur l'ensemble des systèmes Track A.
