# Pack « or » — trois skills qui contraignent, au lieu de rappeler

**Date** : 2026-10-25
**Objectif** : encoder dans trois skills versionnées ce qui, aujourd'hui, ne
tient que dans 60 Ko de mémoire et dans ma vigilance — l'état d'armement, la
pré-inscription d'une mesure, et le refus de publier un rejeu invalide.

**Destinataire** : Claude Code, dans le dépôt, avec la suite de tests.

---

## 1. Le besoin, mesuré et non supposé

Le 2026-10-25 a produit deux verdicts (`ffb150e`, `56ff582`) et mis au jour
**six pannes silencieuses**. Dans ce travail, j'ai commis **trois erreurs**, et
aucune n'a été rattrapée par ma vigilance :

| erreur | ce qui l'a rattrapée |
|---|---|
| j'ai diagnostiqué le pont **démo** en le prenant pour le réel | la lecture de `MT5_BRIDGE_LIVE_URL`, après une journée perdue |
| j'ai modélisé la sonde à **5 min** au lieu d'1 min | la ligne de crontab, lue tardivement |
| j'ai fait payer le coût **une fois** au lieu de deux | ma barre de validité, qui a imprimé `NON CONCLUANT` |

🔑 **La seule des trois qui m'a arrêté AVANT de publier est celle qu'un calcul
a tranchée.** Les deux autres, je les ai trouvées en cherchant.

Et le précédent qui fonde tout ce document : le 2026-10-13, j'ai annoncé « la
protection a évité 642 € ». La méthode, écrite noir sur blanc dans
`docs/predictions/`, disait déjà de ne pas publier un majorant. **La liste de
contrôle existait et ne m'a pas arrêté.** Le verdict du 25/10 a montré que ce
chiffre était faux **de signe**.

⇒ Une liste de contrôle se survole. Un code de sortie, non.

## 2. Ce que le pack n'est pas

- ⛔ **Pas un acteur.** Les trois skills sont en **lecture seule** sur la
  production : elles n'arment, ne désarment, ne déploient et ne passent jamais
  d'ordre.
- ⛔ **Aucun signal, aucune promesse de rendement.** Le dépôt établit
  l'inverse : 43 cellules de largeur de stop (0 retenue), 3 réfutations de la
  direction.
- ⛔ **Pas une transposition de `trader-skill`.** Son contrôleur de risque,
  essayé le 25/10 sur un ordre XAU/USD, répond : *« does not look like a US
  stock or ETF ticker; this pack trades stocks and ETFs only »* — `0 passed,
  2 blocked`. On copie sa **forme**, pas son contenu.
- ⛔ **Elles ne commitent pas.** Le commit reste un geste humain.

## 3. Décisions arrêtées avec Xavier

| question | décision | raison |
|---|---|---|
| où elles vivent | `.claude/skills/or-*` **dans le dépôt** | versionnées avec le code qu'elles jugent ; une sonde qui dérive du code juge avec l'ancienne règle — défaut du 12/10 |
| périmètre v1 | **3 skills** : `or-etat`, `or-preinscription`, `or-verdict` | un verdict sans pré-inscription ne juge contre rien |
| déclenchement | **auto** pour `preinscription` et `verdict` ; **sur demande** pour `etat` | la méthode doit s'imposer sans que quelqu'un y pense |
| forme | `SKILL.md` + script qui **calcule** et rend un **code de sortie** | une barre calculée arrête, une bonne intention écrite non |
| dépendances | **stdlib seule** | rien à installer, ni ici ni sur l'EC2 |

⚠️ **Le risque assumé** : ces scripts deviennent du code qui doit suivre
REM-002 et les conventions de `docs/predictions/`. S'ils dérivent, ils
jugeront avec l'ancienne règle. Contre-mesures : versionnage dans le dépôt, et
des tests qui **échouent quand la convention bouge**.

## 4. `or-etat` — « suis-je armé, et par quoi ? »

**Le besoin** : le 25/10, répondre à « l'auto-trading est-il désactivé ? » m'a
pris vingt minutes et quatre détours, et la bonne réponse n'était pas un
drapeau mais **trois voies d'ordre**, dont une qui ne passe pas par le backend.

**Ce qu'elle imprime**, dans cet ordre :

```
1. _push_to_destination   -> decision REM-002 (reason_code + detail)
2. _mirror_fill_to_live   -> _mirror_active()
3. file de l EA           -> nb de PENDING dans mt5_pending_orders + date du dernier
```

puis l'équité et les positions ouvertes, le `/health` des **deux** ponts (live
jugeant, démo informatif), et la comparaison `fingerprint_running` /
`fingerprint_armed` — qui dit si un réarmement exigerait une décision neuve.

**Codes de sortie** : `0` l'état est déterminé et cohérent ; `1` il ne peut pas
être déterminé. ⛔ Jamais `0` sur une information manquante.

**Comment elle atteint la production** : `ssh -i scalping-key.pem`, la clé à la
racine du dépôt, puis `docker exec scalping-radar python3 -c …` qui **importe**
`global_execution_switch` et `mt5_bridge` et lit leur décision. ⚠️ Donc elle
n'interroge pas un fichier d'état en parallèle : elle demande au code **qui
décide**. Lire un reflet au lieu de la source est le défaut du 12/10.

⛔ Aucune commande d'écriture, aucun `kill`, aucun `POST`. Si la clé est absente
ou l'hôte injoignable : code `1`, avec la raison.

## 5. `or-preinscription` — refuse une mesure sans critère falsifiable

**Déclenchement** : dès qu'on s'apprête à écrire un banc ou une mesure.

**Ce qu'elle refuse**, en listant ce qui manque :

1. un critère à **seuils numériques** explicites, pas de la prose ;
2. au moins une condition d'**ADMISSION** — ⛔ « pas significativement pire »
   n'en est jamais une : faute commise le 12/10 **et** le 14/10 ;
3. un **plafond par permutation** dès que plusieurs cellules sont testées — le
   14/10, **sept** cellules auraient « passé » à `t = 2`, et le hasard seul en
   fait passer autant ;
4. une **condition de validité** du rejeu, distincte du critère ;
5. au moins **trois prédictions** numérotées ;
6. 🔑 le commit de la pré-inscription **antérieur** au premier commit du banc.
   Le chemin du banc est donné **en argument** (`--banc scripts/banc_x.py`) :
   la skill ne le devine pas. Vérifié par `git log --diff-filter=A -- <banc>`
   contre `git log -1 -- <preinscription>`. ⚠️ Un banc **non suivi par git** est
   refusé : on ne peut pas prouver qu'il est postérieur.

**Codes de sortie** : `0` complète ; `1` incomplète, avec la liste.

## 6. `or-verdict` — refuse de publier un rejeu invalide

**Déclenchement** : dès qu'on s'apprête à annoncer un chiffre.

**Entrées** : la sortie JSON du banc + le chemin de la pré-inscription, tous
deux en arguments — rien n'est deviné. Le contrat JSON est celui que
`scripts/banc_contrefactuel_protection.py` émet déjà :

```
n, total_reel, total_A, total_B, evite, moy_appariee, t,
reussite_A, reussite_B, ecart_par_trade, valide
```

⚠️ Un banc qui n'émet pas `ecart_par_trade` et `valide` est **refusé** : sans
eux la condition de validité n'est pas calculable, et un verdict non validable
ne doit pas être rendu.

**Ce qu'elle recalcule** :

- le rejeu reproduit-il la réalité **dans la barre pré-inscrite** ? Sinon :
  `NE PAS PUBLIER`, code `1` ;
- les branches du critère (`t > +2` / `t < −2` / entre les deux) ;
- chaque prédiction doit être **notée** juste ou fausse — une prédiction non
  notée bloque ;
- 🔑 l'**empreinte du critère** : on hache le **bloc `CRITERE-MACHINE`** du
  fichier de pré-inscription tel qu'il est **sur le disque**, et on le compare
  au haché du même bloc dans `git show <commit-de-preinscription>:<fichier>`.
  Un critère réécrit après coup donne deux hachés différents ⇒ **refus**.

  ⛔ **RÉVISÉ LE 2026-10-26, et la première version était fausse.** Elle hachait
  la **section en prose** « CRITÈRE ». Mesuré sur le corpus réel de
  `docs/predictions/` : **16 formes** de titre contiennent « critère », **5
  fichiers sur 38** en ont plusieurs, et dans l'un d'eux le premier est du
  **récit** — 60 lignes avant le vrai critère. L'empreinte hachait donc la
  mauvaise section : **fail-open** sur la garde même qu'elle constitue.

  ⛔ Et le correctif intermédiaire — « retenir le titre où le mot-clé apparaît
  le plus tôt » — était pire : il n'est **pas stable par ajout en fin de
  fichier**, alors que le flux de travail **ajoute le verdict au fichier de la
  pré-inscription**. Un titre de verdict commençant par « Critère » aurait
  produit une **fausse accusation de falsification**. Une heuristique sur de la
  prose française échange un défaut contre un autre.

  🔑 **Le bloc machine supprime la classe entière de problème** : il est
  délimité par un marqueur unique, non ambigu, lisible par machine, et déjà
  exigé par le §5. Et il contient précisément ce qui ne doit pas bouger — les
  seuils. La prose autour peut être réécrite, complétée, corrigée : ce n'est
  pas elle qui engage.

  ⇒ Conséquence : l'analyse de section n'a plus à départager des titres
  ambigus. La règle d'ordre du document suffit, et le module commun redevient
  simple.

**Sortie** : le squelette du verdict, prêt à relire — jamais publié par elle.

## 7. Erreurs et silences — la règle transversale

Les trois skills sont **fail-closed et bavardes**. Ne pas pouvoir lire une
base, joindre un pont ou trouver une table rend un **code 1 avec la raison**,
jamais un succès muet.

⛔ Et jamais « OK » sur une donnée dont l'âge est inconnu ou négatif : le
25/10, ma sonde de fraîcheur a affiché `OK` sur un magasin vieux de **13 786
minutes** (le week-end lui servait d'excuse) puis `OK` sur un horodatage à
`-0 min` (dans le futur). Les deux défauts sont corrigés dans
`scripts/sonde_fraicheur_chaine_or.py` et la règle est reprise ici.

## 8. Tests

Chaque skill : des fixtures, et — leçon du 11/10, *un test insensible au défaut
ne prouve rien* — **chaque test a son jumeau négatif**. La même fixture portant
le défaut doit provoquer le refus :

| fixture | attendu |
|---|---|
| pré-inscription sans plafond par permutation | **rejetée** |
| critère uniquement « pas pire » | **rejeté** |
| banc commité avant sa pré-inscription | **rejeté** |
| verdict dont le rejeu dépasse la barre | **code 1** |
| critère modifié après coup | **rejeté** |
| état d'armement illisible | **code 1** |

Exécution : `python -m pytest .claude/skills` — stdlib et `pytest` seuls, sans
réseau ni base de production.

## 9. Ce qui viendra après, et pas maintenant

`or-banc` (rejeu apparié, population fixe, dedans/dehors), `or-cout` (spread +
markup 10 points **par côté**) et l'extension de `or-fraicheur` — déjà écrite
et armée le 25/10 (`7b2b136`, `371e4f5`). ⚠️ `or-banc` est le gros morceau :
celui du 25/10 a demandé des heures et trois défauts corrigés. Il ne doit pas
être bâclé en même temps que les trois autres.
