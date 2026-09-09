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

---

## 🕐 Candidats

Même famille que le FVG, tous codables sur de l'OHLC seul.

| concept | règle pressentie | prédiction falsifiable |
|---|---|---|
| **Break of Structure** | clôture au-dessus du dernier sommet de structure | la tendance continue |
| **CHoCH** | en tendance haussière, clôture sous le dernier creux | retournement |
| **Inversion FVG** | un FVG traversé de part en part | il devient résistance au lieu de support |

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
