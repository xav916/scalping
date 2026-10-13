# La volatilité dit-elle QUAND ouvrir, et DANS QUEL SENS ?

**Déclaré le 2026-10-14, AVANT d'écrire la mesure.**

Xavier : *« peut-on trouver un pattern lié à la volatilité du marché qui nous
indiquerait quand ouvrir la position et dans quel sens »*

## ⚠️ LE PRIOR EST CONTRE, et il faut le poser d'abord

La direction a été réfutée **deux fois**, pré-inscrite les deux fois :

```
5 jours, n=59, horizons 1->60 min    aucune p sous 0,27, reussite 42-54 %
64 062 detections, 6 geometries      reussite 49,83 %, 0 retenue
```

⛔ Mais ces deux bancs mesuraient la direction **sans conditionner**. « La
direction devient-elle prévisible dans certains régimes de volatilité ? » est
une question **distincte** et jamais posée. Un effet moyen nul peut cacher deux
effets opposés qui s'annulent — c'est improbable, ce n'est pas impossible.

🔑 Et la mesure d'aujourd'hui rend ce prior encore plus défavorable :
l'amplitude des 15 minutes précédant l'entrée ne corrèle **pas** avec la perte
du trade (`r = +0,0201`, `t = +1,38`). La volatilité ne porte donc déjà
**aucune** information sur l'**issue**. Il reste à voir si elle en porte sur le
**sens**.

## Ce qu'on mesure

**Le régime de volatilité** = l'amplitude des 15 minutes **strictement avant**
l'instant considéré, découpée en **quintiles** (mesuré ce jour : médiane
5,76 €, p90 10,89 €).

| question | mesure |
|---|---|
| **① LE SENS** | dans chaque quintile : le mouvement des N minutes **suivantes** est-il prévisible par celui des 15 minutes **précédentes** ? (momentum si même signe, retour à la moyenne si signe opposé) |
| **② QUAND** | dans chaque quintile : que rend un trade ouvert là, avec la géométrie de production, **dans les deux sens** ? |

Horizons : **5, 15, 60 min**. ⇒ `5 quintiles × 3 horizons = 15 cellules` pour
①, et `5 quintiles × 2 sens = 10 cellules` pour ②.

## ⛔ LE CRITÈRE — plafond par PERMUTATION, pas un `t` de confort

Avec 25 cellules, un `|t|` de 2,0 est franchi par le hasard seul dans la
quasi-totalité des tirages. Donc :

1. le plafond est **calculé par permutation** : on rejoue 200 fois en
   **mélangeant les étiquettes de quintile entre les instants**, et on retient
   le `|t|` maximal atteint par le hasard. Une cellule ne compte que si elle
   **dépasse ce plafond** ;
2. **et** l'effet doit tenir **hors échantillon** (moitié/moitié, quintiles
   calculés sur la première moitié seulement) ;
3. **et** pour ① l'effet doit être **monotone** en régime — un effet qui
   apparaît dans le 3ᵉ quintile et disparaît dans le 4ᵉ est du bruit, pas un
   mécanisme.

🔑 La condition 3 est celle qui distingue « un pattern » de « une cellule
chanceuse ». C'est aussi celle qui a manqué à mes deux critères trop
permissifs du 12 et du 14/10.

⚠️ **Et je refuse d'avance le réglage a posteriori** : pas de changement de
découpage, d'horizon ou de mesure de volatilité après avoir vu les chiffres.
Ce qui est écrit ici est ce qui sera mesuré.

## MES PRÉDICTIONS, posées avant de coder

1. ⛔ **Aucune cellule de ① ne dépassera le plafond de permutation.** Prior :
   49,83 % sur 64 062 détections. Je prédis un plafond autour de `|t| = 3,0`
   et un maximum observé sous 2,5.
2. 🔑 **MAIS ② montrera quelque chose de réel et de trivial** : le rendement
   par trade sera **pire dans les quintiles hauts**, et monotone. Ce n'est pas
   un edge — c'est le **coût** : plus ça bouge, plus l'excursion adverse est
   grande. Je prédis un écart d'au moins **0,05 €/trade** entre le quintile 1
   et le quintile 5.
3. ⚠️ **Et c'est ça qui sera exploitable, pas le sens** : si ② est monotone,
   alors « quand ouvrir » a une réponse — **dans le calme** — même si « dans
   quel sens » n'en a pas. Ce serait le premier filtre d'entrée du projet à
   reposer sur un mécanisme plutôt que sur une corrélation.
4. ⛔ **Les deux sens seront négatifs dans TOUS les quintiles.** Si c'est vrai,
   aucun régime ne rend l'or rentable — le filtre ne ferait que **perdre
   moins**, jamais gagner. Je le dis d'avance pour ne pas présenter une
   réduction de perte comme un gain.
5. 🔑 **Et une prédiction qui me contredirait** : si un quintile montre les
   deux sens **positifs**, alors il existe un régime où l'or est rentable
   quelle que soit la direction — ce qui voudrait dire que c'est la
   **géométrie** qui paie dans ce régime, pas la direction. Ce serait le
   résultat le plus important du projet, et je le re-mesurerais trois fois
   avant d'y croire.

⇒ Si 1 et 2 tiennent, la réponse à Xavier sera : **« quand » a une réponse,
« dans quel sens » n'en a pas.**

---

# VERDICT, le 2026-10-14 : NI « QUAND », NI « DANS QUEL SENS »

3 682 189 ticks, 18 jours, 4 669 instants. Quintiles et plafond calculés sur
la **première moitié seulement**.

## ⛔ ① LE SENS reste muet, même conditionné à la volatilité

```
la cellule la plus forte :  Q5 (le plus volatil), horizon 60 min
                            r = -0,1607    t = -3,60    n = 492
plafond par permutation (200 melanges) :  median 2,644   p95 3,758   max 4,886
|t| maximal OBSERVE : 3,605
```

**3,605 < 3,758** ⇒ **aucune cellule ne dépasse le plafond.** Le sens n'est pas
prévisible, y compris dans les régimes extrêmes.

⚠️ Et il faut dire que le plafond est **haut** (p95 = 3,76) précisément parce
qu'il y a 15 cellules : c'est le prix du découpage, et c'est pourquoi il était
posé **d'avance**. Avec un `t` de confort à 2,0, **sept** cellules auraient
« passé » — et le hasard seul en fait passer autant.

## ⛔ ② « QUAND » N'A PAS DE RÉPONSE NON PLUS — le signe s'inverse

```
          dedans                      dehors
Q1       -0,1310                     -0,1042
Q2       -0,0796                     -0,0453
Q3       -0,0166                     -0,0003
Q4       -0,1003                     +0,0563
Q5       +0,0026                     -0,1130

monotone ?   dedans NON    dehors NON
ecart Q1->Q5  -0,1337       +0,0088      <- LE SIGNE S'INVERSE
```

Le quintile le plus volatil est **le meilleur** en échantillon (+0,0026) et
**le pire** hors échantillon (−0,1130). La condition 3 (monotonie) échoue dans
les deux moitiés.

🔑 Et chaque cellule positive **ne se reproduit pas** : `Q5` achats passe de
**+0,0985** à **−0,1091** ; `Q4` passe de **−0,1003** à **+0,0563**.

## MES PRÉDICTIONS : 1 sur 5, et les échecs sont instructifs

| n° | prédiction | verdict |
|---|---|---|
| 1 | aucune cellule de ① ne passera, plafond ≈ 3,0, max observé < 2,5 | ⚠️ **conclusion JUSTE, chiffres FAUX** : plafond 3,76 et max 3,61 |
| 2 | ② sera **monotone**, pire dans les quintiles hauts, ≥ 0,05 € d'écart | ⛔ **FAUSSE** : non monotone, et le signe s'inverse |
| 3 | « quand » aura une réponse : **dans le calme** | ⛔ **FAUSSE** — elle dépendait de la 2 |
| 4 | les deux sens négatifs dans TOUS les quintiles | ⛔ **fausse à la lettre** (`Q3`, `Q4`, `Q5` ont des cellules positives) — ✅ **juste au fond** : aucune ne se reproduit |
| 5 | si un quintile montre les deux sens positifs, ce serait majeur | ⚠️ `Q4` hors échantillon les montre (**+0,058 / +0,055**) — mais il valait **−0,215 / +0,015** dedans ⇒ **bruit** |

## ⇒ LA RÉPONSE À XAVIER

⛔ **Aucun pattern de volatilité n'indique quand ouvrir, ni dans quel sens.**
C'est la **troisième** réfutation de la direction, et la première qui la teste
**conditionnée** — donc la plus difficile à contourner : on ne peut plus dire
« l'effet moyen est nul parce que deux régimes s'annulent ».

🔑 **La seule chose qui pointe un mécanisme**, et je la nomme en disant qu'elle
a **échoué sa barre** : `Q5` à 60 min montre un **retour à la moyenne**
(`r = −0,1607`, `t = −3,60`) — après une forte agitation, l'or tend à revenir.
C'est un phénomène de marché connu, et c'est la seule cellule à portée du
plafond.

⛔ **Mais elle ne le franchit pas, et je refuse de la re-tester sur ces mêmes
18 jours** : re-découper la même donnée jusqu'à ce qu'une cellule passe est
exactement ce que ce plafond existe pour empêcher. Si on l'éprouve un jour, ce
sera sur une **fenêtre neuve** et avec une **pré-inscription neuve**.
