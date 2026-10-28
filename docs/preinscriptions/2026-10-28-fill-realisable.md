# Pré-inscription — le signal `5min` survit-il à un prix d'entrée RÉALISABLE ?

**Date** : 2026-10-28 · **Écrit AVANT la mesure.** · **Fichier NEUF, commité une fois.**
**Origine** : verdict `4f47737`. En cherchant pourquoi donner les décalages
d'entrée au placebo tuait 75 % de l'écart, j'ai trouvé **bien plus grave**.

## 🔴 CE QUI A ÉTÉ MESURÉ, ET QUI MOTIVE CE BANC

### 1. Toute la différence vit dans la PREMIÈRE BOUGIE

| | `SL` dès la 1ʳᵉ bougie | `TP1` dès la 1ʳᵉ bougie | total |
|---|---|---|---|
| **bras RÉEL** | **6,2 %** | **7,0 %** | 13,2 % |
| placebo (`r = 1`) | **9,2 %** | **2,7 %** | 11,9 % |

Contribution de la **seule première bougie** à l'espérance, à `+1,8 R / −1 R` :

```
reel     : 0,070 x 1,8  -  0,062 x 1,0  =  +0,064 R
placebo  : 0,027 x 1,8  -  0,092 x 1,0  =  -0,043 R
ECART de la premiere bougie seule        =  +0,107 R
```

⇒ 🔴 **L'écart total mesuré vaut +0,092 R.** La première bougie en explique
donc **la totalité, et au-delà**. Les 96 heures restantes ne contribuent
**rien**, voire négativement.

### 2. Et la cause : `entry_price` n'est pas un prix EXÉCUTABLE

```
entry == cloture de la barre   :  5,8 %
entry == ouverture de la barre :  4,6 %
entry == ouverture suivante    :  1,8 %
entry == AUTRE                 : 87,8 %
```

`entry_price` est un **niveau de motif** (sommet de cassure, niveau de pin-bar,
…), pas un prix de marché. Et il tombe **hors** de la bougie d'entrée dans
**50,2 %** des cas.

⇒ **Le banc accorde donc au bras réel un fill à un prix que le marché n'a
souvent jamais traité**, et ce fill est **net favorable** : `(r−1)` orienté par
la direction a pour moyenne **−0,104 risque**, avec **11,1 %** d'objectifs déjà
franchis contre **2,0 %** de stops déjà franchis.

🔑 **Le placebo, lui, entre toujours à l'ouverture de sa bougie — un prix
toujours atteignable.** L'asymétrie n'est donc **pas sur l'instant** : elle est
sur le **prix d'entrée**. Et c'est l'instant que le banc croyait tester.

### 3. ⚠️ Et cela expliquerait TOUTE la série

L'artefact vaut `décalage / risk_pct` : il grandit quand le stop se resserre.

| horizon | `risk_pct` médian | décalage / risque | écart publié |
|---|---|---|---|
| `1d` | 9,326 % | ≈ 0,007 | **−0,105 R** |
| `4h` | 0,37 % | ≈ 0,18 | **−0,022 R** |
| `5min` | 0,2106 % | **0,341** | **+0,092 R** |

🔴 **Monotone.** Le « signal » apparaît exactement là où l'artefact de prix
d'entrée est le plus grand devant le stop. ⛔ Ce n'est pas testé ici — ce banc
ne porte que sur le `5min` — mais c'est une **conséquence vérifiable**, et je
l'écris d'avance pour ne pas pouvoir la découvrir « après coup ».

## La conception : une spécification de fill COMMUNE aux deux bras

| cellule | bras réel | placebo |
|---|---|---|
| `REF_STOCKE` | `entry` **stocké** d'août | ouverture de la bougie tirée |
| **`FILL_OUVERTURE`** | **ouverture de sa bougie d'entrée** | ouverture de la bougie tirée |

Dans `FILL_OUVERTURE`, les deux bras entrent **à l'ouverture de leur propre
bougie d'entrée**, avec le **`risk_pct` stocké** et `R:R = 1,8` autour de ce
prix. ⇒ **Même spécification d'exécution des deux côtés**, et aucune barrière
ne peut être franchie avant l'entrée.

⛔ **C'est une RE-SPÉCIFICATION DU BRAS RÉEL, et je le dis net.** Elle le rend
**non comparable** aux chiffres publiés — d'où la cellule `REF_STOCKE`, qui doit
reproduire `espérance réelle = −0,059336` et `écart = +0,091961` à 1 % près,
sinon le banc **s'arrête**.

⚖️ **Pourquoi cette re-spécification est légitime** : la question posée est
« l'instant d'entrée porte-t-il de l'information ? ». Pour y répondre, les deux
bras doivent partager leur **modèle d'exécution**. Un niveau de motif atteint
dans 49,8 % des cas n'est pas une exécution — c'est un ordre à cours limité
dont on ignore s'il a été rempli. Entrer au marché à l'ouverture suivante est,
elle, **toujours réalisable**.

⚠️ **Et ce n'est pas la seule spécification défendable.** On pourrait exiger que
le prix **atteigne** le niveau du motif, sinon pas de trade — mais cela change
`n` et introduit une sélection. Je n'en teste **qu'une**, celle qui garde `n`.

## 🔑 L'ARITHMÉTIQUE, faite AVANT d'engager les seuils

Sous `FILL_OUVERTURE`, la contribution de la première bougie au bras réel doit
rejoindre celle du placebo (≈ −0,043 R au lieu de +0,064 R) :

```
esperance reelle attendue  ~  -0,0593 - 0,107  =  -0,166 R
placebo (inchange)                             =  -0,151 R
=> ecart attendu                               ~  -0,015 R
=> t attendu                                   ~  -0,015 / 0,021  ~  -0,7
```

⚠️ **Premier ordre seulement** : changer le prix d'entrée déplace aussi les
barrières de tout le reste du chemin. L'estimation donne l'**ordre de
grandeur**, pas la valeur.

### Contrôle d'amplitude

- **L'écart** n'est pas borné ; les valeurs de la série vont de **−0,27** à
  **+0,24 R**. Les seuils **+0,05**, **0** et **−0,08** sont tous intérieurs.
- **`|t|`** : la barre de **2,00** est franchissable dans les deux sens (le
  même banc rend +4,39 sous l'autre spécification).
- **`esperance_R_reel_fill`** : seuil **−0,12** intérieur (observé −0,059 sous
  l'ancienne spécification, attendu −0,166 sous la neuve).
- **L'asymétrie de première bougie** vaut aujourd'hui
  `|7,0−2,7| + |6,2−9,2| = **7,3 points**` ; le seuil de **2,0** est donc très
  en dessous de l'actuel et **atteignable** si la re-spécification agit.

<!-- CRITERE-MACHINE
statistique: ecart_signal_sous_fill_realisable
convention: A
forme: placebo
horizon: 5min
fenetre_heures: 96
source_bras_reel: RECALCULE
cellules_fill: REF_STOCKE,FILL_OUVERTURE
cellule_decisive: FILL_OUVERTURE
population: resolved_backfill=0 AND timeframe=5min AND pair IN 7_BINANCE AND bar_timestamp < 2026-08-20
fin_chargement: 2026-10-27T18:00:00+00:00
tirages_placebo: 200
graine: 20261027
cellules: 1
reference_esperance_reel_stocke: -0.059336
reference_ecart_stocke: 0.091961
validite: n_reel >= 3500 ET couverture_bougies_pct > 99 ET ecart_reproduction_max_pct < 1.0 ET part_entree_hors_bougie_stocke_pct > 30 ET part_entree_hors_bougie_fill_pct < 0.5 ET tirages_aboutis >= 190
admission: ecart_signal_fill > 0 ET t_fill > 2.00
rejet: abs(t_fill) < 2.00
P1_ecart_signal_fill_max: 0.05
P2_t_fill_abs_max: 2.00
P3_esperance_reel_fill_max: -0.12
P4_asymetrie_premiere_bougie_pts_max: 2.0
P5_ecart_signal_fill_plancher: -0.08
-->

⚠️ **Correspondance des noms** : `admission` = **le signal SURVIT** à une
spécification de fill symétrique. `rejet` = **il DISPARAÎT**, et l'écart publié
était un artefact de **prix d'entrée**.

🔑 **Les deux gardes qui vérifient que la re-spécification a AGI** :
`part_entree_hors_bougie_stocke_pct > 30` (l'ancien bras réel entre bien hors
de sa bougie — observé 50,2 %) et `part_entree_hors_bougie_fill_pct < 0.5`
(le neuf n'y entre **jamais**, par construction). ⛔ Sans elles, une
re-spécification **inerte** rendrait un résultat d'apparence normale.

## Prédictions, dites d'avance

1. **`écart(FILL) < +0,05 R`** — l'écart s'effondre depuis +0,092.
2. **`|t(FILL)| < 2,00`** — 🔑 **LA PRÉDICTION DÉCISIVE** : le signal devient
   **indiscernable du hasard**. Attendu ≈ **−0,7**.
3. **`espérance réelle(FILL) < −0,12 R`** — la perte réelle s'aggrave
   nettement, attendue ≈ **−0,166 R**.
4. **asymétrie de première bougie < 2,0 points** — la cause disparaît.
5. **`écart(FILL) > −0,08 R`** — et pas absurdement négatif.

## Ce que chaque issue implique

- **Rejet (`P2` tenue)** ⇒ 🔴 **JE RETIRE LE SIGNAL `5min`.** L'écart publié en
  `c5c68dc`, `2613282` et `8935497` serait un **artefact de prix d'entrée**, et
  **aucun horizon n'aurait d'information démontrée à l'entrée**. Ce serait la
  **rétractation la plus lourde de la série**, et je l'écrirai comme telle,
  avec la correction des trois verdicts.
- **Admission** ⇒ le signal **survit** à une exécution réalisable, et il devient
  **bien plus solide** qu'avant ce banc. ⛔ Et toujours **non exploitable** :
  l'écart devrait dépasser **0,0950 R** de coût, ce qu'aucune mesure n'a jamais
  montré.
- **Ni l'un ni l'autre** (`écart < 0` mais `|t| ≥ 2`) ⇒ l'instant porterait une
  information **défavorable**, comme le `1d`. ⇒ **Même conclusion pratique** :
  rien à exploiter.
- ⚠️ **Si `P3` échoue** alors que `P2` tient, mon arithmétique de première
  bougie est fausse quelque part, et je devrai le dire avant d'interpréter.

## ⚠️ Limites

- **Hors échantillon seulement** (4 280 lignes, 7 paires crypto, 05 → 19/08).
- **Une seule spécification de fill testée** (marché à l'ouverture suivante).
- L'extension aux horizons `1d` et `4h` est **annoncée mais non testée ici**.
- L'**asymétrie résiduelle de source** (bornes d'août, bougies du jour)
  subsiste, et elle est **plus petite** sous cette spécification puisque le prix
  d'entrée ne vient plus d'août.
- Antériorité du banc partagé : refus pré-annoncé, skill **non modifiée**.
