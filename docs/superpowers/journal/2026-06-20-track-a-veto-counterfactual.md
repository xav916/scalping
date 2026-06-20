# 2026-06-20 — Track A × veto contrefactuel (auto)

**Sample :** 106 réconciliés (CRÉDIBLE — analyse statistique fiable)
**Verdict :** veto_would_help

> ⚠️ **Signal détecté** : le veto géopolitique aurait aidé (réduit les faux trades).
> À intégrer dans la décision gate S6.

# Track A × Veto géopolitique — analyse contrefactuelle

**Généré :** 2026-06-20T06:01:39+00:00
**Source :** `shadow_setups` filtre `outcome IS NOT NULL AND geopolitical_features_json IS NOT NULL`
**Échantillon :** 106 setups réconciliés
**Confiance échantillon :** CRÉDIBLE — analyse statistique fiable

## Vue d'ensemble

| Groupe | n | n_tp | n_sl | n_timeout | win_rate | PF | mean PnL% | total PnL% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Tous | 106 | 8 | 66 | 32 | 10.8% | 0.41 | -1.42% | -150.73% |
| Would VETO | 7 | 0 | 6 | 1 | 0.0% | 0.26 | -1.86% | -13.04% |
| Would PASS | 99 | 8 | 60 | 31 | 11.8% | 0.43 | -1.39% | -137.68% |

## Verdict directionnel

**LE VETO AURAIT AIDÉ** : les setups que le veto aurait skip ont une mean PnL de -1.86% vs -1.39% pour les autres (écart +0.47% par trade en faveur du veto)

## Détail par règle de veto

| Règle | n | n_tp | n_sl | mean PnL% |
|---|---:|---:|---:|---:|
| `iran_hormuz` | 7 | 0 | 6 | -1.86% |

## Détail par pair

| Pair | n | n_tp | n_sl | n_timeout | mean PnL% |
|---|---:|---:|---:|---:|---:|
| WTI/USD | 32 | 4 | 28 | 0 | -2.77% |
| XAU/USD | 30 | 4 | 18 | 8 | -0.68% |
| XAG/USD | 22 | 0 | 14 | 8 | -1.19% |
| XLK | 14 | 0 | 4 | 10 | -2.32% |
| ETH/USD | 4 | 0 | 2 | 2 | +3.81% |
| XLI | 4 | 0 | 0 | 4 | +0.41% |

## Notes méthodologiques

- `would_veto` est calculé au moment du log Track A (commit `3ac0d70`). Les seuils env vars `GEOPOLITICAL_VETO_*` au moment du log peuvent différer des seuils actuels.
- Les setups antérieurs au 2026-05-08 (commit du snapshot) sont exclus.
- Outcome `TIMEOUT` est compté dans `n_total` mais exclu du PF (pas de gain ni perte franche).
- Track A reste **lecture seule** — le veto n'affecte ni les setups loggés ni les outcomes ; cette analyse est purement contrefactuelle.
- Pour décision gate S6 (2026-06-06), viser `n ≥ 100` sur l'ensemble des systèmes Track A.
