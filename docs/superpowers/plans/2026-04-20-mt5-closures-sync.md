# MT5 Closures Sync — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Réconcilier automatiquement les personal_trades OPEN contre les positions MT5 réelles via un polling périodique, et renseigner exit_price + pnl quand MT5 ferme une position (SL, TP, ou fermeture manuelle app mobile).

**Architecture:** Nouveau endpoint bridge `GET /deals?ticket=X` qui interroge `mt5.history_deals_get(position=ticket)` et retourne le deal de fermeture (DEAL_ENTRY_OUT). Côté radar, nouvelle fonction `_reconcile_open_trades` appelée en fin de `sync_from_bridge` : compare les tickets DB OPEN vs `/positions`, appelle `/deals` pour chaque ticket manquant, et met à jour `personal_trades` via `_update_closed_trade` existant.

**Tech Stack:** Python 3.13 asyncio, httpx, sqlite3, Flask (bridge côté VPS Windows), MetaTrader5 Python package, pytest.

---

## File Structure

- **Create** : `backend/tests/test_mt5_sync_reconcile.py` — 5 tests couvrant les scénarios de réconciliation
- **Modify** : `backend/services/mt5_sync.py` — ajout de 3 fonctions (`_select_open_auto_tickets`, `_mark_ticket_closed_no_deal`, `_reconcile_open_trades`) + 1 appel à la fin de `sync_from_bridge`
- **Modify** : `C:\Scalping\mt5-bridge\bridge.py` (VPS Windows, pas dans le repo) — ajout d'un handler `@app.route("/deals")`. Déploiement par scp + Task Scheduler restart.

---

### Task 1 — Ajouter l'endpoint `/deals` côté bridge VPS

**Files:**
- Modify: `C:\Scalping\mt5-bridge\bridge.py` (VPS Windows via scp)

- [ ] **Step 1.1 : Rapatrier bridge.py courant depuis le VPS**

Run:
```bash
ssh -i C:/Users/xav91/Scalping/scalping/scalping-key.pem -o ProxyCommand='ssh -i C:/Users/xav91/Scalping/scalping/scalping-key.pem ec2-user@100.103.107.75 -W %h:%p' Administrator@100.74.160.72 "type C:\\Scalping\\mt5-bridge\\bridge.py" > C:/Users/xav91/Scalping/bridge_vps.py
```

Alternative (si le ProxyCommand ne passe pas) : RDP sur `100.74.160.72`, copier `bridge.py` dans `C:\Scalping\vps-credentials\` partagé, puis `scp Administrator@100.74.160.72:C:/Scalping/vps-credentials/bridge.py ./bridge_vps.py`.

- [ ] **Step 1.2 : Localiser un point d'ajout dans bridge.py**

Chercher la définition du handler `/positions` (déjà exposé) et ajouter le handler `/deals` juste après dans le même fichier.

Run: `grep -n "def get_positions\|@app.route.*positions" C:/Users/xav91/Scalping/bridge_vps.py` pour repérer la ligne.

- [ ] **Step 1.3 : Ajouter le handler**

Insérer ce bloc juste après `def get_positions()` :

```python
@app.route("/deals", methods=["GET"])
@_require_api_key
def get_deals():
    """Retourne le deal de fermeture (DEAL_ENTRY_OUT) pour un ticket donné.

    - closed=true  : position fermée, exit_price+pnl+closed_at renseignés
    - closed=false : position encore ouverte côté MT5
    - closed=null  : aucun deal trouvé (history purgée / ticket inconnu)
    """
    try:
        ticket = int(request.args.get("ticket", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "ticket must be int"}), 400
    if ticket <= 0:
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

Note : `_require_api_key` est le décorateur déjà utilisé par les autres handlers (vérifier le nom exact dans le fichier — adapter si besoin). `request`, `jsonify`, `mt5`, `datetime`, `timezone` doivent déjà être importés par les handlers voisins.

- [ ] **Step 1.4 : Backup + upload**

Run :
```bash
scp -i C:/Users/xav91/Scalping/scalping/scalping-key.pem C:/Users/xav91/Scalping/bridge_vps.py ec2-user@100.103.107.75:/tmp/bridge_deals.py
# Puis depuis l'EC2, transiter vers le VPS Windows via Tailscale/RDP OU scp direct si SSH is enabled
# Option recommandée : copier depuis PC local vers le VPS via partage réseau ou RDP copy/paste
```

Simpler si possible : RDP sur `100.74.160.72` (IP publique `13.51.157.9`, firewall autorisé sur IP home), ouvrir `C:\Scalping\mt5-bridge\bridge.py`, coller le bloc ajouté, sauver.

- [ ] **Step 1.5 : Backup de l'ancien bridge.py côté VPS**

Via RDP PowerShell :
```powershell
cd C:\Scalping\mt5-bridge
Copy-Item bridge.py bridge.py.bak.deals-endpoint-20260420
```

- [ ] **Step 1.6 : Restart du process bridge**

Via RDP Task Scheduler : clic droit sur `ScalpingBridge` → End → Run. Ou PowerShell :
```powershell
Stop-ScheduledTask -TaskName ScalpingBridge
Start-ScheduledTask -TaskName ScalpingBridge
```

- [ ] **Step 1.7 : Smoke test depuis EC2 ou PC**

Avec un ticket existant (ex: position ouverte actuellement `66685891` pour GBPUSD) :
```bash
VPS_KEY=$(tr -d '\r\n' < C:/Scalping/vps-credentials/vps-bridge-api-key.txt)
curl -s -H "X-API-Key: $VPS_KEY" "http://100.74.160.72:8787/deals?ticket=66685891"
```

Expected si position encore ouverte :
```json
{"ticket":66685891,"closed":false}
```

Puis avec un ticket déjà fermé (smoke test du matin, `66598763`) :
```bash
curl -s -H "X-API-Key: $VPS_KEY" "http://100.74.160.72:8787/deals?ticket=66598763"
```

Expected :
```json
{"ticket":66598763,"closed":true,"exit_price":...,"pnl":...,"closed_at":"..."}
```

- [ ] **Step 1.8 : Noter l'absence de commit**

Le fichier `bridge.py` n'étant pas versionné dans le repo scalping, pas de commit. Le backup `.bak` sert de rollback.

---

### Task 2 — Tests unit `_select_open_auto_tickets`

**Files:**
- Create: `C:/Users/xav91/Scalping/scalping/backend/tests/test_mt5_sync_reconcile.py`

- [ ] **Step 2.1 : Écrire le test pour _select_open_auto_tickets**

```python
"""Tests pour la réconciliation des fermetures MT5 → personal_trades.

Le bridge ne log pas les fermetures naturelles (SL/TP touchés par le marché).
_reconcile_open_trades compare les tickets DB OPEN vs /positions et comble
les trous via /deals.
"""
import sqlite3
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.services import mt5_sync


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """DB SQLite temporaire avec schéma personal_trades minimal."""
    db_file = tmp_path / "trades.db"
    conn = sqlite3.connect(db_file)
    conn.execute("""
        CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY,
            user TEXT, pair TEXT, direction TEXT,
            entry_price REAL, stop_loss REAL, take_profit REAL,
            size_lot REAL, signal_pattern TEXT, signal_confidence REAL,
            checklist_passed INTEGER, notes TEXT, status TEXT,
            created_at TEXT, mt5_ticket INTEGER, is_auto INTEGER,
            post_entry_sl INTEGER, post_entry_tp INTEGER, post_entry_size INTEGER,
            context_macro TEXT, exit_price REAL, pnl REAL, closed_at TEXT
        )
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(mt5_sync, "_db_path", lambda: str(db_file))
    return db_file


def _insert_trade(db_path, ticket, status="OPEN", is_auto=1):
    with sqlite3.connect(db_path) as c:
        c.execute("""
            INSERT INTO personal_trades
              (user, pair, direction, entry_price, stop_loss, take_profit,
               size_lot, status, created_at, mt5_ticket, is_auto)
            VALUES ('u', 'EUR/USD', 'buy', 1.1, 1.09, 1.12, 0.1, ?,
                    '2026-04-20T20:00:00+00:00', ?, ?)
        """, (status, ticket, is_auto))


def test_select_open_auto_tickets_returns_only_open_auto(temp_db):
    _insert_trade(temp_db, 100, status="OPEN", is_auto=1)
    _insert_trade(temp_db, 101, status="OPEN", is_auto=0)   # pas auto
    _insert_trade(temp_db, 102, status="CLOSED", is_auto=1) # déjà fermé
    _insert_trade(temp_db, 103, status="OPEN", is_auto=1)

    tickets = mt5_sync._select_open_auto_tickets()

    assert tickets == {100, 103}


def test_select_open_auto_tickets_empty_when_no_matching(temp_db):
    _insert_trade(temp_db, 200, status="CLOSED", is_auto=1)
    assert mt5_sync._select_open_auto_tickets() == set()
```

- [ ] **Step 2.2 : Vérifier que le test fail (fonction pas encore écrite)**

Run: `cd C:/Users/xav91/Scalping/scalping && python -m pytest backend/tests/test_mt5_sync_reconcile.py -v`
Expected: ERROR au collect `AttributeError: module 'backend.services.mt5_sync' has no attribute '_select_open_auto_tickets'`

- [ ] **Step 2.3 : Implémenter _select_open_auto_tickets dans mt5_sync.py**

Ajouter juste après `_update_closed_trade` (vers ligne 150) :

```python
def _select_open_auto_tickets() -> set[int]:
    """Retourne les mt5_tickets des personal_trades auto encore OPEN."""
    with sqlite3.connect(_db_path()) as c:
        rows = c.execute(
            "SELECT mt5_ticket FROM personal_trades "
            "WHERE status='OPEN' AND is_auto=1 AND mt5_ticket IS NOT NULL"
        ).fetchall()
    return {int(r[0]) for r in rows}
```

- [ ] **Step 2.4 : Re-run tests, doivent passer**

Run: `python -m pytest backend/tests/test_mt5_sync_reconcile.py -v`
Expected: 2 passed.

- [ ] **Step 2.5 : Commit**

```bash
git add backend/services/mt5_sync.py backend/tests/test_mt5_sync_reconcile.py
git commit -m "feat(mt5-sync): helper _select_open_auto_tickets

Première étape de la réconciliation des fermetures MT5 → DB.
Retourne les tickets des personal_trades auto encore OPEN, seul
point d'entrée nécessaire pour _reconcile_open_trades."
```

---

### Task 3 — Test + implem `_mark_ticket_closed_no_deal`

**Files:**
- Modify: `backend/tests/test_mt5_sync_reconcile.py`
- Modify: `backend/services/mt5_sync.py`

- [ ] **Step 3.1 : Ajouter le test**

Append au fichier de test :

```python
def test_mark_ticket_closed_no_deal_updates_status_only(temp_db):
    _insert_trade(temp_db, 300, status="OPEN", is_auto=1)

    mt5_sync._mark_ticket_closed_no_deal(300)

    with sqlite3.connect(temp_db) as c:
        row = c.execute(
            "SELECT status, exit_price, pnl, closed_at FROM personal_trades WHERE mt5_ticket=?",
            (300,)
        ).fetchone()
    assert row[0] == "CLOSED"
    assert row[1] is None        # exit_price pas touché
    assert row[2] is None        # pnl pas touché
    assert row[3] is not None    # closed_at renseigné


def test_mark_ticket_closed_no_deal_preserves_existing_closed_at(temp_db):
    with sqlite3.connect(temp_db) as c:
        c.execute("""
            INSERT INTO personal_trades
              (user, pair, direction, entry_price, stop_loss, take_profit,
               size_lot, status, created_at, mt5_ticket, is_auto, closed_at)
            VALUES ('u', 'EUR/USD', 'buy', 1.1, 1.09, 1.12, 0.1, 'CLOSED',
                    '2026-04-20T20:00:00+00:00', 301, 1, '2026-04-20T21:00:00+00:00')
        """)
    mt5_sync._mark_ticket_closed_no_deal(301)

    with sqlite3.connect(temp_db) as c:
        closed_at = c.execute(
            "SELECT closed_at FROM personal_trades WHERE mt5_ticket=?", (301,)
        ).fetchone()[0]
    assert closed_at == "2026-04-20T21:00:00+00:00"  # pas écrasé
```

- [ ] **Step 3.2 : Vérifier que les tests fail**

Run: `python -m pytest backend/tests/test_mt5_sync_reconcile.py::test_mark_ticket_closed_no_deal_updates_status_only -v`
Expected: FAIL `AttributeError: ... _mark_ticket_closed_no_deal`

- [ ] **Step 3.3 : Implémenter**

Ajouter dans `mt5_sync.py` après `_select_open_auto_tickets` :

```python
def _mark_ticket_closed_no_deal(ticket: int) -> None:
    """Fallback quand le deal MT5 est introuvable (history purgée) :
    on marque status=CLOSED sans pouvoir renseigner exit_price/pnl.
    closed_at est protégé par COALESCE."""
    with sqlite3.connect(_db_path()) as c:
        c.execute(
            "UPDATE personal_trades "
            "SET status='CLOSED', closed_at=COALESCE(closed_at, ?) "
            "WHERE mt5_ticket=?",
            (datetime.now(timezone.utc).isoformat(), ticket),
        )
```

- [ ] **Step 3.4 : Re-run tests**

Run: `python -m pytest backend/tests/test_mt5_sync_reconcile.py -v`
Expected: 4 passed.

- [ ] **Step 3.5 : Commit**

```bash
git add backend/services/mt5_sync.py backend/tests/test_mt5_sync_reconcile.py
git commit -m "feat(mt5-sync): helper _mark_ticket_closed_no_deal

Fallback quand MT5 history_deals_get retourne vide (purge ancienne).
Status='CLOSED' seul, sans exit_price/pnl. closed_at préservé via
COALESCE pour ne pas écraser une date déjà présente."
```

---

### Task 4 — Tests + implem `_reconcile_open_trades`

**Files:**
- Modify: `backend/tests/test_mt5_sync_reconcile.py`
- Modify: `backend/services/mt5_sync.py`

- [ ] **Step 4.1 : Ajouter les 5 tests principaux**

Append au fichier de test :

```python
class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Mock d'httpx.AsyncClient retournant des réponses prédéfinies par URL."""
    def __init__(self, responses):
        self._responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, params=None):
        key = url
        if params and "ticket" in params:
            key = f"{url}?ticket={params['ticket']}"
        if key not in self._responses:
            raise httpx.ConnectError(f"no mock for {key}")
        resp = self._responses[key]
        if isinstance(resp, Exception):
            raise resp
        return resp


@pytest.fixture
def mock_bridge_config(monkeypatch):
    monkeypatch.setattr(mt5_sync, "MT5_SYNC_ENABLED", True)
    monkeypatch.setattr(mt5_sync, "MT5_BRIDGE_URL", "http://bridge.test")
    monkeypatch.setattr(mt5_sync, "MT5_BRIDGE_API_KEY", "key")


@pytest.mark.asyncio
async def test_no_closures_when_all_tickets_still_open(temp_db, mock_bridge_config):
    _insert_trade(temp_db, 400, status="OPEN", is_auto=1)
    _insert_trade(temp_db, 401, status="OPEN", is_auto=1)

    responses = {
        "http://bridge.test/positions": _FakeResponse(200, {
            "positions": [{"ticket": 400}, {"ticket": 401}]
        }),
    }
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses)):
        await mt5_sync._reconcile_open_trades()

    with sqlite3.connect(temp_db) as c:
        statuses = [r[0] for r in c.execute(
            "SELECT status FROM personal_trades WHERE mt5_ticket IN (400, 401)"
        ).fetchall()]
    assert statuses == ["OPEN", "OPEN"]


@pytest.mark.asyncio
async def test_closure_detected_and_full_update(temp_db, mock_bridge_config):
    _insert_trade(temp_db, 500, status="OPEN", is_auto=1)

    responses = {
        "http://bridge.test/positions": _FakeResponse(200, {"positions": []}),
        "http://bridge.test/deals?ticket=500": _FakeResponse(200, {
            "ticket": 500, "closed": True,
            "exit_price": 1.1234, "pnl": -12.5,
            "closed_at": "2026-04-20T21:30:00+00:00",
        }),
    }
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses)):
        await mt5_sync._reconcile_open_trades()

    with sqlite3.connect(temp_db) as c:
        row = c.execute(
            "SELECT status, exit_price, pnl, closed_at FROM personal_trades WHERE mt5_ticket=?",
            (500,)
        ).fetchone()
    assert row[0] == "CLOSED"
    assert row[1] == 1.1234
    assert row[2] == -12.5
    assert row[3] == "2026-04-20T21:30:00+00:00"


@pytest.mark.asyncio
async def test_partial_closure_when_deal_history_missing(temp_db, mock_bridge_config):
    _insert_trade(temp_db, 600, status="OPEN", is_auto=1)

    responses = {
        "http://bridge.test/positions": _FakeResponse(200, {"positions": []}),
        "http://bridge.test/deals?ticket=600": _FakeResponse(200, {
            "ticket": 600, "closed": None, "reason": "no deals found",
        }),
    }
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses)):
        await mt5_sync._reconcile_open_trades()

    with sqlite3.connect(temp_db) as c:
        row = c.execute(
            "SELECT status, exit_price, pnl FROM personal_trades WHERE mt5_ticket=?",
            (600,)
        ).fetchone()
    assert row[0] == "CLOSED"
    assert row[1] is None
    assert row[2] is None


@pytest.mark.asyncio
async def test_bridge_positions_unreachable_leaves_tickets_open(temp_db, mock_bridge_config):
    _insert_trade(temp_db, 700, status="OPEN", is_auto=1)

    responses = {
        "http://bridge.test/positions": httpx.ConnectError("bridge down"),
    }
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses)):
        await mt5_sync._reconcile_open_trades()

    with sqlite3.connect(temp_db) as c:
        status = c.execute(
            "SELECT status FROM personal_trades WHERE mt5_ticket=?", (700,)
        ).fetchone()[0]
    assert status == "OPEN"


@pytest.mark.asyncio
async def test_idempotent_on_already_closed_ticket(temp_db, mock_bridge_config):
    # Scenario : le ticket est déjà CLOSED en DB (ex: sync /audit a déjà travaillé).
    # Un cycle supplémentaire ne doit ni échouer ni écraser les données.
    with sqlite3.connect(temp_db) as c:
        c.execute("""
            INSERT INTO personal_trades
              (user, pair, direction, entry_price, stop_loss, take_profit,
               size_lot, status, created_at, mt5_ticket, is_auto,
               exit_price, pnl, closed_at)
            VALUES ('u', 'EUR/USD', 'buy', 1.1, 1.09, 1.12, 0.1, 'CLOSED',
                    '2026-04-20T20:00:00+00:00', 800, 1,
                    1.15, 50.0, '2026-04-20T20:30:00+00:00')
        """)

    # Pas dans les OPEN, donc _reconcile ne doit jamais le toucher
    responses = {
        "http://bridge.test/positions": _FakeResponse(200, {"positions": []}),
    }
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses)):
        await mt5_sync._reconcile_open_trades()

    with sqlite3.connect(temp_db) as c:
        row = c.execute(
            "SELECT status, exit_price, pnl, closed_at FROM personal_trades WHERE mt5_ticket=?",
            (800,)
        ).fetchone()
    assert row == ("CLOSED", 1.15, 50.0, "2026-04-20T20:30:00+00:00")
```

- [ ] **Step 4.2 : Vérifier que les tests fail (fonction pas écrite)**

Run: `python -m pytest backend/tests/test_mt5_sync_reconcile.py -v -k reconcile`
Expected: 5 tests en ERROR (`AttributeError: _reconcile_open_trades`).

- [ ] **Step 4.3 : Implémenter _reconcile_open_trades**

Ajouter dans `mt5_sync.py` après `_mark_ticket_closed_no_deal` :

```python
async def _reconcile_open_trades() -> None:
    """Compare les tickets DB OPEN vs /positions du bridge et réconcilie
    les fermetures naturelles (SL/TP touchés par le marché).

    Appelé à la fin de sync_from_bridge. No-op si bridge non configuré
    ou s'il n'y a aucun ticket OPEN en DB."""
    if not (MT5_SYNC_ENABLED and MT5_BRIDGE_URL and MT5_BRIDGE_API_KEY):
        return

    open_tickets = _select_open_auto_tickets()
    if not open_tickets:
        return

    base = MT5_BRIDGE_URL.rstrip("/")
    headers = {"X-API-Key": MT5_BRIDGE_API_KEY}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{base}/positions", headers=headers)
            if r.status_code != 200:
                logger.warning(f"mt5_sync: /positions {r.status_code}")
                return
            positions = r.json().get("positions", []) or []
            live_tickets = {int(p["ticket"]) for p in positions if "ticket" in p}
    except Exception as e:
        logger.debug(f"mt5_sync: /positions unreachable: {e}")
        return

    closed_tickets = open_tickets - live_tickets
    if not closed_tickets:
        return

    n_full = 0
    n_partial = 0
    for ticket in closed_tickets:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(
                    f"{base}/deals", headers=headers,
                    params={"ticket": ticket},
                )
                if r.status_code != 200:
                    continue
                data = r.json()
        except Exception as e:
            logger.debug(f"mt5_sync: /deals ticket={ticket} failed: {e}")
            continue

        if data.get("closed") is True:
            _update_closed_trade({
                "ticket": ticket,
                "exit_price": data.get("exit_price"),
                "pnl": data.get("pnl"),
                "created_at": data.get("closed_at"),
            })
            n_full += 1
        elif data.get("closed") is None:
            logger.warning(
                f"mt5_sync: ticket {ticket} history introuvable, status=CLOSED sans pnl"
            )
            _mark_ticket_closed_no_deal(ticket)
            n_partial += 1

    if n_full or n_partial:
        logger.info(
            f"mt5_sync: {n_full} closures reconciled (full), {n_partial} partial"
        )
```

- [ ] **Step 4.4 : Re-run tests**

Run: `python -m pytest backend/tests/test_mt5_sync_reconcile.py -v`
Expected: 9 passed (2 + 2 + 5).

- [ ] **Step 4.5 : Commit**

```bash
git add backend/services/mt5_sync.py backend/tests/test_mt5_sync_reconcile.py
git commit -m "feat(mt5-sync): _reconcile_open_trades via polling /positions + /deals

Compare les tickets DB OPEN avec la liste /positions du bridge ; pour
chaque ticket manquant, récupère le deal via /deals?ticket=X et appelle
_update_closed_trade avec exit_price + pnl. Si history MT5 purgée,
_mark_ticket_closed_no_deal en fallback. Skip silencieux si bridge
unreachable (retry au cycle suivant).

Tests : 5 nouveaux cas couvrant no-op, full closure, partial, bridge down,
idempotence."
```

---

### Task 5 — Intégrer `_reconcile_open_trades` dans `sync_from_bridge`

**Files:**
- Modify: `backend/services/mt5_sync.py` (ligne finale de `sync_from_bridge`)
- Modify: `backend/tests/test_mt5_sync_reconcile.py`

- [ ] **Step 5.1 : Ajouter un test d'intégration**

Append au fichier de test :

```python
@pytest.mark.asyncio
async def test_sync_from_bridge_calls_reconcile(temp_db, mock_bridge_config):
    """sync_from_bridge doit appeler _reconcile_open_trades à la fin,
    même quand /audit ne retourne aucun ordre nouveau."""
    called = []

    async def _spy():
        called.append(True)

    responses = {
        "http://bridge.test/audit": _FakeResponse(200, {"orders": []}),
    }
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses)), \
         patch.object(mt5_sync, "_reconcile_open_trades", _spy):
        await mt5_sync.sync_from_bridge()

    assert called == [True]
```

- [ ] **Step 5.2 : Vérifier que le test fail (appel pas encore fait)**

Run: `python -m pytest backend/tests/test_mt5_sync_reconcile.py::test_sync_from_bridge_calls_reconcile -v`
Expected: FAIL (`assert called == [True]` → `assert [] == [True]`).

- [ ] **Step 5.3 : Ajouter l'appel dans `sync_from_bridge`**

Modifier `mt5_sync.py` : à la fin de `sync_from_bridge`, après `_save_last_synced_id(max_id)` (ou après le early-return si `orders` vide mais avant la fin) :

Le patch précis — dans `sync_from_bridge`, chercher :
```python
    if not orders:
        return
```

Remplacer par :
```python
    if not orders:
        await _reconcile_open_trades()
        return
```

Et à la toute fin de la fonction, après `_save_last_synced_id(max_id)` :
```python
    _save_last_synced_id(max_id)
    await _reconcile_open_trades()
```

- [ ] **Step 5.4 : Re-run le test d'intégration + full suite**

Run:
```bash
python -m pytest backend/tests/test_mt5_sync_reconcile.py -v
python -m pytest backend/tests/
```

Expected: 10 passed dans reconcile, suite globale toujours green (attendu 75+ en tout).

- [ ] **Step 5.5 : Commit**

```bash
git add backend/services/mt5_sync.py backend/tests/test_mt5_sync_reconcile.py
git commit -m "feat(mt5-sync): brancher _reconcile_open_trades dans sync_from_bridge

Appelé à la fin du cycle, même si /audit est vide. Ça garantit que les
trades auto fermés naturellement par MT5 (SL/TP touchés) seront détectés
au max 60s après (intervalle scheduler mt5_sync)."
```

---

### Task 6 — Déploiement + vérification prod

**Files:**
- Aucun changement de code. Commandes de déploiement uniquement.

- [ ] **Step 6.1 : Push main**

```bash
cd C:/Users/xav91/Scalping/scalping && git push origin main
```

- [ ] **Step 6.2 : Pull + build + restart sur EC2**

```bash
ssh -i C:/Users/xav91/Scalping/scalping/scalping-key.pem ec2-user@100.103.107.75 \
  'cd /home/ec2-user/scalping && sudo git pull && \
   sudo docker build -t scalping-radar:latest . && \
   sudo systemctl restart scalping && sleep 4 && sudo systemctl is-active scalping'
```

Expected: `active`.

- [ ] **Step 6.3 : Attendre un cycle mt5_sync (60s)**

Un cycle mt5_sync tourne toutes les 60s. Attendre et vérifier les logs :
```bash
ssh -i C:/Users/xav91/Scalping/scalping/scalping-key.pem ec2-user@100.103.107.75 \
  'sleep 75 && sudo docker logs --since 2m scalping-radar 2>&1 | grep -E "mt5_sync|reconciled" | tail -20'
```

Expected: au moins une ligne `mt5_sync: Sync bridge MT5 → personal_trades` executed successfully. Si un trade s'est fermé, une ligne `mt5_sync: X closures reconciled`.

- [ ] **Step 6.4 : Vérifier l'état DB**

```bash
ssh -i C:/Users/xav91/Scalping/scalping/scalping-key.pem ec2-user@100.103.107.75 \
  'sudo sqlite3 /opt/scalping/data/trades.db "SELECT mt5_ticket, status, exit_price, pnl FROM personal_trades WHERE is_auto=1 ORDER BY id DESC LIMIT 10"'
```

Expected : pour les tickets fermés côté MT5 depuis le début du cycle, `status='CLOSED'` avec `pnl` renseigné.

- [ ] **Step 6.5 : Smoke /deals pour un ticket fermé connu**

```bash
VPS_KEY=$(tr -d '\r\n' < C:/Scalping/vps-credentials/vps-bridge-api-key.txt)
curl -s -H "X-API-Key: $VPS_KEY" "http://100.74.160.72:8787/deals?ticket=66598763" | python -m json.tool
```

Expected : payload `{"closed": true, "exit_price": ..., "pnl": ..., "closed_at": "..."}`.

- [ ] **Step 6.6 : Mettre à jour la mémoire claude**

Marquer le chantier 1.5 comme fait dans `project_scalping_next_steps.md` et ajouter commit dans `project_scalping_current_phase.md`.

---

## Self-review

- [ ] **Spec coverage check** :
  - B.1 (endpoint /deals) → Task 1 ✓
  - B.2 (_reconcile_open_trades) → Task 4 ✓
  - B.3 (idempotence) → Task 4 test idempotent ✓
  - B.4 (périodicité) → Task 5 (intégration dans sync_from_bridge qui tourne déjà toutes les 60s) ✓
  - Tests 1-5 de la section Tests de la spec → tous couverts par Task 4 ✓
  - Déploiement → Task 1 (bridge) + Task 6 (radar) ✓
  - Rollback : documenté dans la spec, commandes dans Task 1.5 + standard git revert pour radar.

- [ ] **Placeholder scan** : aucun TBD / TODO / "similar to" / "etc". Toutes les steps ont du code concret.

- [ ] **Type consistency** : `_select_open_auto_tickets` retourne `set[int]`, utilisé cohéremment dans les tests et dans `_reconcile_open_trades`. `data.get("closed")` testé sur `True`, `None` et `False` implicite (géré par les deux `elif` cas). `_update_closed_trade` signature respectée (dict avec `ticket`, `exit_price`, `pnl`, `created_at`).

Pas de gap détecté.

---

## Risques connus

- **Task 1.1 complexité accès VPS** : l'accès SSH au VPS Windows via ProxyCommand peut ne pas marcher. Backup : RDP manuel + copier-coller du bloc. Acceptable car one-shot.
- **`mt5.history_deals_get` comportement** : en théorie retourne tous les deals liés à la `position=ticket`. Si Pepperstone Demo a un comportement différent (ex: splitting du ticket), les tests d'intégration de Task 6.5 révéleront.
- **Latence 60s détection** : acceptable pour la phase d'observation, pas pour du copy-trading temps réel (hors scope).

---
