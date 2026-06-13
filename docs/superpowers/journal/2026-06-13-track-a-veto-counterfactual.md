# 2026-06-13 — Track A × veto contrefactuel (auto)

**Sample :** 76 réconciliés (EXPLOITABLE — signal directionnel possible, intervalles larges)
**Verdict :** insufficient

---

# Track A × Veto géopolitique — analyse contrefactuelle

**Généré :** 2026-06-13T06:01:46+00:00
**Source :** `shadow_setups` filtre `outcome IS NOT NULL AND geopolitical_features_json IS NOT NULL`
**Échantillon :** 76 setups réconciliés
**Confiance échantillon :** EXPLOITABLE — signal directionnel possible, intervalles larges

## Vue d'ensemble

| Groupe | n | n_tp | n_sl | n_timeout | win_rate | PF | mean PnL% | total PnL% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Tous | 76 | 6 | 48 | 22 | 11.1% | 0.18 | -2.23% | -169.75% |
| Would VETO | 0 | 0 | 0 | 0 | — | — | — | +0.00% |
| Would PASS | 76 | 6 | 48 | 22 | 11.1% | 0.18 | -2.23% | -169.75% |

## Verdict directionnel

Aucun setup réconcilié n'aurait été veto'd par les règles actuelles. Le contexte géopolitique au moment des entrées n'a déclenché aucune règle.

## Détail par pair

| Pair | n | n_tp | n_sl | n_timeout | mean PnL% |
|---|---:|---:|---:|---:|---:|
| WTI/USD | 24 | 2 | 22 | 0 | -3.34% |
| XAU/USD | 20 | 4 | 10 | 6 | -0.65% |
| XLK | 14 | 0 | 4 | 10 | -2.32% |
| XAG/USD | 12 | 0 | 10 | 2 | -3.21% |
| XLI | 4 | 0 | 0 | 4 | +0.41% |
| ETH/USD | 2 | 0 | 2 | 0 | -3.71% |

## Notes méthodologiques

- `would_veto` est calculé au moment du log Track A (commit `3ac0d70`). Les seuils env vars `GEOPOLITICAL_VETO_*` au moment du log peuvent différer des seuils actuels.
- Les setups antérieurs au 2026-05-08 (commit du snapshot) sont exclus.
- Outcome `TIMEOUT` est compté dans `n_total` mais exclu du PF (pas de gain ni perte franche).
- Track A reste **lecture seule** — le veto n'affecte ni les setups loggés ni les outcomes ; cette analyse est purement contrefactuelle.
- Pour décision gate S6 (2026-06-06), viser `n ≥ 100` sur l'ensemble des systèmes Track A.
