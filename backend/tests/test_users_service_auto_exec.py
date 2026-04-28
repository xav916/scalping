"""Tests Phase C — `users_service.list_premium_auto_exec_users` + toggle.

Vérifie le filtrage des users éligibles à l'auto-exec multi-tenant et le
toggle préservant les autres champs broker_config.
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.services import users_service


@pytest.fixture
def db(tmp_path: Path):
    db_file = tmp_path / "trades.db"
    with patch.object(users_service, "_DB_PATH", db_file):
        users_service.init_users_schema()
        yield db_file


def _create_premium_user(
    email: str,
    *,
    bridge_url: str = "http://user-bridge:8787",
    bridge_api_key: str = "u" * 32,
    auto_exec_enabled: bool = True,
    watched_pairs: list[str] | None = None,
    has_active_sub: bool = True,
) -> int:
    """Crée un user premium avec broker_config configuré."""
    uid = users_service.create_user(email, "password123")
    cfg: dict = {}
    if bridge_url:
        cfg["bridge_url"] = bridge_url
    if bridge_api_key:
        cfg["bridge_api_key"] = bridge_api_key
    if auto_exec_enabled is not None:
        cfg["auto_exec_enabled"] = auto_exec_enabled
    pairs = watched_pairs if watched_pairs is not None else ["EUR/USD", "XAU/USD"]
    with users_service._conn() as c:
        sub_id = "sub_test_xxx" if has_active_sub else None
        c.execute(
            "UPDATE users SET tier='premium', broker_config=?, watched_pairs=?, "
            "stripe_subscription_id=? WHERE id=?",
            (json.dumps(cfg), json.dumps(pairs), sub_id, uid),
        )
    return uid


# ─── list_premium_auto_exec_users ─────────────────────────────────────


def test_list_returns_eligible_premium_user(db):
    uid = _create_premium_user("alice@test.com")
    users = users_service.list_premium_auto_exec_users()
    assert len(users) == 1
    assert users[0]["id"] == uid
    assert users[0]["email"] == "alice@test.com"
    assert users[0]["broker_config"]["bridge_url"] == "http://user-bridge:8787"
    assert "EUR/USD" in users[0]["watched_pairs"]


def test_list_excludes_user_without_auto_exec(db):
    _create_premium_user("alice@test.com", auto_exec_enabled=False)
    assert users_service.list_premium_auto_exec_users() == []


def test_list_excludes_user_without_bridge_config(db):
    """broker_config NULL → exclu."""
    uid = users_service.create_user("alice@test.com", "password123")
    with users_service._conn() as c:
        c.execute("UPDATE users SET tier='premium' WHERE id=?", (uid,))
    assert users_service.list_premium_auto_exec_users() == []


def test_list_excludes_user_with_short_api_key(db):
    """bridge_api_key < 16 chars → exclu."""
    _create_premium_user("alice@test.com", bridge_api_key="short")
    assert users_service.list_premium_auto_exec_users() == []


def test_list_excludes_user_with_invalid_url(db):
    """bridge_url sans schéma → exclu."""
    _create_premium_user("alice@test.com", bridge_url="just-a-host:8787")
    assert users_service.list_premium_auto_exec_users() == []


def test_list_excludes_non_premium_tier(db):
    """User free / pro → exclu même avec config valide."""
    uid = users_service.create_user("alice@test.com", "password123")
    cfg = {
        "bridge_url": "http://user-bridge:8787",
        "bridge_api_key": "u" * 32,
        "auto_exec_enabled": True,
    }
    with users_service._conn() as c:
        c.execute(
            "UPDATE users SET tier='pro', broker_config=?, watched_pairs=? WHERE id=?",
            (json.dumps(cfg), json.dumps(["EUR/USD"]), uid),
        )
    assert users_service.list_premium_auto_exec_users() == []


def test_list_excludes_premium_with_expired_trial(db):
    """Premium tier mais sub Stripe absente + pas de trial actif → effective tier 'free' → exclu."""
    uid = users_service.create_user("alice@test.com", "password123")
    cfg = {
        "bridge_url": "http://user-bridge:8787",
        "bridge_api_key": "u" * 32,
        "auto_exec_enabled": True,
    }
    with users_service._conn() as c:
        c.execute(
            "UPDATE users SET tier='premium', broker_config=?, watched_pairs=?, "
            "stripe_subscription_id=NULL, trial_ends_at='2020-01-01T00:00:00Z' "
            "WHERE id=?",
            (json.dumps(cfg), json.dumps(["EUR/USD"]), uid),
        )
    assert users_service.list_premium_auto_exec_users() == []


def test_list_returns_multiple_users(db):
    a = _create_premium_user("alice@test.com")
    b = _create_premium_user("bob@test.com")
    users = users_service.list_premium_auto_exec_users()
    assert {u["id"] for u in users} == {a, b}


# ─── update_auto_exec_enabled ─────────────────────────────────────────


def test_toggle_auto_exec_preserves_other_fields(db):
    uid = _create_premium_user("alice@test.com", auto_exec_enabled=False)
    # Avant : bridge_url+key set, auto_exec=False
    cfg = users_service.get_broker_config(uid)
    assert cfg["bridge_url"] == "http://user-bridge:8787"
    assert cfg["auto_exec_enabled"] is False

    users_service.update_auto_exec_enabled(uid, True)

    cfg2 = users_service.get_broker_config(uid)
    assert cfg2["auto_exec_enabled"] is True
    assert cfg2["bridge_url"] == "http://user-bridge:8787"  # préservé
    assert cfg2["bridge_api_key"] == "u" * 32  # préservé


def test_toggle_auto_exec_on_empty_config_creates_minimal_dict(db):
    """User sans broker_config : toggle crée un dict avec juste auto_exec."""
    uid = users_service.create_user("alice@test.com", "password123")
    users_service.update_auto_exec_enabled(uid, True)
    cfg = users_service.get_broker_config(uid)
    assert cfg == {"auto_exec_enabled": True}


def test_update_broker_config_preserves_auto_exec(db):
    """Phase D safety : un PUT broker_config ne doit pas écraser auto_exec.

    Régression possible : avant Phase D, update_broker_config remplaçait
    le dict entier → toggle auto_exec=True silencieusement perdu après
    chaque modif d'URL ou de clé.
    """
    uid = users_service.create_user("alice@test.com", "password123")
    users_service.update_broker_config(
        uid, bridge_url="http://b1:8787", bridge_api_key="key_first_one_xx" * 2
    )
    users_service.update_auto_exec_enabled(uid, True)
    # Maintenant l'user change son URL (ex: nouveau VPS)
    users_service.update_broker_config(
        uid, bridge_url="http://b2:8787", bridge_api_key="key_second_one_x" * 2
    )
    cfg = users_service.get_broker_config(uid)
    assert cfg["bridge_url"] == "http://b2:8787"
    assert cfg["auto_exec_enabled"] is True  # préservé !
