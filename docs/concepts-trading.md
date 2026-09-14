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
