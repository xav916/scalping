# Pair Admission — Weekly Report

Généré : 2026-07-17 19:23 Paris · auto-routine hebdo

## Snapshot états (totals)

- **AUTO_EXEC** : 11
- **TELEGRAM** : 0
- **PAUSED** : 2
- **OBSERVED** : 2
- **DEMOTED** : 29

## Transitions des 7 derniers jours

| When (UTC) | Pair | Dir | State | By | Reason |
|---|---|---|---|---|---|
| 2026-07-13 19:40:56 | `XAU/USD` | buy | **PAUSED** | auto | auto-pause: pnl_pct -113.16% < -3% |
| 2026-07-13 19:40:56 | `EUR/USD` | buy | **PAUSED** | auto | auto-pause: pnl_pct -109.99% < -3% |
| 2026-07-13 19:40:39 | `EUR/USD` | sell | **AUTO_EXEC** | manual | manual override 2026-07-13: unblock alpha whitelist |
| 2026-07-13 19:40:39 | `EUR/USD` | buy | **AUTO_EXEC** | manual | manual override 2026-07-13: unblock alpha whitelist |
| 2026-07-13 19:40:39 | `XAU/USD` | buy | **AUTO_EXEC** | manual | manual override 2026-07-13: unblock alpha whitelist (0 push 14d) |

## 🎯 Candidats promotion manuelle (TELEGRAM → AUTO_EXEC)

_TELEGRAM avec score sain : critères AUTO_EXEC franchis sur fenêtre 30 trades._

_Aucun candidat cette semaine._

## ⚠️ Candidats pause (AUTO_EXEC en zone warning -3% < PnL% < -1%)

_Aucun candidat cette semaine._

## Matrice complète (pair × direction)

| Pair | BUY state | BUY n / PnL% | SELL state | SELL n / PnL% |
|---|---|---|---|---|
| `ADA/USD` | **DEMOTED** | 2 / +10.85% | **DEMOTED** | — |
| `AUD/USD` | **DEMOTED** | 30 / -145.54% | **DEMOTED** | 30 / -2.65% |
| `BCH/USD` | **AUTO_EXEC** | 30 / -0.07% | **AUTO_EXEC** | 30 / -0.04% |
| `BTC/USD` | **DEMOTED** | 30 / -105.80% | **DEMOTED** | 30 / -61.79% |
| `DOT/USD` | **AUTO_EXEC** | 20 / +5.74% | **AUTO_EXEC** | 25 / -0.02% |
| `ETH/USD` | **DEMOTED** | 30 / +53.10% | **AUTO_EXEC** | 30 / -0.02% |
| `EUR/GBP` | **DEMOTED** | 30 / +163.00% | **DEMOTED** | 30 / -171.48% |
| `EUR/JPY` | **DEMOTED** | 30 / -140.19% | **DEMOTED** | 30 / -2.59% |
| `EUR/USD` | **PAUSED** | 30 / -109.99% | **AUTO_EXEC** | 30 / +3.68% |
| `GBP/JPY` | **DEMOTED** | 30 / -93.76% | **DEMOTED** | 30 / -78.15% |
| `GBP/USD` | **DEMOTED** | 30 / -114.68% | **DEMOTED** | 30 / -129.36% |
| `LTC/USD` | **DEMOTED** | — | **DEMOTED** | — |
| `SOL/USD` | **DEMOTED** | 1 / +5.39% | **DEMOTED** | — |
| `USD/CAD` | **DEMOTED** | 30 / -181.86% | **DEMOTED** | 30 / -50.45% |
| `USD/CHF` | **DEMOTED** | 30 / -112.37% | **DEMOTED** | 30 / -101.61% |
| `USD/JPY` | **DEMOTED** | 30 / -227.15% | **DEMOTED** | 30 / -247.97% |
| `WTI/USD` | **AUTO_EXEC** | 30 / +71.57% | **AUTO_EXEC** | 30 / +1.92% |
| `XAG/USD` | **DEMOTED** | 30 / -97.74% | **DEMOTED** | 30 / -10.78% |
| `XAU/USD` | **PAUSED** | 30 / -113.16% | **AUTO_EXEC** | 30 / +10.58% |
| `XLI` | **OBSERVED** | — | **AUTO_EXEC** | — |
| `XLK` | **OBSERVED** | — | **AUTO_EXEC** | — |
| `XRP/USD` | **DEMOTED** | — | **DEMOTED** | 2 / -10.79% |

---

_Seuils promo auto OBSERVED→TELEGRAM : sample ≥ 30, PnL ≥ 2.0%, WR ≥ 45.0%, PF ≥ 1.3, maxDD > -10.0%. Promotion AUTO_EXEC reste manuelle (humain dans la boucle)._