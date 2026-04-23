"""Tests du trial Pro 14j (Chantier 9 SaaS).

Couvre :
- effective_tier : paying sub, trial actif, trial expiré, free
- trial_status : days_left, active flag
- signup crée bien le user avec tier=pro + trial_ends_at
- require_min_tier respecte l'expiration de trial
"""

import sqlite3
from datetime import datetime, timedelta, timezone

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


def _now_plus(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


# ─── effective_tier ────────────────────────────────────────

def test_effective_tier_free_user():
    assert users_service.effective_tier({"tier": "free"}) == "free"


def test_effective_tier_none_user():
    assert users_service.effective_tier(None) == "free"


def test_effective_tier_paying_sub_is_source_of_truth():
    user = {
        "tier": "premium",
        "stripe_subscription_id": "sub_abc",
        "trial_ends_at": None,
    }
    assert users_service.effective_tier(user) == "premium"


def test_effective_tier_trial_active():
    user = {
        "tier": "pro",
        "stripe_subscription_id": None,
        "trial_ends_at": _now_plus(10),
    }
    assert users_service.effective_tier(user) == "pro"


def test_effective_tier_trial_expired_no_sub():
    user = {
        "tier": "pro",
        "stripe_subscription_id": None,
        "trial_ends_at": _now_plus(-1),
    }
    assert users_service.effective_tier(user) == "free"


def test_effective_tier_trial_expired_with_sub_keeps_tier():
    """Si user a payé AVANT expiration trial, tier stocké reste valide."""
    user = {
        "tier": "premium",
        "stripe_subscription_id": "sub_123",
        "trial_ends_at": _now_plus(-5),
    }
    assert users_service.effective_tier(user) == "premium"


def test_effective_tier_trial_never_set():
    user = {
        "tier": "pro",
        "stripe_subscription_id": None,
        "trial_ends_at": None,
    }
    # Pas de trial, pas de sub → effectivement free.
    assert users_service.effective_tier(user) == "free"


def test_effective_tier_malformed_trial_date():
    user = {
        "tier": "pro",
        "stripe_subscription_id": None,
        "trial_ends_at": "not-a-date",
    }
    assert users_service.effective_tier(user) == "free"


# ─── trial_status ──────────────────────────────────────────

def test_trial_status_active():
    user = {
        "tier": "pro",
        "stripe_subscription_id": None,
        "trial_ends_at": _now_plus(10),
    }
    s = users_service.trial_status(user)
    assert s["trial_active"] is True
    assert 9 <= s["trial_days_left"] <= 10


def test_trial_status_expired():
    user = {
        "tier": "pro",
        "stripe_subscription_id": None,
        "trial_ends_at": _now_plus(-1),
    }
    s = users_service.trial_status(user)
    assert s["trial_active"] is False
    assert s["trial_days_left"] == 0


def test_trial_status_paying_user_inactive():
    """User qui a payé pendant trial : trial_active=False (plus besoin)."""
    user = {
        "tier": "premium",
        "stripe_subscription_id": "sub_abc",
        "trial_ends_at": _now_plus(5),
    }
    s = users_service.trial_status(user)
    assert s["trial_active"] is False


def test_trial_status_no_trial_user():
    s = users_service.trial_status({"tier": "free"})
    assert s["trial_active"] is False
    assert s["trial_days_left"] is None


# ─── Integration : signup + DB persistence ─────────────────

def test_signup_persists_trial_end(db):
    uid = users_service.create_user(
        "alice@test.com",
        "pw12345678",
        tier=users_service.SIGNUP_TRIAL_TIER,
        trial_ends_at=users_service.new_trial_end_iso(),
    )
    user = users_service.get_user_by_id(uid)
    assert user["tier"] == "pro"
    assert user["trial_ends_at"] is not None
    # trial_ends_at ≈ now + 14d.
    end = datetime.fromisoformat(user["trial_ends_at"])
    delta = end - datetime.now(timezone.utc)
    assert timedelta(days=13) < delta < timedelta(days=15)


def test_effective_tier_fresh_signup_is_pro(db):
    uid = users_service.create_user(
        "alice@test.com",
        "pw12345678",
        tier=users_service.SIGNUP_TRIAL_TIER,
        trial_ends_at=users_service.new_trial_end_iso(),
    )
    user = users_service.get_user_by_id(uid)
    assert users_service.effective_tier(user) == "pro"


def test_new_trial_end_iso_14_days():
    iso = users_service.new_trial_end_iso()
    end = datetime.fromisoformat(iso)
    delta = end - datetime.now(timezone.utc)
    assert timedelta(days=13, hours=23) < delta <= timedelta(days=14)


# ─── Gating effective_tier via require_min_tier ────────────

def test_require_min_tier_blocks_expired_trial(db):
    from fastapi import HTTPException
    from backend import app as app_module
    from backend.auth import AuthContext

    uid = users_service.create_user(
        "alice@test.com", "pw12345678",
        tier="pro",
        trial_ends_at=_now_plus(-1),  # expiré
    )
    dep = app_module.require_min_tier("pro")
    ctx = AuthContext(username="alice@test.com", user_id=uid)
    with pytest.raises(HTTPException) as exc:
        dep(ctx=ctx)
    assert exc.value.status_code == 403


def test_require_min_tier_allows_active_trial(db):
    from backend import app as app_module
    from backend.auth import AuthContext

    uid = users_service.create_user(
        "alice@test.com", "pw12345678",
        tier="pro",
        trial_ends_at=_now_plus(5),  # actif
    )
    dep = app_module.require_min_tier("pro")
    ctx = AuthContext(username="alice@test.com", user_id=uid)
    assert dep(ctx=ctx).user_id == uid
