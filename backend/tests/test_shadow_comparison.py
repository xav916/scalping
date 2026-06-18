"""Tests pour shadow_comparison_service (chantier #25 Tier 5)."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.services import shadow_comparison_service as svc


@pytest.fixture
def temp_db(tmp_path):
    db = tmp_path / "mt5_pushes.db"
    with sqlite3.connect(db) as con:
        con.execute(
            """
            CREATE TABLE mt5_pushes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                destination_id TEXT NOT NULL,
                date TEXT NOT NULL,
                pair TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price_5dp TEXT NOT NULL,
                pushed_at TEXT NOT NULL,
                ok INTEGER NOT NULL,
                bridge_response TEXT,
                UNIQUE(destination_id, date, pair, direction, entry_price_5dp)
            )
            """
        )
        con.commit()
    with patch.object(svc, "_DB_PATH", db):
        yield db


def _seed(db, rows):
    with sqlite3.connect(db) as con:
        con.executemany(
            "INSERT INTO mt5_pushes (destination_id, date, pair, direction, "
            "entry_price_5dp, pushed_at, ok, bridge_response) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        con.commit()


def test_empty_db_returns_empty_signals(temp_db):
    out = svc.get_shadow_comparison()
    assert out["signals"] == []
    assert out["summary"] == {}


def test_single_destination_one_signal(temp_db):
    today = date.today().isoformat()
    _seed(temp_db, [
        ("admin_binance", today, "BTC/USD", "buy", "65000.00000",
         f"{today}T10:00:00+00:00", 1, json.dumps({"avg_price": 65010.0})),
    ])
    out = svc.get_shadow_comparison()
    assert len(out["signals"]) == 1
    sig = out["signals"][0]
    assert sig["pair"] == "BTC/USD"
    assert sig["direction"] == "buy"
    assert sig["entry_price"] == 65000.0
    bin_dest = sig["destinations"]["admin_binance"]
    assert bin_dest["ok"] is True
    assert bin_dest["fill_price"] == 65010.0
    # buy fill > entry → défavorable, slippage_bps > 0
    assert bin_dest["slippage_bps"] > 0


def test_signed_slippage_for_sell(temp_db):
    today = date.today().isoformat()
    _seed(temp_db, [
        ("admin_binance", today, "ETH/USD", "sell", "3000.00000",
         f"{today}T10:00:00+00:00", 1, json.dumps({"avg_price": 2990.0})),
    ])
    out = svc.get_shadow_comparison()
    dest = out["signals"][0]["destinations"]["admin_binance"]
    # sell fill < entry → défavorable (on encaisse moins) → slippage_bps > 0
    assert dest["slippage_bps"] > 0


def test_two_destinations_same_signal(temp_db):
    today = date.today().isoformat()
    _seed(temp_db, [
        ("admin_legacy", today, "BTC/USD", "buy", "65000.00000",
         f"{today}T10:00:00+00:00", 1, json.dumps({"price": 65005.0})),
        ("admin_binance", today, "BTC/USD", "buy", "65000.00000",
         f"{today}T10:00:01+00:00", 1, json.dumps({"avg_price": 65010.0})),
    ])
    out = svc.get_shadow_comparison()
    assert len(out["signals"]) == 1
    dests = out["signals"][0]["destinations"]
    assert dests["admin_legacy"]["fill_price"] == 65005.0
    assert dests["admin_binance"]["fill_price"] == 65010.0
    # Summary doit comptabiliser les 2 destinations
    assert "admin_legacy" in out["summary"]
    assert "admin_binance" in out["summary"]
    assert out["summary"]["admin_legacy"]["total_pushes"] == 1
    assert out["summary"]["admin_binance"]["total_pushes"] == 1


def test_failed_push_counted_in_total_but_not_ok_rate(temp_db):
    today = date.today().isoformat()
    _seed(temp_db, [
        ("admin_binance", today, "BTC/USD", "buy", "65000.00000",
         f"{today}T10:00:00+00:00", 0, None),
        ("admin_binance", today, "ETH/USD", "buy", "3000.00000",
         f"{today}T10:00:01+00:00", 1, json.dumps({"avg_price": 3001.0})),
    ])
    out = svc.get_shadow_comparison()
    bin_summary = out["summary"]["admin_binance"]
    assert bin_summary["total_pushes"] == 2
    assert bin_summary["ok_rate"] == 0.5


def test_pair_filter(temp_db):
    today = date.today().isoformat()
    _seed(temp_db, [
        ("admin_binance", today, "BTC/USD", "buy", "65000.00000",
         f"{today}T10:00:00+00:00", 1, json.dumps({"avg_price": 65010.0})),
        ("admin_binance", today, "ETH/USD", "buy", "3000.00000",
         f"{today}T10:00:01+00:00", 1, json.dumps({"avg_price": 3001.0})),
    ])
    out = svc.get_shadow_comparison(pair="ETH/USD")
    assert len(out["signals"]) == 1
    assert out["signals"][0]["pair"] == "ETH/USD"


def test_days_cutoff_excludes_old(temp_db):
    old_date = (date.today() - timedelta(days=30)).isoformat()
    _seed(temp_db, [
        ("admin_binance", old_date, "BTC/USD", "buy", "65000.00000",
         f"{old_date}T10:00:00+00:00", 1, json.dumps({"avg_price": 65010.0})),
    ])
    out = svc.get_shadow_comparison(days=7)
    assert out["signals"] == []


def test_extract_fill_handles_missing_or_garbage():
    assert svc._extract_fill(None) is None
    assert svc._extract_fill("") is None
    assert svc._extract_fill("not json {{{{") is None
    assert svc._extract_fill(json.dumps({"foo": "bar"})) is None
    assert svc._extract_fill(json.dumps({"avg_price": "65010.5"})) == 65010.5
    assert svc._extract_fill(json.dumps({"price": 65010})) == 65010.0
