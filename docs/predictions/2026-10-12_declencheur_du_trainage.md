# Le DÉCLENCHEUR du traînage — « dès que le trade passe en positif »

**Déclaré le 2026-10-12, AVANT d'écrire la mesure.**

Xavier, après l'armement du plancher au spread :

> « Dès que le trade passe en positif, alors remontez le SL. Parce que là,
> j'ai l'impression qu'on laisse vivre le trade pendant un certain temps,
> avant de toucher au SL. »

## ✅ SA PERCEPTION EST EXACTE — voici le code en production

```python
largeur = trainage_eur()          # ECHELLE_STOP_OR_TRAINAGE_EUR = 0,50
if profit_eur < largeur:          # sous +0,50 EUR
    return None                   # ON NE POSE RIEN
return round(profit_eur - largeur, 2)
```

Rien ne bouge côté gain sous **+0,50 €** de profit, soit **56 points** de
mouvement à 0,01 lot, soit **2,5 fois le spread** mesuré ce matin (22 points).
Et le premier palier de l'échelle est à **+1,00 €**. Ce n'est pas un délai de
temps : c'est une distance de prix.

## ⚠️ POURQUOI SA FORMULATION LITTÉRALE EST IMPOSSIBLE

Avec une largeur de 0,50 €, « remonter le SL » à +0,10 € de profit place le
stop à **−0,40 €** : toujours en perte. Pour que le stop atteigne **0** dès le
premier centime, il faudrait une largeur ≈ 0, donc un stop **à l'intérieur du
spread** ⇒ fermeture immédiate par le rebond bid/ask.

⛔ Et c'est déjà mesuré : les cellules C et D du banc `45b2526` faisaient
exactement ça (stop à l'équilibre dès `k × spread` de profit) ⇒ **51 % de
trades nuls**, rejetées.

🔑 **MAIS une variante n'a jamais été mesurée**, et c'est celle qui honore son
intention sans l'arithmétique impossible : **baisser le DÉCLENCHEUR sans
toucher à la LARGEUR**. Le stop commence alors à suivre plus tôt, en restant
à 0,50 € derrière le cours — donc jamais dans le spread.

## Les cellules

```
A production        declenche a 0,50 EUR   largeur 0,50 EUR
B declencheur bas   declenche a k x spread largeur 0,50 EUR   <- sa demande, version possible
C les deux au spread declenche a k x spread largeur k x spread
D largeur seule     declenche a 0,50 EUR   largeur k x spread
```

avec **k = 1** et **k = 2** ⇒ **1 + 2 + 2 + 2 = 7 cellules.**

Tout le reste reprend la production : stop de départ 13 €, plafond de largeur
9 €, pas minimal 0,10 €, aucun objectif, protection des pertes à la minute
(âge 60 s, négativité 30 s consécutives, point milieu, **plancher au spread
k=2** armé ce matin), traînage relu **à la seconde**.

🔑 Contrôle **apparié** : les sept cellules rejouent les **mêmes positions**,
aux mêmes instants, sur les mêmes ticks. Unité = **le JOUR**.

⚠️ Le magasin de ticks porte un spread **2,75× plus serré** que le réel
(8 points contre 22) — cf. le verdict de `12fe165`. Les magnitudes ne se
transporteront pas ; seul le **signe** et le **classement** des cellules sont
exploitables.

## ⛔ LE CRITÈRE

Une cellule remplace A **si et seulement si** les **trois** conditions tiennent :

1. l'écart de rendement `cellule − A` n'est pas significativement négatif
   (`t > −2,0` sur l'unité JOUR) ;
2. **et** sa pire journée n'est pas pire que celle de A ;
3. **et** son taux de trades NULS (`|pnl| < 0,05 €`) ne dépasse pas celui de A
   de plus de **25 % en relatif**.

🔑 La condition 3 est nouvelle, et elle corrige une faute de ma part : hier
**mon critère était trop permissif** et les six cellules de spread le
passaient toutes. Un réglage qui transforme les gagnants en trades nuls ne
« perd » rien au sens du `t` — il stérilise. Il faut le borner **d'avance**.

## MES PRÉDICTIONS, posées avant de coder

1. ⛔ **C sera la plus destructrice.** Largeur `2 × spread` = 44 points de
   marge contre 56 aujourd'hui : le bruit normal de l'or (~0,25 €) la
   traverse. Je prédis `t < −3`.
2. ⚠️ **B sera la plus intéressante, et je ne sais pas prédire son signe.**
   Deux forces opposées : `r = −0,802` dit que **les perdants traînent**, donc
   serrer tôt devrait couper des perdants ; mais un gagnant qui respire est
   coupé avant de se développer. **C'est la seule cellule dont j'attends
   vraiment la réponse.** Je parie quand même sur **légèrement négatif**,
   parce que c'est le résultat de toutes les variantes « serrer plus » testées
   jusqu'ici (16 configurations M1, 0 retenue ; échelle TP/SL ; TP à 2 €).
3. ⛔ **D augmentera les trades nuls** sans améliorer le rendement : à +0,50 €
   le stop irait à +0,11 au lieu de 0, donc plus de sorties à un petit gain
   ridicule. Je prédis qu'elle **échoue sur la condition 3**.
4. ✅ **La pire journée s'améliorera pour les six**, comme toujours quand on
   serre plus tôt. Donc la condition 2 ne discriminera pas — ce sera le `t` et
   le taux de nuls.
5. 🔑 **Et une prédiction sur le MÉCANISME, pas sur le chiffre** : je prédis
   que le nombre de trades qui atteignent +0,50 € est **faible** — que la
   plupart des trades ne déclenchent **jamais** le traînage, et que ce réglage
   touche donc moins de trades que son importance apparente ne le suggère. Si
   c'est vrai, l'impression de Xavier (« on laisse vivre ») décrit la
   **majorité** des trades, pas une minorité.

⇒ Si mes prédictions 1 et 3 tiennent, la recommandation dépendra entièrement
de **B**. C'est la question ouverte de ce banc.

---

# VERDICT, le 2026-10-12

3 298 970 ticks, 4 115 positions par cellule, 15 jours, apparié sur le JOUR.

```
  cellule              moyenne   pire jour   reussite   nuls   declenche
  A production         -0,0008     -0,126     78,1 %    8,2 %    78,1 %
  B declencheur k=1    -0,0058     -0,119     48,4 %    6,5 %    90,4 %   t -0,31
  B declencheur k=2    -0,0050     -0,114     51,8 %    7,0 %    88,3 %   t -0,35
  C les deux k=1       -0,1813     -1,671     11,8 %    0,0 %    90,4 %   DEGENEREE
  C les deux k=2       +0,0031     -0,129     85,4 %   17,2 %    88,3 %   rejete (cond. 3)
  D largeur k=1        -0,1813     -1,671     11,8 %    0,0 %    78,1 %   DEGENEREE
  D largeur k=2        +0,0102     -0,107     78,0 %    0,0 %    78,1 %   t +1,08
```

## ⛔ D'ABORD, UN DÉFAUT DE MON BANC — les cellules k=1 ne mesurent RIEN

La garde qui empêche de poser le stop dans le spread s'écrit `c2 < pnl −
spread`. Avec `largeur = 1 × spread`, elle devient `pnl − spread < pnl −
spread` : **toujours fausse**. À k=1 le traînage ne s'applique donc **jamais**.

Preuve dans les résultats eux-mêmes : `C k=1` et `D k=1` sont **identiques au
centième** (−0,1813 / pire −1,671 / 11,8 % / 0,0 % nuls) alors que leurs
déclencheurs diffèrent (90,4 % contre 78,1 %). Elles mesurent toutes les deux
« aucun traînage », pas ce qu'elles annoncent.

🔑 Ce que ces deux cellules montrent quand même, par accident : **sans
traînage du tout**, le rendement tombe à −0,1813 €/trade et la pire journée à
−1,671. Le traînage vaut donc beaucoup — c'est la mesure la plus nette du banc,
et elle n'était pas la question posée.

## MES PRÉDICTIONS : 1 sur 5

| n° | prédiction | verdict |
|---|---|---|
| 1 | C la plus destructrice, `t < −3` | ⛔ **FAUX** : C k=1 est dégénérée, C k=2 est **positive** (+0,0031) |
| 2 | B légèrement négative | ✅ tenue (−0,0046 / −0,0041), mais non significative |
| 3 | D échoue sur la condition 3 (trades nuls) | ⛔ **FAUX, et à l'envers** : D k=2 a **0,0 %** de nuls et c'est la meilleure cellule |
| 4 | la pire journée s'améliore pour les six | ⛔ **FAUX** : −1,671 pour les deux dégénérées |
| 5 | le traînage ne se déclenche que sur peu de trades | ⛔ **FAUX** : **78,1 %** des trades atteignent +0,50 € |

## ⛔ LA RÉPONSE À XAVIER : baisser le déclencheur NE SERT PAS

`B` passe le critère par la lettre (`t = −0,31`, pire journée améliorée, moins
de nuls) **mais la réussite s'effondre de 78,1 % à 48,4 %** pour un rendement
statistiquement inchangé. Déclencher plus tôt coupe un trade gagnant sur
trois sans rien rapporter.

🔑 Et la prédiction 5 renversée l'explique : **78,1 % des trades atteignent
déjà +0,50 €**. Le déclencheur n'est pas un barrage — la grande majorité des
trades le franchit. Ce que Xavier voit (« on laisse vivre ») est la *première
phase* de presque tous les trades, pas un blocage.

⇒ **Recommandation : ne pas toucher au déclencheur.**

## ⚠️ MAIS UNE CELLULE MÉRITE UN SECOND BANC — et je ne peux pas la retenir

`D k=2` — garder le déclencheur à +0,50 € et **resserrer la LARGEUR** à
`2 × spread` — passe les trois conditions : `+0,0106 €/trade`, `t = +1,08`,
pire journée **−0,107 contre −0,126**, **0 % de trades nuls**, réussite
inchangée (78,0 contre 78,1 %).

⛔ **Je ne la retiens pas, pour une raison de régime de spread.** Dans le
magasin, `2 × spread = 0,143 €` ; en production ce matin, `2 × 0,196 =
0,393 €`. Le banc a donc mesuré un resserrage **de 0,50 à 0,14 €** — radical —
alors qu'armer le réglage donnerait **0,50 → 0,39 €**, presque rien. Le `+0,0106`
ne décrit pas ce que l'armement ferait.

🔑 C'est le même piège que la veille, et il est ici **proportionnel à l'effet
mesuré** au lieu d'être un simple décalage. La règle qui s'impose : **tout
réglage dont l'effet est proportionnel au spread doit être mesuré sur un
magasin de ticks au régime COURANT.** Le magasin s'arrête au 09/10 20h56.

⇒ **Dette préalable : réalimenter le magasin de ticks.** Ensuite, et seulement
ensuite, rejouer `D k=2` — et corriger la garde à k=1.
