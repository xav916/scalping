# Day Trading Radar V0 — spec architecture

**Date :** 2026-05-09 (gate décalé le 2026-05-22)
**Statut :** spec **draft, gated** par la validation Scalping V2 au gate **S8 (2026-07-04)** — décalé de S6 (2026-06-06) suite à l'incident rsync --delete du 2026-05-18 qui a wipé la table `shadow_setups` et fait perdre 3 semaines de données V2
**Auteur :** session collaborative humain + assistant (Opus 4.7 1M)
**Horizon de mise en chantier :** ~2026-07-04 (au plus tôt) si Track A V2_CORE_LONG XAU H4 valide gate S8 (cf. `project_research_j1_findings.md`)
**Effort estimé :** ~15-20 h pour V0 shadow log, +30-40 h pour passage live démo
**Précondition :** Scalping V2 confirmé profitable en shadow live (gate S8) OU pivot SaaS observatoire-only acté

---

## Contexte

### Pourquoi maintenant

`project_trading_radars_roadmap.md` fixe l'ordre : scalping → **day** → swing → position. Le Scalping Radar V2 (Track A) est **en shadow live depuis 2026-04-25**, gate de décision le **2026-06-06**. À cette date, 3 issues :

1. **Scalping V2 validé** → on lance Day Trading V0 selon cette spec
2. **Délai +6 semaines** → on attend, mais cette spec reste utile (rien à jeter)
3. **Pivot observatoire-only** → on archive cette spec et on refocalise sur SaaS

Cette spec est rédigée **maintenant** (et pas en juin) parce que :
- Le contexte technique est frais dans la tête de l'auteur
- Si gate S6 valide, on peut démarrer le brainstorm le 2026-06-07 sans temps de chargement
- Le coût de rédaction (1.5 h) << coût d'oubli des décisions architecturales prises pendant scalping

### Ce qui change vs scalping

| Dimension | Scalping V1/V2 | Day Trading V0 |
|---|---|---|
| **Horizon trade** | minutes à 1-2 h | 4 h à 1 jour (clôture avant fin session US ou auto-close fin de journée) |
| **TF analyse** | M5/M15 (V1), H1/H4 (V2 Track A) | M30 + H1 (analyse), H4 (contexte) |
| **Patterns** | momentum, engulfing, breakout (3 patterns LONG) | breakout opening range, retournement sur niveaux clés, continuation trend intraday, fade gap |
| **Stops** | 10-30 pips (V1), ATR×1-2 (V2) | 30-80 pips ou ATR×2-3 |
| **Targets** | 15-50 pips (V1), R:R 1.5-3 (V2) | 60-200 pips, R:R 1.5-2.5 |
| **Volume signaux/jour** | 5-30 setups (V1), 1-3 (V2 stars-only) | 3-8 setups (estimation) |
| **Sessions actives** | 24/5 forex/metals, 24/7 crypto | London open + NY open (2 fenêtres ~4h chacune) |
| **Macro contexte** | scoring multiplier | **filtre principal** (DXY trend, SPX sentiment, calendrier news high-impact) |

### Hypothèse de marché

Le day trading **devrait** mieux exploiter l'edge structurel que le scalping car :
- Le ratio bruit/signal est meilleur (mouvements 5-10× plus grands que les coûts spread+slippage)
- Le contexte macro intraday (London/NY open, calendrier économique 8:30 ET) est exploitable sans timing à la seconde
- La V2 Track A H4 a déjà montré du Sharpe 1.59 sur 24 mois — preuve qu'au-dessus de M15 il y a de l'edge sur les métaux. Day trading H1 prolonge cette logique.

À démontrer dans la phase recherche (cf. ci-dessous).

---

## Scope V0

### Inclus

- **Assets** : XAU/USD, XAG/USD, WTI/USD, ETH/USD (même stars-set que scalping V2). + extension SPX/NDX H1 (instruments index = day-trading friendly, abandonnés en scalping V1 pour bonnes raisons mais re-évaluables sur H1).
- **TF analyse** : M30 + H1 (analyse principale), H4 (contexte tendance)
- **3 patterns V0** :
  1. **Opening range breakout** — high/low des 60 premières minutes London (08:00 UTC) ou NY (13:30 UTC). Cassure avec volume confirme un trade dans la direction de la cassure.
  2. **Retournement support/résistance** — rejet H1 sur niveau swing high/low identifié sur H4. Pattern : pin bar + clôture H1 du côté opposé.
  3. **Continuation pullback** — pullback sur EMA(20) H1 dans le sens d'une tendance H4 confirmée (close > EMA(50) H4). Entrée sur clôture H1 dans le sens de la tendance.
- **Macro filtre principal** :
  - Calendrier news high-impact ±30 min : skip (pas pendant la news)
  - DXY trend day (open vs current) : longs USD-fort uniquement si DXY < open ; longs USD-faible uniquement si DXY > open
  - SPX/VIX intraday : si VIX > seuil régime, augmenter min_confidence requis
  - GDELT geopolitical (déjà branché scalping) : réutiliser tel quel
- **Risk model** : stops ATR(14) × 2.5 sur H1, targets R:R 2.0 (TP1) + 3.0 (TP2). Sizing 0.3-0.5% par trade
- **Bridge** : EA MQL5 partagé avec scalping (queue `mt5_pending_orders`, polling déjà en prod). Pas d'EA dédié day-trading V0.
- **Auto-close fin journée** : nouvelle logique côté bridge — si position ouverte > 18h Paris pour XAU/XAG/WTI ou > 22h Paris pour ETH, force close. Évite de tenir overnight (par construction day trading).

### Exclus V0 (à reporter swing/V1)

- ❌ Stops dynamiques type trailing
- ❌ Pyramidage (entrées multiples sur la même direction)
- ❌ Cross-asset corrélation comme contrainte (max 1 USD-long simultané, etc.)
- ❌ Patterns multi-bougies complexes (head-shoulders, triangles, double-tops manuels)
- ❌ ML features
- ❌ Hedging
- ❌ Multi-broker arbitrage

---

## Architecture

### Décision V0 : extension du repo scalping (PAS app séparée)

**Pourquoi** :
- 80% du code utile (price_service, EA queue, MT5 push, signals DB, scheduler, frontend cockpit) est dans `scalping-radar` et marche
- Une app séparée double les coûts ops (deploy, monitoring, EC2) sans valeur ajoutée pour V0
- L'extraction en lib partagée a du sens APRÈS validation day trading V0 (sinon on extrait pour rien)

**Implémentation** :
- Nouveau scheduler hook `day_trading_scheduler.py` à côté de `analysis_engine.py`
- Setups stockés dans `signals` table avec colonne `strategy='day_trading_v0'` (à ajouter via migration)
- Frontend cockpit : nouvelle carte "Day Trading" séparée de la carte scalping (filtre par strategy)
- EA reçoit les ordres sans distinction (bridge ne sait pas si c'est scalping ou day trading, juste un setup à exécuter)

### À refactor en lib partagée AVANT le swing

Quand on attaquera Swing Radar (post-day trading V1), faire un refactor `lib/` :
- `lib/price_service` (TwelveData + cache)
- `lib/macro_context` (DXY/SPX/VIX/yields/oil/gold)
- `lib/mt5_queue` (mt5_pending_orders, EA serving)
- `lib/auth` (cookies session, tier gates)
- `lib/ui_shell` (header, glass card, motion primitives)

C'est un chantier ~2 semaines à part entière. À ne PAS faire pendant Day Trading V0 (over-engineering).

---

## Data sources

### Identique scalping (réutilisé tel quel)

- **Twelve Data Grow** : OHLC M30/H1/H4 sur les pairs watchlist. Quota 55 req/min suffit (5 pairs × 3 TF = 15 req/cycle, cycle toutes les 5 min = 3 req/min)
- **GDELT geopolitical** (déjà en prod) : filtre veto si stress haut
- **ForexFactory JSON** : calendrier économique, déjà en prod
- **Polymarket prediction markets** (déjà en prod) : optionnel pour V0

### À ajouter pour day trading

- **Session boundary detection** : module `sessions.py` qui calcule open/close London (07:00-15:00 UTC) et NY (12:30-21:00 UTC) en tenant compte des DST. Identique à `market_hours.py` existant mais focalisé sur les 2 sessions actives intraday.
- **Opening range tracker** : calcule high/low des 60 premières minutes de chaque session, persiste en mémoire (SQLite optionnel). Utilisé par le pattern #1 (breakout opening range).
- **VWAP intraday** : moyenne pondérée par volume depuis open de session. **Limite Twelve Data Grow** : pas de volume forex fiable, donc VWAP forex = approximation OHLC mid. Pour XAU/XAG/WTI/ETH le volume futures CME ou crypto est utilisable mais demande source supplémentaire (à reporter V1).

---

## Méthodologie de validation

### Phase 1 — Recherche (~1 semaine)

Backtest historique sur 24 mois de données H1 (2024-2026) pour les 3 patterns V0 sur les 6 assets :

- **Métriques cibles** (par pattern × asset) : Sharpe ≥ 1.0, PF ≥ 1.15, maxDD ≤ 25%, n_trades ≥ 30
- **Outcome** : matrice 3×6 = 18 cellules, on garde les cellules pass et on pousse en shadow live ; on rejette les cellules fail
- **Suspect-patterns à challenger explicitement** :
  - Opening range breakout : forte literature mais souvent false breakouts. Confirmer avec filtre volume (XAU futures CME).
  - Pin bar S/R : sample petit à H1, risque d'overfitting sur 24M. Tester en walk-forward.
- **Précédent** : Track A research J1 a produit 13 expériences en 1 jour. Day trading V0 demande un effort similaire (~5-7 jours) pour parcourir les 18 cellules.

### Phase 2 — Shadow log (~6 semaines, identique scalping V2)

- Setups loggés dans `shadow_setups` avec `system_id` type `DAY_BREAKOUT_OR_XAUUSD_1H`
- Reconciliation auto via le pipeline existant (réutilisé tel quel)
- Routine RemoteTrigger hebdo `Day Trading shadow W1-W6` (cloner la routine scalping `trig_01EpPcrxPacoW8qk6fsPAyAX`)
- Gate de décision après 6 semaines : KPIs vs cibles backtest

### Phase 3 — Live démo

- Auto-exec sur compte démo Pepperstone existant via EA. Aucune nouvelle infra.
- Sizing initial 0.1% par trade (vs 0.5% scalping) pour limiter risk pendant validation
- Phase démo 4-6 semaines, gate avant live réel : Sharpe live ≥ 70% du backtest, slippage observé < 5 pips moyen

---

## Réutilisation depuis le Scalping Radar

| Composant scalping | État pour day trading | Effort |
|---|---|---|
| `analysis_engine.py` | Réutiliser le squelette, ajouter detect_patterns_day_trading | 2 h |
| `price_service.py` | Réutilisé tel quel (cache + semaphore TD) | 0 h |
| `mt5_pending_orders` queue | Réutilisé tel quel (EA polling) | 0 h |
| `macro_context_service` | Réutilisé tel quel | 0 h |
| `geopolitical_veto` | Réutilisé tel quel | 0 h |
| `signal_rejections` | Étendre avec reason_codes day-specific (`outside_session`, `news_blackout`) | 1 h |
| `shadow_setups` | Étendre avec strategy column ou nouveaux system_id | 1 h |
| Frontend cockpit | Ajouter carte Day Trading + onglet | 4 h |
| Telegram service | Réutilisé tel quel (bot user-facing pédagogique) | 0 h |
| Routine RemoteTrigger | Cloner les routines hebdo + gate | 1 h |

### À écrire spécifiquement

| Module | Effort estimé |
|---|---|
| `day_trading/patterns.py` (3 patterns V0) | 4 h |
| `day_trading/sessions.py` (London/NY open detection) | 2 h |
| `day_trading/opening_range.py` (tracker high/low premières 60 min) | 2 h |
| `day_trading/scheduler.py` (hook scheduler appelant les patterns) | 2 h |
| `bridge.py` patch — auto-close intraday | 2 h |
| Frontend `DayTradingCard.tsx` | 4 h |
| Tests unitaires patterns + sessions | 4 h |

**Total V0 shadow log : ~25 h** dev + ~7 h research backtest = ~32 h pour MVP shadow live.

---

## Risk model V0

### Sizing

- 0.3% par trade en démo, 0.1% en early live (premiers 50 trades)
- Cap simultané : max 2 positions day trading ouvertes (vs 6 scalping)
- Pas de pyramidage

### Stops / targets

- **Stop** : ATR(14) H1 × 2.5, capé à 80 pips max sur forex / 1% du prix max sur metals/crypto/oil
- **TP1** : entry + R × 2.0 (50% taille close, breakeven move sur le reste)
- **TP2** : entry + R × 3.0 (50% taille restante)
- Si hold > N heures sans toucher TP1, close à breakeven (TIMEOUT logic)

### Auto-close fin journée

- XAU/XAG/WTI/SPX/NDX : close forcé à 21:00 UTC (= 22h Paris) si position encore ouverte. Évite le risque overnight gap.
- ETH : close forcé à 22:00 UTC (24h crypto, mais les liquidités baissent en weekend Asia → close vendredi soir)
- Implémentation côté bridge.py + EA : tâche scheduler vérifie chaque heure, ferme les `magic_number` day-trading si trop vieux

### Kill switch

- DD journalier > 2% → pause auto-exec day trading 24h
- DD hebdo > 5% → pause 1 semaine + alerte infra Telegram
- Réutiliser le pattern kill-switch scalping (déjà en prod)

---

## Open questions / décisions à prendre

### Avant le brainstorm post-gate S6

1. **TF analyse principal** : H1 ou M30 ? Trade-off : M30 = plus de signaux (5-8/jour) mais plus bruité, H1 = moins (3-5/jour) mais cleaner. Reco : H1 pour V0 (cohérent avec backtest J1 V2 H4 qui a montré edge à TF élevé).
2. **Pattern set initial** : 3 patterns V0 ci-dessus est un guess. À challenger en brainstorm — peut-être ne garder que 2 (breakout + pullback) et virer le pin bar S/R (sample petit historique).
3. **Indices US (SPX/NDX)** : à inclure V0 ? Avantage diversification + day-trading friendly ; risque sample plus petit en backtest car horaires limités. Reco : OUI, c'est exactement le cas où le V0 day trading peut faire mieux que V1 scalping qui les avait écartés.
4. **Volume forex** : sans data fiable, l'opening range breakout est moins robuste. Aller chercher CME futures (XAU = GC, WTI = CL) via une 2e source data ? Ou skip volume filter pour V0 et accepter plus de false breakouts ?
5. **Auto-close intraday** : pause-éviction (close auto sur tous magic_numbers day-trading à 21h UTC) ou simple notif "tu as une position ouverte, ferme-la manuellement" pour V0 ? Reco : auto-close (sinon le user oublie et perd l'avantage day trading).

### Décisions architecturales à valider

1. **Strategy column dans `signals`** : ALTER TABLE `signals` ADD COLUMN `strategy` TEXT DEFAULT 'scalping' — accepté ou refus (préférence pour `system_id` parsing) ?
2. **EA inputs** : ajouter `InpDayTradingMaxLot` séparé du scalping ? Ou unifié sur `InpDefaultLot` avec sizing déjà géré côté backend dans le payload ?
3. **Frontend** : un onglet `/v2/day-trading` séparé, ou onglet du cockpit existant ? Reco : carte du cockpit V0, page dédiée V1.
4. **Telegram** : nouveau bot dédié day-trading, ou même bot user-facing avec préfixe `[DAY]` ? Reco : même bot avec préfixe, simplifie les credentials.

---

## Gating

### Précondition pour démarrer

- ✅ Scalping V2 (Track A) gate S6 = **GO** (= 2026-06-06)
- OU décision business explicite "on lance day trading même si scalping en délai" (peu probable)

### Blocker pour passer en live

- Backtest 24M : ≥ 50% des cellules 3×6 montrent Sharpe ≥ 1.0 ET PF ≥ 1.15
- Shadow log 6 semaines : KPIs vs backtest dans tolérance ±20%
- Ratio backtest/shadow Sharpe ≥ 0.5 (sinon overfitting)
- DD shadow ≤ DD backtest × 1.5

### Quand ARRÊTER (kill-switch architectural)

- Si après 1 semaine de research backtest, ≤ 3 cellules sur 18 passent → day trading n'a probablement pas d'edge structurel non plus, **abort** et refocaliser sur SaaS observatoire-only
- Si shadow PF live < 0.85 sur 100+ trades → idem abort

---

## Phasage / planning macro

| Étape | Effort | Date estimée |
|---|---|---|
| Spec drafted (cette session) | 1.5 h | 2026-05-09 ✅ |
| Gate S6 validation scalping | — | 2026-06-06 |
| Brainstorm + spec V1 day trading | 4 h | 2026-06-07 |
| Phase 1 research backtest (3×6 cellules) | 30 h | 2026-06-08 → 2026-06-15 |
| Décision GO / NO-GO live shadow | — | 2026-06-15 |
| Phase 2 implémentation shadow log | 25 h | 2026-06-16 → 2026-06-22 |
| Phase 2 observation 6 semaines | — | 2026-06-22 → 2026-08-03 |
| Gate S12 day trading | — | ~2026-08-03 |
| Phase 3 live démo Pepperstone | 15 h | 2026-08-04 onwards |
| Live argent réel | — | au plus tôt 2026-10 |

---

## Pour reprise

Si l'user revient sur cette spec après gate S6 et veut démarrer day trading :

1. **Lire** : cette spec + `project_research_j1_findings.md` + `project_trading_radars_roadmap.md`
2. **Brainstorm** dédié 1-2h via `superpowers:brainstorming` pour trancher les 5 open questions ci-dessus
3. **Spec V1** : itérer cette spec en `2026-06-07-day-trading-radar-v1-spec.md` avec les décisions actées
4. **Plan** : générer `docs/superpowers/plans/2026-06-07-day-trading-research-phase1.md` pour la phase backtest
5. **Exécution** : research backtest en mode 3 tracks parallèles (1 par pattern V0), précédent J1 scalping prouve que c'est faisable en 5-7 jours

Si gate S6 ressort en **délai** ou **stop**, cette spec reste utile :
- En cas de délai : la relire dans 6 semaines au gate S12
- En cas de stop/pivot : archiver dans `docs/superpowers/journal/` avec un header "ABANDONNÉ post-gate S6"

---

## Pourquoi cette spec maintenant et pas en juin

Le coût de rédaction est ~1.5 h. Le gain :
- Capture le contexte architectural pendant que c'est encore frais (composants réutilisables, pièges connus, métriques validées)
- Permet de démarrer le brainstorm post-gate S6 sans temps de chargement
- Évite de re-prendre les décisions structurantes (extension du repo vs app séparée, EA partagé, etc.) qui ont déjà été pesées dans le contexte du scalping

Si scalping ne valide pas le gate, cette spec est jetée — mais 1.5 h investies vs 4-6 h de re-discovery + risque d'oubli structurel = ratio gagnant.

## Références

- `project_trading_radars_roadmap.md` — ordre des radars
- `project_research_j1_findings.md` — précédent méthodo + 6 candidats portefeuille
- `project_research_portfolio.md` — pivot recherche 2026-04-25
- `project_scalping_current_phase.md` — seuils + état actuel scalping
- `docs/superpowers/specs/2026-04-25-research-portfolio-master.md` — master plan recherche scalping V2
- `docs/superpowers/specs/2026-04-25-phase4-shadow-log-spec.md` — pattern shadow log à reproduire
