# Gérer la SORTIE par la volatilité : le traînage est-il trop serré ?

**Déclaré le 2026-10-14, AVANT d'écrire la mesure.**

Xavier : *« par rapport à la volatilité, comment peut-on gérer la sortie d'un
trade ? »*

## CE QUE LA JOURNÉE A DÉJÀ ÉTABLI

| mesuré aujourd'hui | résultat |
|---|---|
| volatilité **avant** l'entrée → perte du trade | `r = +0,020`, `t = +1,38` ⇒ **rien** |
| volatilité **avant** → sens | plafond 3,758, max 3,605 ⇒ **rien** |
| volatilité **avant** → quand ouvrir | non monotone, signe s'inverse ⇒ **rien** |
| **vitesse du mouvement PENDANT** le trade → queue | **−31 % / −27 %**, robuste |

🔑 **La volatilité ne dit rien de l'entrée et quelque chose de la sortie.** La
différence est l'instant de mesure : avant le trade, elle est muette ; sur le
trade en vol, elle porte.

## 🔑 L'HYPOTHÈSE, et son mécanisme chiffré

Toute la journée a attaqué le **côté perte**. Or le déséquilibre mesuré le
12/10 est :

```
83 gagnants a +0,623 EUR    contre    41 perdants a -1,708 EUR
```

Le gain moyen est **petit**. Et le traînage qui l'encaisse vaut
**`2 × spread ≈ 0,37 €`** — or le spread est quasi **plat** de 00h à 19h UTC,
donc ce traînage **ne s'adapte à rien**.

⚠️ Et voici le chiffre qui motive ce banc : l'amplitude médiane sur 15 min
vaut **5,76 €**, soit ~**0,38 €/minute** de bruit normal. **Le traînage est
donc de l'ordre du bruit d'UNE minute.** Il encaisse un gagnant dès que le
marché respire — pas quand le mouvement s'épuise.

⇒ **Hypothèse : le traînage est trop serré, et il l'est d'autant plus que le
marché est agité.**

## Les cellules — largeur du TRAÎNAGE

| | largeur du traînage | s'adapte à |
|---|---|---|
| **A** | `2 × spread` — **production** | le coût (quasi constant) |
| **B** | `k × amplitude(5 min)` | la volatilité **rapide** |
| **C** | `k × amplitude(15 min)` | la volatilité **lente** |
| **D** | ⛔ **TÉMOIN : `m × spread`**, `m` choisi pour la même largeur médiane que `B` | rien — **juste plus large** |

🔑 **`D` est le cœur du protocole**, et c'est ce témoin qui a rendu crédible la
trouvaille de la vitesse ce matin. Si élargir **sans** indexer fait aussi bien,
alors la volatilité n'apporte rien et seule la largeur comptait.

`k` calibré pour que `B` et `C` aient la **même largeur médiane** — ici
**délibérément PLUS LARGE que A**, puisque l'hypothèse est que A est trop
serré. Je teste **trois niveaux** : médiane à **1×, 2× et 3×** celle de A.

Tout le reste reprend la production : stop initial 0,35 %, protection à la
minute, plancher `2 × spread`, aucun objectif, coût réel, population **FIXE**.

## ⛔ LE CRITÈRE

Une cellule remplace A **si et seulement si** :

1. l'écart de rendement est **significativement positif**, `t > +2,0` sur
   l'unité JOUR ;
2. **et** le signe survit **hors échantillon** (`k` calibré sur la première
   moitié seulement) ;
3. **et** elle **bat son témoin `D`** à largeur médiane égale — sinon l'effet
   est la largeur, pas la volatilité.

⚠️ 3 cellules × 3 niveaux = 9 comparaisons. Je ne retiendrai rien sur un `t`
isolé, et la condition 3 est non négociable.

🔑 **Et la mesure que je regarderai même si rien ne passe** : le **gain moyen
des gagnants**. C'est la grandeur que ce banc cherche à déplacer. Si elle monte
franchement sans que le net bouge, ça dit où est le mur.

## MES PRÉDICTIONS, posées avant de coder

1. ✅ **Le gain moyen des gagnants AUGMENTERA** avec la largeur, nettement :
   je prédis **+40 % ou plus** au niveau 3×. Mécanisme direct — on arrête de
   couper dans le bruit d'une minute.
2. ⛔ **Mais la RÉUSSITE chutera** d'au moins **10 points**, parce qu'un
   traînage large rend ce qu'il laissait courir. C'est le compromis
   symétrique de celui de la vitesse.
3. ⛔ **Et le NET ne bougera pas** : `|t| < 2` partout. Prior : tout ce qui a
   été testé aujourd'hui nette à zéro, et le 12/10 le traînage à `2 × spread`
   était déjà indistinguable du traînage fixe à 0,50 €.
4. 🔑 **`D` (plus large sans indexer) fera AUSSI BIEN que `B` et `C`** — c'est
   ma prédiction qui décide. Contrairement à la vitesse, je ne vois pas de
   mécanisme qui rende l'indexation supérieure ici : le traînage suit déjà le
   prix, et l'amplitude passée ne prédit pas l'amplitude future (c'est la
   leçon du banc de ce matin, `r = +0,020`).
5. ⚠️ **Si 1 et 3 tiennent ensemble**, la conclusion sera dure mais nette :
   **le gain moyen et la réussite sont les deux faces d'une même pièce**, et
   aucun réglage de sortie ne les déplace tous les deux dans le bon sens.
   Ce serait la quatrième fois de la journée.

⇒ Si 4 tient, la réponse à Xavier sera : **la volatilité ne sert à la sortie
que par la VITESSE du mouvement adverse** — ce qu'on a déjà trouvé ce matin —
**et pas par la largeur du traînage**.
