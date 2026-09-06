"""Canal Radar restreint à l'argent réel (2026-08-04).

Architecture décidée : un bot = une question.

    Scalping Radar    → « qu'est-ce qui se passe sur mon argent »
    Xav Scalping Infra → « est-ce que la machine tourne »
    Radar Sales        → « où j'en suis »

Le canal Radar recevait aussi les trades Demo, qui n'engagent rien : la
moitié du volume pour zéro décision. Ils restent visibles dans le récap.

⚠️ `personal_trades` ne porte pas de `destination_id` : le chemin de clôture
ignore chez quel broker le trade a eu lieu. On le résout depuis `mt5_pushes`
via le ticket — exact, plutôt qu'une heuristique sur le format du numéro.
Deviner sur de l'argent réel n'est pas acceptable.
"""
from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from backend.services import telegram_service as ts



@pytest.fixture(autouse=True)
def _fils_par_compte(monkeypatch):
    """Depuis le 06/09, chaque compte a SON bot : un harnais qui n'en gree
    qu'un seul ferait retomber tous les envois sur infra, donc sur rien."""
    import config.settings as _s
    for var in ("SALES_TELEGRAM_BOT_TOKEN", "TRADES_TELEGRAM_BOT_TOKEN",
                "TELEGRAM_BOT_TOKEN", "INFRA_TELEGRAM_BOT_TOKEN"):
        monkeypatch.setattr(_s, var, "T", raising=False)
    for var in ("SALES_TELEGRAM_CHAT_ID", "TRADES_TELEGRAM_CHAT_ID",
                "TELEGRAM_CHAT_ID", "INFRA_TELEGRAM_CHAT_ID"):
        monkeypatch.setattr(_s, var, "1", raising=False)

@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    from backend.services import trade_log_service
    db = tmp_path / "trades.db"
    monkeypatch.setattr(trade_log_service, "_DB_PATH", db)
    with sqlite3.connect(db) as c:
        c.execute("""CREATE TABLE mt5_pushes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, destination_id TEXT,
            date TEXT, pair TEXT, direction TEXT, entry_price_5dp TEXT,
            pushed_at TEXT, ok INTEGER, bridge_response TEXT)""")
    ts._notified_closes.clear()
    return db


def _push(db, dest, ticket):
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO mt5_pushes (destination_id, bridge_response) VALUES (?, ?)",
                  (dest, '{"ok": true, "ticket": %s, "volume": 0.02}' % ticket))


def _capture(monkeypatch):
    envoyes = []

    class _R:
        status_code, text = 200, "ok"

    class _C:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, **kw):
            envoyes.append(json)
            return _R()

    monkeypatch.setattr(ts, "is_configured", lambda: True)
    monkeypatch.setattr(ts, "_destinataires", lambda: [("x", "1")])
    monkeypatch.setattr(ts, "TELEGRAM_BOT_TOKEN", "T", raising=False)
    monkeypatch.setattr(ts.httpx, "AsyncClient", lambda *a, **k: _C())
    return envoyes


def _setup():
    return NS(pair="XAU/USD", direction=NS(value="sell"),
              entry_price=3312.40, stop_loss=3320.10, take_profit_1=3298.54,
              take_profit_2=3290.0, risk_pips=7.7, reward_pips_1=13.86,
              reward_pips_2=22.4, risk_reward_1=1.8, risk_reward_2=2.9,
              confidence_score=74.0, asset_class="metal",
              pattern=NS(pattern=NS(value="range_bounce_down")))


# --- la déclaration argent réel -------------------------------------------

@pytest.mark.parametrize("dest,attendu", [
    ("admin_live", True),
    ("admin_kraken", True),
    ("admin_kraken_spot", True),
    ("admin_kraken_stocks", True),
    ("admin_legacy", False),
    ("admin_binance", False),
    ("user:2", False),
])
def test_qui_engage_de_l_argent_reel(dest, attendu):
    assert ts.destination_is_real_money(dest) is attendu


def test_destination_inconnue_traitee_comme_fictive():
    """Silencieux plutôt que bruyant : mieux vaut rater une notif."""
    assert ts.destination_is_real_money("admin_truc") is False
    assert ts.destination_is_real_money(None) is False


# --- l'ouverture -----------------------------------------------------------

def test_ouverture_argent_reel_notifiee(monkeypatch):
    envoyes = _capture(monkeypatch)
    asyncio.run(ts.send_trade_opened(_setup(), ticket="881", fill_price=3312.4,
                                     volume=0.02, mode="LIVE",
                                     destination_id="admin_live"))
    assert len(envoyes) == 1
    assert "IC Markets" in envoyes[0]["text"]


@pytest.mark.parametrize("dest", ["admin_binance", "user:2", None])
def test_ouverture_hors_de_NOS_comptes_reste_silencieuse(monkeypatch, dest):
    """⛔ Ces destinations n'ont pas de fil : leur message atterrirait sur
    `infra`, ou il se lirait comme un trade de la maison."""
    envoyes = _capture(monkeypatch)
    asyncio.run(ts.send_trade_opened(_setup(), ticket="881", fill_price=3312.4,
                                     volume=0.02, mode="DEMO", destination_id=dest))
    assert envoyes == []


def test_le_DEMO_recoit_desormais_ses_ouvertures(monkeypatch):
    """⛔ Il en etait exclu depuis le 2026-08-04, au motif qu'il « doublait le
    volume du canal sans rien engager ». C'etait vrai quand tout partageait UN
    SEUL fil ; depuis le decoupage par compte il a le sien, et le motif de
    l'exclusion a disparu avec sa cause.

    ⚠️ Demande explicite : etendre le message d'ouverture aux comptes reels
    ET demo qui tradent."""
    envoyes = _capture(monkeypatch)
    asyncio.run(ts.send_trade_opened(_setup(), ticket="881", fill_price=3312.4,
                                     volume=0.02, mode="DEMO",
                                     destination_id="admin_legacy"))
    assert len(envoyes) == 1


# --- la clôture, destination résolue depuis le ticket ---------------------

def test_resolution_de_la_destination_par_le_ticket(_db):
    _push(_db, "admin_live", 1353880967)
    _push(_db, "admin_legacy", 82202633)
    assert ts.destination_for_ticket(1353880967) == "admin_live"
    assert ts.destination_for_ticket(82202633) == "admin_legacy"


def test_ticket_inconnu_ne_leve_pas(_db):
    assert ts.destination_for_ticket(999999) is None
    assert ts.destination_for_ticket(None) is None


def _trade(ticket):
    return {"pair": "XAU/USD", "direction": "sell", "entry_price": 3312.40,
            "exit_price": 3298.54, "pnl": 12.47, "close_reason": "TP1",
            "mt5_ticket": ticket, "size_lot": 0.02,
            "closed_at": "2026-08-04T17:40:00+00:00"}


def test_cloture_argent_reel_notifiee(monkeypatch, _db):
    _push(_db, "admin_live", 1353880967)
    envoyes = _capture(monkeypatch)
    asyncio.run(ts.send_close(_trade(1353880967)))
    assert len(envoyes) >= 1


def test_cloture_demo_silencieuse(monkeypatch, _db):
    """Le cas concret : une clôture Pepperstone Demo ne doit plus sonner."""
    _push(_db, "admin_legacy", 82202633)
    envoyes = _capture(monkeypatch)
    asyncio.run(ts.send_close(_trade(82202633)))
    assert envoyes == []


def test_cloture_ticket_orphelin_silencieuse(monkeypatch, _db):
    """Sans push correspondant, on ne sait pas : on se tait."""
    envoyes = _capture(monkeypatch)
    asyncio.run(ts.send_close(_trade(424242)))
    assert envoyes == []


# --- les transitions ne partent plus --------------------------------------

def test_les_transitions_ne_sonnent_plus(monkeypatch):
    envoyes = _capture(monkeypatch)
    asyncio.run(ts.send_pac_transition_user("XAG/USD", "buy", "TELEGRAM",
                                            "AUTO_EXEC", "auto-promote"))
    assert envoyes == []
