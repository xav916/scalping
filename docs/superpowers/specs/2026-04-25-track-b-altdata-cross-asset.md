# Track B — Alt-data + cross-asset features

**Date :** 2026-04-25
**Statut :** spec active
**Master :** `2026-04-25-research-portfolio-master.md`
**Budget :** 10 h/sem × 6 semaines

---

## Hypothèse

Le ML V1 a échoué (AUC 0.526) en utilisant **uniquement des features techniques dérivées du prix de la paire elle-même**. Il existe peut-être un edge dans des features **non-techniques** ou **cross-asset** qui n'ont jamais été testées :

1. **Macro** : VIX (régime de risque), DXY (force du dollar), SPX (régime risk-on/off), 10Y yields, BTC (proxy risk-on alternatif)
2. **Cross-asset corrélations** : XAU vs DXY (corrélation usuellement -0.7, divergences = signal), forex vs SPX, etc.
3. **Régime detection** : niveaux discrets (VIX low/normal/high), ATR regime, trend regime via EMAs longues
4. **Sentiment retail** : ratio long/short Myfxbook ou OANDA (effet contrarien documenté)
5. **News calendar features** : distance à un event high impact, surprise vs forecast (NFP, CPI)

Hypothèse falsifiable : "Si on étend les 35 features V1 avec ≥10 features alt-data/cross-asset et qu'on re-entraîne RandomForest + GradientBoost, alors l'AUC test ≥ 0.55 sur ≥1 horizon".

## Motivation / contexte

- Les findings ML V1 mentionnent explicitement que macro + sentiment + news + cross-asset **n'ont jamais été testés**. C'est le gap le plus visible.
- Académiquement, les meilleurs prédicteurs identifiés en retail forex ne sont pas techniques :
  - Sentiment retail contrarien (papers OANDA, Myfxbook 70%/30% rule)
  - Vol regime → choix de stratégie (mean reversion en low vol, trend en high vol)
  - News-driven 15min post-release (cf research Nasdaq, FXCM)
- Cette track est **transversale** : si elle révèle des features prédictives, elles peuvent profiter à Track A (H4/Daily ML) et Track C (signal d'entrée TF).

## Données

### Sources gratuites (priorité 1)

| Source | Données | API | Coût |
|---|---|---|---|
| **FRED** (St. Louis Fed) | VIX, DXY, 10Y/2Y yields, USD index | `fredapi` Python lib, key gratuite | 0€ |
| **Yahoo Finance** | SPX, NDX, BTC daily, sectors ETFs | `yfinance` Python | 0€ |
| **Twelve Data Grow** (déjà payé) | SPX, NDX, BTC déjà dans WATCHED_PAIRS | API existante | inclus |

### Sources payantes (priorité 2, à activer si signal sur priorité 1)

| Source | Données | Coût | Quand |
|---|---|---|---|
| **Myfxbook** ou **OANDA** | ratio long/short retail par paire | ~20€/mois | Si AUC > 0.53 sur priorité 1 |
| **ForexFactory premium** | calendrier news + actuals | ~15€/mois | Si pic AUC pendant news weeks |

### Période et alignement

- **Période :** 2020-01 à 2026-04 (cohérent avec ML V1, ~6 ans)
- **Granularité :** la plus fine disponible (daily pour macro, intraday pour SPX/BTC), alignée temporellement à chaque setup H1 par forward-fill (au moment T du setup, on prend la dernière valeur connue de chaque feature macro)

## Protocole

### Phase 1 — Pipeline data (1 semaine, S1)

1. **Créer `backend/services/macro_data.py`** : fetcher FRED + Yahoo, cache local SQLite (`data/macro.db`), API simple `get_macro_features_at(timestamp) -> dict`
2. **Étendre `scripts/ml_extract_features.py`** pour ajouter ces features lors de l'extraction :
   - `vix_level`, `vix_regime` (low <15 / normal 15-25 / high >25), `vix_delta_1d`
   - `dxy_level`, `dxy_dist_sma50`, `dxy_delta_1d`
   - `spx_dist_sma50`, `spx_return_1d`, `spx_return_5d`
   - `btc_return_1d`, `btc_return_5d` (risk on/off proxy)
   - `pair_dxy_corr_30d` (rolling 30d correlation entre la paire tradée et DXY)
   - `pair_spx_corr_30d` (idem avec SPX)
3. **Re-extraire les features** sur le dataset existant (233k samples). Si l'extraction est trop lente, sous-sampler à 50k pour aller vite en Phase 2.
4. **Sanity check** : visualiser les distributions des nouvelles features, vérifier l'alignement temporel (pas de look-ahead).

### Phase 2 — ML training (1 semaine, S2)

1. **Re-runner `ml_train.py`** avec les features étendues. 3 modèles : Logistic Regression, RandomForest, GradientBoost.
2. **Mesurer AUC test** sur le walk-forward split (15% test). Comparer à AUC V1 (0.526).
3. **Feature importance** : voir si les nouvelles features dominent le top 10. Si oui, signal positif. Si elles sont diluées, signal faible.

### Phase 3 — Approfondir si signal (S3-S4)

Si **AUC ≥ 0.55** :
- Ajouter sentiment retail (priorité 2) — Myfxbook API
- Ajouter news calendar features
- Tester sur Track A horizons (H4, Daily) si Track A a aussi un signal
- Cross-validation par paire : edge global ou concentré ?

Si **AUC entre 0.53 et 0.55** :
- Ajouter sentiment retail seulement (15€/mois) en croisant les doigts
- Test focalisé sur les conditions "atypiques" (VIX > 25, news days) où le signal devrait être plus fort

Si **AUC < 0.53** :
- Test ultime : DNN simple (MLP 3 couches) sur features étendues — au cas où l'edge soit non-linéaire et raté par RF/GB
- Si DNN aussi à plat → fermer track. Conclusion : le pattern detection actuel n'est pas exploitable même augmenté.

## Critère go/no-go (FIXÉ AVANT EXÉCUTION)

| Sortie | Condition | Action |
|---|---|---|
| **Succès** | AUC test ≥ 0.55 ET prec@0.65 > 0 sur ≥1 modèle, avec features nouvelles dans top-10 importance | Phase 3 approfondir, préparer intégration shadow log live |
| **Signal partiel** | AUC entre 0.53 et 0.55 | Ajouter sentiment retail (priorité 2), re-tester. Si toujours partiel, fermer. |
| **Échec** | AUC < 0.53 sur tous modèles, y compris DNN simple | Fermer track. Documenter "features alt-data ne suffisent pas à débloquer pattern detection". |

## Résultats attendus / risques

### Si succès
- Le `ml_predictor` live (déjà câblé en shadow log via commit `42f47c4`) consomme les nouvelles features → on peut commencer à filtrer les setups par proba ML en mode soft (alerter dans le dashboard, pas auto-exec)
- Les features macro deviennent réutilisables dans Track A (test sur H4) et Track C (input de régime pour TF)

### Risques techniques
- **Look-ahead leakage** : si on prend `vix_level` au timestamp T mais que VIX daily n'a fermé qu'à 21h UTC alors que le setup est à 14h UTC, on triche. Forward-fill avec un délai conservatif (T-1 day pour daily, T-1h pour intraday) est obligatoire. À tester explicitement avec un experiment "shuffle features cross-time" qui devrait redonner AUC ~0.50.
- **Stationnarité macro** : VIX/DXY ont des régimes différents sur 6 ans. Les modèles RF/GB peuvent overfitter le régime majoritaire. Robustness test : entraîner sur 2020-2023, tester sur 2024-2026 (out-of-time pur, pas walk-forward).
- **Twelve Data Grow rate limit** : si on fetch SPX/BTC en plus à chaque cycle live, surveiller le quota 55 req/min. Le cache est essentiel.

### Risques méthodologiques
- **Tester trop de features → overfitting** : on commence avec ~10-15 features alt-data ajoutées, pas 50. Si signal apparaît, ablation puis ajouts ciblés.
- **Multiple testing** : tester N feature sets × N modèles × N horizons inflate le risque de faux positif. Garder un test set unique réservé pour le verdict final, pas itérer dessus.

## Artefacts attendus

- `backend/services/macro_data.py` — service unifié macro
- `scripts/ml_extract_features_v2.py` — extraction étendue (peut être un fork de v1 ou un argument `--features-set`)
- `data/macro.db` — cache local des séries macro
- `data/ml_features_v2.csv` — re-extraction avec nouvelles features
- `model_outputs/` — comparaisons AUC V1 vs V2
- Journal entries dans `docs/superpowers/journal/`

## Dépendances

- **Indépendante** de Track A (peut runner en parallèle)
- **Synergie** avec Track A : si Track A trouve un horizon gagnant, refaire le ML training sur cet horizon avec features V2 = 4e expérience cross-track
- **Alimente** Track C : la feature `vix_regime` peut servir d'input du sizing TF (réduire exposition en VIX > 25)

## Échéancier indicatif

| Date | Étape | Statut |
|---|---|---|
| 2026-04-26 → 2026-05-02 | Phase 1 — pipeline data + extraction | à faire |
| 2026-05-03 → 2026-05-09 | Phase 2 — ML training, premier verdict | à faire |
| 2026-05-09 | **Verdict binaire AUC** dans le journal | à faire |
| 2026-05-10 → 2026-05-23 | Phase 3 conditionnelle (sentiment retail, news, DNN) | conditionnel |
