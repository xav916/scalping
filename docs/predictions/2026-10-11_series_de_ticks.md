# Les SÉRIES de ticks : la construction d'une figure, à l'échelle du tick

**Déclaré le 2026-10-11, AVANT de mesurer.** Xavier : « à partir du moment où
nous pouvons suivre en live l'évolution des ticks et que nous pouvons y repérer
la **construction** d'un pattern, nous pourrons donner un sens aux trades que
nous allons ouvrir ».

## La pièce qui manque, et c'est la seule

Son cycle de vie tient : suivre les ticks (budget mesuré **55 ms**, soit 18
passages/s possibles), ouvrir avec un stop, appliquer les règles négatives puis
positives — **tout cela est construit et testé**. La seule pièce non mesurée est
**ce qui donne le sens**.

Et sa figure la plus simple — « ça monte, donc ça va descendre » — n'existe
**nulle part** dans le dépôt : ni sur bougies (où `pin_bar`, `engulfing`,
`double_sweep` sont à zéro), ni sur ticks. C'est donc une mesure neuve.

## Ce que je mesure : la SÉRIE

À chaque tick, la **longueur de la série en cours** : le nombre de variations de
bid consécutives dans le même sens. Une série de 5 hausses, c'est « ça monte »
au sens de Xavier.

    longueurs testées : k >= 3, 5, 8, 12

Deux moments d'entrée, et ils testent deux choses différentes :

- **AU k-ième tick** — on entre pendant que la série court : c'est la
  **continuation** ;
- **À LA CASSURE** — on attend le premier tick de sens opposé, puis on entre :
  c'est le **retournement**, exactement ce que Xavier décrit.

Deux géométries : la production (départ −13 €, traînage 0,50 €, aucun objectif,
protection à 60 s) et des **bornes symétriques ±2 €**.

⇒ **4 longueurs × 2 moments × 2 géométries = 16 cellules.**

🔑 Le contrôle est **intrinsèque** : continuation et retournement sont les deux
sens opposés au même instant. Mesurer l'un donne l'autre, et leur écart est
l'information — exactement le contrôle apparié des bancs précédents.

Plafond par **permutation** : 200 tirages d'instants faux, appariés sur l'heure.
Unité = **le JOUR** (15 jours). **3 298 970 ticks** du courtier.

## ⛔ LE CRITÈRE

Une cellule est retenue si son |t| dépasse le 95ᵉ centile du max|t| des 200
permutations, avec **n ≥ 200** et un **signe stable sur les deux moitiés**.

## MA PRÉDICTION, POSÉE MAINTENANT

1. ⛔ **0 cellule retenue sur 16.** C'est mon septième zéro annoncé, et je le
   pose avec la même méthode que les six premiers.
2. 🔑 **MAIS si une cellule passe, je prédis que ce sera le RETOURNEMENT sur les
   séries LONGUES** (k ≥ 8), et pas la continuation. Motif : le seul chiffre de
   la journée qui ait approché ma barre est le tick rate à 10 s, à **|t| = 2,24
   contre un plafond de 2,260** — et son signe dit que **quand le flux est
   dense, entrer dans le sens du mouvement PERD**. C'est l'intuition de Xavier,
   et elle penche déjà dans son sens.
3. ⚠️ Je prédis que les **séries longues seront rares** : une série de 12
   variations consécutives dans le même sens devrait représenter moins de 1 %
   des instants, donc `n` pourrait tomber sous 200 et disqualifier la cellule
   par manque d'effectif plutôt que par absence de signal. Je le dirai si ça
   arrive.
4. ✅ Et je prédis que la **continuation sera clairement négative** — entrer
   dans un mouvement déjà couru, c'est payer la fin du mouvement.

⇒ Si le retournement passe, Xavier a trouvé le premier signal directionnel du
projet, et la détection doit passer aux séries de ticks.


---

# VERDICT — 2026-10-11

`scripts/banc_series_de_ticks.py`. **3 298 970 ticks**, 15 jours. Plafond par
permutation : **2,123**.

## La distribution des séries, d'abord

    >= 2 variations consecutives : 59,923 %
    >= 3                         : 37,137 %
    >= 5                         : 14,496 %
    >= 8                         :  3,629 %
    >= 12                        :  0,602 %
    >= 16                        :  0,101 %

## ⇒ 0 CELLULE RETENUE SUR 16. Tous les |t| ≤ 1,39.

    k   moment          geometrie       n     le sens  l'inverse   ecart      t
    3   au k-ieme       symetrique    4087    -0,0083    -0,1242  +0,1148  +1,29
    3   au k-ieme       production    4087    +0,0867    +0,0240  +0,0611  +1,23
    5   a la cassure    symetrique    4002    -0,1129    -0,0299  -0,0827  -1,39
    8   a la cassure    production    3675    +0,0465    -0,0074  +0,0533  +0,96
    8   a la cassure    symetrique    3675    -0,0225    -0,1060  +0,0829  +0,96
    12  au k-ieme       production    2433    +0,0304    +0,0241  +0,0071  +0,15
    ... les dix autres : |t| <= 0,80

## ⛔ TROIS DE MES QUATRE PRÉDICTIONS SONT FAUSSES

1. ✅ « 0 cellule retenue sur 16 » : **juste**. Septième zéro annoncé, septième
   zéro obtenu.
2. ⛔ « si une cellule passe, ce sera le RETOURNEMENT sur les séries longues » :
   **faux**. Les deux plus gros |t| sont la **CONTINUATION sur les séries
   COURTES** (k = 3, t +1,29 et +1,23). Le retournement sur k ≥ 8 fait +0,96.
3. ⛔ « les séries longues seront rares, n pourrait tomber sous 200 » : **faux**.
   k = 12 garde **2 433 entrées** — le repos de 5 minutes les espace, donc
   l'effectif ne s'effondre pas. Aucune cellule n'a été disqualifiée par manque
   d'effectif.
4. ⛔ « la continuation sera clairement négative » : **faux, et à l'envers**.
   C'est la continuation sur séries courtes qui donne les **meilleurs** écarts
   (+0,1148 et +0,0611).

🔑 Ce qui reste de la journée : **sur sept bancs dont j'avais annoncé le
résultat, j'ai eu raison sept fois sur le ZÉRO, et faux la plupart du temps sur
le MÉCANISME.** Le zéro est robuste ; mes explications ne le sont pas.

## ⇒ CE QUE ÇA FERME

La figure de Xavier — « ça monte, donc ça va descendre » — est mesurée à
l'échelle du tick, dans les deux sens, à quatre longueurs, sur 3,3 millions de
ticks : **elle ne porte pas de direction**. C'est le **septième zéro
indépendant**, et il couvre désormais :

    les motifs (0/22, 0/28, 2/30 anti-predictifs) · l'echelle jusqu'au tick
    (0/16) · l'instant de la decision (0/4) · et la microstructure (0/16)
