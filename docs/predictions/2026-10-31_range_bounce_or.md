# Le retour à la moyenne sur l'or a-t-il rapporté ? — pré-inscription du 2026-10-31

**Question de Xavier :** le trading auto fera-t-il du retour à la moyenne ?
La réponse factuelle est qu'il en **faisait déjà** : `range_bounce_up` et
`range_bounce_down` sont les 2ᵉ et 3ᵉ motifs les plus poussés sur `XAU/USD`,
**85 poussées sur 298**, soit 28,5 %.

Reste la vraie question, qui n'a jamais été mesurée : **est-ce que ça a
rapporté ?**

## La source, et pourquoi celle-là

`mt5_pushes` ⋈ `broker_close_snapshots` sur `ticket`. **298 poussées
joignables sur 298**, dont **85 `range_bounce`** contre **213 autres motifs**.

🔑 On prend **`pnl_net`**, net de swap, commission et frais — jamais `pnl`.
Le verdict le plus solide de ce dépôt est que le coût mange l'avantage
(`le SPREAD est la perte`, et le coût réel de l'or mesuré au tick porte le
manque à **1,29 pt**). Un rendement brut dirait l'inverse du net.

⛔ Sources écartées, et pourquoi : `ea_closed_trades` ne contient **qu'une
ligne** (0 sur l'or) — ce n'est pas la table des clôtures, contrairement à ce
que son nom suggère. `personal_trades` en a 639 clôturées dont 106
`range_bounce`, mais ne porte pas les frais séparément.

## Critère

<!-- CRITERE-MACHINE
admission: t > +2 et moyenne_nette_eur > 0 et bat_plafond_permutation
rejet: t < -2
validite: part_pnl_net_manquant < 0.02
cellules: 3
plafond: permutation_p95
-->

- **Grandeur mesurée :** `pnl_net` moyen par trade, en euros.
- **Comparaison :** les trades `range_bounce` contre **tous les autres
  motifs**, sur la même paire et la même période. Les autres motifs sont le
  témoin : ils ont subi le même coût, le même courtier, le même régime.
- **Les 3 cellules**, déclarées avant de regarder :
  1. `range_bounce*` (n=85) contre les autres (n=213) ;
  2. `range_bounce_up` (n=50) contre les autres ;
  3. `range_bounce_down` (n=35) contre les autres.
- **Plafond :** 200 permutations de l'étiquette de motif, p95 du `t` obtenu.
  ⛔ Exigé parce que `cellules > 1` : le 14/10, **sept** cellules passaient à
  `t = 2`, et le hasard seul en fait passer autant.
- **Admission :** il faut les **trois** conditions. Une moyenne positive sans
  `t` ne vaut rien, et un `t` qui ne bat pas le plafond ne vaut rien non plus.
- **Validité :** le rejeu est invalide si plus de 2 % des trades joints n'ont
  pas de `pnl_net`. Un échantillon amputé en silence ne juge rien.

⚠️ Ce que ce banc **ne peut pas** dire : il mesure ce que `range_bounce` a
rapporté **tel qu'il a été exécuté**, pas ce qu'une stratégie de retour à la
moyenne rapporterait. Les trades ont subi les garde-fous, le plafond de lot et
la gestion de sortie de l'époque. Ce n'est pas un backtest de règle.

## Prédictions

Écrites **avant** d'exécuter quoi que ce soit, et chacune falsifiable.

1. **P1_moyenne_nette_negative** — le `pnl_net` moyen par trade `range_bounce`
  sera **négatif**. Raison : le coût réel de l'or mesuré au tick est de
  **1,29 pt**, et aucun motif n'a jamais montré d'avantage qui le dépasse.
  *Fausse si la moyenne nette est ≥ 0.*

2. **P2_indiscernable_des_autres_motifs** — `|t| < 2` sur la cellule 1 :
  `range_bounce` ne sera **pas distinguable** des autres motifs. Raison : la
  direction a été réfutée **quatre fois** par quatre chemins indépendants, et
  le score ne prédit pas. *Fausse si |t| ≥ 2.*

3. **P3_une_cellule_passera_par_hasard** — **au moins une** des 3 cellules
  montrera `|t| > 2`, et elle **ne battra pas** le plafond par permutation.
  Raison : c'est exactement ce qui s'est produit le 14/10 avec sept cellules.
  *Fausse si aucune cellule n'atteint |t| > 2, ou si celle qui l'atteint bat
  aussi le plafond.*

4. **P4_le_sens_haussier_ne_sera_pas_meilleur** — l'écart entre
  `range_bounce_up` et `range_bounce_down` sera **inférieur à 2 € par trade**
  en valeur absolue. Raison : les bornes symétriques ont donné **49,83 %** sur
  64 062 détections. *Fausse si l'écart dépasse 2 €.*

## Ce qui sera publié, et ce qui ne le sera pas

⛔ Aucun chiffre ne sort avant `or-verdict`. Et **aucun majorant** : le 13/10,
« la protection a évité 642 € » était faux **de signe**, et la méthode
l'interdisait déjà.

Si le banc admet, cela ne réarme rien : l'IA de trading est coupée
(REM-002 `DISARMED_MANUALLY`), et le réarmement demande une décision humaine
explicitement nommée.
