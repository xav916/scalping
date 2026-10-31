# Le retour à la moyenne sur l'or — pré-inscription n°2, fenêtre INÉDITE

## Pourquoi une deuxième pré-inscription

La première (`2026-10-31_range_bounce_or.md`) a été **perdue sur la forme** :
son `admission` écrivait ` et ` en minuscules et portait une clause sans
opérateur, donc `or-verdict` n'a pas pu l'appliquer — après que le banc avait
tourné.

⛔ **Les chiffres de cette première fenêtre ont été vus.** Rejouer le même
échantillon avec un critère réparé serait pré-inscrire en connaissant le
résultat. Cette fenêtre est donc **brûlée**, définitivement.

Le correctif de forme est maintenant dans `or-preinscription`, qui refuse à
l'entrée ce que `or-verdict` refuserait à la sortie.

## La fenêtre, et la preuve qu'elle est inédite

`personal_trades`, trades `CLOSED` sur l'or, **dont le ticket n'apparaît pas**
parmi les 298 déjà mesurés :

- **98 trades inédits**, du **2026-05-26** au **2026-09-16** ;
- dont **29 `range_bounce`** et **69 autres motifs** (le témoin).

Seuls leurs **comptes** ont été regardés. Aucun rendement n'a été calculé sur
cette tranche.

## ⚠️ Deux faiblesses déclarées AVANT de mesurer

1. **Le rendement y est BRUT.** `personal_trades` ne sépare pas swap,
   commission et frais, contrairement à `broker_close_snapshots`. Or le
   verdict le plus solide de ce dépôt est que le coût mange l'avantage (coût
   réel de l'or au tick : **1,29 pt**). ⛔ Une admission sur du brut **n'est
   pas** une admission sur du net, et ne sera jamais présentée comme telle.

2. **n = 29 est petit.** La puissance est faible : un résultat nul ne
   démontrera **pas** une absence d'effet, seulement l'incapacité de cette
   fenêtre à le voir. C'est écrit ici pour ne pas être redit après coup.

## Critère

<!-- CRITERE-MACHINE
admission: t > 2 ET moyenne_brute_eur > 0 ET t_abs > plafond_p95
rejet: t < -2
validite: part_pnl_manquant < 0.02 ET n >= 25
cellules: 1
plafond: permutation_p95
-->

- **Grandeur :** `pnl` moyen par trade, en euros, **brut**.
- **Témoin :** les 69 trades inédits des autres motifs, même période, même
  instrument, même courtier — ils ont subi le même coût.
- **Une seule cellule.** Avec n=29, découper par sens donnerait deux
  sous-échantillons incapables de rien dire. ⛔ En ajouter après coup serait
  du p-hacking.
- **Plafond :** p95 de `|t|` sur 200 permutations de l'étiquette de motif,
  graine 42. Conservé bien que `cellules = 1` : il coûte peu et il a déjà
  réfuté sept cellules le 14/10.
- **Admission :** les **trois** clauses. Une moyenne positive sans `t` ne vaut
  rien ; un `t` qui ne bat pas le plafond non plus.
- **Validité :** moins de 2 % de `pnl` manquants **et** au moins 25 trades
  dans le bras réel. Sous 25, on ne juge pas.

## Prédictions

Écrites avant d'exécuter. ⚠️ Mes priors sont **informés** par la première
fenêtre, dont j'ai vu les chiffres : ces prédictions sont donc moins
risquées qu'elles n'y paraissent, et je le déclare.

1. **P1_moyenne_brute_sous_deux_euros** — la moyenne brute par trade
   `range_bounce` sera **inférieure à +2 €**. Raison : même en brut, aucun
   motif n'a montré d'avantage dépassant le coût de l'or.
   *Fausse si la moyenne brute est ≥ +2 €.*

2. **P2_indiscernable_du_temoin** — `|t| < 2` : `range_bounce` ne sera pas
   distinguable des autres motifs. Raison : la direction a été réfutée quatre
   fois par quatre chemins indépendants. *Fausse si |t| ≥ 2.*

3. **P3_ne_bat_pas_le_plafond** — `|t|` ne dépassera **pas** le p95 par
   permutation. Raison : c'est le témoin qui a réfuté sept cellules le 14/10.
   *Fausse si |t| > plafond.*

4. **P4_la_fenetre_est_trop_petite_pour_trancher** — la demi-largeur de
   l'intervalle à 95 % sur la moyenne du bras réel **dépassera 2 €**, donc la
   fenêtre ne pourra pas résoudre un effet de la taille du coût de l'or.
   Raison : n=29 avec la dispersion observée sur l'or. *Fausse si la
   demi-largeur est ≤ 2 €.*

## Ce qui sera publié

⛔ Rien avant `or-verdict`. Aucun majorant. Et si le critère admet, il admet
sur du **brut**, sur **29 trades**, sur une période **passée** — pas une
raison de réarmer quoi que ce soit. L'IA de trading reste coupée
(REM-002 `DISARMED_MANUALLY`) et son réarmement demande une décision humaine
explicitement nommée.
