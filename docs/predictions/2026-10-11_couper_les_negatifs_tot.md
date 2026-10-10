# Fermer tôt les trades déjà négatifs : ça aide ou ça coûte ?

**Déclaré le 2026-10-11, AVANT de mesurer.** Demande de Xavier : « et si on
ferme tous les trades négatifs au démarrage ? »

## ⚠️ LA PRÉCISION QUI CHANGE LA QUESTION

**Au démarrage exact, TOUS les trades sont négatifs** — du montant du spread
(0,045 €). Prise au mot, la règle revient à ne jamais trader.

⇒ Je résous donc l'ambiguïté en mesurant **le délai** au lieu de le supposer :
la règle devient « si le trade est négatif à la minute **k**, on le ferme »,
pour **k = 1, 2, 3, 5 et 10 minutes**.

## Ce que cette question n'est PAS

⛔ Ce n'est **pas** le test de la « négativité persistante » du 2026-10-10,
qui mesurait si la **proportion de temps** passée en négatif sur 10 minutes
prédisait l'issue (réfuté : t = +1,34, 12 jours positifs sur 25).

🔑 Ici c'est **conditionnel à un instant précis** : sachant que le trade est
négatif à la minute k, que fait-il **ensuite** ? C'est une question neuve.

## L'argument arithmétique, posé d'avance

Le théorème d'arrêt optionnel dit qu'**aucune règle d'arrêt appliquée à une
martingale ne change son espérance**. Couper tôt ne peut donc pas créer de
gain. Mais la règle change **deux choses qui comptent** :

1. ✅ elle **borne la queue des pertes** — et c'est précisément ce que le stop
   à 20 € ne fait pas : 66 trades au stop = **−436,72 €** sur 30 jours ;
2. ⛔ elle **libère le capital plus vite** ⇒ plus de trades ⇒ **plus de spread
   payé**.

⇒ Attendu : neutre sur l'espérance, **meilleure** sur la variance, **pire** sur
le coût. Et ce que la mesure doit trancher, c'est **l'ampleur** de chacun.

## Ce que je mesure

Entrées **aveugles et systématiques** (une toutes les 30 minutes, dans les deux
sens) sur les **98 629 bougies M1 du courtier**, juillet → octobre 2026, bornes
de production **TP 2 € / SL 20 €**.

Pour chaque k, je sépare les trades en **négatif à k** / **positif à k**, puis
je compare, appariés sur les mêmes trades :

- **TENIR** : laisser courir jusqu'à une borne ;
- **COUPER** : fermer à la minute k si négatif, tenir sinon.

Et je publie le chiffre qui décide vraiment : parmi les trades **négatifs à
k**, **quelle part finit quand même à l'objectif** ? C'est elle qui dit si
couper jette des gagnants.

## ⛔ LE CRITÈRE, POSÉ AVANT DE REGARDER

La règle est retenue si, pour au moins un k, elle réunit **les quatre** :

1. P&L de **COUPER** > P&L de **TENIR**, sur les mêmes trades ;
2. **|t| > 2,241** — le plafond du laboratoire pour ~24 cellules
   (5 délais × 2 panneaux × 2 sens), l'unité étant **le JOUR** ;
3. **n ≥ 1 000** trades ;
4. le signe de l'écart **stable sur les deux moitiés** de la période.

## MA PRÉDICTION, POSÉE MAINTENANT

1. ⚠️ Être négatif à la minute k **prédira** l'issue — mais **mécaniquement**,
   parce qu'on est plus près du stop, pas parce que l'information existe.
2. ⛔ Et **couper ne battra pas tenir** : **0 délai retenu sur 5**. Motif :
   l'arrêt optionnel, plus le spread payé sur les trades recyclés.
3. ✅ En revanche je prédis que **la variance baissera nettement** et que la
   **pire journée s'améliorera** — c'est le seul effet réel attendu.

⇒ Si couper bat tenir avec les quatre critères, ma prédiction est réfutée.

## Ce que cette mesure ne tranche PAS

- Rien sur une coupure déclenchée par autre chose que le **signe** (un seuil
  en euros, une durée, un motif).
- Rien sur le **réemploi** du capital libéré : je ne simule pas les trades
  supplémentaires que la coupure permettrait. ⚠️ Et cela joue **en faveur** de
  la coupure dans mon tableau, puisque je ne lui fais pas payer le spread des
  trades qu'elle rendrait possibles.
