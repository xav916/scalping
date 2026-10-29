# `or-politique` — refuser une configuration qui laisse de l'argent réel sans garde

**But :** juger la **configuration déclarée** des destinations actives et sortir
en non-zéro si une destination en argent réel n'a pas de filtre de paires, ou si
ce qui la protège n'est pas lisible.

**Architecture :** cinquième skill du pack `or-*`, même patron qu'`or-porte` —
un **juge pur** testé, un **collecteur impur** non testé. Le transport SSH est
extrait dans `or_commun`, et les trois skills qui s'en servent y sont branchées.
Lecture seule.

**Pile technique :** Python de la bibliothèque standard. `pytest`. Exécution par
`ssh` + `docker exec -i`, charge transmise par **stdin**.

**Spec dont ce document est l'autorité :** celui-ci.

## Contraintes globales

- ⛔ **Lecture seule.** Aucun ordre, aucun armement, aucune écriture de données
  en production. Même contrat qu'`or-etat` et `or-porte`.
- ⛔ **Elle ne BLOQUE rien.** Pas de câblage dans le déploiement, pas de sonde
  Telegram. Elle rapporte et rend un code de sortie ; l'usage est à l'appelant.
- ⛔ **Fail-closed.** Fait illisible, destination inconnue, production
  injoignable : **FAIL** ou code 2, jamais « conforme ».
- 🔑 **Chaque règle nomme la source qui DÉCIDE**, et la valeur lue. Une règle
  sans source est un avis, pas un verdict.
- 🔑 **Elle juge la configuration DÉCLARÉE, jamais le comportement observé** —
  voir « Pourquoi elle ne peut pas sonder ».
- Nommage **français**, aligné sur `or-etat` / `or-porte`.
- Codes de sortie : `0` conforme · `1` au moins un FAIL · `2` n'a pas pu juger.

## Ce qui établit ce besoin

Mesuré en production les 2026-10-29 et 30 (cf.
[[project_or_porte_miroir_des_portes_2026_10_29]]) :

```
admin_destinations() -> admin_legacy, admin_live, admin_kraken   (3 actives)

is_real_money : admin_live True · admin_kraken True · admin_legacy False
LIVE_WHITELIST_PAIRS   = {XAU/USD}            -> admin_live
LEGACY_WHITELIST_PAIRS = {12 paires}          -> admin_legacy
                         (rien)               -> admin_kraken
```

🔴 **`admin_kraken` est en argent réel, joignable, avec 22 buckets `AUTO_EXEC`,
et aucun filtre de paires côté backend.** Son kill-switch vit sur le pont et est
illisible depuis le conteneur. ⇒ C'est le trou que cette skill doit **asserter**
au lieu de le redécouvrir à la main.

⚖️ Et l'asymétrie est parlante : `admin_legacy` **a** une liste blanche de 12
paires mais n'est **pas** en argent réel. La protection existe là où elle ne
tranche rien, et manque là où elle tranche.

## ⛔ Pourquoi elle ne peut pas sonder

L'approche naturelle serait de **sonder** la porte : soumettre une paire hors
liste blanche et vérifier qu'elle est refusée. Une destination qui la laisse
passer n'a pas de filtre.

**C'est impossible aujourd'hui.** `execution_globale_fermee` est la première
clause de `_check_rejection`, fail-closed, et elle court-circuite toutes les
autres tant que REM-002 est désarmé. Prouvé empiriquement : la recette
d'`or-porte` a rendu **25 couples sur 25** avec ce seul motif.

⇒ `or-politique` lit la **configuration**. Conséquence à écrire dans
`SKILL.md` : elle dit si la configuration **déclare** une protection, pas si
cette protection **fonctionne**. Les deux questions sont distinctes, et seule
la première est répondable IA coupée.

## L'extraction dans `or_commun`

Le transport SSH serait sa **troisième** copie. Et la duplication a déjà coûté :
le défaut `python3 -c` a persisté dans `or-etat` **parce que** le correctif
d'`or-porte` n'était pas partagé — deux copies, une seule réparée. Ce n'est donc
pas un refactor spéculatif, c'est le mode de défaillance démontré.

**Nouveau module : `or_commun/distant.py`**

```python
def executer_a_distance(depot: pathlib.Path, src: str,
                        timeout: int = 90) -> dict:
```

Il porte le comportement déjà éprouvé : charge par **stdin**
(`sudo docker exec -i scalping-radar python3 -`, `input=src`), **pas** de `-n`
(il fermerait ce stdin), dernière ligne commençant par `{` (la bannière SSH
pollue `stdout`), et **lève** sur une sortie illisible.

**L'idiome d'import est celui déjà en service dans `or-verdict`** :

```python
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from or_commun import distant
```

**Les trois branchements :** `or-etat/etat.py` et `or-porte/porte.py` perdent
leur copie privée et appellent `distant.executer_a_distance` ; `or-politique`
l'utilise d'emblée.

⚠️ **Les tests de transport existants d'`or-etat`
(`tests/test_transport.py`) déménagent dans `or_commun/tests/`** : ils testent
désormais le module partagé, et c'est là qu'ils doivent échouer si quelqu'un
revient à `python3 -c`.

## Ce qu'`or-politique` lit, et qui décide

| fait | source qui DÉCIDE | note |
|---|---|---|
| destinations actives | `bridge_destinations.admin_destinations()` | ce que la production itère (`mt5_bridge.py:2612`) |
| argent réel | `destinations_registry.is_real_money()` | ⚠️ **seule source** — `BridgeConfig` ne porte pas `reel` |
| filtre de paires | `mt5_bridge.LIVE_WHITELIST_PAIRS` / `LEGACY_WHITELIST_PAIRS` | ⚠️ le **mappage** destination↔liste est codé en dur (`mt5_bridge.py:1100-1117`) |
| classes autorisées | `BridgeConfig.allowed_asset_classes` | le registre **diverge** : il annonce `equity` pour `admin_live` et `metal` pour `admin_kraken`, à tort |
| seuil de confiance | `BridgeConfig.min_confidence` | 42,0 sur les trois |
| garde-fous du pont | `/health` → `garde_fous` | vide sur les ponts non-MT5, qui ne publient pas ce champ |

🔑 **Le mappage destination↔liste blanche est le seul fait reconstruit**, parce
qu'il n'existe que sous forme de `if dest_id_wl == "admin_live"` dans le code de
la porte. `SKILL.md` doit le déclarer, et un **test de dérive** doit échouer si
la production ajoute, retire ou renomme une liste blanche.

## Les cinq règles

Chacune rend `CONFORME`, `FAIL` ou `ILLISIBLE`, et nomme sa source et sa valeur.

| # | règle | verdict si violée |
|---|---|---|
| 1 | argent réel **et** aucun filtre de paires applicable | **FAIL** |
| 2 | argent réel **et** `/health` ne publie aucun garde-fou | **FAIL** — on ne peut pas vérifier ce qui protège |
| 3 | argent réel **et** `min_confidence` absent ou `<= 0` | **FAIL** |
| 4 | destination active **absente** du registre | **FAIL** — impossible de savoir si c'est de l'argent réel |
| 5 | classes du registre ≠ `allowed_asset_classes` | **WARN**, pas FAIL |

**Pourquoi la règle 5 n'est qu'un WARN :** la divergence est connue et le
`BridgeConfig` tranche ; la production se comporte donc correctement. Le risque
est qu'un **humain** lise le registre et se trompe — un avertissement, pas un
défaut de configuration.

⛔ **Aucune règle ne propose de desserrer une limite comme correctif.** Si la
seule issue est d'élargir une liste blanche, le rapport le dit comme une
**décision à prendre**, jamais comme un correctif.

## La sortie

Une section par destination active : son `bridge_type`, si elle est en argent
réel, puis une ligne par règle avec son verdict, la source et la valeur lue. En
tête : l'empreinte `fingerprint_running`, l'état d'armement, et le rappel que
**seule la configuration déclarée est jugée**.

En pied : le total, et la liste des faits qui n'ont pas pu être lus.

## Les erreurs

| cas | comportement |
|---|---|
| production injoignable | code 2, message distinguant « injoignable » de « a répondu mais illisible » |
| `admin_destinations()` vide | code 2 — une production sans destination active est invraisemblable, donc suspecte |
| `/health` illisible pour une destination | règle 2 rend `ILLISIBLE` → **FAIL** si argent réel |
| une règle lève | cette règle rend `ILLISIBLE`, les autres continuent, la trace est en pied |

## Les tests

**1. Juge pur, sur des entrées synthétiques.** Les cinq règles, chacune dans ses
deux sens : violée et respectée. Plus les combinaisons qui comptent — argent
réel sans filtre **et** sans garde-fou doit rendre **deux** FAIL, pas un.

**2. Témoin à réponse connue d'avance.** Avec la configuration **réelle du
2026-10-30**, le juge doit rendre :

| destination | attendu |
|---|---|
| `admin_kraken` | **FAIL règle 1** (argent réel, aucun filtre) **et FAIL règle 2** (`garde_fous = {}`) |
| `admin_live` | règle 1 **CONFORME** (`{XAU/USD}`) · règle 2 conforme (garde-fous publiés) |
| `admin_legacy` | règles 1 et 2 **non applicables** (pas d'argent réel) |

⚠️ Et le témoin doit aussi fixer ce que la skill **ne** doit **pas** dire :
aucun FAIL sur `admin_legacy`. Une skill qui alerte sur un compte papier crie
au loup, et on cesse de la lire.

🔑 Ce témoin vient de mesures faites **avant** que la skill existe, et pas de la
table que la skill lira — cf.
[[feedback_un_temoin_doit_avoir_une_source_independante]].

**3. Dérive du mappage.** Un test qui, **dans le conteneur**, recense les
constantes de liste blanche de `mt5_bridge` et échoue si l'ensemble diffère de
`{LIVE_WHITELIST_PAIRS, LEGACY_WHITELIST_PAIRS}`. Sans lui, l'ajout d'une liste
blanche côté production rendrait le verdict faux en silence.

**4. Transport partagé.** Les tests déménagés dans `or_commun/tests/` : la
charge passe par stdin et non par l'argv, aucun fragment de code n'apparaît dans
l'argv, une sortie illisible lève.

**5. Non-régression des deux branchements.** `or-etat` et `or-porte` doivent
rester verts après avoir perdu leur copie privée, et `or-etat` doit encore
rendre `=> DESARME, verifie sur les 3 voies` en vrai.

⚠️ **Aucun `tests/__init__.py`** et aucun nom de fichier de test déjà employé
dans une autre skill du pack : c'est la collision introduite le 29/10 et
corrigée en `a59f7a4`.

## La recette

1. `python .claude/skills/or-politique/politique.py` sort en **1**, et nomme
   `admin_kraken` comme la cause sur **DEUX** règles, pas une : la **1** (argent
   réel, aucun filtre de paires) **et** la **2** — son `/health` rend
   `garde_fous = {}`, mesuré le 29/10, parce que les ponts non-MT5 ne publient
   pas ce champ. ⓘ Les deux FAIL disent la même inquiétude par deux chemins :
   rien de lisible ne protège cette destination. Le rapport doit les montrer
   **séparément**, et non les fondre en un seul motif.
2. Les trois destinations apparaissent, chacune avec son `bridge_type` et son
   statut d'argent réel.
3. La règle 5 avertit sur `admin_live` (`equity`) et `admin_kraken` (`metal`).
4. Les cinq suites du pack passent **en une seule commande**.
5. `or-etat` rend toujours `=> DESARME`, exit 0.

## Suites

- **Fermer le trou** : donner à `admin_kraken` un filtre de paires côté backend,
  comme en a `kraken_spot` (`_SPOT_SUPPORTED_PAIRS`). `or-politique` devient
  alors le test qui prouve la fermeture — elle doit passer de **1** à **0**.
- **Les 9 libellés FR manquants** dans `REASON_LABELS_FR`.
- Faire publier ses garde-fous par le `/health` du pont Kraken, pour que la
  règle 2 cesse d'être `ILLISIBLE` là-bas.
