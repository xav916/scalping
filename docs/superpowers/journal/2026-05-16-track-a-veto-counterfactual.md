> 🚨 **ALERT VERDICT CHANGED** — direction_verdict = `veto_would_hurt`, n_total = `8`. Le veto a quitté le statut 'insufficient'.

# Track A × Veto géopolitique — analyse contrefactuelle

**Généré :** 2026-05-16T07:05:44+00:00
**Source :** `shadow_setups` filtre `outcome IS NOT NULL AND geopolitical_features_json IS NOT NULL`
**Échantillon :** 8 setups réconciliés
**Confiance échantillon :** DÉRISOIRE — pas d'analyse statistiquement valide possible

## Vue d'ensemble

| Groupe | n | n_tp | n_sl | n_timeout | win_rate | PF | mean PnL% | total PnL% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Tous | 8 | 3 | 5 | 0 | 37.5% | 0.46 | -2.02% | -16.19% |
| Would VETO | 2 | 1 | 1 | 0 | 50.0% | 4.11 | +2.74% | +5.48% |
| Would PASS | 6 | 2 | 4 | 0 | 33.3% | 0.23 | -3.61% | -21.67% |

## Verdict directionnel

**LE VETO AURAIT NUIT** : les setups que le veto aurait skip ont une mean PnL de +2.74% vs -3.61% pour les autres (écart -6.35% par trade — le veto retire des trades gagnants)

## Détail par règle de veto

| Règle | n | n_tp | n_sl | mean PnL% |
|---|---:|---:|---:|---:|
| `iran_hormuz` | 2 | 1 | 1 | +2.74% |

## Détail par pair

| Pair | n | n_tp | n_sl | n_timeout | mean PnL% |
|---|---:|---:|---:|---:|---:|
| XAG/USD | 7 | 3 | 4 | 0 | -2.06% |
| XAU/USD | 1 | 0 | 1 | 0 | -1.76% |

## Notes méthodologiques

- `would_veto` est calculé au moment du log Track A (commit `3ac0d70`). Les seuils env vars `GEOPOLITICAL_VETO_*` au moment du log peuvent différer des seuils actuels.
- Les setups antérieurs au 2026-05-08 (commit du snapshot) sont exclus.
- Outcome `TIMEOUT` est compté dans `n_total` mais exclu du PF (pas de gain ni perte franche).
- Track A reste **lecture seule** — le veto n'affecte ni les setups loggés ni les outcomes ; cette analyse est purement contrefactuelle.
- Pour décision gate S6 (2026-06-06), viser `n ≥ 100` sur l'ensemble des systèmes Track A.
