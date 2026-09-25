# Pré-enregistrement — `sweep_avec_biais_haussier` hors échantillon

**Date :** 2026-09-25
**Track :** hors-track
**Numéro d'expérience :** preenr-1
**Statut :** `declared` (aucune mesure lancée à l'écriture de cette entrée)

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

À remplir **après** la mesure, sans toucher à ce qui précède.
