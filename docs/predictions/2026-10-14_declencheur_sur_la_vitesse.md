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

---

# VERDICT, le 2026-10-14 : LA VITESSE PORTE QUELQUE CHOSE DE RÉEL

3 682 189 ticks, 18 jours, **4 669 positions fixes**. `V = 2,143 € / 30 s`
(les 10 % de descentes les plus rapides), **calibré sur la première moitié
seulement**.

## 🔑 LA QUEUE — et c'est le premier effet ROBUSTE de la journée

```
                    queue dedans   queue dehors    gain
A production            -20,18        -15,84       0 %  /  0 %
B vitesse resserre      -13,84        -11,50     +31,4 % / +27,4 %
C vitesse ferme         -13,81        -11,29     +31,6 % / +28,7 %
D TEMOIN cadence 15     -17,50        -12,61     +13,3 % / +20,4 %
E TEMOIN sans age       -20,18        -15,84       0 %  /  0 %
```

✅ `B` **affine la queue de 31 % dedans et 27 % dehors**. Même signe, même
ordre de grandeur dans les deux moitiés. **C'est le premier effet de cette
session qui survive au hors échantillon.**

## ⛔ MA PRÉDICTION n°3 EST FAUSSE — et c'est la bonne nouvelle

Je prédisais que le témoin `D` (cadence 15 s, sans mesurer la vitesse) ferait
**aussi bien** que `B`, auquel cas la vitesse n'aurait rien apporté.

**`D` n'obtient que +13,3 % dedans contre +31,4 % pour `B`** — moins de la
moitié. ⇒ **La vitesse porte une information que « regarder plus souvent » ne
donne pas.** Réagir plus vite explique environ un tiers de l'effet ; les deux
autres tiers viennent de **mesurer la vitesse elle-même**.

## ⛔ ET UN DÉFAUT DE MON PROTOCOLE : le témoin `E` est DÉGÉNÉRÉ

`E` (aucun âge minimum) rend des chiffres **identiques à `A` au centième**.
Raison : la cadence de 60 s impose déjà le délai — le premier contrôle tombe à
`t = 60 s`, où la condition d'âge est de toute façon satisfaite. **`E` ne
mesurait rien.** C'est une faute de conception de ma part, repérée par
l'égalité parfaite des deux lignes.

## ⛔ MAIS LE RENDEMENT NE BOUGE PAS — le critère rejette tout

```
B  ecart/jour :  dedans -0,0099 (t -0,64)   dehors +0,0018 (t +0,14)
```

La condition 1 exigeait `t > +2,0`. Elle échoue pour les quatre cellules.
⇒ **Rien n'est « retenu ».** Et c'est juste : la queue s'affine, le rendement
ne s'améliore pas.

Le prix de cette queue plus fine est visible : la **réussite** passe de
**78,9 % à 76,3 %** dedans (77,5 → 75,9 % dehors). `B` convertit quelques
petits gagnants en petits perdants, et coupe les gros perdants.

## MES PRÉDICTIONS : 2 sur 5

| n° | prédiction | verdict |
|---|---|---|
| 1 | `B` affinera la queue de plus de 10 % | ✅ **+31,4 / +27,4 %** |
| 2 | `B` ne passera pas `t > +2` | ✅ `t = −0,64 / +0,14` |
| 3 | `D` fera aussi bien que `B` | ⛔ **FAUSSE** — `D` fait moins de la moitié |
| 4 | `C` sera pire que `B` | ⚠️ égales sur la queue, `C` un peu pire en rendement |
| 5 | `E` sera mauvaise | ⛔ **FAUSSE** : `E` est **dégénérée**, elle ne mesure rien |

## ⇒ CE N'EST PAS UN VERDICT, C'EST UN CHOIX — et il est à Xavier

Je l'avais pré-inscrit : *« si la queue s'affine nettement sans que le
rendement bouge, je ne retiens pas la cellule — je présente le compromis
chiffré et c'est lui qui tranche »*.

```
le compromis, mesure dans les deux moities :
   la QUEUE s'affine de ~30 %   (les 3 pires trades de chaque journee)
   la REUSSITE perd ~2,5 points (78,9 -> 76,3 %)
   le RENDEMENT ne change pas   (t -0,64 dedans, +0,14 dehors)
```

⚠️ Ce n'est **pas** une machine à gagner. C'est une **réduction de variance
sans coût de rendement mesurable** — des pires journées moins dures, pour un
rendement identique. Sur un compte réel de 468 €, ça change ce qu'on ressent,
pas ce qu'on gagne.

🔑 Et une réserve honnête : 18 jours, et l'effet repose sur les **10 % de
descentes les plus rapides**, soit ~470 trades dont 3 par journée pèsent la
queue. **Ce n'est pas assez pour une politique durable** — mais c'est assez
pour mériter une mesure plus longue, ce qui n'était arrivé à aucune piste
aujourd'hui.
