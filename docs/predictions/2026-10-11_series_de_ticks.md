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
