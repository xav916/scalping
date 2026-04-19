# Macro Context Scoring — Rollout Guide

Vague 1 du scoring multi-sources. Ajoute un multiplicateur (0.75 → 1.2) et un veto conditionnel à la confidence des setups, basé sur 8 indicateurs macro (DXY, SPX, VIX, US10Y, DE10Y, Oil, Nikkei, Gold).

## Variables d'environnement

```bash
# Feature flags
MACRO_SCORING_ENABLED=false      # false = aucun effet (le job ne tourne pas)
MACRO_VETO_ENABLED=false         # false = multiplicateur seulement, pas de veto hard

# Refresh / tolérance cache
MACRO_REFRESH_INTERVAL_SEC=900   # 15 min
MACRO_CACHE_MAX_AGE_SEC=7200     # 2h avant fallback neutre
```

Voir `config/settings.py` pour les seuils fins (z-score, VIX, sigma veto).

## Phases de déploiement

### Phase 1 — Shadow mode (off)

État initial après déploiement :

```
MACRO_SCORING_ENABLED=false
MACRO_VETO_ENABLED=false
```

Le job de refresh ne tourne pas, `enrich_trade_setup` n'applique aucun ajustement. Comportement identique au pré-macro.

### Phase 2 — Observation du refresh (1 jour)

```
MACRO_SCORING_ENABLED=true
MACRO_VETO_ENABLED=false
```

Le job tourne toutes les 15 min, le cache se remplit, le multiplicateur s'applique à `confidence_score`. Aucun veto.

Vérifications :

```bash
# Endpoint debug (admin)
curl -u <user>:<pass> https://scalping-radar.duckdns.org/debug/macro

# Logs du conteneur
sudo docker logs --tail 100 scalping-radar | grep -iE "macro"
```

Lignes attendues :
```
macro: refresh job scheduled every 900s
macro: refreshed — dxy=up spx=neutral vix=17.3(normal) risk=neutral
macro_applied pair=EUR/USD dir=buy base=72 mult=0.9 final=64.8 veto=false
```

Pendant 3-5 jours, comparer les scores sans macro (historique) vs avec macro (current). Valider que les multiplicateurs < 1 correspondent bien aux contextes défavorables.

### Phase 3 — Veto activé

```
MACRO_SCORING_ENABLED=true
MACRO_VETO_ENABLED=true
```

Le veto force `verdict_action = "SKIP"` sur les cas extrêmes (VIX > 30 contre setup, DXY > 2σ intraday contre setup).

Observer pendant 2 semaines avant de conclure sur l'impact final.

## Kill switch

À tout moment :

```bash
# Sur EC2
sudo sed -i 's/^MACRO_SCORING_ENABLED=.*/MACRO_SCORING_ENABLED=false/' /opt/scalping/.env
sudo docker restart scalping-radar
```

Le job refresh s'arrête, `enrich_trade_setup` skip le bloc macro, le comportement revient immédiatement au pré-macro.

## Inspection des trades enrichis

Colonne `context_macro` (JSON) dans `personal_trades` :

```sql
SELECT id, pair, direction, confidence_score,
       json_extract(context_macro, '$.dxy') AS dxy,
       json_extract(context_macro, '$.risk_regime') AS regime,
       json_extract(context_macro, '$.vix_value') AS vix
FROM personal_trades
WHERE context_macro IS NOT NULL
ORDER BY id DESC
LIMIT 20;
```

Pour chiffrer l'impact après quelques semaines :

```sql
-- Win rate par régime macro
SELECT json_extract(context_macro, '$.risk_regime') AS regime,
       COUNT(*) AS n_trades,
       SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
       ROUND(100.0 * SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) AS win_pct
FROM personal_trades
WHERE status = 'CLOSED' AND context_macro IS NOT NULL
GROUP BY regime;
```

## Critères de succès

Mesurés sur ~100 trades après activation complète (Phase 3) :

- **Réduction du taux de faux positifs** : setups classés TAKE qui finissent en perte → baisse visible vs baseline
- **Pas de régression sur les vrais positifs** : taux de gain sur trades pris ≥ baseline
- **Distribution des multiplicateurs cohérente** : majorité autour de 1.0, queues à 0.75 et 1.2 actives mais pas dominantes
- **Vetos rares** : < 10% des setups potentiels — si plus, recalibrer `MACRO_VIX_HIGH` ou `MACRO_DXY_VETO_SIGMA`

## Dépannage

| Symptôme | Cause probable | Action |
|---|---|---|
| Aucun log "macro: refreshed" après activation | `TWELVEDATA_API_KEY` vide ou invalide | Vérifier la clé |
| Log "macro: SYMBOL HTTP 400" répété | Ticker non supporté par Twelve Data (ex: DE10Y) | Surcharger `MACRO_SYMBOL_DE10Y` ou laisser en fallback neutre |
| `/debug/macro` renvoie `no_snapshot_yet` >30 min | Job scheduler non enregistré | Vérifier que `MACRO_SCORING_ENABLED=true` au démarrage du conteneur |
| Tous les setups ont multiplicateur=1.0 | Snapshot stale (> 2h) ou pair non mappée | Voir `/debug/macro` pour l'âge du cache ; la classe de paire est définie dans `backend/services/macro_scoring.py` |

## Vagues 2 et 3 (non inclus)

- **Vague 2** : sentiment retail (Myfxbook / OANDA) — spec séparé à venir
- **Vague 3** : news sentiment (Finnhub / Alpha Vantage) — spec séparé à venir

À ouvrir seulement une fois la Vague 1 validée (critères de succès atteints).
