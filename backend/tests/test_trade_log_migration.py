"""Verify that _init_schema() adds the context_macro column idempotently."""
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from backend.services import trade_log_service


def _cols(db: Path) -> list[str]:
    conn = sqlite3.connect(db)
    try:
        return [r[1] for r in conn.execute("PRAGMA table_info(personal_trades)").fetchall()]
    finally:
        conn.close()


def test_context_macro_column_added_on_fresh_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "test.db"
        with patch.object(trade_log_service, "_DB_PATH", db):
            trade_log_service._init_schema()
            cols = _cols(db)
        assert "context_macro" in cols


def test_init_schema_is_idempotent():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "test.db"
        with patch.object(trade_log_service, "_DB_PATH", db):
            trade_log_service._init_schema()
            trade_log_service._init_schema()  # must not raise
            cols = _cols(db)
        assert cols.count("context_macro") == 1
