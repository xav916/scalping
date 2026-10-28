# ⛔ CORRECTION du verdict `9d955dc` — j'ai publié une cause FAUSSE

**Écrit le 2026-10-28, après `9d955dc`.** Le verdict corrigé **reste au dépôt**
tel quel : il est faux sur un point central et il faut que ça se voie.

## Ce que j'ai écrit, et qui est FAUX

> « **15,9 %** des setups ont leur fenêtre de 240 h au-delà de la dernière
> bougie chargée […] **L'espérance publiée du `1d` n'a jamais été
> reproductible** : elle dérive avec la frontière de données, **17,4 % en un
> jour**. […] C'est exactement le défaut que la borne de chargement a été
> introduite pour corriger. »

🔴 **Faux.** Mesuré depuis :

```
bras reel STOCKE EN BASE (pnl_pct_net) : -0,064062   <- la reference publiee, A L IDENTIQUE
bras reel RECALCULE sur les bougies    : -0,052925   <- ce que MON banc mesurait
desaccord d issue : 16 / 1362 = 1,2 %, et les 16 sont des SL -> TIMEOUT
```

À `risk_pct` médian **9,326 %**, basculer 16 `SL` (−1 R) en `TIMEOUT` (une
fraction de R) déplace la moyenne de `16/1362 × ≈0,95 = **+0,0112 R**` —
**exactement** les +0,011137 observés. La cause est **entièrement** expliquée.

## 🔴 La vraie cause : une faute de PROVENANCE, et elle est de moi

Le critère `1d` (`2026-10-27-esperance-1d.md`) **n'a pas de
`source_bras_reel`**, donc le banc publié a pris la valeur par défaut
**`STOCKE`** : il a lu les `pnl_pct_net` **de la base**.

Mon banc de décomposition, lui, nomme son premier bras « STOCKE » mais
**recalcule l'issue** sur les bougies du jour (il garde seulement la
**géométrie** d'août). ⇒ **Deux choses différentes sous le même mot**, et j'ai
comparé l'une à la référence de l'autre.

🔑 **C'est exactement la faute du 27/10** —
[[feedback_les_deux_bras_doivent_partager_leur_source]] — **refaite par moi dans
le verdict même qui la cataloguait.** Et mon étiquette y est pour beaucoup :
« STOCKE » voulait dire « géométrie stockée », pas « issue stockée ».

## Ce qui tombe, et ce qui tient

**TOMBE :**
- ⛔ « l'espérance publiée du `1d` n'est pas reproductible » ⇒ **elle l'est, à
  0,000 %**, à condition de comparer **stocké contre stocké** ;
- ⛔ « elle dérive avec la frontière de données, 17,4 % en un jour » ⇒ **aucune
  dérive temporelle n'a été démontrée** ; les deux passes voyaient la même
  donnée ;
- ⛔ « c'est le défaut que `fin_chargement` corrige » ⇒ **`fin_chargement` n'y
  change rien**. Pire : ma borne du 28/10 était posée à **21:00 UTC** alors que
  le banc tournait à **06:03 UTC** — **dans le futur, donc inopérante**. Elle
  n'a jamais mordu ;
- ⛔ et donc la recommandation « relire le verdict `1d` à la lumière de sa
  non-reproductibilité » : **sans objet**.

**TIENT :**
- ✅ **216 / 1 362 = 15,9 %** de fenêtres finissent bien au-delà de la dernière
  bougie **disponible pour leur paire** — mais c'est une limite de **couverture
  Twelve Data par paire** (`INJ/USD` s'arrête au **2026-10-18**), **pas** une
  frontière mouvante. Fait réel, **conséquence annulée**.
- ✅ **47,7 % de `TIMEOUT`** sur le `1d`.
- ✅ **L'artefact `1d` = −0,207122** : les **deux** bras de ce calcul sont
  recalculés, donc il est **interne et cohérent**. Il n'est pas touché.
- ✅ **L'échelle monotone reste RÉFUTÉE** : `+0,1385` · `−0,0107` · `−0,2071`.
- ✅ **`P4` reste un échec** (0,1014 contre `< 0,05` prédit), et la leçon du
  substitut transposé tient.
- ✅ **`P1`/`P2` passent toujours « à l'envers »**, et la leçon du seuil
  unilatéral tient.
- ✅ **La cellule `4h` reproduit** — et maintenant je sais **pourquoi** : sur le
  `4h`, recalculé et stocké coïncident presque (contre 1,2 % de désaccord sur le
  `1d` et **24,5 %** sur le `5min`).
- ✅ **Le garde-fou s'est déclenché**, et il avait raison de le faire : il a
  attrapé une incohérence **réelle**. ⛔ **Mais j'ai mal diagnostiqué ce qu'il
  avait attrapé**, et j'ai publié ce mauvais diagnostic.

## 🔑 La leçon, et elle est double

1. **Un garde-fou qui se déclenche ne dit pas POURQUOI.** Il a signalé un écart
   de 17,4 % ; j'ai attribué cet écart à la première cause plausible
   (`fin_chargement` absente) **sans la tester**, alors que la vérifier coûtait
   une requête. ⇒ **Un arrêt doit être diagnostiqué par une mesure, pas par une
   hypothèse.**
2. ⛔ **Nommer deux choses différentes du même mot finit par les confondre.**
   « STOCKE » pour « géométrie stockée, issue recalculée » était une étiquette
   fausse. Le banc sera corrigé pour exposer **trois** bras explicites :
   `ISSUE_STOCKEE`, `GEOMETRIE_STOCKEE_ISSUE_RECALCULEE`, `FILL_OUVERTURE`.

## 🔬 Ce que ça change pour la suite

⇒ **Refaire le `1d` avec `fin_chargement` n'a plus d'objet.** La bonne mesure
est un banc dont le **contrôle de reproduction porte sur le bras `ISSUE_STOCKEE`**
(qui reproduit à 0,000 %), et qui publie à côté le bras recalculé et le bras
`FILL`. C'est ce qui sera pré-inscrit.

🔴 **Et la question de fond reste entièrement ouverte** : l'artefact `1d` de
**−0,207** et l'écart `FILL` de **+0,113** (`t +4,52`) sont **inchangés** par
cette correction. Si le `1d` et le `5min` échangent bien leurs places selon la
spécification d'exécution, **aucune des deux conventions ne démontre quoi que ce
soit** — et c'est cela qu'il faut trancher, avec un contrôle de reproduction qui
tient.
