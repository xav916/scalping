"""Tests pour ``bridge_destinations.resolve_destinations()``.

Phase A.1 du chantier multi-tenant bridge routing — V1 ne résout qu'admin
legacy depuis l'env. Phase C ajoutera la résolution des users Premium.

Les patches sont appliqués sur ``mt5_bridge`` parce que
``_admin_legacy_destination()`` lit la config legacy via ce module (lazy
import) — voir le module bridge_destinations pour le rationale.
"""
import dataclasses
from unittest.mock import MagicMock

import pytest

from backend.services import bridge_destinations, mt5_bridge


def _mk_setup(pair: str = "EUR/USD") -> MagicMock:
    s = MagicMock()
    s.pair = pair
    s.direction = MagicMock(value="buy")
    s.entry_price = 1.0
    return s


def _set_admin_env(monkeypatch, **overrides):
    """Helper : force la config admin legacy via patches sur mt5_bridge."""
    defaults = {
        "MT5_BRIDGE_ENABLED": True,
        "MT5_BRIDGE_URL": "http://admin-bridge:8787",
        "MT5_BRIDGE_API_KEY": "x" * 32,
        "MT5_BRIDGE_MIN_CONFIDENCE": 55.0,
        "MT5_BRIDGE_ALLOWED_ASSET_CLASSES": ["forex", "metal"],
    }
    defaults.update(overrides)
    for name, value in defaults.items():
        monkeypatch.setattr(mt5_bridge, name, value)


# ─── admin_legacy résolu correctement ─────────────────────────────────


def test_admin_legacy_returned_when_env_set(monkeypatch):
    """Admin legacy doit être présent quand ENABLED + URL + KEY sont set."""
    _set_admin_env(monkeypatch)

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
    _set_admin_env(monkeypatch, MT5_BRIDGE_URL="http://admin-bridge:8787/")

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert dests[0].bridge_url == "http://admin-bridge:8787"


def test_bridge_config_is_frozen(monkeypatch):
    """Une ``BridgeConfig`` doit être immuable (frozen=True)."""
    _set_admin_env(monkeypatch)

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    with pytest.raises(dataclasses.FrozenInstanceError):
        dests[0].destination_id = "user:1"  # type: ignore[misc]


# ─── admin_legacy court-circuité quand env manquant ───────────────────


def test_no_destinations_when_disabled(monkeypatch):
    """``MT5_BRIDGE_ENABLED=False`` → aucune destination admin_legacy."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert dests == []


def test_no_destinations_when_url_missing(monkeypatch):
    """URL vide → admin pas dans la liste."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_URL="")

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert dests == []


def test_no_destinations_when_api_key_missing(monkeypatch):
    """API key vide → admin pas dans la liste."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_API_KEY="")

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert dests == []


# ─── placeholder Phase C ──────────────────────────────────────────────


def test_no_destinations_when_admin_off_and_no_users(monkeypatch):
    """Admin off + aucun user éligible → liste vide."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users",
        lambda: [],
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert dests == []


# ─── Phase C : user destinations ──────────────────────────────────────


def _stub_premium_user(
    user_id: int = 42,
    bridge_url: str = "http://user-bridge:8787",
    bridge_api_key: str = "u" * 32,
    watched_pairs: list[str] | None = None,
) -> dict:
    return {
        "id": user_id,
        "email": "test@example.com",
        "broker_config": {
            "bridge_url": bridge_url,
            "bridge_api_key": bridge_api_key,
            "auto_exec_enabled": True,
        },
        "watched_pairs": watched_pairs if watched_pairs is not None else ["EUR/USD"],
    }


def test_premium_user_returned_when_pair_in_watchlist(monkeypatch):
    """Premium user + auto_exec + pair in watchlist → BridgeConfig avec user:id."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)  # admin off pour isoler
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users",
        lambda: [_stub_premium_user(user_id=42)],
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup("EUR/USD"))

    assert len(dests) == 1
    user_dest = dests[0]
    assert user_dest.destination_id == "user:42"
    assert user_dest.user_id == 42
    assert user_dest.bridge_url == "http://user-bridge:8787"
    assert user_dest.bridge_api_key == "u" * 32
    assert user_dest.auto_exec_enabled is True


def test_premium_user_excluded_when_pair_not_in_watchlist(monkeypatch):
    """Pair pas dans watched_pairs du user → exclu."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users",
        lambda: [_stub_premium_user(watched_pairs=["XAU/USD"])],
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup("EUR/USD"))

    assert dests == []


def test_admin_and_user_returned_in_order(monkeypatch):
    """Admin + user Premium → admin en premier (rétro-compat), user après."""
    _set_admin_env(monkeypatch)  # admin actif
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users",
        lambda: [_stub_premium_user(user_id=42)],
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup("EUR/USD"))

    assert len(dests) == 2
    assert dests[0].destination_id == "admin_legacy"
    assert dests[1].destination_id == "user:42"


def test_multiple_users_returned(monkeypatch):
    """Deux users Premium éligibles → deux destinations."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users",
        lambda: [
            _stub_premium_user(user_id=42),
            _stub_premium_user(user_id=43),
        ],
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup("EUR/USD"))

    assert {d.destination_id for d in dests} == {"user:42", "user:43"}


def test_user_destinations_resilient_to_users_service_error(monkeypatch):
    """Si users_service raise, retomber sur [] (pas de crash global)."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)

    def boom():
        raise RuntimeError("DB unreachable")

    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users", boom
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup("EUR/USD"))

    assert dests == []  # safe fallback


def test_user_destination_skipped_on_malformed_broker_config(monkeypatch):
    """broker_config sans bridge_url → ce user-là est skip, les autres passent."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)
    bad = _stub_premium_user(user_id=99)
    bad["broker_config"] = {"auto_exec_enabled": True}  # manque url + key
    good = _stub_premium_user(user_id=42)
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users",
        lambda: [bad, good],
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup("EUR/USD"))

    # Seul le user bien configuré passe
    assert {d.destination_id for d in dests} == {"user:42"}
