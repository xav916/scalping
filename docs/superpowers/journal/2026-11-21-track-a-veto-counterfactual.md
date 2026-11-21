# 2026-11-21 — Track A × veto contrefactuel (auto)

**Sample :** N/A (endpoint indisponible)
**Verdict :** N/A

---

> ⚠️ **Endpoint indisponible** — rapport de substitution (traçabilité automatique)

## Détail de l'erreur

- **URL** : `https://app.scalping-radar.online/api/shadow/v2_core_long/counterfactual`
- **HTTP code** : 403
- **Réponse** : `{"detail":"invalid token"}`
- **Cause probable** : token d'accès `shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg` refusé par l'API (expiré, révoqué ou mauvais environnement)

## Contexte

L'endpoint `/api/shadow/v2_core_long/counterfactual` (commit 6eb39c6 du 2026-05-08) renvoie normalement le rapport hebdomadaire d'analyse contrefactuelle Track A × veto géopolitique.

Ce rapport est automatiquement généré à partir de la table `shadow_setups` (colonne `geopolitical_features_json` peuplée depuis le commit 3ac0d70).

## Action requise

Vérifier et renouveler le token d'accès shadow dans la configuration de la tâche planifiée. Si le problème persiste la semaine prochaine, cela constituera **2 semaines consécutives d'indisponibilité**.

---

*Rapport auto-généré — collecte du 2026-11-21 (1ère semaine en échec)*
