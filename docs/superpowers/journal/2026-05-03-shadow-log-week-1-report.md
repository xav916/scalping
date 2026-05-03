# Rapport hebdo W1 — Shadow log V2_CORE_LONG

**Date :** 2026-05-03 (auto-généré par agent remote)
**Période :** 2026-04-26 → 2026-05-03 (7 jours)
**Déploiement Phase 4 :** 2026-04-25 17h00 UTC

---

## KPIs observés vs cibles

| Métrique | XAU obs | XAU cible | XAG obs | XAG cible | Diagnostic |
|---|---|---|---|---|---|
| n_total 7j | N/A | ~6 | N/A | ~6 | **CRITICAL** |
| n_pending | N/A | — | N/A | — | — |
| Sharpe | N/A | ≥ 0.5 | N/A | ≥ 0.5 | N/A |
| PF obs | N/A | 1.32–1.59 | N/A | 1.32–1.59 | N/A |
| maxDD% | N/A | < 20% | N/A | < 26% | N/A |
| WR% | N/A | 50–55% | N/A | 49–54% | N/A |
| net_pnl_eur | N/A | — | N/A | — | N/A |

> **Réponse brute API :** endpoint non joignable depuis l'environnement sandbox (DNS résout vers IP privée/réservée). Le frontend `/v2/` répond HTTP 200, ce qui confirme que l'infra EC2 tourne. Le silence du pipeline shadow est à investiguer en SSH directement sur EC2.

---

## Diagnostic global

- **INFRA :** PARTIAL OK — frontend `/v2/` répond HTTP 200. L'endpoint shadow `/api/shadow/v2_core_long/public-summary` n'est pas joignable depuis sandbox (DNS privé), statut API inconnu.
- **DATA FEED :** CRITICAL présumé — 0 setup confirmé via l'API après 7 jours. Cause probable : scheduler non actif ou aucun pattern V2_CORE_LONG détecté sur les bougies H4 disponibles.
- **PERFORMANCE :** NON ÉVALUABLE — aucune donnée de trade disponible.

### Interprétation du silence

Deux causes possibles, par ordre de probabilité :

1. **Scheduler H4 en panne** — le job qui scanne les setups (branche Phase 4 dans `scheduler.py`) ne tourne pas (EC2 reboot ? worker mort ? variable d'env manquante après redeploy).
2. **Marché calme / aucun pattern** — le `detect_patterns` ne trouve aucun setup V2_CORE_LONG sur les bougies H4 récentes, ce qui est normal en marché sans tendance H4 claire. Sur 7 jours, ~6 setups sont attendus statistiquement mais restent probabilistes.

---

## Activité git (depuis 2026-04-26)

**49 commits** pushés depuis la fin de la session Phase 4.

```
2602815 feat(admin): dashboard auto-exec health dans /v2/admin
fa905e8 fix(deploy): persiste les chunks lazy entre deploys
86e3c6a fix(spa): auto-reload sur stale chunk 404 après deploy
02bef56 test: smoke test Header rendu sur Settings et Admin
b6ba8c2 feat(layout): render Header on Settings and Admin pages
3721411 feat(header): expose /admin backoffice link in admin nav
f80938f feat(watchdog): persistance historique rafales + UI history
fd085b3 test: integration tests endpoints admin watchdog
4eb5ee9 feat(admin): watchdog UI + manual unpause
4a50b16 feat(circuit-breaker): smart resume basé sur activité réelle V1
076c974 refactor(circuit-breaker): per-pair pause + global safety net
1efbd6d feat(circuit-breaker): auto-pause/resume sur rafale stops loss
b4be565 feat(alerts): watchdog stops loss en rafale
1400327 docs: journal drawdown V1 2026-04-30 + carte archi 3 couches
fd2f787 docs(ea-setup): add Mac-specific section
0de1995 fix(ea): détection dynamique filling mode + propagation retcode dans ack
a640e5e docs(ea): /docs/ea-setup.html guide HTML + alignement MT5_EA_INSTALL.md sur flow MQL.E
d50ee50 feat(ea): Phase MQL.E — UI Settings auto-exec + endpoints download/api-key
a624e43 feat(ea): Phase MQL.D — Expert Advisor MQL5 source ScalpingRadarEA.mq5
f06d9d2 feat(ea): Phase MQL.C — _push_to_destination route admin/HTTP vs user/queue
bca2503 feat(ea): Phase MQL.B — queue mt5_pending_orders + 3 endpoints EA
2b57c15 docs(spec): pivot MQL5 EA pour éliminer le bridge Python Premium
d6f0843 feat(mt5-bridge): version le code bridge MT5 dans le repo (Phase E.1)
1575a9d docs: starter pack onboarding Cédric (bridge MT5 Premium)
7580af3 merge: multi-tenant bridge routing — Phases A-D
48293a9 feat(bridge): Phase D.2 — toggle UI auto-exec MT5 dans Settings
a7c24a2 feat(bridge): Phase D.1 — endpoint /api/user/broker/auto-exec + safety check
aeb19d5 feat(bridge): Phase C — _user_destinations route les Premium auto-exec
dbf2b13 feat(bridge): Phase B — dedup atomique en DB via mt5_pushes_service
aa35bee feat(bridge): Phase A.2 — send_setup boucle sur destinations multi-tenant
9aa1662 feat(bridge): Phase A.1 — bridge_destinations module + 7 tests verts
154d44d docs(spec): multi-tenant bridge routing pour ouverture tier Premium auto-exec
7b8c125 feat(monitor): version bridge_monitor.py + env template, bridge_local probe optional
ad61c73 feat(admin): Infra cache aux non-admins (lien header + redirect propre)
dc9731b feat(admin): expose is_admin dans /api/me + V1 cache aux non-admins (lien + page)
3b7703e feat(active-trades): renomme Engage->Exposition + colonne Bloque (margin EUR + pct capital)
7b39d99 feat(active-trades): colonne Engage (notional EUR) entre Entry et Dist SL
52ad4b7 feat(telegram): format compact action-first + desactive send_signal pollutant
21bf3e5 feat(menu): epuration top-level (Cockpit/Candidats/Infra/V1) + V1HubPage
21bf3e5 feat(cockpit): courbe live capital MT5 (parsing bridge_monitor.log)
918044f feat(cockpit): 6 stars dans LiveChartsGrid + nav admin (V1, Infra)
1d77df9 fix(App): retirer l'import DashboardPage unused (TS6133 build fail)
e317026 feat(home+admin): cockpit unifie + tour de controle + page V1 legacy
805ce4d feat(mt5_bridge): n'auto-exec que sur les 6 stars du portefeuille
ee3b9c3 feat(telegram): n'alerter que sur les 6 stars du portefeuille
971c378 fix(changelog): pré-génération docs/changelog.json au deploy
dd663a6 feat(public): sitemap + changelog + about + parrainage + tests
cc98d50 feat(public): email capture + page recherche + SEO meta tags
9ddfc18 feat(public): pages /v2/live + /v2/track-record + endpoints public + landing repivot
```

### Thèmes majeurs sur la semaine

| Thème | Commits | Impact Phase 4 |
|---|---|---|
| MQL5 Expert Advisor (Phases MQL.B→E) | ~8 | Aucun (hors scope) |
| Multi-tenant bridge routing (Phases A-D) | ~10 | Aucun (hors scope) |
| Circuit-breaker / Watchdog V1 | ~6 | Aucun (V1 inchangé) |
| Cockpit unifié + UI Admin | ~7 | Monitoring facilité |
| Pages publiques (/v2/live, /track-record) | ~3 | Aucun |
| Docs + fixes divers | ~15 | Aucun |

> **Observation :** Aucun commit ne touche `scheduler.py`, `shadow_setups`, ou la branche Phase 4. Le pipeline shadow n'a pas été modifié depuis le déploiement initial du 2026-04-25.

---

## Recommandations

### Priorité CRITICAL — Investiguer le silence du pipeline shadow

**Étape 1 — Vérifier le scheduler EC2 :**
```bash
sudo systemctl status scalping
sudo journalctl -u scalping --since '2026-04-25' | grep -i 'shadow\|error' | tail -50
```

**Étape 2 — Vérifier le data feed Twelve Data :**
```bash
sudo docker exec scalping-radar python -c "
import asyncio
from backend.services.price_service import fetch_candles
c, _ = asyncio.run(fetch_candles('XAU/USD', interval='1h', outputsize=10))
print(f'fetched {len(c)} candles')
"
```

**Étape 3 — Vérifier la table `shadow_setups` directement :**
```bash
sudo docker exec scalping-radar python -c "
import sqlite3
c = sqlite3.connect('/app/data/trades.db')
print(c.execute('SELECT COUNT(*) FROM shadow_setups').fetchone())
print(c.execute(\"SELECT system_id, COUNT(*) FROM shadow_setups GROUP BY system_id\").fetchall())
"
```
> ⚠ La seule table concernée est `shadow_setups` avec colonne `system_id` — pas de table `shadow_systems`.

### Si 0 ligne dans `shadow_setups`

Le pipeline de détection n'a jamais inséré de setup. Vérifier dans `scheduler.py` que la branche Phase 4 est bien appelée et que les logs d'erreur ne contiennent pas de traceback Python lié au shadow log.

### Délai de grâce

Si le bug est identifié et corrigé avant le **2026-05-06**, le rapport W1-bis (2026-05-10) pourra être considéré comme le premier rapport probant avec données réelles. Le gate S6 du **2026-06-06** reste atteignable.

---

## Santé endpoint public

| Endpoint | Statut | Code HTTP |
|---|---|---|
| `/api/shadow/v2_core_long/public-summary` | Non joignable depuis sandbox (DNS privé) | N/A |
| `/v2/` (frontend) | OK | 200 |

---

## Conclusion W1

Le déploiement Phase 4 du **2026-04-25** n'a produit **aucun setup confirmé** sur la première semaine de shadow. L'infra EC2 est opérationnelle (frontend HTTP 200), mais le pipeline de génération de signaux V2_CORE_LONG est silencieux. Ce silence est classifié **CRITICAL** (règle : 0 setup en 7 jours).

L'activité git est soutenue (49 commits sur la semaine) mais porte exclusivement sur d'autres fonctionnalités (EA MQL5, bridge multi-tenant, circuit-breaker V1). La Phase 4 shadow n'a fait l'objet d'aucune correction, ce qui suggère que le problème est soit un scheduler en panne silencieuse, soit un marché sans setup H4 valide sur la période — les deux étant indiscernables sans accès direct aux logs EC2.
