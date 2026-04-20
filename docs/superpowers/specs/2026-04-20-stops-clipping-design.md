# Fiabilisation du taux d'exécution — clipping des stops côté bridge

**Date** : 2026-04-20
**Auteur** : session scalping (brainstorm A+B après observation 2h d'auto-exec)
**Scope** : `C:\Scalping\mt5-bridge\bridge.py` (code non versionné dans le repo principal ; voir reference_scalping_paths.md pour la procédure de patch)

## Contexte

Après le cutover PC → VPS et le retrait du gate `verdict_action == "TAKE"` (commit `f97ff07`), l'auto-exec s'est enfin déclenché. 2h d'observation donnent le bilan :

| Statut                       | Nombre | %    |
|------------------------------|--------|------|
| `filled` (retcode 10009)     | 6      | 14%  |
| `rejected` (retcode 10016)   | 24     | 56%  |
| `blocked` (pré-MT5, bridge)  | 13     | 30%  |
| **Total hors smoke**         | **43** | 100% |

- `rc=10016` = `TRADE_RETCODE_INVALID_STOPS` — MT5 refuse l'ordre car `|price − SL|` ou `|price − TP|` est inférieur à la distance minimum du symbole chez le broker (`symbol_info.trade_stops_level`).
- `blocked` = rejet côté bridge avant envoi MT5, produit par `_check_safety_gates` (4 gardes : `trading_hours`, `max_daily_loss`, `max_open_positions`, dedup temporelle).

## Objectif

Chaque ordre envoyé au bridge aboutit à **un résultat compris et choisi** :
- soit `filled`,
- soit `blocked` avec une raison claire parmi les gardes connues,
- soit `rejected` avec une raison non-broker (ex : échec de connectivité MT5, filling mode incompatible).

**Plus aucun `rc=10016` "surprise".** Le bridge doit s'adapter aux contraintes broker de manière transparente en préservant l'intention de risk management du radar.

## Non-objectifs

- Ne pas réduire ni assouplir les `_check_safety_gates`. La dedup + max_pos sont une **feature** de l'observation Phase 2, pas un bug.
- Ne pas changer le code du radar (`backend/services/mt5_bridge.py`, `analysis_engine.py`). Le radar continue d'envoyer un payload `{entry, sl, tp, risk_money}` sans connaître les spécificités broker.
- Pas de refonte du sizing : `_compute_lots_from_symbol` reste la source unique de vérité pour la conversion risk_money → lots.

## Architecture

### A.1 — Nouvelle fonction `_clip_stops_to_broker_limits`

**Signature** :
```python
def _clip_stops_to_broker_limits(
    symbol: str,
    direction: str,
    sl: float,
    tp: float,
) -> dict:
    """Ajuste SL/TP pour respecter trade_stops_level du broker.

    Returns {
      "sl": float,            # SL final à envoyer à MT5
      "tp": float,            # TP final
      "clipped": bool,        # True si au moins un des deux a bougé
      "sl_requested": float,  # valeur originale (pour l'audit)
      "tp_requested": float,
      "min_dist": float,      # distance minimum appliquée (prix)
      "reason": str | None,   # libellé explicatif si clipped
    }
    """
```

**Algorithme** :
1. `info = mt5.symbol_info(symbol)` ; si `None` → retour passthrough avec warning log (on laisse MT5 décider, ordre partira avec le SL/TP d'origine).
2. `tick = mt5.symbol_info_tick(symbol)` ; prix de référence :
   - buy → `tick.ask`
   - sell → `tick.bid`
3. `min_dist = info.trade_stops_level * info.point * STOPS_BUFFER_MULT`
   - `STOPS_BUFFER_MULT` : env var, défaut `1.5` (50% de marge au-dessus du minimum pour absorber les micro-mouvements entre la requête et l'exécution).
4. Clip selon direction :
   - **buy** :
     - `sl_clip = min(sl, price − min_dist)` si `sl > price − min_dist`
     - `tp_clip = max(tp, price + min_dist)` si `tp < price + min_dist`
   - **sell** :
     - `sl_clip = max(sl, price + min_dist)` si `sl < price + min_dist`
     - `tp_clip = min(tp, price − min_dist)` si `tp > price − min_dist`
5. Arrondi final à `info.digits` chiffres après la virgule.
6. `clipped = (sl_clip != sl) or (tp_clip != tp)`.
7. Construction du `reason` si clipped (ex: `"SL clipped from 1.17700 → 1.17680 (min_dist=20pts×1.5)"`).

### A.2 — Intégration dans `_handle_live_order`

Avant `_send_market_order`, après `_check_safety_gates(ok)` :

```python
clip = _clip_stops_to_broker_limits(mt5_symbol, direction, sl, tp)
sl_requested, tp_requested = clip["sl_requested"], clip["tp_requested"]
lots_requested = lots  # sizing calculé avant clip
if clip["clipped"]:
    sl, tp = clip["sl"], clip["tp"]
    logger.info(f"[CLIP] {mt5_symbol} {direction} {clip['reason']}")
    # Recalculer les lots avec le nouveau SL pour préserver risk_money
    if "risk_money" in data:
        lots = _compute_lots_from_symbol(mt5_symbol, entry, sl, float(data["risk_money"]))
        logger.info(f"[CLIP] lots recalculés: {lots_requested} → {lots}")
```

### A.3 — Persistence audit

**Migration** (idempotente, au démarrage du bridge) :
```python
def _migrate_add_requested_columns(conn):
    for col_def in (
        "sl_requested REAL",
        "tp_requested REAL",
        "lots_requested REAL",
    ):
        try:
            conn.execute(f"ALTER TABLE orders ADD COLUMN {col_def}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise
```

**Extension `_db_log_order`** : accepter les 3 nouveaux kwargs optionnels, les INSERT en même temps que les colonnes existantes.

**Appel `_handle_live_order`** : passer `sl_requested=..., tp_requested=..., lots_requested=...` dans tous les `_db_log_order(status="filled"|"rejected")`.

### A.4 — Endpoint `/audit`

Ajouter les 3 colonnes au `SELECT`. Compatibilité ascendante : les anciennes lignes auront `null` pour ces colonnes (SQLite accepte `ALTER TABLE ADD COLUMN` avec valeurs `NULL` par défaut).

## B — Safety gates : aucun changement

Les 4 gardes de `_check_safety_gates` restent actives avec leurs valeurs actuelles :
- `TRADING_HOURS_UTC`
- `MAX_DAILY_LOSS_PCT`
- `MAX_OPEN_POSITIONS`
- `DEDUP_WINDOW_SEC`

Ces blocs sont **la feature** : ils empêchent les excès et fournissent des raisons documentées dans la colonne `message`. Aucune modification.

## Tests

### Unit tests — `test_stops_clipping.py` (nouveau fichier, sur VPS)

1. `test_clip_buy_sl_too_close` — mock symbol_info avec `trade_stops_level=10`, `point=0.00001`, price=1.10000. SL demandé à 1.09998 (distance 2pts) → SL clippé à 1.09985 (distance 15pts = 10 × 1.5).
2. `test_clip_buy_tp_too_close` — idem pour TP.
3. `test_clip_sell_sl_too_close` — direction inversée.
4. `test_clip_sell_tp_too_close` — idem.
5. `test_no_clip_when_respects_min_dist` — SL/TP à 50pts, `min_dist=15pts` → `clipped=False`.
6. `test_lots_recalc_preserves_risk_money` — après clip, `lots × |entry − sl_clipped| × tick_value ≈ risk_money` (tolérance 5% pour arrondis volume_step).
7. `test_passthrough_when_symbol_info_none` — `mt5.symbol_info` retourne None → `clipped=False`, SL/TP inchangés, warning logué.
8. `test_audit_columns_present` — après migration, `PRAGMA table_info(orders)` contient `sl_requested`, `tp_requested`, `lots_requested`.

### Test d'intégration — smoke live (documenté dans DEPLOY.md du bridge)

- `POST /order` vers EUR/USD avec SL volontairement à 1 pip du prix.
- Attendu : 200 `{ok: true, clipped: true, sl_original: ..., sl_applied: ..., ticket: ...}`.
- Vérifier ligne audit : `sl_requested != sl`, `clipped=true`, status `filled`.
- Kill la position via `/kill` après validation.

## Déploiement

1. Patch `bridge.py` local sur PC, validation syntaxe Python.
2. Tests unit exécutés localement (venv PC).
3. `scp` vers VPS Lightsail (user Administrator, chemin `C:\Scalping\mt5-bridge\bridge.py`).
4. Backup de l'ancienne version : `bridge.py.bak.YYYYMMDD_HHMMSS`.
5. Kill du process `pythonw.exe` via Task Scheduler stop ScalpingBridge → start (redémarre avec nouveau code).
6. `curl /health` → doit répondre 200.
7. Surveillance 1h : aucun `rc=10016` attendu sur les ordres envoyés.

## Rollback

En cas de régression (exceptions Python inattendues, 0 ordre filled pendant 1h post-deploy, bridge non répondant) :
1. Task Scheduler : stop ScalpingBridge.
2. PowerShell (RDP VPS) : `Rename-Item bridge.py bridge.py.regression ; Copy-Item (Get-ChildItem bridge.py.bak.*.py | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName bridge.py`.
3. Task Scheduler : start ScalpingBridge.
4. `curl /health` → 200.

Temps de rollback estimé : < 2 min.

## Métriques de succès (sur 24h post-deploy)

- `retcode=10016` **< 1%** des ordres (vs 56% baseline — voir tableau contexte).
- `filled` **≥ 40%** des ordres hors `blocked` (baseline : 6 filled sur 30 non-blocked = 20%). Note : ce ratio est différent du 14% global du contexte, qui mélange `filled` et `blocked`.
- `clipped=true` dans un sous-ensemble significatif (> 5%) des filled, preuve que le clip a travaillé.
- Les lignes audit post-deploy ont systématiquement `sl_requested` et `lots_requested` remplis.

## Suites prévues (hors scope ce chantier)

- **Chantier C — diversification** : cap notionnel par asset class (déjà dans next_steps).
- **Chantier D — qualité setups** : remonter `MT5_BRIDGE_MIN_CONFIDENCE` à 65+ après 50 trades observés.
- **Chantier F — sync fermetures MT5 → DB** (chantier 1.5 déjà listé) : nécessaire pour analyse perf a posteriori.

Ces chantiers deviennent plus lisibles une fois le taux de fill stabilisé.
