# Track A — Horizon expansion (H4 / Daily)

**Date :** 2026-04-25
**Statut :** spec active
**Master :** `2026-04-25-research-portfolio-master.md`
**Budget :** 10 h/sem × 6 semaines

---

## Hypothèse

L'edge sur retail forex existe à des **horizons plus longs que H1** parce que :

1. **Spread/slippage devient un coût marginal** quand le mouvement cible est 5-10× plus large (TP de 100 pips vs 15 pips → spread 1-2 pips amorti)
2. **Micro-noise H1 mécaniquement filtrée** par l'agrégation 4h/daily
3. **Pattern detection** (déjà codé) a probablement un signal-to-noise meilleur sur des bougies plus signifiantes

Hypothèse falsifiable : "Si on re-tourne le backtest V2 (mêmes patterns, mêmes pairs, mêmes coûts) sur des bougies H4 et Daily, alors le PF sera ≥ 1.15 sur au moins une combinaison paire×stratégie".

## Motivation / contexte

- Findings ML V1 : AUC 0.526 ≠ 0.500. Il y a un *peu* de signal dans les features techniques. Ce signal pourrait franchir le seuil d'edge à un horizon plus généreux.
- La roadmap initiale prévoyait scalping → day trading → swing → position en série. On accélère en testant les horizons longs en parallèle plutôt qu'après 6 semaines de scalping.
- La littérature retail (Carver, Hurst, Faith) place l'edge majoritairement sur des horizons multi-jours pour les particuliers.

## Données

- **Source :** Twelve Data Grow (déjà fetchée localement dans `data/backtest_candles.db`)
- **Période :** 2025-04 à 2026-04 (12 mois) — cohérent avec backtest V1
- **Pairs :** 12 (les mêmes que V1 : EUR/USD, GBP/USD, USD/JPY, USD/CHF, AUD/USD, USD/CAD, EUR/JPY, GBP/JPY, EUR/GBP, XAU/USD, XAG/USD, BTC/USD, ETH/USD — 13 si on garde XAG)
- **Granularités à tester :**
  - **H4** (priorité 1) — fetch ou re-aggrégation depuis H1 si nécessaire
  - **Daily** (priorité 2) — devrait être direct depuis Twelve Data
  - **H1 baseline** — déjà testé, sert de référence comparative

## Protocole

### Phase 1 — Spike H4 (1-2 jours, semaine S1)

1. **Vérifier la disponibilité H4** dans Twelve Data Grow. Si OK, fetcher 12 mois de H4 sur les 13 paires. Sinon, ré-agréger H1 → H4 dans le script (4 bougies H1 → 1 bougie H4 alignée 00/04/08/12/16/20 UTC).
2. **Adapter `scripts/backtest_v2.py`** pour accepter un paramètre `--timeframe {1h,4h,1d}` qui :
   - Charge les bougies à la granularité demandée
   - Ajuste le forward window (24 bougies pour H1 = 1 jour ; 24 bougies pour H4 = 4 jours ; 14 bougies pour daily = 2 semaines — à doc)
   - Garde les mêmes patterns (pattern_detector ne change pas, juste les bougies en input)
   - Garde les mêmes coûts (0.02% spread/slippage)
3. **Lancer 3 backtests** : H1 (référence), H4, Daily
4. **Mesurer** : PF, win rate, total trades, max drawdown, Sharpe annualisé, par paire et global

### Phase 2 — Spike Daily (1 jour, semaine S2)

Idem Phase 1 sur granularité daily. Note : moins de trades (~1/10e du H1), donc IC plus large.

### Phase 3 — Approfondir si signal (semaines S3-S4)

Si **PF ≥ 1.15 sur ≥1 combinaison** en Phase 1 ou 2 :
- Ablation par pattern : quels patterns portent l'edge à H4/Daily ?
- Ablation par session : edge concentré sur Tokyo/London/NY/Asia ?
- Ablation par paire : isoler les paires "porteuses" vs "neutres"
- Re-fit ML V1 sur la granularité gagnante avec les 35 features actuelles (pas de nouvelles features dans cette track) — juste pour confirmer si le ML capte mieux à cet horizon

Si **PF < 1.10 sur tout** : track fermée, on documente "Horizon n'est pas le facteur déterminant", et on bascule les 10h/sem dispo vers la track la plus prometteuse parmi B et C.

## Critère go/no-go (FIXÉ AVANT EXÉCUTION)

| Sortie | Condition | Action |
|---|---|---|
| **Succès** | PF ≥ 1.15 sur ≥1 paire×stratégie en H4 ou Daily, avec ≥ 50 trades pour validité statistique | Approfondir Phase 3, préparer migration prod en S5-S6 |
| **Signal partiel** | PF entre 1.10 et 1.15, ou PF ≥ 1.15 mais < 50 trades | Étendre la fenêtre backtest à 24 mois (re-fetcher si besoin), refaire la mesure |
| **Échec** | PF < 1.10 sur toutes les combinaisons en H4 ET Daily | Fermer la track, documenter dans journal, libérer les 10h/sem |

## Résultats attendus / risques

### Si succès
- Pivot horizon prod : changer `MT5_BRIDGE_TIMEFRAME` (s'il existe) ou les paramètres pattern_detector
- Re-train ML V1 sur le nouvel horizon
- Re-démarrer observation live shadow sur 4-8 semaines avant éventuel passage réel

### Risques techniques
- **Twelve Data H4** : pas sûr que le plan Grow le fournisse en historique long. À vérifier en Phase 1 étape 1.
- **Slippage différent à H4/Daily** : sur des TP plus larges, les fills se font sur des chandelles plus stretched, le slippage relatif (en % du TP) est plus faible mais le slippage absolu (en pips) peut être plus élevé sur les news. À monitorer si on passe en live.
- **Volume trade trop faible en Daily** : 12 paires × 252 jours = 3024 trade-days max ; avec un pattern detector qui trigger ~1 trade tous les 5-10 jours, on aura ~300-600 trades total sur 12 mois. C'est limite pour la robustesse stat, d'où la priorité H4 sur Daily.

### Risques méthodologiques
- **Lookback bias** : si on adapte les pattern thresholds à H4/Daily, c'est de l'overfit. Garder les mêmes thresholds que V1 en première mesure.
- **Survivorship sur les paires** : on a déjà filtré les paires faibles en V1. À vérifier que le set 13 paires reste représentatif à H4 (certaines paires moins liquides à H4 ?)

## Artefacts attendus

- `scripts/backtest_v2_multitf.py` (ou patch de `backtest_v2.py` avec `--timeframe`)
- `data/backtest_candles_h4.db` ou ré-utilisation de la même DB avec table `candles_h4`
- Fichiers journal `docs/superpowers/journal/2026-XX-XX-track-a-*.md` (1 par expérience close)
- Mise à jour `INDEX.md` et `master.md` à chaque verdict

## Dépendances

- **Aucune** sur Track B ou C — peut tourner totalement isolée.
- **Pas d'impact prod** — ne touche pas le scoring live, le bridge, ou la DB principale.

## Échéancier indicatif

| Date | Étape | Statut |
|---|---|---|
| 2026-04-26 / 27 | Spike H4 (Phase 1) | à faire |
| 2026-04-28 / 29 | Spike Daily (Phase 2) | à faire |
| 2026-04-30 | **Premier verdict binaire écrit dans le journal** | à faire |
| 2026-05-01 → 2026-05-09 | Approfondir si signal, ou fermer | conditionnel |
