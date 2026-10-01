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
| Restreindre les motifs aux heures « bon marché » | effet du spread horaire **déjà mesuré le 11/08** : ×2,13 à 20h et 22h, mais **0,015 R** rapporté à la distance au stop — **1/57** de la perte moyenne de 0,86 R | `mt5_bridge._heure_defavorable` (docstring) |
| Porte de durée 16 h | Δ = −0,15 R | `project_contrefactuel_duree_16h_2026_08_13` |
| Gestion de sortie active | **−0,329 R** sur l'or ; désarmée ⇒ +21 % | `project_edge_gestion_sorties_2026_08_11` |
| ML sur le critère d'ouverture | pire que le hasard, deux phases | `project_ml_verdict_2026_08_05` |

---

## Les deux seules cellules `RETENU` jamais observées — archivées le 2026-09-20

⛔ **Elles disparaissent à la nuit du 21/09, et il faut garder leur trace avant.**
Sur **40 084 cellules**, 13 nuits, 56 motifs, 20 paires, la copie de lecture
compte **4 lignes `RETENU` — soit 2 cellules mesurées deux nuits de suite**, aux
valeurs identiques (mêmes trades, re-mesurés) :

| nuit | paire | échelle | motif | `n` | R moyen | Δ hasard | plafond |
|---|---|---|---|---|---|---|---|
| 19 et 20/09 | **ADA/USD** | 60 min | `breakout_up` | 23 | +0,064 | +1,392 | 3,79 |
| 19 et 20/09 | **ADA/USD** | 60 min | `chaine:cassure_confirmee_volume_haussier` | 20 | +0,141 | +1,469 | 3,81 |

- ⛔ **Les deux sont CRYPTO — donc les deux sont des artefacts du même défaut de
  coût, mais dans l'autre sens.** Le laboratoire facturait à ADA/USD le spread
  du CFD altcoin de MT5. Arithmétique, depuis les colonnes stockées : le contrôle
  aléatoire de ces cellules tourne à **−1,33 R** (0,064 − 1,392), quand la
  cellule elle-même fait +0,064. L'écart n'est pas une performance, c'est un
  contrôle **noyé par un coût faux**.
- 🔑 Le contraste, nuit du 20/09, 4 432 cellules : contrôle aléatoire moyen
  **−1,64 R** sur les paires crypto contre **−0,83 R** ailleurs. Le coût gonflé
  double la perte des deux côtés ; l'écart cellule−contrôle y devient dominé par
  le coût, dans les **deux** directions. C'est ce qui produit 100 % de `REFUTE`
  crypto d'un côté, et ces deux `RETENU` de l'autre.
- ⛔ **Elles ne seront pas réfutées : elles vont simplement quitter l'univers
  mesuré.** ADA/USD s'exécute chez Kraken, et `instruments_servis()` filtre
  depuis le 2026-09-20 les paires que la destination mesurée ne sert pas. Le
  dispositif passera donc à **zéro cellule `RETENU`** — et ce zéro sera plus
  honnête que ces quatre lignes.
- 🔑 **Et le compte des `RETENU` était déjà celui du hasard.** 27 256 cellules
  concluantes, plafond ≈ 3,8 bilatéral : `2 × Φ(−3,8) ≈ 1,4·10⁻⁴`, soit **≈ 0,3
  faux positif par nuit** — pour 4 observés sur 13 nuits, c'est-à-dire ≈ 0,31 par
  nuit. Le nombre de cellules retenues est **indistinguable de ce que le plafond
  laisse passer par construction**. ⚠️ Les nuits se recouvrent (fenêtres de 90
  jours décalées d'un jour) : elles ne sont pas 13 tests indépendants, et le
  calcul se lit par nuit, pas cumulé.
- ⚠️ Répartition d'ensemble des 40 084 cellules : **12 824** manquent de trades
  (32 %), **21 008** sont mesurées et **sous le plafond** (52 %), **6 248**
  `REFUTE` (16 %), **4** `RETENU` (0,01 %). Le goulot n'est donc PAS le volume de
  données — la moitié des cellules a assez de trades et reste indistinguable du
  hasard.

---

## La décomposition que la table permet enfin — 2026-09-20

⛔ **Ce n'est pas un concept, c'est une colonne** — et c'est pour ça que ça figure
ici : la prochaine session qui cherchera « une idée » doit d'abord lire ce
paragraphe.

Les cellules perdent **−0,86 R** en moyenne, le contrôle aléatoire **−0,83 R**.
Deux populations opposées, presque la même perte : le facteur commun n'est pas le
signal, c'est le **coût**. Or `rejouer_cellule` calcule `cout = spread / risque`
pour chaque trade, `mesurer()` en prend la médiane par cellule sous le nom
`spread_r` — et **personne ne l'écrivait**. Treize nuits de mesure sans pouvoir
répondre à la question la plus lourde du projet.

- Depuis le 2026-09-20, `labo_or_cellules` porte `spread_r` et `risque_pct`.
  La décomposition `R_brut = R_net + coût` se lit donc dans la table, sans
  rejouer une nuit et sans lire un log.
- 🔑 **`risque_pct` n'est pas décoratif.** Le coût est un *rapport*, pas une
  propriété du spread : le même spread coûte 0,05 R sur un stop large et 0,40 R
  sur un stop de scalping. Sans le dénominateur, un coût élevé se lit « le
  courtier est cher » alors qu'il dit peut-être « nos stops sont serrés ». Deux
  diagnostics opposés, deux remèdes opposés.
- **Ce que la première nuit dira**, et les deux lectures possibles :
  - coût médian ≈ 0,3 R → les frais expliquent un tiers de l'écart, et il reste
    une perte de fond à expliquer ailleurs ;
  - coût médian ≈ 0,8 R → **le problème EST le coût**, et le levier n'est plus
    le motif mais la distance au stop : élargir les stops, viser des horizons
    plus longs, ou cesser de scalper cet instrument à ce spread.
- ⚠️ **Ce que ça ne dira pas.** Un coût élevé ne prouve pas qu'un edge existe
  sous les frais : un R brut négatif reste négatif. Cette colonne sert à
  savoir **où chercher**, pas à conclure qu'on a trouvé.
- ⚠️ **Quatrième occurrence du même défaut** : l'horizon (26/08), la chaîne
  (16/09), l'écart au hasard (20/09), le coût (20/09). À chaque fois une valeur
  **déjà calculée** qui mourait avec le processus. Le défaut n'est pas le calcul,
  c'est de croire qu'un nombre lu dans un log est un nombre enregistré.

---

## ⚡ EXPÉRIENCE ARMÉE — `sweep_avec_structure_m15` sur XAU/USD, argent réel

**Déclarée le 2026-09-21, AVANT armement.** Demandée par Pascal, qui a mis de côté
une enveloppe qu'il peut perdre sans conséquence. Cette section existe pour que le
résultat ne puisse pas être surinterprété dans un sens ni dans l'autre.

### Ce que cette expérience mesure — et ce n'est PAS l'edge

⛔ **Le laboratoire donne 700 trades par nuit sur cette chaîne ; le réel en donnera
deux ou trois par jour.** Distinguer −0,01 R de zéro en direct prendrait des mois.
Cette expérience ne peut donc pas trancher la question de l'edge, et ne sera jamais
lue comme le faisant.

🔑 **Ce que seul le réel enseigne** : le prix de remplissage contre le prix annoncé,
le spread réellement payé, le stop honoré ou non, le glissement. Aucun rejeu ne le
simule — le laboratoire facture un spread lu sur un seul tick et suppose des
remplissages parfaits. C'est la seule inconnue que l'argent réel lève.

### L'espérance déclarée d'avance

Mesure de la nuit du 21/09, cellules XAU/USD 5 min, **pondérées par les trades** :

| sens | n | R net | coût | R brut |
|---|---|---|---|---|
| haussier | 127 | **−0,009** | 0,024 | +0,014 |
| baissier | 122 | **−0,013** | 0,023 | +0,010 |

- **Espérance annoncée : ≈ −0,011 R par trade.** Sur 30 ordres, ≈ **−0,33 R au
  total**, soit un tiers du risque d'un seul trade. C'est le prix de l'information.
- ⛔ **Et la moyenne non pondérée aurait menti.** Sur l'ensemble des paires, la
  moyenne des moyennes de cellules donnait **+0,195 R** — portée par des cellules à
  3, 4 et 9 trades à +1,0 R. Pondérée : **−0,131 R**. Le même piège que
  `_R_par_politique` avait payé le 14/09. Toute lecture de cette expérience se fait
  pondérée par les trades, jamais par les cellules.

### Le périmètre, et pourquoi il est si étroit

- **XAU/USD seulement.** ⛔ **XAG/USD est exclu** : coût de **0,19–0,20 R** par
  trade contre 0,023 sur l'or, et c'est lui qui portait toute la perte de la chaîne
  (355 des 706 trades de la nuit).
- **5 min seulement** : c'est la seule échelle où la chaîne produit des cellules.
- ⛔ **`niveau_majeur` n'est PAS armée** : `n` moyen de 2,3 et 3,4 par cellule. Elle
  ne tirerait pratiquement jamais, et l'armer donnerait l'illusion d'un essai.
- **Taille minimale**, plafond de perte journalière et kill switch existants inchangés.

### La règle d'arrêt, écrite d'avance

**30 ordres ou 20 % de l'enveloppe, le premier atteint.** Puis on désarme et on lit.

⛔ **Ce qu'on ne lira pas : le P&L.** Sur 30 trades il ne dit rien — un tirage au
hasard de même taille produit régulièrement ±1 R de moyenne. Ce qui sera lu :
remplissage contre entrée annoncée, spread réel contre spread supposé, stops
honorés, glissement. Trois chiffres, aucun verdict sur la méthode.

### Ce qui bloquait, et qu'il faut ouvrir

⚠️ `chaine:sweep_avec_biais_haussier` était **déjà armée** et n'a jamais produit un
ordre en trois semaines. Cause : deux portes en amont du registre des chaînes —
`pattern_not_allowed` (6 486 refus sur `liquidity_sweep_*` depuis le 01/09) et
`horizon_not_allowed` (6 726). Armer une chaîne sans ouvrir le motif et l'horizon
ne produit rien. Et `sl_too_close` (3 214 refus) en écartera encore une partie :
c'est le même problème de distance au stop qui fait le coût.

### L'asymétrie assumée

Les motifs qui tradent aujourd'hui (`momentum`, `breakout`) sont documentés
**négatifs** dans `config/settings.py` — respectivement −0,037 et −0,088 R/trade —
et n'y sont que par antériorité. Armer un balayage à −0,011 R n'est donc pas un
relâchement de la discipline : c'est **moins mauvais** que ce qui tourne déjà. Ce
constat ne justifie pas l'armement, il en borne le reproche.

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

---

## 🔬 Balayage de la LARGEUR DU STOP sur l'or — déclaré le 2026-09-30, AVANT le code

Xavier a demandé s'il fallait **réduire** le TP et le SL de l'or. Réduire le TP
est déjà réfuté ([banc des objectifs du 15/09] : aucune cible de 0,5 à 3,5 R ne
bat 1,8, et rapprocher est **pire** à 15 min, t = −2,41 / −2,58 / −2,81). Le
**stop**, lui, n'a jamais été balayé : le banc des objectifs le tenait constant.

### Ce que le code dit déjà, et qui motive le sens du balayage

Dans `laboratoire_or`, le coût passe à `_issue` sous la forme `spread / risque`.
Le spread est une distance de **prix** ; `risque` **est** la distance au stop.
⇒ **le coût en R est inversement proportionnel à la largeur du stop.** Mesuré
sur l'or (spread 0,20 pt, stop médian 16,2 pt) : stop ÷2 ⇒ coût 0,0247 R ;
stop ×2 ⇒ coût 0,0062 R.

C'est donc **élargir**, pas resserrer, qui allège la charge. Le balayage teste
cette direction.

### La règle

Mêmes entrées, même objectif **en R** (1,8), seule la largeur du stop change :
`risque_k = k × risque_observé`, pour **k ∈ {0,5 ; 0,75 ; 1 ; 1,5 ; 2 ; 3}**.

⚠️ Rejeu **séquentiel par k** : un stop plus large tient la position plus
longtemps et décale toutes les entrées suivantes. Figer les entrées une fois
pour toutes fabriquerait une comparaison fausse — c'est le piège que
`comparer_sorties` existe pour fermer.

⚠️ `k` n'est **pas** un réglage de production : en réel, un stop deux fois plus
large impose un lot deux fois plus petit pour tenir le même risque en euros.
Le R est justement l'unité invariante au lot, donc le balayage est licite —
mais il ne dit rien sur la taille de position.

⚠️ Le filtre `PLACEBO_PCT` (0,1 % du prix) reste appliqué **après**
multiplication : à k = 0,5 une partie des cellules disparaîtra, et c'est le
résultat, pas un défaut. 18 des 163 stops réels sont **déjà** sous ce seuil.

### Les prédictions falsifiables — écrites AVANT de coder

1. **Mécanique** : le coût mesuré par trade suivra `spread / (k × risque)` à
   ±15 %. Si cette identité ne sort pas, **le banc est faux** et rien d'autre
   n'est interprétable. C'est le contrôle de l'appareil, pas de l'hypothèse.

2. **Monotonie** : le R moyen sera **croissant en k** sur 0,5 → 3. En
   particulier `R_moyen(k=0,5) < R_moyen(k=1) < R_moyen(k=2)`.

3. ⛔ **LA PRÉDICTION QUI COMPTE — je prédis un échec** : **aucun k ne franchira
   le plafond du hasard.** L'écart au contrôle aléatoire (30 graines, sens
   respecté) restera sous `plafond_hasard(6)` pour les six valeurs. Autrement
   dit : élargir le stop **retire une charge, ne crée pas d'avantage**, parce
   que l'entrée 5 min vaut ≈ −0,008 R avant frais — rien.

4. **Ce qui rendrait l'expérience intéressante** : si un k franchit le plafond,
   c'est un fait neuf, et il devra être répliqué en **validation croisée sur
   les 20 instruments** avant toute décision de production.

### La règle d'arrêt, écrite d'avance

- Prédiction 1 fausse ⇒ on **arrête** et on répare le banc. Aucun verdict.
- Prédictions 2 et 3 vraies ⇒ **verdict négatif assumé** : ne pas toucher au
  stop en production, et l'écrire dans les verdicts « ne pas refaire ».
- Prédiction 3 fausse ⇒ passer en validation croisée 20 instruments, plafond
  recalculé sur le **total** des tests, jamais par instrument.

⛔ Aucun seuil neuf : `k` réutilise le `risque` observé, l'objectif reste 1,8 R,
le spread reste celui du courtier, `PLACEBO_PCT` et `MAX_BOUGIES_TENUE` sont
inchangés. Chaque réglage neuf serait un degré de liberté, donc de l'edge
fabriqué.

### ⛔ RÉSULTAT du balayage de la largeur du stop — 2026-09-30, prédiction `47b5c6c`

90 jours, 17 500 bougies M5, 38 cellules, 30 graines de contrôle, spread
**épinglé à 0,20** (voir plus bas pourquoi).

| k | n | stop % du prix | coût R | R moyen | t | contrôle | z |
|---|---|---|---|---|---|---|---|
| 0,50 | 10 134 | 0,148 % | 0,0316 | −0,0239 | −1,79 | −0,0974 | +6,88 |
| 0,75 | 10 277 | 0,182 % | 0,0257 | −0,0420 | −3,19 | −0,0762 | +4,00 |
| **1,00** | **8 386** | 0,220 % | **0,0213** | **−0,0451** | −3,10 | −0,0620 | +1,68 |
| 1,50 | 5 426 | 0,312 % | 0,0150 | −0,0349 | −1,93 | −0,0305 | −0,52 |
| 2,00 | 3 586 | 0,417 % | 0,0113 | −0,0257 | −1,16 | −0,0155 | −1,11 |
| 3,00 | 1 988 | 0,641 % | 0,0074 | −0,0237 | −0,80 | −0,0125 | −0,91 |

**P1 — l'appareil est validé.** Coût à k=1 : **0,0213** contre **0,0207**
publié, soit 3 % d'écart. n = **8 386** contre **8 362**, soit 0,3 %. Le R moyen
reste à −0,0451 contre −0,0306 : fenêtre de 90 jours décalée de 15 jours, sur
une grandeur dont le `t` vaut −3.

**P2 — FAUSSE.** La courbe n'est pas croissante mais en **U** : moins négative
aux extrêmes (k=0,5 et k=3), pire au milieu (k=1). ⚠️ Non interprétable comme
un effet de gestion : le nombre de trades passe de 10 134 à 1 988, donc la
POPULATION change avec k. C'était nommé d'avance.

**P3 — VRAIE, et c'est le verdict.** Aucun k ne franchit le plafond de 1,654.
Le coût tombe bien de 0,0213 à **0,0074 R** entre k=1 et k=3 — conforme à
`spread/risque` — mais **le R moyen reste négatif partout**. Le meilleur, k=3,
vaut −0,0237 R avec t = −0,80 et **z = −0,91 contre son contrôle** : pas mieux
que le hasard.

⇒ **Ne pas toucher au stop en production.**

#### 🔑 Ce que ce banc apprend EN PLUS, et qui durcit le verdict du 15/09

Retirer **65 % du coût** (0,0213 → 0,0074 R) laisse la perte quasi intacte
(−0,0451 → −0,0237 R). Avant coûts, l'entrée vaut donc **−0,016 à −0,024 R**
selon k — et non « ≈ −0,008 R, rien » comme publié. ⚠️ À réconcilier : c'est
une soustraction, pas une mesure directe, et la fenêtre diffère.

#### ⛔ DÉFAUT DE MÉTHODE TROUVÉ, qui vaut pour TOUS les bancs du labo

`reglage_or._bougies_et_spread` rend `ask - bid` du tick **VIVANT** : 90 jours
de rejeu sont facturés au spread d'un **seul instant**. Mesuré le 30/09 à
21h45 Paris : **0,50** — contre **0,20** au banc du 15/09, et **0,15-0,21**
dans les 96 relevés de `spreads_hors_crypto.jsonl` (`mt5_spread_pct` 0,0036 à
0,0051 % d'un or à 4 200).

Lancé au spread vivant de 0,50, ce banc rendait un coût de 0,0531 R et un
R moyen de −0,0792 : **deux bancs lancés à deux heures différentes ne sont pas
comparables**. ⇒ Épingler le spread, ou prendre la médiane des relevés, mais
jamais le tick de l'instant.

---

## 🔬 `fvg_up` sur l'or — TEST HORS ÉCHANTILLON, déclaré le 2026-09-30 AVANT le code

`fvg_up` acheteur, or 5 min, est la **meilleure cellule de ~4 580** mesurées par
le laboratoire. Dix nuits consécutives la donnent positive : R médian
**+0,133**, `t_vs_hasard` médian **+2,47**, max +2,73, n ≈ 170.

### ⛔ Pourquoi ces dix nuits ne prouvent rien

Chaque nuit rejoue une fenêtre **glissante de 90 jours** : deux nuits
consécutives partagent **89 jours sur 90**. « 10/10 positif » est donc **une**
mesure regardée dix fois. C'est le piège nommé le 25/09 — « 11 nuits de
fenêtres qui SE RECOUVRENT ≠ une fenêtre disjointe » — et il a fait passer la
chaîne armée de t≈5 à **t=0,72** sur données neuves.

### La règle du test

- **Fenêtre DISJOINTE** : les jours **90 à 365** avant aujourd'hui. Aucun jour
  commun avec les dix nuits. Bornes de dates imprimées à l'exécution, et le
  test s'arrête si le recouvrement n'est pas nul.
- Cellule unique : `fvg_up` / `buy` / `XAU/USD` / 5 min. Aucun balayage.
- **Spread épinglé à 0,20** — le tick vivant valait 0,50 ce soir, et deux bancs
  à deux heures différentes ne sont pas comparables (mesuré le 30/09).
- Contrôle aléatoire **30 graines**, **sens respecté**.
- Validation croisée sur les 20 instruments servis, plafond sur le **total**.

### ⚠️ La barre, et l'honnêteté sur son niveau

`plafond_hasard(1) = 0,798` pour **un** test spécifié d'avance.
`plafond_hasard(20) = 2,167` pour la validation croisée.

⛔ **0,798 est une barre BASSE**, et l'utiliser seule serait blanchir un
candidat **sélectionné parmi 4 580** en candidat pré-spécifié. La sélection a eu
lieu sur les 90 derniers jours ; la fenêtre disjointe est de la donnée neuve,
ce qui rend le test licite — mais pas suffisant. ⇒ **Deux conditions
cumulatives**, pas une.

### Les prédictions falsifiables

1. **Effondrement** : `t_vs_hasard` sur la fenêtre disjointe sera
   **inférieur à +2,47**, la médiane des fenêtres glissantes. C'est la
   prédiction qui teste le recouvrement, et c'est celle à laquelle je crois.
2. **Concordance absente** : sur les 20 instruments, **moins de la moitié** des
   cellules `fvg_up` acheteur seront positives, et **aucune** ne franchira
   `plafond_hasard(20) = 2,167`. (Sur la dernière nuit : 12 positives sur 44.)
3. ⚠️ **Ce que je ne prédis PAS** : je ne sais pas si l'or seul franchira
   0,798. J'avais annoncé un échec avant de connaître cette valeur ; contre une
   barre aussi basse, je retire cette assurance. Dire « je ne sais pas » ici
   vaut mieux qu'une bravade que le résultat démentirait.

### La règle de décision, écrite d'avance

| résultat | décision |
|---|---|
| Recouvrement non nul | ⛔ **test invalide**, aucun verdict |
| Or > 0,798 **ET** concordance > 2,167 | 🔬 premier candidat sérieux du projet — passer en `TELEGRAM`, jamais directement en `AUTO_EXEC` |
| Or > 0,798 mais concordance absente | ⛔ **non retenu** — profil de la chaîne réfutée |
| Or < 0,798 | ⛔ **réfuté**, à inscrire dans les verdicts |

⛔ Aucun seuil neuf : `PLACEBO_PCT`, `FENETRE`, `MAX_BOUGIES_TENUE`, l'objectif
du setup et `plafond_hasard` sont ceux du laboratoire.

---

## 🔬 LA MAIN — test HORS ÉCHANTILLON, déclaré le 2026-10-01 AVANT le code

Le 08/09, la main a été mesurée comme **l'effet le plus significatif du
projet** : **+0,728 R** contre le contrefactuel, **t=+4,07** sur 44 sorties ;
33 stops évités. Sur le vrai chemin intra-trade : main **+0,459 R (t=+5,04)**
contre **+0,040 R (t=+0,17)** pour les SL/TP laissés courir.

⛔ Cette mesure n'a **jamais** été rejouée. Deux effets se sont effondrés hors
échantillon en une soirée — la chaîne armée (t≈5 → 0,72) et `fvg_up`
(+2,47 → +0,101). **Le plus fort résultat du projet doit subir le même test.**

### La donnée

**38 contrefactuels résolus sur `admin_live` postérieurs au 08/09 18h00** —
jamais vus par la mesure d'origine, et d'une taille comparable à ses 35-44.
Fenêtre de référence : 32 résolus antérieurs.

### ⚠️ La tension d'UNITÉ que ce test doit trancher

| | médiane | moyenne |
|---|---|---|
| fermetures manuelles avant 08/09 (n=74) | **+1,57 €** | **+0,02 €** |

La note du 08/09 citait la **médiane**. La **moyenne** est nulle : la règle
gagne souvent et perd gros parfois. Or `+0,459 R` est une **moyenne en R**, sur
des trades dont le risque varie de **8 à 65 €**.

🔑 Sommer des R sur des risques incomparables sur-pondère les petits risques —
c'est le piège d'unité déjà payé par le régulateur. Le test doit donc mesurer
**dans les deux unités**, et dire laquelle paie.

### La barre

**|t| > 2,0**, la même que le test pré-enregistré de la chaîne. ⛔ Pas
`plafond_hasard(1) = 0,798` : c'est le |t| **attendu** sous l'hypothèse nulle,
pas un quantile — bien trop permissif pour un test unique. (Pour `fvg_up` cette
barre permissive avait été utilisée et le résultat, 0,101, échouait quand même.)

### Les prédictions falsifiables

1. **Appareil** : sur les 32 trades antérieurs, la mesure doit reproduire un
   gain de la main **> +0,4 R** avec **t > 3**. Sinon on s'arrête : aucun
   verdict, l'appareil ne reproduit pas.
2. **Effondrement partiel** : sur les 38 trades neufs, le gain en R sera
   **inférieur à +0,728 R**. Trois effets sur trois se sont effondrés ; je
   prédis le même sens, mais **pas** une disparition.
3. **La main SURVIT en R** : je prédis que le gain restera **> +0,3 R avec
   |t| > 2,0** — ce serait le **premier effet de ce projet à survivre à un test
   hors échantillon**. C'est une prédiction risquée et je l'assume.
4. **⛔ Mais l'euro dira moins que le R** : le gain par trade en euros sera
   **inférieur à la moitié** de ce que le gain en R laisse croire une fois
   multiplié par le risque médian. Autrement dit : l'effet est réel mais
   **sur-représenté par la mesure en R**.

### La règle de décision, écrite d'avance

| résultat | décision |
|---|---|
| P1 fausse | ⛔ **aucun verdict**, réparer l'appareil |
| R > +0,3 et \|t\| > 2,0 **et** euro > 0 | ✅ **effet confirmé** — le seul du projet |
| R survit mais euro ≈ 0 ou négatif | ⚠️ **effet d'unité** : vrai en R, sans valeur en caisse |
| R < +0,3 ou \|t\| < 2,0 | ⛔ **effondré comme les deux autres** |

⛔ Aucun réglage neuf : contrefactuel stocké, `r_realise`/`r_contrefactuel` du
laboratoire, test **apparié** sur les mêmes trades.

---

## 🔬 LA MAIN EN EUROS — déclaré le 2026-10-01, jugé sur une fenêtre qui N'EXISTE PAS ENCORE

Le test du 01/10 (`accafd0` → `2591349`) a donné : critère déclaré en R
**ÉCHOUÉ** (+0,338 R, t=+1,59 contre une barre de 2,0), mais **+231,81 €** et
**25 stops évités sur 37**. Et le piège d'unité joue à l'inverse de ma
prédiction : le R **sous-estime** l'euro d'un facteur **3,24**.

⛔ Cet euro n'était **pas** le critère pré-enregistré. Le promouvoir en verdict
serait déplacer la cible après le tir. Il est donc déclaré **ici**, avant, pour
être jugé sur des trades **qui n'ont pas encore eu lieu**.

### La fenêtre — la plus propre possible

Trades `admin_live` fermés **`MANUAL`** avec contrefactuel résolu, **clôturés
après le 2026-10-01 00h00**. 🔑 Au moment de cette déclaration, cette donnée
**n'existe pas** : aucune sélection n'est possible, même involontaire.

### Le critère PRIMAIRE, en euros

`gain_eur = (r_realise − r_contrefactuel) × risque_eur`, trade par trade, avec
le `risk_eur.calculer` de la production. Test **apparié**.

**Retenu si et seulement si** : moyenne **> +3,00 €/trade** ET **|t| > 2,0**.

⚠️ Le seuil de 3 € est fixé **maintenant**, à moitié du +6,27 € observé — pour
laisser la place à une régression vers la moyenne sans rendre le test
inutilement facile.

### ⛔ Les garde-fous contre un seul gros trade

L'euro est dominé par les trades à gros risque : un seul peut porter le
verdict. Trois conditions **cumulatives** :

1. la **médiane** doit être positive elle aussi ;
2. la **moyenne tronquée à 10 %** doit rester **> +1,50 €** ;
3. retirer le **meilleur trade** ne doit pas faire passer la moyenne sous
   **+1,50 €**.

Une seule de ces trois qui tombe ⇒ **effet porté par la queue, non retenu**.

### Taille minimale, et interdiction de regarder avant

**Jugé quand n ≥ 30** contrefactuels résolus dans la fenêtre, **et pas avant**.
Au rythme observé (~37 par trois semaines), c'est **fin octobre**.

⛔ **Aucune lecture intermédiaire.** Regarder à n=12 puis attendre un chiffre
qui plaît serait de l'arrêt optionnel — la forme de tricherie la plus facile et
la plus invisible. La sonde programmée refuse de mesurer sous n=30 et ne parle
qu'une fois.

### Le critère SECONDAIRE, explicitement NON éligible à un verdict

Le gain en **R** sera publié à titre de continuité (il valait +0,338 R,
t=+1,59). ⛔ Il ne peut **pas** retenir l'effet à lui seul cette fois : il a
déjà échoué sur sa propre barre, et le reprendre comme critère principal serait
lui offrir une seconde chance après coup.

⚠️ De même, la règle « couper les achats » (achats coupés 76,7 % contre 34,2 %
pour les ventes, z=+4,38) reste **dérivée de ses propres données**. Elle n'est
pas testée ici et n'a pas de barre : la mentionner ne la valide pas.

### La règle de décision, écrite d'avance

| résultat | décision |
|---|---|
| n < 30 à la date de lecture | ⏳ **on attend**, aucun verdict |
| moyenne > +3 € · \|t\| > 2,0 · les 3 garde-fous tiennent | ✅ **PREMIER effet confirmé du projet** |
| seuils atteints mais un garde-fou tombe | ⚠️ **porté par la queue** — non retenu |
| moyenne < +3 € ou \|t\| < 2,0 | ⛔ **réfuté** ; la main n'est pas mécanisable |

⛔ Et si le trading est arrêté, ou si les fermetures manuelles cessent, la
fenêtre est **déclarée incomplète** — pas jugée sur ce qu'elle contient.

---

## 🔬 LA MÉTHODE VIVIEN, ÉPROUVÉE EN BLOC — déclaré le 2026-10-01 AVANT le code

Demande de Xavier : « je veux que la méthode Vivien soit éprouvée ». Objet
exact, relevé dans le laboratoire : **22 chaînes** (`sweep_sur_order_block`,
`choch_puis_fvg`, `cassure_killzone_londres`, `avalement_en_premium`,
`prise_en_accumulation`, `niveau_confirme_volume`, `sweep_avec_structure_m15`,
`sweep_sur_niveau_majeur`, `sweep_avec_biais`, `cassure_confirmee_volume`,
`sweep_puis_structure`, chacune en deux sens) **+ 22 motifs** (`order_block`,
`liquidity_sweep`, `poc_return`, `opening_range`, `retest`, `reintegration`,
`double_sweep`, `fvg`, `fvg_inverse`, `bos`, `choch`, deux sens chacun).

⇒ **168 des 232 cellules** mesurées chaque nuit sur l'or, soit **72 %** du
laboratoire.

### ⛔ Ce qui est DÉJÀ tranché, et qu'on ne refait pas

Chaque cellule est mesurée chaque nuit. Bilan sur l'or, toutes nuits
confondues : **4 570 `INSUFFISANT`, 10 `REFUTE`, ZÉRO `RETENU`**. Et la
meilleure de toutes, `fvg_up`, vient d'être **réfutée hors échantillon** le
30/09 (+2,47 → **+0,101** contre une barre de 0,798).

### 🔬 La question RÉELLEMENT neuve

Un test **par cellule** n'a de puissance que sur ~50 à 170 trades, et le
plafond de multiplicité pour 168 cellules est écrasant. Un effet **faible mais
réel**, commun à la famille, serait donc invisible.

⇒ **On met TOUT en commun en UNE seule mesure** : tous les trades produits par
les 44 constructions Vivien, sur la même fenêtre, contre le même contrôle. Un
seul test, une seule barre, et un échantillon d'un ordre de grandeur supérieur.
Cela n'a jamais été fait.

### Le protocole

- **Fenêtre DISJOINTE** : jours **90 à 365**, jamais vus par les nuits
  glissantes. Recouvrement vérifié nul, arrêt sinon.
- **Or uniquement** pour le verdict : `CHAINES_PAIRES` est figé sur `XAU/USD`
  dans le code, les chaînes n'existent pas ailleurs.
- **Spread épinglé à 0,20**, la valeur de référence. ⛔ Le tick vivant valait
  **0,50** dans la nuit du 30/09 : deux bancs à deux heures différentes ne sont
  pas comparables.
- **Contrôle aléatoire 30 graines, sens respecté**, au risque médian des trades
  Vivien eux-mêmes.
- Garde-fous `COUT_MAX_R = 0,25` et `R_MAX_PLAUSIBLE = 3` : la mesure refuse de
  publier un chiffre absurde.

### La barre

**|t| > 2,0** contre le contrôle, la même que les deux tests pré-enregistrés
précédents. ⛔ Un seul test est éligible au verdict — le **bloc entier**. La
décomposition chaînes / motifs sera publiée pour lecture mais **ne peut pas
retenir l'effet** : trois tests éligibles rouvriraient la multiplicité que ce
protocole ferme.

### Les prédictions falsifiables

1. **Appareil** : le bloc Vivien doit produire **n > 3 000** trades sur la
   fenêtre disjointe. En dessous, la mise en commun n'apporte pas la puissance
   qui justifie ce test, et on le dit.
2. ⛔ **Je prédis l'ÉCHEC** : **|t| < 2,0**. Et cette fois je l'assume sans
   réserve, contrairement à `fvg_up` — l'argument n'est pas un pressentiment :
   4 580 cellules mesurées n'en ont jamais retenu une, et la meilleure de
   toutes s'est effondrée hors échantillon. Mettre en commun des cellules dont
   aucune ne gagne ne fabrique pas un gagnant.
3. **Signe** : le R moyen du bloc sera **négatif**, entre −0,05 et −0,35 R.

### La règle de décision, écrite d'avance

| résultat | décision |
|---|---|
| n < 3 000 ou recouvrement non nul | ⛔ **test invalide**, aucun verdict |
| \|t\| > 2,0 et R moyen > 0 | 🔬 **fait neuf** — à répliquer avant toute production |
| \|t\| > 2,0 et R moyen < 0 | ⛔ la méthode est **mesurablement NUISIBLE** |
| \|t\| < 2,0 | ⛔ **RÉFUTÉE en bloc** — à inscrire dans les verdicts |

⚠️ Et quel que soit le résultat : **il ne change RIEN aux portes**. Aucun motif
Vivien n'est dans la liste blanche de l'or, et ce test ne demande pas qu'on
l'y mette.

---

## ⚡ EXPÉRIENCE EN ARGENT RÉEL — les motifs Vivien sur l'or, `admin_live`

Demandée explicitement par Xavier le 2026-10-01, **après** que les chiffres du
laboratoire lui ont été présentés. Décision assumée, pas une découverte.

### ⛔ Ce que la mesure dit AVANT d'ouvrir — c'est le contexte du pari

| construction | n | R moyen | t vs hasard |
|---|---|---|---|
| `double_sweep_up` | 16 | **−0,840** | **−4,61** ⛔ pire que le hasard |
| `poc_return_up` | 88 | −0,349 | −2,04 |
| `chaine:sweep_sur_order_block_haussier` | 76 | **−0,220** | −1,39 |
| `fvg_up` (le meilleur) | 170 | +0,117 | +2,02, **réfuté hors échantillon** |

Bilan or, toutes nuits : **4 570 `INSUFFISANT`, 10 `REFUTE`, 0 `RETENU`**.

⇒ **L'espérance déclarée d'avance est NÉGATIVE.** Au risque médian mesuré de
**5,73 €** et à un R moyen de famille de l'ordre de **−0,2**, le coût attendu
est **≈ −1,15 € par ordre**. Sur le quota déclaré, **≈ −23 €**.

### ⛔ LE DÉFAUT DU GARDE-FOU EXISTANT, qu'il faut réparer d'abord

Le projet a déjà le bon outil : `TRADE_DEROGATION_PUSHES`. **Un jeton lève les
DEUX portes** (`pattern_not_allowed` et `fees_exceed_edge`) et elles **se
referment seules** au quota — « retirer la whitelist le temps de voir laisse
toujours une fenêtre ouverte plus longtemps que prévu ».

⚠️ Mais il compte les pushes d'**`admin_legacy`**, parce qu'à sa conception ce
compte **pilotait** le réel par le miroir. Or `_mirror_active()` est **False**
depuis le 04/09. Donc, tel quel :

- les ordres Vivien sur `admin_live` **ne consommeraient pas** le quota ;
- les ordres **ordinaires** d'`admin_legacy` le consommeraient ;
- et les portes s'ouvriraient **aussi sur `admin_legacy`**, non demandé.

⇒ Le quota doit compter **les pushes que la dérogation a effectivement
permis** : ceux dont le motif n'est **pas** dans la liste blanche de leur
destination. C'est la seule définition qui borne la chose mesurée.

### Le périmètre, étroit par construction

- **`admin_live` seulement**, **`XAU/USD` seulement**.
- Seuls les motifs **hors liste blanche** consomment un jeton ; les 8 motifs
  classiques continuent comme avant, sans toucher au quota.
- Les portes non concernées **restent fermées** : verrou d'intégrité, kill
  switch, plafond journalier, plafond par paire, corrélation, `sl_too_close`,
  `below_confidence` (barre 66), `price_divergence`, et les 8 portes du pont.

### La règle d'arrêt, écrite d'avance

**Quota : 20 pushes dérogatoires.** Atteint ⇒ les deux portes se referment
**seules**, sans dépendre de personne.

Et une alerte Telegram, **et une fermeture immédiate**, au premier des trois :

| déclencheur | seuil |
|---|---|
| ordres dérogatoires | **20** |
| perte cumulée sur ces ordres | **−40 €** |
| durée | **7 jours** |

⛔ Aucune prolongation « pour voir un peu plus ». Reconduire exigerait une
nouvelle déclaration, avec les chiffres obtenus en face.

### La prédiction, déclarée d'avance

**Je prédis une perte.** R moyen entre **−0,05 et −0,40** sur les ordres
dérogatoires, et un P&L net **négatif**. Si le résultat est positif, ce sera un
fait à répliquer — **pas** une validation : 20 ordres ne renversent pas 4 580
cellules.

⚠️ Et quoi qu'il arrive : ces ordres seront marqués pour être **exclus des
verdicts de stratégie**. Le P&L d'une dérogation n'est pas une mesure d'edge —
c'est la leçon des 9 ordres du fail-open de septembre.

---

## La CIBLE SUR LA LIQUIDITÉ — déclaration du 2026-10-01

### D'où vient la question

Le 01/10 à 03h06, un `momentum_up` 4h sur USD/JPY est sorti avec un objectif à
**160,445**. Mesuré le même jour sur les 4h du courtier : le plus haut des
**42 derniers jours** vaut 160,405, celui des 10 derniers 159,029. L'objectif
était donc posé **au-dessus de tout plafond atteint depuis six semaines**, sans
que rien ne l'ait regardé — `calculate_trade_setup` pose `TP₁ = risque × 1,8`,
point final.

Or une brique qui fait exactement ce qu'il faudrait existe déjà :
`_niveaux_poc` pose sa cible sur `market_profile.niveaux_liquidite()`, c'est-à-dire
le plus haut sommet fractal de la fenêtre — un plafond **déjà atteint**. Elle est
réservée à `poc_return_up/down`, qui n'a le droit de trader nulle part.

### La règle mise à l'épreuve

Quatre variantes de l'objectif, le stop et l'entrée inchangés :

| | variante | objectif |
|---|---|---|
| **A** | référence | `1,8 × risque` — la règle en place |
| **B** | **plafonnée** | `min(1,8 R, niveau de liquidité)`, refus si < `POC_RR_MIN` |
| **C** | niveau seul | le niveau de liquidité, même s'il est **plus loin** que 1,8 R |
| **D** | **placebo de longueur** | objectif FIXE = médiane des objectifs de B, **mêmes trades admis que B** |

**D est le contrôle qui décide.** Plafonner raccourcit mécaniquement l'objectif,
et raccourcir a déjà été mesuré comme coûteux sur l'or (banc du 08/09 : R moyen
croissant de 1,0 R à 2,5 R). Sans D, un écart entre A et B serait illisible : on
ne saurait pas s'il vient du **niveau** ou de la **longueur**. D porte la même
longueur que B sans regarder le moindre niveau.

### Aucun réglage neuf — ce qui est repris, et d'où

- **La cible** : `niveaux_liquidite()["au_dessus"/"en_dessous"]`, **sans marge**,
  exactement comme `_niveaux_poc` la pose aujourd'hui.
- **Le plancher** : `POC_RR_MIN = 1,0`, déjà mesuré sur 414 setups réels.
- **La fenêtre** : `bougies[i-FENETRE:i]` — ce que le détecteur a vu, pas une
  bougie de plus. La bougie d'entrée ne sert jamais à calculer le niveau.
- **Le rejeu** : `_issue`, `detections`, `controle_aleatoire`, `_stat`, `_welch`,
  `plafond_hasard`, `PLACEBO_PCT`, `_bougies_et_spread`. Rien de réécrit.

### Ce que ce banc NE mesure PAS

⛔ Il rejoue du **5 min**. La question est née d'un trade **4h** sur une paire
forex. `_bougies_et_spread` est câblé en M5 et le recâbler fabriquerait un
second banc incomparable au premier. **Le cas 4h n'est pas couvert**, et aucun
verdict d'ici ne doit lui être appliqué.

### La prédiction, déclarée AVANT de produire un chiffre

**Je prédis que le plafonnement dégrade.**

- **P1** — `R(B) < R(A)` sur la fenêtre de 90 jours. Raccourcir coûte, et le
  filtre de refus ne compensera pas.
- **P2** — aucune des 4 variantes ne franchit `plafond_hasard(4)` avec un R positif.
- **P3** — **B ne se distingue pas de D** : `|R(B) − R(D)|` reste sous l'écart-type
  du contrôle aléatoire. Autrement dit, ce que fait B s'explique par la
  **longueur** de l'objectif, pas par le niveau visé.
- **P4** — hors échantillon (jours 90 → 365, jamais rejoués par les nuits du
  laboratoire), le signe de `R(B) − R(A)` **ne tient pas**.

### La règle de décision, écrite d'avance

**RETENU** seulement si les quatre conditions tiennent **ensemble** :
B bat A, **et** B bat D, **et** B franchit `plafond_hasard(4)`, **et** le signe
de l'écart se répète hors échantillon.

Un seul manquement ⇒ **⛔ NON RETENU**, et `PATTERN_TP1_RR = 1,8` reste en place.
Un résultat positif sur la seule fenêtre vue ne vaut rien : c'est exactement ce
qui a fait paraître bonnes les 75 variantes précédentes.

### Le résultat — mesuré le 2026-10-01, `afcd5c7`

Or 5 min, 70 893 bougies, spread épinglé à 0,20, 38 cellules motif × sens,
30 graines de contrôle. Deux fenêtres **disjointes**, recouvrement nul.

**Fenêtre VUE — 03/07 → 01/10, 17 587 bougies**

| variante | n | obj méd | R moyen | t brut | hasard | t_vs |
|---|---|---|---|---|---|---|
| A référence | 8 392 | 1,800 | **−0,0431** | −2,96 | −0,0607 | +1,13 |
| B plafonnée | 7 564 | 1,800 | **−0,0634** | −4,29 | −0,0734 | +0,65 |
| C niveau seul | 6 474 | 2,644 | **−0,0984** | −4,49 | −0,1017 | +0,14 |
| D placebo | 7 408 | 1,800 | **−0,0636** | −4,12 | −0,0736 | +0,62 |

**Fenêtre JAMAIS VUE — 01/10/2025 → 03/07/2026, 53 306 bougies**

| variante | n | obj méd | R moyen | t brut | hasard | t_vs |
|---|---|---|---|---|---|---|
| A référence | 25 612 | 1,800 | **−0,0022** | −0,27 | −0,0791 | +8,60 |
| B plafonnée | 23 059 | 1,800 | **−0,0211** | −2,47 | −0,0931 | +8,05 |
| C niveau seul | 19 200 | 2,600 | **−0,0316** | −2,43 | −0,1277 | +7,09 |
| D placebo | 22 608 | 1,800 | **−0,0159** | −1,77 | −0,0860 | +7,51 |

**P1 VRAIE** · **P2 VRAIE** · **P3 VRAIE** · **P4 FAUSSE**

⛔ **NON RETENU.** `PATTERN_TP1_RR = 1,8` reste en place.

#### 🔑 Ce que P3 tranche, et c'est le cœur

`|R(B) − R(D)| = 0,0002 R` — **deux dix-millièmes**. Le plafonnement ne se
distingue pas d'un objectif fixe de même longueur posé **sans regarder le
moindre niveau**. Ce que B fait s'explique entièrement par la longueur de la
cible et par son filtre d'admission ; le niveau de liquidité n'y apporte
**rien**. Sans D, l'écart B−A aurait pu passer pour un effet du niveau.

#### ⚠️ Ma prédiction P4 était FAUSSE, et il faut le dire

J'avais prédit que le signe de `R(B) − R(A)` ne tiendrait pas hors échantillon.
**Il tient** : −0,0203 sur la fenêtre vue, −0,0189 sur 23 059 trades jamais
rejoués. La dégradation n'est donc pas un accident de fenêtre, elle **se
réplique**. Mon erreur renforce la conclusion négative au lieu de l'affaiblir —
mais elle reste une prédiction ratée, et elle compte comme telle.

#### Pourquoi le plafonnement ne mord presque jamais

L'objectif médian de B vaut **1,800** — identique à A. Celui de C vaut **2,6** :
sur une fenêtre de 50 bougies M5 (≈ 4 h d'or), le niveau de liquidité est le
plus souvent **PLUS LOIN** que 1,8 R. Le plafond ne se déclenche donc que
rarement ; B diffère surtout de A en **refusant** des trades (8 392 → 7 564), et
ce refus coûte. Quant à viser le niveau quand il est plus loin (C), c'est la
**pire** des quatre dans les deux fenêtres.

#### ⛔ Ce que ce banc ne dit PAS

Le niveau est lu dans les **50 bougies vues par le détecteur**, soit ≈ 4 h.
Le trade qui a posé la question visait au-delà d'un plafond de **six semaines**.
Allonger la fenêtre de lecture du niveau serait un **degré de liberté neuf**,
ajouté après avoir vu un résultat — donc une nouvelle déclaration, pas une
retouche de celle-ci.

#### Observation annexe, hors prédictions

Hors échantillon, A bat son contrôle aléatoire avec `t = +8,60` sur 25 612
trades — mais son R reste **négatif** (−0,0022 contre −0,0791). Les motifs
choisissent donc mieux que le hasard **et perdent quand même** une fois le
spread payé. Cohérent avec « le spread est la perte » ; aucune décision n'en
découle, et le contrôle aléatoire tire à des heures que les détecteurs évitent.

---

## TOUS LES HORIZONS SUR L'OR — déclaration du 2026-10-01

### Qui décide, et contre quoi

Demande explicite de Xavier : « tous les horizons ouverts pour l'or, et qu'on
puisse capitaliser là-dessus ». Posée **après** lui avoir montré la mesure et
**contre** ma recommandation de ne pas ouvrir. C'est sa décision, son argent,
et elle est exécutée en entier.

⚠️ Elle va aussi contre sa propre règle du 2026-08-11 — « si les trades sont
mesurés perdants alors ne pas desserrer ». Le dire ici une fois suffit ; ça ne
se redira pas à chaque ligne.

### Ce que la mesure dit, le jour même

Laboratoire or du **2026-10-01 03h51**, quatre échelles, 232 cellules,
**0 retenue**, verdict `INSUFFISANT` partout :

| horizon | cellules | retenues | R moyen | meilleur t | coût en R | trades |
|---|---|---|---|---|---|---|
| 5 min | 60 | 0 | −0,0688 | 2,21 | 0,0204 | 10 679 |
| 15 min | 57 | 0 | **−0,0513** | 1,41 | 0,0119 | 4 148 |
| 30 min | 58 | 0 | **−0,0381** | 2,15 | 0,0083 | 2 161 |
| 60 min | 57 | 0 | −0,0651 | 1,63 | 0,0062 | 1 176 |

🔑 Le mécanisme qui avait motivé l'ouverture sur la démo le 08/09 est
**confirmé** — le coût en R tombe de 0,0204 à 0,0062, soit **÷3,3** — et il ne
suffit pas : le signe de R ne bascule pas. Monter d'échelle allège les frais
sans créer d'edge.

### Le mécanisme posé, et pourquoi pas le `.env`

`MT5_BRIDGE_HORIZON_OVERRIDES`, paire par paire ET destination par destination :

    {"XAU/USD": {"admin_live": ["5min","15min","30min","1h","4h","1d"]}}

⛔ C'est le **premier dispositif de ce dépôt qui peut OUVRIR un horizon**. Toute
la cascade existante est restriction seule, exprès. Il est donc nommé, sans
joker, et il tranche dans les deux sens : ce qu'il ne déclare pas reste refusé.

🔑 Pourquoi pas élargir `MT5_BRIDGE_LIVE_ALLOWED_HORIZONS` : cette variable est
**par destination**. L'élargir aurait ouvert 15 min et 30 min pour **toutes**
les paires du compte réel, où la liste blanche globale (`range_bounce_up/down`)
les aurait laissées passer. **« Pour l'or » veut dire pour l'or.**

### La prédiction, déclarée AVANT le premier ordre

**Au lot minimum, sur 650 € de capital déclaré :**

| échelle | stop médian | risque | % capital | prédiction |
|---|---|---|---|---|
| 15 min | 0,428 % | 15,38 € | 2,4 % | **tradera** |
| 30 min | 0,655 % | 23,53 € | 3,6 % | **tradera** |
| 1 h | 0,882 % | 31,69 € | 4,9 % | **ne tradera pas — non produit** (échelles agrégées = 15/30 min) |
| 4 h · 1 j | 1,810 % | 65,03 € | 10,0 % | **ne tradera pas** — `risque_par_trade_excessif` |

- **P1** — l'or 15 min et 30 min produit des ordres sur `admin_live` dans les
  72 h suivant l'ouverture.
- **P2** — **aucun** ordre or en 1 h, 4 h ou 1 j n'est passé : les deux derniers
  sont refusés par la porte de risque, le premier n'existe pas comme produit.
- **P3** — le R moyen des ordres 15 min + 30 min est **négatif**, dans
  l'intervalle [−0,15 ; 0]. Point central attendu ≈ −0,045, la moyenne
  pondérée des deux cellules du laboratoire.
- **P4** — le P&L net de ces ordres est **négatif** à 30 ordres.

⚠️ Écart de mesure à nommer : la porte calcule sur **650 €** de capital déclaré
quand le courtier rend **572,43 €** d'`equity`. Le plafond de 5 % vaut donc
5,7 % du réel. Ça ne change aucun verdict ci-dessus, et ça doit être su.

### Ce que je recommande, et qui n'est PAS imposé

Aucun quota automatique n'a été posé : la demande était d'ouvrir, pas de borner,
et je ne rétrécis pas une demande en silence. Mais la dérogation 4h des motifs
forex avait, elle, une règle d'arrêt écrite d'avance — et c'est ce qui l'a rendue
lisible. Je recommande la même : **arrêt au premier des trois**, 30 ordres,
−40 € cumulés, ou 14 jours. Un mot de Xavier suffit pour que je la pose.

### Ce qui n'est PAS ouvert

Les autres paires, les autres destinations, et la production du 1 h (il
faudrait ajouter un facteur d'agrégation à `ECHELLES_AGREGEES`, ce qui change ce
que le radar **fabrique** — un autre chantier, une autre déclaration).
