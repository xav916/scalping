# Gate S6 — Décision Phase 5 (rappel pour user)

**Date :** 2026-06-06
**Statut :** DÉCISION REQUISE PAR USER
**Généré par :** agent remote (session automatique Gate S6)
**Sources :** rapports W2 + W4 + W5 · endpoint public `/api/shadow/v2_core_long/public-summary` · script `track_a_veto_counterfactual` · spec `2026-04-26-research-project-synthesis.md` §6

> **Note W1 et W3 :** Le rapport W1 (2026-05-03) est non probant (ancienne URL `duckdns.org`). Le rapport W3 (2026-05-17) n'a jamais été généré — les données de la semaine 3 ont été détruites lors de l'incident rsync le 2026-05-18. La baseline s'appuie sur W2 + W4 + W5.

---

## Résumé hebdo W1-W5 (cumul 6 semaines)

### Chronologie des événements majeurs

| Date | Événement | Impact |
|---|---|---|
| 2026-04-25 | Deploy Phase 4 shadow log | Démarrage |
| 2026-04-27 | Premier signal XAU détecté (J+2) | Pipeline OK |
| 2026-05-03 | W1 — URL incorrecte, données N/A | Non probant |
| 2026-05-10 | W2 — Première lecture probante | ✅ KPIs positifs sur n=3 |
| 2026-05-18 | **INCIDENT rsync --delete** | 💥 3 semaines de données détruites |
| 2026-05-19 | Restart pipeline, protection rsync déployée | Reconstruction J+0 |
| 2026-05-20 | Backups S3+EBS activés | Hardening infra |
| 2026-05-24 | W4 — J+5 post-restart, 2 setups SL | Non conclusif |
| 2026-05-31 | W5 PRÉ-GATE — J+12, 26 setups totaux | 🔴 WR=0%, PF=0.00 |
| 2026-06-06 | **Gate S6** (J+18 post-restart) | **Décision aujourd'hui** |

### Tableau synthèse par système — fil des semaines disponibles

| system_id | W2 n_résolu | W2 PF | W2 WR | W5 n_résolu | W5 PF | W5 WR | W5 PnL total | Statut gate |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| V2_CORE_LONG_XAUUSD_4H | 3 | **3.51** | **66.7%** | **10** | **0.00** | **0.0%** | −11.2% | 🔴 CRITIQUE |
| V2_CORE_LONG_XAGUSD_4H | 1† | 0.00† | 0%† | **6** | **0.00** | **0.0%** | −23.5% | 🔴 CRITIQUE |
| V2_WTI_OPTIMAL_WTIUSD_4H | 2 | 0.00 | 0% | **8** | **0.00** | **0.0%** | −36.2% | 🔴 CRITIQUE |
| V2_CORE_LONG_ETHUSD_1D | 1 | — | n/a | **2** | **0.00** | **0.0%** | −7.4% | 🔴 CRITIQUE |
| V2_WTI_OPTIMAL_XLK_1D | 0 | — | — | n/a | n/a | n/a | n/a | ⚠️ INCONNU |
| V2_TIGHT_LONG_XLI_1D | **0** | — | — | **0** | — | — | — | 🔴 SILENCIEUX (43j) |
| **PORTEFEUILLE TOTAL** | **~7** | — | — | **26** | **0.00** | **0.0%** | **−78.3%** | 🔴🔴 ALERTE |

† W2 : 1 seul SL résolu sur XAG — non significatif statistiquement.

**Signal statistique W5 :** P(WR=0 | n=26, p_true=0.45) ≈ 1.8×10⁻⁷ → ce n'est pas du bruit.

**Contexte régime marché (source V1 pair admission 2026-05-29) :**
- XAU/USD BUY : **PAUSED · −125.18% PnL/30 trades** → régime SELL sur l'or
- XAG/USD BUY : **PAUSED · −84.47%** → régime SELL sur l'argent
- V2_CORE_LONG est long-only → opère structurellement à contre-courant

---

## KPIs ULTIME (au jour du gate, 2026-06-06)

> **Méthode :** L'endpoint public `/api/shadow/v2_core_long/public-summary` retourne uniquement des systèmes V1_SHADOW (10 systèmes forex, comportement identique à W4). Les systèmes V2_CORE_LONG ne sont pas visibles dans la réponse publique. La DB EC2 n'est pas accessible depuis l'environnement sandbox. Les chiffres ci-dessous sont les meilleures estimations disponibles au J+18 post-restart.

| Métrique | Source | Valeur J+12 (W5) | Estimation J+18 (gate) |
|---|---|---|---|
| XAU n_résolu | W5 DB contrefactuel | 10 | ~13–17 (extrapolation ~0.6/jour) |
| XAU n_TP1 | W5 DB | 0 | 0–2 (tendance bearish persistante) |
| XAU WR% | W5 | 0.0% | 0–15% (incertain) |
| XAU PF | W5 | 0.00 | 0.00–0.15 (incertain) |
| XAU maxDD% | Non calculable via API | n/a | n/a |
| Portefeuille n_résolu total | W5 | 26 | ~32–38 estimé |
| Portefeuille WR | W5 | 0.0% | 0–10% |
| Infra EC2 | Endpoint public | HTTP 200 ✅ | Opérationnelle |
| V2 visible en API publique | Endpoint public | ❌ Non | Probablement ❌ |

> **Limite importante :** Sans accès direct à la DB EC2 au J+18, les chiffres ultime sont des estimations fondées sur les tendances W4→W5. L'utilisateur peut obtenir les valeurs exactes via `sqlite3 /opt/scalping/data/trades.db "SELECT system_id, COUNT(*), SUM(CASE WHEN outcome='TP1' THEN 1 ELSE 0 END) FROM shadow_setups WHERE system_id LIKE 'V2_%' AND created_at > '2026-05-19' GROUP BY system_id;"` sur EC2.

---

## Critères Phase 5 GO

Source : `docs/superpowers/specs/2026-04-26-research-project-synthesis.md`, section 6.

| Critère | Cible spec | Observé (J+12 W5) | Projection J+18 | OK ? |
|---|---|---|---|---|
| n_total XAU sur 6 sem | ≥ 50 | 10 résolus (post-restart) · ~13 comptant W2 pré-wipe | ~13–17 | ❌ ÉCHEC MASSIF |
| WR % | ≥ 45% | **0.0%** sur 26 setups × 4 paires | 0–15% | ❌ ÉCHEC CRITIQUE |
| PF live | ≥ 1.15 | **0.00** | ~0.00–0.15 | ❌ ÉCHEC CRITIQUE |
| maxDD% | < 30% | Non calculable (API ne remonte pas V2) | Non évaluable | ⚠️ N/A |
| Slippage observé | < 0.08% | Non applicable (pas de trades live, shadow seulement) | N/A | ⚠️ N/A |

**Déclencheurs STOP (spec §6) :**

| Condition STOP | Seuil | Observé | Déclenché ? |
|---|---|---|---|
| Setups < 30 sur 6 sem | < 30 | XAU : ~13–17 à J+18 | ⚠️ Oui (si compte post-restart) · Borderline (si compte depuis deploy) |
| PF live < 0.9 sur > 100 setups | < 0.9 ET n > 100 | 0.00 sur ~26–38 | ⚠️ PF déclenché, mais n < 100 → seuil formel non atteint |
| Drift macro évident | Qualitatif | 0 TP × 4 paires · XAU BUY V1 −125% PAUSED | 🔴 **OUI — confirmé par sources multiples** |

---

## Véto géopolitique (analyse contrefactuelle)

### Résultat script J+18 (2026-06-06)

```
python -m scripts.research.track_a_veto_counterfactual --db /opt/scalping/data/trades.db --no-write

Échantillon : 0 setups réconciliés
Confiance : DÉRISOIRE — DB non accessible depuis sandbox
```

**Cause :** La DB EC2 n'est pas montée dans l'environnement sandbox remote. Le script a tourné mais n'a pas pu ouvrir `/opt/scalping/data/trades.db`. Sample : **NON EXPLOITABLE**.

### Historique des verdicts contrefactuels (sources rapports hebdo)

| Date | n setups | WR% | PF | Verdict | Contexte |
|---|---:|---:|---:|---|---|
| 2026-05-09 | 0 | — | — | INSUFFISANT | J+14, trop tôt |
| 2026-05-16 (pré-wipe) | 8 | 37.5% | 0.46 | **🚨 VETO_WOULD_HURT** | Règle `iran_hormuz` retirait des gagnants |
| 2026-05-23 | 2 | 0.0% | 0.00 | Neutre (n dérisoire) | J+4 post-restart |
| 2026-05-30 | 26 | 0.0% | 0.00 | **Neutre — 0/26 setups filtrés** | J+11 post-restart |
| **2026-06-06** | **0** | — | — | **NON EXPLOITABLE (DB inaccessible sandbox)** | J+18 |

**Verdict consolidé :** Le veto géopolitique (GDELT + Polymarket) **n'aurait pas amélioré** les performances post-restart. 0/26 setups auraient été filtrés. La cause des pertes est le régime marché (trend bearish metals), pas un événement géopolitique filtrable. Le signal pré-wipe (VETO_WOULD_HURT sur n=8) était lié à la règle `iran_hormuz` momentanément active — cette règle n'est plus déclenchée. **Impact sur la décision gate : nul.** Le veto ne modifie pas la recommandation.

---

## Recommandation finale

### → **DÉLAI +6 SEMAINES** (Gate S8 : 2026-07-04)

**Motifs :**

1. **Volume insuffisant** : XAU n_résolu ~13–17 à J+18 vs 50 requis. Même en comptant les 3 setups pré-wipe de W2, le total ne dépasse pas ~20. L'incident rsync a rendu le critère de volume inatteignable au gate S6.

2. **Performance catastrophique, statistiquement non aléatoire** : WR=0%, PF=0.00 sur 26 setups × 4 paires différentes. P < 2×10⁻⁷ si edge réel à 45% WR. Ce n'est pas du bruit.

3. **Régime marché adverse confirmé** : La V1 pair admission (XAU BUY PAUSED −125.18%) et V2 shadow (WR=0%) convergent. V2_CORE_LONG est long-only et opère à contre-courant du régime actuel. C'est le risque documenté en spec §5 : *"Long-only — performe mal en régimes de baisse durables."*

4. **Trigger "drift macro évident" déclenché** (spec §6) : 0 TP × 4 paires sur 12j → condition STOP qualitative atteinte. Cependant, le seuil formel STOP (PF < 0.9 sur > 100 setups) n'est **pas** atteint (n~26-38 < 100). Le DÉLAI est donc préférable au STOP.

5. **Pas d'artefact technique détecté** : Aucun commit ne touche `shadow_setups` ou le scheduler V2 depuis le deploy initial. Le pipeline est stable. La sous-performance n'est pas causée par un bug de code — c'est le marché.

**Nuance critique :** Avant de conclure définitivement, il est recommandé d'éliminer un bug potentiel de réconciliation TP1 (W5 §8 recommandations) :

```bash
# Sur EC2 — vérifier tous les outcomes post-restart
sqlite3 /opt/scalping/data/trades.db \
  "SELECT outcome,
   SUM(CASE WHEN geopolitical_features_json IS NOT NULL THEN 1 ELSE 0 END) as with_geo,
   SUM(CASE WHEN geopolitical_features_json IS NULL THEN 1 ELSE 0 END) as without_geo
   FROM shadow_setups
   WHERE created_at > '2026-05-19'
   GROUP BY outcome;"
```

Si des TP1 existent sans `geopolitical_features_json` → recalculer WR sans filtre geo (WR réel pourrait être supérieur à 0%). Si 0 TP1 dans toute la table → WR réellement nul, régime marché confirmé.

---

Prochaines actions (DÉLAI) :
1. Vérifier manuellement le bug de réconciliation TP1 sur EC2 (priorité critique)
2. Continuer Phase 4 jusqu'au **gate S8 (~2026-07-04)**
3. Signal de retournement à surveiller : **repromotion XAU BUY en AUTO_EXEC dans V1 admission** = indicateur que le régime metals a retourné
4. Condition urgente avant mi-juin : ≥ 3 TP1 XAU sur la période 2026-06-06 → 2026-06-20 pour valider que WR=0% est conjoncturel et non structurel
5. Relancer une session agent W6–W11 (hebdomadaire) pour monitoring continu
6. Si le régime bearish persiste jusqu'au 2026-06-20 → probabilité élevée que gate S8 soit également DÉLAI ou STOP

---

### Si TOUS les critères GO étaient remplis : → **GO PHASE 5**

*(Non applicable au gate S6)*

Prochaines actions (rappel pour référence future) :
1. Configurer auto-exec V2_CORE_LONG XAU H4 sur compte démo Pepperstone
2. Désactiver l'auto-exec V1 actuel (les 2 ne doivent pas tourner ensemble)
3. Sizing : 0.5% risk/trade, capital démo 5-10k€
4. Phase 5 dure 2-3 mois minimum avant considérer Phase 6 (live réel)

### Si invalide : → **STOP / PIVOT**

*(Trigger formel n > 100 non atteint — STOP prématuré à ce stade)*

Prochaines actions si décision STOP est prise malgré tout :
1. Bascule Observatoire SaaS-only (le projet conserve sa valeur dashboard/alertes/signal)
2. Post-mortem dans `docs/superpowers/journal/2026-06-XX-phase4-post-mortem.md`
3. Considérer pivot vers Track C TF, ML proper, ou futures équités

---

## Notes pour l'user

**La décision est ENTIÈREMENT MANUELLE. L'agent recommande DÉLAI mais le user décide.**

Si tu reviens sur ce projet après la session de gate S6, lis :
- `docs/PHASE4_OPERATIONS_GUIDE.md` pour le contexte opérationnel
- `docs/superpowers/specs/2026-04-26-research-project-synthesis.md` pour le contexte recherche

**Limites de ce rapport :**
- KPIs J+18 sont des estimations (DB EC2 non accessible depuis sandbox)
- Le script contrefactuel a retourné 0 setups (DB inaccessible) — les verdicts contrefactuels proviennent des rapports auto hebdo W4-W5
- Le rapport W3 n'existe pas (données détruites par l'incident rsync)
- L'endpoint public retourne uniquement V1_SHADOW, les V2 ne sont pas visibles sans accès DB direct

**Signal clé à surveiller :** Repromotion XAU/USD BUY de PAUSED à AUTO_EXEC dans le pair admission controller = signal que le régime metals a retourné et que V2_CORE_LONG retrouve un contexte favorable.
