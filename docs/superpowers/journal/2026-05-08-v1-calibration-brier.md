# V1 confidence_score — calibration Brier sur backtest 5342 trades

**Date** : 2026-05-08
**Source** : `_macro_veto_analysis/backtest.db` table `trades`
**Script** : `scripts/research/v1_calibration_brier.py`
**Trigger** : critique d'un guide tutoriel sur les bots de prédictifs (Brier
score mentionné comme outil de validation calibration). Application à la
situation propre du Scalping Radar.

## Verdict

**Le `confidence_score` du V1 est anti-prédictif dans la zone qui auto-exec.**

```
Bucket    n      Mean p_pred   Win rate obs   Δ (obs-pred)
----------------------------------------------------------
25-30   108        28.63%        37.96%       +9.34pp
30-40  1375        36.04%        44.15%       +8.10pp
40-50  2308        45.26%        47.92%       +2.66pp
50-55   825        50.41%        39.52%      -10.90pp
55-60   455        57.85%        41.54%      -16.31pp
60-65   253        60.24%        32.02%      -28.23pp 🚨
65-70    17        67.50%        76.47%       +8.97pp (n trop petit)
70-75     1        72.00%       100.00%       (n=1, ignore)
```

- **Brier global V1** : 0.2549
- **Brier baseline naïve** ("prédire toujours win_rate global 44.25%") : 0.2467
- **Skill score** : −3.3% (V1 fait *pire* qu'une moyenne fixe)
- **Monotonicité confidence→win_rate** : **NON** (le score inverse l'ordre)

## Lecture

1. **Bucket 60-65 → 32% win rate** alors que le score prédit 60%. C'est
   exactement la zone où le seuil bridge live filtre les setups à pousser
   en auto-exec. Le score sélectionne les **pires** trades de la
   distribution.

2. **Buckets 25-50 → win rate observé de 38-48% avec sous-confiance** :
   le système gagne plus que prédit dans la zone "low confidence". Si on
   ne filtrait pas, on aurait mécaniquement un win rate plus haut que la
   moyenne actuelle des trades auto-exec.

3. **Skill score négatif** : un coin flip à 50/50 garderait Brier = 0.25,
   ce qui est *meilleur* que 0.2549. Le scoring V1 ajoute donc du bruit
   par rapport à un "no-information" benchmark.

## Conséquences pratiques

### ✅ Confirme le bon choix V2 pattern-based

La recherche J1 (2026-04-25) a abandonné les filtres gradués numériques
au profit d'un filtre binaire `pattern ∈ {momentum_up, engulfing_bullish,
breakout_up}`. Cette analyse confirme rétroactivement que *garder* un
score numérique aurait été nocif — pas juste neutre.

### 🚨 Trou logique côté bridge auto-exec

Le bridge MT5 (admin compte Pepperstone démo 62119130 + utilisateurs
Premium tels que Cédric) utilise *encore* le seuil V1 pour décider
quoi push. Tant que Track A V2 n'est pas activé en live (gate S6
2026-06-06), l'auto-exec démo tourne avec un scoring activement
préjudiciable.

**Options de remédiation, par ordre de "cost-to-fix" croissant** :

1. **Pause auto-exec démo** jusqu'au live V2 → zéro effet réel mais
   coupe la pollution de la série live démo.
2. **Désactiver le filtre par seuil** (laisser passer tous les setups
   stars-only V2 candidates) → win rate mécaniquement remonté à ~44%
   (mais on n'aura toujours pas d'edge structurel).
3. **Brancher Track A V2 pattern-only en bridge live** → demande une
   validation de plus que les 11 jours actuels (Sharpe backtest 1.59,
   live 0/3 réconciliés).

### 📊 Limite de l'analyse

- 5342 trades fermés couvrent l'historique V1 jusqu'à fin avril 2026.
- Distribution des confidence_score concentrée sur 30-50 (3683 trades sur
  5342, soit 69%). Buckets 65+ (n=18) trop petits pour une lecture
  robuste — mais c'est la queue rare déjà, pas critique.
- Le Brier ne sépare pas par pair, asset class ou direction. Une
  analyse par segment pourrait révéler un sous-univers où le score
  est calibré (peu probable mais à vérifier en suite).

## Pour suite

- Optionnel : refaire l'analyse par `pair × pattern` pour identifier
  s'il existe une niche où le V1 score est calibré (1h).
- Mémoire : `feedback_v1_score_anti_predictive_60_65.md` créée pour
  archiver le finding.
- Pas d'action code immédiate : le V1 est déjà déprécié, V2 est
  pattern-only, donc on a juste documenté ce qu'on suspectait.
