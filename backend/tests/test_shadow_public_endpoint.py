"""Tests pour l'endpoint /api/shadow/v2_core_long/public-summary.

Vérifie : token requis, token invalide refusé, token valide OK.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from backend.app import app
    return TestClient(app)


def test_public_summary_requires_token(client):
    """Pas de token → 403."""
    r = client.get("/api/shadow/v2_core_long/public-summary")
    assert r.status_code == 403
    assert "token required" in r.json()["detail"]


def test_public_summary_invalid_token(client):
    """Token incorrect → 403."""
    r = client.get("/api/shadow/v2_core_long/public-summary?token=wrong")
    assert r.status_code == 403
    assert "invalid token" in r.json()["detail"]


def test_public_summary_valid_token(client):
    """Token valide → 200 + structure summary."""
    valid_token = "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
    r = client.get(f"/api/shadow/v2_core_long/public-summary?token={valid_token}")
    assert r.status_code == 200
    data = r.json()
    assert "systems" in data
    assert isinstance(data["systems"], list)
