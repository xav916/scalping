"""Tests feature gating par tier (Chantier 6 SaaS).

Couvre :
- users_service.max_lookback_days par tier
- clamp_since_iso pour Free (cap 7j) vs Pro/Premium (no cap)
- require_min_tier dep : 403 si insuffisant, pass si OK ou legacy env
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


# ─── max_lookback_days ─────────────────────────────────────

def test_free_lookback_7_days():
    assert users_service.max_lookback_days("free") == 7


def test_pro_lookback_unlimited():
    assert users_service.max_lookback_days("pro") is None


def test_premium_lookback_unlimited():
    assert users_service.max_lookback_days("premium") is None


def test_unknown_tier_defaults_to_7():
    assert users_service.max_lookback_days("enterprise") == 7


# ─── clamp_since_iso ─────────────────────────────────────

def test_clamp_free_caps_at_7_days():
    """Free avec since=1 an dans le passé → clampé à today-7d."""
    old = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    clamped = users_service.clamp_since_iso(old, "free")
    # Le clamp doit être récent (< 8 jours)
    parsed = datetime.fromisoformat(clamped)
    delta = datetime.now(timezone.utc) - parsed
    assert delta < timedelta(days=8)
    assert delta > timedelta(days=6)


def test_clamp_free_none_returns_floor():
    clamped = users_service.clamp_since_iso(None, "free")
    assert clamped is not None
    parsed = datetime.fromisoformat(clamped)
    delta = datetime.now(timezone.utc) - parsed
    assert timedelta(days=6) < delta < timedelta(days=8)


def test_clamp_pro_no_op():
    old = "2020-01-01T00:00:00+00:00"
    assert users_service.clamp_since_iso(old, "pro") == old
    assert users_service.clamp_since_iso(None, "pro") is None


def test_clamp_premium_no_op():
    old = "2020-01-01T00:00:00+00:00"
    assert users_service.clamp_since_iso(old, "premium") == old


def test_clamp_free_recent_since_unchanged():
    """Free avec since=hier (dans les 7j) → non modifié."""
    recent = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    clamped = users_service.clamp_since_iso(recent, "free")
    assert clamped == recent


# ─── require_min_tier dep ─────────────────────────────────

def test_require_min_tier_blocks_free_on_pro_route(db):
    from fastapi import HTTPException
    from backend import app as app_module
    from backend.auth import AuthContext

    uid = users_service.create_user("free@test.com", "pw12345678", tier="free")
    dep = app_module.require_min_tier("pro")
    ctx = AuthContext(username="free@test.com", user_id=uid)
    with pytest.raises(HTTPException) as exc:
        dep(ctx=ctx)
    assert exc.value.status_code == 403


def test_require_min_tier_allows_pro(db):
    from backend import app as app_module
    from backend.auth import AuthContext

    uid = users_service.create_user("pro@test.com", "pw12345678", tier="pro")
    # Simule sub Stripe active pour que effective_tier respecte le tier stocké
    # (sans stripe_subscription_id et sans trial, un pro est considéré free).
    users_service.update_stripe_subscription(
        uid, subscription_id="sub_test_pro", tier="pro", billing_cycle="monthly"
    )
    dep = app_module.require_min_tier("pro")
    ctx = AuthContext(username="pro@test.com", user_id=uid)
    result = dep(ctx=ctx)
    assert result.user_id == uid


def test_require_min_tier_allows_premium_on_pro_route(db):
    from backend import app as app_module
    from backend.auth import AuthContext

    uid = users_service.create_user("prem@test.com", "pw12345678", tier="premium")
    users_service.update_stripe_subscription(
        uid, subscription_id="sub_test_prem", tier="premium", billing_cycle="monthly"
    )
    dep = app_module.require_min_tier("pro")
    ctx = AuthContext(username="prem@test.com", user_id=uid)
    assert dep(ctx=ctx).user_id == uid


def test_require_premium_blocks_pro(db):
    from fastapi import HTTPException
    from backend import app as app_module
    from backend.auth import AuthContext

    uid = users_service.create_user("pro@test.com", "pw12345678", tier="pro")
    dep = app_module.require_min_tier("premium")
    ctx = AuthContext(username="pro@test.com", user_id=uid)
    with pytest.raises(HTTPException) as exc:
        dep(ctx=ctx)
    assert exc.value.status_code == 403


def test_require_min_tier_legacy_env_allowed(db):
    """User legacy env (user_id=None) = admin = passe tous les gates."""
    from backend import app as app_module
    from backend.auth import AuthContext

    dep_premium = app_module.require_min_tier("premium")
    ctx = AuthContext(username="legacy", user_id=None)
    assert dep_premium(ctx=ctx).username == "legacy"
