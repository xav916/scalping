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
