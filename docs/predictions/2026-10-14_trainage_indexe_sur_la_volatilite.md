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

---

# VERDICT, le 2026-10-14 : LA LARGEUR PAIE, L'INDEXATION NON

3 682 189 ticks, 18 jours, 4 669 positions fixes, `k` calibrés sur la
**première moitié**.

## ✅ ① L'HYPOTHÈSE ÉTAIT JUSTE : le traînage était bien trop serré

```
                   largeur   gain moyen   vs A     reussite
A production        0,339      +0,602       -        78,7 %
B x2 (vol 5 min)    0,679      +0,976     +62,3 %    71,8 %
B x3                1,018      +1,304    +116,8 %    65,8 %
```

**Élargir le traînage DOUBLE le gain moyen** (+0,602 → +1,304 €), et ça se
reproduit hors échantillon (+1,247). ✅ Prédiction n°1 tenue, et largement —
je prédisais +40 %, c'est **+117 %**.

🔑 Le mécanisme annoncé était le bon : à `2 × spread ≈ 0,34 €`, le traînage
vivait **dans le bruit d'une minute** (amplitude 15 min = 6,30 €, soit
~0,42 €/min). Il encaissait dès que le marché respirait.

## ⛔ ② MAIS LA RÉUSSITE S'EFFONDRE, exactement comme prédit

```
A 78,7 %  ->  B x2 71,8 %  ->  B x3 65,8 %      (-12,9 points)
```

✅ Prédiction n°2 tenue (je prédisais ≥ 10 points).

## 🔑 ③ ET LA PRÉDICTION QUI DÉCIDE — n°4 — TIENT, plus fort que prévu

Le témoin `D` (simplement **plus large**, sans indexer sur rien) :

```
             gain moyen    vs A       ecart net /jour
B x3 (vol)     +1,304    +116,8 %        -0,0630
D x3 (large)   +1,237    +105,6 %        -0,0167     <- MIEUX que B
```

⇒ **Élargir sans indexer obtient presque tout le gain, et abîme deux fois
moins le net.** La condition 3 (« battre son témoin ») échoue pour **5 cellules
sur 6**.

🔑 **L'indexation sur la volatilité n'apporte RIEN ici — elle est même nuisible.**
Et la raison était mesurée ce matin : **l'amplitude passée ne prédit pas
l'amplitude future** (`r = +0,020`). Indexer sur un bruit ajoute du bruit.

⚠️ Contraste instructif avec la trouvaille du matin : la **vitesse** du
mouvement adverse battait son témoin (+31 % contre +13 %), la **largeur** du
traînage ne bat pas le sien. La volatilité porte donc quelque chose **sur
l'instant où l'on réagit**, rien **sur la distance où l'on se place**.

## ⛔ ④ ET LE NET NE S'AMÉLIORE JAMAIS

Aucune cellule ne passe `t > +2`. Et ma prédiction n°3 est **partiellement
fausse** : je disais « le net ne bougera pas, `|t| < 2` partout ». En réalité
`B x1/x2/x3` et `C x2` sont **significativement PIRES** en échantillon
(`t` de −2,00 à −2,11) — puis le signe **s'inverse** hors échantillon. Donc
pas « plat » : du bruit de forte amplitude.

## MES PRÉDICTIONS : 4 sur 5

| n° | prédiction | verdict |
|---|---|---|
| 1 | le gain moyen montera de ≥ 40 % à 3× | ✅ **+117 %** |
| 2 | la réussite chutera de ≥ 10 points | ✅ **−12,9 points** |
| 3 | le net ne bougera pas, `\|t\| < 2` partout | ⚠️ direction juste (aucun gain) mais 4 cellules sont **significativement pires** dedans |
| 4 | `D` fera aussi bien que `B` et `C` | ✅ **et même mieux sur le net** |
| 5 | gain moyen et réussite sont les deux faces d'une pièce | ✅ **+117 % de gain pour −12,9 points, net inchangé** |

## ⇒ LA RÉPONSE À XAVIER

**La volatilité ne sert à la sortie que par la VITESSE du mouvement adverse**
(trouvée ce matin : queue −31 %, et elle battait son témoin). **Pas par la
largeur du traînage** : là, c'est la largeur seule qui agit, et l'indexer
dégrade.

🔑 **Mais ce banc a produit un choix réel, et chiffré.** Un traînage simplement
plus large change complètement le profil des trades, **à net identique** :

```
                  reussite    gain moyen   perte moyenne   net
A production (aujourd hui)  78,7 %   +0,60      -2,55       reference
D x2 (trainage double)      71,8 %   +0,93      -2,62       -0,005  (t -0,36)
D x3 (trainage triple)      66,4 %   +1,24      -2,69       -0,017  (t -0,72)
```

Deux tiers de réussite avec des gains deux fois plus gros, ou quatre cinquièmes
de réussite avec des petits gains : **le même argent, une expérience tout
autre**. C'est son choix, pas une mesure — et il n'y a **aucun gain de
rendement** à la clé, je le dis avant qu'il ne le demande.
