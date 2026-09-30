# Phase 0 — Containment. Journal d'implémentation et runbook

**Cahier des charges :** Remédiation de l'audit Scalping Radar, v1.0 (2026-09-28)
**Périmètre de ce document :** REM-001, REM-002, REM-003, et l'amorce de REM-004
**Base de code :** `46ae213` (2026-09-27) + les changements décrits ici
**État :** codé, testé, **non déployé**

---

## 0. Ce que ce document engage

Il décrit ce qui a été fait, ce qui n'a pas été fait, et les **deux décisions de
périmètre** prises en cours de route. Les deux réduisent la protection par
rapport à une lecture maximaliste du cahier des charges, et sont signalées en
🔴 à l'endroit où elles s'appliquent.

⛔ Rien ici n'est déployé. La conséquence du déploiement est décrite en §5, et
elle est majeure : **le trading s'arrête jusqu'à un armement explicite.**

---

## 1. REM-001 — Porte de chaîne fail-closed

### Le défaut, tel qu'il était

`mt5_bridge._patterns_autorises` portait la décision « cette chaîne peut-elle
trader ? » dans sa **valeur de retour** : un `set()` vide signifiait « rien ne
peut partir ». Le consommateur écrivait :

```python
allowed_patterns = _patterns_autorises(setup, dest)
if allowed_patterns and not _jeton_derogation_restant():
    if _pattern_value(setup) not in allowed_patterns:
        return "pattern_not_allowed"
```

Un ensemble vide est **faux** en Python. Le `if` sautait le filtre entier.

⇒ Une étiquette de chaîne non armée ne fermait pas la porte : **elle supprimait
la liste blanche**. Elle ouvrait plus grand qu'un setup ordinaire.

Aggravant, dans le même fichier : `dest.allowed_patterns = frozenset()`
signifie « désactiver le filtre pour cette destination ». **Deux sens opposés
pour la même valeur.**

### Le correctif

| Élément | Fichier |
|---|---|
| Porte dédiée, décision explicite | `backend/services/chain_execution_gate.py` (nouveau) |
| Branchement en première porte | `backend/services/mt5_bridge.py::_check_rejection` |
| Retrait du `return set()` | `backend/services/mt5_bridge.py::_patterns_autorises` |
| Motif de refus traçable | `backend/services/rejection_service.py` |
| Tests | `backend/tests/test_rem001_chain_execution_gate.py` |

La décision ne voyage plus dans un type ambigu mais dans un `ChainDecision`
gelé qui porte `decision`, `reason_code`, `chain_id`, `trigger_id`,
`destination_id`, `horizon`, `configuration_version`, `timestamp`.

États rendus : `ALLOW/NO_CHAIN`, `ALLOW/CHAIN_ARMED`, `DENY/CHAIN_NOT_ARMED`,
`DENY/CHAIN_REGISTRY_UNREADABLE`, `DENY/CHAIN_PATTERN_INDETERMINATE`,
`DENY/CONTROL_ERROR`.

Le refus sort désormais en **`chaine_non_armee`** — distinct de
`pattern_not_allowed`, et sans préfixe `_` (un motif privé ne laisse aucune
trace, et c'est ce qui a rendu le défaut invisible dix jours).

### Critères d'acceptation du cahier des charges

| Test | Attendu | Résultat |
|---|---|---|
| chaîne armée + figure autorisée | ALLOW | ✅ |
| chaîne non armée | DENY | ✅ |
| whitelist vide | DENY | ✅ |
| configuration absente | DENY | ✅ |
| exception interne | DENY | ✅ |
| figure artificielle non déclarée | DENY | ✅ |

### ⛔ Ce que la mutation a révélé, et qui compte plus que les tests verts

Trois mutations ont été injectées volontairement pour vérifier que la suite
**mord** :

| Mutation | Attrapée ? |
|---|---|
| remettre le `return set()` d'origine | ✅ 1 échec |
| débrancher la porte de `_check_rejection` | ❌ **0 échec au premier essai** |
| faire rendre `ALLOW` par défaut à la décision | ✅ 8 échecs |

La deuxième n'était **pas** attrapée : les tests validaient le module en
isolation, jamais son branchement. C'est la famille de défauts « patch sur
import mort » et « doublure absente en production ». Trois tests d'intégration
ont été ajoutés ; la mutation est maintenant attrapée (2 échecs).

### 🔴 Découverte : le défaut était PORTEUR de 14 tests

En branchant la porte, 14 tests préexistants sont tombés. Cause : un
`MagicMock()` **fabrique** ses attributs, donc `setup.chaine` était un Mock
**vrai**. L'ancien code appelait alors `autorisee()` → `False` → `return set()`
→ falsy → **filtre sauté** → l'ordre passait.

**Ces 14 tests passaient grâce au fail-open.** Ils ont été corrigés en donnant
aux doublures la forme de la production (`chaine = None` pour un setup
ordinaire).

Et un quinzième test, `test_un_setup_de_chaine_NON_ARMEE_est_refuse...`,
assertait `de_chaine == set()` : il **assertait le véhicule du défaut** au lieu
de son effet. Corrigé pour juger l'effet, et doublé d'un test qui vérifie que
le dispatch refuse réellement.

---

## 2. REM-002 — Verrou d'exécution global

`backend/services/global_execution_switch.py` (nouveau).

### Ce qu'il coupe, et ce qu'il ne coupe pas

Il interdit **l'envoi de nouveaux ordres**. Il n'empêche jamais :

- la surveillance des positions ouvertes ;
- leur fermeture, y compris d'urgence ;
- la récupération des données du courtier ;
- l'audit, les sondes, la réconciliation.

C'est garanti par l'emplacement du branchement : `_check_rejection` n'est
traversé que par le chemin d'**ouverture**.

### Pourquoi il est distinct de `kill_switch`

`kill_switch` existe depuis avril et ses déclencheurs sont des faits de
**marché** (rafale de stops, plafond de perte journalière, coupure manuelle).
Ce verrou-ci a des déclencheurs d'**intégrité**. Les mélanger rendrait
impossible de dire pourquoi on est coupé. **Les deux s'appliquent.**

### Les règles

| Situation | Décision |
|---|---|
| état persistant absent ou illisible | DENY / `STATE_MISSING`, `STATE_UNREADABLE` |
| manifest absent, illisible, incomplet, ou commit divergent | DENY / `DEPLOYMENT_INTEGRITY` |
| empreinte de déploiement ≠ empreinte armée | DENY / `NEW_DEPLOYMENT` |
| blocage d'intégrité posé | DENY / `INTEGRITY_BLOCK` |
| désarmé à la main | DENY / `DISARMED_MANUALLY` |
| exception interne | DENY / `CONTROL_ERROR` |
| armé pour ce déploiement, rien d'autre | ALLOW / `ARMED` |

Blocages déclarés : `reconciliation_error`, `monitoring_down`,
`broker_unreachable`, `configuration_error`, `critical_anomaly`. Chacun doit
être levé **explicitement** — jamais par expiration.

⚠️ Un blocage de nom **inconnu** est accepté et ferme quand même. Le refuser au
motif qu'il n'est pas déclaré rendrait le garde-fou silencieux.

### 🔴 DÉCISION DE PÉRIMÈTRE nº 1 — la dérive de configuration ne ferme pas

Ma première version faisait porter l'armement sur **commit + empreinte de
configuration** : tout changement de réglage invalidait l'armement. C'est plus
fort, et c'est ce qui aurait attrapé le réarmement silencieux du 22/09.

Le cahier des charges met en P0 la fermeture sur « nouveau déploiement » et
« incohérence de version » — deux faits d'**identité du code**. La gouvernance
des configurations est **REM-023, en P2**.

⇒ L'armement porte sur le **commit seul**. La dérive de configuration est
**mesurée et publiée** (`configuration_drift` dans `/system/version`), mais
elle **ne ferme pas la porte**.

**Conséquence à assumer, écrite noir sur blanc : jusqu'à REM-023, éditer
`/opt/scalping/.env` puis redémarrer ne demande PAS de ré-armer.** C'est
exactement le geste du 22/09. La dérive se voit ; elle n'arrête rien.

Un test verrouille cet état (`test_la_derive_de_configuration_est_PUBLIEE`) et
**doit échouer** le jour où REM-023 est livré. Il est écrit pour être réécrit,
pas désactivé.

### 🔴 DÉCISION DE PÉRIMÈTRE nº 2 — le harnais de test arme, il n'exempte pas

Le verrou étant fail-closed, la suite entière refusait. La tentation était
d'ajouter un drapeau « ne pas appliquer en test » — c'eût été **un fail-open de
plus**, le défaut exact que REM-001 vient de supprimer.

La fixture `_armer_execution_globale` (autouse, dans `conftest.py`) pose donc un
**vrai** manifest et un **vrai** armement dans un dossier temporaire. Les tests
traversent le code de production sans exception, et la fixture s'auto-vérifie :
si l'armement ne prend pas, elle échoue là, pas dans 4 000 erreurs ailleurs.

### Mutations vérifiées

| Mutation | Attrapée |
|---|---|
| verrou débranché du dispatch | ✅ 1 échec |
| état absent devient ALLOW | ✅ 2 échecs |
| nouveau déploiement ne referme plus | ✅ 1 échec |
| manifest incomplet accepté | ✅ 5 échecs |

---

## 3. REM-003 — Manifest de déploiement

| Élément | Fichier |
|---|---|
| Lecture et vérification | `backend/services/deployment_manifest.py` (nouveau) |
| Génération au build | `scripts/generer_manifest_deploiement.py` (nouveau) |
| Intégration au déploiement | `deploy-v2.sh` |
| Endpoint | `GET /system/version` dans `backend/app.py` |
| Exclusion git | `.gitignore` |

Champs : `git_commit_sha`, `git_branch`, `git_dirty`, `git_dirty_files`,
`build_timestamp`, `docker_image_digest`, `configuration_hash`,
`database_schema_version`, `research_rules_version`, `risk_rules_version`,
`build_environment`, `deployment_timestamp`, `manifest_schema`.

Les cinq premiers cités dans `CHAMPS_REQUIS` sont **obligatoires** : leur
absence rend `MANIFEST_INCOMPLETE`, donc DENY.

### Deux précautions

**Le hash de configuration ne contient aucun secret.** La liste des clés est
**explicite**, pas un préfixe — `MT5_*` aurait embarqué les identifiants du
courtier. Un test vérifie qu'ajouter un mot de passe à l'environnement **ne
change pas** le hash, et qu'aucun secret n'apparaît dans `/system/version`.

**Le manifest est généré AVANT `docker build`**, parce qu'il lit `.git`, exclu
de l'image par `.dockerignore`. Le générer depuis l'intérieur du conteneur ne
dirait rien.

`--exiger-propre` : un arbre de travail sale rend le commit insuffisant pour
identifier le code. Le déploiement refuse de construire une image qu'il ne
saurait pas nommer.

### `/system/version` est non authentifié, à dessein

Un endpoint d'intégrité qui exige un jeton ne sert à rien quand c'est
justement la configuration qu'on soupçonne. Les champs exposés sont énumérés
dans `public_version()` ; aucun n'est secret.

---

## 4. REM-004 — amorcé, pas terminé

`EXPECTED_GIT_COMMIT` est désormais posé dans `/opt/scalping/.env` par
`deploy-v2.sh`, et le runtime le compare à ce que le manifest déclare. Une
divergence **ferme** l'exécution.

⛔ **Ce qui reste :** le dossier de scripts exécuté par les tâches planifiées de
l'hôte (`/opt/scalping/scripts/`) est toujours distinct du clone git. Huit
fichiers y divergeaient au 8 septembre. Le manifest ne couvre pas ce chemin.
REM-004 n'est donc **pas** clos.

---

## 5. 🔴 Conséquence du déploiement — à lire avant de déployer

Après ce déploiement, **l'exécution est FERMÉE**. Aucun ordre neuf ne part,
sur aucun compte, jusqu'à un armement explicite.

C'est le comportement demandé (« `GLOBAL_EXECUTION_ENABLED = FALSE` par défaut
lors d'un nouveau déploiement ») et il est cohérent avec la règle de gel du §36
du cahier des charges. Mais il faut le vouloir.

Ce qui continue de fonctionner : surveillance des positions, fermetures,
stops, réconciliation, sondes, notifications, laboratoire nocturne.

### Procédure de déploiement

```bash
# 1. Depuis le poste de dev — le script pousse, tire, génère le manifest,
#    construit l'image et pose EXPECTED_GIT_COMMIT.
./deploy-v2.sh

# 2. Vérifier ce qui tourne AVANT d'armer.
curl -s https://<domaine>/system/version | python -m json.tool
#    Attendu : status = OK, git_commit_sha = le commit déployé,
#              execution.live_execution = OFF

# 3. Témoin NÉGATIF : l'exécution est bien fermée.
sudo docker exec scalping python scripts/execution_switch.py status
#    Attendu : LIVE EXECUTION OFF, reason_code NEW_DEPLOYMENT

# 4. Armer, avec une raison écrite.
sudo docker exec scalping python scripts/execution_switch.py \
     arm --raison "Phase 0 vérifiée, REM-001/002/003" --par "<prénom>"

# 5. Témoin POSITIF : la fonction sait dire oui.
sudo docker exec scalping python scripts/execution_switch.py status
#    Attendu : LIVE EXECUTION ON, reason_code ARMED
```

⛔ **Ne pas sauter l'étape 3.** Un silence n'est pas une preuve : il faut avoir
vu la porte fermée avant de la voir ouverte. C'est la leçon du 25 septembre, où
une vérification « à chaud » qui lisait le journal a conclu que la porte
fonctionnait alors qu'elle était grande ouverte.

### Si `arm` refuse

Il refuse quand l'intégrité n'est pas bonne. **Ce n'est pas un obstacle à
contourner, c'est le contrôle qui fonctionne.** Lire `reason_code` :

| `reason_code` | Cause | Geste |
|---|---|---|
| `MANIFEST_MISSING` | l'image a été construite sans le manifest | reconstruire avec `deploy-v2.sh` |
| `MANIFEST_INCOMPLETE` | un champ requis est vide | vérifier `BUILD_ENVIRONMENT` au build |
| `COMMIT_MISMATCH` | `EXPECTED_GIT_COMMIT` ≠ manifest de l'image | l'image n'est pas celle du commit attendu ; reconstruire |
| `INTEGRITY_BLOCK` | un blocage est posé | le lever explicitement une fois la cause traitée |

### Où vit l'état d'armement

`/app/data/global_execution_switch.json` dans le conteneur, soit
`/opt/scalping/data/global_execution_switch.json` sur l'hôte.

⛔ **Pas** `/var/lib/scalping` : c'est un chemin de l'hôte, utilisé par les
crons, que le conteneur ne voit pas — `scalping.service` ne monte que
`-v /opt/scalping/data:/app/data`. Défaut trouvé le 2026-09-28 **avant**
déploiement : l'état y aurait disparu à chaque redémarrage, donc un
ré-armement aurait été exigé après chaque restart. Un restart n'est pas un
déploiement : c'est l'empreinte de commit qui invalide l'armement, pas la
perte du fichier.

🔑 `/opt/scalping/data` est par ailleurs le seul chemin protégé du
`rsync --delete` du déploiement (incident du 2026-05-18).

### Pour refermer

```bash
sudo docker exec scalping python scripts/execution_switch.py \
     close --raison "<pourquoi>" --par "<prénom>"
```

Une fermeture aboutit **toujours**, même intégrité cassée : une coupure ne se
négocie pas.

---

## 6. Ce qui reste ouvert dans la Phase 0

| Exigence | État |
|---|---|
| REM-001 porte de chaîne fail-closed | ✅ codé, testé, muté |
| REM-002 kill switch global | ✅ codé, testé, muté |
| REM-003 manifest de déploiement | ✅ codé, testé, muté |
| REM-004 source unique de code | ⚠️ partiel — le dossier de scripts de l'hôte diverge toujours |
| REM-005 ledger financier | ✅ POSÉ le 01/10 — `trade_financial_ledger`, 31 colonnes du cahier + 6 de provenance, 1 353 lignes. ⛔ largement VIDE et c'est le livrable : 11 colonnes quasi complètes, 10 sous 50 %, 6 vides ASSUMÉES. L'argent n'est vérifié au courtier que sur **496 trades sur 1 353** (36,7 %). |
| REM-006 classification du P&L | ✅ POSÉ le 01/10 — `categorie_pnl` : algorithme **−362,06 €** (232 trades) · main **+177,45 €** (152) · recherche −82,24 € (99), sur argent vérifié seulement. ⛔ 383 trades NON CLASSABLES : le cahier exigeait « exactement une catégorie » et 385 trades n'ont pas d'environnement. ⛔ les 10 ordres du fail-open sont FLAGUÉS `bug_affected`, pas blanchis en « recherche ». |
| REM-007 monitoring end-to-end | ⛔ non commencé |
| Rebuild de l'image | ⛔ non fait |
| Vérification du runtime | ⛔ non faite |

**La Phase 0 n'est donc pas close** au sens du §33 du cahier des charges.

### Et un travail préalable non prévu au cahier des charges

Les ordres de chaîne du 16 au 25 septembre doivent être marqués
`BUG_AFFECTED` (REM-006) : neuf des dix sont passés par le fail-open et leur
P&L est celui d'un défaut, pas d'une méthode. Tant que ce marquage n'existe
pas, le jeu de données reste utilisable par erreur comme verdict.

---

## 7. Fichiers touchés

**Nouveaux**

```
backend/services/chain_execution_gate.py
backend/services/global_execution_switch.py
backend/services/deployment_manifest.py
scripts/generer_manifest_deploiement.py
scripts/execution_switch.py
backend/tests/test_rem001_chain_execution_gate.py
backend/tests/test_rem002_global_execution_switch.py
docs/rem-phase0-containment.md
```

**Modifiés**

```
backend/services/mt5_bridge.py          porte + verrou branchés, return set() retiré
backend/services/rejection_service.py   2 motifs de refus déclarés
backend/app.py                          GET /system/version
backend/tests/conftest.py               fixture d'armement du harnais
backend/tests/test_chaine_dispatch.py   assertion du véhicule → assertion de l'effet
backend/tests/test_mt5_bridge_guard.py  doublures à la forme de la production
backend/tests/test_dispatch_user_vs_admin.py   idem
deploy-v2.sh                            manifest + EXPECTED_GIT_COMMIT
.gitignore                              deployment_manifest.json
```
