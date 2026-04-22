"""Tests du service de journal des rejections auto-exec."""
import json
import sqlite3

import pytest

from backend.services import rejection_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_file = tmp_path / "trades.db"
    # Crée une DB vide ; le service crée lui-même la table au 1er écrit
    sqlite3.connect(db_file).close()
    monkeypatch.setattr(rejection_service, "_db_path", lambda: str(db_file))
    return str(db_file)


def test_record_and_read_back(db):
    rejection_service.record_rejection(
        pair="EUR/USD",
        direction="buy",
        confidence=57.0,
        reason_code="bridge_max_positions",
    )
    out = rejection_service.get_rejections(
        since="2026-01-01T00:00:00+00:00",
        until="2030-01-01T00:00:00+00:00",
    )
    assert out["total"] == 1
    assert out["by_reason"][0]["reason_code"] == "bridge_max_positions"
    assert out["by_reason"][0]["label_fr"] == "Cap positions bridge"
    assert out["by_reason"][0]["count"] == 1
    assert out["by_reason"][0]["top_pair"] == "EUR/USD"


def test_empty_db_returns_zero(db):
    out = rejection_service.get_rejections(
        since="2026-01-01T00:00:00+00:00",
        until="2030-01-01T00:00:00+00:00",
    )
    assert out["total"] == 0
    assert out["by_reason"] == []
    # 24 heures toujours présentes
    assert len(out["by_hour_utc"]) == 24


def test_aggregation_ranks_reasons_by_count(db):
    for _ in range(5):
        rejection_service.record_rejection("XAU/USD", "sell", 60, "bridge_max_positions")
    for _ in range(2):
        rejection_service.record_rejection("EUR/USD", "buy", 57, "market_closed")
    rejection_service.record_rejection("GBP/USD", "buy", 58, "sl_too_close")

    out = rejection_service.get_rejections(
        since="2026-01-01T00:00:00+00:00",
        until="2030-01-01T00:00:00+00:00",
    )
    assert out["total"] == 8
    reasons = [r["reason_code"] for r in out["by_reason"]]
    # Tri décroissant par count
    assert reasons == ["bridge_max_positions", "market_closed", "sl_too_close"]
    assert out["by_reason"][0]["count"] == 5


def test_respects_since_until_range(db):
    # Ne peut pas mocker datetime.now facilement ici sans refactor ;
    # on vérifie plutôt qu'un window futur retourne 0
    rejection_service.record_rejection("EUR/USD", "buy", 57, "kill_switch")

    out = rejection_service.get_rejections(
        since="2030-01-01T00:00:00+00:00",
        until="2030-12-31T23:59:59+00:00",
    )
    assert out["total"] == 0


def test_details_json_stored(db):
    rejection_service.record_rejection(
        pair="USD/CAD",
        direction="buy",
        confidence=56,
        reason_code="bridge_error",
        details={"status": 500, "body": "server error"},
    )
    # Vérifie que la ligne contient bien le JSON stringifié
    db_path = rejection_service._db_path()
    with sqlite3.connect(db_path) as c:
        row = c.execute("SELECT details FROM signal_rejections").fetchone()
    assert json.loads(row[0]) == {"status": 500, "body": "server error"}


def test_by_hour_distribution(db):
    # Insert 3 rejections à des timestamps forgés
    with sqlite3.connect(rejection_service._db_path()) as c:
        rejection_service._ensure_schema()
        c.execute(
            "INSERT INTO signal_rejections (created_at, pair, reason_code) VALUES (?, ?, ?)",
            ("2026-04-22T08:30:00+00:00", "EUR/USD", "bridge_max_positions"),
        )
        c.execute(
            "INSERT INTO signal_rejections (created_at, pair, reason_code) VALUES (?, ?, ?)",
            ("2026-04-22T08:45:00+00:00", "GBP/USD", "bridge_max_positions"),
        )
        c.execute(
            "INSERT INTO signal_rejections (created_at, pair, reason_code) VALUES (?, ?, ?)",
            ("2026-04-22T14:00:00+00:00", "XAU/USD", "sl_too_close"),
        )

    out = rejection_service.get_rejections(
        since="2026-04-22T00:00:00+00:00",
        until="2026-04-22T23:59:59+00:00",
    )
    hour_by_idx = {h["hour"]: h["count"] for h in out["by_hour_utc"]}
    assert hour_by_idx[8] == 2
    assert hour_by_idx[14] == 1
    assert hour_by_idx[0] == 0  # fill des heures vides


def test_by_reason_hour_for_heatmap(db):
    with sqlite3.connect(rejection_service._db_path()) as c:
        rejection_service._ensure_schema()
        c.execute(
            "INSERT INTO signal_rejections (created_at, pair, reason_code) VALUES (?, ?, ?)",
            ("2026-04-22T08:30:00+00:00", "EUR/USD", "bridge_max_positions"),
        )
        c.execute(
            "INSERT INTO signal_rejections (created_at, pair, reason_code) VALUES (?, ?, ?)",
            ("2026-04-22T08:45:00+00:00", "GBP/USD", "bridge_max_positions"),
        )

    out = rejection_service.get_rejections(
        since="2026-04-22T00:00:00+00:00",
        until="2026-04-22T23:59:59+00:00",
    )
    heatmap = {(c["reason_code"], c["hour"]): c["count"] for c in out["by_reason_hour"]}
    assert heatmap[("bridge_max_positions", 8)] == 2
