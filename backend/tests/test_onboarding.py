"""Tests pour le chantier 4 SaaS : onboarding broker + watched pairs."""

import json
import sqlite3

import pytest

from backend.services import users_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_file = tmp_path / "trades.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE personal_trades (id INTEGER PRIMARY KEY, user TEXT)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(users_service, "_DB_PATH", db_file)
    users_service.init_users_schema()
    return db_file


# ─── broker_config ─────────────────────────────────────────

def test_update_and_get_broker_config(db):
    uid = users_service.create_user("alice@test.com", "pw12345678")
    users_service.update_broker_config(
        uid,
        bridge_url="http://100.64.0.1:8787",
        bridge_api_key="secret_api_key_12345",
    )
    cfg = users_service.get_broker_config(uid)
    assert cfg["bridge_url"] == "http://100.64.0.1:8787"
    assert cfg["bridge_api_key"] == "secret_api_key_12345"


def test_broker_config_strips_trailing_slash(db):
    uid = users_service.create_user("alice@test.com", "pw12345678")
    users_service.update_broker_config(
        uid,
        bridge_url="http://foo.com:8787/",
        bridge_api_key="secret_api_key_12345",
    )
    cfg = users_service.get_broker_config(uid)
    assert cfg["bridge_url"] == "http://foo.com:8787"


def test_broker_config_rejects_invalid_url(db):
    uid = users_service.create_user("alice@test.com", "pw12345678")
    with pytest.raises(ValueError, match="bridge_url invalide"):
        users_service.update_broker_config(uid, bridge_url="no-scheme", bridge_api_key="secret_api_key_12345")


def test_broker_config_rejects_short_api_key(db):
    uid = users_service.create_user("alice@test.com", "pw12345678")
    with pytest.raises(ValueError, match="bridge_api_key trop court"):
        users_service.update_broker_config(
            uid, bridge_url="http://foo:8787", bridge_api_key="short"
        )


def test_get_broker_config_empty_for_new_user(db):
    uid = users_service.create_user("alice@test.com", "pw12345678")
    assert users_service.get_broker_config(uid) == {}


def test_broker_config_isolated_between_users(db):
    uid_a = users_service.create_user("alice@test.com", "pw12345678")
    uid_b = users_service.create_user("bob@test.com", "pw12345678")
    users_service.update_broker_config(
        uid_a, bridge_url="http://alice:8787", bridge_api_key="alice_key_12345678"
    )
    users_service.update_broker_config(
        uid_b, bridge_url="http://bob:8787", bridge_api_key="bob_key_87654321"
    )
    assert users_service.get_broker_config(uid_a)["bridge_url"] == "http://alice:8787"
    assert users_service.get_broker_config(uid_b)["bridge_url"] == "http://bob:8787"


# ─── watched_pairs ─────────────────────────────────────────

def test_update_watched_pairs_dedupes_and_uppercases(db):
    uid = users_service.create_user("alice@test.com", "pw12345678", tier="pro")
    saved = users_service.update_watched_pairs(uid, ["eur/usd", "EUR/USD", " gbp/usd "])
    assert saved == ["EUR/USD", "GBP/USD"]


def test_watched_pairs_cap_by_tier(db):
    uid_free = users_service.create_user("free@test.com", "pw12345678", tier="free")
    uid_pro = users_service.create_user("pro@test.com", "pw12345678", tier="pro")
    uid_prem = users_service.create_user("prem@test.com", "pw12345678", tier="premium")

    pairs = ["EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD", "BTC/USD", "ETH/USD", "SPX", "NDX"]

    assert len(users_service.update_watched_pairs(uid_free, pairs)) == 1
    assert len(users_service.update_watched_pairs(uid_pro, pairs)) == 5
    assert len(users_service.update_watched_pairs(uid_prem, pairs)) == 8  # tous dans le cap 16


def test_watched_pairs_empty_for_new_user(db):
    uid = users_service.create_user("x@y.com", "pw12345678")
    assert users_service.get_watched_pairs(uid) == []


def test_update_watched_pairs_unknown_user_raises(db):
    with pytest.raises(ValueError, match="introuvable"):
        users_service.update_watched_pairs(999, ["EUR/USD"])


# ─── is_onboarding_complete ─────────────────────────────────

def test_new_user_needs_onboarding(db):
    uid = users_service.create_user("alice@test.com", "pw12345678")
    status = users_service.is_onboarding_complete(uid)
    assert status["has_broker"] is False
    assert status["has_pairs"] is False
    assert status["needs_onboarding"] is True


def test_broker_only_still_needs_pairs(db):
    """Modèle signal-only : avoir un broker sans pairs → onboarding pas terminé."""
    uid = users_service.create_user("alice@test.com", "pw12345678")
    users_service.update_broker_config(
        uid, bridge_url="http://x:8787", bridge_api_key="secret_api_key_12345"
    )
    status = users_service.is_onboarding_complete(uid)
    assert status["has_broker"] is True
    assert status["has_pairs"] is False
    assert status["needs_onboarding"] is True


def test_pairs_only_completes_onboarding(db):
    """Modèle signal-only : pairs seul suffit, bridge est optionnel."""
    uid = users_service.create_user("alice@test.com", "pw12345678", tier="pro")
    users_service.update_watched_pairs(uid, ["EUR/USD"])
    status = users_service.is_onboarding_complete(uid)
    assert status["has_broker"] is False
    assert status["has_pairs"] is True
    # has_broker=False mais onboarding complet (bridge optionnel).
    assert status["needs_onboarding"] is False


def test_complete_onboarding_with_broker(db):
    uid = users_service.create_user("alice@test.com", "pw12345678", tier="pro")
    users_service.update_broker_config(
        uid, bridge_url="http://x:8787", bridge_api_key="secret_api_key_12345"
    )
    users_service.update_watched_pairs(uid, ["EUR/USD"])
    status = users_service.is_onboarding_complete(uid)
    assert status["has_broker"] is True
    assert status["has_pairs"] is True
    assert status["needs_onboarding"] is False
