# Backtest V1 — Findings et décision stratégique

**Date** : 2026-04-22
**Auteur** : session Claude + user
**Statut** : leçon actée, auto-exec en pause via kill switch

---

## Contexte

Construit en urgence dans la même session : fetch 3 ans × 15 pairs ×
(1h + 5min) via Twelve Data (~3.3M candles, 682 MB DB) + moteur de
replay (`backend/services/backtest_engine.py`) qui rejoue le scoring
sur l'historique et simule forward chaque trade (SL/TP hit avec 5min
bars, timeout 24h, slippage 0.02%).

Buts déclarés :
1. Valider l'edge du scoring AVANT passage live
2. Économiser 6-9 mois d'accumulation démo si un problème structurel existait

Le backtest V1 **a atteint le but #2 en 3h**.

## Résultats bruts

### Run 1 — scoring original (SL = recent_low ± ATR×0.3, TP = 1.5R, round(x, 2))

77 500 trades simulés sur 3 ans × 15 pairs.

| Pair | N | WR | PnL% | Sharpe | Max DD |
|---|---|---|---|---|---|
| **XAU/USD** | 6159 | 26.0% | **+86.66%** | 0.28 | 82.7% |
| GBP/JPY | 1478 | 26.1% | -24.82% | -0.97 | 25.6% |
| USD/JPY | 6244 | 26.7% | -69.55% | -0.47 | 92.9% |
| XAG/USD | 6291 | 25.3% | -75.97% | -0.12 | 223.3% |
| 11 autres pairs | — | 20-29% | -121 à -555% | -0.35 à -5.46 | catastrophique |

**Seul XAU semblait profitable.** Mais walk-forward trimestriel a révélé :

| Trimestre XAU | WR | PnL% | |
|---|---|---|---|
| 10 trimestres (2023Q2 - 2025Q3) | ~23% | cumul ~-75% | ❌ |
| **2025Q4 + 2026Q1** | 32% | **cumul +175%** | 🟢 anomalie |

→ L'edge XAU **n'est pas structurel** : concentré sur 2 trimestres où le
régime or haussier 2025-2026 (rallye 2000$→3500$) a rendu les patterns
momentum/breakout artificiellement performants.

### Run 2 — fix SL/TP (SL = 1.0×ATR, TP1 = 1.5×ATR, rounding adaptatif par pair)

Hypothèse : les SL recent_low profonds transformaient les vraies
pertes en timeouts neutres (masquant l'absence d'edge). Fix =
SL prévisible basé sur ATR seul.

**Résultat : encore pire partout.**

| Pair | Run 1 | Run 2 | Delta |
|---|---|---|---|
| EUR/USD | -210% | -285% | -75% |
| USD/JPY | -69% | -377% | -308% |
| XAU/USD | **+86%** | **-572%** | **-658%** |
| BTC/USD | -544% | -1967% | -1423% |
| ETH/USD | -433% | -2247% | -1814% |

Interprétation : les SL plus serrés (1×ATR) sont touchés par le bruit
intra-bar naturel → stop-outs systématiques. Les SL profonds originaux
**cachaient** l'absence d'edge en convertissant les pertes en timeouts.

## Conclusion ferme

Sur **77 500+ trades historiques indépendants**, aucune combinaison
SL/TP testée ne rend le scoring pattern_detector profitable.

**Le scoring V1 actuel (patterns techniques + volatility + trend + R:R)
n'a PAS d'edge statistique exploitable**, sur 3 ans de marché incluant
plusieurs régimes. Le "+19€ sur 11 trades" observé en live post-fix
2026-04-20 est **conjoncturel au rallye or 2025-2026**, pas le signal
d'un système profitable.

## Décisions actées

1. **Kill switch activé** le 2026-04-22 à 14:09 UTC avec raison explicite.
   Plus d'auto-exec jusqu'à nouvelle décision.
2. **L'outil continue de tourner** en mode observatoire : scoring +
   signaux + UI + Telegram + logging. User garde la surface analytique.
3. **Pas de tuning SL/TP supplémentaire** sans macro historique testé.
   Changer SL/TP sur un système sans edge ne le rend pas profitable.

## Pistes pour plus tard (non décidées)

### A. Backtest V2 avec macro historique
Reconstituer VIX/SPX/DXY via Twelve Data historique, appliquer le macro
multiplier et event blackout. **Seule façon honnête** de tester si le
macro apporte assez de signal pour rendre profitable. Effort 1-2 semaines.
Probabilité de succès : modérée — le macro ajoute typiquement 5-15% de
signal, pas de quoi renverser -200%/pair.

### B. Pivot stratégique
Repenser le fond :
- Trend-following swing (positions jours/semaines) au lieu de scalping
- Carry trade (différentiel de taux)
- ML supervisé direct sur features brutes
- News-driven (réaction 15min post-release)
- Sentiment flow retail (contrarien)

### C. Observatoire passif
Garder le système tel quel, observer les cycles macro/régime, apprendre.
Ne pas réactiver l'auto-exec.

## Leçons meta

1. **Le backtest rigoureux sur 3 ans rend un vrai service** même (surtout)
   quand il invalide. +19€ sur 11 trades ≠ edge. Sans backtest, cette
   illusion aurait pu durer 6-12 mois et coûter 2-5k€ en démo → live.
2. **L'approche "observation démo d'abord" a ses limites** : trop lente
   pour exclure rigoureusement un système, et **soumise aux régimes de
   marché** (on peut avoir un bon 3 mois purement par chance).
3. **Le pattern_detector seul = pas un edge.** Tous les systèmes rentables
   retail ont soit (a) beaucoup plus de features, (b) du contexte macro
   déterminant, (c) de l'alpha humain, ou (d) du ML sophistiqué. Un
   scoring heuristique sur 3 patterns ne suffit pas.

## État technique

- Backtest engine + fetcher : en place, réutilisables pour V2
- DB backtest_candles.db : 3 ans × 13 pairs exploitables (SPX/NDX data
  insuffisante sur plan Grow)
- Le code live tourne normalement, juste l'auto-exec est off via
  kill_switch
