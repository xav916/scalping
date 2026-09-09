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

---

## 🕐 Candidats

Même famille que le FVG, tous codables sur de l'OHLC seul.

| concept | règle pressentie | prédiction falsifiable |
|---|---|---|
| **Order Block** | la dernière bougie de sens opposé avant l'impulsion | elle est retestée, puis tient |
| **Liquidity sweep** | mèche qui dépasse le plus-haut récent puis clôture dessous | le prix repart en sens inverse |
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
