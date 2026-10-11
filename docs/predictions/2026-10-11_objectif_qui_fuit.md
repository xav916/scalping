# L'objectif qui FUIT : TP 3 € à 1 € de profit, 4 € à 1,50 €, 5 € à 2 €…

**Déclaré le 2026-10-11, AVANT de mesurer.** Ajout de Xavier à sa règle :
« dès qu'on atteint 1 euro, le SL passe à 0,5 et le TP passe à 3 euros ; dès
1,50 le TP passe à 4 ; dès 2 euros le TP passe à 5, etc. Donc on pourrait avoir
une sortie en TP supérieure à 2 euros, avec le SL positif : quelque chose de
positif avec des gains supplémentaires. »

## Sa règle, mise en formule

    profit ≥ 0,50 €  →  SL 0        TP 2 € (inchangé)
    profit ≥ 1,00 €  →  SL 0,50     TP **3 €**
    profit ≥ 1,50 €  →  SL 1,00     TP **4 €**
    profit ≥ 2,00 €  →  SL 1,50     TP **5 €**
    …et ainsi de suite : **SL = profit − 0,50**, **TP = 2 × profit + 1**

Départ inchangé : SL **−9 €**, plancher de resserrage **−2 €**, point milieu
côté perte.

## ⛔ LA CONSÉQUENCE MÉCANIQUE, à dire AVANT de mesurer

**Son objectif ne peut jamais être atteint.** À 1 € de profit l'objectif est à
3 € — donc 2 € plus loin. À 2 € de profit il est à 5 € — donc 3 € plus loin.
**L'écart entre le prix et l'objectif GRANDIT à chaque palier** :

    profit 1,0  ->  objectif 3,0  ->  il reste **2,0 €** a parcourir
    profit 2,0  ->  objectif 5,0  ->  il reste **3,0 €**
    profit 3,0  ->  objectif 7,0  ->  il reste **4,0 €**

⇒ Le prix ne rattrape jamais la cible. **Sa règle est donc, en pratique, un
stop suiveur à 0,50 € SANS objectif** : la sortie se fera toujours par le stop
qui remonte, jamais par le TP.

🔑 Ce n'est pas une objection à sa logique — c'est ce que sa logique **est**
réellement, et il vaut mieux le mesurer sous son vrai nom. Je mesure donc aussi
une variante où l'objectif monte **moins vite que le profit**, donc reste
atteignable.

## Les stratégies comparées, sur les MÊMES trades

6 668 entrées aveugles, 99 999 bougies M1 du courtier, palier armé sur la
clôture, plafond de durée 24 h puis sortie au prix.

| | SL départ | échelle du SL | objectif |
|---|---|---|---|
| **Y** sa nouvelle règle | −9 € | profit − 0,50 | **2 × profit + 1** (fuyant) |
| **Y0** la même, SANS objectif | −9 € | profit − 0,50 | aucun |
| **Y2** objectif ATTEIGNABLE | −9 € | profit − 0,50 | **profit + 1** |
| **X+** sa règle précédente | −9 € | profit − 0,50 | **palier + 2 €** |
| **A2** production + protection | −20 € | 1:0,75 … 2:1,75 | palier + 2 € |
| **B2** stop −2 sec | −2 € | aucune | 2 € fixe |

Je publie : P&L par trade, écart-type, pire journée, taux de réussite, durée,
**gain moyen des gagnants**, **le plus gros gain**, et le compte des sorties
par objectif.

## ⛔ LE CRITÈRE

Retenue si P&L par trade supérieur avec **|t| > 2,5** sur l'écart par **JOUR**
et **signe stable sur les deux moitiés**.

## MA PRÉDICTION, POSÉE MAINTENANT

1. ✅ **Y et Y0 donneront EXACTEMENT le même résultat**, et le compte de
   sorties par objectif de Y sera **zéro**. C'est la vérification mécanique de
   ce qui précède.
2. ⛔ **Y ne battra pas X+** : je prédis Y **moins bon**, parce que chaque
   gagnant rend les 0,50 € du traînage au lieu d'encaisser une cible, et que
   l'espérance, elle, ne bouge pas (arrêt optionnel).
3. ✅ En revanche je prédis que **le plus gros gain de Y sera bien supérieur**
   à celui de X+ — son intuition sur les « gains supplémentaires » est juste
   sur la **queue droite**, et c'est là qu'il faut regarder.
4. ⚠️ Et je prédis une **durée nettement plus longue** et donc plus de sorties
   par le plafond de 24 h.

⇒ Si Y bat X+ avec |t| > 2,5, j'ai tort et laisser courir paie enfin sur cette
géométrie — alors que « laisser courir » a déjà été réfuté le 10/10 sur la
géométrie 2/20 (A−B = −0,27 €, t = −7,04).
