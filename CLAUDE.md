# Scalping — notes projet

> **Dernière mise à jour : 2026-10-31.** Ce fichier décrit le système
> **d'aujourd'hui**. L'ancienne version décrivait une démo MetaQuotes sur 16
> paires avec une feuille de route en 5 phases ; rien de tout cela n'était
> encore vrai (constat G-1 de l'audit du 2026-09-16).

---

## ⛔ Règles non négociables

Ces trois règles ne se discutent pas au cas par cas. Elles existent parce que
chacune a déjà coûté quelque chose.

### 1. Aucun signal directionnel sans banc pré-inscrit

Pas de nouveau signal, indicateur ou biais **directionnel** sans un banc
**pré-enregistré avant d'écrire le code**, sur une **fenêtre de données
neuve**, avec **plafond par permutation** et **hors échantillon**.

**Pourquoi :** la direction a été réfutée **quatre fois**, par quatre chemins
indépendants — le radar seul (n=59, aucune p sous 0,27, réussite 49,4 %), les
bornes symétriques (64 062 détections, 6 géométries, 49,83 %), la volatilité
(elle ne dit ni quand ni dans quel sens), le dollar et les taux (l'information
est **entièrement contemporaine** : r = −0,42 le même jour, rien la veille).
Et le contrôle aléatoire a montré que **rien ne battait le hasard** tant que le
plafond n'était pas calculé.

**En pratique :** passer par `or-preinscription` **avant** d'écrire la mesure,
puis par `or-verdict` **avant** d'annoncer le moindre chiffre.

### 2. La largeur du stop n'est pas un levier

**Pourquoi :** **43 cellules mesurées le 2026-10-14, zéro retenue.** Le constat
qui ferme le sujet : **l'agitation d'avant l'entrée ne prédit pas la perte**.
Un banc antérieur avait déjà balayé k = 0,5 → 3 en pré-déclarant les
prédictions : le coût était divisé par 2,9 et le R restait **négatif partout**.

Corollaire mesuré le même mois : **baisser le déclencheur du traînage est
refusé** — la réussite tombe de 78,1 % à 48,4 % pour un rendement inchangé.

### 3. Tout changement qui touche au trading passe par la suite de tests en CI

Pas de dérogation « c'est une petite modification ». La suite est le seul
endroit où une régression se voit avant l'argent réel.

⚠️ **Et un « c'est vert » ne prouve rien tout seul** (constat R-27 de
l'audit) : 8 exécutions du *même* commit ont donné 7 × `4268 passed` et
1 × `4262 passed, 6 failed`, cause inconnue. Seule compte la **preuve
ciblée** : rouge sans le correctif, vert avec, et on le montre.

---

## Ce qui tourne réellement

### Le courtier et les destinations

| Destination | Quoi | Argent |
|---|---|---|
| `admin_live` | **IC Markets via MT5** — forex et or | réel |
| `admin_ibkr_us` | **IBKR** — actions américaines | réel |
| `admin_kraken` | **Kraken** — crypto | réel |
| `admin_legacy` | ancienne route MT5 | réel |
| `admin_kraken_spot`, `admin_kraken_stocks`, `admin_binance` | déclarées, **inactives** | — |

Le registre en déclare **7** ; **3 seulement sont actives**.

🔑 **Le registre déclare, le `BridgeConfig` décide.** Une destination présente
dans `destinations_registry.py` n'est pas pour autant joignable, et une
destination joignable n'a pas pour autant ses filtres armés. C'est ce
décalage qui a laissé `admin_kraken` pousser en argent réel **sans filtre de
paires** jusqu'au 2026-10-30 (`fb8b283`) : la liste blanche existait, mais elle
était gardée par `bridge_type == "mt5"`.

### En argent réel, une seule paire

```
MT5_BRIDGE_LIVE_WHITELIST_PAIRS=XAU/USD
```

**L'or, et rien d'autre**, depuis le 2026-10-08. Donc IBKR, l'énergie et les
indices ne partent pas en réel même si leur classe d'actif est autorisée par
`MT5_BRIDGE_ALLOWED_ASSET_CLASSES=forex,metal,energy,crypto`.

`WATCHED_PAIRS` en compte 25 — c'est l'univers **observé**, pas l'univers
**tradé**. Ne jamais confondre les deux.

### 🛑 L'IA de trading est COUPÉE

**REM-002 `DISARMED_MANUALLY` depuis le 2026-10-12.** Décision de Xavier après
une journée à **−38,31 €** : « j'ai perdu assez d'argent aujourd'hui ».
`MT5_SERVER` est vide.

⛔ **Le réarmement demande une décision humaine explicitement nommée.** Aucun
agent ne le fait de lui-même, aucune tâche ne le fait « au passage ».

Vérifier avec `or-etat`, qui contrôle les **trois voies d'ordre** au lieu d'un
seul drapeau — un seul drapeau vert ne prouve pas que les trois sont fermées.

### Les garde-fous armés

- **Porte du banc d'essai** (`RESEARCH_BENCH_GATE_ENABLED=true`) — une
  promotion vers `AUTO_EXEC` en argent réel exige un essai passé, ou la
  clause d'antériorité du 2026-08-25.

  ⚠️ **Deux chiffres, et ils ne disent pas la même chose** (mesuré le
  2026-10-31) : sur les 98 buckets évalués, **21 n'ont aucune couverture
  de banc** — c'est l'*exposition* — mais seulement **14 sont refusés à
  chaque cycle**, parce que la porte n'est consultée que quand le
  contrôleur *tente* une promotion. Les 7 d'écart : 4 paires fantômes
  (guillemets collés, aucune donnée) et 3 buckets `DEMOTED`, que le
  contrôleur ne re-promeut pas. Réconcilié bucket par bucket sur les
  journaux de production, sans aucun refus non prédit.

  🔑 Et aucun des 21 n'est en `AUTO_EXEC` : la porte n'a rien retiré.
- **Bloc de risque** — plafond en euros, poches par devise, métaux séparés,
  et un refus explicite quand le taux n'est pas vivant.
- **28 motifs de refus** ont réellement mordu sur l'or. Les deux qui mordent
  le plus : `fees_exceed_edge` (1 238 refus, plancher de viabilité
  **13,83 $** = prix/300) et `sl_too_close` (431 refus, stop d'ouverture à
  **≥ 0,05 %** = 2,075 $).

🔑 Ces garde-fous **bloquent l'ouverture**. Ils ne gèrent pas une position
déjà ouverte.

### Construit mais désarmé

- **Pause après rafale de stops** — `RAFALE_AUTO_PAUSE_ENABLED=false`,
  décision de Xavier le 2026-10-12 après 57 minutes sans un trade.
- **Suivi des trades à la main** — `EQUIPER_TRADES_MAIN_SUIVI=0` : le stop est
  **posé une fois** (13 € / objectif 20 €) puis **plus jamais suivi**.
- **Horizon `1d` et lignes rattrapées** — écartés du vivier d'admission
  (`4232ae7`, `00bbb2b`) : le vivier est passé de 26 465 à 5 679.

---

## Les skills `or-*`

Cinq skills, toutes bâties sur le même patron : un **juge pur et testé**, et un
**collecteur impur** qui va chercher l'état réel. Elles **importent** les
portes de production, elles ne les réimplémentent jamais.

| Skill | Ce qu'elle refuse |
|---|---|
| `or-etat` | de dire « c'est armé » sans avoir vu les **trois** voies d'ordre |
| `or-politique` | une configuration qui laisse une destination en réel **sans filtre de paires**, ou dont les garde-fous sont illisibles |
| `or-porte` | de **deviner** si un setup passerait : elle rejoue les ~30 portes réelles, par destination |
| `or-preinscription` | une mesure dont le critère n'est **pas falsifiable** — à invoquer **avant** d'écrire un banc |
| `or-verdict` | de publier un chiffre dont le rejeu n'est pas valide — à invoquer **avant** d'annoncer |

---

## Comment travailler ici

### Chercher du code

⛔ **L'instrument est l'AST, jamais le texte.** Le 2026-10-30, un `grep -c` a
conclu l'inverse du réel **trois fois**, et dans les deux sens : il trouve la
**prose qui décrit** le motif autant que le motif.

### Prouver qu'une chose marche

- **Un module qui compile n'a pas prouvé qu'il tourne.** Deux `NameError`
  livrées le même jour après un import réussi — l'erreur n'apparaît qu'à
  l'**appel**.
- **Un test insensible au défaut ne prouve rien.** Quatre défauts ont été
  livrés avec 42 tests verts, à cause de doublures qui ne ressemblaient pas au
  vrai.
- **Tester l'instrument sur un témoin avant de conclure à une absence.** Trois
  instruments faux d'affilée ont fait croire à une absence qui n'existait pas.
- **Un témoin doit avoir une source indépendante de l'instrument** : témoin 25,
  outil 25, réalité 22 — même table fausse des deux côtés, donc accord parfait
  et vide.
- **« Absent » n'est pas « vide », ni « zéro », ni « faux ».** Une première
  réconciliation a été livrée **inerte** parce qu'elle exigeait un zéro
  explicite là où un symbole à plat est simplement **absent**.

### Toucher à l'historique ou à la configuration

- **Un historique ne se nettoie pas en supprimant** : un `DELETE` **ressuscite**
  l'état d'avant, donc **arme** des buckets. On ajoute une ligne, on n'en retire
  pas. La preuve d'un nettoyage réussi, c'est des **comptes identiques avant et
  après**.
- **La spécificité bat la récence** : la cascade d'états va du plus **spécifique**
  au plus général, pas du plus récent au plus ancien. Un SQL naïf s'est trompé
  sur **79 clés contradictoires sur 79**.
- **Écrire en atomique, jamais `open(p, 'w')`** : un `open` tronque **avant**
  d'écrire. C'est comme ça que l'index de mémoire a été détruit.

### Déployer

```
SCALPING_HOST=ec2-user@13.63.77.180 bash deploy-v2.sh
```

La clé est **dans le dépôt** (`scalping-key.pem`, à la racine). Le script fait
le préflight, pousse, tire, produit le manifeste REM-003 avec `--exiger-propre`
**avant** le build, construit, pose `EXPECTED_GIT_COMMIT`, redémarre.

⚠️ **Un script de `/opt/scalping/jobs/` écrase celui de l'image à chaque
minute** — un rebuild ne le déploie donc pas.

⚠️ **Le pont Kraken se déploie à la main** : `/opt/kraken-bridge/bridge.py`
(root:root 644), service `kraken-bridge.service`, port 8790 vu comme
`172.17.0.1:8790` depuis le conteneur. CRLF→LF, scp, `py_compile` avec
`/opt/kraken-bridge/venv/bin/python`, `sudo install`, redémarrage — **un à la
fois**, le classifieur refuse un script `sudo` composé.

### Comparer deux fichiers

Par **md5 normalisé**. CRLF contre LF a fait différer 2 027 lignes de
2 027 octets.

### Les secrets

⛔ **Ne jamais afficher un identifiant, ni diffuser un fichier de secrets.**
Pour comparer deux `.env` : md5 et **noms de clés**, jamais le contenu.

---

## Architecture

- **Backend** : FastAPI sur EC2, derrière nginx et Let's Encrypt
- **Données** : Twelve Data, plus les bougies **du courtier** (c'est sur
  celles-ci que les bancs doivent tourner : les bougies d'un fournisseur tiers
  ont déjà produit un backtest invalide)
- **Auth** : cookies HttpOnly, session same-origin
- **Ponts** : MT5 sur PC Windows (IC Markets), pont Kraken sur l'EC2, IBKR

Le décalage horaire du pont est **déterministe** :
`-decalage_serveur_sec/60 + 180`, **à soustraire** (vérifié 21 jours sur 21,
154 ancres).

---

## Ce que ce système fait, honnêtement

> « Ce cycle ne gagne pas d'argent, il arrête d'en perdre bêtement. »
> — `docs/cycle-de-vie-d-un-trade-or.md`

La direction est muette. Ce qui a été mesuré comme payant, c'est la **gestion
de sortie** : le 2026-10-12, le **stop devenu positif** a apporté **100 % des
gains** (`TRAILING_SL`, n = 108, +64,02 €).

Pour le détail d'un trade de bout en bout, lire
[`docs/cycle-de-vie-d-un-trade-or.md`](docs/cycle-de-vie-d-un-trade-or.md).
Pour l'état de la production, [`docs/architecture-current-state.md`](docs/architecture-current-state.md).
