# PISTE 2 — Entrer à l'instant d'une GRAPPE de publications

**Déclaré le 2026-10-11, AVANT de mesurer.**

## Pourquoi cette question est neuve

Deux résultats du jour se croisent sans s'être rencontrés :

- l'amplitude M5 de l'or fait **×1,523** (t +5,02, n=215) sur la bougie d'une
  **grappe de 5 publications ou plus** dont une High ;
- la grille des 120 couples TP/SL ne retient **rien** — mais elle a testé des
  entrées **AVEUGLES**, une par heure, jamais des entrées **conditionnées à
  cet instant**.

⇒ Un mécanisme démontré n'a donc jamais rencontré une géométrie. C'est le seul
endroit du projet où ça reste vrai.

## Ce que je mesure

Sur le magasin M5 **du courtier** (99 750 bougies, 2025-05 → 2026-10) :

- **GRAPPE** : entrée à la clôture de la bougie qui contient la publication,
  dans les **deux sens** ;
- **TÉMOIN** : entrées **appariées sur (heure UTC, jour de semaine)**, tirées
  au hasard hors de toute publication — **200 tirages**.

Cinq couples, déclarés maintenant : **2/20** (la production), **2/2**, **5/5**,
**10/10**, **20/20**. ⇒ 5 cellules.

Plafond de durée 24 h puis sortie au prix du marché ; une bougie qui contient
les deux bornes compte comme un **stop**.

## ⛔ LE CRITÈRE, POSÉ AVANT DE REGARDER

Retenu si, pour au moins un couple :

1. P&L **GRAPPE** > P&L **TÉMOIN** ;
2. |t| supérieur au **95ᵉ centile du max|t| des 200 tirages appariés** ;
3. **n ≥ 200** entrées.

## MA PRÉDICTION, POSÉE MAINTENANT

1. ⛔ **Aucun couple retenu.** Une amplitude plus grande ne crée pas de dérive :
   atteindre `+a` avant `−b` reste `b/(a+b)` quelle que soit la volatilité.
2. ✅ En revanche la **durée de résolution** sera nettement plus courte sur les
   grappes — c'est le seul effet que l'amplitude peut produire.
3. ⚠️ Et le spread sera un peu plus large à ces instants, donc le net sera
   **légèrement pire** que le témoin.

⇒ Si un couple passe, c'est la première fois qu'un mécanisme du projet devient
de l'argent.


---

# VERDICT — 2026-10-11

`scripts/banc_entrer_sur_grappe.py`. **215 instants de grappe** (≥5
publications USD dans ±5 min dont une High) dans la fenetre du magasin M5 du
courtier, 15 000 bougies propres comme univers de controle, 200 tirages
appaires (heure × jour).

## ⇒ 0 COUPLE RETENU SUR 5. Ma prediction 1 tient.

    couple      GRAPPE $   TEMOIN $     ecart        t     plafond
    TP2/SL20     -0,4211    -0,2473   **-0,1738**   -0,48    16,71
    TP2/SL2      -0,7048    -0,2769   **-0,4280**   -5,81    16,71
    TP5/SL5      -0,2708    -0,1418     -0,1290     -1,79    16,71
    TP10/SL10    -0,1949    -0,1107     -0,0841     -0,92    16,71
    TP20/SL20    -0,0646    -0,0781     +0,0135    +10,18    16,71

⇒ Quatre ecarts sur cinq sont **negatifs** : entrer sur une grappe est **pire**
que d'entrer au hasard a la meme heure. Le seul positif (TP20/SL20, +0,0135 $)
reste loin sous le plafond de permutation.

## ✅ ET MA PREDICTION 2 EST JUSTE — l'amplitude fait UNE chose, et une seule

Duree moyenne jusqu'a une borne, en bougies M5 :

    TP2/SL20    grappe **6,5**   temoin 10,8    ÷ 1,66
    TP2/SL2     grappe   1,3     temoin  2,2    ÷ 1,69
    TP5/SL5     grappe   3,5     temoin  8,5    **÷ 2,43**
    TP10/SL10   grappe  15,3     temoin 25,8    ÷ 1,69
    TP20/SL20   grappe  49,5     temoin 62,9    ÷ 1,27

🔑 Le ×1,523 d'amplitude est **reel** et il se traduit exactement en **vitesse
de resolution** : les trades se denouent **1,3 a 2,4 fois plus vite**. Il ne se
traduit **pas** en argent — ce qui est l'arithmetique annoncee : atteindre
`+a` avant `−b` vaut `b/(a+b)` quelle que soit la volatilite.

⇒ Le seul usage defendable de ce mecanisme serait donc **le temps**, pas le
rendement : liberer une place plus vite. Et la valeur de cette place est
elle-meme nulle tant qu'aucune entree n'a d'avantage.
