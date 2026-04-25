# Track C — Trend-following systématique multi-asset

**Date :** 2026-04-25
**Statut :** spec active
**Master :** `2026-04-25-research-portfolio-master.md`
**Budget :** 10 h/sem × 6 semaines

---

## Hypothèse

Le pattern detection (V1) **n'est pas le bon paradigme** pour retail forex/multi-asset. La littérature académique et les traders systématiques rentables (Carver, Hurst, Faith, Covel) convergent sur un autre paradigme : **trend-following systématique multi-asset diversifié**.

Caractéristiques :
1. **Pas de pattern detection** — juste un signal de momentum N mois (ex : croisement EMA 12/48 sur close daily, ou breakout 20-day Donchian, ou écart-type vs SMA 200)
2. **Sizing par target volatilité** — chaque position dimensionnée pour contribuer au même budget de risque journalier (ex : ATR × N en lots)
3. **Diversification** — portefeuille 10-20+ instruments décorrélés, pas concentration sur EUR/USD
4. **Trade trade infrequent** — 2-10 ouvertures par instrument et par mois, pas 100
5. **Stop-loss ATR-based**, pas de TP fixe — les gagnants courent jusqu'au signal d'inversion

Hypothèse falsifiable : "Si on implémente un trend-following multi-asset basique (signal momentum 3-mois, sizing vol target 0.5%, stop ATR×3) sur les 13 paires V1 sur 12 mois, alors le **Sharpe ratio annualisé** dépasse 0.7 avec coûts 0.02%."

## Motivation / contexte

- **C'est l'approche la mieux documentée** pour retail/CTAs sur des décennies (Faith *Way of the Turtle*, Carver *Systematic Trading*, Hurst-Ooi-Pedersen *A Century of Evidence on Trend-Following*)
- **Sharpe historiques publiés** : 0.5-1.0 sur portefeuilles 30-50 instruments sur 30+ ans
- **Ne dépend pas de features compliquées** — un EMA 12/48 ou un breakout 20-day suffit. Le secret est le sizing + diversification.
- **Si même cette approche échoue sur nos données**, ce n'est pas un problème de stratégie, c'est un problème de data ou de coûts. C'est une info précieuse en soi.
- **Nous avons déjà l'infra** : 13 paires, 12 mois H1 fetché, MT5 bridge fonctionnel. La seule pièce nouvelle est le moteur TF + sizing vol target.

## Données

- **Sources :** identique à V1 (`data/backtest_candles.db`)
- **Période :** 12 mois (2025-04 → 2026-04) en S1, étendre à 6 ans (2020-2026) en S3 si signal positif
- **Granularité :** **Daily** (le TF systématique tourne en daily, pas en H1) — re-aggréger H1 → Daily si nécessaire
- **Pairs :** les 13 paires V1, à étendre vers indices/commodités si signal (DAX, US30, Brent, etc.)

## Protocole

### Phase 1 — Backtest TF basique (1 semaine, S1)

1. **Créer `scripts/backtest_trend_following.py`** indépendant de pattern_detector :
   - Signal entrée : `close_today > EMA(close, 100)` AND `EMA(close, 12) > EMA(close, 48)` (long), inverse pour short. Tester aussi alternative breakout 20-day Donchian.
   - Signal sortie : croisement EMA inverse OU stop ATR×3 (whichever first)
   - Sizing : `lots = (risk_pct × equity) / (ATR × pip_value × point)` avec `risk_pct = 0.5%` par position
   - Cap exposure : max 10 positions ouvertes simultanément, max 20% equity en risque cumulé
2. **Mesures** : equity curve, Sharpe annualisé, max drawdown, Calmar, win rate, profit factor, nombre de trades
3. **Comparaison naive** : TF basique vs buy-and-hold de chaque paire (pour voir si on bat un benchmark passif)

### Phase 2 — Diversification + ablation (S2)

1. Ajouter plus d'instruments si dispo (indices, commodities) — voir si Twelve Data Grow couvre DAX/CAC/US30/Brent en daily long history
2. **Ablation des règles** : tester les 4 variantes — EMA cross, breakout Donchian, mix des deux, vol target 0.3% vs 0.5% vs 1%
3. **Walk-forward** : split 70/30 train/test sur 6 ans pour vérifier la robustesse

### Phase 3 — Approfondir si signal (S3-S4)

Si **Sharpe ≥ 0.7** :
- Multi-timeframe TF (mix daily + weekly signal)
- Filtre régime via Track B (réduire exposure en VIX > 25)
- Étendre à 30+ instruments si possible
- Préparer migration prod : adapter le bridge MT5 pour des positions long-terme avec trailing stop

Si **Sharpe entre 0.4 et 0.7** :
- TF est marginalement rentable mais pas assez. Tester combinaison cross-asset momentum (Asness/Moskowitz) qui ajoute un boost de ~0.2-0.3 au Sharpe.
- Si toujours < 0.7 après combinaison, fermer.

Si **Sharpe < 0.4** :
- C'est anormalement bas pour TF multi-asset. Diagnostiquer : (a) coûts trop élevés ? (b) data gap ? (c) période 2025 spéciale (les TF perdent régulièrement de l'argent en marchés mean-reverting comme 2017 ou 2023) ?
- Si diag clean → conclusion forte : retail forex multi-asset à 12 instruments est trop concentré pour TF. Pivot vers indices+commodities only.

## Critère go/no-go (FIXÉ AVANT EXÉCUTION)

| Sortie | Condition | Action |
|---|---|---|
| **Succès** | Sharpe annualisé ≥ 0.7 ET max drawdown < 25% sur backtest 12M, sur ≥1 variante de signal | Phase 3 approfondir, préparer migration prod live shadow en S5-S6 |
| **Signal partiel** | Sharpe entre 0.4 et 0.7 | Tester cross-asset momentum + filtre régime macro (intersection avec Track B). Si toujours partiel, fermer. |
| **Échec** | Sharpe < 0.4 sur toutes les variantes, et drawdown > 30% | Fermer track. Documenter "TF retail multi-asset 13 instruments insuffisamment diversifié". |

## Résultats attendus / risques

### Si succès
- Pivot **paradigme complet** : on abandonne pattern detection, on construit un système TF systématique. Rebuild pipeline live.
- L'auto-exec actuel (V1 démo) est désactivé proprement, le moteur TF prend la relève en démo Pepperstone.
- Le SaaS continue avec le V1 affiché en mode "legacy / observation" et le TF en mode "premium / signaux pro".

### Risques techniques
- **Daily data history** : Twelve Data Grow plafonne probablement à 5-6 ans en daily aussi. À vérifier en Phase 1 étape 1. Pour TF, idéalement 10-20 ans de history pour test cross-régime.
- **Pip value / lot size par instrument** : chaque instrument a sa specificité (XAU = 100 oz, BTC = 1 BTC, NDX = $1/point). Le calcul vol target est trivial sur forex mais demande table de mapping pour les autres. Voir si l'infra `asset_class_for()` existante suffit ou s'il faut étendre.
- **Backtest path-dependence** : avec position holding 1-3 mois, l'ordre de tirage des trades est crucial. Pas de bootstrap naïf possible.

### Risques méthodologiques
- **Survivor bias instruments** : on backteste sur 13 paires *qui existent encore en 2026*. C'est un biais mineur en forex (paires majeures stables) mais réel en crypto.
- **Régime sensitivity** : 12 mois 2025-2026 peut être un régime mean-reverting (mauvais pour TF). Étendre à 6 ans atténue mais ne résout pas. Le walk-forward 70/30 aide à voir.
- **Vol target nécessite récence vol** : ATR ou stdev rolling. À calculer sans look-ahead.

## Artefacts attendus

- `scripts/backtest_trend_following.py` — engine TF complet (signal + sizing + portfolio)
- `backend/services/portfolio_risk.py` — wrapper réutilisable sizing vol target + cap exposure (utilisable Track A et live aussi si succès)
- `data/tf_backtest_results.json` — equity curves + métriques
- Journal entries dans `docs/superpowers/journal/`

## Dépendances

- **Indépendante** de Track A et B en Phase 1-2
- **Synergie possible** avec Track B en Phase 3 : utiliser `vix_regime` ou `dxy_regime` comme filtre exposition
- **Indépendante** de Track A : ne se soucie pas de pattern detection

## Échéancier indicatif

| Date | Étape | Statut |
|---|---|---|
| 2026-04-26 → 2026-05-02 | Phase 1 — Backtest TF basique sur 13 paires 12 mois | à faire |
| 2026-05-03 → 2026-05-09 | Phase 2 — Diversification, ablation, walk-forward | à faire |
| 2026-05-09 | **Verdict binaire Sharpe** dans le journal | à faire |
| 2026-05-10 → 2026-05-23 | Phase 3 conditionnelle (cross-asset momentum, régime filter) | conditionnel |

## Lectures de référence

- Andrew Clenow, *Following the Trend* (2013) — état de l'art TF multi-asset retail-friendly
- Robert Carver, *Systematic Trading* (2015) — ch. 4-7 sur sizing vol target et diversification
- Hurst, Ooi, Pedersen, *A Century of Evidence on Trend-Following Investing* (AQR 2017) — paper de référence académique
- Curtis Faith, *Way of the Turtle* (2007) — règles Donchian breakout originelles
