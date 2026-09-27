# Pré-enregistrement — `sweep_avec_biais_haussier` hors échantillon

**Date :** 2026-09-25
**Track :** hors-track
**Numéro d'expérience :** preenr-1
**Statut :** `closed-negative` (réfutée le 2026-09-25, après le commit de la déclaration)

---

## ⛔ Cette entrée est écrite AVANT la mesure, et c'est tout son intérêt

La chaîne `chaine:sweep_avec_biais_haussier` est **armée sur l'argent réel**
(porte des frais levée, `CHAINES_AUTORISEES`, réarmée le 2026-09-22 04h11).
Sa mesure en échantillon est positive et reproductible mais `INSUFFISANT` :

| or 5 min, nuit du 2026-09-25 | n | R moyen | t vs hasard | plafond |
|---|---|---|---|---|
| `chaine:sweep_avec_biais_haussier` | 141 | +0,1664 | 2,58 | 3,668 |
| `liquidity_sweep_up` seul | 367 | −0,0777 | 0,88 | 3,668 |

Le plafond de 3,668 est le prix de **2 492 cellules** mesurées chaque nuit. Une
cellule **pré-enregistrée seule** ne paie pas ce prix : k=1. C'est la seule
façon honnête de faire compter un 2,58 — et elle exige que la fenêtre, la
barre et la cellule soient fixées **avant** de regarder le résultat.

## Ce qui est figé ici, et ne changera pas

| élément | valeur |
|---|---|
| cellule | `chaine:sweep_avec_biais_haussier`, sens `buy` |
| instrument arbitré | **XAU/USD** |
| échelle | **5 min** uniquement (`echelles=(1,)`) — c'est ce qui est armé |
| fenêtre hors échantillon | **2025-06-27T00:00Z → 2026-06-27T00:00Z** (365 j) |
| code de mesure | `laboratoire_or.mesurer()` tel que déployé, sans modification |
| contrôle | contrôle aléatoire **par sens** (`ae8e210`), effectif depuis le 21/09 |

🔑 **Pourquoi cette fenêtre.** Le laboratoire sélectionne sur `LABO_OR_JOURS=90`
jours glissants, soit 2026-06-27 → 2026-09-25. La fenêtre ci-dessus s'arrête
**exactement** où celle-là commence : aucun recouvrement, et elle n'a jamais
servi à retenir cette cellule.

## La barre — fixée maintenant

`RETENU` exige les **trois** conditions, aucune négociable :

1. `r_moyen > 0`
2. écart au hasard de son propre sens `> 0`
3. **`t_vs_hasard >= 2,0`** (k=1, bilatéral ~95 %)

**Puissance déclarée avant mesure :** σ ≈ 1,39 R en échantillon ; pour t=2 sur
un écart de 0,31 R il faut n ≈ 82. La fenêtre de 365 j doit rendre n ≈ 570.
⇒ Si `n < 82`, le verdict est **`non concluant`**, et non « à refaire ailleurs ».

## Ce que la réfutation déclenche

Si l'une des trois conditions manque : **l'armement n'est pas mérité.**
Recommandation alors portée à Xavier : retirer cette chaîne de
`CHAINES_AUTORISEES`, ce qui referme la porte des frais sans toucher à aucune
autre garde.

⛔ Aucune variante de secours n'est autorisée : ni autre fenêtre, ni autre
échelle, ni barre abaissée, ni « mais le signe est bon ». Élargir après coup
est exactement la faille auto-référentielle du 16/09.

## Mesure SECONDAIRE, qui ne décide rien

La même cellule sur **XAG/USD**, même fenêtre. En échantillon l'argent
contredit l'or (−0,1669 sur n=229, contexte n'apportant rien : −0,011).
Elle est déclarée **descriptive** : elle ne peut ni sauver ni condamner le
verdict de l'or. Elle sert à savoir si la contradiction persiste.

## Deux limites assumées, écrites avant de voir le résultat

1. **Le spread est celui du courtier aujourd'hui**, appliqué à une fenêtre
   2025-2026 — c'est la convention du laboratoire. Il est appliqué à
   l'identique à la chaîne **et** au contrôle aléatoire : il ne peut pas
   fabriquer l'écart, seulement décaler les deux ensemble.
2. La règle de la chaîne (facteur de biais 8, fenêtre 50) a été déclarée le
   2026-09-14 et corrigée le 2026-09-20. Ces choix n'ont pas été réglés sur la
   fenêtre ci-dessus, mais ils n'ont pas non plus été tirés au sort : le
   facteur 8 est réutilisé d'un concept antérieur.

## Résultat

**Statut : `closed-negative` — la prédiction est RÉFUTÉE.**

Mesure lancée après le commit du pré-enregistrement, dans le conteneur, sur
`laboratoire_or.mesurer()` non modifié. Or : **70 870 bougies**,
2025-06-27T00:00Z → 2026-06-26T20:55Z, **0 fenêtre manquante**, spread 0,19.

### La cellule arbitrée — XAU/USD 5 min, sens acheteur

| | n | R moyen | écart au hasard | **t vs hasard** | barre | |
|---|---|---|---|---|---|---|
| **hors échantillon** (365 j) | **502** | **+0,0101** | +0,0445 | **0,72** | 2,0 | ⛔ |
| en échantillon (90 j, 25/09) | 141 | +0,1664 | +0,3092 | 2,58 | 3,668 | ⛔ |

Les trois conditions déclarées : `r_moyen > 0` ✅ · écart `> 0` ✅ ·
**`t ≥ 2,0` ❌ (0,72)**. Une condition manque ⇒ l'armement n'est pas mérité.

### Ce n'est pas un manque de puissance — c'est une réfutation

`n = 502`, bien au-delà du `n ≥ 82` déclaré : le verdict `non concluant` ne
s'applique pas. σ mesuré 1,33 R, proche du 1,39 annoncé.

🔑 **Le test avait la puissance de voir l'effet supposé.** Si l'écart de
+0,3092 R mesuré en échantillon était réel, cette fenêtre l'aurait rendu à
**t ≈ 5,0**. Elle rend **0,72**. L'écart ne rétrécit pas un peu, il s'effondre
d'un facteur **7** — et le R moyen d'un facteur **16**, à +0,0101, soit zéro.

### Ce qui survit, et ne sert à rien

La chaîne bat encore son déclencheur *en signe* : +0,0101 contre −0,0292
(écart +0,039). Mais le déclencheur lui-même n'est qu'à +0,005 du hasard : les
deux sont du bruit. « Battre son déclencheur » était la prédiction du 14/09 ;
elle est techniquement tenue et **économiquement vide**. ⛔ Ne pas s'en servir
pour sauver l'armement : la barre déclarée porte sur le hasard, pas sur le
déclencheur.

### Mesure secondaire — XAG/USD, qui ne décide rien

70 864 bougies, même fenêtre, 0 manquante.

| XAG/USD 5 min, buy | n | R moyen | écart au hasard | t vs hasard |
|---|---|---|---|---|
| `chaine:sweep_avec_biais_haussier` | 671 | **−0,1238** | −0,0214 | −0,40 |
| `liquidity_sweep_up` seul | 1 628 | −0,1471 | −0,0448 | −1,27 |

L'argent reste négatif hors échantillon, comme en échantillon. Il ne condamne
pas l'or — il ne le sauve pas non plus.

### Ce que cela déclenche, comme déclaré

Retirer `chaine:sweep_avec_biais_haussier` de `CHAINES_AUTORISEES`. C'est un
**resserrage** : la porte des frais se referme, aucune autre garde n'est
touchée, et le geste est réversible d'une ligne.

⚠️ **Portée exacte.** Cela ne supprime pas la chaîne du détecteur : elle
continuera d'être détectée, mesurée chaque nuit et journalisée. Cela lui retire
seulement l'exemption de la porte des frais — donc le droit d'ouvrir une
position dont le stop est trop serré pour payer le spread.

⛔ Cela ne referme rien pour les autres chaînes qui ont tiré sur le réel
(`cassure_killzone_londres`, `avalement_en_premium_baissier`,
`choch_puis_fvg_baissier`) : celles-là passaient par les portes normales, sans
exemption. Le relevé du 25/09 reste ouvert pour elles.
