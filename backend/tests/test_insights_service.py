"""Tests du service d'insights de performance."""
import json
import sqlite3

import pytest

from backend.services import insights_service


@pytest.fixture
def db(tmp_path, monkeypatch):
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
    monkeypatch.setattr(insights_service, "_db_path", lambda: str(db_file))
    return str(db_file)


def _insert(db, **kw):
    defaults = {
        "user": "u", "pair": "EUR/USD", "direction": "buy",
        "entry_price": 1.1, "stop_loss": 1.09, "take_profit": 1.12,
        "size_lot": 0.1, "status": "CLOSED", "is_auto": 1,
        "created_at": "2026-04-21T10:00:00+00:00",
        "signal_confidence": 70.0, "pnl": 5.0, "mt5_ticket": 1,
        "context_macro": json.dumps({"risk_regime": "neutral"}),
    }
    defaults.update(kw)
    cols = ",".join(defaults.keys())
    ph = ",".join("?" * len(defaults))
    with sqlite3.connect(db) as c:
        c.execute(f"INSERT INTO personal_trades ({cols}) VALUES ({ph})", tuple(defaults.values()))


def test_empty_db_returns_no_data(db):
    out = insights_service.get_performance()
    assert out["total_trades"] == 0


def test_excludes_non_auto_trades(db):
    _insert(db, is_auto=0, mt5_ticket=10)
    assert insights_service.get_performance()["total_trades"] == 0


def test_excludes_open_trades(db):
    _insert(db, status="OPEN", mt5_ticket=20)
    assert insights_service.get_performance()["total_trades"] == 0


def test_excludes_null_pnl(db):
    _insert(db, pnl=None, mt5_ticket=30)
    assert insights_service.get_performance()["total_trades"] == 0


def test_global_stats_basic(db):
    _insert(db, pnl=10.0, mt5_ticket=1)
    _insert(db, pnl=-5.0, mt5_ticket=2)
    _insert(db, pnl=3.0, mt5_ticket=3)

    out = insights_service.get_performance()
    assert out["total_trades"] == 3
    assert out["win_rate"] == pytest.approx(2 / 3, rel=1e-3)
    assert out["total_pnl"] == 8.0
    assert out["avg_pnl"] == pytest.approx(8 / 3, rel=1e-2)
    assert out["total_losses"] == -5.0


def test_by_score_bucket(db):
    # 2 trades dans 55-65, 1 trade dans 75-85
    _insert(db, signal_confidence=58, pnl=1.0, mt5_ticket=1)
    _insert(db, signal_confidence=62, pnl=-2.0, mt5_ticket=2)
    _insert(db, signal_confidence=80, pnl=10.0, mt5_ticket=3)

    out = insights_service.get_performance()
    buckets = {b["bucket"]: b for b in out["by_score_bucket"]}
    assert "55-65" in buckets
    assert buckets["55-65"]["count"] == 2
    assert buckets["55-65"]["wins"] == 1
    assert "75-85" in buckets
    assert buckets["75-85"]["count"] == 1
    assert buckets["75-85"]["win_rate"] == 1.0


def test_by_asset_class_detects_forex_metal_crypto(db):
    _insert(db, pair="EUR/USD", pnl=1.0, mt5_ticket=1)
    _insert(db, pair="XAU/USD", pnl=2.0, mt5_ticket=2)
    _insert(db, pair="BTC/USD", pnl=3.0, mt5_ticket=3)

    out = insights_service.get_performance()
    classes = {b["bucket"]: b for b in out["by_asset_class"]}
    assert classes["forex"]["count"] == 1
    assert classes["metal"]["count"] == 1
    assert classes["crypto"]["count"] == 1


def test_by_risk_regime_from_context_macro(db):
    _insert(db, context_macro=json.dumps({"risk_regime": "risk_on"}), pnl=1.0, mt5_ticket=1)
    _insert(db, context_macro=json.dumps({"risk_regime": "risk_off"}), pnl=-1.0, mt5_ticket=2)
    _insert(db, context_macro=json.dumps({"risk_regime": "risk_off"}), pnl=-2.0, mt5_ticket=3)

    out = insights_service.get_performance()
    regimes = {b["bucket"]: b for b in out["by_risk_regime"]}
    assert regimes["risk_on"]["count"] == 1
    assert regimes["risk_off"]["count"] == 2
    assert regimes["risk_off"]["win_rate"] == 0.0


def test_null_signal_confidence_not_in_score_bucket(db):
    """Trades anciens avec confidence=NULL ne sont pas groupés par score."""
    _insert(db, signal_confidence=None, pnl=5.0, mt5_ticket=1)
    _insert(db, signal_confidence=70, pnl=3.0, mt5_ticket=2)

    out = insights_service.get_performance()
    assert out["total_trades"] == 2
    total_in_buckets = sum(b["count"] for b in out["by_score_bucket"])
    assert total_in_buckets == 1


def test_since_filter(db):
    _insert(db, created_at="2026-04-19T10:00:00+00:00", pnl=1.0, mt5_ticket=1)
    _insert(db, created_at="2026-04-21T10:00:00+00:00", pnl=2.0, mt5_ticket=2)

    out = insights_service.get_performance(since_iso="2026-04-20T00:00:00+00:00")
    assert out["total_trades"] == 1
    assert out["total_pnl"] == 2.0


def test_by_direction(db):
    _insert(db, direction="buy", pnl=1.0, mt5_ticket=1)
    _insert(db, direction="buy", pnl=2.0, mt5_ticket=2)
    _insert(db, direction="sell", pnl=-3.0, mt5_ticket=3)

    out = insights_service.get_performance()
    dirs = {b["bucket"]: b for b in out["by_direction"]}
    assert dirs["buy"]["count"] == 2
    assert dirs["sell"]["count"] == 1
    assert dirs["sell"]["win_rate"] == 0.0
