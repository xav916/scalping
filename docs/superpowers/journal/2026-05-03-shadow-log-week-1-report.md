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

> **Réponse brute API :** `{"systems":[]}` — tableau vide, aucun système enregistré.

---

## Diagnostic global

- **INFRA :** PARTIAL OK — frontend `/v2/` répond HTTP 200, mais le shadow log ne retourne aucun système.
- **DATA FEED :** CRITICAL — `{"systems":[]}` après 7 jours de démo. Aucun setup XAU ni XAG n'a été détecté ou enregistré dans V2_CORE_LONG.
- **PERFORMANCE :** NON ÉVALUABLE — aucune donnée de trade disponible.

### Interprétation de `{"systems":[]}`

Trois causes possibles, par ordre de probabilité :

1. **Enregistrement des systèmes absent** — les systèmes `V2_CORE_LONG_XAUUSD_4H` et `V2_CORE_LONG_XAGUSD_4H` n'ont jamais été inscrits dans la table `shadow_systems` (migration ou seed manquant).
2. **Scheduler H4 en panne** — le job cron/celery qui scanne les setups ne tourne pas (EC2 reboot ? Celery worker mort ? Variable d'env manquante).
3. **Data feed Twelve Data HS** — les bougies H4 ne sont pas récupérées (quota épuisé, clé API invalide, ou paire non couverte par le plan Grow).

---

## Activité git

```
git log --oneline --since='2026-04-26'
(aucun commit retourné)
```

**0 commit** depuis la fin de la session de déploiement Phase 4 (2026-04-25).
Aucune correction d'urgence n'a été poussée, aucune config n'a été modifiée.

---

## Recommandations

### Priorité CRITICAL — À traiter avant tout

1. **Vérifier la table `shadow_systems`** (ou équivalent) :
   ```sql
   SELECT * FROM shadow_systems WHERE log_id = 'V2_CORE_LONG';
   ```
   Si vide → lancer le seed / la migration de création des deux systèmes.

2. **Vérifier le worker scheduler** sur EC2 :
   ```bash
   systemctl status celery   # ou le nom du service équivalent
   journalctl -u celery --since "2026-04-25" | tail -50
   ```

3. **Vérifier la clé Twelve Data** :
   ```bash
   curl "https://api.twelvedata.com/time_series?symbol=XAU/USD&interval=4h&apikey=$TWELVE_DATA_API_KEY&outputsize=1"
   ```
   Quota plan Grow : 5 000 req/jour — surveiller si épuisement en début de semaine.

4. **Vérifier les logs FastAPI** pour toute erreur 500 sur les routes shadow :
   ```bash
   grep -i "shadow\|v2_core" /var/log/nginx/access.log | tail -30
   ```

### Si systèmes absents de la DB

Réinsérer manuellement ou via le script d'initialisation Phase 4 les deux entrées :
- `V2_CORE_LONG_XAUUSD_4H`
- `V2_CORE_LONG_XAGUSD_4H`

### Délai de grâce

Si le bug est identifié et corrigé avant le **2026-05-06**, le rapport W1 bis (2026-05-10) pourra être considéré comme le premier rapport probant avec données réelles.

---

## Détails (extraits)

### Monthly returns observés

Aucune donnée disponible (`monthly_returns` absent — `systems` vide).

### Equity curve highlights

Aucune donnée disponible (`equity_curve` absent — `systems` vide).

### Santé endpoint public

| Endpoint | Statut | Code HTTP |
|---|---|---|
| `/api/shadow/v2_core_long/public-summary` | Répond, JSON valide, `systems` vide | 200 |
| `/v2/` (frontend) | OK | 200 |

---

## Conclusion W1

Le déploiement Phase 4 du **2026-04-25** n'a produit **aucun setup détecté** sur la première semaine de shadow. L'infra réseau est saine (frontend 200, API accessible), mais le pipeline de génération de signaux V2_CORE_LONG est silencieux. Ce silence est classifié **CRITICAL** selon les règles de monitoring définies (0 setup en 7 jours).

Le gate S6 prévu le **2026-06-06** reste atteignable si le bug est corrigé cette semaine et que les 4 prochaines semaines de données s'accumulent normalement.
