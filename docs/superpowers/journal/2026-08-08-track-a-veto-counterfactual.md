# 2026-08-08 — Track A × veto contrefactuel (auto)

**Sample :** 297 réconciliés (CRÉDIBLE — analyse statistique fiable)
**Verdict :** veto_would_help

> ⚠️ **Signal détecté** : le veto géopolitique aurait aidé.
> À intégrer dans la décision gate S6.

---

# Track A × Veto géopolitique — analyse contrefactuelle

**Généré :** 2026-08-08T06:04:01+00:00
**Source :** `shadow_setups` filtre `outcome IS NOT NULL AND geopolitical_features_json IS NOT NULL`
**Échantillon :** 297 setups réconciliés
**Confiance échantillon :** CRÉDIBLE — analyse statistique fiable

## Vue d'ensemble

| Groupe | n | n_tp | n_sl | n_timeout | win_rate | PF | mean PnL% | total PnL% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Tous | 297 | 46 | 150 | 101 | 23.5% | 0.63 | -0.65% | -193.64% |
| Would VETO | 9 | 0 | 6 | 3 | 0.0% | 0.58 | -0.87% | -7.84% |
| Would PASS | 288 | 46 | 144 | 98 | 24.2% | 0.63 | -0.65% | -185.79% |

## Verdict directionnel

**LE VETO AURAIT AIDÉ** : les setups que le veto aurait skip ont une mean PnL de -0.87% vs -0.65% pour les autres (écart +0.23% par trade en faveur du veto)

## Détail par règle de veto

| Règle | n | n_tp | n_sl | mean PnL% |
|---|---:|---:|---:|---:|
| `iran_hormuz` | 7 | 0 | 6 | -1.86% |
| `gdelt_stress` | 2 | 0 | 0 | +2.60% |

## Détail par pair

| Pair | n | n_tp | n_sl | n_timeout | mean PnL% |
|---|---:|---:|---:|---:|---:|
| WTI/USD | 120 | 16 | 78 | 26 | -1.08% |
| XAU/USD | 108 | 30 | 44 | 34 | -0.05% |
| XAG/USD | 22 | 0 | 14 | 8 | -1.19% |
| ETH/USD | 21 | 0 | 6 | 15 | +0.43% |
| XLK | 20 | 0 | 8 | 12 | -2.17% |
| XLI | 6 | 0 | 0 | 6 | +0.25% |

## Notes méthodologiques

- `would_veto` est calculé au moment du log Track A (commit `3ac0d70`). Les seuils env vars `GEOPOLITICAL_VETO_*` au moment du log peuvent différer des seuils actuels.
- Les setups antérieurs au 2026-05-08 (commit du snapshot) sont exclus.
- Outcome `TIMEOUT` est compté dans `n_total` mais exclu du PF (pas de gain ni perte franche).
- Track A reste **lecture seule** — le veto n'affecte ni les setups loggés ni les outcomes ; cette analyse est purement contrefactuelle.
- Pour décision gate S6 (2026-06-06), viser `n ≥ 100` sur l'ensemble des systèmes Track A.
