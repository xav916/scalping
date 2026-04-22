# ML Training V1 — Findings finaux

**Date** : 2026-04-22 (soirée autonome)
**Statut** : résultat scientifique ferme — **pas d'edge détecté**

---

## Protocole expérimental

### Données

- **Historique** : 10 ans candles 1h via Twelve Data Grow (plan plafonne
  effectivement à 6 ans : 2020-2026 pour forex/metal, 2021-2026 crypto)
- **Pairs** : 13 exploitables (forex majors + JPY + XAU + XAG + BTC + ETH,
  SPX/NDX exclus pour manque de data)
- **233 567 setups extraits** au total après `detect_patterns` +
  `calculate_trade_setup` + feature extraction

### Features (35 au total)

Toutes calculables AU MOMENT T (pas de look-ahead) :

- **Geometry** : risk_pct, reward_pct, rr
- **Volatility** : atr14, atr_ratio (current/baseline)
- **Distance to moving averages** : dist_sma20/50/200 en ATR units
- **Trend** : ema_spread (EMA10 vs EMA30)
- **Momentum** : rsi14, stoch_k, adx14
- **Candle shape** : body/wick ratio last 3 bars
- **Time** : hour cyclic (sin/cos), day-of-week
- **Pattern** : one-hot 12 types (breakout up/down, momentum, etc.)
- **Session** : one-hot 5 (tokyo/london/ny/overlap/sydney)

### Target

Binary classification : `WIN=1` si outcome == TP1, `0` sinon (SL + TIMEOUT).

### Split temporel

- Train : 163 496 samples (70%)
- Validation : 35 035 (15%)
- Test : 35 036 (15%)

Split par timestamp (walk-forward correct, pas de leakage). Class balance
stable autour 38% TP1 sur tous les splits.

### Modèles

- Logistic Regression (baseline, avec standardisation + class weight balanced)
- Random Forest (200 trees, depth 8, min leaf 20, class weight balanced)
- Gradient Boosting (200 estimators, depth 5, learning rate 0.05)

## Résultats

### Distribution des outcomes (raw)

| Outcome | N | % |
|---|---|---|
| SL | 141 965 | 60.8% |
| TP1 | 89 013 | 38.1% |
| TIMEOUT | 2 589 | 1.1% |

**Win rate brut TP1 = 38.1%**. R:R théorique = 1.5 → seuil de rentabilité
win rate = 40%. On est **1.9 points sous la rentabilité pure**.

### AUC sur test set (stratification temporelle)

| Modèle | Val AUC | Test AUC | Prec@0.5 | Prec@0.65 |
|---|---|---|---|---|
| Logistic Regression | 0.510 | **0.512** | 0.382 | 0.000 |
| **Random Forest** | 0.513 | **0.526** | 0.390 | 0.000 |
| Gradient Boost | 0.510 | **0.509** | 0.284 | 0.169 |

**Meilleur AUC : 0.526** (Random Forest) vs **seuil d'edge défini 0.55** →
pas d'edge détecté. Modèle NON sauvegardé.

### Feature importance (Random Forest top 10)

| Rank | Feature | Importance |
|---|---|---|
| 1 | dist_sma20_atr | 0.086 |
| 2 | atr14 | 0.076 |
| 3 | dist_sma50_atr | 0.068 |
| 4 | stoch_k | 0.067 |
| 5 | rsi14 | 0.067 |
| 6 | dist_sma200_atr | 0.067 |
| 7 | ema_spread | 0.066 |
| 8 | reward_pct | 0.063 |
| 9 | risk_pct | 0.056 |
| 10 | adx14 | 0.056 |

**Répartition très uniforme** (top feature à 8.6%, 10e à 5.6%) → pas de
feature dominante → pas de pattern clair dans les données.

## Interprétation scientifique

### Ce que le résultat dit

Avec **233k samples sur 6-10 ans d'historique**, les features techniques
standards n'arrivent pas à distinguer les trades gagnants des perdants de
manière statistiquement significative. L'AUC 0.526 correspond à une
**amélioration de 2.6% vs aléatoire** — détectable mais non exploitable
(prec@0.65 = 0 car jamais de prédiction "haute confiance" qui ne soit pas
dominée par le bruit).

C'est cohérent avec le backtest V1 précédent (77k trades simulés à PnL
très négatif) : même verdict, méthodologie indépendante, 3× plus de data.

### Ce que ça invalide

1. Le scoring pattern_detector + trend + volatility + R:R **n'a pas d'edge**
2. Le tuning SL/TP ne peut pas créer un edge qui n'existe pas
3. Les features techniques "classiques" (ATR, ADX, RSI, MACD, EMA, SMA)
   prises isolément ou combinées ne contiennent pas de signal prédictif
   exploitable pour la cible WIN/LOSS à 1h d'entrée + 24h forward

### Ce que ça n'invalide PAS

1. **Le macro context** (VIX/SPX/DXY/COT) n'a **pas été testé** car absent
   des features historiques. La "Vague 1" du projet reste non vérifiée.
2. Les **horizons différents** (swing 1-5j, position weeks, intraday tick)
   pourraient avoir des edges différents.
3. Des features **non-techniques** (sentiment retail, news, flow, IV
   implied volatility, correlations cross-asset) pourraient contenir des
   edges non capturés ici.

## Conséquences actées

1. Le modèle ML **n'est pas intégré** au scoring live (pas d'edge à
   ajouter).
2. Le **verdict précédent** du backtest V1 (`2026-04-22-backtest-v1-findings.md`)
   est **confirmé scientifiquement** avec un protocole plus robuste.
3. L'**auto-exec démo continue** (pas d'euro réel en jeu, data s'accumule).
4. **Ligne rouge absolue** : ne pas passer en argent réel sans avoir testé
   une stratégie différente ou une approche de features non techniques.

## Pistes sérieuses pour un edge potentiel

Par ordre de probabilité décroissante selon la littérature académique +
observations traders retail rentables :

1. **Sentiment retail contrarien** (Myfxbook/OANDA position ratio) —
   effet documenté, retail 70%+ long = baisse dans 1-5j. Effort : 1
   semaine. API payante ~20€/mois.
2. **News-driven 15min post-release** — réactions binaires aux surprises
   (NFP, CPI, FOMC). Effort : 2-3 semaines (parser calendrier + timing
   précis + features surprise vs forecast).
3. **Cross-asset + regime detection** — XAU ~ DXY inverse, BTC ~ risk
   on/off, etc. Combiner les signaux plutôt que les isoler. Effort :
   2-3 semaines.
4. **Swing trend-following** (positions 2-10 jours) — edge plus clair sur
   horizons longs, moins dévoré par spread. Changement de paradigme :
   n'est plus du scalping. Effort : 1-2 mois de rebuild.
5. **ML end-to-end avec features brutes** (prix normalisés, sans
   indicateurs pré-calculés) sur DNN (LSTM/Transformer) — complexe,
   probabilité modérée.

## État technique

- Pipeline ML (feature extraction + training) : **fonctionnel**,
  réutilisable. Les scripts `ml_extract_features.py` et `ml_train.py`
  peuvent être re-lancés avec d'autres features (macro historique,
  sentiment, etc.) sans refactor majeur.
- CSV features : `/opt/scalping/data/ml_features.csv` (103 MB, 233k rows).
- Disk EC2 : 90% (7.2 GB / 8 GB). Le CSV peut être supprimé si besoin
  d'espace — regenerable via le script.
- Modèle : **NON sauvegardé** (pas d'edge). `ml_predictor.py` reste
  fonctionnel en mode neutre (retourne 0.5).
