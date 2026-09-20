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

### Double prise de liquidité

- **Tradition** : ICT / Smart Money Concepts. Donnée comme centrale dans le
  corpus rapporté par Xavier le 2026-09-12 — d'où sa place ici, et non parce
  qu'une mesure l'aurait suggérée.
- **Idée** : une poche de liquidité prise **une seule fois** peut n'être qu'un
  dépassement ordinaire. Prise **deux fois** et rejetée deux fois, elle dit que
  quelqu'un défend ce niveau. C'est la deuxième prise qui porte l'information.
- **Règle** (miroir pour le sens opposé) :
  - `niveau` = `max(haut)` de la **première moitié** des 30 bougies de
    référence — la poche ;
  - dans la **seconde moitié**, bougie courante comprise, au moins **deux**
    bougies vérifient `haut > niveau` **et** `clôture < niveau` ;
  - la **dernière** bougie est l'une d'elles — sinon le signal appartient au
    passé, pas au présent ;
  - **et** la dernière bougie est elle-même un **balayage simple** : elle
    dépasse le `max(haut)` des **30** et clôture en deçà.
- ⛔ **Cette dernière ligne a été ajoutée APRÈS mesure, et elle corrige un
  vrai défaut.** Sans elle, la poche valait le max de 15 bougies quand le
  balayage simple compare à celui de 30 : la barre du double était donc plus
  **basse** que celle du simple. Mesuré sur 708 fenêtres réelles :

  | | avant | après |
  |---|---|---|
  | double | 56 (7,9 %) | **12 (1,7 %)** |
  | simple | 49 (6,9 %) | 49 (6,9 %) |
  | double sans simple | **44 (78,6 %)** | **0** |

  Une « double prise » qui se déclenche **plus souvent** qu'une prise simple
  ne mesure pas ce que son nom promet. La règle corrigée est aussi plus
  fidèle : la seconde incursion va **plus loin** que la première et se fait
  rejeter quand même. Un balayage simple sur quatre est désormais un double.
- **Prédiction falsifiable** : `double_sweep_down` doit rendre un **R moyen
  supérieur** à `liquidity_sweep_down` sur le même instrument et la même
  échelle. Si le double ne bat pas le simple, la notion n'ajoute rien — et
  c'est exactement le genre de résultat que ce laboratoire existe pour rendre.
- **Motifs** : `double_sweep_down` (deux prises des hauts ⇒ on vend) ·
  `double_sweep_up`.
- **Seuil** : **aucun réglage neuf**. Les 30 bougies viennent de
  `_detect_breakout` ; la coupe en deux moitiés est l'idiome déjà employé par
  `_tendance_de_structure` (« on coupe en deux la fenêtre de 30 déjà
  utilisée »). Le « deux fois » est la définition même du concept, pas un
  paramètre.
- ⚠️ **Recouvrement TOTAL avec `liquidity_sweep`**, désormais **mesuré à 0
  exception** sur 708 fenêtres. Toute double prise est aussi un balayage
  simple. Les deux cellules ne sont donc **pas** deux tests indépendants, et
  leur comparaison est **appariée** — c'est ce qui la rend lisible.
- ⛔ Je l'avais d'abord affirmé « vrai par construction ». **C'était faux**, et
  le test l'a montré : 78,6 % des doubles n'étaient pas des simples. C'est la
  **deuxième fois le même jour** qu'une affirmation de recouvrement tombe —
  après `breakout` le 09/09. *Un recouvrement se mesure, il ne se déduit pas.*
- ⚠️ **12 déclenchements sur 708 fenêtres** : la cellule sera longtemps
  `INSUFFISANT`. C'est le verdict honnête d'un motif rare, pas un échec.
- ⚠️ Elle héritera du plafond du hasard **commun** : l'ajouter relève la barre
  pour toutes les autres cellules. C'est le prix, et il est assumé.
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

⚠️ Avant d'en coder un : vérifier qu'il n'est pas déjà **⛔ réfuté** ci-dessous,
et écrire sa prédiction falsifiable **ici, avant la première ligne de code**.

---

### Les trois maillons manquants — déclarés le 2026-09-14, non codés

⛔ **Pourquoi ces trois-là, et pas d'autres.** L'architecture rapportée par
Xavier le 2026-09-12 est une chaîne :

```
Contexte → Opening Range → niveau majeur → liquidité → prise de liquidité
   → double prise → réaction/réintégration → retest → confirmation volume
   → BUY/SELL → SL → TP → gestion
```

Sur ces treize maillons, trois manquent — et ils sont **au milieu**, donc
aucun n'est contournable. Les douze chaînes du laboratoire s'arrêtent à deux
maillons parce que les suivants n'existent pas. **La chaîne complète n'a
jamais été mesurée : elle n'est pas montable.**

🔑 Ces trois-là sont notre **formalisation** d'un vocabulaire. Personne n'a
publié ces seuils. Ce qui est *dit* et ce qui est *déduit* doit rester
séparable — sinon on croira avoir reproduit une méthode qu'on a inventée.

#### 1. Opening Range

- **Idée** : le marché ouvre, il construit une fourchette pendant les
  premières bougies de la session, et ce qui compte n'est pas la cassure
  n'importe quand — c'est la cassure **de cette fourchette-là**.
- **Règle** (miroir pour le sens opposé) :
  - `ouverture` = première bougie dont l'heure **locale de la place** atteint
    l'ouverture de la session ;
  - `fourchette` = `max(haut)` / `min(bas)` des `OR_BOUGIES` premières bougies
    depuis l'ouverture ;
  - signal quand une bougie **clôture** au-dessus de `max(haut)`, et seulement
    dans la **même session** — un franchissement le lendemain ne parle pas de
    ce range-là.
- ⚠️ **Recouvrement attendu avec `breakout`, et il sera MESURÉ, pas déduit.**
  C'est l'erreur commise deux fois le 09/09 et le 12/09 : un recouvrement
  « total par construction » s'est révélé faux les deux fois.
- **Prédiction falsifiable** : `opening_range_up` doit rendre un **R moyen
  supérieur** à `breakout_up`, même instrument, même échelle. Si la cassure du
  range d'open ne bat pas la cassure ordinaire, **l'heure n'ajoute rien** et la
  notion est réfutée.

#### 2. Retest

- **Idée** : entrer **sur** la cassure, c'est payer le mouvement. La notion
  dit d'attendre que le prix revienne sur le niveau cassé et qu'il **tienne**.
- **Règle** (miroir pour le sens opposé) :
  - `niveau` = `max(haut)` des 30 bougies de référence ;
  - une bougie antérieure a **clôturé au-dessus** de `niveau` — la cassure ;
  - le prix est **revenu toucher** `niveau` (`bas <= niveau`) dans les
    `RETEST_FENETRE` bougies suivantes ;
  - la **dernière** bougie clôture **au-dessus** de `niveau` — il tient.
- ⚠️ **Recouvrement attendu avec `order_block`**, dont la définition contient
  déjà « retestée et TENUE ». À mesurer, cellule contre cellule.
- **Prédiction falsifiable** : `retest_up` doit rendre un **R moyen supérieur**
  à `breakout_up`. C'est exactement ce que la notion affirme — attendre paie.
  Si le retest ne bat pas la cassure, attendre ne paie pas.

#### 3. Réintégration

- **Idée** : différente du balayage. Un balayage est une **mèche** rejetée
  dans la même bougie. Une réintégration, c'est le prix qui **passe du temps**
  hors de la fourchette — donc qui a l'air accepté dehors — puis qui rentre.
  L'échec est plus coûteux pour ceux qui ont suivi, donc le retour plus violent.
- **Règle** (miroir pour le sens opposé) :
  - `niveau` = `max(haut)` des 30 bougies de référence, **hors** les
    `REINTEGRATION_DEHORS` dernières ;
  - au moins `REINTEGRATION_DEHORS` bougies consécutives ont **clôturé
    au-dessus** de `niveau` — l'acceptation hors du range ;
  - la **dernière** bougie clôture **en deçà** — la réintégration.
- ⚠️ **Recouvrement attendu avec `liquidity_sweep`** : à mesurer. Le critère
  qui les sépare est la **clôture** — le balayage rejette dans la mèche, la
  réintégration accepte puis échoue.
- **Prédiction falsifiable** : `reintegration_down` doit rendre un **R moyen
  supérieur** à `liquidity_sweep_down`. Si accepter puis échouer ne vaut pas
  mieux que rejeter tout de suite, la distinction ne porte rien.

#### Recouvrements et fréquences — **mesurés** le 2026-09-14, après codage

4 950 fenêtres de 50 bougies, vraies bougies XAU/USD 5 min (fixture figée) :

| motif | % des fenêtres | recouvrement mesuré |
|---|---|---|
| `opening_range_up` | 1,19 % | **39,0 %** dans `breakout_up` |
| `opening_range_down` | 1,66 % | **31,7 %** dans `breakout_down` |
| `retest_up` | 2,63 % | 17,7 % dans `breakout_up` · 15,4 % dans `order_block_up` |
| `retest_down` | 3,01 % | 13,4 % dans `order_block_down` |
| `reintegration_down` | 0,79 % | **30,8 %** dans `liquidity_sweep_down` |
| `reintegration_up` | 0,59 % | 24,1 % dans `liquidity_sweep_up` |

🔑 **Les recouvrements sont PARTIELS — et ça change la lecture des trois
prédictions.** Pour la double prise, l'inclusion était *stricte* : chaque
double était aussi un simple, donc la comparaison était **appariée**, donc
lisible. Ici non : les deux tiers d'un `opening_range_up` ne sont pas des
`breakout_up`. La comparaison oppose donc deux populations **distinctes qui se
chevauchent**, ce qui est plus faible qu'un appariement — il faudra plus de
nuits pour trancher, et un écart modeste ne voudra rien dire.

⚠️ Les fréquences (0,59 % à 3,01 %) sont du même ordre que les motifs
existants : ni bruit permanent, ni détecteur muet.

---

### Zone d'accumulation — déclarée le 2026-09-14, non codée

⛔ **Ce concept est NOTRE formalisation, et il faut le dire fort.** L'étape 2
des cinq de Vivien est « trouver une zone d'accumulation ». C'est tout ce
qu'on en sait : **aucun seuil n'a été publié**. Les quatre nombres ci-dessous
sont les nôtres. Les présenter comme sa définition fabriquerait « un robot
inspiré de Vivien » — exactement ce qu'il a été demandé d'éviter.

- **Idée** : une accumulation, c'est le prix qui **se resserre** après avoir
  bougé, et qui **se concentre** sur peu de niveaux. Les deux conditions sont
  nécessaires : un marché qui se resserre en balayant toute sa fourchette n'est
  pas une accumulation, c'est une dérive lente.
- **Règle** (les quatre seuils sont déclarés, pas dérivés) :
  - `RECENTES = 10` dernières bougies — la zone candidate ;
  - `AVANT = 20` bougies juste avant — la référence de mouvement ;
  - **compression** : `amplitude(RECENTES) <= 0,60 × amplitude(AVANT)` ;
  - **retour** : `|clôture_fin − clôture_début| <= 0,35 ×` amplitude(RECENTES).
- ⛔ **La règle déclarée était INATTEIGNABLE — corrigée le jour même, avant
  toute mesure, et voici pourquoi.** J'avais écrit « concentration = largeur
  de la zone de valeur / amplitude, `<= 0,50` ». Mon propre test l'a réfutée :
  dix bougies identiques — la forme la **plus** accumulée qui soit — donnent un
  profil **plat**, dont la zone de valeur vaut `0,70 ×` l'amplitude **par
  construction** (`PART_ZONE_VALEUR`). Le seuil était hors d'atteinte pour la
  figure même qu'il devait reconnaître.
- 🔑 Le **retour** dit ce que la concentration voulait dire : *le prix
  revient-il d'où il est parti ?* Zéro pour une accumulation, proche de 1 pour
  une dérive. La compression seule ne sait pas les séparer — une tendance
  linéaire a une compression de 0,50, sous le seuil.
- 🔑 **Et le profil de volume n'appartenait pas là.** L'étape 2 **trouve** la
  zone, l'étape 3 la **profile**. Les confondre était mon glissement, pas le
  sien. Le profil est désormais **joint** au résultat — `poc`, `zone_valeur` —
  et jamais une condition d'existence : sans volume ils valent `None`, la zone
  tient, et rien ne retombe sur le temps sous un autre nom.
- ⛔ **Ce n'est pas un motif, c'est un CONTEXTE.** Une zone d'accumulation ne
  dit ni d'acheter ni de vendre : elle n'a pas de sens. En faire un
  `PatternType` créerait deux motifs directionnels qui n'existent pas. C'est
  donc un **prédicat** de chaîne, comme `volume_fort` et les sessions.
- **Chaîne déclarée** : `prise_en_accumulation` = `liquidity_sweep` **dans**
  une zone d'accumulation. C'est notre lecture des étapes 2 + 4.
- **Prédiction falsifiable** : `chaine:prise_en_accumulation_baissier` doit
  rendre un **R moyen supérieur** à `liquidity_sweep_down` seul, même
  instrument, même échelle. Si prendre la liquidité **dans** une accumulation
  ne vaut pas mieux que la prendre n'importe où, le contexte n'ajoute rien.
- 🔑 L'inclusion est **stricte** — la chaîne ne se déclenche que sur des
  bougies où le balayage se déclenche déjà. La comparaison est donc
  **appariée**, comme pour la double prise, et non chevauchante comme pour les
  trois maillons. C'est la forme la plus lisible.
- **Coût** : 2 chaînes, ~160 cellules, le plafond du hasard monte encore.

---

### Biais de l'échelle supérieure — déclaré le 2026-09-14, non codé

- **Idée** : le premier maillon de la chaîne est **le contexte**. Un balayage
  haussier pris à contre-courant de la structure large n'est pas le même trade
  que le même balayage dans le sens du contexte.
- ⛔ **Le piège que ce concept évite** : agréger les bougies en H4 fixe ne
  voudrait rien dire aux échelles supérieures — un « biais H4 » mesuré sur des
  bougies d'une heure serait un biais de 8 jours sous le même nom. Le biais est
  donc **relatif à l'échelle mesurée**.
- **Règle** : `tendance_de_structure` — celle qui existe déjà, qui coupe une
  fenêtre en deux et exige *à la fois* un plus-haut **et** un plus-bas
  supérieurs — appliquée à une fenêtre **8 × plus longue** que celle des
  détecteurs (`8 × 30 = 240` bougies). À l'échelle 5 min, cela regarde 20 h de
  marché : l'ordre de grandeur du H4.
- 🔑 **Un seul réglage neuf** : le facteur 8. Tout le reste est réutilisé —
  `_tendance_de_structure` n'a aucun seuil propre, et la fenêtre de 30 est
  celle de `breakout` et du balayage.
- **Chaînes déclarées** : `sweep_avec_biais_haussier` /
  `sweep_avec_biais_baissier` = `liquidity_sweep` **dans le sens** de la
  structure large.
- **Prédiction falsifiable** : la chaîne doit rendre un **R moyen supérieur**
  à `liquidity_sweep` seul, même instrument, même échelle. Si prendre la
  liquidité dans le sens du contexte ne vaut pas mieux que la prendre à
  contre-courant, le contexte n'ajoute rien — et le premier maillon de la
  chaîne serait décoratif.
- 🔑 Inclusion **stricte**, donc comparaison **appariée** : la chaîne ne se
  déclenche que là où le balayage se déclenche déjà.
- **Coût** : 2 chaînes, ~160 cellules de plus.

---

### Premium / discount — déclaré le 2026-09-14, non codé

⚠️ **Provenance, et elle est différente des autres.** Ce concept ne figure
**pas** dans les 38 familles rapportées par Xavier le 2026-09-12. Il vient de
ma propre liste, et Xavier l'a explicitement demandé le 2026-09-14 après que je
l'aie signalé comme un ajout de mon fait. Il est donc marqué **ICT / tradition
Smart Money**, et non « corpus Vivien ».

- **Idée** : dans une fourchette, acheter n'a pas le même sens en haut qu'en
  bas. Au-dessus de l'équilibre le prix est **cher** (*premium*) — on y vend ;
  en dessous il est **bon marché** (*discount*) — on y achète.
- **Règle** — et elle n'introduit **aucun réglage neuf** :
  - `haut` / `bas` = extrêmes de la fenêtre de référence, celle que les
    détecteurs utilisent déjà ;
  - `équilibre` = le **milieu**, `(haut + bas) / 2` — 50 % est la définition du
    concept, pas un paramètre ;
  - `position` = `(clôture − bas) / (haut − bas)` ;
  - **discount** si `position <= 0,5`, **premium** sinon.
- ⛔ **Ce n'est pas un motif, c'est un contexte** — comme la zone
  d'accumulation et le biais. « Être en premium » ne dit pas d'entrer, ça dit
  *dans quel sens on a le droit d'entrer*. C'est donc un **prédicat**.
- **Chaînes déclarées** : `avalement_en_discount_haussier` et
  `avalement_en_premium_baissier`.
- ⛔ **MONTAGE CORRIGÉ APRÈS MESURE — et la mesure était prévue.** Ma première
  version accrochait le contexte au **balayage**. Mesuré sur 15 jours, XAU/USD :

  | déclencheur | en discount |
  |---|---|
  | `liquidity_sweep_up` | **91,8 %** |
  | `bos_up` | 0,0 % |
  | `breakout_up` | 2,0 % |
  | `engulfing_bullish` | **45,5 %** |
  | `engulfing_bearish` | 61,0 % |

  Un balayage des bas **est déjà** en discount — par construction, puisqu'il
  fait un nouveau plus-bas. Le filtre n'écartait que 8 % des cas : **160
  cellules pour presque aucune information**, et le plafond du hasard monte
  pour tout le monde.

  🔑 Accroché à un motif dont la position n'est **pas** dictée par sa propre
  définition, le même filtre discrimine vraiment. C'est aussi la lecture ICT
  fidèle : *« n'achète un signal haussier qu'en discount »* — un avalement
  haussier peut survenir n'importe où dans la fourchette, un balayage des bas
  non.
- **Prédiction falsifiable** : chaque chaîne doit rendre un **R moyen
  supérieur** à `liquidity_sweep` seul, même instrument, même échelle. Si
  prendre la liquidité du bon côté de l'équilibre ne vaut pas mieux que la
  prendre n'importe où, la notion n'ajoute rien.
- 🔑 Inclusion **stricte** → comparaison **appariée**.
- ⚠️ **Recouvrement attendu avec le balayage lui-même** : un balayage des bas
  a de bonnes chances d'être déjà sous l'équilibre. **À mesurer, pas à
  déduire** — c'est l'erreur commise trois fois ce mois-ci.
- **Coût** : 2 chaînes, ~160 cellules.

⚠️ **Ce que ces trois coûtent à tout le monde.** Six motifs de plus, soit
environ **480 cellules** sur les 20 instruments — le plafond du hasard monte
pour **toutes** les cellules existantes. C'est le prix assumé de la chaîne
complète, et c'est pourquoi ils sont **déclarés ici avant d'être codés**.

---

### Niveau majeur — déclaré le 2026-09-20, non codé

⛔ **Pourquoi ce concept maintenant.** La revue de couverture du 2026-09-20 a
comparé la chaîne de treize maillons rapportée le 12/09 à ce qui est réellement
codé. Huit maillons sont là, trois sont partiels, un est réfuté. Sur les trois
partiels, celui-ci est le seul qui change le SENS de tout ce qui vient après.

🔑 **Le défaut qu'il nomme.** Dans la chaîne rapportée, le niveau majeur décide
**OÙ** on attend la liquidité. Chez nous, le balayage se déclenche sur le max
glissant des **30 dernières bougies** — donc n'importe où. Nos cellules ne
mesurent donc pas « un balayage sur un niveau qui compte », elles mesurent
« un balayage, quelque part ». `_find_level` ne comble pas ce manque : il
moyenne les cinq extrêmes de la fenêtre courante s'ils forment un amas — une
seule échelle, ni plus-haut journalier, ni nombre rond, ni confluence. C'est un
extrême local lissé, pas un niveau majeur.

⚠️ **Et ça éclaire une mesure existante.** Le 2026-09-20,
`chaine:sweep_avec_biais_baissier` rend **−0,330 R** sur 149 à 120
échantillons, soit trois fois pire que `liquidity_sweep_down` seul (−0,096).
Empiler une condition de DIRECTION sur un déclencheur non LOCALISÉ peut très
bien dégrader. Ce n'est pas une explication démontrée — c'est l'hypothèse que
ce concept rend testable.

- **Tradition** : commune à l'analyse technique classique et au vocabulaire
  Smart Money. ⛔ **Mais la définition ci-dessous est LA NÔTRE** : personne n'a
  publié ces seuils, et le corpus rapporté le 12/09 nomme le maillon sans le
  définir. Ne jamais la présenter comme la définition de quiconque.
- **Idée** : un extrême de 30 bougies est un accident local. Un extrême de
  l'échelle supérieure est un endroit que le marché a défendu à une échelle que
  tout le monde regarde. Prendre la liquidité là n'est pas le même trade.
- **Règle** — et elle n'introduit **aucun réglage neuf** :
  - `niveau_majeur` = `max(haut)` / `min(bas)` de la fenêtre du **biais**,
    soit `BIAIS_FACTEUR × FENETRE = 8 × 50 = 400` bougies. Le facteur 8 est
    déjà déclaré (biais de l'échelle supérieure, 2026-09-14) ; on ne crée pas
    un second réglage d'échelle.
  - ⛔ **Correction du 2026-09-20, le jour même de la déclaration.** J'avais
    écrit « 8 × 30 = 240 ». FAUX : le facteur 8 multiplie `FENETRE` (50, la
    fenêtre de détection), pas le `lookback` de 30 propre au balayage. La
    fenêtre du biais vaut donc **400** bougies, soit 33 h de marché à
    l'échelle 5 min. Deux géométries différentes portaient le même chiffre
    dans ma tête — exactement ce que ce carnet existe pour attraper.
  - `sur_niveau_majeur` est vrai quand l'extrême BALAYÉ par la bougie courante
    se trouve à moins de `0,5 × ATR(14)` du niveau majeur de son côté.
  - 🔑 Le `0,5 × ATR` est **repris** de `_IMPULSION_MIN_ATR`, déjà utilisé par
    les détecteurs de gap et d'order block. ⚠️ C'est une RÉUTILISATION, pas une
    dérivation : rien ne prouve que la bonne tolérance soit celle de
    l'impulsion. Elle est posée une fois et n'est jamais ajustée.
- ⛔ **Ce n'est pas un motif, c'est un CONTEXTE** — comme la zone
  d'accumulation, le biais et le premium/discount. « Être sur un niveau
  majeur » ne dit pas d'acheter, ça dit *où* l'entrée a un sens. C'est donc un
  **prédicat**.
- **Chaînes déclarées** : `sweep_sur_niveau_majeur_haussier` /
  `sweep_sur_niveau_majeur_baissier` = `liquidity_sweep` **sur** un niveau
  majeur.
- **Prédiction falsifiable** : la chaîne doit rendre un **R moyen supérieur** à
  `liquidity_sweep` seul, même instrument, même échelle. Si prendre la
  liquidité sur un niveau qui compte ne vaut pas mieux que la prendre n'importe
  où, **le maillon 3 est décoratif** — et on l'aura appris proprement.
- 🔑 Inclusion **stricte** : la chaîne ne se déclenche que sur des bougies où le
  balayage se déclenche déjà. La comparaison est donc **appariée**, la forme la
  plus lisible — celle de la double prise, pas celle chevauchante des trois
  maillons.
- ⛔ **L'OBJECTION À MESURER, et elle est sérieuse.** Un `liquidity_sweep_down`
  fait par définition un nouveau plus-haut de 30 bougies. S'il est en plus à
  portée du plus-haut de 240, il fait peut-être simplement un nouveau plus-haut
  de 240 — et le prédicat sélectionnerait alors des **cassures de la grande
  fourchette**, pas des balayages sur un niveau retesté. Deux populations
  opposées sous un seul nom.
  ⚠️ La mesure qui tranche, à faire AVANT de lire le moindre R : la part des
  déclenchements où le niveau de 240 est **atteint pour la première fois**
  contre celle où il était **déjà en place** dans la fenêtre. Si la première
  domine, la règle mesure une cassure et il faudra exiger que le niveau
  préexiste. C'est le troisième recouvrement « évident » de ce carnet — les
  deux premiers (09/09, 12/09) se sont révélés faux. *Un recouvrement se
  mesure, il ne se déduit pas.*
- 🔬 **RECOUVREMENT MESURÉ le 2026-09-20, avant toute lecture de R** — fixture
  figée XAU/USD 5 min, 4 598 fenêtres, règle LARGE (tolérance seule) :

  | déclencheur | balayages | sur niveau majeur | dont **dépassent** | dont **retestent** |
  |---|---|---|---|---|
  | `liquidity_sweep_down` | 159 | 31 (19,5 %) | **25 (80,6 %)** | 6 (19,4 %) |
  | `liquidity_sweep_up` | 183 | 53 (29,0 %) | **50 (94,3 %)** | 3 (5,7 %) |

  ⛔ **L'objection était fondée.** La règle large mesurait majoritairement une
  **cassure** de la grande fourchette, pas un niveau retesté. Corrigée le jour
  même : le niveau ne doit **pas être dépassé**. Ce n'est pas un seuil neuf,
  c'est la contrainte de sens que cette déclaration avait prévue.

  🔑 **Et la leçon est la plus chère du carnet, encore une fois** : la version
  la plus FOURNIE (31 et 53 déclenchements) était la MOINS fidèle. Lire son R
  aurait donné un résultat exploitable statistiquement et faux sur le fond.

- ⚠️ **Fréquence attendue basse, et c'est assumé.** `liquidity_sweep_down` rend
  n = 395 sur l'or 5 min ; exiger la proximité du niveau de 240 en retirera une
  large part. Le verdict honnête sera `INSUFFISANT` pendant longtemps. Une
  chaîne peut être vraie et non mesurable — ce n'est pas la même chose que
  fausse.
- **Coût** : 2 chaînes, ~160 cellules, le plafond du hasard monte pour **toutes**
  les autres cellules. C'est le prix, et c'est pourquoi le concept est déclaré
  ici avant d'être codé.

---

### Structure de l'échelle agrégée (M15) — déclaré le 2026-09-20, non codé

⚠️ **PROVENANCE, et elle est faible.** Le critère vient de la synthèse transmise
par Pascal le 2026-09-20, produite par un autre assistant depuis des
publications TradingView. Sources **non consultées de première main**, citations
non vérifiées. Cf. `notions_vivien.SOURCE_SYNTHESE`, entrée
`cassure_structure_m15`. Rien ici n'est « ce qu'il dit » : c'est ce qui nous a
été rapporté, et notre réduction de ce rapport.

- **Critère rapporté** : casser le high M15 fait repasser la structure M15
  haussière ; casser le low, baissière. La structure reposerait donc sur des
  highs/lows structurels et leur cassure, pas sur une moyenne mobile.
- **Idée, et ce qui est VRAIMENT neuf ici.** Ce n'est pas la cassure de
  structure : `bos_up` / `bos_down` existent depuis le 09/09. C'est que la
  structure d'une **échelle agrégée** devienne un **prédicat** disponible pour
  un déclencheur détecté sur une autre échelle. Aujourd'hui chaque cellule vit
  entièrement à l'intérieur d'un seul horizon : un balayage 5 min ne sait rien
  de l'état du M15. C'est le maillon « M15 = setup, M5 = trigger » de la
  hiérarchie rapportée, et il manque au dispositif.
- **Règle** — et elle n'introduit **aucun réglage neuf** :
  - les bougies M15 viennent de `echelle_agregee.agreger(candles, 3)` — le
    chemin d'agrégation existe depuis le 2026-09-08, mesuré avant d'être
    construit ;
  - l'état de structure vient de `_tendance_de_structure`, qui n'a aucun seuil
    propre (elle coupe une fenêtre en deux et exige *à la fois* un plus-haut
    **et** un plus-bas supérieurs) ;
  - `structure_m15_haussiere` est vrai quand cette lecture, appliquée aux
    bougies M15 agrégées, rend `haussiere`. Miroir pour l'autre sens.
- ⛔ **CE QUE NOUS RÉDUISONS, et il faut le dire.** Le critère rapporté décrit un
  **basculement** — « casser le high *fait repasser* la structure haussière ».
  `_tendance_de_structure` rend un **état**, pas un événement de bascule. Nous
  mesurons donc « la structure M15 *est* haussière », pas « elle *vient de*
  basculer ». C'est une réduction assumée, pas une implémentation fidèle : un
  état peut durer des heures là où une bascule est instantanée, et les deux ne
  produisent pas les mêmes trades. La version fidèle exigerait un détecteur de
  bascule ; elle n'est pas déclarée ici.
- ⛔ **Ce n'est pas un motif, c'est un CONTEXTE** — comme le biais,
  l'accumulation et le premium/discount. C'est donc un **prédicat**.
- **Chaînes déclarées** : `sweep_avec_structure_m15_haussier` /
  `sweep_avec_structure_m15_baissier` = `liquidity_sweep` sur 5 min **dans le
  sens** de la structure M15.
- **Prédiction falsifiable** : la chaîne doit rendre un **R moyen supérieur** à
  `liquidity_sweep` seul, même instrument, même échelle. Si l'état du M15
  n'ajoute rien à un balayage 5 min, le maillon « M15 = setup » est décoratif.
- 🔑 Inclusion **stricte** → comparaison **appariée**.
- ⛔ **L'OBJECTION À MESURER, et c'est la quatrième fois.** Le recouvrement avec
  `biais_haussier` / `biais_baissier` sera **fort**. Les deux appellent la MÊME
  fonction : le biais sur 400 bougies de 5 min de la même série, celle-ci sur
  ~30 bougies M15, soit ~90 bougies de 5 min. Fenêtres différentes, lecture
  identique, résultats corrélés.
  ⚠️ La mesure qui tranche, **avant toute lecture de R** : la part des bougies
  où les deux prédicats disent la même chose. **Si le recouvrement est
  quasi-total, la chaîne n'ajoute rien et duplique une cellule que nous payons
  déjà sur le plafond** — et il faudra soit la retirer, soit choisir laquelle
  des deux échelles porte le contexte. Les trois recouvrements « évidents »
  précédents (09/09, 12/09, 20/09) se sont tous révélés autres que prévu :
  *un recouvrement se mesure, il ne se déduit pas.*
- ⚠️ **Fréquence attendue élevée**, contrairement au niveau majeur : une
  structure est haussière ou baissière une bonne partie du temps. La chaîne
  aura donc du `n` — ce qui la rend mesurable vite, et rend le recouvrement
  d'autant plus important à vérifier d'abord.
- **Coût** : 2 chaînes, ~160 cellules, le plafond du hasard monte pour **toutes**
  les autres cellules.

---

### Balayage de l'extrême d'accumulation — déclaré le 2026-09-20, **GELÉ le jour même par sa propre sonde**

> ⛔ **VERDICT, avant toute ligne de code : NON CODÉ.** La sonde
> `scripts/mesurer_extreme_accumulation.py` rend **n = 3** (achat) et
> **n = 2** (vente) sur 5 000 bougies XAU/USD 5 min, pour
> `MIN_TRADES = 20`. La cellule sortirait `INSUFFISANT` indéfiniment en
> faisant monter le plafond du hasard de toutes les autres. La règle est
> **mort-née par rareté**, pas réfutée sur son R — on ne saura jamais ce
> qu'elle vaut, et c'est un résultat.
>
> 🔑 La sonde a coûté un fichier et trois minutes. La chaîne aurait coûté
> deux cellules × 4 échelles × tous les instruments, chaque nuit, pour
> rien. **C'est la déclaration préalable qui paie ici, pas le code.**

⚠️ **PROVENANCE, et elle est meilleure que d'habitude — sans être bonne.** Vient
du décodage des cinq étapes transmis par Pascal le 2026-09-20 (cf.
`notions_vivien.NOTIONS`, `cinq_etapes`, étapes 4 et 5). C'est un décodage audio
relayé : **la vidéo n'a pas été ouverte par nous**. Ce qui est rapporté, et qui
fonde ce concept : l'étape 4 nomme comme liquidité « les hauts/bas précédents,
les hauts/bas relativement égaux, **et les extrêmes de la zone
d'accumulation** » ; l'étape 5 attend que cette liquidité soit **prise** puis
réintégrée.

- **Ce qui est VRAIMENT neuf, et c'est précis.** `chaine:prise_en_accumulation`
  (déclarée le 14/09) exige qu'une zone d'accumulation **existe**. Elle
  n'exige **rien** sur le niveau balayé : le balayage peut prendre n'importe
  quel plus-bas trouvé par `_find_level`. Le décodage du 20/09 demande autre
  chose — que le niveau pris soit **le bord de la zone**. C'est une règle
  strictement **plus étroite**, et plus fidèle à ce qui est rapporté.
- ⛔ **ET IL FAUT DIRE CE QUE J'AI TROUVÉ EN LE VÉRIFIANT.** `_dans_accumulation`
  est documenté « le balayage se produit-il **DANS** une zone d'accumulation ? »
  — mais le code ne teste que `zone_accumulation(...) is not None`. La position
  du balayage par rapport à la zone n'est **jamais vérifiée**. Le prédicat est
  donc plus faible que son propre docstring, depuis le 14/09. Ce n'est pas un
  bug de mesure (les cellules mesurent bien ce que le code fait), c'est un nom
  qui promet plus que sa règle — exactement ce que ce carnet existe pour
  attraper. À corriger dans le docstring, **pas** dans la règle : changer la
  règle d'un prédicat déjà mesuré invaliderait les nuits déjà enregistrées.
- **Règle** — et elle n'introduit **aucun seuil neuf**, aucune tolérance :
  - la zone vient de `market_profile.zone_accumulation`, qui rend déjà ses
    bords `bas` et `haut` (ils existent depuis le 14/09, ils n'étaient pas
    utilisés) ;
  - `sur_extreme_accumulation_bas` est vrai quand la bougie du signal
    **perce** `bas` (son `low` passe dessous) **et réintègre** (sa clôture
    revient au-dessus de `bas`). Miroir sur `haut` pour l'autre sens.
  - ⛔ **et la zone se calcule SANS la bougie du signal** — corrigé le
    2026-09-20, avant la première mesure, parce que la règle était
    **inatteignable** telle qu'écrite dix minutes plus tôt : `bas` est le
    `min(low)` des dix dernières bougies *y compris* celle qui balaie. Le
    plus-bas de la bougie qui perce EST donc le plus-bas de la zone, et
    `low < bas` est faux **par construction**. La zone se lit sur
    `bougies[:i-1]` (l'accumulation telle qu'elle existait *avant* le
    balayage), le perçage sur `bougies[i-1]`. Même défaut, même correction que
    le niveau majeur : un extrême qui inclut l'événement qu'il doit mesurer ne
    mesure rien. C'est la deuxième règle de ce carnet réfutée par sa propre
    géométrie avant d'être codée — et c'est exactement ce que la déclaration
    préalable sert à attraper.
  - Pas d'ATR, pas de pourcentage, pas de tolérance : les bords de la zone sont
    des prix exacts, et « percer puis réintégrer » est une comparaison de
    clôture. C'est la géométrie du balayage elle-même, appliquée à un autre
    niveau.
- 🔑 **LA QUESTION D'INDICE, POSÉE PUIS TRANCHÉE — dans le code, pas par
  intuition.** Tous les prédicats lisent `bougies[:i]` et jamais la bougie `i`.
  Or cette règle a besoin du `low` et de la clôture de **la bougie qui a
  balayé**. Lecture de `detections()` (2026-09-20) : la détection à l'indice `i`
  travaille sur `bougies[i - FENETRE:i]`, donc la bougie `i` **n'est pas vue par
  le détecteur** — c'est la bougie d'**entrée**, et `rejouer_cellule` ouvre le
  trade à `i`. La bougie du signal est donc `bougies[i-1]`.
  ⚠️ **Conséquence pour la règle** : le perçage-réintégration se lit sur
  `bougies[i-1]`, et il est **dans** `bougies[:i]` — la discipline tient sans
  exception à lui faire. Lire `bougies[i]` aurait fabriqué un edge à partir
  d'une bougie que le détecteur n'a pas vue : le défaut le plus coûteux du
  dispositif, évité ici par une lecture de trois lignes.
- ⛔ **Ce n'est pas un motif, c'est un CONTEXTE** — comme l'accumulation dont il
  lit les bords. C'est donc un **prédicat**.
- **Chaînes déclarées** (non armées) : `sweep_extreme_accumulation_haussier` /
  `_baissier` = `liquidity_sweep` **+** `dans_accumulation` **+**
  `sur_extreme_accumulation_*`.
- **Prédiction falsifiable** : la chaîne doit rendre un **R moyen supérieur** à
  `chaine:prise_en_accumulation` du même sens, même instrument, même échelle.
  ⚠️ Le comparant n'est **pas** `liquidity_sweep` seul : la question posée est
  « *le bord de la zone* ajoute-t-il quelque chose à *la zone* ? ». Si prendre
  l'extrême ne vaut pas mieux que prendre n'importe quel niveau dans le même
  contexte, alors l'étape 4 ne dit rien d'exploitable, et la fidélité gagnée
  est décorative.
- 🔑 Inclusion **stricte** (la nouvelle chaîne ne se déclenche que sur des
  bougies où `prise_en_accumulation` se déclenche déjà) → comparaison
  **appariée**, comme la double prise.
- ⛔ **L'OBJECTION À MESURER AVANT TOUTE LECTURE DE R, et elle est sérieuse
  dans l'autre sens que d'habitude.** Cette fois le risque n'est pas le
  recouvrement, c'est le **`n`**. Deux mesures à produire avant de coder la
  chaîne :
  1. la part des `liquidity_sweep` en accumulation dont le niveau balayé est
     déjà, de fait, le bord de la zone. **Si elle est proche de 100 %**, la
     règle ne filtre rien et duplique une cellule que nous payons sur le
     plafond ;
  2. le nombre de déclenchements par instrument sur les nuits disponibles. **Si
     `n < MIN_TRADES`**, la cellule sortira `INSUFFISANT` indéfiniment : elle
     coûtera du plafond à toutes les autres sans jamais pouvoir conclure. C'est
     le défaut exact du niveau majeur, et il se vérifie *avant*, par sonde.
- ⚠️ **Fréquence attendue FAIBLE.** Il faut la conjonction d'une accumulation,
  d'un balayage, et que ce balayage prenne précisément un bord. Contrairement
  à la structure M15, cette chaîne n'aura **pas** de `n` facilement.
- ⛔ **ET ELLE NE COMPLÈTE PAS LES CINQ ÉTAPES.** Ce concept code les étapes 4
  et 5 *comme setup*. Le **déclencheur final** reste inconnu : le décodage dit
  lui-même qu'un retest et des « volumes alignés » suivent, et la moitié
  « volumes » est bloquée par les **données** (aucun footprint bid/ask sur CFD).
  `notions_vivien.cinq_etapes` reste donc INCOMPLÈTE et ne produit aucune
  chaîne — ce carnet-ci déclare un morceau mesurable, pas la méthode.
- **Coût** : 2 chaînes, ~160 cellules, le plafond du hasard monte pour
  **toutes** les autres cellules — ~+0,011 sur `t`, mesuré sur les 13 nuits
  disponibles.

#### Ce que la sonde a mesuré — 2026-09-20, XAU/USD 5 min, 4 948 fenêtres

| | balayage des BAS (achat) | balayage des HAUTS (vente) |
|---|---|---|
| balayages simples | 193 | 169 |
| dont en accumulation (**le comparant**) | 9 — **4,7 %** | 12 — **7,1 %** |
| dont zone **inexistante sans la bougie du signal** | 6 — 66,7 % | 9 — 75,0 % |
| **dont prennent le bord et réintègrent** | **3** | **2** |
| ne touchent pas le bord | 0 | 0 |

- ⛔ **La règle ne filtre presque rien — et ce n'est pas le problème.** Le
  problème est au-dessus : **le comparant lui-même est rare**. 9 et 12
  déclenchements sur 5 000 bougies, c'est `chaine:prise_en_accumulation`
  elle-même qui frôle `MIN_TRADES` sur un instrument et une échelle. À
  vérifier dans les cellules du laboratoire : si ses verdicts sont
  `INSUFFISANT` depuis le 14/09, elle coûte du plafond sans rien conclure.
- 🔑 **ET LA SONDE A TROUVÉ AUTRE CHOSE, QUI COMPTE PLUS QUE LA RÈGLE
  DÉCLARÉE.** Dans **67 % à 75 %** des cas où `dans_accumulation` est vrai, la
  zone **n'existe pas** si on retire la bougie du signal. Autrement dit : c'est
  la bougie qui balaie qui **fabrique** l'accumulation. Le mécanisme est
  lisible dans `zone_accumulation` — un perçage suivi d'une réintégration
  augmente l'amplitude et laisse le déplacement net petit, donc
  `retour = |Δclôture| / amplitude` **baisse** et passe sous 0,35. Le prédicat
  de contexte est donc, majoritairement, **un effet de l'événement qu'il est
  censé contextualiser**. Ce n'est pas un contexte, c'est un écho.
  ⚠️ Conséquence à trancher, et elle touche une chaîne **déjà mesurée** :
  `dans_accumulation` devrait lire `bougies[:i-1]`. Mais changer la règle d'un
  prédicat déjà mesuré **invalide les nuits enregistrées** — donc pas de
  modification en place : une déclaration séparée, un nom séparé, et les deux
  se comparent. Aucun risque de trade : `prise_en_accumulation` n'est **pas**
  dans `CHAINES_AUTORISEES`.

#### Et ce que les cellules du laboratoire disent du comparant — copie de lecture, 2026-09-20

⚠️ **Première version de ce paragraphe corrigée le jour même.** J'avais écrit
« 93 % des cellules n'ont jamais pu conclure », en lisant `INSUFFISANT` comme
« pas assez de trades ». C'est faux : `_verdict` rend `INSUFFISANT` pour **trois**
raisons différentes — `n < MIN_TRADES`, écart au hasard non mesuré, **ou écart
sous le plafond du hasard**. Le troisième cas est une cellule parfaitement
mesurée, simplement indistinguable du bruit. Les confondre transformait un
résultat en panne de données. Le détail, par échelle :

| échelle | manque de trades (`n` < 20) | mesurée, **sous le plafond** | `REFUTE` | `RETENU` |
|---|---|---|---|---|
| 5 min | 54 | **80** | 44 | **0** |
| 15 min | 186 | 20 | 17 | **0** |
| 30 min | 223 | 2 | 0 | **0** |
| 60 min | **230** | 0 | 0 | **0** |

- ⛔ **693 cellules sur 856 (81 %) manquent de trades** — la sonde le prévoyait
  sur une fixture d'un seul instrument, les 13 nuits le confirment partout.
- ⛔ **Mais là où la chaîne EST mesurable — 5 min — elle donne 80 cellules sous
  le plafond du hasard et zéro `RETENU`.** Ce n'est plus une panne de données,
  c'est un résultat : au pas de 5 minutes, prendre la liquidité en accumulation
  est indistinguable du hasard de son sens.
- ⛔ **ET LES 61 QUI ONT CONCLU SONT TOUTES CRYPTO** — LTC (23), BNB (16),
  UNI (12), ADA (7), XRP (2), ETH (1), avec des R moyens de −0,7 à −17. C'est
  l'artefact de coût corrigé le 2026-09-20 : le laboratoire facturait à des
  paires exécutées chez Kraken le spread du CFD altcoin de MT5. Autrement dit :
  **cette chaîne n'a jamais produit un seul verdict concluant sur un instrument
  non crypto.** Ses `REFUTE` doivent disparaître à la nuit du 21/09 — la
  première après le filtre de classe d'actif.
- ⛔ **ET L'ÉCHAPPATOIRE « IL SUFFIT D'AGRÉGER » EST RÉFUTÉE PAR CES MÊMES
  CHIFFRES.** J'allais proposer de chercher l'accumulation sur une échelle
  supérieure, où 30 bougies couvrent des heures. Les cellules disent l'inverse,
  et monotonement : `n` moyen **29,1** (5 min) → **10,2** (15 min) → **7,0**
  (30 min) → **4,3** (60 min), avec un `n` **maximum de 10** à 60 min. Le
  laboratoire agrège déjà pour chaque horizon : moins de bougies par nuit, donc
  moins d'événements, et la fréquence par bougie ne monte pas assez pour
  compenser. **À 60 min, aucune cellule ne peut atteindre `MIN_TRADES`, jamais.**
  Proposition retirée avant d'être déclarée — elle aurait coûté deux chaînes de
  plus pour une impossibilité arithmétique.
- 🔑 **Ce qui reste, et ce n'est pas du code.** La seule voie non refermée est de
  relire les quatre seuils du 14/09 — et les relâcher pour obtenir du `n` est
  exactement le geste que ce carnet interdit sans déclaration préalable. Quant à
  retirer `prise_en_accumulation` du registre pour rendre du plafond aux autres :
  **le calcul ne le justifie pas.** Deux chaînes coûtent ~0,011 de plafond
  (`plafond ≈ 1,72 + 0,249 × ln(N)`). Garder une chaîne qui ne conclut pas coûte
  presque rien ; ce qui devait changer, c'est **l'attente** qu'on plaçait en
  elle, pas le registre.

---

## ⛔ Réfutés — ne pas recoder

| concept | verdict | où |
|---|---|---|
| Motifs baissiers sur l'or | écart +0,002 R, **t = +0,02** | `project_motifs_baissiers_or_2026_09_08` |
| CAC 40, retour à la moyenne | 168 essais ⇒ plafond t = 2,55, tous les chiffres dessous | `project_cac40_retour_moyenne_2026_09_07` |
| `range_bounce` (version 1) | — | `project_edge_range_bounce_2026_08_04` |
| Balayage de l'extrême d'accumulation | **n = 3 / 2** sur 5 000 bougies, pour `MIN_TRADES = 20` — mort-né par rareté, jamais codé | `scripts/mesurer_extreme_accumulation.py` |
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
