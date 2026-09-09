# Ajouter un concept de trading — la recette

Écrite le 2026-09-09, après l'intégration du *Fair Value Gap* et de la règle du
gap. Elle a pris **2 h**, dont l'essentiel en redécouverte des étapes et en
pièges retrouvés un par un. Avec cette recette, la suivante prend **30 min**.

> ⛔ **La règle qui prime sur tout.** Un motif se **mesure** avant d'être armé.
> Sept motifs mesurés avant septembre, **aucun ne bat le hasard**
> (Δ = +0,004 R sur 29 000 trades). Le but n'est pas d'espérer qu'un motif de
> plus sauve la mise : c'est de **réfuter vite et pas cher**.

---

## Ce que ça coûte, mesuré

Ajouter des concepts est **statistiquement bon marché**. Le plafond du hasard —
le `|t|` qu'il faut dépasser pour que le laboratoire retienne une cellule —
croît en `√(2·ln k)` :

| cellules | plafond \|t\| |
|---|---|
| 14 | 2,02 |
| 56 | 2,55 |
| **80** | **2,67** ← après les 6 motifs de gap |
| 200 | 2,96 |
| 400 | 3,17 |

Passer de 56 à 400 cellules ne coûte que **+0,62 de |t|**. Le frein n'est donc
pas statistique : c'est le temps de codage. D'où cette recette.

---

## Les six étapes

### 1. Écrire la règle AVANT de coder

Dans `docs/concepts-trading.md`, déclarer :

- la **tradition** d'où vient le concept (ICT, analyse classique, autre) ;
- la **règle exacte**, en termes d'OHLC ;
- surtout : **la prédiction falsifiable**. « Le prix retrace puis repart » est
  falsifiable. « Le marché respecte cette zone » ne l'est pas.

> ⛔ Sans cette étape, on code d'abord et on cherche ensuite ce qu'on voulait
> prouver. C'est ainsi qu'on finit par ajuster un seuil jusqu'à ce que ça
> « marche ».

⚠️ **Aucun seuil réglable si on peut l'éviter.** Le FVG standard n'en a aucun
(`bas[3] > haut[1]`) — c'est sa force. Quand un seuil est inévitable, le poser
**une fois** et le déclarer arbitraire dans le code, jamais le régler ensuite.

### 2. Déclarer les types

`backend/models/schemas.py`, enum `PatternType`. Un type **par sens** :
`monmotif_up` / `monmotif_down`.

### 3. Coder le détecteur

`backend/services/pattern_detector.py` :

```python
def _detect_mon_motif(candles: list[Candle], pair: str) -> list[PatternDetection]:
    patterns = []
    if len(candles) < 3:
        return patterns
    atr = _calculate_atr(candles, period=14)
    if atr <= 0:
        return patterns
    ...
    return patterns
```

Puis le brancher dans `detect_patterns` — **sinon il ne tourne jamais**.

⚠️ **Si le concept a plusieurs verdicts, les rendre EXCLUSIFS.** S'ils peuvent
coexister, chaque fenêtre alimente les deux cellules du laboratoire et l'écart
mesuré entre elles est un artefact, pas un résultat.

### 4. Le libellé français

`backend/services/telegram_service.py`, dict `_PATTERN_EXPLAIN_FR`.
**Vulgarisé** : Xavier lit ces libellés sur Telegram, pas le code.

Un test l'exige déjà (`test_tous_les_patterns_ont_un_libelle_fr`) — il tombera
si tu l'oublies.

### 5. La porte de fréquence

`backend/tests/test_frequence_des_motifs.py` tourne automatiquement sur une
fixture de **5 000 vraies bougies** (17 jours). Elle refuse deux choses :

- un motif qui ne se déclenche **jamais** → condition impossible, faute de frappe ;
- un motif au-dessus de **25 %** des fenêtres → un état permanent du marché
  déguisé en signal.

⚠️ **Elle ne juge PAS la rareté utile** : c'est le travail du laboratoire, qui
dispose de 90 jours. Une première version imposait un plancher à 1 % et recalait
quatre motifs sains — le seuil n'était pas trop strict, il était **mal
spécifié** (3,5 jours contre 90).

### 6. Ne rien armer

**Il n'y a rien à faire.** La whitelist de dispatch est *fail-closed* : un motif
absent des listes d'autorisation rend `pattern_not_allowed`. Le laboratoire,
lui, itère sur `detect_patterns` et prendra le nouveau motif **tout seul** dès
la nuit suivante (03:40 UTC).

⇒ Un motif neuf est **mesuré sans être joué**. C'est l'invariant qui rend
l'exercice sans risque.

---

## Les pièges, tous payés au moins une fois

| piège | ce qu'il coûte |
|---|---|
| **Le banc d'essai qui dérive** | `detect_patterns` voit `CANDLE_COUNT = 50` bougies en production. Lui en passer 5 000 rendait `poc_return_down` à **48 %** au lieu de 5,6 %. Un banc qui ne reproduit pas la fenêtre mesure un autre système. |
| **Les balises HTML** | L'endpoint Telegram échappe le HTML : un `<b>` s'affiche tel quel. Défaut propagé sur **huit** sondes. `test_sondes_sans_balises` le verrouille. |
| **`docker exec python`** | Démarre un processus **neuf**, au cache froid. Y lire un cache applicatif ne dit **rien** sur l'application. M'a fait diagnostiquer un défaut inexistant. |
| **Le correctif non branché** | Écrit, testé, déployé — et jamais appelé. Toujours vérifier en production qu'il **agit**, pas seulement qu'il est là. |
| **Les tests qui bouchonnent la fonction fautive** | Ils passent quelle que soit son implémentation. Prévoir au moins un test qui exerce la **vraie** fonction. |
| **Le test qui appelle le réseau** | `test_phase4_e2e` se fait jeter en 429 selon l'ordre de la batterie. Il m'a fait accuser mon propre code deux fois le même jour. La fixture est figée pour cette raison. |

---

## Vérifier que ça a marché

```bash
# les tests du motif + la porte de fréquence
python -m pytest backend/tests/test_frequence_des_motifs.py -q

# après déploiement, en production : le motif se détecte-t-il VRAIMENT ?
ssh ... "sudo docker exec scalping-radar python -c \"
import asyncio, collections
from backend.services import price_service as ps, pattern_detector as pd
c,_ = asyncio.run(ps.fetch_candles('XAU/USD', interval='5min', outputsize=300))
n = collections.Counter()
for i in range(50, len(c)):
    for p in pd.detect_patterns(c[i-50:i], 'XAU/USD'): n[p.pattern.value] += 1
print(n)
\""
```

Puis **attendre la nuit**. Le laboratoire rend son verdict à 03:40 UTC, cellule
par cellule, contre un tirage au hasard.
