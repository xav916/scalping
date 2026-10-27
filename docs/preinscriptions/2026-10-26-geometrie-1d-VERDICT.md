# Verdict — la géométrie `1d` peut-elle payer ?

**Pré-inscription** : `ecbe33c` · **Banc** : `6fe3d82`
(antériorité **prouvée** par `or-preinscription`, code 0)
**4 prédictions sur 5 passent — et le verdict est pourtant INDÉCIDABLE.**

## Le résultat

```
n 1d total 1362   dont résolus TP1/SL 728   (4h de contrôle : 1775)
TIMEOUT 634 = 46,5 % de la population

VALIDITÉ DU REJEU ............................................. valide
  n résolus >= 300 ....................................... 728
  mfe non nul > 99 % .................................. 100,00 %
  R:R conforme > 95 % ................................. 100,00 %

P1  R:R conforme en 1d ....... 100,00 %  (médiane +1,800)       PASSE
P2  risque médian en 1d ......   9,33 %  (attendu 9-15 %)       PASSE
P3  réussite (convention B) ..  29,95 %  contre 35,71 % requis,
                                         z = −3,246             PASSE
P4  R:R conforme en 4h ....... 100,00 %  (médiane +1,800)       PASSE
P5  écart entre conventions ..  +8,748 pt  (A = 38,69 %)       ÉCHOUE

VERDICT : INDECIDABLE_CONVENTIONS
```

## ⛔ Ce que je retire, comme je m'y étais engagé

**P1 passe à 100 %, médiane exactement 1,800 — sur les deux horizons.**
J'avais écrit que le TP `1d` « ressemble à un réglage mal mis à l'échelle ».
**C'est faux, et je le retire.** La formule est appliquée correctement : le TP
vaut exactement 1,8 × le risque, partout. Les 21 % de distance sont la
**conséquence exacte d'une formule correcte** appliquée à `min(low des 5
dernières bougies)` — soit cinq jours sur un horizon journalier. Il n'y a pas
de bug d'échelle.

Et P4 le confirme de façon décisive : le `4h` est **aussi** à 100 % de
conformité. L'écart entre horizons vient donc du **stop** (9,33 % du prix en
`1d`), pas du R:R.

## Pourquoi INDÉCIDABLE, et pourquoi c'est le bon verdict

**46,5 % de la population ne touche aucune borne.** Le sens du résultat dépend
alors entièrement de ce qu'on décide qu'un `TIMEOUT` signifie :

| convention | réussite | contre 35,71 % requis |
|---|---|---|
| **B** — `TIMEOUT` exclu (question de géométrie) | **29,95 %** | **sous** le seuil |
| **A** — `TIMEOUT` compté à son P&L réel | **38,69 %** | **au-dessus** du seuil |

**8,75 points d'écart**, pour un seuil d'indécidabilité pré-inscrit à 5. Les
deux lectures donnent des réponses **opposées** à la question posée.

🔑 Et c'est exactement pour ça que la garde avait été pré-inscrite. Sans elle,
j'aurais publié « la géométrie `1d` est structurellement perdante, z = −3,25 »
— un chiffre juste, une conclusion non soutenue, et une convention choisie
après coup parce qu'elle allait dans le sens de ma piste.

⚠️ Un `TIMEOUT` sort au **dernier prix connu**. Son signe vient d'une clôture
arbitraire, pas d'une décision de sortie. Lui donner le statut de « gagnant »
quand son P&L est positif est défendable, mais ce n'est pas une mesure — c'est
un choix.

## `or-verdict` refuse aussi, pour une autre raison, et elle est légitime

```
=== NE PAS PUBLIER
  - [ecart_par_trade] est null
```

`or-verdict` juge des **rejeux** : `ecart_par_trade` mesure la fidélité d'un
rejeu à la réalité vécue. Ce banc ne rejoue rien — il lit des issues déjà
calculées et les compare à un seuil arithmétique, sans second bras. La quantité
n'existe donc pas, et **émettre `0.0` aurait fait croire à un rejeu parfait**.

⇒ Les deux dispositifs convergent : **ne rien publier comme décision.**

🔬 Limite du pack à retenir : `or-verdict` ne sait juger qu'une forme de banc.
Un banc à un seul échantillon contre un seuil lui est étranger. À étendre, ou à
documenter comme hors de sa portée — mais pas à contourner en fabriquant un
champ.

## Ce qui trancherait

Rien de mesurable. Il faut **décider ce qu'un `TIMEOUT` signifie** pour un
horizon où il concerne presque un setup sur deux :

- soit une sortie au marché à l'échéance — alors la convention A est la bonne,
  et la géométrie `1d` tient son seuil ;
- soit un setup qui n'a jamais abouti — alors c'est B, et elle ne le tient pas.

C'est une décision, pas une mesure. Elle revient à Xavier.

## Ce que ce verdict ne dit pas

- **Aucun placebo n'a été exécuté** (pré-inscrit). Rien ici ne dit s'il existe
  un edge — seulement si une géométrie atteint son propre seuil arithmétique.
- Donnée **rattrapée** (`resolved_backfill = 1`), issues produites par le même
  chemin que la production mais sur des bougies allées chercher après coup.
- Une seule cellule pré-spécifiée, donc aucune correction de multiplicité — et
  **aucune autre cellule ne sera testée après coup sur cette donnée.**
