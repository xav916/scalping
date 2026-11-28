# 2026-11-28 — Track A × veto contrefactuel (auto)

**Sample :** N/A (endpoint indisponible)
**Verdict :** N/A

---

> ⚠️ **ALERTE — 2 semaines consécutives d'indisponibilité**
> L'endpoint `/api/shadow/v2_core_long/counterfactual` est inaccessible pour la **2ème semaine consécutive** (semaines du 2026-11-21 et 2026-11-28).
> **Action requise immédiatement** : renouveler le token d'accès shadow dans la configuration de la tâche planifiée.

## Détail de l'erreur

- **URL** : `https://app.scalping-radar.online/api/shadow/v2_core_long/counterfactual`
- **HTTP code** : 403
- **Réponse** : `{"detail":"invalid token"}`
- **Cause probable** : token d'accès shadow refusé par l'API (expiré, révoqué ou mauvais environnement)

## Historique des pannes

| Date | Statut |
|---|---|
| 2026-11-21 | ❌ Endpoint indisponible (HTTP 403) — semaine 1 |
| **2026-11-28** | ❌ **Endpoint indisponible (HTTP 403) — semaine 2** |

## Contexte

L'endpoint `/api/shadow/v2_core_long/counterfactual` (commit 6eb39c6 du 2026-05-08) renvoie normalement le rapport hebdomadaire d'analyse contrefactuelle Track A × veto géopolitique.

Ce rapport est automatiquement généré à partir de la table `shadow_setups` (colonne `geopolitical_features_json` peuplée depuis le commit 3ac0d70). Les setups antérieurs au commit 3ac0d70 ont la colonne NULL et sont exclus de l'analyse.

## Action requise

La **règle de monitoring** prévoit une alerte explicite après 2 semaines consécutives d'indisponibilité. Ce seuil est atteint.

Étapes suggérées :
1. Se connecter au backend et vérifier que l'endpoint est toujours déployé
2. Renouveler ou corriger le token `shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg` dans la configuration de la tâche planifiée
3. Tester manuellement avec le nouveau token depuis la configuration de la tâche planifiée

---

*Rapport auto-généré — collecte du 2026-11-28 (2ème semaine consécutive en échec)*
