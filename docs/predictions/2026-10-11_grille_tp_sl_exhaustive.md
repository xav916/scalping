# Existe-t-il un couple TP/SL gagnant sur l'or ? — la grille complète

**Déclaré le 2026-10-11, AVANT de mesurer.** Demande de Xavier : « je veux que
tu trouves le juste couple TP/SL qui soit au max gagnant sur l'or ».

## Ce que je sais déjà, et pourquoi je le mesure quand même

L'arithmétique dit qu'aucun couple ne peut gagner : sur une marche sans dérive,
`P(toucher +a avant −b) = b/(a+b)`, donc l'espérance vaut **exactement zéro**
pour tout `(a,b)`, et **−spread** une fois le coût payé. Vérifié hier sur six
couples, sur une plage de produits `a×b` de **1 à 100** : le taux obtenu collait
au taux requis à chaque fois.

⇒ Mais un argument n'est pas une mesure, et Xavier a droit à la **surface
entière** plutôt qu'à ma démonstration. Sur une fenêtre finie, il y aura
**toujours** un couple qui paraît le meilleur — c'est précisément ce que le
hors échantillon existe pour tuer.

## La grille

    TP (EUR) : 1   1,5   2   3   4   5   7   10   15   20
    SL (EUR) : 1   1,5   2   3   4   5   7   10   15   20   30   40

⇒ **120 couples.** Plafond du hasard du laboratoire à 120 cellules :
**|t| > 2,80** (interpolé entre 96 → 2,730 et 128 → 2,829).

## Les données

Magasin **du courtier** bâti hier (`candles_courtier.db`) : **99 750 bougies
M5**, du **2025-05-14** au **2026-10-09** — 17 mois, vérifié à 97/97 ancres
d'exécution et dont la coupure hebdomadaire reproduit l'horaire réel du marché.

⚠️ **Limite déclarée** : granularité **M5**. Une bougie de 5 minutes peut
contenir l'objectif ET le stop ; dans ce cas **on prend le stop**. Cela
**sous-estime** la fréquence des touches pour les petites bornes, et je le dis
plutôt que de le découvrir après.

## Les entrées : systématiques et SANS direction supposée

🔑 Pour mesurer **le couple** et non une entrée, les entrées doivent être
aveugles : **une toutes les 12 bougies M5** (donc une par heure), **dans les
deux sens**.

Et je publie **deux panneaux**, parce qu'ils ne répondent pas à la même
question :

1. **PANNEAU NEUTRE** — achat **et** vente au même instant. L'exposition
   directionnelle est nulle, donc la dérive s'annule : ce panneau montre le
   **coût pur** de chaque couple. C'est l'arithmétique rendue visible.
2. **PANNEAU DIRECTIONNEL** — tous les achats d'un côté, toutes les ventes de
   l'autre. C'est là qu'un « meilleur couple » apparaîtra, parce qu'il
   **récolte la dérive** de la période.

## ⛔ LE CRITÈRE, POSÉ AVANT DE REGARDER

Un couple est retenu s'il réunit **les quatre** :

1. P&L par trade **> 0** sur la **seconde moitié** de la période
   (hors échantillon — la première moitié sert à le désigner) ;
2. **|t| > 2,80** hors échantillon, l'unité étant **le JOUR** ;
3. **n ≥ 500** trades hors échantillon ;
4. le **signe** du P&L identique en échantillon **et** hors échantillon.

⇒ Et une condition de méthode : **le couple est désigné sur la première
moitié, puis jugé sur la seconde.** Je ne choisirai pas le meilleur de la
période entière — ce serait exactement l'erreur que ce document existe pour
éviter.

## MA PRÉDICTION, POSÉE MAINTENANT

1. ✅ Le **panneau neutre** donnera **−spread** partout, à la marge
   d'échantillonnage près, sur les 120 couples.
2. ⚠️ Le **panneau directionnel** fera apparaître un « meilleur couple » en
   échantillon, avec des chiffres qui auront l'air bons.
3. ⛔ Et **ce couple ne se répliquera pas** hors échantillon : **0 couple
   retenu sur 120**.

⇒ Si un couple passe les quatre critères, ma prédiction est **réfutée** et
c'est la première chose exploitable de tout ce chantier.

## Ce que cette mesure ne tranche PAS

- Rien sur une **entrée informée** : les entrées sont volontairement aveugles.
  Un couple optimal pour un signal donné dépendrait de l'horizon de ce signal.
- Rien en dessous de **5 minutes** de granularité.
- Rien sur le **réemploi de la marge** ni sur le nombre de positions.
