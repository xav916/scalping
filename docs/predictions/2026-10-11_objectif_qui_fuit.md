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


---

# VERDICT — 2026-10-11

`scripts/banc_objectif_qui_fuit.py`. 6 668 trades aveugles, 99 999 bougies M1
du courtier, six strategies en parallele.

| | EUR/trade | ecart-type | pire jour | reussite | duree | gain moyen | **plus gros gain** |
|---|---|---|---|---|---|---|---|
| **Y** sa nouvelle regle (2p+1) | −0,0334 | 2,53 | −1,30 | 55,74 % | 6,0 min | +1,642 | **+11,46** |
| **Y0** AUCUN objectif | **+0,0014** | 2,62 | **−0,99** | 55,49 % | 6,2 min | +1,713 | **+13,46** |
| **Y2** objectif p+1 (lent) | −0,0715 | 2,45 | −1,43 | 55,74 % | 5,7 min | +1,574 | +3,46 |
| **X+** sa regle precedente | −0,0227 | 2,54 | −1,30 | 55,58 % | 6,0 min | +1,667 | +7,46 |
| **A2** production + protection | −0,0247 | 2,99 | −2,15 | 72,89 % | 8,5 min | +1,616 | +3,96 |
| **B2** stop −2 sec | −0,0714 | 2,00 | **−0,12** | 49,75 % | 5,3 min | +1,938 | +1,96 |

## ⛔ MA PREDICTION 1 EST FAUSSE, et la raison est instructive

J'annonçais **zero sortie par objectif** pour sa regle. Mesure : **1 948**.

🔑 Pourquoi : l'objectif ne part a 3 € qu'une fois qu'une **cloture** a
enregistre 1 € de profit. Une bougie rapide peut franchir les 2 € **avant**
qu'aucune cloture ne soit tombee dans la bande [1 ; 1,5[. L'objectif initial a
2 € reste donc atteignable — il ne devient inatteignable qu'**apres** le
premier palier. Mon « jamais » etait trop fort.

⇒ L'effet reel de son objectif fuyant : il **retire 616 sorties par objectif**
(2 564 pour Y2, 1 948 pour Y) et les convertit en sorties par stop suiveur.

## ✅ ET SON INTUITION EST JUSTE, de facon MONOTONE et SIGNIFICATIVE

    objectif p+1 (monte lentement)      **-0,0715 EUR/trade**   max +3,46
    objectif palier+2 (la production)    -0,0227               max +7,46
    objectif 2p+1 (le sien)              -0,0334               max **+11,46**
    AUCUN objectif                      **+0,0014**            max **+13,46**

    sa regle contre l'objectif LENT (p+1)   +0,0427 EUR/jour   **t +6,43  ***
    sa regle contre AUCUN objectif          -0,0311            **t -2,72  ***
    sa regle contre X+ (palier+2)           -0,0111             t -2,25 (sous la barre)

🔑 **Plus on laisse l'objectif s'eloigner, mieux c'est** — et le bout du
raisonnement est de **le supprimer**. `Y0` est la **seule strategie de toute la
journee dont l'esperance soit positive** : **+0,0014 EUR/trade**.

⚠️ Et il faut le dire tout de suite : **+0,0014 €/trade est zero**. Ce n'est pas
un avantage, c'est l'**absence de cout** — la premiere fois qu'une geometrie de
ce projet ne perd pas. La difference avec sa regle, elle, est **etablie**
(t −2,72, signe stable sur les deux moities).

## Son autre intuition, verifiee : le stop finit POSITIF souvent

    sorties par stop SUIVEUR (stop au-dessus de l'entree)  1 769 (Y) / 2 447 (Y0)
    sorties au POINT MORT (stop a l'entree)                1 261 / 1 278
    ⇒ **environ 45 % des trades sortent a zero ou mieux par le stop**

## MES QUATRE PREDICTIONS

1. ⛔ « zero sortie par objectif » : **FAUSSE** (1 948), raison ci-dessus.
2. ⚠️ « Y moins bon que X+ » : juste de sens (−0,0334 contre −0,0227) mais
   **t −2,25, sous la barre de 2,5** ⇒ **non etabli**.
3. ✅ « son plus gros gain sera nettement superieur » : **JUSTE** — +11,46 €
   contre +7,46 pour X+ et +1,96 pour un stop sec.
4. ⛔ « duree nettement plus longue » : **FAUSSE** — 6,0 min contre 6,0 min
   pour X+, et **une seule** sortie par le plafond de 24 h.

## ⇒ CE QUE JE RECOMMANDE, mesure en main

**Supprimer l'objectif**, et garder tout le reste de sa regle : depart −9 €,
point milieu cote perte avec plancher −2 €, et le stop suiveur a 0,50 € derriere
le profit a partir de 0,50 €. C'est la meilleure des six, la seule non
negative, et elle bat sa version a objectif fuyant de facon etablie.

⚠️ La limite de toujours : duree 6 min contre 28,9 pour la production ⇒ **5 fois
plus de rotation**, donc 5 fois plus de spread **si on recycle la place**. Ce
banc ne le lui fait pas payer.
