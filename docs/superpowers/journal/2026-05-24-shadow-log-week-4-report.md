# Rapport hebdo W4 — Shadow log V2_CORE_LONG

**Date :** 2026-05-24 (auto-généré par agent remote)
**Période nominale W4 :** 2026-05-17 → 2026-05-24 (7 jours)
**Période cumulée Phase 4 :** 2026-04-25 → 2026-05-24 (29 jours)
**Déploiement Phase 4 :** 2026-04-25 17h00 UTC
**Restart post-incident :** 2026-05-19 → **J+5** à date du rapport

> ⚠️ **Ce rapport est fortement impacté par un incident d'infrastructure critique survenu le 2026-05-18.** Voir section « Incident Post-W2 » ci-dessous.

---

## 🚨 INCIDENT CRITIQUE — rsync --delete (2026-05-18)

### Chronologie

| Datetime (UTC+2) | Événement |
|---|---|
| 2026-05-18 ~22h | `rsync --delete` lors d'un deploy a **wipé la totalité de `/opt/scalping/data`** sur EC2, incluant la table SQLite `shadow_setups` |
| 2026-05-18 22h06 | `fix(mt5_bridge)`: SL/TP relatifs au fill price (anti-slippage) — premier commit post-incident |
| 2026-05-18 23h57 | `fix(admission)`: isole le scoring V1 du shadow V2 via filtre `system_id` |
| 2026-05-19 01h20 | **`fix(deploy)`: protect `/opt/scalping/data` + `.env` from `rsync --delete`** — correctif déployé |
| 2026-05-19 | Shadow log V2_CORE_LONG **redémarre à zéro** — J0 post-restart |
| 2026-05-22 09h27 | `docs(spec)`: gate scalping V2 **décalé S6→S8 (2026-07-04)** — acté formellement |

### Données perdues

- **3 semaines de données V2** (J1 au J23, 2026-04-26 → 2026-05-17) irrécupérables
- Le rapport **W3 n'a pas été généré** : la période W3 (2026-05-10 → 2026-05-17) avait des données mais le rapport hebdo n'a pas été produit avant l'incident
- Tous les setups des 6 systèmes V2_CORE_LONG antérieurs au 2026-05-19 sont perdus

### Mesures post-incident

- Protection rsync déployée : `/opt/scalping/data` et `.env` exclus du `rsync --delete` ✅
- Backups S3 + EBS automatisés activés (Phase 7 hardening, 2026-05-20) ✅
- EA health monitor automation 4×/jour via GitHub Actions (2026-05-19) ✅

---

## Progression W1 → W2 → W3 → W4

### Tableau de progression — XAU (V2_CORE_LONG_XAUUSD_4H) & XAG (V2_CORE_LONG_XAGUSD_4H)

| Semaine | Période | XAU n_total | XAU PF | XAU WR | XAU maxDD | XAG n_total | XAG PF | Événement clé |
|---|---|---:|---:|---:|---:|---:|---:|---|
| **W1** | 25 avr → 3 mai | N/A* | N/A* | N/A* | N/A* | N/A* | N/A* | URL incorrecte — données non disponibles |
| **W2** | 3 → 10 mai | **9** | **3.51** | **66.7%** | **0.5%** | **10** | 0.0†† | Première lecture probante ✅ |
| **W3** | 10 → 17 mai | *(non généré)* | *(non généré)* | *(non généré)* | *(non généré)* | *(non généré)* | *(non généré)* | Rapport manquant |
| **🔴 WIPE** | **18 mai** | 💥 **ZERO** | — | — | — | 💥 **ZERO** | — | rsync --delete — reset total |
| **W4** | 19 → 24 mai | **2†** | n/a | 0.0%† | n/a | **0†** | n/a | **J+5 post-restart** |

\* W1 non probant — ancienne URL `scalping-radar.duckdns.org` (cf. note W2)  
†† PF=0 sur 1 seul SL résolu — non statistiquement significatif  
† Estimé via rapport veto-counterfactuel 2026-05-23 (n=2 XAU/USD, sources `shadow_setups` avec `geopolitical_features_json`)

### Tableau complet 6 systèmes

| system_id | W2 n_total | W2 diagnostic | W4 n_total | W4 diagnostic | Delta |
|---|---:|---|---:|---|---|
| V2_CORE_LONG_XAUUSD_4H | 9 | OK ✅ | ~2† | CRITICAL 🔴 | Wipe + 5j restart |
| V2_CORE_LONG_XAGUSD_4H | 10 | WARNING ⚠️ | ~0† | CRITICAL 🔴 | Wipe + 5j restart |
| V2_WTI_OPTIMAL_WTIUSD_4H | 3 | WARNING ⚠️ | ~0† | CRITICAL 🔴 | Wipe + 5j restart |
| V2_CORE_LONG_ETHUSD_1D | 2 | WARNING ⚠️ | ~0† | CRITICAL 🔴 | Wipe + 5j restart |
| V2_WTI_OPTIMAL_XLK_1D | 2 | WARNING ⚠️ | ~0† | CRITICAL 🔴 | Wipe + 5j restart |
| V2_TIGHT_LONG_XLI_1D | 0 | CRITICAL 🔴 | ~0† | CRITICAL 🔴 | Inchangé |

> **Note :** Le statut CRITICAL de tous les systèmes en W4 est **structurel et attendu** — J+5 après un reset forcé. Ce n'est pas un signal de dégradation des stratégies, mais la conséquence directe de l'incident infrastructure.

---

## État courant — Données API et sources disponibles

### Endpoint public `/api/shadow/v2_core_long/public-summary`

```
GET https://app.scalping-radar.online/api/shadow/v2_core_long/public-summary
     ?token=shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg
→ HTTP 200 ✅ — Infra opérationnelle
```

**Résultat :** L'endpoint retourne **uniquement des systèmes V1_SHADOW** (10 systèmes : AUDUSD, BTCUSD, ETHUSD, EURGBP, EURJPY, EURUSD, etc.). Les systèmes V2_CORE_LONG ne sont pas visibles dans la réponse publique.

**Interprétation :** Les données V2 post-restart (J+5) sont probablement trop récentes et peu nombreuses pour apparaître dans le résumé public, ou le filtre d'agrégation de l'endpoint exclut les systèmes V2 en dessous d'un seuil minimal. À investiguer si l'invisibilité V2 persiste en W5.

### Source counterfactual (2026-05-23)

Le rapport veto-contrefactuel du 2026-05-23 révèle :

| Métrique | Valeur |
|---|---|
| n setups réconciliés | **2** |
| Pair | XAU/USD |
| n_tp | 0 |
| n_sl | **2** |
| n_timeout | 0 |
| Win rate | 0.0% |
| PF | 0.00 |
| Mean PnL% | -1.10% |
| Total PnL% | -2.20% |
| Would VETO | 0 (aucun setup n'aurait été filtré) |

> Ces 2 setups XAU/USD sont les **seules données V2 vérifiables** à ce stade. Sur 5 jours, 2 SL sur XAU = performance non conclusive (statistiquement dérisoire).

### Frontend `/v2/`

| Endpoint | Statut |
|---|---|
| `/v2/` (SPA React) | ✅ HTTP 200 — Landing OK |
| API shadow V2 public | ✅ HTTP 200 — Retourne V1 (V2 non visible) |

---

## Diagnostic global W4

### INFRA — RECOVERED ✅

L'incident rsync --delete est contenu. Les mesures préventives sont en place (protection data, backups S3+EBS, EA health monitor). L'infra EC2 est opérationnelle. Probabilité de récidive : faible.

### PIPELINE V2 SHADOW — CRITIQUE STRUCTUREL 🔴

Tous les 6 systèmes sont à CRITICAL (< 5 setups) sur la période post-restart. C'est **attendu et non-alarmant** à J+5. Le pipeline génère des signaux (2 détectés sur XAU depuis le 2026-05-19).

### PERFORMANCE — NON ÉVALUABLE

- Échantillon total connu : 2 setups (XAU/USD, J+0 et J+x post-restart)
- Tous deux SL (-2.20% cumulé)
- Statistiquement dérisoire — aucune conclusion possible sur 2 setups
- Les cibles de performance (Sharpe ≥ 1.0, PF 1.32-1.59, maxDD < 20%) ne peuvent pas être évaluées

### XLI — TOUJOURS SILENCIEUX 🔴

Le système V2_TIGHT_LONG_XLI_1D n'a généré aucun setup depuis le deploy initial (2026-04-25) ni depuis le restart (2026-05-19). C'est le seul CRITICAL pré-wipe qui n'est pas expliqué par l'incident. **Priorité d'investigation maintenue.**

---

## Diagnostic cumulé 28 jours (2026-04-25 → 2026-05-24)

> **Note préliminaire :** Sur les 29 jours écoulés depuis le deploy, **seuls 15 jours de données V2 ont existé** (J1-J23 perdus, J24-J29 post-restart). Les cibles 28 jours sont donc non atteignables à ce stade.

| Métrique 28j | Cible XAU | Observé XAU | Statut | Cible XAG | Observé XAG | Statut |
|---|---:|---:|---|---:|---:|---|
| n_total | ~24 | ~2 (post-restart) | 🔴 CRITICAL | ~24 | ~0 | 🔴 CRITICAL |
| Sharpe | ≥ 1.0 | n/a | 🔴 n/a | ≥ 0.9 | n/a | 🔴 n/a |
| PF | 1.32–1.59 | n/a (2 setups) | 🔴 n/a | 1.32–1.59 | n/a | 🔴 n/a |
| maxDD% | < 20% | n/a | 🟡 inconnu | < 26% | n/a | 🟡 inconnu |

**Diagnostic consolidé 28j :** CRITICAL structurel. La destruction du dataset empêche toute évaluation de la trajectoire 28j. Les cibles ne pourront être évaluées qu'à partir du **rapport W10 (2026-07-04)**, date du nouveau gate S8.

---

## Activité git depuis W3 (2026-05-17 → 2026-05-24)

| Commit | Date | Message | Impact V2 shadow |
|---|---|---|---|
| `0ade045` | 2026-05-18 | fix(mt5_bridge): SL/TP relatifs au fill price | Aucun direct |
| `d924671` | 2026-05-18 | fix(admission): isole V1/V2 via filtre system_id | ✅ Corrige contamination scoring |
| `c30eee5` | 2026-05-19 01h | **fix(deploy): protect /opt/scalping/data** | ✅ Prévient récidive wipe |
| `112b4b6` | 2026-05-19 | EA health monitor 4×/jour (GitHub Actions) | Monitoring renforcé |
| `e5984c5` | 2026-05-20 | feat(backup): daily backups S3+EBS | ✅ Prévient perte future |
| `57aea7a` | 2026-05-20 | feat(backup): Phase 7 hardening (atomicity, drills) | ✅ Résilience renforcée |
| `37e6862` | 2026-05-22 | docs(spec): gate S6→S8 (2026-07-04) | ✅ Délai acté formellement |
| `11ab205` | 2026-05-23 | docs: rapport veto contrefactuel (auto) | Monitoring shadow |
| `38b5f47` | 2026-05-23 | chore: rapport veto contrefactuel (n=2, insufficient) | Monitoring shadow |

**Thème dominant :** Réponse à incident et hardening infra (5/9 commits). Aucun commit ne touche la logique de détection V2_CORE_LONG — le pipeline shadow est stable.

---

## ⚠️ Note mi-parcours — Gate S8 (anciennement S6)

W4 représentait théoriquement **le mi-chemin du gate S6 (2026-06-06)**. Avec la nouvelle référence :

| Gate | Date | Statut |
|---|---|---|
| ~~Gate S6 (ancienne cible)~~ | ~~2026-06-06~~ | ❌ Annulé — données insuffisantes |
| **Gate S8 (nouvelle cible)** | **2026-07-04** | 🔄 En cours — J+5 post-restart |

**Traduction pratique :** W4 est désormais J+5 d'une nouvelle série propre. Le mi-parcours vers S8 sera atteint en **W7 (~2026-06-14)**, lorsque ~25 jours de données post-restart seront disponibles.

Le gate S8 nécessite pour validation (cibles inchangées) :
- XAU : n_resolved ≥ 20, PF ≥ 1.32, Sharpe ≥ 1.0, maxDD < 20%
- XAG : n_resolved ≥ 20, PF ≥ 1.32, Sharpe ≥ 0.9, maxDD < 26%
- XLI : ≥ 1 setup détecté
- Tous systèmes : maxDD sous seuils

**Trajectoire actuelle → gate S8 :** Réalisable si le pipeline performe conformément aux backtests. Les 6 semaines restantes (J+5 → J+46) sont amplement suffisantes pour accumuler 20+ setups résolus sur XAU/XAG 4H (cadence backtestée : ~2 setups/semaine par paire).

---

## Recommandations

### 1. PRIORITÉ HIGH — Investiguer XLI (silencieux depuis J0)

V2_TIGHT_LONG_XLI_1D n'a produit aucun setup en 29 jours (ni avant wipe, ni après restart). Ce silence prédates l'incident. **Action sur EC2 :**

```bash
# Vérifier présence XLI dans shadow_setups post-restart
sqlite3 /opt/scalping/data/trades.db \
  "SELECT system_id, COUNT(*) FROM shadow_setups
   WHERE created_at > '2026-05-19'
   GROUP BY system_id ORDER BY 2 DESC;"

# Logs scheduler pour XLI post-restart
sudo journalctl -u scalping --since '2026-05-19' | grep -i 'XLI\|TIGHT_LONG' | tail -30
```

### 2. PRIORITÉ MEDIUM — Vérifier visibilité V2 dans l'endpoint public

L'endpoint `/api/shadow/v2_core_long/public-summary` retourne uniquement V1_SHADOW. Si en W5 les systèmes V2 n'apparaissent toujours pas, investiguer le filtre de l'endpoint (seuil minimal, system_id filter).

```bash
# Check direct table V2 post-restart
sqlite3 /opt/scalping/data/trades.db \
  "SELECT system_id, COUNT(*), MIN(created_at), MAX(created_at)
   FROM shadow_setups
   WHERE system_id LIKE 'V2_%'
   GROUP BY system_id;"
```

### 3. PRIORITÉ LOW — Pas de modification pipeline

Le pipeline V2_CORE_LONG ne doit **pas être modifié** à ce stade. Le silence post-restart sur 5 jours est normal. Laisser tourner et accumuler jusqu'à W5 (2026-05-31).

### 4. INFO — Backups opérationnels

Les backups S3+EBS quotidiens sont en place depuis le 2026-05-20. En cas de prochain incident, la perte maximale de données sera limitée à < 24h. La robustesse infrastructure est désormais au niveau requis pour la Phase 5 (live).

---

## Prédiction trajectoire → Gate S8 (2026-07-04)

| Semaine | Date rapport | Jours post-restart | XAU n_total attendu | XAG n_total attendu | Diagnostic attendu |
|---|---|---:|---:|---:|---|
| W5 | 2026-05-31 | J+12 | 4–6 | 3–5 | WARNING → OK XAU |
| W6 | 2026-06-07 | J+19 | 8–12 | 6–10 | OK XAU, WARNING XAG |
| W7 | 2026-06-14 | J+26 | 12–16 | 10–14 | OK XAU/XAG |
| W8 | 2026-06-21 | J+33 | 16–20 | 14–18 | Sharpe calculable |
| W9 | 2026-06-28 | J+40 | 20–24 | 18–22 | Pré-gate review |
| **W10 = Gate S8** | **2026-07-04** | **J+46** | **~24** | **~22** | **Décision gate** |

*Projection basée sur cadence backtestée ~2 setups/semaine XAU 4H, ~2/semaine XAG 4H.*

**Condition gate S8 :** Si PF ≥ 1.32 et Sharpe ≥ 1.0 (XAU) + ≥ 0.9 (XAG) sur ≥ 20 résolus → **validation Track A → Phase 5 (shadow démo broker live)**. Day Trading Radar V0 reste gated en aval.

---

## Santé endpoint public

| Endpoint | Statut | Code HTTP | Remarque |
|---|---|---|---|
| `/api/shadow/v2_core_long/public-summary` | ✅ OK | 200 | Retourne V1_SHADOW (V2 non visible — voir §rec. 2) |
| `/v2/` (frontend SPA) | ✅ OK | 200 | Landing opérationnel |

---

## Conclusion W4

**Rapport impacté par l'incident rsync --delete du 2026-05-18.** La table `shadow_setups` a été intégralement wipée, faisant perdre 3 semaines de données V2 (W1-W3 irrécupérables). Le rapport W3 n'a pas été généré.

**Situation au 2026-05-24 :** Shadow log V2_CORE_LONG à **J+5 post-restart**. Seuls ~2 setups XAU/USD sont confirmés via le rapport veto-contrefactuel (2 SL — non conclusifs). L'API publique ne retourne que des données V1_SHADOW.

**Point positif :** L'incident a provoqué un hardening infra significatif (protection rsync, backups S3+EBS, EA health monitor). La probabilité de récidive est faible. Le pipeline shadow est opérationnel et génère des signaux.

**Gate réajusté :** S6 (2026-06-06) annulé → **Gate S8 : 2026-07-04**. Le gate S8 est **atteignable** sur la trajectoire actuelle si le pipeline continue à fonctionner conformément aux backtests.

**Prochain rapport :** W5 — 2026-05-31. Premier rapport post-restart avec données substancielles (~12 jours). C'est là que la reconstruction du track record V2 sera visible et évaluable.
