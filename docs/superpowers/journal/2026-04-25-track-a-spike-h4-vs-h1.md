# Expérience #1 — Track A — Spike H4 vs H1 vs Daily

**Date début :** 2026-04-25
**Date fin :** 2026-04-25 (~17h Paris)
**Track :** A (Horizon expansion)
**Numéro d'expérience :** 1
**Statut :** `closed-positive`

---

## Hypothèse

> "Si on re-tourne le moteur pattern_detector + scoring V1 sur des bougies H4 et Daily (aggrégées localement depuis H1), avec coûts spread/slippage 0.02%, alors le **Profit Factor** sur ≥1 combinaison paire×stratégie sera ≥ 1.15 sur la fenêtre 2025-04-25 → 2026-04-25, avec ≥ 50 trades pour validité statistique."

## Motivation / contexte

- Findings ML V1 : AUC 0.526 sur 233k samples (un peu de signal mais sous le seuil 0.55).
- Backtest V1 : verdict "sans edge" sur 39689 trades H1 (PF baseline 0.95).
- Hypothèse : changer d'horizon (pas de features) suffit-il à débloquer un edge ?

## Données

- Source : `_macro_veto_analysis/backtest_candles.db` (786 MB)
- Période : 2025-04-25 → 2026-04-25 (12 mois)
- Pairs : 12 — AUD/USD, BTC/USD, ETH/USD, EUR/GBP, EUR/USD, GBP/JPY, GBP/USD, USD/CAD, USD/CHF, USD/JPY, XAG/USD, XAU/USD
- Granularités : H1 natif, H4 et Daily aggrégés localement depuis H1
- Coûts : 0.02% spread/slippage
- Volumes :
  - H1 : 39 689 trades total
  - H4 : 10 352 trades total
  - Daily : 1 717 trades total

## Protocole

1. Aggregation H1 → H4 (buckets alignés 00/04/08/12/16/20 UTC) et H1 → Daily (00 UTC) — fonctions `aggregate_to_h4` / `aggregate_to_daily` dans `scripts/research/track_a_backtest.py`
2. Ré-utilisation du moteur live (`detect_patterns`, `calculate_trade_setup`)
3. Forward simulation sur 5min, timeout scalé : H1=24h, H4=96h, Daily=240h
4. Stats : BASELINE / V2_LIGHT / V2_PATTERN / V2_FULL / RB_DOWN_SELL + breakdown par paire

## Critère go/no-go (FIXÉ AVANT EXÉCUTION)

| Sortie | Condition | Action |
|---|---|---|
| **Succès** | PF ≥ 1.15 sur ≥1 combinaison paire×stratégie en H4 ou Daily, ≥50 trades | Phase 3 approfondir |
| **Signal partiel** | PF entre 1.10 et 1.15, ou PF ≥ 1.15 mais < 50 trades | Étendre fenêtre à 24 mois |
| **Échec** | PF < 1.10 sur toutes les combinaisons en H4 ET Daily | Fermer track |

## Résultats

### H1 baseline (référence, 39 689 trades)

```
=== Comparaison stratégies (TF=1h) ===
  BASELINE (no filter)     n=39689  wr= 39.6%  PnL= -579.15%  avg=-0.015%  PF=0.95  maxDD=638.09%
  V2_LIGHT (sell only)     n=19439  wr= 38.4%  PnL= -502.72%  avg=-0.026%  PF=0.92  maxDD=665.43%
  V2_PATTERN (whitelist)   n=14888  wr= 38.4%  PnL= -241.39%  avg=-0.016%  PF=0.93  maxDD=257.46%
  V2_FULL (all filters)    n= 1200  wr= 39.3%  PnL=  -23.01%  avg=-0.019%  PF=0.78  maxDD=27.42%
  RB_DOWN_SELL only        n= 6685  wr= 38.8%  PnL=  -36.26%  avg=-0.005%  PF=0.97  maxDD=102.89%

  BASELINE par paire — top 3 :
  XAU/USD                  n= 3588  wr= 40.6%  PnL= +154.72%  avg=+0.043%  PF=1.14  maxDD=79.03%
  XAG/USD                  n= 3138  wr= 40.0%  PnL=  +53.79%  avg=+0.017%  PF=1.03  maxDD=125.70%
  USD/JPY                  n= 3255  wr= 41.5%  PnL=   -5.30%  avg=-0.002%  PF=0.99  maxDD=37.73%
```

H1 reproduit fidèlement le verdict V1 (39689 trades, PF 0.95). XAU à PF 1.14 = limite.

### H4 (10 352 trades)

```
=== Comparaison stratégies (TF=4h) ===
  BASELINE (no filter)     n=10352  wr= 41.1%  PnL= +287.76%  avg=+0.028%  PF=1.05  maxDD=346.26%
  V2_LIGHT (sell only)     n= 4921  wr= 39.1%  PnL= -187.58%  avg=-0.038%  PF=0.94  maxDD=429.95%
  V2_PATTERN (whitelist)   n= 4055  wr= 38.4%  PnL=  -22.75%  avg=-0.006%  PF=0.99  maxDD=209.73%
  V2_FULL (all filters)    n=  275  wr= 45.5%  PnL=   +5.24%  avg=+0.019%  PF=1.14  maxDD= 4.62%
  RB_DOWN_SELL only        n= 1874  wr= 38.2%  PnL=  -40.62%  avg=-0.022%  PF=0.95  maxDD=221.77%

  BASELINE par paire — métaux + crypto :
  XAG/USD                  n=  827  wr= 47.0%  PnL=+287.21%  avg=+0.347%  PF=1.28  maxDD=172.33%   ← ✓
  XAU/USD                  n=  866  wr= 44.6%  PnL=+127.73%  avg=+0.147%  PF=1.24  maxDD= 74.46%   ← ✓
  ETH/USD                  n= 1027  wr= 40.0%  PnL=+133.29%  avg=+0.130%  PF=1.06  maxDD=201.77%
  BTC/USD                  n= 1014  wr= 40.3%  PnL= -24.48%  avg=-0.024%  PF=0.98  maxDD=155.59%
  Forex (toutes)           PF entre 0.64 (EUR/GBP) et 0.95 (USD/CHF)
```

### Daily (1 717 trades)

```
=== Comparaison stratégies (TF=1d) ===
  BASELINE (no filter)     n= 1717  wr= 43.0%  PnL=  -32.53%  avg=-0.019%  PF=0.98  maxDD=248.33%
  V2_LIGHT (sell only)     n=  770  wr= 36.1%  PnL=-226.51%  avg=-0.294%  PF=0.76  maxDD=314.35%
  V2_PATTERN (whitelist)   n=  592  wr= 42.1%  PnL=-103.51%  avg=-0.175%  PF=0.82  maxDD=155.33%
  V2_FULL (all filters)    (vide — bug filtre, voir notes)
  RB_DOWN_SELL only        n=  300  wr= 38.7%  PnL= -87.56%  avg=-0.292%  PF=0.67  maxDD= 99.47%

  BASELINE par paire — top :
  ETH/USD                  n=  149  wr= 49.0%  PnL=+152.98%  avg=+1.027%  PF=1.29  maxDD=132.36%   ← ✓
  XAG/USD                  n=  154  wr= 42.9%  PnL=  -0.93%  avg=-0.006%  PF=1.00  maxDD=177.82%
  XAU/USD                  n=  156  wr= 42.3%  PnL= -11.95%  avg=-0.077%  PF=0.95  maxDD= 75.24%
  Forex (toutes)           PF entre 0.58 (USD/JPY) et 0.97 (AUD/USD)
```

### Comparaison synthétique cross-TF (BASELINE)

| Paire | H1 PF | H4 PF | Daily PF | Sweet spot |
|---|---|---|---|---|
| XAU/USD | 1.14 | **1.24** ✓ | 0.95 | H4 |
| XAG/USD | 1.03 | **1.28** ✓ | 1.00 | H4 |
| ETH/USD | 0.97 | 1.06 | **1.29** ✓ | Daily |
| BTC/USD | 0.93 | 0.98 | 0.87 | aucun |
| Forex 9 paires | 0.63-0.99 | 0.64-0.95 | 0.58-0.97 | aucun |

## Verdict

> Hypothèse **CONFIRMÉE** par 3 combinaisons paire×timeframe : XAU/USD H4 (PF 1.24, n=866), XAG/USD H4 (PF 1.28, n=827), ETH/USD Daily (PF 1.29, n=149). L'horizon **est** un facteur déterminant pour les classes d'actifs métaux et crypto. Aucun signal sur forex à aucun timeframe.

### Caveat majeurs à valider en Phase 3

1. **Biais carry / buy-and-hold caché.** XAU a fait ~+25% en 2025, XAG ~+30%, ETH ~+15%. Si la moyenne des trades est long-biaisée, le baseline PF positif peut être en partie un buy-and-hold déguisé. À décomposer par direction (long vs short).
2. **maxDD énorme** (172-202% sur XAU/XAG H4 baseline). Non exploitable tel quel : l'edge doit être filtré (les patterns "tueurs" exclus) pour stabiliser l'équity curve.
3. **V2_FULL global H4** : PF 1.14 sur 275 trades avec maxDD 4.62% **est très intéressant** — équity curve quasi-monotone — mais à la limite du critère et sample size limite.
4. **V2_FULL Daily vide** : les filtres `GOOD_HOURS={1,2,4,14,15}` ne matchent jamais sur bougies Daily alignées 00 UTC. Bug de filtre, pas de signal négatif. À ignorer.

## Conséquences actées

### Pour Track A
- **Phase 3 ouvre** : approfondissement sur XAU/USD H4, XAG/USD H4, ETH/USD Daily
- Priorités Phase 3 :
  1. Décomposition direction (long vs short) sur XAU/XAG H4 — confirmer que l'edge n'est pas purement carry
  2. Ablation par pattern : quels patterns portent l'edge ? Garder uniquement les patterns rentables → PF devrait monter et maxDD descendre
  3. Robustesse : refaire le test sur 24 mois (2024-2026) ou 36 mois si data dispo, vérifier que l'edge tient hors bull cycle
  4. Test du V2_FULL H4 sur sample plus large (extension fenêtre)
- **Pas de migration prod** avant Phase 3 close — l'edge actuel est conditionnel à un régime macro (bull metals/crypto 2025-2026)

### Pour Track B (alt-data + cross-asset)
- Pas de blocage. Track B peut démarrer en parallèle. Synergie possible : si Track B trouve `vix_regime` prédictif, croiser avec cet edge horizon-driven.

### Pour Track C (trend-following)
- **Très intéressant** : l'edge XAU/XAG/ETH H4-Daily est cohérent avec un signal trend-following naturel. La Track C devrait probablement *aussi* trouver de l'edge sur ces mêmes assets. Vérifier l'overlap au gate S6.

### Pour le code prod
- **Aucun changement V1**. Conformément à la règle d'or de la spec master.

## Artefacts

- Script : `scripts/research/track_a_backtest.py` (versionné dans le commit)
- Logs des 3 runs : `/tmp/track_a_{1h,4h,1d}.log` (éphémères)
- Commit : à venir avec ce journal
