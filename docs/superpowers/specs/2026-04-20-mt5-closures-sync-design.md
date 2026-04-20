# Sync des fermetures MT5 → personal_trades (réconciliation par polling)

**Date** : 2026-04-20
**Auteur** : session scalping (chantier B après fiabilisation du pipeline)
**Scope** : `backend/services/mt5_sync.py` (radar) + un nouveau endpoint `/deals?ticket=X` côté bridge (`C:\Scalping\mt5-bridge\bridge.py`)

## Contexte

Après les 4 fixes du 2026-04-20 soir (commits `f97ff07`, `ec6941d`, `69df7f1`, `b946359`), le pipeline envoie enfin des ordres avec de vrais prix marché vers Pepperstone-Demo. Les trades auto (`is_auto=1`) sont correctement créés en DB `personal_trades` avec `status='OPEN'` par `sync_from_bridge.audit` → `_upsert_open_trade`.

**Problème** : quand MT5 ferme la position **naturellement** (SL touché, TP touché, fermeture utilisateur dans l'app MT5 mobile, swap overnight, etc.), le bridge ne crée **aucune ligne d'audit** — il ne log que les fermetures initiées via ses propres endpoints `/kill` et `/close`. Conséquence : la ligne `personal_trades` reste éternellement `status='OPEN'` avec `exit_price=NULL`, `pnl=NULL`, `closed_at=NULL`.

Impact : impossible de calculer win rate, drawdown, P&L cumulé, perf par pattern/classe. Blocant pour la Phase 2 d'observation et les futures étapes (insights dashboard ML Phase 1, passage live).

## Objectif

Faire en sorte que chaque `personal_trade` auto passe à `status='CLOSED'` avec `exit_price` et `pnl` renseignés au plus tard 60 secondes après la fermeture effective côté MT5, quelque soit la cause de la fermeture.

## Non-objectifs

- Pas de refonte du flow `/audit` actuel — il continue de produire les INSERT OPEN et les UPDATE CLOSED pour les fermetures `/kill` / `/close`. La réconciliation polling tourne en complément.
- Pas de backfill manuel au-delà de ce que garde `mt5.history_deals_get` (typiquement ~90 jours chez Pepperstone Demo, à confirmer empiriquement).
- Pas de nouvelle UI. Les écrans existants (Mes trades, Risque, Equity) consomment déjà `status` et `pnl`, ils se mettent à jour seuls.
- Pas de détection sub-minute. La phase d'observation n'a pas besoin de latence fine.

## Architecture

### B.1 — Endpoint bridge `/deals?ticket=X`

Nouveau handler dans `bridge.py`. Expose le deal de fermeture MT5 pour un ticket donné.

**Signature** :
- `GET /deals?ticket=<int>`
- Headers : `X-API-Key`
- Réponses :
  - `200 {"ticket": 66685891, "closed": true, "exit_price": 1.35100, "pnl": -12.34, "closed_at": "2026-04-20T23:15:00+00:00"}`
  - `200 {"ticket": 66685891, "closed": false}` — position encore ouverte côté MT5
  - `200 {"ticket": 66685891, "closed": null, "reason": "no deals found (history purged?)"}` — ticket introuvable

**Implémentation** :
```python
@app.get("/deals")
def get_deals():
    ticket = request.args.get("ticket", type=int)
    if not ticket:
        return jsonify({"error": "ticket required"}), 400

    pos = mt5.positions_get(ticket=ticket)
    if pos:
        return jsonify({"ticket": ticket, "closed": False})

    deals = mt5.history_deals_get(position=ticket) or []
    out_deal = next((d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT), None)
    if out_deal is None:
        return jsonify({"ticket": ticket, "closed": None, "reason": "no deals found"})
    return jsonify({
        "ticket": ticket,
        "closed": True,
        "exit_price": float(out_deal.price),
        "pnl": float(out_deal.profit),
        "closed_at": datetime.fromtimestamp(out_deal.time, tz=timezone.utc).isoformat(),
    })
```

### B.2 — Fonction radar `_reconcile_open_trades`

Dans `backend/services/mt5_sync.py`. Appelée par `sync_from_bridge` juste après le traitement de `/audit`.

**Flow** :
1. `SELECT mt5_ticket FROM personal_trades WHERE status='OPEN' AND is_auto=1 AND mt5_ticket IS NOT NULL`
2. `GET /positions` → set des `ticket` actuellement ouverts côté MT5
3. `tickets_fermés = tickets_db_open − tickets_positions_ouvertes`
4. Pour chaque ticket dans `tickets_fermés` :
   - `GET /deals?ticket=X`
   - `closed == true` : appel `_update_closed_trade(row_from_deal)`
   - `closed == null` (introuvable) : log warning + `UPDATE personal_trades SET status='CLOSED' WHERE mt5_ticket=X` (sans pnl, on ne saura pas)
   - Exception httpx : skip le ticket, retry prochain cycle

**Code visé** (~40 lignes, intégré au fichier existant) :
```python
async def _reconcile_open_trades() -> None:
    if not (MT5_SYNC_ENABLED and MT5_BRIDGE_URL and MT5_BRIDGE_API_KEY):
        return
    open_tickets = _select_open_auto_tickets()
    if not open_tickets:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{MT5_BRIDGE_URL.rstrip('/')}/positions",
                headers={"X-API-Key": MT5_BRIDGE_API_KEY},
            )
            if r.status_code != 200:
                logger.warning(f"mt5_sync: /positions {r.status_code}")
                return
            positions = r.json().get("positions", [])
            live_tickets = {int(p["ticket"]) for p in positions}
    except Exception as e:
        logger.debug(f"mt5_sync: /positions unreachable: {e}")
        return

    closed = open_tickets - live_tickets
    if not closed:
        return

    n_fully = n_partial = 0
    for ticket in closed:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(
                    f"{MT5_BRIDGE_URL.rstrip('/')}/deals",
                    headers={"X-API-Key": MT5_BRIDGE_API_KEY},
                    params={"ticket": ticket},
                )
                if r.status_code != 200:
                    continue
                data = r.json()
        except Exception:
            continue
        if data.get("closed") is True:
            _update_closed_trade({
                "ticket": ticket,
                "exit_price": data["exit_price"],
                "pnl": data["pnl"],
                "created_at": data["closed_at"],
            })
            n_fully += 1
        elif data.get("closed") is None:
            _mark_ticket_closed_no_deal(ticket)
            logger.warning(f"mt5_sync: ticket {ticket} missing deal history, marking CLOSED only")
            n_partial += 1
    if n_fully or n_partial:
        logger.info(f"mt5_sync: {n_fully} closures reconciled (full), {n_partial} partial")
```

Avec deux petits helpers :
```python
def _select_open_auto_tickets() -> set[int]:
    with sqlite3.connect(_db_path()) as c:
        rows = c.execute(
            "SELECT mt5_ticket FROM personal_trades WHERE status='OPEN' AND is_auto=1 AND mt5_ticket IS NOT NULL"
        ).fetchall()
    return {int(r[0]) for r in rows}

def _mark_ticket_closed_no_deal(ticket: int) -> None:
    with sqlite3.connect(_db_path()) as c:
        c.execute(
            "UPDATE personal_trades SET status='CLOSED', closed_at=COALESCE(closed_at, ?) WHERE mt5_ticket=?",
            (datetime.now(timezone.utc).isoformat(), ticket),
        )
```

### B.3 — Intégration dans `sync_from_bridge`

À la fin de la fonction existante, après le `_save_last_synced_id(max_id)` :
```python
await _reconcile_open_trades()
```

## Tests

Nouveau fichier `backend/tests/test_mt5_sync_reconcile.py` :

1. **`test_no_closures_when_all_tickets_still_open`** — DB contient ticket 100 en OPEN, `/positions` retourne `[{"ticket": 100, ...}]` → aucun appel `/deals`, aucun UPDATE.

2. **`test_closure_detected_when_ticket_missing`** — DB contient ticket 100 en OPEN, `/positions` retourne `[]`, `/deals?ticket=100` retourne `{closed:true, exit_price:1.1, pnl:-5.0}` → UPDATE avec status='CLOSED', exit_price=1.1, pnl=-5.0.

3. **`test_partial_closure_when_deal_history_missing`** — `/deals?ticket=100` retourne `{closed:null}` → status='CLOSED', pnl reste NULL (ne doit pas crasher).

4. **`test_bridge_positions_unreachable_leaves_tickets_open`** — `/positions` lève httpx.ConnectError → aucun UPDATE, log debug, retry prochain cycle.

5. **`test_idempotent_on_already_closed`** — ticket 100 déjà CLOSED en DB, on relance le cycle → `_update_closed_trade` enrichit via COALESCE sans écraser.

## Déploiement

**Côté bridge VPS Windows** :
1. Backup `bridge.py` local.
2. Ajout du handler `/deals` (~20 lignes).
3. `scp` du nouveau `bridge.py` vers `C:\Scalping\mt5-bridge\bridge.py` sur le VPS.
4. Task Scheduler : stop ScalpingBridge → start.
5. Smoke test : `curl -H "X-API-Key: ..." http://100.74.160.72:8787/deals?ticket=<ticket_connu>`.

**Côté radar EC2** :
1. Commit `mt5_sync.py` + tests.
2. `git push` + `git pull` sur EC2 + `docker build` + `systemctl restart scalping`.
3. Attendre un cycle (60s) et vérifier `mt5_sync: X closures reconciled` dans les logs.

## Rollback

- Si le endpoint `/deals` du bridge pose problème : rollback `bridge.py` via backup, restart Task Scheduler.
- Si le code radar provoque une régression : `git revert <commit>` + redeploy. La réconciliation est **additive**, elle ne modifie pas le flow existant donc un revert ne perd pas de données.

## Critères de succès

- Les 2 positions actuellement ouvertes (`GBPUSD buy` 0.1, `EURJPY sell` 0.1) passeront en `CLOSED` avec `pnl` renseigné dès que MT5 touchera leur SL/TP.
- À horizon 50 trades auto : `SELECT COUNT(*) FROM personal_trades WHERE is_auto=1 AND status='OPEN' AND created_at < datetime('now', '-1 day')` doit retourner 0 (aucun trade laissé en OPEN > 24h).
- `SELECT COUNT(*) FROM personal_trades WHERE is_auto=1 AND status='CLOSED' AND pnl IS NULL` doit rester marginal (< 5%, correspondant aux edge cases "history purgé").
