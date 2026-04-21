"""Tests du logging ML-ready : table `signals`, matching signal_id,
nouvelles colonnes personal_trades."""
from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.services import backtest_service, mt5_sync, trade_log_service


def _cols(db: Path, table: str) -> list[str]:
    conn = sqlite3.connect(db)
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    finally:
        conn.close()


def _build_setup(
    pair: str = "EUR/USD",
    direction: str = "buy",
    entry: float = 1.1000,
    sl: float = 1.0950,
    tp1: float = 1.1050,
    tp2: float = 1.1100,
    confidence: float = 78.0,
    verdict: str = "TAKE",
):
    """TradeSetup factice assez fidele pour record_signals()."""
    return SimpleNamespace(
        pair=pair,
        direction=SimpleNamespace(value=direction),
        entry_price=entry,
        stop_loss=sl,
        take_profit_1=tp1,
        take_profit_2=tp2,
        risk_pips=50.0,
        reward_pips_1=50.0,
        reward_pips_2=100.0,
        risk_reward_1=1.0,
        risk_reward_2=2.0,
        confidence_score=confidence,
        confidence_factors=[
            SimpleNamespace(name="Pattern", score=80.0, detail="breakout up"),
        ],
        pattern=SimpleNamespace(
            pattern=SimpleNamespace(value="breakout_up"),
            confidence=0.8,
        ),
        asset_class="forex",
        verdict_action=verdict,
        verdict_reasons=["trend aligned"],
        verdict_warnings=[],
        verdict_blockers=[],
        is_simulated=False,
    )


def test_signals_table_persists_all_setups(tmp_path: Path):
    """record_signals() ecrit chaque setup, y compris les SKIP."""
    db = tmp_path / "bt.db"
    setups = [
        _build_setup(pair="EUR/USD", confidence=82, verdict="TAKE"),
        _build_setup(pair="XAU/USD", confidence=45, verdict="SKIP"),
    ]

    with patch.object(backtest_service, "_DB_PATH", db), patch(
        "backend.services.macro_context_service.get_macro_snapshot",
        return_value=None,
    ):
        backtest_service.record_signals(setups)

    assert "signals" in {
        r[0] for r in sqlite3.connect(db).execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    rows = sqlite3.connect(db).execute(
        "SELECT pair, direction, verdict_action, confidence_score FROM signals ORDER BY id"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0][0] == "EUR/USD" and rows[0][2] == "TAKE"
    # Le setup SKIP est bien archive (faux negatif potentiel).
    assert rows[1][0] == "XAU/USD" and rows[1][2] == "SKIP"


def test_find_signal_for_order_matches_recent(tmp_path: Path):
    """find_signal_for_order retrouve le signal dans la fenetre de 30 min."""
    db = tmp_path / "bt.db"
    with patch.object(backtest_service, "_DB_PATH", db), patch(
        "backend.services.macro_context_service.get_macro_snapshot",
        return_value=None,
    ):
        backtest_service.record_signals([
            _build_setup(pair="EUR/USD", direction="buy", entry=1.1000),
        ])
        sid = backtest_service.find_signal_for_order("EUR/USD", "buy", 1.1001)

    assert sid is not None
    assert sid >= 1


def test_find_signal_rejects_out_of_tolerance(tmp_path: Path):
    """Entry plus de 0.1% loin → pas de match (evite les faux positifs)."""
    db = tmp_path / "bt.db"
    with patch.object(backtest_service, "_DB_PATH", db), patch(
        "backend.services.macro_context_service.get_macro_snapshot",
        return_value=None,
    ):
        backtest_service.record_signals([
            _build_setup(pair="EUR/USD", entry=1.1000),
        ])
        # 1.2000 vs 1.1000 : ecart de ~9%, hors tolerance.
        sid = backtest_service.find_signal_for_order("EUR/USD", "buy", 1.2000)

    assert sid is None


def test_find_signal_ignores_old_entries(tmp_path: Path):
    """Un signal emis il y a plus de `within_minutes` ne matche pas."""
    db = tmp_path / "bt.db"
    # On insere manuellement avec un emitted_at ancien.
    with patch.object(backtest_service, "_DB_PATH", db):
        backtest_service._init_schema()
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with sqlite3.connect(db) as c:
            c.execute(
                "INSERT INTO signals (emitted_at, pair, direction, entry_price) "
                "VALUES (?, ?, ?, ?)",
                (old, "EUR/USD", "buy", 1.1000),
            )
        sid = backtest_service.find_signal_for_order(
            "EUR/USD", "buy", 1.1000, within_minutes=30
        )
    assert sid is None


def test_personal_trades_gets_ml_columns():
    """Migration idempotente : signal_id / fill_price / slippage_pips /
    close_reason apparaissent."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "trades.db"
        with patch.object(trade_log_service, "_DB_PATH", db):
            trade_log_service._init_schema()
            trade_log_service._init_schema()  # idempotent
            cols = _cols(db, "personal_trades")

    for expected in ("signal_id", "fill_price", "slippage_pips", "close_reason"):
        assert expected in cols


def test_upsert_open_trade_computes_slippage_and_links_signal(
    tmp_path: Path, monkeypatch
):
    """Un fill avec fill_price != entry doit calculer slippage_pips et
    retrouver le signal d'origine."""
    trades_db = tmp_path / "trades.db"
    bt_db = tmp_path / "bt.db"

    with patch.object(trade_log_service, "_DB_PATH", trades_db), patch.object(
        backtest_service, "_DB_PATH", bt_db
    ), patch(
        "backend.services.macro_context_service.get_macro_snapshot",
        return_value=None,
    ):
        trade_log_service._init_schema()
        # Signal emis juste avant le fill.
        backtest_service.record_signals([
            _build_setup(pair="EUR/USD", direction="buy", entry=1.1000),
        ])

        # Fill 1.1002 = slippage defavorable de 2 pips pour un BUY.
        mt5_sync._upsert_open_trade(
            {
                "ticket": 999,
                "pair": "EUR/USD",
                "direction": "buy",
                "entry": 1.1000,
                "fill_price": 1.1002,
                "sl": 1.0950,
                "tp": 1.1050,
                "lots": 0.10,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            user="test",
        )

        with sqlite3.connect(trades_db) as c:
            row = c.execute(
                "SELECT signal_id, fill_price, slippage_pips "
                "FROM personal_trades WHERE mt5_ticket = ?",
                (999,),
            ).fetchone()

    assert row is not None
    signal_id, fill_price, slippage = row
    assert signal_id is not None
    assert fill_price == 1.1002
    # BUY @1.1000, execute @1.1002 → defavorable → slippage negatif.
    assert slippage == -2.0


def test_normalize_close_reason_maps_variants():
    """Le bridge peut renvoyer "TP_HIT", "stoploss", "manual_close"... →
    on veut des libelles stables."""
    assert mt5_sync._normalize_close_reason("TP_HIT") == "TP1"
    assert mt5_sync._normalize_close_reason("take_profit_2") == "TP2"
    assert mt5_sync._normalize_close_reason("stoploss") == "SL"
    assert mt5_sync._normalize_close_reason("Manual close") == "MANUAL"
    assert mt5_sync._normalize_close_reason(None) is None
