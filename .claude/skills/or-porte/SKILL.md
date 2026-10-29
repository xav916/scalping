---
name: or-porte
description: >-
  Dit si un setup or partirait, et sinon pourquoi, en rejouant les ~30 portes
  REELLES de production par destination au lieu de les deviner. A utiliser
  quand on demande « est-ce que ce setup passerait », « pourquoi ce setup a
  ete refuse », « que partirait-il si on rearmait », « quelles paires sont
  armees sur cette destination », ou avant toute decision de rearmement.
  Rend PASS/BLOCK par setup et par destination, avec le motif, son libelle
  francais, son ORIGINE (`production` ou `lot`) et le correctif. Lecture
  seule : elle ne passe aucun ordre, n'arme rien et n'ecrit jamais dans la
  base de production.
argument-hint: "[--depuis-vivier DESTINATION | --lot fichier.json]"
---

# or-porte

```bash
python .claude/skills/or-porte/porte.py                        # or/lot.json
python .claude/skills/or-porte/porte.py --depuis-vivier admin_kraken
python .claude/skills/or-porte/porte.py --json
python .claude/skills/or-porte/porte.py --no-write
```

Codes de sortie : `0` tout passe · `1` au moins un `BLOCK` · `2` n'a pas pu
juger. Les trois sont distincts : « tout bloque » et « je n'ai pas pu juger »
ne doivent pas se confondre.

⚠️ Sur un depot fraichement clone, `or/lot.json` n'existe pas (il est
gitignore, comme `or/state/`) : lancer la commande sans argument sort donc en
code **2** avec « lot illisible ». C'est le comportement voulu. Partir de
`or/exemple-lot.json`, le copier en `or/lot.json`, puis l'adapter.

## Ce qu'elle garantit

- ⛔ **Elle n'invente aucun verdict de production.** Les refus d'origine
  `production` viennent d'un appel a `mt5_bridge._check_rejection` execute
  dans le conteneur. Aucune porte n'est recopiee ici.
- 🔑 **Deux empreintes.** `empreinte_setup` sur les onze champs que les portes
  lisent vraiment : un setup modifie doit repasser. `empreinte_code` sur le
  `fingerprint_running` de production : un verdict calcule contre un autre
  code est NUL.
- ⚠️ **Quatre clauses sont un AJOUT** — places par paire, exposition
  correlee, risque engage, cadence. `_check_rejection` juge un setup a la
  fois ; ces quatre simulent les remplissages successifs du lot. Elles
  portent `origine: lot`, et le rapport le rappelle en tete.
- ⛔ **Fail-closed.** Limite illisible, empreinte absente, verdict manquant :
  `BLOCK` ou code 2, jamais `PASS`.
- ⚠️ **`--depuis-vivier` construit des setups SANS PRIX**
  (`entry_price=0`, `stop_loss=0`). Les portes independantes du prix restent
  significatives ; celles qui dependent du prix (`fees_exceed_edge`,
  `sl_too_close`, …) ne le sont pas, et le rapport l'affiche en en-tete.

## Ce qu'elle ne fait pas

Elle ne choisit pas de setups et n'en invente aucun : **aucune information
d'entree n'a jamais ete demontree sur l'or**. Elle ne bloque rien en
production non plus — c'est un miroir. Rendre la porte executoire est un
chantier distinct, volontairement differe.

## Exige

Un acces SSH a l'EC2 par `scalping-key.pem` a la racine du depot. Les portes
lisent la configuration et la base de production : les juger depuis un poste
rendrait un verdict qui ne decrit aucune realite.
