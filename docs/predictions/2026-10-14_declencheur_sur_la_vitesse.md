# Un déclencheur sur la VITESSE du mouvement adverse

**Déclaré le 2026-10-14, AVANT d'écrire la mesure.**

Xavier : *« Vas y »* — après le verdict sur la largeur du stop
(`44ddc40`), qui désignait la vitesse comme la seule piste ouverte.

## D'OÙ VIENT CETTE PISTE

```
le 12/10, 125 trades automatiques, -18,33 EUR
   les 3 PIRES font 91 % de la perte nette
   et ils sont morts en  2,9 / 4,7 / 5,2 minutes
```

Or la protection ne peut **rien** faire avant ~**90 secondes** : 60 s d'âge
minimum, **plus** 30 s de négativité **consécutive**, **puis** une cadence de
60 s. Quand elle arrive, le mouvement adverse est déjà fait.

🔑 **Elle mesure une DURÉE, jamais une VITESSE.** Un trade qui perd 7 € en
3 minutes et un trade qui perd 0,50 € en 3 minutes lui sont indistinguables.

## ⚠️ CE QUI REND CETTE ÉTUDE DIFFICILE, et qu'il faut dire d'avance

Trois faits mesurés rendent le succès improbable :

1. L'excursion adverse immédiate est **symétrique** entre achats et ventes
   (écart ≤ 0,022 €) — donc un départ rapide dans le mauvais sens n'est pas
   un signal de direction, c'est le coût d'entrée.
2. **43 cellules de largeur de stop, 0 retenue** ; et chaque intervention
   testée jusqu'ici nette à zéro.
3. Le traînage produit **100 % des gains** (108 trades, +64,02 € le 12/10).
   Toute règle qui coupe tôt risque de couper ce qui paie.

⇒ Je m'attends à ce que la queue s'affine **et** que le rendement ne bouge
pas. Ce serait alors un choix de **préférence de risque** pour Xavier, pas une
amélioration de rendement — et je le dirai comme tel.

## Les cellules

| | règle | mesure |
|---|---|---|
| **A** | production : âge 60 s, négativité 30 s **consécutive**, cadence 60 s, point milieu, plancher `2 × spread`, plafond 9 € | une **durée** |
| **B** | **vitesse** : dès que le P&L chute de `V` € sur 30 s glissantes, resserrer au point milieu **immédiatement** — sans attendre l'âge ni la négativité | une **vitesse** |
| **C** | **vitesse + fermeture** : même déclenchement, mais on **ferme au marché** au lieu de resserrer | une vitesse |
| **D** | ⛔ **TÉMOIN : cadence 15 s** au lieu de 60 s, mêmes règles d'âge et de négativité | une durée, plus souvent |
| **E** | ⛔ **TÉMOIN : aucun âge minimum**, négativité 30 s, cadence 60 s | une durée, plus tôt |

🔑 **`D` et `E` sont le cœur du protocole.** Si « réagir plus tôt » ou « regarder
plus souvent » fait aussi bien que `B`, alors **la vitesse n'apporte RIEN** et
seul le délai comptait. Sans ces témoins, un gain de `B` serait inattribuable.

⚠️ **`V` est calibré** pour que `B` et `C` se déclenchent sur la **même
fraction** de trades (**les 10 % de descentes les plus rapides**). Sans ça on
mesurerait « se déclenche souvent » contre « se déclenche rarement », pas la
règle elle-même.

Tout le reste reprend la production du 14/10 : stop initial 0,35 %, traînage
`2 × spread`, aucun objectif, coût réel (+10 pts de markup), population
**FIXE**.

## ⛔ LE CRITÈRE — strict, et corrigé de ma faute de la veille

Hier ma condition d'admission était « `t > −2` », franchie trivialement par
tout ce qui ne fait rien. **Une condition de « pas significativement pire » ne
peut jamais servir de condition d'admission.** Donc, cette fois :

Une cellule remplace A **si et seulement si** les **quatre** conditions
tiennent :

1. l'écart de rendement `cellule − A` est **significativement POSITIF** :
   `t > +2,0` sur l'unité JOUR ;
2. **et** la queue s'affine : les 3 pires trades de chaque journée pèsent
   moins que chez A ;
3. **et** le signe de l'écart **survit hors échantillon** — moitié/moitié,
   `V` calibré sur la **première** moitié seulement ;
4. **et** le rendement hors échantillon reste positif contre A.

⚠️ 5 cellules et 2 moitiés : je ne retiendrai rien sur un `t` isolé.

🔑 **Et une sortie explicitement prévue** : si la queue s'affine nettement
**sans** que le rendement bouge, je ne « retiens » pas la cellule — je
présente le **compromis chiffré** à Xavier et c'est lui qui tranche. Un choix
de préférence de risque n'est pas une mesure, et le déguiser en verdict serait
malhonnête.

## MES PRÉDICTIONS, posées avant de coder

1. ✅ **`B` affinera la queue de plus de 10 %.** Mécanisme direct : elle se
   déclenche exactement sur les descentes rapides, qui sont ce qui fait la
   queue. C'est ma prédiction la plus confiante.
2. ⛔ **Mais `B` ne passera PAS la condition 1** (`t > +2`). Elle coupera aussi
   des gagnants : une descente rapide précoce n'est pas un signal — l'excursion
   adverse est symétrique entre les sens.
3. 🔑 **`D` (cadence 15 s) fera aussi bien que `B` sur la queue** — et c'est la
   prédiction qui décide. Si elle tient, **la vitesse n'apporte rien** et il
   suffisait de regarder plus souvent.
4. ⛔ **`C` (fermeture au marché) sera la pire**, significativement sous `B` :
   fermer renonce au retour, alors que resserrer le garde.
5. ⚠️ **`E` (aucun âge minimum) sera mauvaise**, parce que les 30 premières
   secondes sont le coût d'entrée (**−0,55 € médian**) : intervenir là coupe
   presque tout.
6. 🔑 **Et une prédiction sur le hors échantillon** : je prédis que **tout
   écart positif en échantillon s'inverse dehors**, comme hier (3 cellules sur
   4). Si une cellule survit, ce sera le premier effet robuste du projet sur la
   gestion de sortie — et il faudra le re-mesurer avant d'y toucher.

⇒ Si 1 et 3 tiennent ensemble, la conclusion sera : **le délai de réaction est
le levier, pas la vitesse** — et le réglage à changer sera simplement la
cadence.
