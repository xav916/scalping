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

---

# VERDICT — 2026-10-11

`scripts/banc_couper_les_negatifs.py`. Magasin M1 **du courtier** rebâti en un
seul passage : **99 999 bougies, 2026-07-01 → 2026-10-09 20h55** (cette
dernière étant la clôture réelle du vendredi). 3 333 entrées aveugles toutes
les 30 minutes, **deux sens** ⇒ **6 666 trades**, bornes TP 2 € / SL 20 €.

ⓘ Ancres d'exécution : 149/171 (87,1 %), le reste à ±1 minute — résidu de la
dérive du champ de décalage entre les 21 pages. Mesure **à la minute**, dit.

## ⇒ 0 DÉLAI RETENU SUR 5. Mes prédictions 2 et 3 tiennent toutes les deux.

    k      n neg   part    TENIR $    COUPER $     ecart       t    neg -> TP
    1       3510   52,7%   -0,1655    -0,1207    -0,0438   -0,41      86,5 %
    2       3464   52,0%   -0,1655    -0,2184    -0,0746   -0,68      85,3 %
    3       3431   51,5%   -0,1655    -0,3083    -0,1998   -1,88      84,6 %
    5       3414   51,2%   -0,1655    -0,4113    **-0,3165  -2,96**   83,4 %
    10      3387   50,8%   -0,1655    -0,7303    **-0,6691  -6,03**   82,2 %

🔑 **LE CHIFFRE QUI DÉCIDE EST LA DERNIÈRE COLONNE.** Parmi les trades négatifs
à la minute k, **82 à 86 % atteignent QUAND MÊME l'objectif**. Couper jette
donc environ **cinq gagnants sur six**.

⇒ Et à k=5 et k=10, la dégradation est elle-même **significative** — |t| au-delà
du plafond pré-inscrit de 2,241, mais **dans le mauvais sens**. Ce n'est pas
« couper n'aide pas » : c'est **couper nuit, et de plus en plus tard on coupe**.

## ✅ CE QUE COUPER ACHÈTE RÉELLEMENT (prédiction 3, confirmée)

    ecart-type par trade   TENIR 7,2132  ->  COUPER 3,60 a 3,97   (÷ ~2)
    pire journee           TENIR -3,9918 ->  COUPER -1,14 a -1,72

⇒ La règle **divise la variance par deux** et **améliore nettement la pire
journée**. C'est une règle d'**assurance**, pas de rendement : elle coûte
0,32 $ par trade à k=5 pour acheter cette tranquillité.

## ⛔ ET ELLE TUE LA LECTURE DE VENDREDI

Vendredi 09/10, sur 75 trades réels, j'ai mesuré « négatif à +5 min ⇒ **40 %**
finissent au stop ». Sur 3,5 mois et 3 414 cas, le taux réel est
**16,6 %** (100 − 83,4). ⇒ **Vendredi était 2,4 fois pire que la normale.**

🔑 Un seul jour, et un jour dont **42 clôtures sur 75 étaient de la main de
Xavier**, ne généralise pas. C'est exactement ce que ce test pré-inscrit
existait pour trancher, et il tranche **contre** la lecture de vendredi.

## ⚠️ UNE INCOHÉRENCE APPARENTE, dite plutôt que lissée

À **k=1**, la moyenne globale dit couper légèrement MEILLEUR (−0,1207 contre
−0,1655) alors que l'écart par **JOUR** — l'unité pré-inscrite — dit
−0,0438. Les deux ne peuvent pas être égaux : la moyenne par jour pèse chaque
journée pareil, la moyenne globale pèse chaque trade pareil. Avec `t = −0,41`,
k=1 est de toute façon du **bruit** dans les deux lectures.

## Le témoin de fond

    TENIR seul : 6 029 TP, 631 SL, 6 sorties par le temps
    ⇒ 90,52 % de reussite contre ~91,11 % requis, soit **-0,1655 $/trade**

Cohérent avec le gros test M1 de septembre (90,39 % contre 91,11 %) : la
géométrie 2/20 paie sa cote et le spread la fait basculer.
