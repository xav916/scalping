"""`check_demotion` juge un compte sur SES trades (2026-09-04).

Troisième chemin démo → réel de la journée, après l'admission (`fcdf6c0`) et
le disjoncteur de rafale. Le plus direct des trois :

    def check_demotion(pair, direction, destination):       # 'admin_live'
        trades = _query_trades_pnl(pair, direction, _iso_since(7))   # SANS destination
        ...  drawdown > 10 %  ->  rétrograde admin_live

⇒ **une mauvaise semaine sur la DÉMO pouvait rétrograder une paire du compte
RÉEL.** Le juge écrivait pourtant bien une ligne par destination — c'est la
DONNÉE qui était globale, pas l'écriture. Une portée correcte à l'écriture ne
vaut rien si la lecture, elle, mélange tout.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture()
def base(tmp_path, monkeypatch):
    import backend.services.promotion_engine as pe
    import backend.services.trade_log_service as t

    chemin = tmp_path / "trades.db"
    monkeypatch.setattr(t, "_DB_PATH", chemin, raising=False)
    monkeypatch.setattr(pe, "_db_path", lambda: str(chemin), raising=False)
    t._init_schema()
    return pe, chemin


def _trade(chemin, pnl, destination, pair="XAU/USD", direction="buy", n=1):
    c = sqlite3.connect(chemin)
    cols = [r[1] for r in c.execute("PRAGMA table_info(personal_trades)")]
    quand = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    for _ in range(n):
        vals = {"user": "admin", "pair": pair, "direction": direction,
                "entry_price": 4400.0, "stop_loss": 4380.0, "take_profit": 4440.0,
                "size_lot": 0.01, "status": "CLOSED", "pnl": pnl, "is_auto": 1,
                "close_reason": "SL", "destination_id": destination,
                "created_at": quand, "closed_at": quand}
        u = {k: v for k, v in vals.items() if k in cols}
        c.execute(f"INSERT INTO personal_trades ({','.join(u)}) "
                  f"VALUES ({','.join('?' * len(u))})", tuple(u.values()))
    c.commit()
    c.close()


def test_le_verdict_du_REEL_ignore_les_trades_de_DEMO(base):
    """⛔ LE test de la certification pour ce juge."""
    pe, chemin = base
    _trade(chemin, pnl=-40.0, destination="admin_legacy", n=20)

    trades = pe._query_trades_pnl("XAU/USD", "buy", pe._iso_since(7),
                                  destination="admin_live")
    assert trades == [], "aucune perte de démo ne doit peser sur le verdict du réel"


def test_le_verdict_du_REEL_lit_bien_ses_propres_trades(base):
    pe, chemin = base
    _trade(chemin, pnl=-4.0, destination="admin_live", n=6)

    trades = pe._query_trades_pnl("XAU/USD", "buy", pe._iso_since(7),
                                  destination="admin_live")
    assert len(trades) == 6


def test_le_verdict_de_la_DEMO_ignore_les_trades_du_REEL(base):
    """La séparation vaut dans les deux sens, sinon ce n'est pas une séparation."""
    pe, chemin = base
    _trade(chemin, pnl=-40.0, destination="admin_live", n=20)
    _trade(chemin, pnl=+2.0, destination="admin_legacy", n=3)

    trades = pe._query_trades_pnl("XAU/USD", "buy", pe._iso_since(7),
                                  destination="admin_legacy")
    assert len(trades) == 3
    assert all(t["pnl"] > 0 for t in trades)


def test_sans_destination_la_portee_reste_globale(base):
    """Compatibilité : les appelants qui ne la passent pas ne changent pas."""
    pe, chemin = base
    _trade(chemin, pnl=-4.0, destination="admin_live", n=5)
    _trade(chemin, pnl=-4.0, destination="admin_legacy", n=5)

    assert len(pe._query_trades_pnl("XAU/USD", "buy", pe._iso_since(7))) == 10
