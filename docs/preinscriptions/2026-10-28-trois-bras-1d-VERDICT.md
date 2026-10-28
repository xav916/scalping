# Verdict — la porte TIENT, et ce n'est PAS le même mécanisme sur le `1d` que sur le `5min`

**Pré-inscription** : `07bd2d9` · **Divulgation** : en tête de la pré-inscription
**`or-verdict` : PUBLIABLE — ADMISSION** · **5 prédictions sur 5, dont SEULEMENT DEUX étaient aveugles**

## Le résultat

```
reproduction ISSUE_STOCKEE : 0,0003 %        reproduction du placebo : 0,099 %
```

| cellule | bras | espérance | ÉCART | `t` |
|---|---|---|---|---|
| **`1d`** | `ISSUE_STOCKEE` | −0,064062 | −0,105410 | −4,226 |
| | `GEOMETRIE_RECALCULEE` | −0,052925 | −0,094273 | −3,780 |
| | **`FILL_OUVERTURE`** | **+0,154197** | **+0,112848** | **+4,524** |
| | *désaccord 1,17 % · artefact **−0,207122** · entrées hors bougie **79,7 %*** | | | |
| **`4h`** | `ISSUE_STOCKEE` | −0,266410 | −0,021834 | −0,974 |
| | `GEOMETRIE_RECALCULEE` | −0,266409 | −0,021832 | −0,974 |
| | **`FILL_OUVERTURE`** | −0,255699 | −0,011122 | −0,496 |
| | *désaccord **0,00 %** · artefact −0,010710 · hors bougie 86,6 %* | | | |

## ✅ LA PORTE TIENT — et elle tue DEUX de mes affirmations

**`ISSUE_STOCKEE` reproduit à 0,0003 %** ⇒ je lis bien **les mêmes lignes** que
les bancs publiés. C'est la porte qui manquait au banc précédent.

Et les deux prédictions **réellement aveugles** passent :

- **`P5` : le placebo publié a reproduit à 0,099 %.** ⇒ 🔴 **Ma thèse d'une
  « dérive de 17,4 % avec la frontière de données » est morte une seconde
  fois** : le placebo, qui n'avait pourtant **pas** de `fin_chargement`, n'a
  **pas** dérivé. Je l'avais déjà retirée en `f36faed` sur la base du bras réel ;
  elle est maintenant réfutée **des deux côtés**.
- **`P3` : désaccord stocké/recalculé du `4h` = 0,00 %** (0 ligne sur 1 775).

## ⛔ ET JE RETIRE L'ALARME QUE J'AI LANCÉE EN `f36faed`

J'y ai écrit que l'asymétrie de provenance du 27/10 était « **présente dans les
TROIS verdicts publiés** ». ⚠️ **Elle l'est formellement, et elle est
IMMATÉRIELLE** :

| | désaccord stocké / recalculé | effet sur l'écart |
|---|---|---|
| `4h` | **0,00 %** | **nul** |
| `1d` | **1,17 %** | −0,105410 → −0,094273, soit **0,011 R** |
| `5min` hors éch. | **24,5 %** | ≈ **0,15 R** *(mesuré le 27/10)* |

⇒ **Les verdicts `1d` et `4h` ne sont pas matériellement contaminés.** Seul le
`5min` hors échantillon l'était, et il avait été corrigé. ⛔ **Mon alarme était
disproportionnée**, et je la retire.

## 🔑 LE RÉSULTAT DE FOND : deux mécanismes DIFFÉRENTS, pas un seul

Je croyais avoir trouvé **un** artefact de prix d'entrée. Il y en a **deux**,
qui n'agissent pas du tout de la même façon :

| | `5min` hors éch. | `1d` |
|---|---|---|
| artefact | **+0,1385** | **−0,207122** |
| sens | la spéc. stockée **FLATTE** le réel | elle le **PÉNALISE** |
| **1ʳᵉ bougie** | **explique 100 % et plus** de l'écart | **0,0 % de résolution — n'explique RIEN** |
| entrées hors bougie | 50,2 % | **79,7 %** |

🔴 **Sur le `1d`, aucune barrière ne se résout à la première bougie** (0,0 % des
setups), donc le mécanisme du `5min` — un fill inatteignable qui franchit
immédiatement l'objectif — **ne s'applique pas**. L'artefact `1d` vient de ce
que le prix d'entrée **déplace tout le carnet** de ≈ 0,95 % de prix (`0,1014 ×
9,326 %`) pour des barrières larges de ±9,3 %, sur **240 heures**.

⇒ **Ma formule `décalage / risk_pct` décrivait le mécanisme du `5min` et pas
celui du `1d`.** C'est pourquoi l'échelle n'était pas monotone : **il n'y avait
pas une échelle, il y avait deux phénomènes.**

## 🔴 ADMISSION : sous une exécution réalisable, le `1d` est POSITIF

`écart = +0,112848`, `t = +4,524`. Et le `4h` reste **indiscernable** sous les
deux spécifications (`t` −0,974 → −0,496).

⇒ **Le `1d` et le `5min` échangent bien leurs places** :

| | spéc. **stockée** | spéc. **réalisable** |
|---|---|---|
| `1d` | **−0,105** (`t` −4,23) | **+0,113** (`t` +4,52) |
| `4h` | −0,022 (`t` −0,97) | −0,011 (`t` −0,50) |
| `5min` hors éch. | **+0,092** (`t` +4,39) | **−0,047** (`t` −2,22) |

### 🔑 La lecture que je retiens, et elle est plus précise que « c'est une convention »

La décision du détecteur a **deux composantes** : **QUAND** entrer, et **À QUEL
NIVEAU**. Les deux spécifications ne séparent pas la même chose :

- la **stockée** juge *quand + à quel niveau*, mais accorde un fill que le
  marché n'a offert que dans **20,3 %** des cas sur le `1d` ;
- la **réalisable** juge *quand* seulement, à un prix toujours obtenable.

⇒ **Sur le `1d`, c'est le NIVEAU qui détruit la performance** (−0,207 R) ; sur
le `5min`, c'est lui qui la **fabriquait** (+0,139 R).

⛔ **Je ne dis donc PAS « tout est convention ».** Je dis : **la spécification
stockée n'est pas exécutable** (79,7 % / 50,2 % de fills hors bougie), donc les
écarts publiés ne mesurent pas ce qu'ils annoncent. Et la seule spécification
exécutable que j'ai testée donne **−0,047 (`5min`)**, **−0,011 (`4h`)** et
**+0,113 (`1d`)**.

## ⛔ CE QUE JE REFUSE DE CONCLURE : le `1d` n'est PAS un signal

`+0,1128 R` pour un coût publié de **0,0021 R** serait exploitable **sur le
papier**. **Je ne le présente pas comme tel**, pour des raisons que je nomme :

- **Le coût de 0,0021 R est faux pour cette population.** Il suppose un spread
  de 0,02 % de prix. La population `1d` compte **36 paires** dont `INJ`, `LDO`,
  `MANA`, `XLK` — des instruments dont le spread réel est **sans commune mesure**
  avec cette hypothèse, et le banc **ne les a jamais mesurés**.
- **`FILL_OUVERTURE` est une AUTRE STRATÉGIE.** La production décide « acheter
  si le prix atteint le niveau X ». Entrer au marché à l'ouverture suivante
  **n'est pas ce qu'elle fait**. Le `+0,113` décrit une stratégie **jamais
  exécutée**.
- **Zéro hors échantillon**, une seule cellule, et des lignes **rattrapées par
  moi** (`resolved_backfill=1`).
- **47,7 % de TIMEOUT** sur 240 h : c'est un pari directionnel à dix jours, pas
  du scalping — hors du périmètre du système.
- ⚠️ **Et le même raisonnement enthousiaste appliqué au `5min` s'est effondré en
  quatre bancs.** Je n'ai aucune raison de croire que celui-ci résistera mieux
  sans être éprouvé de la même façon.

## Les prédictions, honnêtement comptées

| | seuil | mesuré | | aveugle ? |
|---|---|---|---|---|
| `P1` reproduction `ISSUE_STOCKEE` | `< 0,5 %` | **0,0003 %** | ✅ | ⛔ connue |
| `P2` désaccord `1d` | `≤ 3 %` | 1,17 % | ✅ | ⛔ connue |
| **`P3` désaccord `4h`** | `≤ 0,5 %` | **0,00 %** | ✅ | ✅ **AVEUGLE** |
| `P4` `t(FILL)` `1d` | `> 2,00` | +4,524 | ✅ | ⛔ connue |
| **`P5` reproduction du placebo** | `< 2 %` | **0,099 %** | ✅ | ✅ **AVEUGLE** |

⇒ **2 prédictions aveugles sur 2.** Les trois autres étaient divulguées en tête
de la pré-inscription et **je ne les compte pas**.

## 🔬 La suite, par ordre d'importance

1. **Le coût réel des 36 paires du `1d`.** Tant qu'il n'est pas mesuré, le
   `+0,113 R` ne veut rien dire. ⇒ **C'est le premier travail.**
2. **Le `5min` en échantillon** (18 668 lignes) sous les trois bras — la seule
   cellule de la série qui n'a jamais été décomposée.
3. **Un hors échantillon pour le `1d` sous `FILL_OUVERTURE`**, si et seulement
   si le point 1 survit.
4. ⚠️ **Et la question de production** : `entry_price` est un niveau que le
   marché atteint dans **20,3 %** des cas sur le `1d` et **49,8 %** sur le
   `5min`. **Que vaut un vivier d'admission bâti sur des niveaux si rarement
   touchés ?** C'est une question d'exploitation, pas de mesure.

🛑 **Je ne propose pas de réarmer l'IA.** REM-002 reste `DISARMED_MANUALLY`.
