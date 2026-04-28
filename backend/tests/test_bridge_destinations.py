"""Tests pour ``bridge_destinations.resolve_destinations()``.

Phase A.1 du chantier multi-tenant bridge routing — V1 ne résout qu'admin
legacy depuis l'env. Phase C ajoutera la résolution des users Premium.
"""
import dataclasses
from unittest.mock import MagicMock

import pytest

from backend.services import bridge_destinations


def _mk_setup(pair: str = "EUR/USD") -> MagicMock:
    s = MagicMock()
    s.pair = pair
    s.direction = MagicMock(value="buy")
    s.entry_price = 1.0
    return s


# ─── admin_legacy résolu correctement ─────────────────────────────────


def test_admin_legacy_returned_when_env_set(monkeypatch):
    """Admin legacy doit être présent quand ENABLED + URL + KEY sont set."""
    monkeypatch.setattr(bridge_destinations, "MT5_BRIDGE_ENABLED", True)
    monkeypatch.setattr(bridge_destinations, "MT5_BRIDGE_URL", "http://admin-bridge:8787")
    monkeypatch.setattr(bridge_destinations, "MT5_BRIDGE_API_KEY", "x" * 32)
    monkeypatch.setattr(bridge_destinations, "MT5_BRIDGE_MIN_CONFIDENCE", 55.0)
    monkeypatch.setattr(
        bridge_destinations,
        "MT5_BRIDGE_ALLOWED_ASSET_CLASSES",
        ["forex", "metal"],
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert len(dests) == 1
    admin = dests[0]
    assert admin.destination_id == "admin_legacy"
    assert admin.user_id is None
    assert admin.bridge_url == "http://admin-bridge:8787"
    assert admin.bridge_api_key == "x" * 32
    assert admin.min_confidence == 55.0
    assert admin.allowed_asset_classes == frozenset({"forex", "metal"})
    assert admin.auto_exec_enabled is True


def test_admin_legacy_strips_trailing_slash(monkeypatch):
    """``bridge_url`` ne doit pas avoir de slash final."""
    monkeypatch.setattr(bridge_destinations, "MT5_BRIDGE_ENABLED", True)
    monkeypatch.setattr(
        bridge_destinations, "MT5_BRIDGE_URL", "http://admin-bridge:8787/"
    )
    monkeypatch.setattr(bridge_destinations, "MT5_BRIDGE_API_KEY", "x" * 32)

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert dests[0].bridge_url == "http://admin-bridge:8787"


def test_bridge_config_is_frozen(monkeypatch):
    """Une ``BridgeConfig`` doit être immuable (frozen=True)."""
    monkeypatch.setattr(bridge_destinations, "MT5_BRIDGE_ENABLED", True)
    monkeypatch.setattr(bridge_destinations, "MT5_BRIDGE_URL", "http://admin-bridge:8787")
    monkeypatch.setattr(bridge_destinations, "MT5_BRIDGE_API_KEY", "x" * 32)

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    with pytest.raises(dataclasses.FrozenInstanceError):
        dests[0].destination_id = "user:1"  # type: ignore[misc]


# ─── admin_legacy court-circuité quand env manquant ───────────────────


def test_no_destinations_when_disabled(monkeypatch):
    """``MT5_BRIDGE_ENABLED=False`` → aucune destination admin_legacy."""
    monkeypatch.setattr(bridge_destinations, "MT5_BRIDGE_ENABLED", False)
    monkeypatch.setattr(bridge_destinations, "MT5_BRIDGE_URL", "http://admin-bridge:8787")
    monkeypatch.setattr(bridge_destinations, "MT5_BRIDGE_API_KEY", "x" * 32)

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert dests == []


def test_no_destinations_when_url_missing(monkeypatch):
    """URL vide → admin pas dans la liste."""
    monkeypatch.setattr(bridge_destinations, "MT5_BRIDGE_ENABLED", True)
    monkeypatch.setattr(bridge_destinations, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(bridge_destinations, "MT5_BRIDGE_API_KEY", "x" * 32)

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert dests == []


def test_no_destinations_when_api_key_missing(monkeypatch):
    """API key vide → admin pas dans la liste."""
    monkeypatch.setattr(bridge_destinations, "MT5_BRIDGE_ENABLED", True)
    monkeypatch.setattr(
        bridge_destinations, "MT5_BRIDGE_URL", "http://admin-bridge:8787"
    )
    monkeypatch.setattr(bridge_destinations, "MT5_BRIDGE_API_KEY", "")

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert dests == []


# ─── placeholder Phase C ──────────────────────────────────────────────


def test_no_user_destinations_in_v1(monkeypatch):
    """Phase A.1 : ``_user_destinations()`` retourne ``[]``.

    Ce test évoluera en Phase C : il deviendra
    ``test_premium_users_in_destinations`` quand on connectera ``users_service``.
    """
    monkeypatch.setattr(bridge_destinations, "MT5_BRIDGE_ENABLED", False)
    # admin_legacy off ⇒ seule source possible serait _user_destinations()

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert dests == []
