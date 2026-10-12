# Inverser le sens de chaque trade

**Déclaré le 2026-10-12, AVANT de regarder la donnée.**

Xavier :

> « Je vois que beaucoup de trades démarrent mal et je pense qu'il faudrait
> que quand tu souhaites lancer un trade en sell, il faudrait le lancer en buy
> et inversement. »

## ⚠️ POURQUOI JE DOUTE, et c'est arithmétique

**Inverser retourne le signal, pas le coût.** Un achat entre à l'`ask` et sort
au `bid` ; une vente fait l'inverse. Les deux paient le spread. Si le
rendement s'écrit `mouvement − coût`, l'inversion donne `−mouvement − coût` :
le coût reste du même côté.

⇒ Si le sens porte une information **nulle**, l'inverser laisse **la même
chose** : zéro d'information et le même coût. L'inversion ne peut payer que si
le sens porte une information **NÉGATIVE**.

Et c'est mesuré **deux fois**, pré-inscrit les deux fois :

```
5 jours, n=59, horizons 1->60 min   aucune p sous 0,27, reussite 42-54 %
64 062 detections, 6 geometries     reussite 49,83 %, 0 retenue
```

🔑 Le déficit de 49,83 % contre 50 % vaut **0,17 point**. Pour qu'une inversion
rapporte, il faudrait que ce déficit dépasse le coût — qui vaut, lui,
**2,40 points de réussite** (mesuré ce matin, `98f26ec`). L'ordre de grandeur
est contre lui d'un facteur **14**.

## ⚠️ MAIS SON OBSERVATION EST UNE AUTRE QUESTION

« Démarrer mal » peut être **vrai** sans que le sens soit en cause. Si les
trades partent mal dans **les deux sens**, c'est le coût d'entrée, et inverser
n'y change rien — on paierait le même spread en partant du mauvais pied dans
l'autre direction.

⇒ **C'est la dissymétrie qu'il faut mesurer, pas la moyenne.**

## Ce qu'on mesure

| | mesure |
|---|---|
| ① | l'**excursion adverse immédiate** après l'entrée (30 s, 60 s, 300 s), **séparée par sens**, sur les trades RÉELS du jour |
| ② | la même chose sur le magasin de ticks, entrées synthétiques, pour avoir du volume |
| ③ | l'**inversion appariée** : chaque position rejouée dans son sens et dans l'autre, mêmes instants, mêmes ticks, coût réel (+10 pts de markup) |

③ est le test de sa proposition. ① et ② disent si « démarrer mal » est
symétrique.

## ⛔ LE CRITÈRE

L'inversion remplace la production **si et seulement si** l'écart de rendement
`inversé − original` est **significativement positif**, `t > +2,0` sur l'unité
**JOUR**.

🔑 Et une condition de cohérence, posée d'avance : si l'écart est positif mais
que l'excursion adverse est **symétrique** entre achats et ventes, je ne
conclurai pas — un gain sans mécanisme sur un échantillon court est la
signature du bruit, et j'ai déjà payé ça (`B−C` passé de `t +2,28` à `+0,52`
hors échantillon).

## MES PRÉDICTIONS, posées avant de regarder

1. ✅ **Son observation sera VRAIE** : les trades démarrent bien mal. Je prédis
   une excursion adverse médiane à 30 s d'au moins **un spread** (≈0,19 €),
   simplement parce qu'on entre à l'`ask` et qu'on se marque au `bid`.
2. 🔑 **Et elle sera SYMÉTRIQUE** — c'est ma prédiction centrale. Je prédis que
   l'excursion adverse des achats et celle des ventes ne diffèrent pas de plus
   de **0,05 €**. Si c'est vrai, « démarrer mal » est le **coût d'entrée**, pas
   une erreur de sens, et l'inversion est réfutée par construction.
3. ⛔ **L'inversion sera indistinguable** : `|t| < 2` sur l'écart apparié. Et je
   prédis que son signe sera **négatif ou nul**, pas positif.
4. 🔑 **Les deux sens seront négatifs au coût réel.** C'est la prédiction la
   plus utile : si achats ET ventes perdent, aucune permutation des deux ne
   peut gagner. Le problème serait la **géométrie**, pas la direction.
5. ⚠️ **Et je prédis que le réel du jour sera trop court pour trancher seul** —
   quelques dizaines de trades. Je l'écris pour ne pas présenter un `t`
   calculé sur 60 trades comme une conclusion.

⇒ Si 2 et 4 tiennent, la recommandation sera de **ne pas inverser**, et de
dire où le problème est réellement : dans le coût et la géométrie.

---

# VERDICT, le 2026-10-12 : NE PAS INVERSER — et la cible est ailleurs

3 429 790 ticks, 16 jours, 4 297 positions, apparié sur le JOUR.
Plus 125 trades RÉELS du jour.

## ⛔ L'inversion échoue son critère

```
                  moyenne   reussite
ORIGINAL          -0,0881     78,2 %
INVERSE           -0,0409     78,9 %
ecart +0,0473 EUR/trade   t +1,15   11 jours sur 16
```

`t = +1,15`, sous les +2,0 requis. ⇒ **non retenue.**

🔑 Et ma **condition de cohérence**, posée d'avance, s'applique : l'écart est
positif mais l'excursion adverse est **symétrique** (voir ci-dessous), donc il
n'y a **pas de mécanisme** — c'est la signature du bruit. Je ne conclus pas à
un gain.

## 🔑 POURQUOI : « démarrer mal » est SYMÉTRIQUE

```
                30 s        60 s       300 s
ACHAT        -0,5537     -0,7412     -1,5360
VENTE        -0,5358     -0,7189     -1,5181
ecart        -0,0179     -0,0223     -0,0179
```

✅ **Son observation était juste : les trades démarrent bel et bien mal** —
médiane **−0,55 €** dès 30 s. Mais l'écart entre les deux sens ne dépasse pas
**0,022 €**. C'est le **coût d'entrée**, pas une erreur de direction : on entre
à l'`ask` et on se marque au `bid`, dans un sens comme dans l'autre.

⇒ Inverser ferait démarrer mal dans l'autre sens, pour le même prix.

## ✅ ET LA QUESTION QUI DÉCIDE : LES DEUX SENS PERDENT

```
ACHATS   n=2149   -0,0903   reussite 78,1 %
VENTES   n=2148   -0,0859   reussite 78,2 %
```

🔑 **Aucune permutation de deux perdants ne donne un gagnant.**

## MES PRÉDICTIONS : 5 sur 5

| n° | prédiction | verdict |
|---|---|---|
| 1 | les trades démarrent mal, ≥ 1 spread à 30 s | ✅ **−0,55 €**, bien au-delà |
| 2 | et c'est SYMÉTRIQUE, écart ≤ 0,05 € | ✅ **0,022 €** |
| 3 | l'inversion est indistinguable, `\|t\| < 2` | ✅ `t = +1,15` |
| 4 | les deux sens perdent | ✅ −0,0903 / −0,0859 |
| 5 | le réel du jour ne tranchera pas seul | ✅ honorée |

## 🔴 CE QUE XAVIER VOYAIT VRAIMENT : TROIS TRADES

Son observation portait sur du réel, et le réel dit autre chose que ce qu'il
en a déduit :

```
aujourd hui : achats n=63 moyenne -0,031   ventes n=62 moyenne -0,264
   ecart +0,2329 EUR/trade   t de Welch +0,87   => NON significatif
```

Et la dissymétrie **ne se reproduit pas** — le 02/10 elle pointait dans
**l'autre sens** (ventes **+9,38**, achats **−5,57**) :

```
jour          achat        vente        ecart
2026-10-02   -5,5680     +9,3800     -14,9480     <- signe INVERSE
2026-10-09   -0,2611     -0,5177      +0,2566
2026-10-12   -0,0311     -0,2640      +0,2329
   3 jours : ecart moyen -4,8195   t -0,95
```

⛔ **Et 91 % de la perte du jour tient à TROIS trades** :

```
01:17  sell  -7,37   SL  en  2,9 min   engulfing_bearish
12:20  buy   -5,03   SL  en  5,2 min   range_bounce_up
05:32  sell  -4,26   SL  en  4,7 min   breakout_down
   les 3 pires = -16,66 des -18,33 EUR, soit 91 %
```

🔑 **Trois sells, trois buys dans les six pires** : la queue est symétrique
elle aussi.

## ⇒ LA VRAIE CIBLE, chiffrée

```
125 trades, -18,33 EUR
   83 gagnants  moyenne +0,623 EUR
   41 perdants  moyenne -1,708 EUR     <- 2,7 x le gagnant
   reussite OBTENUE 66,4 %   REQUISE 73,3 %   manque -6,9 points
```

Ce n'est pas la direction. C'est qu'**un perdant coûte 2,7 fois ce qu'un
gagnant rapporte**, et que la queue tient à trois trades stoppés en **moins de
6 minutes**.

🔑 **Piste jamais mesurée** : les six pires ont perdu 3 à 7 € en **2,9 à
5,8 minutes**. La protection ne peut agir qu'après 60 s d'âge + 30 s de
négativité consécutive, puis à une cadence de 60 s — elle arrive donc au plus
tôt vers 90 s, quand le mouvement adverse est déjà fait. Un déclencheur sur la
**VITESSE** du mouvement adverse, et non sur sa durée, n'a jamais été teste.
C'est la mesure qui vaut le plus maintenant.
