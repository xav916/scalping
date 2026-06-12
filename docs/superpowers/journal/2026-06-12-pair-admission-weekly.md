# Pair Admission — Weekly Report

Généré : 2026-06-12 19:23 Paris · auto-routine hebdo

## Snapshot états (totals)

- **AUTO_EXEC** : 5
- **TELEGRAM** : 0
- **PAUSED** : 8
- **OBSERVED** : 6
- **DEMOTED** : 17

## Transitions des 7 derniers jours

| When (UTC) | Pair | Dir | State | By | Reason |
|---|---|---|---|---|---|
| 2026-06-12 15:16:59 | `ETH/USD` | buy | **PAUSED** | auto | auto-pause: pnl_pct -6.71% < -3% |
| 2026-06-12 13:04:58 | `WTI/USD` | buy | **PAUSED** | auto | auto-pause: pnl_pct -28.05% < -3% |
| 2026-06-12 11:06:32 | `XAU/USD` | buy | **PAUSED** | auto | auto-pause: pnl_pct -120.23% < -3% |
| 2026-06-12 10:57:51 | `WTI/USD` | buy | **AUTO_EXEC** | admin:xavier-manual | manual override 2026-06-12 : activate Live IC Markets test, accept risk of re-pause |
| 2026-06-12 10:57:51 | `ETH/USD` | buy | **AUTO_EXEC** | admin:xavier-manual | manual override 2026-06-12 : activate Live IC Markets test, accept risk of re-pause |
| 2026-06-12 10:57:50 | `XAU/USD` | buy | **AUTO_EXEC** | admin:xavier-manual | manual override 2026-06-12 : activate Live IC Markets test, accept risk of re-pause |
| 2026-06-12 04:15:46 | `ETH/USD` | buy | **PAUSED** | auto | auto-pause: pnl_pct -98.49% < -3% |
| 2026-06-11 23:15:47 | `WTI/USD` | buy | **OBSERVED** | auto | auto-demote: max_dd -13.42 < -10.0 |
| 2026-06-10 07:41:49 | `WTI/USD` | buy | **TELEGRAM** | auto | auto-promote: all promote criteria met → eligible for TELEGRAM |
| 2026-06-09 20:24:06 | `ETH/USD` | buy | **AUTO_EXEC** | auto | auto-promote: all promote criteria met → eligible for AUTO_EXEC |
| 2026-06-09 00:24:07 | `XAU/USD` | buy | **PAUSED** | auto | auto-pause: pnl_pct -125.18% < -3% |
| 2026-06-08 23:24:07 | `XAU/USD` | buy | **AUTO_EXEC** | auto | cool-off 14j expired, re-evaluating live |
| 2026-06-08 17:24:06 | `BTC/USD` | sell | **DEMOTED** | auto | auto-demote: 2 pauses on 60d (max 2) |
| 2026-06-08 08:24:07 | `EUR/USD` | sell | **DEMOTED** | auto | auto-demote: 2 pauses on 60d (max 2) |
| 2026-06-08 06:24:07 | `USD/CHF` | buy | **DEMOTED** | auto | auto-demote: 2 pauses on 60d (max 2) |
| 2026-06-08 05:24:06 | `GBP/JPY` | sell | **DEMOTED** | auto | auto-demote: 2 pauses on 60d (max 2) |
| 2026-06-08 04:24:06 | `EUR/JPY` | sell | **DEMOTED** | auto | auto-demote: 2 pauses on 60d (max 2) |
| 2026-06-08 03:24:07 | `USD/JPY` | buy | **DEMOTED** | auto | auto-demote: 2 pauses on 60d (max 2) |
| 2026-06-08 03:24:06 | `AUD/USD` | sell | **DEMOTED** | auto | auto-demote: 2 pauses on 60d (max 2) |
| 2026-06-07 14:24:06 | `EUR/JPY` | buy | **DEMOTED** | auto | auto-demote: 2 pauses on 60d (max 2) |
| 2026-06-07 13:24:07 | `USD/CAD` | sell | **DEMOTED** | auto | auto-demote: 2 pauses on 60d (max 2) |
| 2026-06-07 13:24:06 | `GBP/JPY` | buy | **DEMOTED** | auto | auto-demote: 2 pauses on 60d (max 2) |
| 2026-06-07 10:24:07 | `XAG/USD` | buy | **DEMOTED** | auto | auto-demote: 2 pauses on 60d (max 2) |
| 2026-06-07 05:24:06 | `EUR/GBP` | buy | **DEMOTED** | auto | auto-demote: 2 pauses on 60d (max 2) |
| 2026-06-07 03:24:07 | `EUR/USD` | buy | **DEMOTED** | auto | auto-demote: 2 pauses on 60d (max 2) |
| 2026-06-07 03:24:06 | `AUD/USD` | buy | **DEMOTED** | auto | auto-demote: 2 pauses on 60d (max 2) |
| 2026-06-07 01:24:07 | `USD/CHF` | sell | **DEMOTED** | auto | auto-demote: 2 pauses on 60d (max 2) |
| 2026-06-06 20:24:07 | `USD/JPY` | sell | **DEMOTED** | auto | auto-demote: 2 pauses on 60d (max 2) |

## 🎯 Candidats promotion manuelle (TELEGRAM → AUTO_EXEC)

_TELEGRAM avec score sain : critères AUTO_EXEC franchis sur fenêtre 30 trades._

_Aucun candidat cette semaine._

## ⚠️ Candidats pause (AUTO_EXEC en zone warning -3% < PnL% < -1%)

_Aucun candidat cette semaine._

## Matrice complète (pair × direction)

| Pair | BUY state | BUY n / PnL% | SELL state | SELL n / PnL% |
|---|---|---|---|---|
| `AUD/USD` | **DEMOTED** | 30 / -145.54% | **DEMOTED** | 30 / -68.84% |
| `BTC/USD` | **PAUSED** | 30 / -105.80% | **DEMOTED** | 30 / -61.79% |
| `ETH/USD` | **PAUSED** | 30 / -16.19% | **AUTO_EXEC** | 30 / +0.01% |
| `EUR/GBP` | **DEMOTED** | 30 / +163.00% | **PAUSED** | 30 / -228.57% |
| `EUR/JPY` | **DEMOTED** | 30 / -143.86% | **DEMOTED** | 30 / +15.04% |
| `EUR/USD` | **DEMOTED** | 30 / -113.94% | **DEMOTED** | 30 / -118.05% |
| `GBP/JPY` | **DEMOTED** | 30 / -86.62% | **DEMOTED** | 30 / -78.15% |
| `GBP/USD` | **PAUSED** | 30 / -127.23% | **PAUSED** | 30 / -132.77% |
| `NDX` | **OBSERVED** | — | **OBSERVED** | — |
| `SPX` | **OBSERVED** | — | **OBSERVED** | 30 / -50.16% |
| `USD/CAD` | **PAUSED** | 30 / -192.28% | **DEMOTED** | 30 / -61.84% |
| `USD/CHF` | **DEMOTED** | 30 / -122.90% | **DEMOTED** | 30 / -127.89% |
| `USD/JPY` | **DEMOTED** | 30 / -242.18% | **DEMOTED** | 30 / -251.48% |
| `WTI/USD` | **PAUSED** | 30 / +84.48% | **AUTO_EXEC** | 30 / +2.67% |
| `XAG/USD` | **DEMOTED** | 30 / -84.47% | **DEMOTED** | 30 / -20.17% |
| `XAU/USD` | **PAUSED** | 30 / -120.23% | **AUTO_EXEC** | 30 / +6.95% |
| `XLI` | **OBSERVED** | — | **AUTO_EXEC** | — |
| `XLK` | **OBSERVED** | — | **AUTO_EXEC** | — |

---

_Seuils promo auto OBSERVED→TELEGRAM : sample ≥ 30, PnL ≥ 2.0%, WR ≥ 45.0%, PF ≥ 1.3, maxDD > -10.0%. Promotion AUTO_EXEC reste manuelle (humain dans la boucle)._