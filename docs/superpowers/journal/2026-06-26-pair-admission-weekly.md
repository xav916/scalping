# Pair Admission — Weekly Report

Généré : 2026-06-26 19:24 Paris · auto-routine hebdo

## Snapshot états (totals)

- **AUTO_EXEC** : 10
- **TELEGRAM** : 0
- **PAUSED** : 8
- **OBSERVED** : 2
- **DEMOTED** : 24

## Transitions des 7 derniers jours

| When (UTC) | Pair | Dir | State | By | Reason |
|---|---|---|---|---|---|
| 2026-06-26 15:43:29 | `ETH/USD` | buy | **DEMOTED** | auto | auto-demote: 2 pauses on 60d (max 2) |
| 2026-06-26 11:43:29 | `XAU/USD` | buy | **DEMOTED** | auto | auto-demote: 3 pauses on 60d (max 2) |

## 🎯 Candidats promotion manuelle (TELEGRAM → AUTO_EXEC)

_TELEGRAM avec score sain : critères AUTO_EXEC franchis sur fenêtre 30 trades._

_Aucun candidat cette semaine._

## ⚠️ Candidats pause (AUTO_EXEC en zone warning -3% < PnL% < -1%)

_Aucun candidat cette semaine._

## Matrice complète (pair × direction)

| Pair | BUY state | BUY n / PnL% | SELL state | SELL n / PnL% |
|---|---|---|---|---|
| `ADA/USD` | **PAUSED** | 2 / +10.85% | **PAUSED** | — |
| `AUD/USD` | **DEMOTED** | 30 / -145.54% | **DEMOTED** | 30 / -2.65% |
| `BCH/USD` | **AUTO_EXEC** | 30 / -0.07% | **AUTO_EXEC** | 30 / -0.05% |
| `BTC/USD` | **DEMOTED** | 30 / -105.80% | **DEMOTED** | 30 / -61.79% |
| `DOT/USD` | **AUTO_EXEC** | 20 / +5.74% | **AUTO_EXEC** | 25 / -0.02% |
| `ETH/USD` | **DEMOTED** | 30 / +53.10% | **AUTO_EXEC** | 30 / -0.02% |
| `EUR/GBP` | **DEMOTED** | 30 / +163.00% | **DEMOTED** | 30 / -171.48% |
| `EUR/JPY` | **DEMOTED** | 30 / -140.19% | **DEMOTED** | 30 / -2.59% |
| `EUR/USD` | **DEMOTED** | 30 / -109.99% | **DEMOTED** | 30 / -0.93% |
| `GBP/JPY` | **DEMOTED** | 30 / -93.76% | **DEMOTED** | 30 / -78.15% |
| `GBP/USD` | **DEMOTED** | 30 / -114.68% | **DEMOTED** | 30 / -129.36% |
| `LTC/USD` | **PAUSED** | — | **PAUSED** | — |
| `SOL/USD` | **PAUSED** | 1 / +5.39% | **PAUSED** | — |
| `USD/CAD` | **DEMOTED** | 30 / -181.86% | **DEMOTED** | 30 / -50.45% |
| `USD/CHF` | **DEMOTED** | 30 / -112.37% | **DEMOTED** | 30 / -101.61% |
| `USD/JPY` | **DEMOTED** | 30 / -227.15% | **DEMOTED** | 30 / -247.97% |
| `WTI/USD` | **AUTO_EXEC** | 30 / +71.57% | **AUTO_EXEC** | 30 / +1.92% |
| `XAG/USD` | **DEMOTED** | 30 / -97.74% | **DEMOTED** | 30 / -10.78% |
| `XAU/USD` | **DEMOTED** | 30 / -113.16% | **AUTO_EXEC** | 30 / +11.50% |
| `XLI` | **OBSERVED** | — | **AUTO_EXEC** | — |
| `XLK` | **OBSERVED** | — | **AUTO_EXEC** | — |
| `XRP/USD` | **PAUSED** | — | **PAUSED** | 2 / -10.79% |

---

_Seuils promo auto OBSERVED→TELEGRAM : sample ≥ 30, PnL ≥ 2.0%, WR ≥ 45.0%, PF ≥ 1.3, maxDD > -10.0%. Promotion AUTO_EXEC reste manuelle (humain dans la boucle)._