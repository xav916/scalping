# Pair Admission — Weekly Report

Généré : 2026-05-15 19:23 Paris · auto-routine hebdo

## Snapshot états (totals)

- **AUTO_EXEC** : 5
- **TELEGRAM** : 0
- **PAUSED** : 1
- **OBSERVED** : 28
- **DEMOTED** : 0

## Transitions des 7 derniers jours

| When (UTC) | Pair | Dir | State | By | Reason |
|---|---|---|---|---|---|
| 2026-05-13 19:58:44 | `EUR/USD` | buy | **OBSERVED** | admin:notif_test | revert after notification test |
| 2026-05-13 19:58:41 | `EUR/USD` | buy | **TELEGRAM** | admin:notif_test | test live notification Telegram infra from session |

## 🎯 Candidats promotion manuelle (TELEGRAM → AUTO_EXEC)

_TELEGRAM avec score sain : critères AUTO_EXEC franchis sur fenêtre 30 trades._

_Aucun candidat cette semaine._

## ⚠️ Candidats pause (AUTO_EXEC en zone warning -3% < PnL% < -1%)

_Aucun candidat cette semaine._

## Matrice complète (pair × direction)

| Pair | BUY state | BUY n / PnL% | SELL state | SELL n / PnL% |
|---|---|---|---|---|
| `AUD/USD` | **OBSERVED** | — | **OBSERVED** | 15 / -0.40% |
| `BTC/USD` | **OBSERVED** | — | **OBSERVED** | — |
| `ETH/USD` | **OBSERVED** | 2 / -0.24% | **AUTO_EXEC** | 30 / +0.00% |
| `EUR/GBP` | **OBSERVED** | — | **OBSERVED** | 7 / -0.14% |
| `EUR/JPY` | **OBSERVED** | 1 / -0.09% | **OBSERVED** | 23 / -0.62% |
| `EUR/USD` | **OBSERVED** | 1 / +0.02% | **OBSERVED** | 14 / +0.55% |
| `GBP/JPY` | **OBSERVED** | 2 / -0.13% | **OBSERVED** | — |
| `NDX` | **OBSERVED** | — | **OBSERVED** | — |
| `SPX` | **OBSERVED** | — | **OBSERVED** | — |
| `USD/CAD` | **OBSERVED** | 1 / +0.01% | **OBSERVED** | 10 / -0.34% |
| `USD/CHF` | **OBSERVED** | 2 / +0.16% | **OBSERVED** | 2 / +0.15% |
| `USD/JPY` | **OBSERVED** | 1 / -0.04% | **OBSERVED** | 1 / -0.02% |
| `WTI/USD` | **OBSERVED** | 3 / -0.78% | **AUTO_EXEC** | 10 / -0.22% |
| `XAG/USD` | **OBSERVED** | 14 / +2.16% | **PAUSED** | 30 / -6.05% |
| `XAU/USD` | **OBSERVED** | 10 / +0.24% | **AUTO_EXEC** | 30 / +2.08% |
| `XLI` | **OBSERVED** | — | **AUTO_EXEC** | — |
| `XLK` | **OBSERVED** | 1 / +0.72% | **AUTO_EXEC** | — |

---

_Seuils promo auto OBSERVED→TELEGRAM : sample ≥ 30, PnL ≥ 2.0%, WR ≥ 45.0%, PF ≥ 1.3, maxDD > -10.0%. Promotion AUTO_EXEC reste manuelle (humain dans la boucle)._
