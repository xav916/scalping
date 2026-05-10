# Rapport hebdo W2 — Shadow log V2_CORE_LONG

**Date :** 2026-05-10 (auto-généré par agent)
**Période :** 2026-05-03 → 2026-05-10 (7 jours, W2)
**Période cumulée Phase 4 :** 2026-04-25 → 2026-05-10 (15 jours)
**Déploiement Phase 4 :** 2026-04-25 17h00 UTC

> **Note W1 :** Le rapport W1 (2026-05-03) était non-probant — l'API était interrogée via l'ancienne URL `scalping-radar.duckdns.org`. Ce rapport W2 est le **premier rapport avec données réelles** depuis la migration vers `app.scalping-radar.online`.

---

## Santé endpoint public

| Endpoint | Statut | Code HTTP |
|---|---|---|
| `GET /api/shadow/v2_core_long/public-summary` | **OK** | 200 ✅ |
| `GET /v2/` (frontend SPA) | **OK** | 200 ✅ |

**Résolution du CRITICAL W1 :** L'API est désormais joignable. Le silence W1 était dû à l'ancienne URL, pas à un problème de pipeline.

---

## KPIs observés — Tableau par système (6 candidats)

| system_id | n_total | n_pending | n_tp1 | n_sl | n_timeout | net_pnl_eur | PF | WR% | Sharpe | maxDD% | Diagnostic |
|---|---|---|---|---|---|---|---|---|---|---|---|
| V2_CORE_LONG_XAUUSD_4H | 9 | 6 | 2 | 1 | 0 | **+127.68** | **3.51** | **66.7%** | n/a¹ | 0.5% | **OK ✅** |
| V2_CORE_LONG_XAGUSD_4H | 10 | 9 | 0 | 1 | 0 | −30.30 | 0.0² | 0.0%² | n/a¹ | 0.3% | **WARNING ⚠️** |
| V2_WTI_OPTIMAL_WTIUSD_4H | 3 | 1 | 0 | 1 | 1 | −48.08 | 0.0² | 0.0% | n/a¹ | 0.5% | **WARNING ⚠️** |
| V2_CORE_LONG_ETHUSD_1D | 2 | 1 | 0 | 0 | 1 | −5.98 | 0.0² | n/a | n/a¹ | 0.1% | **WARNING ⚠️** |
| V2_WTI_OPTIMAL_XLK_1D | 2 | 2 | 0 | 0 | 0 | n/a | n/a | n/a | n/a | n/a | **WARNING ⚠️** |
| V2_TIGHT_LONG_XLI_1D | **0** | — | — | — | — | — | — | — | — | — | **CRITICAL 🔴** |

¹ Sharpe = null pour tous les systèmes : insuffisance statistique (< 30 setups résolus, horizon 15j). Normal à ce stade.
² PF = 0.0 / WR = 0% : calculés sur 1-2 setups résolus seulement — non statistiquement significatif. Trigger CRITICAL drift (PF < 0.85 sur > 30 résolus) non atteint.

**PnL portefeuille consolidé :** +127.68 − 30.30 − 48.08 − 5.98 + 0 = **+43.32 €** (net, setups résolus uniquement)

---

## Détail par système

### V2_CORE_LONG_XAUUSD_4H — OK ✅

- **Premier signal :** 2026-04-27 12h UTC (2j après deploy)
- **Dernier signal :** 2026-05-08 20h UTC
- 3 setups résolus (2 TP1, 1 SL), 6 encore ouverts
- PF = 3.51 → nettement au-dessus de la cible 1.32–1.59 (attention : sur 3 résolus seulement)
- WR = 66.7% → au-dessus de la cible 50–55% (même réserve statistique)
- maxDD = 0.5% → largement sous le seuil 20%
- PnL cumulé : +127.68 € sur capital 10 000 € fictif (+1.3%)
- **Calmar = 15.04** (très positif mais horizon trop court pour être définitif)

**Interprétation :** Pipeline XAU 4H opérationnel, signaux détectés dès J+2 du deploy. Premiers résultats favorables mais trop peu de résolus pour validation statistique. Continuer à accumuler.

### V2_CORE_LONG_XAGUSD_4H — WARNING ⚠️

- 10 setups générés (le plus actif du portfolio), mais **9 encore en cours**
- 1 seul résolu = 1 SL → PF=0 et WR=0% non représentatifs
- PF null sera calculable dès ~5 résolus
- maxDD = 0.3% → sain, capital préservé
- Cadence de génération correcte (10 en 12j vs cible ~12/14j)

**Interprétation :** Beaucoup de setups ouverts — les prochains jours apporteront les résolutions. Le WARNING est lié à l'absence de données résolues, pas à un problème de pipeline.

### V2_WTI_OPTIMAL_WTIUSD_4H — WARNING ⚠️

- 3 setups seulement (cible 14j : 12) → volume insuffisant (WARNING trigger : 2–5)
- 1 SL + 1 timeout = perte de −48.08 € sur 2 résolus
- WTI est un marché énergétique à volatilité élevée ; un timeout et un SL sur 2 setups n'est pas conclusif
- maxDD = 0.5% → sous seuil

**Interprétation :** WTI sous-actif. Possible que le detector de patterns V2 trouve peu de configurations valides sur cette paire à horizon H4. À surveiller W3.

### V2_CORE_LONG_ETHUSD_1D — WARNING ⚠️

- 2 setups en 15j (1D → rythme normal de 1 setup/semaine attendu)
- 1 timeout résolu (−5.98 €), 1 pending
- Horizon 1D = résolutions plus lentes → WARNING volume normal pour ce timeframe

**Interprétation :** Cadence attendue pour un système daily. Pas de problème détecté. Réévaluer à 30j (≥ 4 setups résolus).

### V2_WTI_OPTIMAL_XLK_1D — WARNING ⚠️

- 2 setups générés depuis 2026-05-04 (premier signal J+9 deploy)
- Les deux encore en cours, aucun résolu
- Démarrage tardif mais pipeline actif
- maxDD = null (pas de résolu)

**Interprétation :** Système récemment activé, pas encore de données exploitables. Normal.

### V2_TIGHT_LONG_XLI_1D — CRITICAL 🔴

- **Absent de l'API** : 0 setup dans la table `shadow_setups` pour ce system_id
- Les 5 autres systèmes sont présents et actifs
- Cause possible : le detector ne trouve aucun pattern XLI valide, ou le system_id est mal configuré dans le scheduler Phase 4

**Action requise (hors scope agent) :**
```bash
# Sur EC2 — vérifier présence du system_id dans la DB
sqlite3 /app/data/trades.db \
  "SELECT system_id, COUNT(*) FROM shadow_setups GROUP BY system_id;"

# Vérifier logs scheduler pour XLI
sudo journalctl -u scalping --since '2026-04-25' | grep -i 'XLI\|TIGHT_LONG' | tail -30
```

---

## Diagnostic global

### INFRA — OK ✅
Frontend HTTP 200, API shadow joignable et retournant des données structurées. L'incident W1 (URL périmée) est résolu. Pas de régression infra détectée.

### DATA FEED — PARTIAL OK ⚠️
- 5/6 systèmes génèrent des signaux (XAU, XAG, WTI, ETH, XLK)
- XLI absent (0 setup) → CRITICAL isolé sur ce candidat
- Les volumes sont cohérents avec les attentes sur les systèmes 4H (XAU=9, XAG=10)
- Les systèmes 1D (ETH, XLK) suivent un rythme plus lent, normal

### PERFORMANCE — NON CONCLUSIF (trop tôt)
- XAU : premiers résultats encourageants (PF=3.51, WR=67%), mais n=3 résolus
- XAG, WTI, ETH, XLK : trop peu de setups résolus pour évaluer
- XLI : non évaluable (0 setup)
- maxDD tous systèmes < 1% → capital virtuel préservé
- PnL consolidé : +43.32 € — portefeuille en territoire positif grâce à XAU
- Aucun trigger CRITICAL performance atteint (seuil : PF < 0.85 sur > 30 résolus)

---

## Évolution depuis Phase 4 deploy (2026-04-25)

| Jalon | Statut |
|---|---|
| Pipeline shadow opérationnel | ✅ Confirmé W2 |
| 6 systèmes actifs dans DB | ⚠️ 5/6 (XLI absent) |
| Premier signal XAU | ✅ 2026-04-27 (J+2) |
| Premier TP1 XAU | ✅ 2026-05-05 (J+10) |
| n_total XAU ≥ 6 (OK range) | ✅ n=9 |
| n_total XAG ≥ 6 (OK range) | ✅ n=10 |
| PF XAU ≥ 1.15 | ✅ PF=3.51 (n=3, non conclusif) |
| maxDD < seuils | ✅ Tous < 1% |
| Sharpe ≥ 0.7 | ⏳ En attente (manque de résolus) |
| V2_TIGHT_LONG_XLI_1D actif | 🔴 0 setup |

---

## Activité git W1 → W2 (2026-05-03 → 2026-05-10)

**46 commits** pushés sur la période.

```
703866b feat(monitoring): radar_cycle_heartbeat dédié pour bridge_monitor
9ec3946 docs(specs): Day Trading Radar V0 spec — gated par scalping V2 gate S6
ca05835 feat(settings): broker preset picker pré-remplit InpSymbolMap pour l'EA
01810a2 docs+fix(ea): no-store cache + section "Mettre à jour l'EA"
4a71a3d fix(telegram): legacy Markdown ne supporte pas **bold**
c4e9b00 chore(journal): rapport hebdo veto contrefactuel 2026-05-09
0e12256 docs(monitoring): rapport hebdo Track A veto contrefactuel (auto)
2eb9545 feat(telegram): notif pédagogique de fermeture (TP/SL/TIMEOUT/MANUAL)
925165d feat(telegram): format pédagogique pour le canal user-facing
222109b refactor(rejection-alerts): bascule canal user-facing → bot infra
db44ef6 feat(admin): expose watched_pairs per user + admin global dans health-token
77bf391 fix(ea): autoriser polling 1s
3f49d2d research(v1): calibration Brier — confidence_score anti-prédictif zone 60-65
1bb7d91 docs(ea): documenter le nouvel input InpSymbolMap
c7754ad feat(ea): InpSymbolMap input pour mapping pair→broker_symbol
63a88cf feat(admin): drill auto-exec/health avec failed_by_pair + recent_errors
994c66e feat(admin): variante token-auth de auto-exec/health pour monitoring remote
5713d56 feat(infra): endpoint /api/admin/notify-infra-telegram pour alertes routines
def6388 feat(shadow): filtered twin systems for A/B veto live comparison
68db33a fix(deploy): move docker image prune AFTER systemctl restart
6eb39c6 feat(shadow): endpoint counterfactual auth-by-token + journal session
1dcede1 chore: hygiene final session — gitignore CSVs + commit doc
e40847a feat(cockpit): Track A shadow log mini-card
2f63cc1 feat(research): script Track A × veto contrefactuel
1864a73 fix(geopolitical): preserve cross-theme coverage on GDELT throttle
3ac0d70 feat(shadow-log): capture geopolitical snapshot per Track A setup
77e89bf feat(admin): geopolitical veto activity dashboard
8a270a8 feat(scoring): add geopolitical veto rules (Polymarket + GDELT)
feda080 fix(cockpit): use event_slug for Polymarket deep-link
22fabbd feat(cockpit): add Polymarket prediction markets card
907e3dd fix(routing): drop bridge_url requirement for EA-only Premium users
091c04c feat(cockpit): add geopolitical tension card
4c54c4c Merge branch 'feat/cache-warmup-task' into deploy/session-2026-05-05-v2
4bfd922 feat(scheduler): cache warmup task pour les endpoints cold-prone
196d521 feat(mobile-nav): ajoute items admin si is_admin
... (+ 12 commits fixes/docs mineurs)
```

### Thèmes majeurs W1 → W2

| Thème | Commits | Impact Phase 4 shadow |
|---|---|---|
| Geopolitical veto (GDELT + Polymarket) | ~8 | ⚠️ Indirect — veto peut filtrer des setups V2 |
| Shadow counterfactual A/B comparison | ~4 | Outillage monitoring shadow amélioré |
| EA MQL5 (InpSymbolMap, presets, cache) | ~5 | Aucun (exécution, hors scope) |
| Cockpit (Track A card, Polymarket card) | ~4 | Monitoring facilité |
| Admin drill + token-auth health | ~3 | Monitoring infra facilité |
| Telegram format pédagogique | ~3 | Aucun |
| Cache warmup scheduler | ~2 | Bénéfique (latence cold réduite) |
| Fixes + docs divers | ~17 | Aucun |

> **Observation clé :** Aucun commit ne touche directement `shadow_setups`, le scheduler Phase 4, ou la logique de détection V2_CORE_LONG. Le pipeline shadow est stable depuis le deploy initial. L'ajout du **veto géopolitique** (GDELT/Polymarket) est la seule évolution susceptible d'impacter la fréquence des signaux — à surveiller si le volume XAU/XAG baisse en W3.

---

## Recommandations

### 1. CRITICAL — Investiguer V2_TIGHT_LONG_XLI_1D (0 setup)

Priorité haute. Ce système est l'un des 6 candidats du portefeuille Phase 4 et ne génère aucun signal 15 jours après le deploy. Actions EC2 :

```bash
# Vérifier que le system_id existe bien en DB
sqlite3 /app/data/trades.db \
  "SELECT system_id, COUNT(*) FROM shadow_setups GROUP BY system_id ORDER BY 2 DESC;"

# Logs scheduler pour XLI
sudo journalctl -u scalping --since '2026-04-25' | grep -i 'XLI\|tight_long' | tail -50

# Vérifier que XLI est bien dans WATCHED_PAIRS ou équivalent Phase 4
grep -r 'XLI' /app/backend/ --include='*.py' | grep -v '.pyc'
```

### 2. WARNING — Surveiller XAG résolutions (9 pending)

XAG a 10 setups ouverts dont 9 pending. Les résolutions vont arriver en W3 et détermineront si le PF réel est conforme aux backtests (cible 1.55). Si PF < 0.85 sur les 9 résolus → déclencher une revue du filtre XAG.

### 3. INFO — Sharpe non calculable à ce stade

Sharpe = null pour tous les systèmes. Normal : le calcul nécessite une série temporelle de rendements avec variance non nulle. Redevient calculable autour de 10-15 setups résolus par système (horizon estimé W4-W5 pour XAU/XAG).

### 4. INFO — Impact veto géopolitique à quantifier en W3

Le pipeline GDELT/Polymarket déployé en W2 peut filtrer des setups V2_CORE_LONG. Si le volume XAU/XAG baisse notablement en W3 vs W2, comparer avec le counterfactual (endpoint dédié) pour distinguer marché calme vs veto trop agressif.

### 5. Gate S6 (2026-06-06) — Horizon 4 semaines

| Condition gate S6 | Statut actuel | Trajectoire |
|---|---|---|
| XAU : n_resolved ≥ 20 | 3/20 | ⚠️ Faisable si 6+ résolutions/semaine |
| XAG : n_resolved ≥ 20 | 1/20 | ⚠️ 9 pending → résolutions imminentes |
| XAU PF ≥ 1.32 sur n ≥ 20 | 3.51 sur 3 | À confirmer sur volume |
| XLI : au moins 1 setup | 0 | 🔴 Bloquer si XLI reste silencieux |
| maxDD < seuils | ✅ | Stable |

Le gate S6 reste atteignable si le volume de résolutions s'accélère en W3-W4 et que XLI est corrigé.

---

## Conclusion W2

**Première lecture probante** depuis le deploy Phase 4 du 2026-04-25. L'infrastructure est opérationnelle (API + frontend HTTP 200), 5 des 6 systèmes génèrent des signaux.

**Point positif :** XAU (V2_CORE_LONG_XAUUSD_4H) affiche des premiers résultats solides (PF=3.51, WR=67%, maxDD=0.5%) sur 3 setups résolus. Capital virtuel global en territoire positif (+43 €).

**Point d'attention :** V2_TIGHT_LONG_XLI_1D est absent de la DB après 15 jours — statut CRITICAL isolé à investiguer manuellement sur EC2. Les autres systèmes sont en WARNING de volume (trop peu de résolus pour juger), ce qui est normal à J+15.

**Prochain jalon :** Rapport W3 (2026-05-17) — attendu avec les résolutions XAG (9 pending) et une première évaluation multi-système de PF réel.
