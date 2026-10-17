# Un stop ÉVOLUTIF : indexé sur la VOLATILITÉ, non sur le prix

**Déclaré le 2026-10-14, AVANT d'écrire la mesure.**

Xavier : *« je souhaite faire une étude sur le stop-loss à poser qui va être
évolutif en fonction du cours de l'or. Quelle est la meilleure stratégie pour
perdre le moins possible et gagner à coup sûr ? »*

## ⛔ D'ABORD, CE QUI EST DÉJÀ RÉPONDU — ne pas le refaire

**« Gagner à coup sûr » n'existe pas**, et c'est ce dépôt qui l'établit le plus
durement : 248 cellules **0 retenue**, la direction **indiscernable du hasard**
sur 64 062 détections, 16 configurations M1 toutes négatives. Je ne le
promettrai pas.

**Et sa demande littérale est déjà balayée.** Le stop de production *est* déjà
évolutif en fonction du cours : `0,35 % du prix`. Le banc du 30/09
(`47b5c6c` → `e182ce0`) a testé **k = 0,5 à 3**, soit 0,148 % à 0,641 %,
38 cellules, 90 jours, 30 graines :

```
k      stop %    cout R    R moyen      t       z vs controle
0,50   0,148 %   0,0316    -0,0239   -1,79        +6,88
1,00   0,220 %   0,0213    -0,0451   -3,10        +1,68
3,00   0,641 %   0,0074    -0,0237   -0,80        -0,91
```

⇒ **R négatif partout**, le meilleur ne bat pas le hasard. 🔑 Et le fait le
plus instructif : **retirer 65 % du coût ne change quasiment rien**.

## 🔑 CE QUI RESTE OUVERT, et pourquoi c'est une AUTRE question

Un stop à `0,35 % du prix` suit le **niveau** de l'or, pas son **agitation**.
À 4180 $, il vaut 13 € que la dernière heure ait bougé de 2 $ ou de 25 $.
**Indexer sur la volatilité n'a jamais été testé.**

Et la structure mesurée hier dit que c'est exactement là qu'est l'argent :

```
125 trades : 83 gagnants a +0,623 EUR,  41 perdants a -1,708 EUR
   les 3 PIRES font 91 % de la perte nette
   et ces 3 sont morts en 2,9 / 4,7 / 5,2 minutes
```

⇒ Le problème n'est pas la largeur moyenne du stop, c'est **la queue** — un
phénomène de volatilité, pas de niveau de prix.

## ⚠️ DEUX DÉFAUTS DU BANC DU 30/09 QUE JE CORRIGE

1. 🔴 **La population changeait avec `k`** : 10 134 trades à k=0,5 contre
   1 988 à k=3, parce qu'un stop large fait échouer la porte des frais. On
   comparait donc des échantillons différents. ⇒ **Ici la population est
   FIXE** : les mêmes entrées, aux mêmes instants, et seule la politique de
   stop change.
2. 🔴 **Le spread était épinglé à une constante** (`0,20`), et un défaut
   connexe facturait 90 jours au spread d'un seul instant. ⇒ **Ici le spread
   est celui du tick**, plus le **markup de 10 points** mesuré le 12/10.

## Les cellules — politique de stop initial

| | politique | évolue avec |
|---|---|---|
| **A** | `0,35 %` du prix — **production** | le niveau du prix |
| **B** | `k × amplitude` des 15 dernières minutes | **la volatilité** |
| **C** | `k × amplitude` des 60 dernières minutes | la volatilité, plus lente |
| **D** | `k × spread` courant | le coût d'exécution |
| **E** | **13 € fixes** — témoin aveugle au prix | rien |

`k` calibré pour que **chaque cellule ait la même largeur MÉDIANE que A**
(≈13 €). 🔑 Sans cette calibration on ne mesurerait pas « indexer », on
mesurerait « plus large ou plus serré » — ce qui est déjà réfuté.

Tout le reste reprend la production du 12/10 : traînage `2 × spread`,
protection à la minute (60 s d'âge, 30 s de négativité, point milieu, plancher
`2 × spread`, plafond 9 €), aucun objectif, coût réel.

## ⛔ LE CRITÈRE

Une cellule remplace A **si et seulement si** :

1. l'écart de rendement `cellule − A` n'est **pas** négatif de façon
   significative (`t > −2,0`, unité **JOUR**) ;
2. **et** sa **pire journée** est meilleure que celle de A ;
3. **et** sa **queue** est plus fine : les 3 pires trades de chaque journée
   pèsent **moins** qu'ils ne pèsent chez A.

🔑 La condition 3 est le cœur : c'est la seule qui répond à « perdre le moins
possible ». Une cellule qui améliore la moyenne sans affiner la queue n'a rien
réglé — elle a déplacé le hasard.

⚠️ Et je fixe le **plafond de comparaisons** d'avance : 4 cellules × 3 valeurs
de `k` = 12 comparaisons, donc un `|t|` de 2,0 sera franchi par le hasard seul
dans ~45 % des cas. **Je ne retiendrai donc une cellule que si elle passe les
TROIS conditions**, et je la rejouerai hors échantillon avant toute
recommandation.

## MES PRÉDICTIONS, posées avant de coder

1. ⛔ **Aucune cellule ne battra A sur le rendement.** Je prédis que les douze
   écarts tiennent dans ±0,02 €/trade. Raison : le 30/09 a montré que même
   diviser le coût par 2,9 ne déplace pas le R.
2. 🔑 **MAIS je prédis que `B` (volatilité 15 min) affinera la QUEUE** — c'est
   ma seule prédiction optimiste, et la seule qui m'intéresse. Mécanisme : les
   3 trades qui font 91 % de la perte sont morts en moins de 6 minutes, donc
   dans un régime agité ; un stop qui s'élargit quand ça bouge leur laisse la
   place de respirer au lieu de les exécuter au pire moment.
3. ⚠️ **`D` (indexé sur le spread) sera le plus proche de A**, parce que le
   spread de l'or est quasi plat 00h-19h UTC : indexer sur une constante
   revient à ne rien indexer.
4. ⛔ **`E` (13 € fixes) sera indistinguable de A**, parce que l'or a varié de
   moins de 3 % sur la fenêtre : `0,35 % du prix` et `13 € fixes` sont presque
   le même nombre. Ce témoin sert à **mesurer combien vaut l'indexation au
   prix** — et je prédis : **rien**.
5. 🔑 **Et une prédiction sur le MÉCANISME** : je prédis que la corrélation
   entre l'amplitude des 15 minutes précédant l'entrée et la perte du trade
   est **positive et significative**. Si elle est nulle, alors la volatilité
   ne prédit pas la queue, `B` échouera, et la bonne conclusion sera que **la
   largeur du stop est le mauvais levier** — il faudra attaquer la
   **vitesse** du mouvement adverse, pas la largeur.

⇒ Si 1 et 5 tiennent ensemble, la recommandation sera de **ne pas toucher à la
largeur** et de passer au déclencheur de vitesse.

---

# VERDICT, le 2026-10-14 : LA LARGEUR DU STOP EST LE MAUVAIS LEVIER

3 682 189 ticks, 18 jours, **4 669 positions identiques pour les 5 cellules**.

## ⛔ ① LE MÉCANISME N'EXISTE PAS — ma prédiction n°5 est FAUSSE

```
amplitude des 15 min AVANT l'entree  ->  perte du trade :  r = +0,0201   t = +1,38
amplitude des 60 min                 ->                     r = +0,0139   t = +0,95
```

Je prédisais `r` **positif et significatif**. Il est positif et **non
significatif**. **L'agitation qui précède un trade ne prédit pas sa perte.**

🔑 Et j'avais écrit d'avance ce que ça impliquerait : *« si elle est nulle, la
volatilité ne prédit pas la queue, `B` échouera, et la bonne conclusion sera
que la largeur du stop est le mauvais levier »*. C'est exactement ce qui suit.

## ② Les cellules — population FIXE, coût réel

```
                      largeur med   p90    moyenne   pire jour  reussite   queue
A production 0,35 %      13,05    13,56   -0,0687     -0,222     78,4 %   -17,91
B volatilite 15 min      13,05    24,67   -0,0563     -0,190     78,0 %   -17,60
C volatilite 60 min      13,05    24,27   -0,0584     -0,166     78,0 %   -17,55
D spread courant         13,05    15,11   -0,0676     -0,246     78,3 %   -17,67
E 13 EUR fixes           13,00    13,00   -0,0709     -0,223     78,3 %   -17,82
```

`B` et `C` passaient **la lettre** de mon critère (les trois conditions).

## 🔴 ③ HORS ÉCHANTILLON, LE SIGNE S'INVERSE

Pré-inscrit : *« je la rejouerai hors échantillon avant toute
recommandation »*. 9 jours de calibration, 9 jours de contrôle, **`k` calibré
sur la première moitié seulement**.

```
                        dedans              dehors            signe
B volatilite 15 min   +0,0077 (t +1,19)   -0,0277 (t -0,60)   S'INVERSE
C volatilite 60 min   +0,0009 (t +0,15)   -0,0279 (t -0,67)   S'INVERSE
D spread courant      -0,0049 (t -1,15)   +0,0055 (t +1,03)   S'INVERSE
E 13 EUR fixes        -0,0040 (t -1,47)   -0,0002 (t -0,77)   tient
```

Et le jugement sur la **queue** s'inverse aussi : `B` l'aggrave dedans,
l'améliore dehors. ⇒ **Trois cellules sur quatre changent de signe. C'est la
signature du bruit, pas d'un effet.**

## ⛔ ET UN DÉFAUT DE MON PROPRE CRITÈRE, que les chiffres ont révélé

La condition 1 s'écrivait `t > −2,0` : elle est franchie **trivialement** par
tout ce qui est proche de zéro. Les conditions 2 et 3 n'étaient alors que des
comparaisons de deux nombres, **sans test de significativité**. Mon critère
laissait donc passer des cellules qui ne font **rien** — et c'est le rejeu hors
échantillon, lui aussi pré-inscrit, qui a rattrapé la faute.

⚠️ C'est la **deuxième fois en trois jours** qu'un critère à moi est trop
permissif (le 12/10, les six cellules de spread le passaient toutes). La
correction à retenir : **une condition de « pas significativement pire » ne
peut jamais servir de condition d'admission.**

## MES PRÉDICTIONS : 3 sur 5

| n° | prédiction | verdict |
|---|---|---|
| 1 | les douze écarts tiennent dans ±0,02 €/trade | ✅ sur l'échantillon complet (max 0,0101) — ⚠️ dépassé en demi-échantillon (0,0279) |
| 2 | `B` affinera la queue | ⛔ **s'inverse** entre dedans et dehors |
| 3 | `D` sera le plus proche de `A` | ✅ +0,0011, le plus petit écart |
| 4 | `E` sera indistinguable de `A` | ✅ **−0,0002, `t = −0,77` hors échantillon** |
| 5 | `r` positif ET significatif | ⛔ **FAUSSE** : `t = +1,38` |

## ✅ LA SEULE TROUVAILLE ROBUSTE, et elle est utile

**`E` — un stop de 13 € fixes — est indistinguable de la production.** Dedans
comme dehors, le signe tient et l'écart vaut **2 dix-millièmes d'euro**.

⇒ **Indexer le stop sur le cours de l'or ne vaut RIEN.** Les 0,35 % pourraient
être un montant fixe sans que rien ne change. Ce n'est pas un gain, c'est une
**simplification** : un réglage de moins à expliquer, et un chiffre que Xavier
lit directement en euros.

## ⇒ RECOMMANDATION

⛔ **Ne pas toucher à la largeur du stop.** Ni proportionnelle au prix, ni à la
volatilité, ni au spread : quatre politiques, aucune ne survit au hors
échantillon. Avec le balayage du 30/09 (38 cellules, k de 0,5 à 3), cela fait
**43 cellules de largeur de stop, zéro retenue**.

🔑 **Le levier est la VITESSE, pas la largeur.** Les trois trades qui faisaient
91 % de la perte du 12/10 sont morts en **2,9 / 4,7 / 5,2 minutes**, et la
protection ne peut agir qu'à partir de ~90 s (60 s d'âge + 30 s de négativité
consécutive, puis 60 s de cadence). Un déclencheur sur la **vitesse du
mouvement adverse** n'a jamais été testé — et c'est la seule piste que ce banc
laisse ouverte.
