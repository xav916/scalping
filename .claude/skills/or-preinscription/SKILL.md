---
name: or-preinscription
description: >-
  Refuse une mesure sur l'or dont le critere n'est pas falsifiable. A utiliser
  AVANT d'ecrire un banc, un rejeu, une mesure ou une etude sur l'or, le
  scalping ou une regle de gestion : verifie qu'il existe un critere a seuils
  numeriques, au moins une condition d'ADMISSION (et pas seulement « pas
  significativement pire »), un plafond par permutation des que plusieurs
  cellules sont testees, une condition de validite du rejeu, au moins trois
  predictions numerotees, et que la pre-inscription est commitee AVANT le banc.
  Declenche sur : « mesurer », « banc », « rejeu », « est-ce que X marche »,
  « tester une regle », avant tout code d'analyse.
---

# or-preinscription

```bash
python .claude/skills/or-preinscription/preinscrire.py \
  docs/predictions/AAAA-MM-JJ_sujet.md --banc scripts/banc_sujet.py
```

Code 0 : le banc peut etre ecrit. Code 1 : la liste des manques, et **on
n'ecrit pas le banc**.

## Pourquoi cette skill existe

Le 13/10 j'ai annonce « la protection a evite 642 EUR ». La methode, ecrite
dans `docs/predictions/`, disait deja de ne pas publier un majorant. Le
verdict du 25/10 a montre que ce chiffre etait faux **de signe**. La liste de
controle existait et ne m'a pas arrete.

## Le bloc machine, obligatoire

```
<!-- CRITERE-MACHINE
admission: t > +2
rejet: t < -2
validite: abs(ecart_par_trade) < 0.50
cellules: 5
plafond: permutation_p95
-->
```

⛔ `admission` est la cle qui manquait les 12/10 et 14/10. Une condition de
non-degradation ne peut jamais admettre.
⛔ `plafond` est exige des que `cellules > 1` : le 14/10, **sept** cellules
auraient passe a `t = 2`, et le hasard seul en fait passer autant.
