# Trouver le X : oscillation dans une bande de 2 €, stop à 2 € du cours, objectif à +X

**Déclaré le 2026-10-11, AVANT de mesurer.** Xavier : « si le trade oscille
entre deux bornes à 2 euros, ramener le stop loss à 2 euros du cours et le TP à
plus X — trouve-moi le X. »

## ⓘ CE QUE LE DOCUMENT DIT DÉJÀ, ET CE QU'IL NE DIT PAS

Ses formules (EMA, VWAP, imbalance, Z) ont été mesurées le 2026-10-10
(`a761779`) comme **prédicteurs du mouvement futur**, jamais comme protection.
Verdict : ses deux setups prioritaires échouent **24 cellules sur 24**, et seul
le **retour à la moyenne sur Z** (son §6, qu'il diffère) respire — INDÉCIDABLE
hors échantillon (t +1,88 sous la barre).

🔑 Mais ce banc portait déjà un début de réponse à sa question d'aujourd'hui :

    bornes ($)        bon sens   mauvais    ecart      t
    2,24 / 22,40      +0,0024    -0,3034   +0,3058   +2,46
    5,00 /  5,00      +0,0673    -0,1800   +0,2473   +2,43
    10,00 / 10,00     +0,5794    -0,6794   +1,2589   +6,97

⇒ « L'information vit dans la dérive à l'heure et demande une cible d'ordre
**10 $ (~9 €)** ». Son intuition d'un X **bien plus grand que 2 €** a donc déjà
un appui — mais sur un **signal** (Z), pas sur une **oscillation**.

## Ce que je mesure maintenant, dans SA configuration

Condition, définie d'avance : sur les **10 dernières clôtures**, plage
**≤ 2,00 €** (elle se déclenche sur ~15 % des fenêtres, la médiane de la plage
10 min valant 3,688 €).

Quand elle se déclenche :

    stop  ->  cours − 2,00 €   (cliquet seul : jamais desserre, jamais du
                                mauvais cote du cours)
    objectif ->  cours + X

Hors condition : départ **−9 €**, point milieu côté perte, plancher **−2 €**.

**X balayé** : 1, 2, 3, 5, 7, 9, 10, 12, 15, 20 € **et aucun objectif**.
⇒ **11 cellules.**

Références, les meilleures connues à ce jour : traînage continu 0,50 € sans
objectif (**+0,0137 €/trade**) et le même élargi de +0,10 €/min en positif
(**+0,0454 €/trade**).

## ⛔ LE CRITÈRE

Le meilleur X est retenu s'il bat la meilleure référence avec **|t| > 3,0** sur
l'écart par **JOUR** — barre relevée de 2,5 à 3,0 parce que je balaie
**11 valeurs**, et que choisir le maximum d'un balayage est exactement la façon
de fabriquer un faux positif.

## MA PRÉDICTION, POSÉE MAINTENANT

1. 🔑 **Le meilleur X sera le plus GRAND, ou « aucun objectif »** — c'est ce que
   trois bancs disent déjà aujourd'hui : un objectif plafonne, et le retirer a
   gagné à `t = −3,12` et `t = −6,85`.
2. ⛔ **Aucun X ne franchira la barre de 3,0** contre le traînage élargi. Motif :
   la condition d'oscillation s'est révélée **inerte** ce matin — stagnation,
   volatilité et absence de condition donnaient le même chiffre à 0,001 €/trade
   près.
3. ⚠️ Et je prédis que **le stop à 2 € du cours fera PIRE que le traînage à
   0,50 €** quand il mord, parce qu'il rend 2 € au lieu de 0,50 € sur chaque
   repli.
4. ✅ Mais je prédis que le **plus gros gain** grandira avec X.

⇒ Si un X franchit la barre, c'est le premier réglage de sortie **établi** du
projet, et il faudra l'armer. Sinon, la réponse à « trouve-moi le X » est
**« X n'existe pas : c'est l'absence d'objectif »** — et je le dirai comme ça.


---

# VERDICT — 2026-10-11

`scripts/banc_trouver_le_X.py`. 6 668 trades aveugles, 99 999 bougies M1 du
courtier.

| variante | EUR/trade | ecart-type | pire jour | reussite | **max** | resserrages |
|---|---|---|---|---|---|---|
| X = 1 € | −0,1097 | 2,82 | −1,49 | 60,83 % | +4,07 | 1 500 |
| X = 2 € | −0,1010 | 2,84 | −1,49 | 60,36 % | +5,91 | 1 683 |
| X = 5 € | −0,0957 | 2,91 | −1,49 | 59,34 % | +11,62 | 2 048 |
| X = 10 € | −0,0943 | 2,99 | −1,49 | 58,98 % | +18,78 | 2 180 |
| X = 20 € | −0,0918 | 3,07 | −1,49 | 58,92 % | +23,71 | 2 252 |
| **X = aucun objectif** | **−0,0837** | 3,24 | −1,49 | 58,89 % | **+75,02** | 2 271 |
| **REF traînage 0,50 €** | **+0,0467** | 2,73 | **−0,97** | **71,22 %** | +14,24 | — |
| **REF traînage +0,10 €/min** | **+0,0819** | 2,89 | −1,07 | 63,35 % | +21,94 | — |

    chaque X contre la meilleure reference : ecart -0,18 a -0,21 EUR/jour,
    t de **-3,58 a -6,54**, signe STABLE dans les onze cas
    ⇒ **0 X sur 11** franchit la barre de 3,0

## ⇒ LA RÉPONSE : X N'EXISTE PAS

Le meilleur X du balayage est **« aucun objectif »** — et **même lui perd** de
−0,2064 €/jour (`t = −4,71`) contre le traînage à 0,50 €.

🔑 **Et la cause n'est pas X : c'est le stop à 2 € du cours.** Il rend **2 €**
à chaque repli au lieu de 0,50 €. Le prix s'en voit dans deux colonnes :
réussite **58,9 % contre 71,2 %**, et pire journée **−1,49 € contre −0,97 €**.
Les 2 271 resserrages ne compensent pas ce qu'ils laissent sur la table.

## ✅ SON INTUITION SUR LA QUEUE EST, ELLE, PARFAITEMENT JUSTE

    X = 1 €   plus gros gain  +4,07
    X = 5 €                  +11,62
    X = 20 €                 +23,71
    aucun objectif           **+75,02**

Monotone, sans exception. **Plus l'objectif est loin, plus la queue droite est
grosse** — exactement ce qu'il décrit. Ce qui ne suit pas, c'est l'espérance.

## ✅ MES QUATRE PRÉDICTIONS SONT JUSTES, pour la première fois de la journée

1. ✅ le meilleur X est « aucun objectif » ;
2. ✅ **0 X sur 11** franchit la barre ;
3. ✅ le stop à 2 € du cours fait **pire** que le traînage à 0,50 € — et c'est
   l'effet **dominant** ;
4. ✅ le plus gros gain grandit avec X.

## ⚠️ ET UNE CORRECTION À MES CHIFFRES PRÉCÉDENTS

Les références valent ici **+0,0467** et **+0,0819 €/trade**, contre **+0,0137**
et **+0,0454** dans les bancs précédents. L'écart vient de l'artefact que
j'avais signalé : là, l'objectif à 2 € n'est **jamais** posé, alors qu'avant il
restait en place la première minute et plafonnait 602 trades.

⇒ **La vraie valeur du traînage élargi est +0,0819 €/trade**, pas +0,0454. Mes
chiffres d'avant étaient **pessimistes d'un facteur ~1,8**, et c'est dans le bon
sens pour la prudence — mais il faut le dire.
