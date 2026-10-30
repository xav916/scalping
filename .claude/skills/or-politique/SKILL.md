---
name: or-politique
description: >-
  Refuse une configuration qui laisse une destination en argent reel sans
  filtre de paires, ou dont les garde-fous ne sont pas lisibles. A utiliser
  quand on demande « la configuration est-elle saine », « qu'est-ce qui
  protege l'argent reel », « peut-on rearmer », « quelles destinations sont
  actives », ou AVANT toute decision de rearmement. Rend un verdict par
  destination et par regle, chacun nommant la SOURCE qui decide et la valeur
  lue. Lecture seule : elle ne passe aucun ordre, n'arme rien, ne bloque
  aucun deploiement.
argument-hint: "[--json]"
---

# or-politique

```bash
python .claude/skills/or-politique/politique.py
python .claude/skills/or-politique/politique.py --json
```

Codes de sortie : `0` conforme · `1` au moins un FAIL ou ILLISIBLE · `2` n'a
pas pu juger.

## ⚠️ Ce qu'elle juge, et ce qu'elle ne juge pas

Elle dit si une protection est **DECLAREE**, pas si elle **FONCTIONNE**. Les
deux questions sont distinctes, et seule la premiere est repondable tant que
l'IA est coupee : `execution_globale_fermee` est la premiere clause de la
porte et court-circuite toute sonde (mesure du 29/10 : 25 couples sur 25).

## Les cinq regles

| # | regle | verdict si violee |
|---|---|---|
| 1 | argent reel sans filtre de paires | **FAIL** |
| 2 | argent reel sans garde-fou lisible | **FAIL** |
| 3 | argent reel avec `min_confidence <= 0` | **FAIL** |
| 4 | destination active absente du registre | **FAIL** |
| 5 | classes du registre differentes de celles de la porte | **WARN** |

La 5 n'est qu'un WARN : la production se comporte correctement puisque c'est le
`BridgeConfig` qui tranche. Le risque est qu'un **humain** lise le registre.

🔴 `ILLISIBLE` (donnee presente mais non interpretable, ex. `min_confidence`
non numerique) compte comme un ECHEC au meme titre que `FAIL` : une donnee
qu'on n'a pas pu lire n'est pas une absence de probleme. Le resume distingue
les deux comptes pour que le lecteur sache lequel il affronte.

## Le seul fait reconstruit

Le mappage destination <-> liste blanche n'existe que sous forme de
`if dest_id_wl == "admin_live"` dans `mt5_bridge.py:1100-1117`. Il est donc
reconstruit ici, et `tests/test_derive_listes.py` echoue si la production
ajoute, retire ou renomme une liste blanche. Tout le reste est LU depuis la
production.

## Exige

Un acces SSH a l'EC2 par `scalping-key.pem` a la racine du depot.
