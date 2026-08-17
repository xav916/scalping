"""La cause de clôture doit venir du COURTIER, pas d'une devinette de prix.

Mesuré le 2026-08-17 : trois positions XAU/USD fermées À LA MAIN par
l'utilisateur ont été enregistrées `TRAILING_SL`, alors que `/deals` répondait
`reason: MANUAL` pour les trois tickets.

Deux défauts empilés, chacun suffisant seul :

1. `_log_closed_position` (bridge) itère les deals, a `d.reason` sous la main,
   et ne l'écrit PAS dans la ligne d'audit.
2. Le chemin `/audit` arrive donc sans cause, la DEVINE par proximité de prix
   (gain positif + stop déplacé ⇒ TRAILING_SL), et
   `close_reason = COALESCE(close_reason, ?)` interdit ensuite définitivement
   au réconciliateur d'y substituer le `MANUAL` du courtier.

Conséquence analytique : les sorties décidées à la main — souvent gagnantes —
viennent grossir le tas du stop suiveur, précisément le mécanisme désarmé le
2026-08-11 pour destruction de valeur (−0,329 R/trade). Les statistiques par
`close_reason` le créditaient de +15,90 € par sortie ; c'est ce bug qui payait
une partie de la différence.

⛔ Le correctif ne consiste PAS à mieux deviner : il consiste à DEMANDER, au
bridge d'où vient la ligne d'audit, avant de se rabattre sur l'heuristique.
"""
import sqlite3
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from backend.services import mt5_sync


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Mock d'httpx.AsyncClient retournant des réponses prédéfinies par URL.

    Enregistre les URL demandées : c'est la seule façon de prouver que le
    correctif INTERROGE le bridge au lieu de deviner en silence.
    """

    def __init__(self, responses, appels):
        self._responses = responses
        self._appels = appels

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, params=None):
        key = url
        if params and "ticket" in params:
            key = f"{url}?ticket={params['ticket']}"
        self._appels.append(key)
        if key not in self._responses:
            raise httpx.ConnectError(f"no mock for {key}")
        resp = self._responses[key]
        if isinstance(resp, Exception):
            raise resp
        return resp


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "trades.db"
    conn = sqlite3.connect(db_file)
    conn.execute("""
        CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY,
            user TEXT, pair TEXT, direction TEXT,
            entry_price REAL, stop_loss REAL, take_profit REAL,
            size_lot REAL, status TEXT, created_at TEXT,
            mt5_ticket INTEGER, is_auto INTEGER, post_entry_sl INTEGER,
            exit_price REAL, pnl REAL, closed_at TEXT, close_reason TEXT
        )
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(mt5_sync, "_db_path", lambda: str(db_file))
    return str(db_file)


@pytest.fixture
def sync_isole(monkeypatch):
    """Neutralise l'état sur disque et la notification Telegram."""
    monkeypatch.setattr(mt5_sync, "_load_state", lambda: {"bridges": {}})
    monkeypatch.setattr(mt5_sync, "_save_state", lambda state: None)
    monkeypatch.setattr(mt5_sync, "_notify_close_telegram", AsyncMock())


def _trade_ouvert(db_path, ticket):
    """Une position or gagnante dont le stop a bougé après l'entrée.

    C'est exactement la configuration qui piège l'heuristique : gain positif
    sous la cible + `post_entry_sl` ⇒ elle conclut TRAILING_SL. Valeurs
    reprises du ticket réel 84430875 du 2026-08-17.
    """
    with sqlite3.connect(db_path) as c:
        c.execute("""
            INSERT INTO personal_trades
              (user, pair, direction, entry_price, stop_loss, take_profit,
               size_lot, status, created_at, mt5_ticket, is_auto, post_entry_sl)
            VALUES ('u', 'XAU/USD', 'buy', 4398.12, 4364.24, 4459.10, 0.01,
                    'OPEN', '2026-08-17T09:18:46+00:00', ?, 1, 1)
        """, (ticket,))


def _cause_en_base(db_path, ticket):
    with sqlite3.connect(db_path) as c:
        return c.execute(
            "SELECT close_reason FROM personal_trades WHERE mt5_ticket=?",
            (ticket,),
        ).fetchone()[0]


@pytest.mark.asyncio
async def test_cloture_manuelle_nest_pas_etiquetee_stop_suiveur(temp_db, sync_isole):
    """Le cas réel du 2026-08-17 : trois ors fermés à la main, lus TRAILING_SL.

    La ligne d'audit du bridge ne porte aucune cause. `/deals` en porte une, et
    elle fait autorité : l'heuristique ne doit même pas être consultée.
    """
    _trade_ouvert(temp_db, 84430875)

    responses = {
        "http://bridge.test/audit": _FakeResponse(200, {"orders": [{
            "id": 1, "mode": "live", "status": "closed",
            "ticket": 84430875, "exit_price": 4426.05, "pnl": 24.11,
        }]}),
        "http://bridge.test/deals?ticket=84430875": _FakeResponse(200, {
            "ticket": 84430875, "closed": True, "reason": "MANUAL",
            "exit_price": 4426.05, "pnl": 24.11,
        }),
    }
    appels: list[str] = []
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses, appels)):
        await mt5_sync._sync_one("legacy", "http://bridge.test", "key")

    assert _cause_en_base(temp_db, 84430875) == "MANUAL"
    assert "http://bridge.test/deals?ticket=84430875" in appels


@pytest.mark.asyncio
async def test_lheuristique_reste_le_repli_quand_le_courtier_se_tait(temp_db, sync_isole):
    """Un `/deals` sans cause ne doit pas faire perdre ce qu'on savait déduire.

    ⚠️ Garde anti-régression : le correctif ne remplace pas l'heuristique, il
    passe devant. Une sortie en gain sous la cible avec stop déplacé reste un
    stop suiveur tant que personne ne dit le contraire.
    """
    _trade_ouvert(temp_db, 900)

    responses = {
        "http://bridge.test/audit": _FakeResponse(200, {"orders": [{
            "id": 1, "mode": "live", "status": "closed",
            "ticket": 900, "exit_price": 4426.05, "pnl": 24.11,
        }]}),
        "http://bridge.test/deals?ticket=900": _FakeResponse(200, {
            "ticket": 900, "closed": True, "exit_price": 4426.05,
        }),
    }
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses, [])):
        await mt5_sync._sync_one("legacy", "http://bridge.test", "key")

    assert _cause_en_base(temp_db, 900) == "TRAILING_SL"


@pytest.mark.asyncio
async def test_bridge_muet_sur_deals_ne_bloque_pas_la_cloture(temp_db, sync_isole):
    """`/deals` injoignable ne doit ni lever, ni laisser le trade OPEN.

    Cf. [[feedback_detection_par_absence]] : une source muette n'est pas une
    source vide. Ici on ne DÉDUIT rien de son silence — on se contente de
    retomber sur ce que l'heuristique sait établir, et la clôture est
    enregistrée quand même.
    """
    _trade_ouvert(temp_db, 901)

    responses = {
        "http://bridge.test/audit": _FakeResponse(200, {"orders": [{
            "id": 1, "mode": "live", "status": "closed",
            "ticket": 901, "exit_price": 4426.05, "pnl": 24.11,
        }]}),
        "http://bridge.test/deals?ticket=901": httpx.ConnectError("bridge down"),
    }
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses, [])):
        await mt5_sync._sync_one("legacy", "http://bridge.test", "key")

    with sqlite3.connect(temp_db) as c:
        status, cause = c.execute(
            "SELECT status, close_reason FROM personal_trades WHERE mt5_ticket=?",
            (901,),
        ).fetchone()
    assert status == "CLOSED"
    assert cause == "TRAILING_SL"


@pytest.mark.asyncio
async def test_la_cause_deja_portee_par_laudit_ne_declenche_aucun_appel(temp_db, sync_isole):
    """Si la ligne d'audit porte déjà la cause, ne pas aller la redemander.

    Le bridge finira par l'écrire (le correctif côté `_log_closed_position`) ;
    ce jour-là, cet aller-retour HTTP par clôture doit disparaître de lui-même.
    """
    _trade_ouvert(temp_db, 902)

    responses = {
        "http://bridge.test/audit": _FakeResponse(200, {"orders": [{
            "id": 1, "mode": "live", "status": "closed",
            "ticket": 902, "exit_price": 4426.05, "pnl": 24.11,
            "close_reason": "DEAL_REASON_CLIENT",
        }]}),
    }
    appels: list[str] = []
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses, appels)):
        await mt5_sync._sync_one("legacy", "http://bridge.test", "key")

    assert _cause_en_base(temp_db, 902) == "MANUAL"
    assert not [a for a in appels if "/deals" in a]
