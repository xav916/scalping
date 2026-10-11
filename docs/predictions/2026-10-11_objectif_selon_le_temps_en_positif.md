# L'objectif qui monte avec le TEMPS passé en positif

**Déclaré le 2026-10-11, AVANT de mesurer.** Xavier : « en fonction du temps
qu'on a en positif, pouvoir mettre un take profit encore plus loin… au lieu de
s'arrêter à 5 euros on pourrait sortir à 20 euros, parce qu'on aurait eu un
mouvement haussier positif. Et si c'est l'inverse, le stop loss coupe en
positif aussi. »

## ⛔ L'ARITHMÉTIQUE D'ABORD, parce qu'elle borne la réponse

Avec un **stop suiveur** qui traîne de `w` derrière le profit, la sortie vaut
`max_atteint − w` dès qu'il y a un repli. Ajouter un objectif à `V` change
l'issue dans **deux cas seulement** :

    max_atteint < V            l'objectif ne sert a rien
    max_atteint = V pile       l'objectif gagne **+w** (sortie a V, pas a V−w)
    max_atteint > V            l'objectif **PERD** max_atteint − V

🔑 **Un objectif ne peut donc jamais battre un stop suiveur de plus que la
largeur du traînage — 0,50 € — et il peut perdre autant que le mouvement
dépasse la cible.** Pousser l'objectif de plus en plus loin, c'est converger
vers **l'absence d'objectif**, qui est précisément la géométrie que je viens de
mesurer comme la meilleure (+0,0014 €/trade, `c0ebe2b`).

⇒ Sa demande littérale est donc bornée d'avance. **Mais son intuition contient
autre chose**, et c'est cette autre chose qui peut gagner : ce n'est pas
l'objectif qui doit s'éloigner avec le temps, c'est le **TRAÎNAGE qui doit
s'élargir**. Un trade installé en positif depuis dix minutes mérite plus de
corde pour absorber un mouvement brusque ; un trade qui vient de passer
positif, non.

## Les stratégies comparées, sur les MÊMES trades

Base commune, celle retenue au verdict précédent : départ SL **−9 €**, point
milieu côté perte avec plancher **−2 €**, stop suiveur à **0,50 €** derrière le
profit à partir de 0,50 €. 6 668 entrées aveugles, 99 999 bougies M1 du
courtier.

| | objectif | traînage |
|---|---|---|
| **Z0** référence (le gagnant d'avant) | aucun | 0,50 € fixe |
| **Z1** sa demande littérale | **2 € + 1 € par minute en positif** | 0,50 € fixe |
| **Z2** traînage qui s'élargit | aucun | **0,50 € + 0,10 €/min en positif**, plafond 2 € |
| **Z3** traînage qui double | aucun | **0,50 € × 2^(min/5)**, plafond 4 € |
| **Z4** traînage qui se resserre (témoin) | aucun | 0,50 € − 0,02 €/min, plancher 0,10 € |
| **A2** la production + protection | palier + 2 € | échelle 1:0,75… |

Le « temps en positif » est le **nombre cumulé de minutes dont la clôture est
au-dessus de l'entrée**.

## ⛔ LE CRITÈRE

Retenue si l'écart par **JOUR** contre **Z0** a un **|t| > 2,5** avec le signe
**stable sur les deux moitiés**. 5 comparaisons.

## MA PRÉDICTION, POSÉE MAINTENANT

1. ⛔ **Z1 sera indistinguable de Z0** : une fois l'objectif à 10 ou 20 €, il ne
   mord presque jamais, et quand il mord il **plafonne**. Je prédis |t| < 2,5.
2. ⛔ **Z2 et Z3 ne battront pas Z0 non plus** : élargir le traînage ne change
   pas l'espérance d'une marche. Je prédis |t| < 2,5 dans les deux cas.
3. ✅ Mais je prédis que **le plus gros gain augmentera nettement** avec Z2 et
   Z3 (au-delà des +13,46 € de Z0), et que **la variance augmentera** avec lui.
4. ✅ Et je prédis **Z4 (traînage resserré) nettement PIRE**, avec un |t| qui,
   lui, dépassera 2,5 — parce que resserrer coupe les gagnants, et c'est le
   seul effet que la mesure a déjà montré solide aujourd'hui (couper les
   négatifs tôt nuit, 82-86 % des négatifs finissaient au TP).

⇒ Si Z2 ou Z3 franchit le critère, son intuition sur le temps est payante et
c'est la première fois qu'un réglage de sortie gagne vraiment sur ce projet.


---

# VERDICT — 2026-10-11

`scripts/banc_trainage_selon_le_temps.py`. 6 668 trades aveugles, 99 999
bougies M1 du courtier, six strategies en parallele.

| | EUR/trade | ecart-type | pire jour | reussite | duree | gain moyen | **max** |
|---|---|---|---|---|---|---|---|
| **Z0** reference (trainage 0,50 fixe, aucun objectif) | +0,0139 | 2,63 | −0,97 | 71,48 % | 6,0 min | +1,342 | +14,24 |
| **Z1** sa demande litterale (TP selon le temps) | **−0,0215** | 2,53 | −1,29 | 71,57 % | 5,8 min | +1,287 | +8,96 |
| **Z2** trainage **+0,10 €/min**, plafond 2 € | **+0,0455** | 2,78 | −1,07 | 63,71 % | 6,8 min | +1,577 | **+21,94** |
| **Z3** trainage qui **double** tous les 5 min | **+0,0443** | 2,83 | −1,06 | 65,00 % | 7,1 min | +1,542 | **+27,69** |
| **Z4** trainage qui se resserre (temoin) | +0,0160 | 2,62 | −1,02 | 72,78 % | 5,9 min | +1,320 | +14,28 |
| **A2** la production actuelle | −0,0238 | 2,99 | −2,15 | 72,89 % | 8,5 min | +1,616 | +3,96 |

    contre Z0 :  Z1  **-0,0414 EUR/jour   t -3,12  ***  signe stable**
                 Z2  **+0,0404            t +2,30**      signe stable
                 Z3   +0,0560             t +1,61        signe stable
                 Z4   +0,0049             t +1,69        signe INVERSE
                 A2  -0,0614              t -1,57        signe stable

## ⛔ SA DEMANDE LITTÉRALE EST RÉFUTÉE, et significativement

Ajouter un objectif qui s'éloigne avec le temps **coûte −0,0414 €/jour contre
pas d'objectif du tout**, `t = −3,12`, signe stable. Et le mécanisme est
exactement celui annoncé avant la mesure : **l'objectif PLAFONNE**. Son plus
gros gain tombe de **+14,24 € à +8,96 €**.

⚠️ Ma prédiction 1 disait « indistinguable » : elle est **fausse dans le bon
sens pour l'argument mais fausse quand même** — c'est franchement pire, pas
équivalent.

## ✅ MAIS SON INTUITION DE FOND EST LA MEILLEURE CHOSE MESURÉE DE LA JOURNÉE

Élargir le **traînage** avec le temps passé en positif, au lieu d'éloigner
l'objectif :

    Z2 (+0,10 EUR/min, plafond 2 EUR)   **+0,0455 EUR/trade**   max **+21,94 EUR**
    Z3 (qui double tous les 5 min)       +0,0443               max **+27,69 EUR**
    Z0 (trainage fixe)                   +0,0139               max  +14,24

🔑 C'est le **meilleur EUR/trade de tous les bancs du jour**, et le raisonnement
qu'il décrivait — « absorber un mouvement brusque haussier » — est
**exactement** ce que fait ce réglage : le plus gros gain passe de 14 € à 22 €
(Z2) et 28 € (Z3).

⛔ **MAIS ÇA NE FRANCHIT PAS MA BARRE.** `t = +2,30` contre le seuil
pré-inscrit de **2,50**. C'est **encourageant, pas établi**. Je ne l'arme pas
sur un `t` de 2,3 après une journée où j'ai vu un `t` de −4,56 s'évaporer et un
`t` de +4,63 se faire démentir par 3,5 mois de données.

## ✅ ET UN GAIN GRATUIT, trouvé en passant

Z0 ici fait **+0,0139 €/trade** contre **+0,0014** pour la même idée en
escalier de 0,50 € (banc précédent). ⇒ **Un traînage CONTINU (stop = profit −
0,50 à chaque minute) bat un traînage par paliers**, pour zéro complexité en
plus.

## MES QUATRE PRÉDICTIONS

1. ⛔ « Z1 indistinguable de Z0 » : **fausse** — significativement pire
   (t −3,12).
2. ✅ « Z2 et Z3 ne battront pas Z0 au critère » : **juste**, mais de justesse
   pour Z2 (2,30 contre 2,50).
3. ✅ « le plus gros gain augmentera nettement » : **juste** (+21,94 et +27,69
   contre +14,24).
4. ⛔ « Z4 nettement pire, |t| > 2,5 » : **fausse** — +0,0049, t +1,69, signe
   inversé : indistinguable.

## ⚠️ UNE LIMITE DU BANC, à dire

Les 602 sorties « OBJECTIF » de Z0, Z2, Z3 viennent de l'objectif initial à 2 €
qui reste en place pendant la **première minute** avant d'être retiré. Un ordre
réellement sans objectif les aurait laissées courir. Cela rend Z0/Z2/Z3
**légèrement pessimistes** — donc du bon côté.
