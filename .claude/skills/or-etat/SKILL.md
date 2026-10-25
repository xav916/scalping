---
name: or-etat
description: >-
  Dit si l'IA de trading sur l'or est armee, et par quoi, en verifiant les
  TROIS voies d'ordre au lieu d'un seul drapeau. A utiliser quand on demande
  « est-ce arme », « l'auto-trading est-il coupe », « peut-il passer un ordre »,
  « quel est l'etat du robot », ou avant/apres toute intervention sur la
  production. Lecture seule : elle n'arme, ne desarme et ne deploie jamais.
---

# or-etat

```bash
python .claude/skills/or-etat/etat.py
```

Code 0 : l'etat est determine (arme ou desarme, elle le dit). Code 1 : il ne
l'est pas, ou une voie contredit les autres.

## Les trois voies, et pourquoi trois

```
1. _push_to_destination  -> decision REM-002
2. _mirror_fill_to_live  -> _mirror_active()
3. file de l'EA          -> PENDING dans mt5_pending_orders
```

La voie 3 ne passe **pas** par le backend : `ScalpingRadarEA.mq5` fait un
`OrderSend` natif depuis la table. Le 25/10, repondre a la question a demande
vingt minutes parce que je cherchais un drapeau et qu'il en fallait trois.
