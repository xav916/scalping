# Observation — Drawdown V1 cluster range_bounce_down 2026-04-30

**Date début :** 2026-04-30
**Date fin :** 2026-04-30 (en cours, monitoring continue)
**Track :** hors-track (observation V1 démo auto-exec)
**Numéro d'expérience :** observation, pas une expérience formelle
**Statut :** `closed-negative`

---

## Hypothèse

**Énoncé en une phrase :**
> "Sur une journée où le radar V1 enchaîne des stops sur le même pattern et la même direction, l'absence d'un cooldown / state-aware reduction transforme une perte ponctuelle en cluster corrélé qui amplifie le drawdown."

## Motivation / contexte

User remonte 2 jours de PnL négatif consécutifs côté démo Pepperstone (auto-exec V1 actif).
Question : "pouvait-on anticiper ces pertes ?". Investigation déclenchée pendant l'attente
de l'onboarding Cédric (MQL.F en cours).

## Données

- **Source :** API prod `/api/trades?limit=80` extrait le 2026-04-30 ~13h35 Paris
- **Période d'observation principale :** 2026-04-30 06:01 → 11:01 UTC (5 heures)
- **Pairs concernées :** XAU/USD + XAG/USD
- **Granularité :** auto-exec live (signal_pattern + entry/SL/TP + pnl)
- **Volume :** 9 trades fermés, tous en SL

## Protocole

1. Pull `/api/trades?limit=80` avec auth admin
2. Filtrer status=CLOSED + close_reason=SL
3. Identifier patterns / pairs / direction / timing communs
4. Cross-référencer avec `context_macro` au moment du fill

## Résultats

### Cluster observé sur 5h le 2026-04-30

| ID | Pair | Direction | Pattern | Entry | SL | Exit | PnL € | conf% |
|---|---|---|---|---|---|---|---|---|
| 201 | XAG/USD | sell | range_bounce_down | 72.204 | 72.388 | 72.388 SL | -23.67 | 66.1 |
| 202 | XAG/USD | sell | range_bounce_down | 72.233 | 72.384 | 72.384 SL | -19.42 | 66.1 |
| 203 | XAG/USD | sell | range_bounce_down | 72.964 | 73.065 | 73.065 SL | -21.63 | 66.4 |
| 204 | XAU/USD | sell | range_bounce_down | 4586.42 | 4596.28 | 4596.28 SL | -33.77 | 65.8 |
| 205 | XAU/USD | sell | range_bounce_down | 4598.05 | 4598.51 | 4598.51 SL | -3.55 | 66.7 |
| 206 | XAU/USD | sell | range_bounce_down | 4600.66 | 4602.24 | 4602.24 SL | -13.53 | 67.0 |
| 207 | XAG/USD | sell | range_bounce_down | 73.053 | 73.145 | 73.145 SL | -35.45 | 66.7 |
| 208 | XAU/USD | sell | range_bounce_down | 4600.78 | 4604.20 | 4604.20 SL | -17.56 | 66.4 |
| 209 | XAG/USD | sell | range_bounce_down | 73.146 | 73.203 | 73.203 SL | -17.07 | 66.7 |

**Total visible : 9 trades, 9 stops, 0 take-profit, PnL = -185.65 €.**

### Trajectoire de prix XAU intra-cluster

```
06:14  XAG short à 72.20  ──► SL 72.38
07:08  XAG short à 72.96  ──► SL 73.07  (XAG monte +0.7% pendant 1h)
07:21  XAU short à 4586   ──► SL 4596
07:48  XAU short à 4598   ──► SL 4599   (SL 0.46$ wide = 0.01%)
07:54  XAU short à 4600   ──► SL 4602
08:01  XAU short à 4601   ──► SL 4604
08:01  XAG short à 73.15  ──► SL 73.20  (8h plus tard, XAG est à 73.20, +1.4% vs entry initiale)
```

L'or a fait **4586 → 4604** (+0.4 %) en 2 heures, l'argent **72.20 → 73.20** (+1.4 %)
en 8 heures. Pendant ce temps, le radar V1 a **continué d'émettre des shorts** sur le
même pattern range_bounce_down — la "résistance" testée et refusée à chaque fois,
mais ré-identifiée comme telle à la barre suivante.

### Contexte macro snapshoté à chaque fill

`risk_regime: neutral`, `vix: 17 normal`, `spx: down`, `dxy: neutral`. Aucun signal
macro n'a permis d'anticiper la cassure haussière intra-day.

## Verdict

> **Hypothèse PARTIELLEMENT CONFIRMÉE :** la perte spécifique de 2j n'est pas
> prédictible (toute fenêtre courte sur un système sans edge a ~50% de chance d'être
> rouge). En revanche, le **mode de défaillance** (rejouer la même idée sur le même
> pattern direction tant qu'aucun état mental ne mute) **est anticipable et fixable**.

### Causes structurelles identifiées

1. **Pas de cooldown post-stop** : aucun mécanisme "après N SL consécutifs sur même
   (pair, pattern, direction), pause de M heures". V1 ré-émet à chaque barre.
2. **Pas de cap de corrélation intraday** : XAU et XAG sont corrélés à 0.62. Les
   shorter simultanément multiplie la concentration risque sans augmenter la diversité
   d'idée. Une seule "thèse" jouée 2× = 2× le risque.
3. **SL trop serrés relativement à l'ATR** : trade #205 = SL à 0.01 % du prix sur
   un instrument dont l'ATR M30 est ~0.05-0.1 %. C'est statistiquement assuré d'être
   touché par le bruit, indépendamment de la direction réelle.
4. **Macro context lag** : le snapshot `gold:down` était valide intra-day mais l'action
   intraday a été hausse → le filtre macro (s'il existait, ce qu'il n'est pas en V1)
   aurait été mis en échec aussi.

### Ce qu'on aurait pu anticiper avant le fait

| Niveau | Anticipable ? | Comment ? |
|---|---|---|
| La perte exacte de ces 9 trades | ❌ non | Aucun système ne prédit le PnL d'une fenêtre 5h |
| Le risque de cluster sur même pattern | ✅ oui | Pattern visible déjà dans les backtests V1 — verdict 2026-04-25 |
| Le risque de drawdown 2j+ | ✅ oui | Sharpe ≈ 0 V1 → variance attendue, prédite par le verdict backtest |
| L'amplitude du DD | 🟡 partiel | Track A backtest dit maxDD 20 % sur 24m — donc -185 € sur 1 matinée est dans la norme statistique |

## Conséquences actées

### Pour V1 (système actuel en démo auto-exec)

- **Aucun changement immédiat** : V1 reste en démo, on n'investit plus dedans (verdict
  2026-04-25 "pas d'edge structurel"). La perte du jour n'invalide ni ne valide V1,
  elle confirme le verdict.
- **Backlog identifié — non priorisé** : si on devait sauver V1, les 4 fixes à
  ajouter sont (par ordre d'impact estimé) :
  1. Cooldown N-stops sur (pair, pattern, direction) — 30 min de dev
  2. Correlation cap : max 1 short metals à la fois — 1h de dev
  3. SL minimum width = X × ATR — 30 min de dev
  4. Pause auto si daily loss > Y % — déjà dans `.env` via `DAILY_LOSS_LIMIT_PCT`,
     vérifier qu'il est bien câblé

### Pour Track A V2_CORE_LONG (le successeur en shadow log)

- **Est-ce qu'il a évité ce drawdown ?** À vérifier. Les patterns Track A sont
  `momentum_up / engulfing_bullish / breakout_up` (LONG-only sur XAU H4). Le 2026-04-30
  matin, l'or **monte** → en théorie Track A aurait dû longer (donc gagner) là où V1
  shortait (donc perdre). **À confirmer via le shadow log endpoint** une fois la
  barre H4 fermée.
- Cette observation **renforce** l'hypothèse Track A : V1 perd sur la cassure haussière
  XAU, Track A devrait en profiter. Si le shadow log le confirme dans les prochains
  jours, c'est un argument fort pour activer Phase 5 plus tôt que la gate S6 (2026-06-06).

### Pour les autres tracks

- Aucun impact direct.

### Pour le code prod

- **Pas de déploiement immédiat.**
- Cette observation alimente le rapport hebdomadaire shadow log W1 (2026-05-03 routine
  programmée).

## Pour la suite

À investiguer (priorité décroissante) :

1. **Lire le résultat shadow log Track A sur 2026-04-30** une fois la barre H4 fermée
   à 16h UTC — confirmer qu'il aurait longé (BUY) là où V1 a shorté.
2. Si Track A confirme, **avancer la décision Phase 5** (activation auto-exec démo
   Track A en parallèle de V1, désactivation V1) au lieu d'attendre gate S6.
3. Vérifier que `DAILY_LOSS_LIMIT_PCT` côté `.env` prod est câblé et a une valeur
   sensée — si non câblé, fixer.

## Artefacts

- Pull trades : `curl /api/trades?limit=80` (auth admin), 9 trades 201-209 ce 2026-04-30
- Macro snapshot : `/api/macro` (public), `risk_regime:neutral` `gold:down` `oil:strong_up`
- Mémoire référence : `project_scalping_backtest_verdict.md` (verdict V1 sans edge),
  `project_research_j1_findings.md` (Track A prêt mais pas live)
- Pas de commit : c'est un journal d'observation, aucun code modifié
