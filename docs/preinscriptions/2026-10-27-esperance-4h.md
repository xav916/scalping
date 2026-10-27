# Pré-inscription — l'espérance de l'horizon `4h`, avec placebo

**Date** : 2026-10-27 · **Écrit AVANT tout code de banc et toute mesure de
l'espérance.**
**Origine** : le `1d` est rejeté (`0b8106b`, espérance **−0,0641 R** contre
**+0,0413 R** au hasard, `t = −4,23`, 0/200 tirages battus). Le `4h` est
l'horizon qui porte le volume réel : **1 775 setups**, dont **1 696 de forex
majeurs**, contre 1 362 pour le `1d`.

## Ce que la forme de la population impose — mesuré avant d'écrire

```
n = 1775, periode 2026-08-20 -> 2026-10-26, 10 paires, fenetre 96 h
GBP/USD 226 · AUD/USD 220 · USD/CAD 206 · EUR/USD 200 · USD/CHF 178
EUR/GBP 174 · EUR/JPY 166 · USD/JPY 164 · GBP/JPY 162 · XAG/USD 79
risk_pct median 0,3722 %   =>  cout = 0,0537 R
```

🔴 **TOUS LES 1 775 SETUPS SONT DES ACHATS.** Pas une seule vente. Deux
conséquences qui changent la conception, et que je dis d'avance :

1. **Le NIVEAU de l'espérance est entièrement confondu avec la dérive du
   marché** sur ces 68 jours. Seul l'**écart réel/placebo** porte une
   information, parce que le placebo subit la même dérive.
2. ⛔ **Je ne reprends donc PAS la prédiction « placebo proche de zéro » du
   `1d`.** Là-bas elle servait de test du banc ; ici un placebo non nul est
   **attendu** et n'est **pas** un défaut. La borne de contrôle devient large
   et ne sert qu'à détecter l'absurde.

🔑 **Et le COÛT devient matériel** : 0,0537 R contre 0,0021 R pour le `1d`,
soit un facteur **26**. Un gain positif inférieur au coût serait mangé. C'est
pourquoi l'admission exige `esperance_R_reel > cout_R_median` et pas `> 0`.

## Critère — ce qui est mesuré, et contre quoi

Même statistique et même dispositif que `d3cd3fe` : l'espérance en **R par
setup**, `R_i = pnl_pct_net_i / risk_pct_i`, convention **A** (les `TIMEOUT`
comptent à leur P&L réel), contre un **placebo de 200 tirages** qui garde du
réel les paires, le nombre de setups par paire, la période, le `risk_pct`, la
fenêtre de **96 h** et le sens — seul l'**instant d'entrée** est tiré.

<!-- CRITERE-MACHINE
statistique: esperance_R_par_setup
convention: A
horizon: 4h
fenetre_heures: 96
tirages_placebo: 200
cellules: 1
correction_multiplicite: PLAFOND_PAR_PERMUTATION_200_TIRAGES
population: resolved_backfill=1 AND timeframe=4h
validite: n_reel >= 1500 ET couverture_bougies_pct > 99 ET abs(risk_pct_median_placebo - risk_pct_median_reel) < 0.05 ET tirages_aboutis >= 190
admission: esperance_R_reel > cout_R_median ET t_contre_placebo > 2.00 ET tirages_battus_pct >= 95.0
rejet: esperance_R_reel <= 0 ET t_contre_placebo < 2.00
indecidable: abs(esperance_R_reel - esperance_R_placebo) < 0.01 ET abs(t_contre_placebo) < 2.00
P1_esperance_R_reel_attendue_max: 0.0
P2_esperance_R_placebo_abs_max: 0.30
P3_tirages_battus_pct_attendu_max: 95.0
P4_cout_R_median_min: 0.04
P5_ecart_esperance_B_moins_A_max: -0.05
-->

Le bloc ci-dessus est le critère **engagé** : c'est lui que `or-verdict` hache.

⚠️ Deux seuils diffèrent volontairement de la pré-inscription `1d` :
`validite` exige **n ≥ 1500** (la population est plus grande) et un accord des
`risk_pct` à **0,05 pt** et non 1,0 pt — le risque médian vaut ici 0,37 % et
non 9,33 %, donc une tolérance d'un point serait sans objet.

## Prédictions, dites d'avance

1. **L'espérance réelle sera NÉGATIVE** (`< 0`). C'est ce que dit tout le mur,
   et c'est ce qu'a donné le `1d`. Je l'écris pour pouvoir avoir tort.
2. **Le placebo sera NON NUL** mais borné (`|moyenne| < 0,30 R`) : population
   exclusivement acheteuse, donc dérive de la période. ⛔ Contrairement au
   `1d`, un placebo loin de zéro n'est **pas** un défaut du banc ici.
3. **Le réel ne battra PAS le 95ᵉ centile du placebo** : moins de 95 % des 200
   tirages seront battus.
4. **Le coût sera matériel** : `cout_R_median > 0,04 R`, soit au moins vingt
   fois celui du `1d`. ⇒ Une espérance positive mais inférieure à 0,054 R ne
   suffirait pas, et l'admission le refuserait.
5. **L'espérance sur les seuls résolus (convention B) sera PLUS NÉGATIVE** que
   sur toute la population, d'au moins **0,05 R** — les `TIMEOUT`, proches de
   zéro, diluent. C'est ce qu'a montré le `1d` (−0,1036 R d'écart) ; si le `4h`
   dit l'inverse, c'est une différence réelle entre horizons et il faudra le
   dire.

## Critère de décision

**VALIDITÉ DU REJEU** — si elle échoue, **le banc ne conclut rien, dans aucun
sens** :

    n_reel >= 1500  ET  couverture_bougies > 99 %
    ET  |risk_pct_median_placebo − risk_pct_median_reel| < 0,05 pt
    ET  tirages_aboutis >= 190 sur 200

**ADMISSION — l'instant d'entrée du `4h` porte une information exploitable** :

    esperance_R_reel > cout_R_median  ET  t_contre_placebo > +2,00
    ET  tirages_battus >= 95 %

**REJET — l'horizon `4h` est écarté** :

    esperance_R_reel <= 0  ET  t_contre_placebo < +2,00

**INDÉCIDABLE** si réel et placebo sont indiscernables **et** sans signe.

### Ce que chaque issue implique

- **Validité ✗** ⇒ rien. On répare, on ne conclut pas.
- **Admission** ⇒ ce serait la **première** information retenue sur ce mur, et
  elle exigerait une mesure **hors échantillon** avant toute production.
- **Rejet** ⇒ le `4h` rejoint le `1d`, et l'horizon qui porte **tout le volume
  forex** est écarté. ⚠️ Conséquence lourde : il ne resterait que le `5min`
  crypto, lui-même à **+0,0089 R** sur une mesure sans placebo.

## ⚠️ Limites, posées d'avance

- **Population exclusivement ACHETEUSE** : rien ici ne dit quoi que ce soit du
  sens vendeur, et les niveaux sont confondus avec la dérive.
- **Donnée rattrapée** (`resolved_backfill = 1`), un seul régime de marché sur
  ~68 jours. Le placebo utilise **exactement les mêmes bougies**, ce qui annule
  ce biais dans la comparaison mais pas dans les niveaux.
- **Une seule cellule pré-spécifiée**, plafond par le placebo. **Aucune autre
  cellule ne sera testée après coup sur cette donnée.**
- ⛔ **Ce banc ne dit rien du `1d`, du `5min`, ni des paires du pont** (XAU,
  WTI), absentes de cette population puisque leur historique est inaccessible.
