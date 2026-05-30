# Track A × Veto géopolitique — analyse contrefactuelle

**Généré :** 2026-05-30T07:08:34+00:00
**Source :** `shadow_setups` filtre `outcome IS NOT NULL AND geopolitical_features_json IS NOT NULL`
**Échantillon :** 26 setups réconciliés
**Confiance échantillon :** INSUFFISANT — observer mais ne pas trancher

## Vue d'ensemble

| Groupe | n | n_tp | n_sl | n_timeout | win_rate | PF | mean PnL% | total PnL% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Tous | 26 | 0 | 24 | 2 | 0.0% | 0.00 | -3.01% | -78.29% |
| Would VETO | 0 | 0 | 0 | 0 | — | — | — | +0.00% |
| Would PASS | 26 | 0 | 24 | 2 | 0.0% | 0.00 | -3.01% | -78.29% |

## Verdict directionnel

Aucun setup réconcilié n'aurait été veto'd par les règles actuelles. Le contexte géopolitique au moment des entrées n'a déclenché aucune règle.

## Détail par pair

| Pair | n | n_tp | n_sl | n_timeout | mean PnL% |
|---|---:|---:|---:|---:|---:|
| XAU/USD | 10 | 0 | 8 | 2 | -1.12% |
| WTI/USD | 8 | 0 | 8 | 0 | -4.52% |
| XAG/USD | 6 | 0 | 6 | 0 | -3.92% |
| ETH/USD | 2 | 0 | 2 | 0 | -3.71% |

## Notes méthodologiques

- `would_veto` est calculé au moment du log Track A (commit `3ac0d70`). Les seuils env vars `GEOPOLITICAL_VETO_*` au moment du log peuvent différer des seuils actuels.
- Les setups antérieurs au 2026-05-08 (commit du snapshot) sont exclus.
- Outcome `TIMEOUT` est compté dans `n_total` mais exclu du PF (pas de gain ni perte franche).
- Track A reste **lecture seule** — le veto n'affecte ni les setups loggés ni les outcomes ; cette analyse est purement contrefactuelle.
- Pour décision gate S6 (2026-06-06), viser `n ≥ 100` sur l'ensemble des systèmes Track A.
