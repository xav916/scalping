"""Tests du service COT : parsing, stockage, z-score, detection d'extremes."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.services import cot_service, trade_log_service


def _sample_row(
    contract: str = "EURO FX - CHICAGO MERCANTILE EXCHANGE",
    report_date: str = "2026-04-15",
    lev_long: int = 100_000,
    lev_short: int = 50_000,
    nr_long: int = 10_000,
    nr_short: int = 8_000,
):
    return {
        "market_and_exchange_names": contract,
        "report_date_as_yyyy_mm_dd": report_date,
        "m_money_positions_long_all": str(lev_long),
        "m_money_positions_short_all": str(lev_short),
        "nonrept_positions_long_all": str(nr_long),
        "nonrept_positions_short_all": str(nr_short),
        "asset_mgr_positions_long_all": "30000",
        "asset_mgr_positions_short_all": "20000",
        "open_interest_all": "500000",
    }


def test_parse_row_maps_contract_to_pair():
    parsed = cot_service._parse_row(_sample_row())
    assert parsed is not None
    assert parsed["pair"] == "EUR/USD"
    assert parsed["lev_funds_net"] == 50_000  # 100k long - 50k short
    assert parsed["non_reportables_net"] == 2_000


def test_parse_row_returns_none_for_unknown_contract():
    row = _sample_row(contract="SOME UNRELATED CONTRACT")
    assert cot_service._parse_row(row) is None


def test_zscore_returns_none_on_small_sample():
    assert cot_service._zscore([1, 2, 3], 5) is None


def test_zscore_returns_none_when_std_zero():
    # Historique constant → std=0 → pas de z-score
    assert cot_service._zscore([5, 5, 5, 5, 5, 5, 5, 5], 10) is None


def test_zscore_sign_and_magnitude():
    history = [10, 12, 14, 11, 13, 15, 9, 12]
    z = cot_service._zscore(history, 20)
    assert z is not None
    assert z > 0  # valeur au-dessus de la moyenne


def test_upsert_and_get_latest_roundtrip(tmp_path: Path, monkeypatch):
    trades_db = tmp_path / "trades.db"
    monkeypatch.setattr(trade_log_service, "_DB_PATH", trades_db)
    trade_log_service._init_schema()

    # 10 snapshots croissants pour pouvoir calculer z-score
    for i, d in enumerate([
        "2026-02-03", "2026-02-10", "2026-02-17", "2026-02-24",
        "2026-03-03", "2026-03-10", "2026-03-17", "2026-03-24",
        "2026-03-31", "2026-04-07",
    ]):
        parsed = cot_service._parse_row(_sample_row(
            report_date=d, lev_long=100_000 + i * 1000, lev_short=50_000
        ))
        cot_service._upsert_snapshot(parsed)

    # Dernier snapshot : leveraged net a 200_000 (gros outlier)
    extreme = cot_service._parse_row(_sample_row(
        report_date="2026-04-14", lev_long=250_000, lev_short=50_000,
    ))
    cot_service._upsert_snapshot(extreme)

    latest = cot_service.get_latest()
    assert len(latest) == 1
    entry = latest[0]
    assert entry["pair"] == "EUR/USD"
    assert entry["report_date"] == "2026-04-14"
    assert entry["lev_funds_net"] == 200_000
    assert entry["lev_funds_z"] is not None
    assert entry["lev_funds_z"] >= 2.0  # outlier massif


def test_find_extremes_flags_high_zscore(tmp_path: Path, monkeypatch):
    trades_db = tmp_path / "trades.db"
    monkeypatch.setattr(trade_log_service, "_DB_PATH", trades_db)
    trade_log_service._init_schema()

    # Historique stable puis spike
    for i, d in enumerate([
        "2026-02-03", "2026-02-10", "2026-02-17", "2026-02-24",
        "2026-03-03", "2026-03-10", "2026-03-17", "2026-03-24",
        "2026-03-31", "2026-04-07",
    ]):
        cot_service._upsert_snapshot(cot_service._parse_row(_sample_row(
            report_date=d, lev_long=100_000 + i * 500, lev_short=50_000,
        )))
    cot_service._upsert_snapshot(cot_service._parse_row(_sample_row(
        report_date="2026-04-14", lev_long=300_000, lev_short=40_000,
    )))

    extremes = cot_service.find_extremes()
    assert any(e["pair"] == "EUR/USD" for e in extremes)
    eur = next(e for e in extremes if e["pair"] == "EUR/USD")
    assert any(s["actor"] == "leveraged_funds" for s in eur["signals"])


@pytest.mark.asyncio
async def test_sync_latest_robust_to_network_failure(tmp_path: Path, monkeypatch):
    """Si CFTC indispo → sync_latest retourne fetched=0, pas d'exception."""
    trades_db = tmp_path / "trades.db"
    monkeypatch.setattr(trade_log_service, "_DB_PATH", trades_db)
    trade_log_service._init_schema()

    with patch.object(cot_service, "fetch_latest_report", AsyncMock(return_value=[])):
        summary = await cot_service.sync_latest()
    assert summary["fetched"] == 0
    assert summary["stored"] == 0


@pytest.mark.asyncio
async def test_sync_latest_stores_rows(tmp_path: Path, monkeypatch):
    trades_db = tmp_path / "trades.db"
    monkeypatch.setattr(trade_log_service, "_DB_PATH", trades_db)
    trade_log_service._init_schema()

    rows = [
        _sample_row(report_date="2026-04-14"),
        _sample_row(contract="GOLD - COMMODITY EXCHANGE INC.", report_date="2026-04-14"),
        _sample_row(contract="UNKNOWN CONTRACT", report_date="2026-04-14"),
    ]
    with patch.object(cot_service, "fetch_latest_report", AsyncMock(return_value=rows)):
        summary = await cot_service.sync_latest()

    assert summary["stored"] == 2  # EUR/USD + XAU/USD, UNKNOWN ignore
    with sqlite3.connect(trades_db) as c:
        n = c.execute("SELECT COUNT(*) FROM cot_snapshots").fetchone()[0]
    assert n == 2
