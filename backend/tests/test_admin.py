"""Tests backoffice admin (Chantier 12 SaaS)."""

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


# ─── require_admin ─────────────────────────────────────────

def test_is_admin_legacy_env_bypasses(monkeypatch):
    from backend import app as app_module
    from backend.auth import AuthContext

    monkeypatch.setattr(app_module, "ADMIN_EMAILS", [])
    ctx = AuthContext(username="legacy", user_id=None)
    assert app_module._is_admin(ctx) is True


def test_is_admin_whitelisted(monkeypatch, db):
    from backend import app as app_module
    from backend.auth import AuthContext

    monkeypatch.setattr(app_module, "ADMIN_EMAILS", ["admin@test.com"])
    ctx = AuthContext(username="admin@test.com", user_id=1)
    assert app_module._is_admin(ctx) is True


def test_is_admin_blocks_non_whitelisted(monkeypatch, db):
    from backend import app as app_module
    from backend.auth import AuthContext

    monkeypatch.setattr(app_module, "ADMIN_EMAILS", ["admin@test.com"])
    ctx = AuthContext(username="notadmin@test.com", user_id=1)
    assert app_module._is_admin(ctx) is False


def test_require_admin_403_non_admin(monkeypatch, db):
    from fastapi import HTTPException
    from backend import app as app_module
    from backend.auth import AuthContext

    monkeypatch.setattr(app_module, "ADMIN_EMAILS", [])
    ctx = AuthContext(username="user@test.com", user_id=1)
    with pytest.raises(HTTPException) as exc:
        app_module.require_admin(ctx=ctx)
    assert exc.value.status_code == 403


def test_require_admin_pass_legacy(monkeypatch, db):
    from backend import app as app_module
    from backend.auth import AuthContext

    monkeypatch.setattr(app_module, "ADMIN_EMAILS", [])
    ctx = AuthContext(username="legacy", user_id=None)
    assert app_module.require_admin(ctx=ctx).username == "legacy"


# ─── list_all_users ─────────────────────────────────────────

def test_list_all_users_orders_desc(db):
    users_service.create_user("old@test.com", "pw12345678")
    users_service.create_user("recent@test.com", "pw12345678")
    rows = users_service.list_all_users()
    assert len(rows) == 2
    # Dernier créé en premier
    assert rows[0]["email"] == "recent@test.com"


def test_list_all_users_excludes_password_hash(db):
    users_service.create_user("x@y.com", "pw12345678")
    rows = users_service.list_all_users()
    assert "password_hash" not in rows[0]


# ─── KPIs endpoint logic (via helper test) ─────────────────

def _now_plus(days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def test_admin_users_kpis_counts(db, monkeypatch):
    """Test end-to-end de la logique de calcul KPIs via l'endpoint."""
    from backend import app as app_module
    from backend.auth import AuthContext
    import asyncio

    # Seed : 1 free, 1 pro paying monthly, 1 premium paying yearly, 1 trial actif
    uid_free = users_service.create_user("free@test.com", "pw12345678", tier="free")
    uid_pro = users_service.create_user("pro@test.com", "pw12345678", tier="pro")
    users_service.update_stripe_customer_id(uid_pro, "cus_pro")
    users_service.update_stripe_subscription(
        uid_pro, subscription_id="sub_pro", tier="pro", billing_cycle="monthly"
    )
    uid_prem = users_service.create_user("prem@test.com", "pw12345678", tier="premium")
    users_service.update_stripe_customer_id(uid_prem, "cus_prem")
    users_service.update_stripe_subscription(
        uid_prem, subscription_id="sub_prem", tier="premium", billing_cycle="yearly"
    )
    users_service.create_user(
        "trial@test.com", "pw12345678",
        tier="pro", trial_ends_at=_now_plus(5),
    )

    monkeypatch.setattr(app_module, "ADMIN_EMAILS", [])
    ctx = AuthContext(username="legacy-admin", user_id=None)
    result = asyncio.run(app_module.api_admin_users(_ctx=ctx))
    t = result["totals"]

    assert t["total_users"] == 4
    assert t["active_users"] == 4
    assert t["trials_active"] == 1
    # by_tier effectif : free + trial pro + pro paying + premium paying
    assert t["by_tier"]["free"] == 1
    assert t["by_tier"]["pro"] == 2  # trial + pro paying
    assert t["by_tier"]["premium"] == 1
    # MRR : 19 (pro monthly) + 390/12 = 32.5 (premium yearly) = 51.5
    assert abs(t["mrr_eur"] - (19.0 + 390.0 / 12)) < 0.01


def test_admin_users_mrr_excludes_trials(db, monkeypatch):
    """Un user en trial actif n'est PAS compté dans le MRR."""
    from backend import app as app_module
    from backend.auth import AuthContext
    import asyncio

    users_service.create_user(
        "trial@test.com", "pw12345678",
        tier="pro", trial_ends_at=_now_plus(10),
    )
    monkeypatch.setattr(app_module, "ADMIN_EMAILS", [])
    ctx = AuthContext(username="legacy", user_id=None)
    result = asyncio.run(app_module.api_admin_users(_ctx=ctx))
    assert result["totals"]["mrr_eur"] == 0.0


def test_admin_users_signups_window(db, monkeypatch):
    from backend import app as app_module
    from backend.auth import AuthContext
    import asyncio

    # User créé maintenant (signup 7d = 1)
    users_service.create_user("new@test.com", "pw12345678")
    # User créé il y a 40 jours (hors fenêtre 30j) : manipulé via UPDATE direct
    uid_old = users_service.create_user("old@test.com", "pw12345678")
    old_iso = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    with sqlite3.connect(db) as c:
        c.execute("UPDATE users SET created_at = ? WHERE id = ?", (old_iso, uid_old))

    monkeypatch.setattr(app_module, "ADMIN_EMAILS", [])
    ctx = AuthContext(username="legacy", user_id=None)
    result = asyncio.run(app_module.api_admin_users(_ctx=ctx))
    t = result["totals"]
    assert t["signups_7d"] == 1
    assert t["signups_30d"] == 1
    assert t["total_users"] == 2
