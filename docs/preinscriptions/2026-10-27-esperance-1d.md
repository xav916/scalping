# Pré-inscription — l'espérance de l'horizon `1d`, avec placebo

**Date** : 2026-10-27 · **Écrit AVANT tout code de banc et toute requête.**
**Origine** : l'addendum `52747fd`. Le banc précédent a rendu ADMISSION sous la
convention A retenue par Xavier, mais **ce verdict ne mesurait pas le point
mort** : le seuil de 35,71 % suppose que chaque issue vaut +1,8 R ou −1 R, ce
qui est faux pour les **46,5 % de `TIMEOUT`** qui sortent au marché pour une
fraction de R. La bonne statistique est une **espérance**, pas un taux.

## Critère — ce qui est mesuré, et contre quoi

**La statistique** : l'espérance en **R par setup**, où
`R_i = pnl_pct_net_i / risk_pct_i` et `risk_pct_i = |entry − SL| / entry`.
Convention **A** (décision de Xavier) : les `TIMEOUT` comptent à leur P&L réel.
`pnl_pct_net` inclut déjà le coût (`SPREAD_SLIPPAGE_PCT = 0,02 %`).

**Contre quoi** : un **PLACEBO**, et c'est le cœur de ce banc. Sans lui, une
espérance positive ne distinguerait pas la géométrie du simple fait d'être
exposé au marché sur dix jours. Le placebo tire **200 jeux** d'entrées au
hasard, et pour chacun :

- mêmes paires et même nombre de setups par paire que le réel ;
- entrées tirées uniformément dans la **même période** que les setups réels de
  cette paire ;
- **même géométrie** : `risk_pct` repris du setup réel apparié, TP à 1,8 R,
  fenêtre de 240 h ;
- même sens (achat/vente) que le setup réel apparié, pour que le placebo ne
  teste que **l'INSTANT d'entrée** et rien d'autre.

<!-- CRITERE-MACHINE
statistique: esperance_R_par_setup
convention: A
tirages_placebo: 200
cellules: 1
correction_multiplicite: PLAFOND_PAR_PERMUTATION_200_TIRAGES
population: resolved_backfill=1 AND timeframe=1d
validite: n_reel >= 1000 ET couverture_bougies_pct > 99 ET abs(risk_pct_median_placebo - risk_pct_median_reel) < 1.0 ET tirages_aboutis >= 190
admission: esperance_R_reel > cout_R_median ET t_contre_placebo > 2.00 ET tirages_battus_pct >= 95.0
rejet: esperance_R_reel <= 0 ET t_contre_placebo < 2.00
indecidable: abs(esperance_R_reel - esperance_R_placebo) < 0.01 ET abs(t_contre_placebo) < 2.00
P1_esperance_R_reel_attendue_max: 0.0
P2_esperance_R_placebo_abs_max: 0.05
P3_tirages_battus_pct_attendu_max: 95.0
P4_esperance_R_timeout_abs_max: 0.20
P5_ecart_esperance_B_moins_A_max: -0.05
-->

Le bloc ci-dessus est le critère **engagé** : c'est lui que `or-verdict` hache.
La prose peut être réécrite sans toucher à l'empreinte ; les seuils, non.

## Prédictions, dites d'avance

1. **L'espérance réelle sera NÉGATIVE** (`< 0`). C'est ce que dit tout le reste
   du mur, et je l'écris pour pouvoir avoir tort.
2. **L'espérance du placebo sera proche de zéro** : `|moyenne| < 0,05 R`. Des
   entrées au hasard sur une géométrie symétrique ne doivent rien rapporter,
   au coût près. ⛔ Si le placebo s'écarte franchement de zéro, c'est le
   **banc** qui est faux, pas une découverte.
3. **Le réel ne battra PAS le 95ᵉ centile du placebo** : moins de 95 % des 200
   tirages seront battus.
4. **Les `TIMEOUT` auront une espérance faible en valeur absolue**
   (`|moyenne| < 0,20 R`) — c'est la prémisse même de mon objection à
   l'addendum. Si elle est fausse, mon objection tombe et il faudra le dire.
5. **L'espérance calculée sur les seuls résolus (convention B) sera PLUS
   NÉGATIVE que sur toute la population**, d'au moins **0,05 R** : les
   `TIMEOUT`, proches de zéro, diluent.

## Critère de décision

**VALIDITÉ DU REJEU** — condition sur la *donnée* et sur le *placebo*,
distincte de la décision. Si elle échoue, **le banc ne conclut rien, dans aucun
sens** :

    n_reel >= 1000  ET  couverture_bougies > 99 %
    ET  |risk_pct_median_placebo − risk_pct_median_reel| < 1,0 pt
    ET  tirages_aboutis >= 190 sur 200

**ADMISSION — l'horizon `1d` porte une information exploitable** :

    esperance_R_reel > cout_R_median  ET  t_contre_placebo > +2,00
    ET  tirages_battus >= 95 %

**REJET — l'horizon `1d` est écarté** :

    esperance_R_reel <= 0  ET  t_contre_placebo < +2,00

**INDÉCIDABLE** si le réel et le placebo sont indiscernables **et** sans
signe : `|esperance_reel − esperance_placebo| < 0,01 R` et `|t| < 2,00`.

### Ce que chaque issue implique

- **Validité ✗** ⇒ rien. On répare le banc ou la donnée, on ne conclut pas.
- **P2 ✗** (placebo loin de zéro) ⇒ le banc est faux. Aucune lecture du réel
  n'est permise tant que ce n'est pas compris.
- **Admission** ⇒ l'instant d'entrée du `1d` porte une information que le
  hasard ne donne pas. Ce serait la **première** sur ce mur, et elle devrait
  alors être re-mesurée hors échantillon avant toute mise en production.
- **Rejet** ⇒ l'horizon `1d` est écarté sur la bonne base, cette fois : une
  espérance, pas un taux dont le seuil ne s'appliquait pas.

## ⚠️ Limites, posées d'avance

- **Donnée rattrapée** (`resolved_backfill = 1`) : les issues ont été produites
  par le même chemin de calcul que la production, mais sur des bougies allées
  chercher après coup. Le placebo utilisera **exactement les mêmes bougies**,
  ce qui annule ce biais dans la *comparaison* mais pas dans les niveaux.
- **Un seul régime de marché** : 1 362 setups sur ~68 jours. Une admission ici
  ne vaudrait rien sans une mesure hors échantillon.
- **Une seule cellule pré-spécifiée**, et le plafond vient du placebo
  (200 tirages), pas d'un balayage de paramètres. **Aucune autre cellule ne
  sera testée après coup sur cette donnée.**
- **Le coût n'est pas le sujet** : à `risk_pct` médian de 9,33 %, les 0,02 % de
  spread valent ≈ 0,002 R. Contrairement aux bancs courts de l'or, ce n'est pas
  le coût qui décidera.
- ⛔ **Ce banc ne dit rien de l'horizon `4h`** ni des autres classes. Il porte
  sur le `1d` et sur lui seul.
