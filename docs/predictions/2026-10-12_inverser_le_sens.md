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
