# La STAGNATION en positif : donner de la corde quand le cours piétine

**Déclaré le 2026-10-11, AVANT de mesurer.** Xavier : « si le cours de l'or est
en train de stagner entre deux bornes, est-ce que nous ne pourrions pas
augmenter le TP pour absorber un mouvement haussier ? Ce cas de figure n'arrive
qu'en positif. Pour un cours négatif, on respecte ce qu'on a mis en place. »

## ⓘ CE QUE J'AVAIS MESURÉ, ET EN QUOI CE N'EST PAS ÇA

Mes variantes `Z2` et `Z3` élargissaient le traînage avec le **nombre de
minutes passées en positif**. Cela **confond deux situations** :

- un trade qui **monte régulièrement** pendant 20 minutes ;
- un trade qui **piétine** 20 minutes dans une bande étroite.

Sa question porte sur le **second** uniquement. Je ne l'avais donc pas mesuré,
et je le dis plutôt que de faire passer `Z2` pour une réponse.

## La stagnation, définie avant de mesurer

À chaque minute, sur les **10 dernières clôtures** :

    stagnation  ⟺  (plus haute cloture − plus basse cloture) ≤ **0,50 €**
                   ET le trade est en POSITIF

Le compteur est le **nombre de minutes consécutives** où c'est vrai. Côté
négatif, rien ne change : départ −9 €, point milieu, plancher −2 €.

## Les stratégies, sur les MÊMES trades

Base commune : départ **−9 €**, plancher **−2 €**, traînage **continu** à
0,50 € dès 0,50 € de profit, **aucun objectif**. 6 668 entrées aveugles,
99 999 bougies M1 du courtier.

| | ce qui s'élargit, et quand |
|---|---|
| **S0** référence | rien — traînage 0,50 € fixe |
| **S1** sa demande | traînage **+0,10 €/min de STAGNATION**, plafond 2 € |
| **S2** sa demande, large | traînage **+0,20 €/min de STAGNATION**, plafond 4 € |
| **S3** objectif sous stagnation | **objectif** `2 € + 1 €/min de stagnation`, traînage fixe |
| **S4** témoin INVERSE | traînage +0,10 €/min de **VOLATILITÉ** en positif (plage > 1,50 €) |
| **Z2** l'ancienne meilleure | traînage +0,10 €/min **en positif**, sans condition |

🔑 **`S4` est le contrôle qui décide**. Si élargir sous **volatilité** marche
aussi bien que sous **stagnation**, alors ce n'est pas la stagnation qui
compte : c'est le fait d'élargir, point. Sans ce témoin, je prendrais une
propriété du traînage pour une propriété du marché.

## ⛔ LE CRITÈRE

Retenue si l'écart par **JOUR** a un **|t| > 2,5** avec le signe **stable sur
les deux moitiés**, contre **S0** *et* contre **Z2** — il ne suffit pas de
battre le traînage fixe, il faut apporter quelque chose de plus que le simple
temps passé en positif.

## MA PRÉDICTION, POSÉE MAINTENANT

1. ⛔ **S1 ne battra pas Z2** : la stagnation et le temps en positif sont
   fortement corrélés (un trade qui piétine accumule des minutes positives),
   donc je prédis |t| < 2,5 entre les deux.
2. ⚠️ **S4, le témoin inverse, fera presque aussi bien que S1** — et c'est ce
   qui montrerait que l'effet est dans l'élargissement, pas dans la condition.
3. ⛔ **S3 (objectif) sera de nouveau le pire** : un objectif plafonne, c'est
   déjà établi aujourd'hui à `t = −3,12`.
4. ✅ Et je prédis que **le plus gros gain augmentera** avec S1 et S2, comme il
   l'a fait avec Z2 et Z3.

⇒ Si S1 bat **à la fois** S0 et Z2, sa notion de stagnation apporte quelque
chose que le temps seul n'apporte pas, et c'est la première fois qu'une
**condition de marché** gagne sur ce projet.
