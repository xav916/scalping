# Verdict — l'hypothèse visée est REJETÉE, et le banc trouve bien pire : **le `t` tombe à +1,600**

**Pré-inscription** : `caeffc4` · **Banc** : `caeffc4`
**4 prédictions sur 5** · **`or-verdict` : PUBLIABLE — REJET**

## Le résultat

```
n = 4280   couverture 100,00 %   duos = 1877
reproduction de 2613282 : ecart maximum 0,000 %
ratios non unitaires : 95,0 %   mediane |decalage| / risque : 0,341
```

| barreau | placebo | ÉCART | σ nul | `t` | `ρ` | var/jambe | 1 TP / 1 SL |
|---|---|---|---|---|---|---|---|
| `RESEAU` | −0,151296 | **+0,091961** | 0,020967 | +4,386 | **+0,0040** | 1,81209 | 45,7 % |
| `RESEAU_ET_PAIRES` | −0,149824 | **+0,090488** | 0,016153 | +5,602 | −0,4432 | 1,81332 | 66,3 % |
| **`DECALAGE`** | **−0,082388** | **+0,023053** | 0,014407 | **+1,600** | −0,3441 | 1,83047 | 63,5 % |

`ρ` RÉEL : **−0,1273** · écart au réel : **DECALAGE 0,2169** contre APPARIÉ 0,3159

## ⛔ CE QUE J'AVAIS VISÉ : REJETÉ

Le barreau fidèle devait retrouver le `ρ` **réel** (−0,1273). Il rend **−0,3441**
— écart **0,2169** pour un seuil de **0,10**. ⇒ **`P1` échoue, et donc le `t`
n'est toujours pas mesurable par cette voie.** J'ai échoué à lever la limite de
`8935497`.

⚖️ **À sa décharge** : il va dans la bonne direction, et de beaucoup — l'écart au
réel passe de **0,3159** (miroir) à **0,2169**. Les décalages d'entrée expliquent
donc environ **un tiers** du chemin. Ce qui reste est inexpliqué, et la
**asymétrie résiduelle** (bornes d'août contre bougies du jour) en est le
candidat le plus probable : du bruit sur le bras réel pousse son `ρ` vers zéro.

## ✅ EN REVANCHE, LE BUT ORIGINEL EST ATTEINT

`P2` et `P3` tiennent : **variance par jambe `DECALAGE / RESEAU` = 1,0101**.

⇒ **L'hypothèse que ma formule de `8935497` supposait est VÉRIFIÉE.** Le
`t ≈ +4,58` dérivé hier n'était donc **pas biaisé** par elle. ✅ **La limite que
j'avais nommée comme « la plus sérieuse » de ce verdict est levée.**

Et `P4`, le contrôle négatif, tient aussi : `ρ(RESEAU) = +0,0040`, nul. ⇒ **Sans
instant partagé, pas de corrélation intra-duo** — l'appariement est bien ce qui
la crée, et le raisonnement de `8935497` n'est pas suspect de ce côté.

`P5` : médiane `|décalage| / risque` = **0,341**, contre ≈ 0,3 estimé.

## 🔴 ET LE RÉSULTAT QUI DOMINE, QUE JE N'AVAIS PAS PRÉDIT

```
placebo RESEAU    -0,151296
placebo DECALAGE  -0,082388     =>  +0,0689 R gagnes par le placebo
ecart original : +0,091961      =>  75 % de « mon signal » recupere
t : +4,386  ->  +1,600          =>  SOUS la barre de 2
```

🔴 **Donner à chaque jambe son propre décalage d'entrée d'août récupère 75 % de
ce que j'appelais « le signal ».** Le `t` tombe **sous 2**.

### ⛔ Je ne conclus PAS que le signal est mort

Le barreau `DECALAGE` **n'est pas un placebo valide** : le ratio
`entry_stocke / open(bougie après la barre)` n'est pas un attribut du temps ni
de la bougie, c'est **une décision de la production** — l'endroit où chaque
motif a choisi d'entrer. Le donner au placebo lui transfère potentiellement de
l'**information réelle**.

### ⚠️ Et je ne conclus PAS non plus qu'il vit

L'autre lecture est tout aussi possible, et plus déflationniste : **l'écart
n'aurait jamais porté sur l'INSTANT, mais sur l'ENDROIT dans la barre où l'on
entre.** Les placebos uniforme et réseau n'en avaient pas, donc ils
paraissaient mauvais. Dans cette lecture, `t = +1,600` est le bon chiffre et
**l'instant ne porte presque rien**.

⇒ 🔴 **LA RÉPLICATION DU `5min` EST DÉSORMAIS EN DOUTE.** Je ne la retire pas —
je n'ai pas de quoi — mais je ne peux plus l'affirmer.

### ⛔ Et ce constat est HORS de ma pré-inscription

Mon critère ne branche que sur `ρ`. L'effondrement de l'écart n'était **prévu
par aucune de mes cinq prédictions**, donc je ne le range **ni** du côté de
l'admission **ni** de celui du rejet, et je **ne réécris pas** le critère pour
l'y faire entrer. Il devient une **question neuve, à pré-inscrire**.

## 🔬 LE TEST QUI TRANCHE, et il est simple

**Permuter les ratios entre setups** (au hasard, à effectif et paire
conservés), puis rejouer le barreau.

- Si l'écart **reste petit** avec des ratios permutés ⇒ la valeur des décalages
  est **STRUCTURELLE** (leur distribution, leur taille devant le risque), pas
  informationnelle ⇒ **lecture déflationniste** : l'instant ne porte presque
  rien, et `t = +1,600` doit être pris au sérieux.
- Si l'écart **remonte vers +0,092** ⇒ c'est l'**appariement ratio ↔ setup** qui
  compte, donc de l'**information réelle** a été transférée au placebo ⇒
  **lecture de contamination** : le barreau `DECALAGE` est invalide et le `t`
  défendable reste ≈ +4,58.

🔑 **C'est un test par permutation sur une quantité que je contrôle entièrement,
et il distingue les deux lectures sans ambiguïté.** Il sera pré-inscrit avant
d'être écrit.

## Où en est la réplication du `5min`

| étape | `t` | état |
|---|---|---|
| placebo uniforme (`c5c68dc`) | +4,32 | publié |
| barreau apparié brut (`2613282`) | ~~+5,60~~ | retiré en `8935497` |
| corrigé du `ρ` réel (`8935497`) | **+4,58** | ✅ son hypothèse de variance est **vérifiée ici** |
| barreau à décalages (ici) | **+1,600** | 🔴 **ni validé ni écarté** |

⛔ **Et dans tous les cas ça ne paie pas** : à +0,0231 R comme à +0,0905 R,
l'écart reste **sous le coût de 0,0950 R**, et l'espérance nette vaut
**−0,0593 R**.

## ⚠️ Limites

- **Hors échantillon seulement** (4 280 lignes, 7 paires crypto).
- Le ratio est calculé contre `open(bougie après la barre)` — **une** référence
  parmi d'autres, et je n'en ai testé **qu'une**.
- L'**espacement** entre instants reste non testé (placebo par blocs).
- 🔴 **L'asymétrie résiduelle** (bornes d'août, bougies du jour) pèse ici plus
  que partout ailleurs : c'est le candidat principal pour expliquer le tiers de
  `ρ` encore manquant.

🛑 **Je ne propose pas de réarmer l'IA.** REM-002 reste `DISARMED_MANUALLY`.
