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
            context_macro TEXT, exit_price REAL, pnl REAL, closed_at TEXT,
            signal_id INTEGER, fill_price REAL, slippage_pips REAL, close_reason TEXT,
            sl_at_close REAL, tp_at_close REAL, niveaux_source TEXT
        )
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(mt5_sync, "_db_path", lambda: str(db_file))
    return str(db_file)


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


def test_mark_ticket_closed_no_deal_updates_status_only(temp_db):
    _insert_trade(temp_db, 300, status="OPEN", is_auto=1)

    mt5_sync._mark_ticket_closed_no_deal(300)

    with sqlite3.connect(temp_db) as c:
        row = c.execute(
            "SELECT status, exit_price, pnl, closed_at FROM personal_trades WHERE mt5_ticket=?",
            (300,),
        ).fetchone()
    assert row[0] == "CLOSED"
    assert row[1] is None
    assert row[2] is None
    assert row[3] is not None


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
    assert closed_at == "2026-04-20T21:00:00+00:00"


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
    # Le bridge réel est lu dans l'environnement : le neutraliser par défaut,
    # sinon un `.env` chargé sur la machine de test ferait interroger une URL
    # non simulée et le résultat dépendrait du poste.
    monkeypatch.delenv("MT5_BRIDGE_LIVE_URL", raising=False)
    monkeypatch.delenv("MT5_BRIDGE_LIVE_API_KEY", raising=False)


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
            (500,),
        ).fetchone()
    assert row[0] == "CLOSED"
    assert row[1] == 1.1234
    assert row[2] == -12.5
    # 21:30 est l'heure de l'horloge du courtier (UTC+3) que `/deals`
    # étiquette `+00:00` ; la base doit porter l'UTC réel.
    assert row[3] == "2026-04-20T18:30:00+00:00"


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
            (600,),
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
    """Un ticket déjà CLOSED en DB n'est plus dans open_tickets, donc jamais touché."""
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

    responses = {
        "http://bridge.test/positions": _FakeResponse(200, {"positions": []}),
    }
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses)):
        await mt5_sync._reconcile_open_trades()

    with sqlite3.connect(temp_db) as c:
        row = c.execute(
            "SELECT status, exit_price, pnl, closed_at FROM personal_trades WHERE mt5_ticket=?",
            (800,),
        ).fetchone()
    assert row == ("CLOSED", 1.15, 50.0, "2026-04-20T20:30:00+00:00")


@pytest.mark.asyncio
async def test_sync_from_bridge_calls_reconcile_even_when_audit_empty(temp_db, mock_bridge_config):
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


@pytest.mark.asyncio
async def test_reconcile_forwards_broker_reason_instead_of_guessing(
    temp_db, mock_bridge_config
):
    """La cause remontée par MT5 doit atteindre la base, pas l'heuristique.

    Depuis la mise à jour du bridge (2026-08-10), `/deals` renvoie `reason`,
    lu directement de `DEAL_REASON_*`. Sans ce transfert, `_update_closed_trade`
    ne reçoit rien et retombe sur `_derive_close_reason_from_exit`, qui situe le
    prix de sortie par rapport aux SL/TP stockés — donc ne peut JAMAIS conclure
    "MANUAL". C'est ce qui a étiqueté `INDETERMINE` la fermeture à la main du
    ticket 83627188 le 2026-08-13, alors que le courtier disait `MANUAL`.

    Le prix de sortie choisi ici (au-delà du TP) ferait dire "TP1" à
    l'heuristique : le test échoue tant que la cause du courtier ne prime pas.
    """
    _insert_trade(temp_db, 900, status="OPEN", is_auto=1)

    responses = {
        "http://bridge.test/positions": _FakeResponse(200, {"positions": []}),
        "http://bridge.test/deals?ticket=900": _FakeResponse(200, {
            "ticket": 900, "closed": True,
            "exit_price": 1.13, "pnl": 30.0,
            "reason": "MANUAL",
            "closed_at": "2026-04-20T21:30:00+00:00",
        }),
    }
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses)):
        await mt5_sync._reconcile_open_trades()

    with sqlite3.connect(temp_db) as c:
        row = c.execute(
            "SELECT status, close_reason FROM personal_trades WHERE mt5_ticket=?",
            (900,),
        ).fetchone()
    assert row == ("CLOSED", "MANUAL")


@pytest.mark.asyncio
async def test_ticket_open_on_live_bridge_is_not_declared_closed(
    temp_db, mock_bridge_config, monkeypatch
):
    """Un ticket ouvert sur le bridge RÉEL ne doit pas être déclaré fermé.

    `_reconcile_open_trades` n'interrogeait que `MT5_BRIDGE_URL` (le démo).
    Un ticket du compte réel lui étant inconnu, `/positions` ne le contenait
    pas et `/deals` répondait `closed=None` — lu comme « historique purgé »,
    donc `status=CLOSED` avec `closed_at=maintenant`.

    Mesuré le 2026-08-13 : les 16 trades réels d'août portent tous une durée
    d'exactement 1 minute, et le ticket 1353960866 (fermé à la main le 08-11)
    était daté du 08-05. Ne pas connaître un ticket n'est pas le voir fermé.
    """
    monkeypatch.setenv("MT5_BRIDGE_LIVE_URL", "http://live.test")
    monkeypatch.setenv("MT5_BRIDGE_LIVE_API_KEY", "livekey")
    _insert_trade(temp_db, 950, status="OPEN", is_auto=1)

    responses = {
        # le démo ne connaît pas ce ticket
        "http://bridge.test/positions": _FakeResponse(200, {"positions": []}),
        "http://bridge.test/deals?ticket=950": _FakeResponse(200, {
            "ticket": 950, "closed": None, "message": "no deals found",
        }),
        # ... mais il est bel et bien OUVERT sur le réel
        "http://live.test/positions": _FakeResponse(200, {
            "positions": [{"ticket": 950}]
        }),
    }
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses)):
        await mt5_sync._reconcile_open_trades()

    with sqlite3.connect(temp_db) as c:
        row = c.execute(
            "SELECT status, closed_at FROM personal_trades WHERE mt5_ticket=?",
            (950,),
        ).fetchone()
    assert row == ("OPEN", None)


@pytest.mark.asyncio
async def test_closure_read_from_the_bridge_that_owns_the_ticket(
    temp_db, mock_bridge_config, monkeypatch
):
    """Une clôture du compte réel se lit sur le bridge du réel.

    Le démo répond `closed=None` (ticket inconnu) ; sa réponse ne doit pas
    l'emporter sur celle du bridge qui détient réellement le deal, sinon la
    ligne finit CLOSED sans prix, sans P&L et avec `closed_at=maintenant` —
    ce qui datait le ticket 1353960866 six jours trop tôt.
    """
    monkeypatch.setenv("MT5_BRIDGE_LIVE_URL", "http://live.test")
    monkeypatch.setenv("MT5_BRIDGE_LIVE_API_KEY", "livekey")
    _insert_trade(temp_db, 960, status="OPEN", is_auto=1)

    responses = {
        "http://bridge.test/positions": _FakeResponse(200, {"positions": []}),
        "http://live.test/positions": _FakeResponse(200, {"positions": []}),
        "http://bridge.test/deals?ticket=960": _FakeResponse(200, {
            "ticket": 960, "closed": None, "message": "no deals found",
        }),
        "http://live.test/deals?ticket=960": _FakeResponse(200, {
            "ticket": 960, "closed": True,
            "exit_price": 4363.03, "pnl": -13.64, "reason": "SL",
            "closed_at": "2026-08-11T09:29:17+00:00",
        }),
    }
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses)):
        await mt5_sync._reconcile_open_trades()

    with sqlite3.connect(temp_db) as c:
        row = c.execute(
            "SELECT status, exit_price, pnl, close_reason FROM personal_trades "
            " WHERE mt5_ticket=?",
            (960,),
        ).fetchone()
    assert row == ("CLOSED", 4363.03, -13.64, "SL")


@pytest.mark.asyncio
async def test_deals_closed_at_is_read_off_the_broker_clock(
    temp_db, mock_bridge_config
):
    """`/deals` étiquette `+00:00` une heure lue sur l'horloge du COURTIER.

    Le bridge construit ce champ avec
    `datetime.fromtimestamp(deal.time, tz=timezone.utc)` : il prend un
    horodatage exprimé en heure SERVEUR pour de l'epoch. Le serveur d'IC
    Markets tourne à UTC+3 (établi le 2026-08-13 par trois voies
    indépendantes), donc une clôture atterrit **3 h dans le futur**.

    Jamais observé en production parce que le chemin `/audit` gagne toujours
    la course et pose sa propre date — mais `closed_at` est protégé par
    `COALESCE` : le jour où `/audit` se tait, la valeur fausse devient
    définitive. Cf. [[project_close_reason_devinee_2026_08_17]].
    """
    _insert_trade(temp_db, 970, status="OPEN", is_auto=1)

    responses = {
        "http://bridge.test/positions": _FakeResponse(200, {"positions": []}),
        "http://bridge.test/deals?ticket=970": _FakeResponse(200, {
            "ticket": 970, "closed": True,
            "exit_price": 1.13, "pnl": 12.0, "reason": "SL",
            # heure serveur courtier, étiquetée UTC par le bridge
            "closed_at": "2026-08-17T20:11:10+00:00",
        }),
    }
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses)):
        await mt5_sync._reconcile_open_trades()

    with sqlite3.connect(temp_db) as c:
        closed_at = c.execute(
            "SELECT closed_at FROM personal_trades WHERE mt5_ticket=?", (970,)
        ).fetchone()[0]

    assert closed_at == "2026-08-17T17:11:10+00:00"


def test_broker_clock_correction_leaves_a_naive_or_unreadable_value_alone():
    """Ne pas corriger ce qu'on n'a pas su lire.

    Une date illisible rendue décalée de 3 h serait pire que rendue telle
    quelle : on inventerait une précision qu'on n'a pas.
    Cf. [[feedback_detection_par_absence]].
    """
    assert mt5_sync._heure_reelle_de_cloture(None) is None
    assert mt5_sync._heure_reelle_de_cloture("") == ""
    assert mt5_sync._heure_reelle_de_cloture("pas une date") == "pas une date"
