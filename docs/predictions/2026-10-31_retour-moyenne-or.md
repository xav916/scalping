# Le retour à la moyenne a-t-il un avantage sur l'or ?

Demandé par Xavier le 2026-10-31 : « peut-on implémenter le retour à la
moyenne maintenant dans l'outil ». Relevé en cherchant où l'implémenter :
**il est déjà implémenté, déjà armé, et muet.**

- `_detect_mean_reversion` vit à `backend/services/pattern_detector.py:1738`
  depuis bien avant cette demande : SMA-20, écart en sigmas, seuil à 2,0σ,
  plus une bougie de retournement en confirmation.
- `MT5_BRIDGE_PATTERN_OVERRIDES` l'arme sur le démo depuis le 2026-09-04 :
  BTC/USD et ETH/USD dans les deux sens, XAU/USD en `_down` seul, sur les
  sept échelles.
- `mt5_pushes` compte **zéro** push de `mean_reversion`, quand douze autres
  motifs en ont poussé entre 6 et 90.

## Ce que cette mesure ne refait PAS

⛔ **Le filtre de tendance est CLOS** (`d416e57`, 2026-10-08). Xavier a
demandé le 31/10 un garde-fou « n'émettre qu'en marché sans tendance ». C'est
mot pour mot la **piste N** du banc du filtre de tendance, pré-inscrite avec
sa condition d'abandon, et abandonnée : `N − B` passe de `t = +2,09` en
échantillon à **`t = +0,16`** hors échantillon sur 6 981 trades d'une année
jamais vue. La phrase « la tendance porte de l'information » y est
explicitement retirée comme fausse.

🔑 Cette mesure-ci ne porte donc **aucun** filtre de régime. Elle demande
quelque chose que personne n'a encore demandé proprement : le motif a-t-il,
nu, le moindre avantage.

⚠️ La seule trace existante est un artefact reconnu dans le code :
`60min mean_reversion_down` avait rendu `t = −685` sur 8 trades tous soldés au
stop — écart-type quasi nul, division par presque rien, cellule écartée par
`MIN_TRADES`. Elle ne dit rien, ni dans un sens ni dans l'autre.

## L'appareil

Le laboratoire de l'or, sans réécriture : `detections()` appelle le détecteur
**de production** et `calculate_trade_setup` pour l'entrée et le stop,
`rejouer_cellule()` rejoue en **séquentiel** (jamais deux trades ouverts),
teste le **stop avant** l'objectif dans une bougie qui contient les deux,
facture le **spread** en R et écarte les stops **placebos** (< 0,1 % du prix).

Données : `candles_courtier.db`, **99 750 bougies M5 de XAU/USD**, du
2025-05-14 au 2026-10-09. Échelles `1, 3, 6, 12` (M5, M15, M30, M60),
fenêtre de détection 50 bougies — la même que la production.

Une seule modification du code de production est nécessaire, et elle ne change
aucun comportement : `_detect_mean_reversion` reçoit un paramètre `sigma`
optionnel, **défaut 2,0**, pour que le banc balaie le seuil sans qu'une
seconde implémentation du z-score existe. Ce dépôt sait ce que coûtent deux
implémentations de la même règle.

## LE CRITÈRE, posé avant de regarder

24 cellules : 3 seuils (1,5σ / 2,0σ / 2,5σ) × 4 échelles × 2 sens. Le plafond
du hasard pour 24 cellules vaut **2,241** (`plafond_hasard(24)`, table simulée
du 2026-09-08, 40 000 tirages par point).

<!-- CRITERE-MACHINE
admission: t > +2.241 et delta_hasard > +0.02 et n >= 20
rejet: max(t) < +2.241 sur les 24 cellules
validite: non_resolus_pct < 5 et bougies_m5 >= 90000
cellules: 24
plafond: permutation_p95
-->

**Admission** — une cellule n'est RETENUE que si son `t` dépasse le plafond du
hasard **et** qu'elle bat le contrôle aléatoire de la même échelle de plus de
0,02 R **et** qu'elle compte au moins 20 trades. Les trois ensemble : battre
zéro ne suffit pas, il faut battre des entrées au hasard.

**Rejet** — si aucune des 24 cellules ne dépasse 2,241, le motif est REFUTÉ
sur l'or et il n'y a rien à desserrer ni à armer.

**Validité du rejeu** — distincte du critère : moins de 5 % de trades non
résolus (soldés de force à `MAX_BOUGIES_TENUE`), sinon les R mesurent une
liquidation forcée et pas une issue de marché ; et au moins 90 000 bougies M5
effectivement lues, sinon la fenêtre n'est pas celle annoncée.

## Les prédictions

1. Le motif se déclenche bel et bien sur l'historique : à 2,0σ, **au moins une
   échelle rend `n >= 20`**. Si c'est faux, le silence de la production vient
   du détecteur lui-même et non des portes en aval — et la suite du chantier
   change de nature.
2. **Aucune cellule n'atteint `t > +2.241`.** Je prédis le REJET. Motif de
   cette prédiction : trois fois déjà dans ce dépôt, un effet à `t ≈ 2` sur une
   seule paire en échantillon s'est évaporé (`fvg_up` +2,47 → +0,101,
   `pin_bar_down`, `sur_niveau_majeur`), et rien ici ne vient d'une théorie
   plus solide que celles-là.
3. Passer de 2,0σ à 1,5σ **multiplie `n` par plus de 2** sur chaque échelle où
   `n >= 20` à 2,0σ. L'événement 1,5σ est franchement plus fréquent que
   l'événement 2σ ; si le compte ne bouge presque pas, c'est la bougie de
   confirmation qui est la vraie contrainte, pas le seuil.
4. `delta_hasard` reste dans **[−0,05 ; +0,05]** pour toute cellule comptant
   `n >= 20` : le motif ne fait ni mieux ni pire que des entrées au hasard de
   même nombre.

## Ce que le résultat décidera

- **Une cellule admise** ⇒ on pose le seuil à cette valeur, pour cette
  échelle, et on arme — sur le démo d'abord.
- **Rejet** ⇒ on ne desserre rien et on n'arme rien de plus. Le motif reste
  où il est, et la question est close par la mesure plutôt que par l'opinion.
- **Prédiction 1 fausse** ⇒ le détecteur ne déclenche pas même sur 17 mois.
  Alors le sujet n'est pas son espérance mais sa condition, et il faudra une
  autre pré-inscription pour ça.

⛔ Dans tous les cas, l'argent réel n'est pas touché : sa liste blanche ne
porte que `range_bounce_*`, et les extras sont démo-seulement par
construction.
