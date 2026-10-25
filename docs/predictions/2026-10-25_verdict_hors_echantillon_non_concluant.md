# VERDICT — hors échantillon NON CONCLUANT, et le signe s'inverse

**Pré-inscrit `c7861fd`, mesuré juste après. 13 journées, 99 trades, coût gelé
à 0,30 USD — zéro paramètre libre.**

## ⛔ LA CONDITION DE VALIDITÉ, PRÉ-INSCRITE, ÉCHOUE

```
ecart A - reel = -56,74 EUR sur 99 trades = -0,5731 EUR/trade
barre pre-inscrite : < 0,50 EUR/trade        =>  NON CONCLUANT
```

J'avais écrit : « si le rejeu ne reproduit pas le P&L réel à mieux que
0,50 €/trade, je déclare la mesure non concluante ». Elle l'est. **Pas de
verdict sur `B − A` pour ces 13 journées.**

## 🔑 ET LA CAUSE EST STRUCTURELLE : CE N'EST PAS LA MÊME ACTIVITÉ

```
jour      n    duree moyenne    duree MAX
12/10   165       2,8 min        11 min      <- du SCALPING
11/10     8       5,4 min        14 min
09/10    32      23,8 min       164 min
08/10     6      64,2 min       340 min
02/10    16     286,2 min     3 368 min      <- 2,3 JOURS
30/09     5     462,6 min     2 107 min
21/09     1     364,7 min       365 min
```

🔑 **L'horizon de détention varie d'un facteur ~100** entre le 12/10 et les
semaines précédentes. Mon rejeu est borné à la journée : il **tronque** les
positions multi-jours, d'où des écarts absurdes sur les journées calmes
(21/09 : 1 trade, réel −16,97 €, rejeu −0,37 € ; 28/09 : réel +33,29 €, rejeu
+1,05 €).

⇒ **Le verdict du 12/10 ne se généralise pas, parce que le 12/10 n'est pas
représentatif de ce que faisait le robot.** La protection a été mesurée sur la
seule journée où elle opérait en régime de scalping.

## ⚠️ OBSERVATION EXPLORATOIRE — et je la marque comme POST HOC

En restreignant aux deux journées dont l'horizon est comparable au 12/10
(**09/10** et **11/10**), le rejeu **repasse la barre de validité** :

```
n=40   ecart A-reel = +0,3824 EUR/trade   VALIDE
       B - A = -21,31 EUR  |  -0,5327 EUR/trade  |  t = -0,98
```

Le 12/10 donnait `B − A = +0,1396 €/trade`. Ici : **−0,5327**. **Le signe
s'inverse.**

⛔ **Ce sous-ensemble a été choisi APRÈS avoir vu la donnée.** Il n'était pas
pré-inscrit, et `|t| = 0,98` reste très en dessous de 2. Son seul usage
légitime est négatif : **il interdit de généraliser le résultat du 12/10.** Je
refuse de le retenir comme une mesure — re-découper la donnée jusqu'à ce
qu'une cellule parle est exactement ce que la pré-inscription existe pour
empêcher.

## ⇒ CE QUI TIENT APRÈS LES DEUX MESURES DU JOUR

1. ✅ **Mon « 642 € évités » du 13/10 était faux**, et de signe. Ça, c'est
   acquis : le rejeu du 12/10 était validé sur trois cibles.
2. ⛔ **L'effet net de la protection n'est établi dans AUCUN sens.** `+0,14` en
   échantillon, `−0,53` hors échantillon sur horizon comparable, `|t| < 1`
   partout.
3. ✅ **Le seul effet stable, sur les deux mesures** : la réussite est
   meilleure **sans** protection — **+17,0 points** le 12/10, **+15,2** sur les
   13 journées, **+10,0** sur le sous-ensemble valide. Le compromis est
   toujours le même : moins de trades perdants, mais ceux qui perdent coûtent
   plus cher.
4. ⛔ **Toujours aucune raison de désarmer quoi que ce soit.**

## MES PRÉDICTIONS : 3 SUR 5

1. ⛔ **FAUSSE** — « `B − A` restera positif ». Négatif sur les 99 trades
   (−0,138) **et** sur le sous-ensemble valide (−0,533). Mon argument
   « le mécanisme est structurel » ne tient pas.
2. ✅ **JUSTE** — « `|t|` ne dépassera pas 2 » : `−0,43` et `−0,98`.
3. ✅ **JUSTE** — « l'écart de réussite tiendra à ≥ +5 points » : **+15,2**.
4. ⚠️ **À MOITIÉ** — j'avais raison que le rejeu reproduirait moins bien
   (erreur > 0,10 €/trade : elle vaut 0,573), **faux** qu'il resterait sous la
   barre de 0,50. Ma propre condition de validité m'a arrêté.
5. ✅ **JUSTE** — « le 12/10 est aberrant » : les 13 autres journées font
   **+0,108 €/trade** contre **−0,231** le 12/10, sur la donnée réelle.

## ⇒ LA SUITE, ET ELLE N'EST PAS DANS CE BANC

Mesurer la protection correctement demande un rejeu **qui ne s'arrête pas à
minuit** — les positions vivaient jusqu'à 2,3 jours. Et ça demande des ticks
que nous n'avons plus : le magasin est **gelé au 16/10** depuis la panne du
pont. Cf. [[project_pont_mt5_mort_9_jours_2026_10_25]].

🔑 **Autrement dit : la prochaine version de cette mesure dépend de la
réparation du pont, pas de mon code.**
