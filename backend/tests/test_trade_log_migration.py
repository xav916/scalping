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


def _insert(db: Path, ticket, direction, pair="EUR/USD"):
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO personal_trades "
            "  (user, pair, direction, entry_price, stop_loss, take_profit, "
            "   size_lot, status, created_at, mt5_ticket, is_auto) "
            "VALUES ('u', ?, ?, 1.1, 1.09, 1.12, 0.01, 'OPEN', "
            "        '2026-08-13T00:00:00+00:00', ?, 1)",
            (pair, direction, ticket))
        conn.commit()
    finally:
        conn.close()


def _count(db: Path) -> int:
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT COUNT(*) FROM personal_trades").fetchone()[0]
    finally:
        conn.close()


def test_unicite_ticket_direction_rend_insert_or_ignore_effectif():
    """Sans contrainte, `INSERT OR IGNORE` n'ignore RIEN : il n'y a rien a violer.

    C'est ce qui a laisse s'accumuler 544 doublons entre avril et juin 2026 —
    le garde etait ecrit dans mt5_sync depuis le debut, mais aucun index
    unique ne lui donnait prise.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "test.db"
        with patch.object(trade_log_service, "_DB_PATH", db):
            trade_log_service._init_schema()
            _insert(db, 12345, "buy")
            _insert(db, 12345, "buy")          # doublon exact -> doit etre ignore
            _insert(db, 12345, "close-sell")   # patte de cloture -> doit PASSER
        assert _count(db) == 2


def test_init_schema_ne_casse_pas_sur_une_base_deja_dupliquee():
    """Une base d'un autre tenant peut encore contenir des doublons.

    Poser la contrainte y echouerait ; l'exception ne doit JAMAIS remonter,
    sinon `_init_schema` — appele a chaque operation — arreterait le service
    pour une question d'hygiene.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "test.db"
        with patch.object(trade_log_service, "_DB_PATH", db):
            trade_log_service._init_schema()
            conn = sqlite3.connect(db)
            # On se replace AVANT la contrainte : c'est l'etat d'une base
            # creee par une version anterieure du code.
            conn.execute("DROP INDEX IF EXISTS idx_pt_ticket_dir")
            for _ in range(2):                 # 2 doublons, index absent
                conn.execute(
                    "INSERT INTO personal_trades "
                    "  (user, pair, direction, entry_price, stop_loss, "
                    "   take_profit, size_lot, status, created_at, mt5_ticket, is_auto) "
                    "VALUES ('u','EUR/USD','buy',1.1,1.09,1.12,0.01,'OPEN',"
                    "        '2026-08-13T00:00:00+00:00', 999, 1)")
            conn.commit()
            conn.close()

            trade_log_service._init_schema()   # ne doit pas lever

        assert _count(db) == 2                 # les doublons restent, rien n'est detruit
