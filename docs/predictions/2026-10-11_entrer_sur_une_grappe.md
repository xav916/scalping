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
