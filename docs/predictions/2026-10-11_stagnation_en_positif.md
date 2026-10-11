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


---

# VERDICT — 2026-10-11

`scripts/banc_stagnation_en_positif.py`. 6 668 trades aveugles, 99 999 bougies
M1 du courtier.

## ⛔ MON PREMIER PASSAGE NE MESURAIT RIEN — seuil jamais atteint

Mon seuil de stagnation a **0,50 €** sur 10 minutes ne qualifiait que
**0,021 %** des fenêtres. `S1` et `S2` rendaient un resultat **identique a S0
au centieme pres** — c'est cette identite qui a trahi le defaut, pas une
relecture.

Distribution mesuree, 14 285 fenetres de 10 min :

    centile 10 : **1,741 €**    centile 20 : **2,268 €**    MEDIANE : **3,688 €**
    centile 75 : 5,447          centile 90 : 7,823
    part sous 0,50 € : **0,021 %**   sous 1,00 € : 1,34 %   sous 1,50 € : 6,31 %

⇒ Seuils repris **dans la distribution** : stagnation = 1er quintile
(**2,268 €**), volatilite = dernier quartile (**5,447 €**). Choisis sur la
distribution, **jamais sur le resultat**.

## LE TABLEAU, seuils corriges

| | EUR/trade | ecart-type | pire jour | reussite | **max** |
|---|---|---|---|---|---|
| **S0** reference (traînage 0,50 fixe) | +0,0137 | 2,63 | −0,97 | 71,48 % | +14,24 |
| **S1** stagnation +0,10 €/min | +0,0150 | 2,63 | −0,97 | 71,15 % | +14,24 |
| **S2** stagnation +0,20 €/min | +0,0140 | 2,63 | −0,97 | 71,01 % | +14,24 |
| **S3** objectif sous stagnation | **−0,0845** | 2,41 | −1,42 | 71,69 % | +4,92 |
| **S4** TEMOIN volatilite | +0,0136 | 2,63 | −0,97 | 71,48 % | +14,24 |
| **Z2** temps en positif, sans condition | **+0,0454** | 2,78 | −1,07 | 63,71 % | **+21,94** |

    contre S0 :  S1 +0,0009  t +0,71  signe INVERSE
                 S2 -0,0001  t -0,04  signe INVERSE
                 S4 -0,0003  t -0,45  signe INVERSE
                 S3 **-0,1015  t -6,85  ***
                 Z2 +0,0404   t +2,30  stable

    contre Z2 :  S1 -0,0394  t -2,26  ·  S2 -0,0404  t -2,31  ·  S4 -0,0406  t -2,32

## ⇒ LA STAGNATION N'APPORTE RIEN, ET LE TEMOIN LE PROUVE

`S1` (stagnation), `S4` (volatilite — la condition **inverse**) et `S0` (aucune
condition) sont **indistinguables a 0,001 €/trade pres**. 🔑 **Ce n'est donc ni
la stagnation ni la volatilite : la condition de marche ne compte pas.**

Et ce qui porte l'effet, c'est `Z2` : le **temps cumule passe en positif**, sans
aucune condition. Pourquoi : son compteur **ne se remet jamais a zero**, donc
le traînage s'elargit **durablement**. La stagnation, elle, est rare ET courte —
le compteur retombe a zero des qu'elle casse, et l'elargissement n'atteint
jamais une valeur utile. C'est ce que montre la colonne `max`, restee a
**+14,24** pour S1/S2 contre **+21,94** pour Z2.

## MES QUATRE PREDICTIONS

1. ✅ « S1 ne battra pas Z2 » : **juste** (t −2,26).
2. ✅ « S4 fera presque aussi bien que S1 » : **juste, et plus fort que prevu** —
   ils sont identiques, donc la condition est **inerte**.
3. ✅ « S3 (objectif) sera le pire » : **juste** (−0,0845, t −6,85).
4. ⛔ « le plus gros gain augmentera avec S1 et S2 » : **faux** — +14,24,
   identique a S0, parce que l'elargissement n'atteint jamais de valeur utile.

## ⇒ CE QUI RESTE DEBOUT

**Un seul reglage** : traînage **continu** a 0,50 €, **aucun objectif**,
elargi **+0,10 €/min passee en positif** (plafond 2 €), **sans condition de
marche**. `+0,0454 €/trade`, `t = +2,30` contre le traînage fixe.
⛔ Toujours **sous ma barre de 2,50** : encourageant, pas etabli.
