# Décision — XAU/USD reste rétrogradé sur `admin_live`

**Date début :** 2026-09-21 (investigation)
**Date fin :** 2026-09-22 (décision)
**Track :** hors-track
**Numéro d'expérience :** dec-1
**Statut :** `closed-negative`

---

## ⛔ Lire d'abord : cette entrée ne respecte PAS la règle 2

Le carnet exige des critères go/no-go **fixés avant de regarder le résultat**. Ici,
la mesure a été lancée pour élucider un incident — une absence de trade sur l'or le
2026-09-21 — et l'hypothèse ci-dessous a été **formulée après**.

🔑 Ce que cela autorise, et ce que cela interdit. Le contrefactuel compare les
**mêmes trades aux mêmes prix** : le biais de sélection est traité par construction,
donc le chiffre est utilisable comme **diagnostic**. Il n'est pas utilisable comme
verdict sur le comportement futur des niveaux, et aucune promotion ne doit s'y
appuyer. Pour cela il faudrait un essai déclaré au banc, avant mesure.

## Hypothèse

> Les niveaux SL/TP générés pour `XAU/USD` sur `admin_live` ont une espérance
> positive : laissés à eux-mêmes, les trades sortis manuellement auraient rendu un
> R moyen **≥ 0**.

## Motivation / contexte

Le 2026-09-18 à 03:00 UTC, `promotion_engine` a rétrogradé `XAU/USD sell` en
`TELEGRAM` sur `admin_live` — `auto:demotion:dd_above_5.0R_7d:5.168`. Le côté achat
était déjà en pause régulateur. L'or ne tradait donc plus en argent réel, ce qu'une
absence de trade le 21/09 a rendu visible.

Trois réadmissions manuelles antérieures (2026-06-12, 2026-07-13, 2026-09-08) ont
toutes été suivies d'une re-pause, **deux fois le jour même**, à des PnL de −113 %,
−120 % et −125 % (`pair_admission_state`). Aucune n'avait été précédée d'une mesure.

## Données

- **Source :** `personal_trades` + `contrefactuels_sortie` (base de production)
- **Période :** 2026-09-11 → 2026-09-18
- **Instrument :** `XAU/USD`, destination `admin_live`
- **Volume :** 9 clôtures non automatiques résolues

## Protocole

1. `contrefactuel_sortie.balayer()` — enregistre les clôtures hors `{SL, TP1, TP2}`.
2. `resoudre()` — rejeu **bougie par bougie** depuis l'instant de clôture ; `expire`
   et `indetermine` reçoivent `r_contrefactuel = None` et sont exclus du bilan.
3. Comparaison du R obtenu au R contrefactuel, sur les **mêmes** trades.
4. Contrôles de validité : filtre placebo (< 0,1 % du prix) sur les dépassements de
   stop ; vérification que `promotion_engine` applique ce même filtre dans `dd_R`.

## Résultats

```
XAU/USD · admin_live · depuis 2026-09-11        n = 9
  contrefactuel : 8 clôtures au SL, 1 au TP
  R obtenu       : +0,175   (total +1,578)
  R contrefactuel: -0,689   (total -6,200)
  écart          : +0,864 R par trade
```

Agrégats de contrôle, toutes paires, depuis 2026-08-25 :

| Destination | n | R obtenu | R contrefactuel | Écart |
|---|---:|---:|---:|---:|
| `admin_live` | 55 | +0,330 | −0,287 | +0,617 |
| `admin_legacy` | 23 | +0,513 | −0,270 | +0,782 |

Contrôles de validité :

- **`dd_R = 5,168` est sain.** Les stops de la fenêtre valaient 0,22 % à 0,63 % du
  prix — aucun placebo. `promotion_engine` écarte déjà les stops < 0,1 %
  (`if dist / abs(e) < 0.001: continue`), vérifié dans le code.
- **Aucun biais d'exécution.** Dépassement moyen des stops sur `admin_live`, hors
  placebos : **−0,080 R** sur 159 clôtures `SL`. Les stops sont honorés.

## Verdict

> Hypothèse **INFIRMÉE** : le R contrefactuel vaut **−0,689** sur n=9, avec 8
> clôtures sur 9 au stop. **Les niveaux perdent.** Les sorties discrétionnaires
> apportent +0,864 R par trade, et sont la seule raison pour laquelle la fenêtre
> n'est pas franchement négative.

## Conséquences actées

**Décision (Xavier, 2026-09-22) : maintenir la rétrogradation. Ne pas réadmettre
`XAU/USD` en `AUTO_EXEC` sur `admin_live`.**

- **Portée** : `XAU/USD` sell et buy sur `admin_live` uniquement. `admin_legacy` et
  `admin_kraken` inchangés.
- **Condition de révision — une mesure, jamais un délai** : réadmission envisagée
  seulement si un contrefactuel sur une fenêtre **postérieure** rend un
  `r_contrefactuel_moyen ≥ 0`. Le cool-off `PAC_PAUSE_COOLOFF_DAYS` reste nécessaire
  et jamais suffisant.
- **Ce que la décision coûte, et il faut l'écrire** : `XAU/USD` est le seul
  instrument à edge volumique apparent du portefeuille (223 trades, 38,4 %,
  +432,54 USD au gate S8) et porte 87,6 % du résultat. S'en priver en argent réel
  réduit l'activité à presque rien. C'est assumé — un instrument dont les niveaux
  rendent −0,689 R ne devient pas rentable parce qu'il est le moins mauvais.

🔑 **Ce qui distingue cette décision des trois précédentes** : elle consiste à
suivre le régulateur au lieu de le contourner, et c'est la première fois qu'une
mesure indépendante dit la même chose que lui.

**Pour le code prod** : aucun déploiement. Rien n'a été modifié.

**Pour les autres tracks** : le constat porte sur les **niveaux**, pas sur la
sélection des setups. Il converge avec `DSR = 0,017`, `PBO = 0,579` et le contrôle
aléatoire à +0,004 R — par une troisième voie, et sur un objet différent.

## Suite du 2026-09-22 — la porte du banc rendue effective

Après armement du banc (`RESEARCH_BENCH_GATE_ENABLED=true`), le diagnostic a
montré que l'or et le WTI passaient quand même : `porte 6 : PASSERAIT — couvert
par la clause d'antériorité`. Les octrois posés le 2026-08-25 à l'installation du
banc les exemptaient **sans aucune borne** (`direction` et `destination` à `NULL`,
et `_couvre(None, …)` rend `True` sur toute demande, y compris `user:N`).

⛔ **Huit octrois supprimés le 2026-09-22**, quatre par paire. La porte refuse
désormais les deux sur `admin_live` et `admin_kraken`.

### Restauration, si la décision est révisée

```sql
INSERT INTO bench_legacy_grants (pair, direction, destination, granted_at, reason) VALUES
 ('WTI/USD', NULL,   NULL,         '2026-08-25T22:24:00.307430+00:00', 'restaure'),
 ('WTI/USD', 'buy',  NULL,         '2026-08-25T22:24:00.312469+00:00', 'restaure'),
 ('WTI/USD', 'buy',  'admin_live', '2026-08-25T22:24:00.317572+00:00', 'restaure'),
 ('WTI/USD', 'sell', NULL,         '2026-08-25T22:24:00.322856+00:00', 'restaure'),
 ('XAU/USD', NULL,   NULL,         '2026-08-25T22:24:00.333641+00:00', 'restaure'),
 ('XAU/USD', 'buy',  NULL,         '2026-08-25T22:24:00.340286+00:00', 'restaure'),
 ('XAU/USD', 'buy',  'admin_live', '2026-08-25T22:24:00.345405+00:00', 'restaure'),
 ('XAU/USD', 'sell', 'admin_live', '2026-08-25T22:24:00.350399+00:00', 'restaure');
```

⚠️ **Ce que la suppression ne fait PAS.** `gate_promotion` n'est consulté que dans
`set_state`, donc au moment d'une **transition**. `WTI/USD` étant déjà `AUTO_EXEC`
sur `admin_live`, il continue de trader en argent réel : seules les promotions
**futures** sont désormais gardées. Fermer WTI serait une autre décision, non prise
à ce jour.

**Les 25 autres paires exemptées sans borne** (dont `XAG/USD`) conservent leurs
octrois. Traitées séparément, à froid.

## Artefacts

- Scripts : `scripts/contrefactuel-sortie.sh`, `backend/services/contrefactuel_sortie.py`
- Essai de banc `trail-en-R-or-2026-09-21` : **jamais déclaré**. Rédigé le
  2026-09-21 sur une hypothèse qui nommait le stop suiveur — lequel est désarmé
  depuis le 2026-08-11 — l'appel a échoué sur un `ModuleNotFoundError` non vu, et la
  vérification du 2026-09-22 rend « l'essai n'existe pas ». **`N` n'a donc jamais été
  gonflé par cette hypothèse** (1 226 au dépouillement, 1 233 avant les deux essais
  de réhabilitation). Le script subsiste dans le dépôt pour l'histoire :
  `scripts/declarer_essai_trail_en_R.py`.
- Essais de réhabilitation déclarés le 2026-09-22 : `rehabilitation-or-2026-09-22`
  (empreinte `4cf95985…`) et `rehabilitation-wti-2026-09-22` (`f97397fd…`).
  **N = 1 235.**
- Rapport d'audit : `docs/audit-externe-2026-09-16.md` §4.6.5 à §4.6.8
- Commits : `1598c53`, `519c991`, `f36e111`, `dd69c46`
