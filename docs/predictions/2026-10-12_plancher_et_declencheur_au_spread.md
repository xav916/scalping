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
