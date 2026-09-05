# 2026-09-05 — Track A × veto contrefactuel (auto)

**Sample :** 971 réconciliés (INSUFFISANT — observer mais ne pas trancher)
**Verdict :** insufficient

# Track A × Veto géopolitique — analyse contrefactuelle

**Généré :** 2026-09-05T06:01:23+00:00
**Source :** `shadow_setups` filtre `outcome IS NOT NULL AND geopolitical_features_json IS NOT NULL`
**Échantillon :** 971 setups réconciliés
**Groupe décisif (would VETO) :** 29 setups
**Confiance :** INSUFFISANT — observer mais ne pas trancher

## Vue d'ensemble

| Groupe | n | n_tp | n_sl | n_timeout | win_rate | PF | mean PnL% | total PnL% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Tous | 971 | 271 | 389 | 311 | 41.1% | 2.63 | +1.58% | +1536.30% |
| Would VETO | 29 | 5 | 9 | 15 | 35.7% | 1.58 | +0.60% | +17.30% |
| Would PASS | 942 | 266 | 380 | 296 | 41.2% | 2.67 | +1.61% | +1519.00% |

## Verdict directionnel

**ÉCHANTILLON INSUFFISANT POUR TRANCHER** : seuls **29** setups auraient été bloqués par le veto (seuil : 30). Les 942 autres ne servent que de témoin — c'est le plus petit groupe qui borne la conclusion.

> Aucun verdict directionnel n'est énoncé à ce stade. Un écart calculé sur 29 observations est régulièrement reproduit par un tirage au hasard de même taille.

## ⚠️ Paires au résultat invraisemblable

Ces paires gagnent (ou perdent) **100 % du temps**, alors que l'ensemble gagne 50.5 %. Presque sûrement un artefact de log, pas un résultat.

| Paire | n | mean PnL% |
|---|---:|---:|
| `LDO/USD` | 22 | +10.45% |
| `LINK/USD` | 18 | +15.02% |
| `ETHFI/USD` | 16 | +20.60% |
| `CRV/USD` | 12 | +14.87% |
| `BNB/USD` | 8 | +5.29% |
| `SOL/USD` | 8 | +15.27% |
| `DOGE/USD` | 8 | +13.08% |

> Elles sont **conservées** dans les chiffres ci-dessus — écarter des données est une décision de méthode qui revient à l'humain. Mais toute moyenne les incluant est à lire avec ça en tête : le 22/08, quatre d'entre elles portaient les trois quarts de l'écart annoncé, et l'effet disparaissait sans elles.

## Détail par règle de veto

| Règle | n | n_tp | n_sl | mean PnL% |
|---|---:|---:|---:|---:|
| `gdelt_stress` | 22 | 5 | 3 | +1.38% |
| `iran_hormuz` | 7 | 0 | 6 | -1.86% |

## Détail par pair

| Pair | n | n_tp | n_sl | n_timeout | mean PnL% |
|---|---:|---:|---:|---:|---:|
| XAU/USD | 158 | 34 | 64 | 60 | +0.09% |
| WTI/USD | 156 | 24 | 78 | 54 | -0.31% |
| USD/CAD | 48 | 2 | 44 | 2 | -0.17% |
| EUR/USD | 34 | 16 | 6 | 12 | +0.16% |
| GBP/USD | 32 | 12 | 2 | 18 | +0.22% |
| ETH/USD | 31 | 4 | 7 | 20 | +2.10% |
| AUD/USD | 26 | 8 | 10 | 8 | -0.04% |
| USD/JPY | 26 | 0 | 14 | 12 | -0.23% |
| XLK | 24 | 0 | 8 | 16 | -1.19% |
| XAG/USD | 22 | 0 | 14 | 8 | -1.19% |
| XRP/USD | 22 | 14 | 8 | 0 | +3.72% |
| SEI/USD | 22 | 2 | 20 | 0 | -1.75% |
| LDO/USD | 22 | 16 | 0 | 6 | +10.45% |
| GBP/JPY | 22 | 4 | 4 | 14 | +0.24% |
| XLM/USD | 20 | 2 | 18 | 0 | -1.73% |
| HBAR/USD | 20 | 6 | 14 | 0 | +1.11% |
| EUR/GBP | 20 | 4 | 4 | 12 | +0.04% |
| UNI/USD | 20 | 12 | 8 | 0 | +4.47% |
| LINK/USD | 18 | 18 | 0 | 0 | +15.02% |
| EUR/JPY | 18 | 3 | 5 | 10 | +0.14% |
| ARB/USD | 18 | 8 | 8 | 2 | +2.05% |
| AAVE/USD | 18 | 8 | 10 | 0 | +0.23% |
| ETHFI/USD | 16 | 10 | 0 | 6 | +20.60% |
| BTC/USD | 14 | 4 | 5 | 5 | +2.53% |
| ENS/USD | 14 | 2 | 12 | 0 | -1.25% |
| CRV/USD | 12 | 4 | 0 | 8 | +14.87% |
| USD/CHF | 12 | 4 | 2 | 6 | +0.20% |
| ALGO/USD | 12 | 2 | 10 | 0 | -1.37% |
| MANA/USD | 12 | 6 | 4 | 2 | +2.01% |
| LTC/USD | 10 | 8 | 2 | 0 | +4.88% |
| DOT/USD | 10 | 6 | 4 | 0 | +2.25% |
| BNB/USD | 8 | 2 | 0 | 6 | +5.29% |
| SOL/USD | 8 | 8 | 0 | 0 | +15.27% |
| DOGE/USD | 8 | 8 | 0 | 0 | +13.08% |
| XLE | 8 | 0 | 0 | 8 | -0.57% |
| XLI | 6 | 0 | 0 | 6 | +0.25% |
| PAXG/USD | 6 | 2 | 0 | 4 | +2.04% |
| XLU | 6 | 2 | 4 | 0 | -0.96% |
| XLF | 4 | 0 | 0 | 4 | -0.58% |
| XLRE | 4 | 4 | 0 | 0 | +1.57% |
| XLB | 2 | 0 | 0 | 2 | -0.62% |
| ADA/USD | 2 | 2 | 0 | 0 | +5.16% |

## Notes méthodologiques

- `would_veto` est calculé au moment du log Track A (commit `3ac0d70`). Les seuils env vars `GEOPOLITICAL_VETO_*` au moment du log peuvent différer des seuils actuels.
- Les setups antérieurs au 2026-05-08 (commit du snapshot) sont exclus.
- Outcome `TIMEOUT` est compté dans `n_total` mais exclu du PF (pas de gain ni perte franche).
- Track A reste **lecture seule** — le veto n'affecte ni les setups loggés ni les outcomes ; cette analyse est purement contrefactuelle.
- Pour décision gate S6 (2026-06-06), viser `n ≥ 100` sur l'ensemble des systèmes Track A.
