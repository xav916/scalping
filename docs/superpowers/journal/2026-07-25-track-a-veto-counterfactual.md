# 2026-07-25 — Track A × veto contrefactuel (auto)

**Sample :** 222 réconciliés (CRÉDIBLE — analyse statistique fiable)
**Verdict :** veto_would_help

> ⚠️ **Signal détecté** : le veto géopolitique aurait aidé (setups bloqués = moins de pertes).
> À intégrer dans la décision gate S6.

# Track A × Veto géopolitique — analyse contrefactuelle

**Généré :** 2026-07-25T06:01:36+00:00
**Source :** `shadow_setups` filtre `outcome IS NOT NULL AND geopolitical_features_json IS NOT NULL`
**Échantillon :** 222 setups réconciliés
**Confiance échantillon :** CRÉDIBLE — analyse statistique fiable

## Vue d'ensemble

| Groupe | n | n_tp | n_sl | n_timeout | win_rate | PF | mean PnL% | total PnL% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Tous | 222 | 20 | 116 | 86 | 14.7% | 0.61 | -0.73% | -161.82% |
| Would VETO | 8 | 0 | 6 | 2 | 0.0% | 0.61 | -0.86% | -6.85% |
| Would PASS | 214 | 20 | 110 | 84 | 15.4% | 0.61 | -0.72% | -154.97% |

## Verdict directionnel

**LE VETO AURAIT AIDÉ** : les setups que le veto aurait skip ont une mean PnL de -0.86% vs -0.72% pour les autres (écart +0.13% par trade en faveur du veto)

## Détail par règle de veto

| Règle | n | n_tp | n_sl | mean PnL% |
|---|---:|---:|---:|---:|
| `iran_hormuz` | 7 | 0 | 6 | -1.86% |
| `gdelt_stress` | 1 | 0 | 0 | +6.19% |

## Détail par pair

| Pair | n | n_tp | n_sl | n_timeout | mean PnL% |
|---|---:|---:|---:|---:|---:|
| WTI/USD | 92 | 8 | 60 | 24 | -1.06% |
| XAU/USD | 68 | 12 | 30 | 26 | -0.23% |
| XAG/USD | 22 | 0 | 14 | 8 | -1.19% |
| ETH/USD | 18 | 0 | 6 | 12 | +0.84% |
| XLK | 16 | 0 | 6 | 10 | -2.44% |
| XLI | 6 | 0 | 0 | 6 | +0.25% |

## Notes méthodologiques

- `would_veto` est calculé au moment du log Track A (commit `3ac0d70`). Les seuils env vars `GEOPOLITICAL_VETO_*` au moment du log peuvent différer des seuils actuels.
- Les setups antérieurs au 2026-05-08 (commit du snapshot) sont exclus.
- Outcome `TIMEOUT` est compté dans `n_total` mais exclu du PF (pas de gain ni perte franche).
- Track A reste **lecture seule** — le veto n'affecte ni les setups loggés ni les outcomes ; cette analyse est purement contrefactuelle.
- Pour décision gate S6 (2026-06-06), viser `n ≥ 100` sur l'ensemble des systèmes Track A.
