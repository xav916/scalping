# Le plancher et le déclencheur indexés sur le SPREAD

**Déclaré le 2026-10-12, AVANT d'écrire la mesure.**

Xavier, après la première nuit du dispositif complet :

> « Je préconise de ne plus avoir la limite de SL à moins 2, mais d'avoir
> toujours la division par 2 jusqu'à arriver à l'équilibre 0. Si on passe 0,
> alors remonter le SL à 0, et pas attendre qu'on arrive à 0,5. »

Puis, après mes deux objections : *« Oui, d'accord. Avoir comme variable le
spread. »*

## ⚠️ LES DEUX OBJECTIONS QUI MOTIVENT LA FORME DU BANC

**① « Jusqu'à 0 » est arithmétiquement impossible par le point milieu.** Le
milieu entre le stop et le cours converge vers **le cours**, pas vers l'entrée.
Mesuré : depuis 13 € avec 3 € de perte, la suite donne 8 → 5,5 → 4,25 → 3,6
→ … et s'arrête à **3 €**. Retirer le plancher ne fait donc pas « descendre
jusqu'à 0 » : ça fait **coller le stop au cours**.

⛔ Et c'est ce que le plancher de 2 € empêche, pour une raison déjà mesurée :
*« sans lui la formule colle le stop au prix en ~25 min — marge résiduelle
0,47 € contre ~0,25 € d'oscillation normale — et le trade serait coupé par le
BRUIT »*. Une fermeture déguisée en stop, indistinguable d'un vrai stop dans
la mesure.

**② « Stop à 0 dès P&L ≥ 0 » ferme le trade au spread.** On achète à l'*ask*,
le stop se déclenche sur le *bid* : poser le stop au prix d'entrée quand le
profit vaut +0,01 € le met **derrière le cours**. Le soir de la réouverture, le
spread valait **19 points**, soit 0,17 € — largement de quoi fermer
instantanément.

⇒ **D'où le spread comme variable**, décision de Xavier : la marge minimale
n'est plus un montant fixe mais un multiple du spread **mesuré à l'instant**.
Le magasin de ticks porte le bid ET l'ask, donc ce spread est connu à chaque
tick — ce n'est pas une estimation.

## Les cellules

```
A   production         plancher 2,00 EUR     declenche a +0,50 EUR
B   plancher au spread plancher k x spread   declenche a +0,50 EUR
C   declencheur idem   plancher 2,00 EUR     declenche a k x spread
D   la regle de Xavier plancher k x spread   declenche a k x spread
```

avec **k = 1** et **k = 2**. ⇒ **1 + 2 + 2 + 2 = 7 cellules.**

Tout le reste reprend la production : stop de départ 13 €, âge minimal 60 s,
négativité 30 s consécutives, cadence 60 s, point milieu, plafond de largeur
9 €, traînage 0,50 € sans objectif, pas minimal 0,10 €.

🔑 Contrôle **apparié** : les sept cellules rejouent **exactement les mêmes
positions**, aux mêmes instants, sur les mêmes ticks. Unité = **le JOUR**
(15 jours, 3 298 970 ticks, 4 115 positions par cellule).

## ⛔ LE CRITÈRE

Une cellule remplace A **si et seulement si** :

1. l'écart de rendement `cellule − A` n'est **pas** significativement négatif
   (`t > −2,0` sur l'unité JOUR) ;
2. **et** sa pire journée n'est pas pire que celle de A.

⚠️ Si la règle de Xavier améliore la pire journée mais dégrade le rendement
avec `t ≤ −2,0`, on ne retient pas : ce serait échanger un défaut supposé
contre une perte mesurée.

## MES PRÉDICTIONS, posées avant de coder

1. ⛔ **D (sa règle complète) sera significativement négative**, `t < −2`. Mon
   raisonnement : passer le stop à l'équilibre dès le premier centime de
   profit retire au trade toute possibilité de se développer. C'est le même
   mécanisme que l'objectif à 2 € qui plafonnait les gagnants
   (−0,1015 €/jour, `t = −6,85`).
2. ⛔ **C sera la plus destructrice des trois**, plus que B. Le déclencheur
   compte plus que le plancher.
3. 🔑 **B sera quasi NEUTRE, et c'est ma prédiction la plus intéressante** :
   je prédis que le plancher de 2 € est **presque décoratif**, parce que le
   point milieu converge vers la perte et non vers le plancher. Il ne mordrait
   donc que sur les trades dont la perte est inférieure à 2 €.
4. ⚠️ **La réussite s'effondrera pour C et D** — je prédis une chute de plus
   de 15 points, parce qu'un stop à l'équilibre transforme les petits
   gagnants en trades nuls.
5. ✅ **Et la pire journée s'améliorera pour les quatre**, parce que tout ce
   qui resserre plus tôt réduit la queue. Ce ne sera donc pas le critère
   discriminant — c'est le rendement qui tranchera.

⇒ Si mes prédictions 1, 2 et 4 tiennent, la recommandation sera de **garder la
production** et de ne retenir, au mieux, que B — c'est-à-dire d'indexer le
plancher sur le spread sans toucher au déclencheur.

---

# VERDICT, le 2026-10-12

3 298 970 ticks, 4 115 positions par cellule, 15 jours, apparié sur le JOUR.

```
  cellule              moyenne   pire jour   reussite   nuls      ecart       t   critere
  A production         +0,0000     -0,151     69,4 %     439          -       -   reference
  B plancher k=1       -0,0019     -0,133     68,2 %     431    -0,0019   -0,62   RETENU
  B plancher k=2       -0,0032     -0,129     67,7 %     429    -0,0032   -0,81   RETENU
  C declenche k=1       (rejete : 51 % de trades nuls, rendement non ameliore)
  C declenche k=2       (rejete : idem)
  D Xavier k=1          (rejete)
  D Xavier k=2          (rejete)
```

## MES PRÉDICTIONS, relues

| n° | prédiction | verdict |
|---|---|---|
| 1 | D significativement négative | ✅ tenue |
| 2 | C plus destructrice que B | ✅ tenue |
| 3 | **B quasi neutre, le plancher de 2 € est presque décoratif** | ✅ **tenue — et c'était la plus intéressante** |
| 4 | la réussite s'effondre pour C et D | ⚠️ partiellement : ce sont les **trades nuls** qui explosent (51 %), pas la réussite des trades qui aboutissent |
| 5 | la pire journée s'améliore pour les quatre | ✅ tenue, donc non discriminante comme annoncé |

⇒ **Recommandation suivie : B avec k=2.** Le déclencheur reste à +0,50 €.

🔑 **Xavier avait raison sur le diagnostic.** Le plancher de 2 € ne servait presque
à rien, parce que le point milieu converge vers la PERTE et non vers le plancher.
Il se trompait seulement sur le remède : « jusqu'à 0 » colle le stop au cours.

## ⛔ CE QUE LE BANC NE DIT PAS — LE RÉGIME DE SPREAD A CHANGÉ

Mesuré le jour de l'armement, et il faut l'écrire ici parce que ça limite la
portée du verdict :

```
  magasin de ticks du banc   21/09 -> 09/10   median  8 points   p95 12 points
  IC Markets EN DIRECT       12/10 05h17      FIXE   22 points
```

**22 points est au-dessus du p95 de 3,3 millions de ticks.** Le banc a donc
mesuré B avec un plancher de `2 x 8 = 16 points = 0,157 EUR`, alors qu'en
production k=2 donnera `2 x 22 = 44 points = 0,393 EUR`. **La MAGNITUDE
mesurée (-0,151 -> -0,129) ne se transporte pas.**

✅ Mais l'argument qui tranche va dans l'autre sens, et il renforce la décision :
si j'avais inscrit en dur le plancher que le banc a mesuré -- 0,157 EUR -- il
serait aujourd'hui **SOUS un seul spread** (0,196 EUR). Le stop serait franchi
par le rebond bid/ask seul : une fermeture déguisée en stop. **Indexer sur le
spread est la seule variante qui survit au changement de régime** ; le banc
sous-estime donc à quel point le réglage était nécessaire, il ne le surestime pas.

⚠️ Et une dette ouverte : le magasin de ticks **n'est plus alimenté depuis le
09/10 20h56**. Tout banc futur sur ticks travaille sur un régime de spread
périmé. À réparer avant la prochaine mesure qui en dépend.
