# Décision — réouverture de XAU/USD et WTI/USD sur IC Markets (argent réel)

**Date :** 2026-09-22
**Track :** hors-track
**Numéro :** dec-2
**Statut :** `closed-neutral` — décision actée, résultat inconnu

> ⛔ **Cette entrée SUPERSÈDE `dec-1` du même jour**, qui actait le maintien de la
> rétrogradation. Elle ne la réécrit pas : `dec-1` reste tel quel, avec sa base et
> sa condition de révision. La règle 4 du carnet vaut aussi quand c'est la décision
> qui change, et pas la mesure.

## Ce qui a été fait

| | |
|---|---|
| **Décideur** | Xavier, exploitant |
| **Demande** | Formulée trois fois, la dernière explicitement « maintenant » |
| **Portée** | `XAU/USD` et `WTI/USD`, les deux sens, sur `admin_live` (IC Markets) |

Quatre gestes, dans cet ordre :

1. **Pause du régulateur PnL levée** sur `XAU/USD@admin_live` — elle courait depuis
   le `2026-09-17T08:20:12`. `apply_resume`, motif enregistré.
2. **Huit octrois d'antériorité restaurés** (`bench_legacy_grants`), annulant la
   suppression faite quelques heures plus tôt le même jour.
3. **`XAU/USD sell` promu** `TELEGRAM → AUTO_EXEC` par `manual:xavier`,
   transition **380**.
4. Vérification : les six portes passent pour les deux paires, dans les deux sens.

`WTI/USD` n'a demandé aucun geste — il était déjà `AUTO_EXEC` des deux côtés.

## Ce que les mesures disaient au moment de la décision

Écrit ici parce qu'une décision dont on ne consigne que l'intention n'est pas
consignée :

| Mesure | Date | Valeur |
|---|---|---|
| Contrefactuel de sortie, `XAU/USD@admin_live` | 2026-09-21 | **−0,689 R**, 8 clôtures sur 9 au stop |
| Rétrogradation automatique de l'or | 2026-09-18 | `dd_R = 5,168`, calculé sur de vrais stops |
| `WTI/USD` en argent réel, historique | gate S8 | 116 trades, **6,1 %** de réussite |
| Shadow `V2_WTI_OPTIMAL` | 2026-07-04 | 16 setups, WR 11 %, −205 EUR |
| Programme entier | 2026-08-26 | `DSR = 0,017`, `PBO = 0,579` |

## Le précédent, sans commentaire

`pair_admission_state` porte trois réadmissions manuelles antérieures de l'or en
argent réel. Les trois ont été suivies d'une re-pause automatique, **deux fois le
jour même** :

    2026-06-12  readmission manuelle  ->  re-pause le jour meme, pnl_pct -120,23 %
    2026-07-13  readmission manuelle  ->  re-pause le jour meme, pnl_pct -113,16 %
    2026-09-08  readmission manuelle  ->  retrogradation le 2026-09-18

Celle-ci est la quatrième.

## Ce qui protège encore

La réouverture ne désarme aucun garde-fou. Restent actifs :

- le **plafond de perte journalière**, avec arbitrage Telegram et blocage jusqu'à
  réponse ;
- la **porte de risque par trade** (5 % du capital au lot minimum) ;
- le **régulateur PnL**, qui ré-évaluera et pourra re-pauser sur le seuil habituel ;
- le **blackout news**, fonctionnel depuis le 2026-09-20 — une protection que les
  trois réadmissions précédentes n'avaient pas ;
- la **fermeture du vendredi**, élargie à l'énergie depuis le 2026-09-04.

⚠️ Le banc d'essai, lui, est armé mais **ne garde plus ces deux paires** : les
octrois d'antériorité restaurés le couvrent. Il reste effectif pour les paires
vraiment nouvelles.

## Ce qui dira tôt si la décision était bonne

Deux signaux, mesurables sans attendre un verdict de banc :

1. **Le contrefactuel de sortie** sur la fenêtre qui commence. Si
   `r_contrefactuel_moyen` reste négatif sur `XAU/USD@admin_live`, les niveaux
   perdent toujours et la réouverture ne fait que payer pour le vérifier.
   `bash scripts/contrefactuel-sortie.sh`.
2. **Le régulateur lui-même.** S'il re-pause dans les jours qui viennent, ce sera
   la quatrième fois sur le même motif — et le fait que ce soit la quatrième est
   l'information, pas la pause.

## Ce que la décision n'a pas changé

Les essais `live-or-2026-09-22` et `live-wti-2026-09-22` restent ouverts et
accumulent. Ils portent sur `admin_legacy` **et** `admin_live` : leurs clôtures
compteront désormais des deux côtés. Leur verdict tombera au 30ᵉ, contre le plafond
du hasard à `N = 1 237`.

Ils ne gardent plus aucune porte — mais ils restent la seule mesure hors-échantillon
que le projet ait jamais mise en place, et la réouverture les alimente au lieu de
les vider.

## Artefacts

- Carnet : `2026-09-22-decision-xauusd-admin-live.md` (`dec-1`, supersédé)
- Rapport : `docs/audit-externe-2026-09-16.md` §4.6.5 à §4.6.8, constats R-11 à R-18
- Diagnostic : `scripts/diagnostic_or_wti_live.py`
