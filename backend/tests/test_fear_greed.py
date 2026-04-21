"""Tests du service Fear & Greed : classification, fetch, stockage."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from backend.services import fear_greed_service, trade_log_service


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "extreme_fear"),
        (20, "extreme_fear"),
        (30, "fear"),
        (50, "neutral"),
        (60, "greed"),
        (80, "extreme_greed"),
        (100, "extreme_greed"),
    ],
)
def test_classify_thresholds(value: float, expected: str):
    assert fear_greed_service.classify(value) == expected


def test_get_current_returns_none_on_empty_db(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(trade_log_service, "_DB_PATH", tmp_path / "t.db")
    trade_log_service._init_schema()
    assert fear_greed_service.get_current() is None


@pytest.mark.asyncio
async def test_fetch_latest_stores_snapshot(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(trade_log_service, "_DB_PATH", tmp_path / "t.db")
    trade_log_service._init_schema()

    fake_payload = {"fear_and_greed": {"score": 72.5, "rating": "Greed"}}

    class _FakeResponse:
        status_code = 200
        def json(self):
            return fake_payload

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def get(self, url, headers=None):
            return _FakeResponse()

    with patch("backend.services.fear_greed_service.httpx.AsyncClient", _FakeClient):
        snap = await fear_greed_service.fetch_latest()

    assert snap is not None
    assert snap["value"] == 72.5
    assert snap["classification"] == "greed"

    # Persistance verifiee
    current = fear_greed_service.get_current()
    assert current["value"] == 72.5
    assert current["classification"] == "greed"


@pytest.mark.asyncio
async def test_fetch_latest_handles_network_error(tmp_path: Path, monkeypatch):
    """CNN down → pas de crash, None retourne."""
    monkeypatch.setattr(trade_log_service, "_DB_PATH", tmp_path / "t.db")
    trade_log_service._init_schema()

    class _BrokenClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def get(self, url, headers=None):
            raise httpx.ConnectError("boom")

    with patch(
        "backend.services.fear_greed_service.httpx.AsyncClient", _BrokenClient
    ):
        snap = await fear_greed_service.fetch_latest()
    assert snap is None


@pytest.mark.asyncio
async def test_fetch_latest_ignores_unexpected_payload(tmp_path: Path, monkeypatch):
    """Si CNN change la structure → retourne None, pas de crash."""
    monkeypatch.setattr(trade_log_service, "_DB_PATH", tmp_path / "t.db")
    trade_log_service._init_schema()

    class _FakeResponse:
        status_code = 200
        def json(self):
            return {"some_other_key": {}}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def get(self, url, headers=None):
            return _FakeResponse()

    with patch("backend.services.fear_greed_service.httpx.AsyncClient", _FakeClient):
        snap = await fear_greed_service.fetch_latest()
    assert snap is None


def test_is_extreme_flags_correctly(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(trade_log_service, "_DB_PATH", tmp_path / "t.db")
    trade_log_service._init_schema()
    fear_greed_service._init_schema()
    with sqlite3.connect(tmp_path / "t.db") as c:
        c.execute(
            "INSERT INTO fear_greed_snapshots (recorded_at, value, classification) "
            "VALUES ('2026-04-21T00:00:00Z', 15, 'extreme_fear')"
        )
    assert fear_greed_service.is_extreme() is True

    with sqlite3.connect(tmp_path / "t.db") as c:
        c.execute(
            "INSERT INTO fear_greed_snapshots (recorded_at, value, classification) "
            "VALUES ('2026-04-22T00:00:00Z', 50, 'neutral')"
        )
    assert fear_greed_service.is_extreme() is False
