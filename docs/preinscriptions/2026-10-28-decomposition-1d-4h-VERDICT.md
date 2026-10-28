# Verdict — banc ARRÊTÉ par sa propre porte, et mon échelle est RÉFUTÉE

**Pré-inscription** : `b9cf462` → `6f5ad03` · **Banc** : `6f5ad03`
**`or-verdict` : NE PAS PUBLIER** — `ecart_reproduction_max_pct = 17,3848`, attendu `< 2,0`
**0 prédiction tenue sur les 3 qui comptent.**

## Le résultat

| cellule | `n` | `risk%` | réel STOCKE | réel FILL | **ARTEFACT** | écart FILL | `t` fill | repro |
|---|---|---|---|---|---|---|---|---|
| **`4h`** | 1 775 | 0,3722 | −0,266409 | −0,255699 | **−0,010710** | −0,011130 | −0,496 | **0,001 %** ✅ |
| **`1d`** | 1 362 | 9,3260 | **−0,052925** | **+0,154197** | **−0,207122** | **+0,112848** | **+4,524** | **17,385 %** 🔴 |

Référence `1d` : **−0,064062** · référence `4h` : **−0,266410**.

## ✅ LE GARDE-FOU A FONCTIONNÉ, et c'est le premier acquis

Le banc **s'est arrêté de lui-même** sur sa clause de validité, avant toute
interprétation. ⇒ **La cellule `1d` est INVALIDE** par ma propre porte
pré-inscrite, et je ne conclurai rien dessus.

## 🔴 POURQUOI LE `1d` NE REPRODUIT PAS — et c'est un défaut de son VERDICT

Mesuré, pas supposé :

```
fenetre de 240 h DEPASSANT la derniere bougie chargee : 216 / 1362 = 15,9 %
issues : TIMEOUT 47,7 %   SL 36,3 %   TP1 16,0 %
derive de l esperance : -0,064062 -> -0,052925, soit +0,011137 R en UN JOUR
   si elle vient des 216 setups au bord : +0,0702 R chacun
   = 0,65 % de prix a risk_pct 9,326 %  -> une journee de marche. Coherent.
```

🔑 **Le critère `1d` (`d3dcfe`… `2026-10-27-esperance-1d.md`) n'a pas de
`fin_chargement`.** Avec une fenêtre de **240 h** et **47,7 % de TIMEOUT** dont
le prix de sortie est **la dernière bougie disponible**, son espérance **dérive
avec la frontière de données** : **17,4 % en un jour**.

⇒ 🔴 **L'espérance publiée du `1d` n'a jamais été reproductible.** Ce n'est pas
une erreur de ce banc-ci : c'est une **limite du verdict `1d`** que personne
n'avait vue. ⚠️ Et c'est **exactement** le défaut que la borne de chargement a
été introduite pour corriger — **après** le `1d`, pour le `4h`, qui lui
reproduit à **0,001 %**.

## ⛔ MON ÉCHELLE MONOTONE EST RÉFUTÉE

```
artefact :  5min +0,1385      4h -0,0107      1d -0,2071
```

🔴 **Ni monotone, ni de signe constant.** La spécification stockée **favorise**
le bras réel sur le `5min` (+0,139) et le **défavorise** sur le `1d` (−0,207).
⇒ **L'histoire que j'ai annoncée en `644fded` — « l'artefact grandit quand le
stop se resserre » — est fausse.**

Et le décalage lui-même, mesuré :

```
decalage/risque median :  5min 0,341      4h 0,191      1d 0,101
```

⇒ L'**ordre** `1d < 4h < 5min` est bien respecté, mais **`P4` échoue** : j'avais
prédit `< 0,05` pour le `1d` et mesuré **0,1014**, soit **14 fois** mon
estimation annoncée de `≈ 0,007`.

🔑 **Pourquoi mon estimation était fausse** : j'avais pris le décalage du `5min`
(≈ 0,067 % du prix) et l'avais divisé par le `risk_pct` du `1d`. Mais l'entrée
d'un setup `1d` est calculée sur une barre **journalière** et comparée à la
première bougie **5 min** suivante : le décalage **absolu** est bien plus grand.
⇒ **Un substitut transposé d'un horizon à l'autre n'est pas une mesure.**

## Les prédictions, honnêtement

| | seuil | mesuré | | compté ? |
|---|---|---|---|---|
| `P1` artefact `1d` | `< 0,02` | −0,2071 | ✅ | ⛔ **non** — passe **à l'envers** |
| `P2` artefact `4h` | `< 0,1385` | −0,0107 | ✅ | ⛔ **non** — passe **à l'envers** |
| **`P3` artefact `4h`** | **`> 0`** | **−0,0107** | ⛔ **ÉCHEC** | ✅ |
| **`P4` décalage/risque `1d`** | **`< 0,05`** | **0,1014** | ⛔ **ÉCHEC** | ✅ |
| **`P5` artefact `1d`** | **`> −0,02`** | **−0,2071** | ⛔ **ÉCHEC** | ✅ |

⛔ **`P1` et `P2` sont des maxima unilatéraux** : elles « passent » parce que les
artefacts sont sortis **négatifs**, c'est-à-dire pour la raison **inverse** de
celle que j'avais en tête. **Je ne les compte pas.** ⇒ **0 sur 3.**

🔑 **La leçon de forme** : un seuil unilatéral sur une quantité dont je crois
connaître le signe est un **piège** — il ne distingue pas « petit comme prévu »
de « grand dans l'autre sens ». Il fallait **encadrer des deux côtés**, comme je
l'avais fait pour `P1`/`P5` du `1d` et **pas** pour le `4h`.

## ✅ CE QUE LA CELLULE `4h` ÉTABLIT, et c'est le seul résultat solide

Elle reproduit à **0,001 %** (réel) et **1,071 %** (écart, la dérive du placebo
sans borne). Donc :

- **artefact = −0,010710** — **minuscule**, et **négatif** ;
- écart FILL **−0,011130**, `t` **−0,496** ⇒ le `4h` **reste indiscernable du
  hasard** sous **les deux** spécifications ;
- première bougie : réel STOCKE `4,6 / 0,8 %` → **−0,0314 R** ; réel FILL
  `0,2 / 0,0 %` → **−0,0023 R** ; placebo `0,2 / 0,1 %` → **−0,0012 R**.

⇒ **Sur le `4h`, la spécification d'exécution ne change rien à la conclusion.**
⚠️ Je n'ai **pas** calculé l'erreur-type de l'artefact : je le qualifie de
« minuscule » par sa taille devant les écarts de la série, pas par un test.

## 🔴 LE FAIT LE PLUS LOURD — et je ne le conclus PAS

Sur la cellule **invalide** : artefact `1d` = **−0,2071**, écart FILL
**+0,112848**, `t` **+4,524**. Le `1d` passe donc de **−0,105 / t −4,23**
(stocké) à **+0,113 / t +4,52** (fill).

⇒ **Sous la spécification réalisable, le `1d` et le `5min` ÉCHANGENT leurs
places.** Le `5min` passe de **+0,092** à **−0,047** ; le `1d` de **−0,105** à
**+0,113**.

⛔ **Je ne le conclus pas** : la cellule n'a pas passé sa porte de reproduction,
et une partie de ce `+0,154` de réel FILL vient peut-être de la même dérive de
frontière qui a fait échouer la reproduction.

⚠️ **Mais si cela se confirme, c'est dévastateur pour toute la série** : le
**signe** de l'« écart » dépendrait **entièrement** de la spécification
d'exécution ⇒ **aucune des deux ne démontre quoi que ce soit**, et les trois
verdicts d'espérance mesureraient un choix de convention, pas une information.

## 🔬 La suite, et elle est précise

1. **Un critère `1d` NEUF avec `fin_chargement`**, pour re-mesurer le `1d`
   proprement. C'est la **seule** voie pour trancher le point ci-dessus, et
   c'est la première chose à faire.
2. **Relire le verdict `1d` publié** (`0b8106b`) à la lumière de sa
   non-reproductibilité : **47,7 % de TIMEOUT** et **15,9 %** de fenêtres au
   bord de la donnée.
3. **Le `5min` en échantillon** (18 668 lignes), toujours non décomposé — c'est
   lui qui contredit le classement par `1/risk`.
4. ⚠️ **Et poser `fin_chargement` dans TOUT critère à fenêtre longue** : la
   borne existe depuis le `4h`, mais rien ne l'exige.

🛑 **Je ne propose pas de réarmer l'IA.** REM-002 reste `DISARMED_MANUALLY`.
