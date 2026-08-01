# 2026-08-01 — Track A × veto contrefactuel (auto)

**Sample :** 257 réconciliés (CRÉDIBLE — analyse statistique fiable)
**Verdict :** neutral

# Track A × Veto géopolitique — analyse contrefactuelle

**Généré :** 2026-08-01T06:01:44+00:00
**Source :** `shadow_setups` filtre `outcome IS NOT NULL AND geopolitical_features_json IS NOT NULL`
**Échantillon :** 257 setups réconciliés
**Confiance échantillon :** CRÉDIBLE — analyse statistique fiable

## Vue d'ensemble

| Groupe | n | n_tp | n_sl | n_timeout | win_rate | PF | mean PnL% | total PnL% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Tous | 257 | 24 | 136 | 97 | 15.0% | 0.55 | -0.83% | -214.34% |
| Would VETO | 9 | 0 | 6 | 3 | 0.0% | 0.58 | -0.87% | -7.84% |
| Would PASS | 248 | 24 | 130 | 94 | 15.6% | 0.55 | -0.83% | -206.49% |

## Verdict directionnel

**ÉGAL** : le veto n'aurait pas changé matériellement la performance moyenne par trade

## Détail par règle de veto

| Règle | n | n_tp | n_sl | mean PnL% |
|---|---:|---:|---:|---:|
| `iran_hormuz` | 7 | 0 | 6 | -1.86% |
| `gdelt_stress` | 2 | 0 | 0 | +2.60% |

## Détail par pair

| Pair | n | n_tp | n_sl | n_timeout | mean PnL% |
|---|---:|---:|---:|---:|---:|
| WTI/USD | 100 | 10 | 66 | 24 | -1.20% |
| XAU/USD | 90 | 14 | 44 | 32 | -0.46% |
| XAG/USD | 22 | 0 | 14 | 8 | -1.19% |
| ETH/USD | 21 | 0 | 6 | 15 | +0.43% |
| XLK | 18 | 0 | 6 | 12 | -2.10% |
| XLI | 6 | 0 | 0 | 6 | +0.25% |

## Notes méthodologiques

- `would_veto` est calculé au moment du log Track A (commit `3ac0d70`). Les seuils env vars `GEOPOLITICAL_VETO_*` au moment du log peuvent différer des seuils actuels.
- Les setups antérieurs au 2026-05-08 (commit du snapshot) sont exclus.
- Outcome `TIMEOUT` est compté dans `n_total` mais exclu du PF (pas de gain ni perte franche).
- Track A reste **lecture seule** — le veto n'affecte ni les setups loggés ni les outcomes ; cette analyse est purement contrefactuelle.
- Pour décision gate S6 (2026-06-06), viser `n ≥ 100` sur l'ensemble des systèmes Track A.
