# ⛔ CORRECTION du verdict `09c31e2` — le coût EST mesurable, et mon diagnostic était trop large

**Écrit le 2026-10-28, après `09c31e2`.** Le verdict corrigé **reste au dépôt**.
⚠️ **C'est la DEUXIÈME fois aujourd'hui** que je publie un diagnostic trop
large après l'échec de deux sources, sans avoir vérifié la troisième. Le motif
est nommé en bas.

## Ce que j'ai écrit, et qui est trop large

> « Le coût réel des 36 paires est **INMESURABLE** […] **le système ne sait pas
> mesurer ce que ses trades coûtent** […] chaque `cout_R` dérive d'une
> constante codée en dur **que rien ne vérifie** et **qui ne peut pas l'être**. »

🔴 **Faux sur le point central.** Le coût **est** mesuré, et il **est**
récupérable.

## 🔑 Ce que j'avais manqué : `slippage_pips` est INVERSIBLE

J'avais conclu après deux sources mortes (`spread_cost` vide, `fill_price`
recopié) **sans examiner la troisième**. Or `slippage_pips` est calculé par
`mt5_sync.py` depuis `entry_requested` contre le fill, et stocké en **pips** via
`_pip_size(pair)` — une fonction **déterministe** que je peux **inverser** :

```python
def _pip_size(pair):                      # mt5_sync.py:143
    if base in {"XAU","XAG","XPT","XPD"}: return 0.01
    if quote == "JPY":                    return 0.01
    return 0.0001          # <-- TOUT LE RESTE, dont la CRYPTO et l ENERGIE
```

⇒ `cout_%_du_prix = |slippage_pips| × pip_size(paire) / prix × 100`

## Le coût réel, mesuré sur 544 trades automatiques depuis le 2026-08-06

| paire | `n` | médiane | p90 | vs **0,02 %** supposé |
|---|---|---|---|---|
| `WTI/USD` | 2 | 0,2322 % | 0,0219 % | **×11,6** |
| **`BTC/USD`** | **24** | **0,1298 %** | **0,3551 %** | **×6,5** |
| `XAG/USD` | 48 | 0,0599 % | 0,2246 % | ×3,0 |
| `XAU/USD` | **352** | 0,0251 % | 0,0980 % | ×1,3 |
| `USD/CHF` | 16 | 0,0161 % | | ×0,8 |
| `AUD/USD` · `EUR/JPY` | 17 · 8 | 0,0111 % · 0,0110 % | | ×0,6 · ×0,5 |
| `GBP/JPY` · `USD/JPY` | 14 · 27 | 0,0098 % · 0,0090 % | | ×0,5 · ×0,4 |
| `EUR/USD` · `GBP/USD` · `USD/CAD` | 2 · 11 · 21 | 0,0069 % · 0,0067 % · 0,0051 % | | ×0,3 |
| `EUR/GBP` | 2 | 0,0006 % | | ×0,0 |
| **TOUTES** | **544** | **0,0229 %** | | **×1,1** |

## Ce qui tombe, et ce qui tient

**TOMBE :**
- ⛔ « le coût est inmesurable » ⇒ **il est mesuré et récupérable** ;
- ⛔ « le système ne sait pas mesurer ce que ses trades coûtent » ⇒ **il le
  mesure**, et **correctement pour le forex et les métaux** ;
- ⛔ « `SPREAD_PCT = 0,0002` est **certainement faux** » ⇒ 🔑 **il est juste à
  10 % près GLOBALEMENT** (médiane 0,0229 % contre 0,0200 %). Mon
  « certainement » était une **affirmation sans mesure**.

**TIENT, et se précise :**
- ✅ `spread_cost` **jamais peuplée** (0/1 784) et `fill_price` **toujours égal à
  `entry_price`** (0 % de différence sur 569 trades auto post-correctif) — deux
  champs réellement inertes. ⚠️ Mais `slippage_pips` **ne passe pas par eux** :
  il compare `entry_requested` au fill, d'où son contenu réel.
- 🔴 **L'échelle est fausse par CLASSE**, dans les deux sens : le forex coûte
  **moins** que supposé (×0,3 à ×0,8), la crypto et l'énergie **beaucoup plus**
  (×6,5 à ×11,6). ⇒ **La constante unique est juste en moyenne et fausse
  partout en particulier.**
- 🔴 **`_pip_size` n'a aucun cas crypto ni énergie** et retombe sur `0,0001` :
  d'où `BTC/USD` à **1 113 350 pips** de médiane. Défaut réel, cause lue dans le
  code.
- 🔴 **Et la sonde `slippage_instrumentation_check` rend `OK, alerte: false`
  sur une moyenne de −19 082,80 pips.** Elle vérifie que les colonnes sont
  **remplies**, jamais que leurs valeurs ont un **sens**. ⛔ Et son `run()`
  **n'est appelé par rien** — le silence qu'elle devait empêcher s'est
  réinstallé sous une autre forme.

## ✅ Et la réponse à la question posée

**Pour les 36 paires du `1d`** : une seule, **`BTC/USD`**, a des exécutions
réelles (24 trades). Son coût mesuré vaut **0,1298 % du prix**, soit, au
`risk_pct` médian du `1d` (14,64 %) :

```
cout mesure (BTC/USD) : 0,0089 R     contre 0,0021 R publie  =>  x4,2
ecart FILL du 1d      : +0,1128 R
```

⇒ ✅ **Ma prédiction `P4` TIENT** : le coût, même multiplié par 4, **ne mange
pas l'écart**. Il faudrait **×12,7** pour l'annuler.

⛔ **Et je n'extrapole PAS** à `INJ`, `ETHFI`, `LDO` ou aux 7 ETF : `BTC/USD`
est **le plus liquide du lot**, donc son coût est un **plancher** pour les
autres. Transposer serait exactement la faute du « substitut transposé » du
verdict `9d955dc`.

⇒ 🔑 **Le `+0,113 R` du `1d` n'est donc PAS condamné par le coût.** Il reste non
établi pour les raisons déjà publiées : **56,7 %** d'univers hors
`WATCHED_PAIRS`, `FILL_OUVERTURE` qui est **une autre stratégie**, **zéro hors
échantillon**, **47,7 % de TIMEOUT sur 240 h**.

## 🔑 LE MOTIF, et c'est la deuxième fois aujourd'hui

| | j'ai publié | la vérité |
|---|---|---|
| `9d955dc` | « l'espérance du `1d` n'est pas reproductible, dérive de frontière » | une faute de **provenance**, et elle reproduit à **0,000 %** |
| `09c31e2` | « le coût est **inmesurable** » | il est **mesurable**, par une **troisième** source que je n'avais pas ouverte |

⇒ ⛔ **Je conclus « impossible » trop vite dès que deux sources échouent.**
Dans les deux cas, la vérification coûtait **une requête**. Et dans les deux
cas, le mot que j'ai choisi (« pas reproductible », « inmesurable ») était
**plus large que ce que j'avais testé**.

🔑 **La règle** : avant d'écrire « impossible » ou « inmesurable », **énumérer
les sources** et dire laquelle a été ouverte. Deux échecs ne font pas une
preuve d'absence.

## 🔬 La suite, resserrée par ce diagnostic

1. **Ajouter la crypto et l'énergie à `_pip_size`** — ou mieux, **enregistrer le
   glissement en % du prix**, unité qui ne dépend d'aucune convention et qui
   est ce dont tous les bancs ont besoin. ⚠️ `_pip_size` est **dupliquée** dans
   `mt5_sync.py` et `cockpit_service.py` : les deux, ou aucune.
2. **Rendre la sonde sensible à la PLAUSIBILITÉ**, pas seulement à la présence :
   un glissement médian au-delà de ~1 % du prix doit alerter.
3. **Câbler `run()`** — il n'est appelé par rien.
4. ⛔ **Remplacer `SPREAD_PCT` unique par un coût PAR CLASSE** dans les bancs,
   avec les valeurs mesurées ci-dessus, et le dire dans chaque verdict.
