# PISTE 3 — Le prix de l'assurance : couper sur un SEUIL, pas sur le signe

**Déclaré le 2026-10-11, AVANT de mesurer.**

## Ce qui est déjà su, et ce qui manque

Couper les trades négatifs **sur le signe** a été mesuré le même jour : ça
**nuit** (0 délai retenu sur 5 ; 82-86 % des négatifs finissent quand même à
l'objectif), mais ça **divise la variance par 2** (écart-type 7,21 → 3,60) et
améliore la pire journée (−3,99 → −1,67 $), pour **0,32 $/trade à k=5**.

⛔ Et la pré-inscription de ce test excluait explicitement « une coupure
déclenchée par autre chose que le signe ». C'est donc ce qui manque, et c'est
ce qu'un humain ferait réellement : **couper à −2 €, −5 €, −10 €**.

## Ce que je mesure

Mêmes **6 666 trades aveugles**, magasin M1 du courtier (99 999 bougies,
2026-07-01 → 2026-10-09), bornes de production **TP 2 € / SL 20 €**.

Pour chaque seuil **S ∈ {−1, −2, −5, −10 €}** : fermer dès que la perte
courante atteint S (au premier passage, sur les bougies M1), sinon tenir.

Je publie, pour chaque S : le **coût par trade** contre TENIR, l'**écart-type**,
la **pire journée**, la **part des trades coupés** et la **part de ceux-là qui
auraient atteint l'objectif**.

## ⛔ CE QUE CE BANC NE FAIT PAS

Il ne **retient** rien : ce n'est pas une règle à valider, c'est un **prix à
afficher**. La décision est celle de Xavier, pas la mienne — et un banc qui
prétendrait « retenir » une assurance confondrait rendement et tranquillité.

## MA PRÉDICTION, POSÉE MAINTENANT

1. ⚠️ Le coût **croît** quand le seuil se resserre : −1 € coûtera plus que
   −10 €.
2. ✅ L'écart-type et la pire journée **s'améliorent de façon monotone** quand
   le seuil se resserre.
3. 🔑 Et je prédis que couper à **−10 €** coûtera **moins** que couper sur le
   signe à k=5 (0,32 $/trade), parce qu'un seuil large laisse respirer les
   trades que le bruit rend momentanément négatifs.
