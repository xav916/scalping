# Carnet des concepts de trading

Un concept se **déclare ici avant d'être codé** : sa tradition, sa règle exacte,
et surtout **sa prédiction falsifiable**.

> ⛔ **Pourquoi cet ordre.** Sans déclaration préalable, on code d'abord et on
> cherche ensuite ce qu'on voulait prouver — c'est ainsi qu'on ajuste un seuil
> jusqu'à ce que ça « marche ». Une prédiction écrite avant la mesure est la
> seule qui puisse être réfutée.

Recette d'intégration : [`ajouter-un-motif.md`](ajouter-un-motif.md).

---

## États

| état | sens |
|---|---|
| 🕐 **candidat** | déclaré, pas encore codé |
| 🔬 **en mesure** | codé, détecté, le laboratoire l'observe — **jamais armé** |
| ⛔ **réfuté** | mesuré, ne bat pas le hasard. **Ne pas recoder.** |
| ✅ **retenu** | bat le plafond du hasard sur plusieurs nuits |

⚠️ Aucun concept n'a jamais atteint ✅. Sept motifs mesurés avant septembre,
**Δ = +0,004 R sur 29 000 trades**. C'est l'état normal, pas un échec du
dispositif — c'est le dispositif qui fonctionne.

---

## 🔬 En mesure

### Fair Value Gap (FVG)

- **Tradition** : ICT / Smart Money Concepts.
- **Règle** : haussier si `bas[3] > haut[1]` — un trou non recouvert sur trois
  bougies. **Aucun seuil.**
- **Prédiction falsifiable** : le prix retrace dans la zone du trou, puis repart
  dans le sens de l'impulsion.
- **Motifs** : `fvg_up` · `fvg_down` — 9,2 % / 9,6 % des fenêtres.
- **Posé** : 2026-09-09 (`4de0f36`).

### Gap classé par la troisième bougie

- **Tradition** : règle de Xavier, ni ICT ni classique. Le *breakaway gap* de
  Edwards & Magee exige un **vrai saut de prix** — mesuré : sur l'or 5 min,
  **100 %** des bougies ouvrent à côté de la clôture précédente (écart médian
  0,24 USD). « Vrai gap » n'est donc pas une catégorie exploitable ici, et un
  seuil choisi à la main serait un degré de liberté de plus.
- **Règle** : après une bougie d'impulsion (corps > 0,5 × ATR), la 3ᵉ bougie
  classe : clôture **dans** la 2ᵉ → `gap_retrace_*` ; **au-delà** →
  `gap_breakaway_*`. **Exclusifs** par construction.
- **Prédiction falsifiable** : `retrace` revient dans la zone avant de repartir ;
  `breakaway` continue sans retracer. ⇒ leurs R moyens doivent **différer**.
- **Motifs** : 6,8 % à 8,6 % des fenêtres.
- **Posé** : 2026-09-09 (`4de0f36`). Sonde dédiée : `mesurer_face_a_face_gaps.py`,
  06:00 UTC sur le fil `infra`.

### Liquidity sweep (balayage de liquidité)

- **Tradition** : ICT / Smart Money Concepts. Aussi appelé *stop hunt*.
- **Idée** : les stops s'accumulent juste au-delà d'un extrême récent. Le prix
  va les chercher, puis repart en sens inverse — la mèche prend la liquidité,
  le corps la rejette.
- **Règle** (miroir pour le sens opposé) :
  - `haut[dernière] > max(haut des 30 précédentes)` — l'extrême est dépassé ;
  - **et** `clôture[dernière] < ce même max` — le prix est REVENU dessous.
- **Prédiction falsifiable** : après un balayage des plus-hauts, le prix va
  **baisser** (et inversement). C'est un signal de **retournement**, pas de
  continuation.
- **Motifs** : `liquidity_sweep_down` (balayage des hauts ⇒ on vend) ·
  `liquidity_sweep_up`.
- **Seuil** : 30 bougies de référence, **repris de `_detect_breakout`** pour ne
  pas introduire un réglage de plus. Arbitraire, posé une fois, jamais ajusté.
- ⛔ **J'avais écrit « exclusif de `breakout` par construction ». C'était FAUX**,
  et mes données synthétiques ne pouvaient pas le montrer : `_detect_breakout`
  compare à `_find_level` (un niveau aggloméré), pas au maximum. Le prix peut
  clôturer au-dessus de ce niveau tout en restant sous le plus-haut. Mesuré sur
  4 950 fenêtres réelles : **26 co-occurrences, soit 0,53 %**. Aligner le sweep
  sur `_find_level` dénaturerait le concept — les stops s'accumulent à
  l'**extrême**. On garde la règle fidèle, et un test **borne** le recouvrement
  à 1 %.
- ⚠️ **Recouvrement attendu avec `pin_bar`** : un balayage est souvent une pin
  bar. Ce sont deux cellules distinctes, mais elles ne constituent PAS deux
  tests indépendants. À garder en tête si les deux ressortent ensemble.
- **Posé** : 2026-09-09.

### Order Block

- **Tradition** : ICT / Smart Money Concepts.
- **Idée** : la dernière bougie de sens **opposé** juste avant une impulsion est
  la zone où les gros ordres ont été placés. Le prix devrait y revenir, et elle
  devrait **tenir**.
- **Règle** (miroir pour le sens opposé) :
  1. une bougie d'**impulsion** haussière dans la fenêtre (corps > 0,5 × ATR) ;
  2. la dernière bougie **rouge** avant elle est l'*order block* — sa zone est
     son `[bas, haut]` ;
  3. la bougie courante **redescend dans la zone** (`bas ≤ haut_OB`) ;
  4. **et clôture au-dessus** (`clôture > haut_OB`) — la zone a tenu.
- **Prédiction falsifiable** : après ce retest tenu, le prix repart **dans le
  sens de l'impulsion**. Si son R moyen est nul, le concept est réfuté.
- **Motifs** : `order_block_up` · `order_block_down`.
- **Seuil** : **aucun nouveau** — `_IMPULSION_MIN_ATR = 0,5` est repris du
  détecteur de gap. Un réglage de plus serait un degré de liberté de plus.
- ⚠️ **Recouvrement ATTENDU avec `range_bounce` et `fvg`** — un retest tenu
  ressemble à un rebond sur support, et l'impulsion laisse souvent un FVG.
  ⛔ On ne déclare **aucune exclusivité** : c'est précisément ce que j'ai
  affirmé à tort pour le *liquidity sweep*, et que le vrai marché a démenti.
  Le recouvrement est **mesuré**, pas supposé.
- **Posé** : 2026-09-09.

### Break of Structure (BOS) et Change of Character (CHoCH)

- **Tradition** : ICT / Smart Money Concepts. Les deux sont le **même
  événement** — une cassure — lu dans un **contexte de tendance** :
  - en tendance haussière, casser le dernier **sommet** ⇒ **BOS**, continuation ;
  - en tendance haussière, casser le dernier **creux** ⇒ **CHoCH**, retournement.
- **Structure, sans nouveau réglage** : la fenêtre de **30 bougies** est reprise
  de `_detect_breakout` et du *liquidity sweep*. La tendance se lit en coupant
  cette fenêtre **en deux** : haussière si la moitié récente a **à la fois** un
  plus-haut ET un plus-bas supérieurs à l'ancienne (sommets et creux qui
  montent). Aucun seuil numérique nouveau.
- ⛔ **Ma première prédiction était MAL FORMÉE** : j'avais écrit « leurs R
  moyens doivent être de signes opposés ». **Faux.** Le laboratoire calcule
  `signe = 1 si buy sinon -1` : le R est le résultat du **trade**, pas le
  mouvement du prix. BOS et CHoCH sont deux signaux de trade — si les deux
  concepts marchent, leurs R sont **tous deux positifs**. Rien ne les oppose.
- **Prédiction falsifiable, corrigée** : le concept affirme que le **contexte de
  tendance ajoute de l'information**. Le test est donc `BOS` **contre**
  `breakout` — la même cassure, avec et sans contexte. Si leurs R moyens sont
  égaux, le contexte n'apporte rien et le BOS n'est qu'un breakout renommé.
- **Motifs** : `bos_up` · `bos_down` · `choch_up` · `choch_down`.
- ⚠️ **Recouvrement ATTENDU et fort avec `breakout`** : c'est la même cassure,
  seule la lecture change. Mesuré, jamais supposé.
- **Posé** : 2026-09-09.

### Inversion FVG

- **Tradition** : ICT. Prolonge directement le FVG déjà posé.
- **Idée** : un trou qui servait de support devient **résistance** une fois
  traversé de part en part.
- **Règle** : un `fvg_up` existe dans la fenêtre ; le prix est **repassé
  entièrement dessous** (clôture < bas du trou) ; puis il **revient toucher** la
  zone sans la reprendre (haut ≥ bas du trou, clôture < bas du trou).
- **Prédiction falsifiable** : le retour refusé produit un trade gagnant —
  R moyen **positif**, et supérieur au tirage au hasard.
  ⚠️ ~~« signe opposé à celui du `fvg_up` »~~ : formulation FAUSSE, corrigée le
  même soir. `fvg_up` est un achat, `fvg_inverse_down` une vente ; leurs R sont
  tous deux positifs si les deux concepts marchent. C'est le laboratoire, cellule
  par cellule contre le hasard, qui tranche — pas une comparaison entre eux.
- **Motifs** : `fvg_inverse_up` · `fvg_inverse_down`.
- **Seuil** : **aucun**, comme le FVG dont il dérive.
- **Posé** : 2026-09-09.

---

## 🕐 Candidats

**La file est vide.** Les cinq concepts déclarés le 2026-09-09 sont tous passés
en 🔬 *en mesure*. Le prochain se déclare ici, avec sa prédiction falsifiable,
**avant** d'être codé.

⚠️ Avant d'en coder un : vérifier qu'il n'est pas déjà **⛔ réfuté** ci-dessous,
et écrire sa prédiction falsifiable dans le tableau ci-dessus.

---

## ⛔ Réfutés — ne pas recoder

| concept | verdict | où |
|---|---|---|
| Motifs baissiers sur l'or | écart +0,002 R, **t = +0,02** | `project_motifs_baissiers_or_2026_09_08` |
| CAC 40, retour à la moyenne | 168 essais ⇒ plafond t = 2,55, tous les chiffres dessous | `project_cac40_retour_moyenne_2026_09_07` |
| `range_bounce` (version 1) | — | `project_edge_range_bounce_2026_08_04` |
| Porte de durée 16 h | Δ = −0,15 R | `project_contrefactuel_duree_16h_2026_08_13` |
| Gestion de sortie active | **−0,329 R** sur l'or ; désarmée ⇒ +21 % | `project_edge_gestion_sorties_2026_08_11` |
| ML sur le critère d'ouverture | pire que le hasard, deux phases | `project_ml_verdict_2026_08_05` |

---

## Le contrôle qui tranche

Un concept n'est **jamais** jugé sur son R moyen seul. Le laboratoire le rejoue
contre un **tirage au hasard** sur la même fenêtre, spread facturé, et publie le
plafond de `|t|` que le hasard atteint compte tenu du nombre de cellules
testées :

```
 56 cellules -> 2,55        200 cellules -> 2,96
 80 cellules -> 2,67        400 cellules -> 3,17
```

⚠️ **Un R moyen positif ne prouve rien** tant qu'il n'a pas dépassé ce plafond
sur plusieurs nuits. C'est la leçon la plus chère de ce projet, et la seule qui
ne se périme pas.
