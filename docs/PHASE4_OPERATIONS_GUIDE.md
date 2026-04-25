# Phase 4 Shadow Log — Guide opérationnel

Si tu reviens sur ce projet après plusieurs jours/semaines et que tu te demandes "c'est quoi ce truc shadow log et où en est-on ?", ce doc te remet en route en 5 min.

**Date de création :** 2026-04-26 (~03h Paris, fin de la session de recherche intensive)
**Auteur :** session collaborative humain + assistant Claude Opus 4.7

---

## 1. C'est quoi Phase 4 ?

Le projet Scalping Radar est passé en **mode recherche structurée** le 2026-04-25. Après 31 expériences en 1 journée, on a identifié un système de trading rentable sur backtest 6 ans cross-régime :

**V2_CORE_LONG sur XAU H4 + XAG H4** (or et argent en bougies 4h)
- 3 patterns BUY only : `momentum_up`, `engulfing_bullish`, `breakout_up`
- Sharpe 1.59 sur 24 mois (top 10% retail)
- PF 1.32-1.59 selon période, validé sur 3 régimes (COVID 2020, bear 2022, bull 2024-26)

**Phase 4 = observation live** de ce système sans auto-exec. On loggue les setups détectés en temps réel pour vérifier que le backtest se confirme avec les vrais prix de marché et la latence d'exécution.

Si Phase 4 valide → Phase 5 (auto-exec démo) → Phase 6 (live réel).
Si Phase 4 invalide → bascule vers Observatoire SaaS-only.

## 2. Où voir l'état du système

### Frontend (auth cookie session, login user)

- `https://scalping-radar.duckdns.org/v2/shadow-log` — **KPIs live en temps réel**
  - Setups détectés, Sharpe observed, PF, maxDD, equity curve, monthly returns
  - Compare aux cibles backtest (Sharpe 1.59, PF 1.32-1.59)
  - Filtres + export CSV
- `https://scalping-radar.duckdns.org/v2/supports` — **Référence statique**
  - Tout ce qu'on sait sur XAU et XAG (caractéristiques, drivers, régimes)
  - 3 patterns retenus + 7 tentatives rejetées
  - 6 limitations connues
  - Roadmap Phase 4-6

### Backend API (auth cookie OU token)

| Endpoint | Auth | Usage |
|---|---|---|
| `/api/shadow/v2_core_long/setups` | Cookie | Liste paginée setups |
| `/api/shadow/v2_core_long/setups.csv` | Cookie | Download CSV |
| `/api/shadow/v2_core_long/summary` | Cookie | KPIs avancés |
| `/api/shadow/v2_core_long/public-summary?token=XYZ` | Token | KPIs avancés (pour agents remote) |

**Token public-summary :** `shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg`
- Hash SHA256 dans `backend/app.py` (constante `SHADOW_PUBLIC_TOKEN_HASH`)
- Token clair dans : ce doc + config des routines remote (claude.ai/code/routines/)
- Pour révoquer : générer un nouveau token, mettre à jour le hash, redéployer

```bash
# Générer un nouveau token
python -c "import secrets; print('shdw_'+secrets.token_urlsafe(24))"

# Hasher le nouveau token
python -c "import hashlib; print(hashlib.sha256(b'NEW_TOKEN').hexdigest())"
```

## 3. Architecture technique en 1 schéma

```
EC2 prod (scalping.service)
│
├─ Scheduler (apscheduler, cycles 5 min)
│  │
│  ├─ Cycle V1 (existant, scoring + auto-exec démo)
│  │   inchangé par Phase 4
│  │
│  └─ Hook Phase 4 (try/except non-bloquant)
│      ├─ aggregate_to_h4(h1_candles)
│      ├─ detect_patterns + filter_v2_core_long
│      └─ persist dans `shadow_setups` (UNIQUE par system_id × bar_timestamp)
│
├─ cockpit_broadcast_cycle (toutes les ~5 min)
│  └─ Hook reconciliation auto (toutes les 12 ticks ≈ 60 min)
│      └─ reconcile_pending_setups : fetch 5min Twelve Data → simulate forward → UPDATE outcome
│
└─ DB shadow_setups (dans trades.db)
   ├─ system_id : V2_CORE_LONG_XAUUSD_4H | V2_CORE_LONG_XAGUSD_4H
   ├─ bar_timestamp, entry_price, stop_loss, take_profit_1, risk_pct
   ├─ outcome : NULL (pending) | TP1 | SL | TIMEOUT
   └─ pnl_eur (sizing virtuel 10k€ × 0.5% risk = 50€ max loss/trade)
```

**Une SEULE table** `shadow_setups`. Pas de table séparée par système. Le `system_id` dans la colonne fait office de discriminateur.

## 4. Code key files

| Fichier | Rôle |
|---|---|
| `backend/services/shadow_v2_core_long.py` | Module principal : run_shadow_log, persist, list, summary |
| `backend/services/shadow_reconciliation.py` | Job reconcile pending setups |
| `backend/services/scheduler.py` (+12 lignes) | Hook shadow + reconciliation |
| `backend/services/macro_data.py` | Fetch + cache features macro (utilisé par snapshot des setups) |
| `backend/app.py` (4 endpoints shadow) | API REST |
| `frontend-react/src/pages/ShadowLogPage.tsx` | UI live KPIs |
| `frontend-react/src/pages/SupportsPage.tsx` | UI référence statique |
| `scripts/research/track_a_backtest.py` | Re-runner backtest local si besoin |
| `scripts/research/risk_metrics.py` | Sharpe, Calmar, maxDD calculations |

**Tests :** `backend/tests/test_shadow_*.py` + `test_macro_data.py` + `test_risk_metrics.py` + `test_phase4_e2e.py` = **43 tests passent en 1.6s**.

## 5. Routines hebdomadaires programmés

| Run | Date Paris | Trigger ID | Lit les rapports précédents |
|---|---|---|---|
| W1 | 2026-05-03 09:00 | `trig_011q56h7fvjzMXJmyFScUuCL` | aucun (1er rapport) |
| W2 | 2026-05-10 09:00 | `trig_0141MLnzHHwtooW9DPPgi7uW` | W1 |
| W3 | 2026-05-17 09:00 | `trig_01P4AurEvssEAZnbqd3SjFdS` | W1, W2 |
| W4 | 2026-05-24 09:00 | `trig_01G5CrP9xfqTuneVQ2HxNqwM` | W1-W3 (mi-chemin gate) |
| W5 | 2026-05-31 09:00 | `trig_014CCcBCyNahwxnDySpUpMjy` | W1-W4 (pré-gate, assessment final) |

Chaque routine :
1. Fetch `/api/shadow/v2_core_long/public-summary` avec token
2. Lit les rapports précédents pour comparer la progression
3. Écrit `docs/superpowers/journal/2026-05-XX-shadow-log-week-N-report.md`
4. Commit + push automatique sur main

**Gate S6 = 2026-06-06.** Décision finale GO Phase 5 / DÉLAI / STOP basée sur les critères du white paper section 6.

## 6. Critères de migration vers Phase 5 (auto-exec démo)

À évaluer manuellement le 2026-06-06 (un agent te rappellera) :

| Sortie | Condition | Décision |
|---|---|---|
| **GO Phase 5** | ≥50 setups XAU sur 6 sem ET WR ≥45% ET PF live ≥1.15 ET maxDD <30% ET slippage <0.08% | Activer auto-exec V2_CORE_LONG XAU H4 sur démo Pepperstone |
| **Délai +6 sem** | Setups corrects mais PF entre 1.0 et 1.15 | Étendre Phase 4 |
| **Stop / pivot** | Setups <30 sur 6 sem OU PF live <0.9 OU drift macro évident | Édition shadow log infirme le backtest. Pivot Observatoire SaaS-only |

## 7. Si quelque chose casse

### Symptôme : 0 setup en > 5 jours

```bash
# SSH dans EC2 (ssh-key dans le repo)
ssh -i scalping-key.pem ec2-user@100.103.107.75

# Check service running
sudo systemctl status scalping

# Check logs récents
sudo journalctl -u scalping --since "1 hour ago" | grep -i "shadow\|error" | tail -50

# Check DB (depuis EC2)
sudo docker exec scalping-radar python -c "
import sqlite3
c = sqlite3.connect('/app/data/trades.db')
print(c.execute('SELECT COUNT(*) FROM shadow_setups').fetchone())
print(c.execute('SELECT system_id, COUNT(*) FROM shadow_setups GROUP BY system_id').fetchall())
"

# Check Twelve Data
sudo docker exec scalping-radar python -c "
import asyncio
from backend.services.price_service import fetch_candles
c, _ = asyncio.run(fetch_candles('XAU/USD', interval='1h', outputsize=10))
print(f'fetched {len(c)} candles')
"
```

### Symptôme : endpoint public-summary retourne 403

Le token a peut-être été régénéré et le hash mis à jour sans que le routine soit synchronisé. Updater les routines (5 routines : W1-W5) avec le nouveau token via `RemoteTrigger` action="update".

### Symptôme : agent remote échoue

Voir `https://claude.ai/code/routines/<trigger_id>` pour les logs d'exécution.

## 8. Reprendre la recherche après le gate S6

Si Phase 4 valide ET tu veux continuer Phase 5 :
1. Lire le rapport W5 (2026-05-31) avec assessment GO/DELAI/STOP
2. Si GO : nouvelle session de recherche pour adapter le bridge MT5 à V2_CORE_LONG XAU H4 (auto-exec sur démo Pepperstone)
3. Critères stricts pour Phase 6 (live) après 2-3 mois de Phase 5 : Sharpe live > 1.0, drawdown < 30%, ≥100 trades

Si Phase 4 invalide :
1. Bascule Observatoire SaaS-only (le projet conserve sa valeur signal/dashboard sans prétention edge)
2. Documenter le post-mortem comme valeur publique
3. Considérer pivots : Track C TF systématique, ML proper avec features avancées, futures équités ES/NQ

## 9. Documentation associée

- `docs/superpowers/specs/2026-04-25-research-portfolio-master.md` — pivot recherche
- `docs/superpowers/specs/2026-04-25-phase4-shadow-log-spec.md` — spec implémentation Phase 4
- `docs/superpowers/specs/2026-04-26-research-project-synthesis.md` — **white paper master** (à lire en priorité si tu veux le contexte complet)
- `docs/superpowers/specs/2026-04-26-validation-checklist.md` — checklist état système
- `docs/superpowers/journal/INDEX.md` — index des 31 expériences
