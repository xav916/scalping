# Protocole de mesure — le COUT REEL de l'or, au tick

**Figé le 2026-10-30, AVANT d'avoir regardé une seule valeur de spread.**

## Pourquoi ce document n'a pas de bloc `CRITERE-MACHINE`

Ce n'est **pas un banc**. Il n'y a ni hypothèse, ni admission, ni rejet : on
mesure un **paramètre** du système. Le bloc machine d'`or-preinscription`
existe pour empêcher d'admettre une hypothèse sur un critère choisi après
coup ; ici le risque est différent et plus simple :

⛔ **choisir la statistique après avoir vu les nombres** — prendre la médiane
si elle arrange, la moyenne sinon.

Ce protocole ferme ce risque-là en figeant d'avance la fenêtre, les
statistiques **toutes** rapportées, et les exclusions.

⚠️ La question « ce coût change-t-il un verdict publié ? » **est** une
hypothèse. Elle fera l'objet d'une pré-inscription séparée, avec bloc
machine, et ne doit pas être traitée ici.

## Le défaut qu'on solde

`scripts/banc_esperance_horizon.py:240` applique

```python
SPREAD_PCT = 0.0002          # 0,02 % du prix, UNE constante
```

à plat dans `pnl_pct()`, **pour toute paire et tout instant**. Les verdicts
d'horizon (`1d` rejeté, `4h` indiscernable, `5min` retiré) en dépendent, ainsi
que `banc_placebo_structure.py` qui l'importe.

🔑 Une constante unique est fausse **dans les deux sens à la fois** : trop dure
là où le spread est serré, trop douce là où il s'écarte. Elle ne peut donc pas
être « prudente ».

## Source — persistée, donc reproductible

| | |
|---|---|
| magasin | `/app/data/ticks_courtier.db`, table `ticks` |
| champs | `pair, ts_utc, ms, bid, ask` — **bid/ask réels du courtier** |
| volume | 11 987 039 ticks |
| couverture | `XAU/USD` seul, 2026-09-21 → 2026-10-30 |

✅ Les ticks portent `bid` et `ask`, donc **pas** la troncature à l'entier de
`spread_pts` qui obligeait `mesurer_spread_par_instrument.py` à borner le
forex à « 1 point » faute de résolution.

⛔ **Aucune donnée bid/ask persistée pour le forex, la crypto ou l'énergie.**
Ce protocole ne mesure donc QUE l'or, et toute valeur par classe pour les
autres restera une **hypothèse déclarée**, jamais une mesure. C'est une limite
de données, pas un choix.

⚖️ Acceptable parce que l'or est la **seule voie en argent réel**
(`LIVE_WHITELIST_PAIRS == {XAU/USD}`).

## Définition du coût

```
spread_relatif(tick) = (ask - bid) / ((ask + bid) / 2)
```

Payé **une fois par aller-retour** (on achète à l'offre, on vend à la
demande) : il ne doit pas être compté deux fois. Sur ces comptes la
commission est nulle et le swap négligeable (mesure du 2026-08-11, 191
trades) ⇒ **le spread EST le coût d'exécution**.

## Statistiques rapportées — TOUTES, décidées maintenant

1. médiane, moyenne, **p75**, **p95**, p99 du spread relatif, global ;
2. les mêmes **par heure UTC** (0-23) ;
3. la part de ticks exclus, par motif ;
4. le même jeu en **$ absolus** et en **points**, pour comparer aux fiches.

⛔ Aucune de ces statistiques ne sera retirée du rapport selon sa valeur.

## Exclusions, figées d'avance

| exclusion | motif |
|---|---|
| `ask <= bid` | cotation croisée ou nulle : impossible, donc instrument faux |
| `bid <= 0` ou `ask <= 0` | idem |
| spread relatif > 1 % | aberration de collecte (l'or ne cote pas à 1 % d'écart) |

Chaque exclusion est **comptée et publiée**. Un volume d'exclusion inattendu
est un signal sur l'instrument, pas un détail de ménage.

## Comment ce coût entrera dans les bancs

🔑 **Le vrai correctif n'est pas une meilleure constante : c'est de supprimer
la constante.** Le banc simule un trade à un instant donné ; son coût est le
spread **à cet instant**.

```
cout_spread(pair, ts) -> fraction du prix
   1. tick le plus proche de `ts` dans le magasin, tolérance ±60 s
   2. sinon : valeur par classe DECLAREE, et marquée « hypothèse »
   3. jamais de silence : tout trade sans tick dans la tolérance est
      COMPTE et le compte est publié
```

⛔ **Interdit** : remplacer un tick manquant par la valeur par défaut sans le
dire. C'est la faute qui a produit les faux-sûrs du 28/10 et du 30/10
(« absent » traité comme « vide »).

## Ce que ce protocole NE fait pas

- il ne juge aucun horizon ;
- il ne touche à aucun réglage de production ;
- il ne réarme rien (REM-002 reste `DISARMED_MANUALLY`).
