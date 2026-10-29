# `or-porte` — la porte avant le pont

**But :** juger un lot de setups or contre les portes réelles de production, par
destination, et rendre `PASS` ou `BLOCK` avec la raison, le correctif et une
empreinte qui périme le verdict dès que le setup ou le code change.

**Architecture :** une quatrième skill du pack `or-*`, dont l'outil tourne
**dans le conteneur de production** et **importe** `_check_rejection` au lieu de
la réimplémenter. Elle ajoute trois choses que la production ne fait pas : la
conscience du lot, l'empreinte, et le correctif à côté du refus. Lecture seule.

**Pile technique :** Python de la bibliothèque standard, aucune dépendance,
aucune clé. `pytest` avec fixtures. Exécution par `ssh` + `docker exec`.

**Spec dont ce document est l'autorité :** celui-ci. Il n'y a pas de spec amont.

## Contraintes globales

- ⛔ **Lecture seule, sans exception.** Aucun ordre, aucune écriture dans
  `trades.db`, aucun armement, aucun déploiement. Même contrat que `or-etat`.
- ⛔ **Importer, jamais réimplémenter.** Toute clause de production est obtenue
  en appelant le code de production. Une clause recopiée est un défaut.
- ⛔ **Fail-closed partout.** Limite illisible, import impossible, empreinte de
  code indisponible : `BLOCK`, jamais `PASS`.
- 🔑 **Chaque clause déclare son origine**, `production` ou `lot`. Un verdict qui
  mélange les deux sans le dire mentirait sur ce qu'il a vérifié.
- ⛔ **REM-002 n'est pas contourné.** La skill constate l'état d'armement, elle
  ne le modifie pas et ne le simule pas.
- Les sorties utilisateur sont en français ; le code et les identifiants en
  anglais, comme le reste du dépôt.

## Ce qui établit ce besoin

Vérifié en production le 2026-10-29 (cf. fiches
`project_cinq_destinations_verifiees_2026_10_29`,
`feedback_la_specificite_bat_la_recence`) :

- **`admin_kraken` tient 25 buckets en `AUTO_EXEC`**, en argent réel, joignable,
  **sans aucun filtre de paires côté backend** ; son kill-switch vit sur le pont
  et est **illisible** depuis le conteneur.
- **La liste blanche MT5 n'est pas une seconde couche** : `XAU/USD` `buy` et
  `sell` ressortent `AUTO_EXEC` pour `admin_live`, parce que la cascade
  d'admission va du plus **spécifique**, pas du plus **récent**.
- **La table d'admission est un historique**, pas un état : la lire par requête
  recomposée rend 166 là où la cascade rend 1.
- ⇒ Il n'existe aujourd'hui **aucun moyen de répondre** à « que partirait-il si
  on réarmait ? » autrement qu'en lisant le code à la main. C'est ce que cette
  skill rend mécanique et reproductible.

## Ce que la skill ne fait pas

- Elle **ne choisit pas** de setups et n'en invente pas : elle juge ce qu'on lui
  donne. Aucune information d'entrée n'a jamais été démontrée sur l'or, et cette
  skill n'en produit aucune.
- Elle **ne bloque rien** en production. C'est un miroir. Rendre la porte
  exécutoire est un chantier distinct, explicitement différé (voir « Suites »).
- Elle **ne possède pas de limites**. Pas de `config.json` : la production est
  seule propriétaire de ses seuils, et en déclarer un second jeu créerait deux
  choses sous un même nom.

## Architecture

```
poste  ──ssh──>  EC2  ──docker exec──>  conteneur scalping-radar
                                          │
                                          ├─ importe mt5_bridge._check_rejection
                                          ├─ importe destinations_registry
                                          ├─ importe pair_admission_controller
                                          └─ importe rejection_service.REASON_LABELS_FR
```

**Pourquoi dans le conteneur.** Les portes lisent la configuration
d'environnement et la base de production. Les juger depuis un poste, avec
d'autres variables, rendrait un verdict qui ne décrit aucune réalité — la faute
« les deux bras doivent partager leur source ». Le prix à payer est assumé : la
skill **exige** un accès SSH à l'EC2 et ne fonctionne pas hors ligne.

**Ce qu'elle appelle, nom par nom :**

| appel | ce qu'il rend |
|---|---|
| `mt5_bridge._check_rejection(setup, dest)` | `None` si le setup passe, sinon un `reason_code` |
| `destinations_registry.get(id)` | la destination : `bridge_type`, `reel`, `asset_classes`, `max_correlated_positions`, `order_cooldown_sec`, `risk_per_trade_pct` |
| `pair_admission_controller.get_current_state(pair, direction, destination)` | l'état d'admission par la **cascade** à trois étages |
| `rejection_service.REASON_LABELS_FR[code]` | le libellé français du refus |

## Le contrat de fichiers

Trois fichiers sous `or/`, et pas un de plus.

### `or/lot.json` — l'entrée

Un objet par setup candidat. Les clés autorisées sont **exactement** les onze
champs que les portes lisent (voir « L'empreinte »), **plus `risk_pct`**, seul
champ admis sans être lu par une porte. Toute autre clé est refusée (code 2),
pour qu'on ne croie jamais qu'un champ décoratif a influencé le verdict.

```json
{
  "destinations": ["admin_live", "admin_kraken"],
  "setups": [
    {
      "pair": "XAU/USD",
      "direction": "buy",
      "entry_price": 2412.50,
      "stop_loss": 2404.10,
      "confidence_score": 71,
      "pattern": "range_bounce",
      "horizon": "30min",
      "chaine": null,
      "shadow_system_id": null,
      "is_simulated": false,
      "verdict_blockers": [],
      "risk_pct": 0.35
    }
  ]
}
```

⚠️ `risk_pct` n'est lu par aucune porte de production : il sert **uniquement**
à la contrainte de lot « risque engagé », et son origine sera donc étiquetée
`lot`. Il est exclu de `empreinte_setup`.

### `or/state/porte.json` — les verdicts

```json
{
  "juge_le": "2026-10-29T18:04:11+00:00",
  "empreinte_code": "a4d9aedeee17",
  "verdicts": [
    {
      "empreinte_setup": "3f1c…",
      "pair": "XAU/USD",
      "direction": "buy",
      "destination": "admin_live",
      "resultat": "BLOCK",
      "reason_code": "below_confidence",
      "libelle": "Confiance < seuil",
      "origine": "production",
      "correctif": "Confiance 71 sous le seuil 66 de cette destination — relever le score ou viser une destination au seuil plus bas."
    }
  ]
}
```

### `or/exemple-lot.json`

Un lot d'exemple réel : les **2 buckets `XAU/USD` d'`admin_live`** et **3 des 25
de `admin_kraken`**, avec les chiffres de production du 29/10. Il sert de recette
et de documentation exécutable.

## L'empreinte

Deux parties. Un verdict n'est valable que si les deux correspondent.

### `empreinte_setup`

Hash `sha256` tronqué à 12 caractères du JSON canonique (clés triées,
séparateurs compacts) des **onze** champs que les portes lisent réellement,
obtenus par analyse AST transitive de `_check_rejection` et de ses aides
(`_horizon_rejection`, `_patterns_autorises`, `_pattern_value`,
`_direction_value`, `_cost_rejection`, `_jeton_derogation_restant`,
`_event_rejection`) :

```
chaine · confidence_score · direction · entry_price · horizon ·
is_simulated · pair · pattern · shadow_system_id · stop_loss · verdict_blockers
```

🔑 **Ni plus, ni moins.** Hacher davantage périmerait des verdicts pour une
modification sans effet ; hacher moins garderait vivant un verdict qu'une
modification matérielle a invalidé. La liste de onze est **dérivée**, pas
choisie : un test la recalcule et échoue si la production se met à lire un
douzième champ.

### `empreinte_code`

Le `fingerprint_running` de production — `a4d9aedeee17` le 2026-10-29. Un
verdict calculé contre un autre code est **nul**, et la skill le dit au lieu de
le réutiliser. C'est la partie que trader-skill n'a pas, et c'est exactement la
faute que le dépôt a déjà commise : une sonde qui calcule l'attendu avec
l'ancienne règle vaut moins que pas de sonde.

Si `fingerprint_running` est illisible : `BLOCK` sur tout le lot, motif
`empreinte_code_illisible`. Fail-closed.

## La conscience du lot

`_check_rejection(setup, dest)` n'accepte aucun paramètre « fais comme si
ceux-là étaient remplis ». La conscience du lot est donc **impossible par le
seul import**, et la skill la calcule à côté — sur **quatre** contraintes
nommées, et pas une de plus.

Les setups sont jugés **dans l'ordre du fichier**, chaque `PASS` étant traité
comme rempli pour les suivants. Un lot correct setup par setup mais fautif
ensemble est ainsi attrapé.

| contrainte de lot | la limite de production qu'elle ombre | ce que chaque `PASS` consomme |
|---|---|---|
| positions par paire | le comptage chez le courtier (`_places_libres_pour`, MT5 seulement) | une place sur cette paire |
| exposition corrélée | `Destination.max_correlated_positions` | une place dans la classe d'actif |
| risque engagé | `max_risque_engage_pct` publié par `/health`, quand il l'est | `risk_pct` du setup |
| cadence | `Destination.order_cooldown_sec` | ouvre une fenêtre sur cette paire : un `PASS` suivant sur la **même paire** et la **même destination** `BLOCK` tant que la fenêtre court. Le lot n'ayant pas d'horloge, les setups d'un même lot sont traités comme **simultanés** — donc le deuxième bloque dès que `order_cooldown_sec > 0`. |

**Règles communes aux quatre :**

- Chaque clause **nomme** la limite de production qu'elle ombre, et sa valeur
  lue à l'exécution. Une clause sans limite lisible rend `BLOCK` avec le motif
  `limite_illisible` — jamais `PASS`.
- Chaque verdict issu de ces clauses porte `"origine": "lot"`. Un verdict issu
  de `_check_rejection` porte `"origine": "production"`.
- ⚠️ Ces quatre clauses sont un **ajout de la skill**, pas une description du
  comportement de production. La sortie le dit explicitement, en tête de
  rapport comme sur chaque ligne.

## La sortie

Par setup × destination, une ligne. `PASS`, ou `BLOCK` avec quatre éléments :
le `reason_code`, son libellé français, l'origine, et le **correctif**.

Le correctif dit quoi changer, en nommant la valeur et le seuil — « confiance 71
sous le seuil 66 », pas « confiance insuffisante ». ⛔ La skill ne propose
**jamais** de modifier une limite comme correctif par défaut ; si la seule issue
est de desserrer une règle, elle le dit comme une décision à prendre, pas comme
un correctif.

En tête : l'empreinte de code, l'état d'armement lu par `or-etat`, et le rappel
que les clauses `lot` sont un ajout.

**Les neuf motifs sans libellé.** `cooldown_symbole`, `correlated_exposure`,
`direction_blocked_for_pair`, `direction_blocked_global`,
`energy_pre_weekend_freeze`, `hour_in_avoid_list`, `pair_auto_paused`,
`pair_blocked` et **`pair_not_whitelisted`** sont rendus par
`_check_rejection` mais absents de `REASON_LABELS_FR`. La skill retombe sur le
code brut **et signale la lacune** en pied de rapport. 🔴 Le cas
`pair_not_whitelisted` est le plus gênant : c'est la porte qui protège l'argent
réel sur MT5, et partout où ce refus est affiché à l'utilisateur, il apparaît
sans texte.

## Interface

```bash
python .claude/skills/or-porte/porte.py                      # or/lot.json ; écrit or/state/porte.json
python .claude/skills/or-porte/porte.py --lot autre.json
python .claude/skills/or-porte/porte.py --json
python .claude/skills/or-porte/porte.py --no-write           # juger sans rien enregistrer
python .claude/skills/or-porte/porte.py --depuis-vivier admin_kraken
```

`--depuis-vivier <destination>` construit le lot depuis les buckets `AUTO_EXEC`
de cette destination, résolus par la **cascade** `get_current_state()` et non
par requête sur la table — la table est un historique.

**Code de sortie :** `0` si tout passe, `1` si au moins un `BLOCK`, `2` si la
skill n'a pas pu juger (import, empreinte, limite illisible). Les trois sont
distincts : « tout bloqué » et « je n'ai pas pu juger » ne doivent pas se
confondre.

## Les erreurs

| cas | comportement |
|---|---|
| `lot.json` absent ou illisible | code 2, message nommant le fichier et la ligne fautive |
| champ inconnu dans un setup | code 2 — on ne juge pas un setup dont une clé pourrait être attendue à tort |
| champ requis manquant | code 2, en nommant le champ et la porte qui le lit |
| destination inconnue du registre | code 2, avec la liste des destinations connues |
| `_check_rejection` lève | le setup est `BLOCK` motif `porte_en_erreur`, le lot continue, la trace est en pied |
| `fingerprint_running` illisible | code 2, tout le lot en `BLOCK` |

## Les tests

`pytest`, fixtures en JSON, à côté de la skill comme pour les trois autres.
Trois familles sont **non négociables**.

**1. Anti-dérive.** Pour chaque setup d'un jeu de fixtures, le verdict
`production` de la skill doit être **égal** à
`mt5_bridge._check_rejection(setup, dest)`. ⇒ réimplémenter une porte devient
impossible sans casser la suite. C'est le test qui protège la propriété
principale de tout l'objet.

**2. Témoin dans les deux sens.** Un setup connu **passant** et un setup connu
**bloquant**, et la suite échoue si l'un des deux change de camp. Un « aucun
refus » est ambigu — il peut vouloir dire « rien ne bloque » ou « l'instrument
est cassé ». Un témoin positif lève l'ambiguïté.

**3. Empreinte, dans les deux directions.**
- modifier **chacun** des onze champs, un par un, périme le verdict ;
- modifier `risk_pct`, qui n'est lu par aucune porte, **ne** le périme pas ;
- changer `empreinte_code` périme tout le fichier d'état ;
- un test **recalcule la liste des onze champs** par analyse AST et échoue si la
  production se met à lire un champ de plus — la liste ne peut pas se désynchroniser en silence.

**4. Conscience du lot.** Un lot de deux setups, chacun passant seul, dont le
second doit `BLOCK` sur chaque contrainte de lot — quatre cas, un par
contrainte. Et un test vérifie que l'`origine` de ces refus est bien `lot`.

**Mutation.** Au moins six mutations comptées doivent être discriminantes :
retirer une des quatre contraintes de lot, hacher dix champs au lieu de onze,
ignorer `empreinte_code`, et transformer un `BLOCK` fail-closed en `PASS`.

## La recette

La skill est acceptée quand elle répond, avec des chiffres, à la question
ouverte du 2026-10-29 :

1. `--depuis-vivier admin_kraken` juge les **25 buckets** et dit, pour chacun,
   s'il partirait et sinon pourquoi.
2. Les **2 buckets `XAU/USD` d'`admin_live`** (`buy` et `sell`) sont jugés, et le
   `buy` doit faire apparaître que son `AUTO_EXEC` vient d'une ligne
   **spécifique à la destination** qui domine l'auto-pause du 06/10.
3. Les **10 paires hors `WATCHED_PAIRS`** de `admin_kraken` ressortent avec un
   motif explicite, et non en silence.
4. Le rapport nomme les motifs sans libellé rencontrés.
5. `or-etat` et `or-porte` s'accordent sur l'état d'armement.

## Suites

- **`or-politique` (chantier suivant, approche C).** Vérifie les *limites* que la
  production lit déjà et refuse une configuration qui laisse une destination en
  argent réel sans filtre de paires. C'est le plus petit changement qui ferme le
  trou `admin_kraken`.
- **Porte exécutoire (approche B, différée).** Un étage par lot, apparié par
  empreinte, obligatoire avant l'aiguillage. ⛔ À ne pas entreprendre avant que
  `or-porte` existe : c'est du code de garde neuf sur le chemin de l'argent, et
  `or-porte` est l'instrument qui permettrait de le tester.
- **Les neuf libellés manquants** à écrire dans `REASON_LABELS_FR` — petit,
  indépendant, et visible par l'utilisateur.
