# Les bancs refaits au COÛT RÉEL (+10 points de markup)

**Déclaré le 2026-10-12, AVANT d'écrire la mesure.**

Xavier : *« Refaire les bancs. »*

## D'OÙ VIENT CE BANC

Mesuré ce matin (`0e8a1ae`) : la route historique `/ticks`, dont est bâti
`ticks_courtier.db`, rend un spread **inférieur de 10 points** à la route
`/tick` que l'exécution utilise. 40 secondes appariées, écart médian
**+10,0 pts**, σ 1,2, 26 sur 40 valant exactement +10. Confirmé par les prix
d'exécution réels, qui dévient du bid/ask du magasin de **+3,5 pts (achats)**
et **+5,0 pts (ventes)** — la moitié de l'écart, exactement ce que prédit un
spread réel `= magasin + 10`.

⇒ **Tous mes bancs sur ticks ont sous-estimé le coût de 0,089 €/trade.**

## Le modèle de correction, et pourquoi celui-là

Le milieu est juste, la marge est **symétrique** :

```
bid_reel = bid_magasin - 5 points        ask_reel = ask_magasin + 5 points
```

🔑 Ce n'est pas une hypothèse de confort : la mesure d'exécution donne
**+3,5 pts** d'un côté et **+5,0** de l'autre, soit 5 par côté aux
arrondis près. ⚠️ Mais sa dispersion était énorme (p05 −48, p95 +126) à cause
de l'appariement temporel : **la première étape du banc re-mesure ce markup
proprement**, maintenant que le magasin couvre aujourd'hui, et le banc
s'arrête si la mesure ne confirme pas ~5 points par côté.

## Ce qu'on refait

| banc | question |
|---|---|
| ① validation | le markup par côté vaut-il bien ~5 points ? |
| ② plancher au spread | `B k=2` (ARMÉ ce matin) tient-il au coût réel ? |
| ③ traînage | la règle de Xavier (`k=2`) tient-elle au coût réel ? |
| ④ **l'audit de coût** | que rend la configuration ACTUELLE au coût réel, et quelle réussite exige-t-elle contre celle qu'elle obtient ? |

④ est le vrai enjeu. Les trois autres sont des contrôles.

## ⛔ LE CRITÈRE

Pour ② et ③, le critère reste celui de leurs bancs d'origine (`45b2526`,
`3cdd76e`), **inchangé** — on ne déplace pas la barre après coup.

Pour ④ il n'y a pas de critère : c'est une **description**, pas un test. Elle
ne peut rien « retenir ».

## MES PRÉDICTIONS, posées avant de coder

1. 🔑 **Les écarts APPARIÉS survivront** — c'est la prédiction qui compte,
   parce que **je l'ai affirmée ce matin sans la mesurer**. Les deux cellules
   d'une paire paient le même coût ajouté, donc `B − A` ne doit presque pas
   bouger. Je prédis **|Δ(B−A)| < 0,005 €/trade** pour les deux bancs.
   ⚠️ Et je prédis que ce ne sera pas exactement zéro : le coût plus élevé
   fait toucher le stop plus tôt, donc il change *aussi* la trajectoire, pas
   seulement le solde. Si l'écart bougeait de plus de 0,02 €, mon affirmation
   du matin serait **fausse** et je devrais la retirer.
2. ⚠️ **Le plancher `B k=2` restera retenu.** Son plancher passe de
   `2 × 8 = 16 pts` à `2 × 18 = 36 pts`, soit 0,157 → 0,246 € — toujours très
   loin des 2,00 € (224 pts) qu'il remplace.
3. ⚠️ **La règle de Xavier restera indistinguable de zéro.** Sa largeur passe
   de 0,143 à 0,232 €, donc elle coupe moins tôt, donc son effet s'atténue
   des deux côtés. Je prédis que son écart contre A **reste dans ±0,01 €**.
4. 🔴 **Le niveau absolu s'effondrera de ~0,089 €/trade**, et c'est la vraie
   nouvelle : la configuration actuelle passera d'environ **−0,001** à
   environ **−0,090 €/trade**. Sur 30 trades/5 h cela fait ~−2,7 €, à
   comparer aux **−7,26 €** réellement constatés ce matin — je prédis donc
   que le coût corrigé **explique une partie de l'écart entre banc et réel,
   sans le combler entièrement**.
5. 🔑 **Et une prédiction sur la réussite requise** : au coût réel, la
   géométrie actuelle exigera une réussite **plus haute d'environ 1,5 point**
   que ce qu'elle exigeait au coût du magasin. Si l'écart mesuré en
   production (90,39 % obtenus contre 91,11 % requis, soit **0,72 point**)
   est du même ordre, alors **le markup explique à lui seul tout l'échec de
   la géométrie** — ce serait le résultat le plus important de la journée.
6. ⛔ **Enfin, je prédis que je ne pourrai PAS conclure sur ⑤ avec ce banc
   seul**, parce que les entrées du banc sont synthétiques (toutes les 300 s)
   et non les setups réels. Je l'écris d'avance pour ne pas être tenté de
   surinterpréter un chiffre qui m'arrangerait.

---

# VERDICT, le 2026-10-12

3 371 441 ticks, 16 jours, 4 213 positions par cellule, apparié sur le JOUR.

## ① La validation est passée

```
ACHATS  execute - ask magasin   n=30  median +4,3 pts
VENTES  bid magasin - execute   n=32  median +5,2 pts
                                      => +5,0 pts par cote (attendu 5,0)
```

✅ Le modèle `bid − 5 pts / ask + 5 pts` est confirmé par l'exécution réelle.

## ② Les cellules, au coût du magasin puis au coût RÉEL

```
                     moyenne  pire jour  reussite   nuls   gain moy
A production magasin +0,0072    -0,146     80,2 %   8,4 %   +0,743
A production REEL    -0,0824    -0,228     77,8 %   7,3 %   +0,748
B plancher   magasin +0,0032    -0,126     78,3 %   8,1 %   +0,740
B plancher   REEL    -0,0868    -0,267     75,7 %   7,2 %   +0,745
X regle Xavier magas +0,0038    -0,123     85,4 %  17,1 %   +0,387
X regle Xavier REEL  -0,0871    -0,204     78,2 %  11,0 %   +0,581
```

## 🔑 PRÉDICTION n°1 : TENUE — et elle valide mon affirmation du matin

```
ecart contre A      au magasin      t     au cout REEL      t      DELTA
B plancher k=2         -0,0025   -0,57        -0,0037   -0,83    -0,0011
X regle de Xavier      -0,0069   -0,40        -0,0020   -0,18    +0,0049
```

**Plus grand déplacement : +0,0049 €/trade**, sous mes 0,005 annoncés. ✅ Mon
affirmation du matin — « les comparaisons appariées survivent » — **se
vérifie**. Je ne la retire pas.

## MES PRÉDICTIONS : 3 sur 5, et les deux fausses comptent

| n° | prédiction | verdict |
|---|---|---|
| 1 | les écarts appariés survivent, < 0,005 | ✅ **tenue** (+0,0049) |
| 2 | `B k=2` reste retenu | ⛔ **FAUSSE — il ÉCHOUE** (voir ci-dessous) |
| 3 | la règle de Xavier reste dans ±0,01 | ✅ tenue (−0,0020) |
| 4 | le niveau chute de ~0,089 €/trade | ✅ **tenue au millième** : −0,0895 mesuré contre 0,0893 théorique |
| 5 | le markup relève la réussite REQUISE de ~1,5 pt | ⛔ **FAUSSE, et instructive** : il la relève de **−0,00 point** |

## 🔑 CE QUE LA PRÉDICTION n°5 M'APPREND EN SE TROMPANT

Le markup **ne change pas** ce que la géométrie exige :

```
reussite REQUISE   79,99 %  au magasin   ->   79,99 %  au cout REEL
reussite OBTENUE   80,18 %               ->   77,78 %
marge              +0,19 pt              ->   -2,20 pt
```

Il ne déplace pas la barre : il **détruit 2,40 points de réussite obtenue**,
en basculant du bon côté au mauvais les trades qui gagnaient de moins que le
markup. Et **2,40 points, c'est 3,3 fois les 0,72 point** qui manquaient à la
géométrie en production.

⛔ **Mais je tiens ma prédiction n°6 : on ne peut PAS en conclure l'attribution.**
Les entrées de ce banc sont synthétiques (toutes les 300 s), pas les setups
réels. C'est un **ordre de grandeur** qui dit où chercher, pas une cause
établie.

## 🔴 ET LA CONSÉQUENCE QUI PORTE : `B` NE PASSE PLUS SON CRITÈRE

Le critère de `45b2526`, **inchangé** : (1) `t > −2`, (2) pire journée pas
pire que A, (3) nuls bornés.

```
B au cout REEL :  t -0,83  ✅      pire jour -0,267 contre -0,228  ⛔      nuls 7,2 vs 7,3  ✅
```

**Il échoue sur la condition 2.** Au coût du magasin il la passait
(−0,126 contre −0,146) : **ma décision du matin reposait sur un coût
sous-estimé.**

Et j'ai regardé si cet échec tenait à un accident, parce que la mémoire du
projet porte déjà « tout l'écart vient d'1 trade » :

```
sa pire journee est le 2026-10-05, ecart B-A = -0,0390
   SANS ce jour, le critere PASSE (pire jour B -0,195 contre A -0,227)
   et sur ce jour, 3 trades sur 276 font 69 % de l'ecart (-7,42 de -10,76 EUR)
```

⚠️ **Mais ce n'est pas qu'un accident** : `B` est aussi **mollement et
régulièrement moins bon** — moyenne `B−A` **−0,0037**, médiane **−0,0070**, et
`B` ne fait mieux que **5 jours sur 16**. Rien de significatif (`t = −0,83`),
mais la direction est constante.

⇒ **Recommandation : DÉSARMER le plancher au spread**
(`PROTECTION_PERTE_PLANCHER_SPREAD_K`). Le critère posé avant la mesure
tranche, et les deux lectures indépendantes pointent dans le même sens.
Retrait par une ligne de crontab, sans redémarrage ni réarmement.

🔑 Et sur `X` (la configuration armée cet après-midi, plancher ET traînage au
spread) : au coût réel son rendement est **indistinguable** de A (`t = −0,18`)
et sa **pire journée est MEILLEURE** (−0,204 contre −0,228). Seuls ses trades
nuls restent hauts (11,0 % contre 7,3 %) — ce que j'avais déjà dit avant de
l'armer. **Rien de nouveau contre elle.**

---

# 🔴 DÉCISION DE XAVIER, le 2026-10-12 : GARDER le plancher au spread

J'ai recommandé de désarmer `PROTECTION_PERTE_PLANCHER_SPREAD_K` parce que la
condition 2 de mon critère pré-inscrit ne tient plus au coût réel. Xavier :
**« Garder armé. »**

⇒ **Le réglage reste en vigueur. Décision prise contre ma recommandation**, et
elle est défendable : l'écart n'est **pas significatif** (`t = −0,83`) et mon
banc rejoue des entrées **synthétiques**, pas ses setups.

## Ce qui remplace le critère : une surveillance FALSIFIABLE sur le réel

Mon banc ne pouvait pas trancher. Ses vrais trades, eux, peuvent — à condition
de dire **d'avance** ce qui compterait comme un échec.

🔑 Le mécanisme suspecté est précis : un plancher à `2 × spread` (~0,39 €)
place le stop si près du prix qu'il est touché par le bruit, coupant des
trades qui allaient gagner. Sur le banc, 3 trades du 05/10 passaient de
**+1,17 € à −1,47 €**.

**Ce qui le prouverait sur le réel** — les trades dont le stop a été resserré
par la protection **jusqu'au plancher** (et non au point milieu) :

| | seuil fixé d'avance |
|---|---|
| ⛔ échec | ≥ 10 trades plancher-liés, et leur P&L moyen est inférieur de plus de **0,30 €** à celui des trades resserrés au point milieu |
| ✅ succès | ≥ 10 trades plancher-liés, et leur P&L moyen n'est **pas** inférieur |
| ⏳ indécidable | moins de 10 trades plancher-liés |

⚠️ **Et la limite de cette surveillance, écrite maintenant** : elle compare
des trades que la protection a traités différemment **parce qu'ils étaient
différents** — ce n'est pas un contrôle apparié. Elle peut donc **signaler**
un problème, pas l'établir. Un signalement déclenchera un banc apparié sur
les setups réels, pas un désarmement direct.

⇒ Relevé à faire quand le compteur atteint 10 trades plancher-liés.
