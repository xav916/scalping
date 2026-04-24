"""Tests Stripe service (Chantier 5 SaaS) — webhook parsing + tier logic.

Mocke `stripe` pour ne jamais hit l'API Stripe réelle. Couvre le chemin
critique : verification signature, dispatch event, update DB.
"""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from backend.services import users_service
from backend.services import stripe_service


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


@pytest.fixture
def enable_stripe(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "STRIPE_ENABLED", True)
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_test_dummy")
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", "whsec_dummy")
    # Monthly + yearly pour chaque tier (4 price ids).
    monkeypatch.setattr(settings, "STRIPE_PRICE_PRO_MONTHLY", "price_pro_monthly_dummy")
    monkeypatch.setattr(settings, "STRIPE_PRICE_PRO_YEARLY", "price_pro_yearly_dummy")
    monkeypatch.setattr(settings, "STRIPE_PRICE_PREMIUM_MONTHLY", "price_premium_monthly_dummy")
    monkeypatch.setattr(settings, "STRIPE_PRICE_PREMIUM_YEARLY", "price_premium_yearly_dummy")
    # Aliases legacy (tests historiques qui lisent STRIPE_PRICE_PRO).
    monkeypatch.setattr(settings, "STRIPE_PRICE_PRO", "price_pro_monthly_dummy")
    monkeypatch.setattr(settings, "STRIPE_PRICE_PREMIUM", "price_premium_monthly_dummy")


# ─── tier rank helpers ─────────────────────────────────────────

def test_tier_rank_order():
    assert users_service.tier_rank("free") < users_service.tier_rank("pro")
    assert users_service.tier_rank("pro") < users_service.tier_rank("premium")


def test_has_min_tier():
    assert users_service.has_min_tier("premium", "pro")
    assert users_service.has_min_tier("pro", "pro")
    assert not users_service.has_min_tier("free", "pro")
    assert users_service.has_min_tier("pro", "free")


# ─── Stripe IDs persistance ───────────────────────────────────

def test_update_stripe_customer_id(db):
    uid = users_service.create_user("x@y.com", "pw12345678")
    users_service.update_stripe_customer_id(uid, "cus_test_123")
    user = users_service.get_user_by_id(uid)
    assert user["stripe_customer_id"] == "cus_test_123"


def test_update_stripe_subscription(db):
    uid = users_service.create_user("x@y.com", "pw12345678")
    users_service.update_stripe_subscription(
        uid, subscription_id="sub_test_abc", tier="pro"
    )
    user = users_service.get_user_by_id(uid)
    assert user["stripe_subscription_id"] == "sub_test_abc"
    assert user["tier"] == "pro"


def test_update_stripe_subscription_persists_cycle(db):
    uid = users_service.create_user("x@y.com", "pw12345678")
    users_service.update_stripe_subscription(
        uid, subscription_id="sub_123", tier="pro", billing_cycle="yearly"
    )
    user = users_service.get_user_by_id(uid)
    assert user["stripe_billing_cycle"] == "yearly"


def test_update_stripe_subscription_free_resets_cycle(db):
    uid = users_service.create_user("x@y.com", "pw12345678", tier="pro")
    users_service.update_stripe_subscription(
        uid, subscription_id="sub_1", tier="pro", billing_cycle="monthly"
    )
    assert users_service.get_user_by_id(uid)["stripe_billing_cycle"] == "monthly"
    # Downgrade free → cycle reset NULL.
    users_service.update_stripe_subscription(
        uid, subscription_id=None, tier="free", billing_cycle="monthly"
    )
    assert users_service.get_user_by_id(uid)["stripe_billing_cycle"] is None


def test_update_stripe_subscription_invalid_cycle(db):
    uid = users_service.create_user("x@y.com", "pw12345678")
    with pytest.raises(ValueError, match="billing_cycle invalide"):
        users_service.update_stripe_subscription(
            uid, subscription_id="s", tier="pro", billing_cycle="weekly"
        )


def test_update_stripe_subscription_rejects_invalid_tier(db):
    uid = users_service.create_user("x@y.com", "pw12345678")
    with pytest.raises(ValueError, match="tier invalide"):
        users_service.update_stripe_subscription(uid, subscription_id="s", tier="gold")


def test_get_user_by_stripe_customer_id(db):
    uid = users_service.create_user("x@y.com", "pw12345678")
    users_service.update_stripe_customer_id(uid, "cus_abc")
    found = users_service.get_user_by_stripe_customer_id("cus_abc")
    assert found is not None and found["id"] == uid
    assert users_service.get_user_by_stripe_customer_id("cus_absent") is None
    assert users_service.get_user_by_stripe_customer_id("") is None


# ─── stripe_service guards ────────────────────────────────────

def test_assert_enabled_false_by_default():
    with pytest.raises(RuntimeError, match="désactivé"):
        stripe_service._assert_enabled()


def test_price_for_tier_requires_configured(monkeypatch, enable_stripe):
    # pro & premium configurés par enable_stripe → OK (monthly par défaut).
    assert stripe_service._price_for_tier("pro") == "price_pro_monthly_dummy"
    assert stripe_service._price_for_tier("premium") == "price_premium_monthly_dummy"


def test_price_for_tier_yearly(monkeypatch, enable_stripe):
    assert stripe_service._price_for_tier("pro", "yearly") == "price_pro_yearly_dummy"
    assert stripe_service._price_for_tier("premium", "yearly") == "price_premium_yearly_dummy"


def test_price_for_tier_invalid_cycle(enable_stripe):
    with pytest.raises(ValueError, match="billing_cycle invalide"):
        stripe_service._price_for_tier("pro", "weekly")


def test_price_for_tier_missing_config_raises(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "STRIPE_ENABLED", True)
    monkeypatch.setattr(settings, "STRIPE_PRICE_PRO_MONTHLY", "")
    with pytest.raises(ValueError, match="price_id"):
        stripe_service._price_for_tier("pro")


def test_price_for_tier_missing_yearly_raises(monkeypatch, enable_stripe):
    from config import settings

    monkeypatch.setattr(settings, "STRIPE_PRICE_PRO_YEARLY", "")
    with pytest.raises(ValueError, match="price_id"):
        stripe_service._price_for_tier("pro", "yearly")


# ─── Webhook dispatch ────────────────────────────────────────

def _fake_event(event_type: str, obj: dict) -> dict:
    return {"id": "evt_test", "type": event_type, "data": {"object": obj}}


def test_webhook_checkout_session_completed(db, enable_stripe):
    uid = users_service.create_user("x@y.com", "pw12345678")
    event = _fake_event(
        "checkout.session.completed",
        {"client_reference_id": str(uid), "customer": "cus_abc"},
    )
    with patch.object(stripe_service.stripe.Webhook, "construct_event", return_value=event):
        result = stripe_service.handle_webhook(b"payload", "sig")

    assert result["applied"] == "customer_id"
    user = users_service.get_user_by_id(uid)
    assert user["stripe_customer_id"] == "cus_abc"


def test_webhook_subscription_created_upgrades_tier(db, enable_stripe):
    uid = users_service.create_user("x@y.com", "pw12345678")
    users_service.update_stripe_customer_id(uid, "cus_abc")

    sub_obj = {
        "id": "sub_123",
        "customer": "cus_abc",
        "items": {"data": [{"price": {"id": "price_premium_monthly_dummy"}}]},
    }
    event = _fake_event("customer.subscription.created", sub_obj)
    with patch.object(stripe_service.stripe.Webhook, "construct_event", return_value=event):
        result = stripe_service.handle_webhook(b"p", "sig")

    assert result["tier"] == "premium"
    assert result["billing_cycle"] == "monthly"
    user = users_service.get_user_by_id(uid)
    assert user["tier"] == "premium"
    assert user["stripe_subscription_id"] == "sub_123"
    assert user["stripe_billing_cycle"] == "monthly"


def test_webhook_subscription_yearly_persists_cycle(db, enable_stripe):
    uid = users_service.create_user("x@y.com", "pw12345678")
    users_service.update_stripe_customer_id(uid, "cus_abc")
    sub_obj = {
        "id": "sub_year_42",
        "customer": "cus_abc",
        "items": {"data": [{"price": {"id": "price_premium_yearly_dummy"}}]},
    }
    event = _fake_event("customer.subscription.updated", sub_obj)
    with patch.object(stripe_service.stripe.Webhook, "construct_event", return_value=event):
        stripe_service.handle_webhook(b"p", "sig")
    assert users_service.get_user_by_id(uid)["stripe_billing_cycle"] == "yearly"


def test_cycle_from_subscription(enable_stripe):
    sub_yearly = {"items": {"data": [{"price": {"id": "price_pro_yearly_dummy"}}]}}
    sub_monthly = {"items": {"data": [{"price": {"id": "price_pro_monthly_dummy"}}]}}
    sub_unknown = {"items": {"data": [{"price": {"id": "price_foo"}}]}}
    assert stripe_service._cycle_from_subscription(sub_yearly) == "yearly"
    assert stripe_service._cycle_from_subscription(sub_monthly) == "monthly"
    assert stripe_service._cycle_from_subscription(sub_unknown) is None
    assert stripe_service._cycle_from_subscription({}) is None


def test_webhook_subscription_updated_downgrades_tier(db, enable_stripe):
    uid = users_service.create_user("x@y.com", "pw12345678", tier="premium")
    users_service.update_stripe_customer_id(uid, "cus_abc")

    # Downgrade vers pro
    sub_obj = {
        "id": "sub_123",
        "customer": "cus_abc",
        "items": {"data": [{"price": {"id": "price_pro_monthly_dummy"}}]},
    }
    event = _fake_event("customer.subscription.updated", sub_obj)
    with patch.object(stripe_service.stripe.Webhook, "construct_event", return_value=event):
        stripe_service.handle_webhook(b"p", "sig")

    assert users_service.get_user_by_id(uid)["tier"] == "pro"


def test_webhook_subscription_deleted_reverts_to_free(db, enable_stripe):
    uid = users_service.create_user("x@y.com", "pw12345678", tier="pro")
    users_service.update_stripe_customer_id(uid, "cus_abc")
    users_service.update_stripe_subscription(uid, subscription_id="sub_old", tier="pro")

    sub_obj = {"id": "sub_old", "customer": "cus_abc"}
    event = _fake_event("customer.subscription.deleted", sub_obj)
    with patch.object(stripe_service.stripe.Webhook, "construct_event", return_value=event):
        result = stripe_service.handle_webhook(b"p", "sig")

    assert result["tier"] == "free"
    user = users_service.get_user_by_id(uid)
    assert user["tier"] == "free"
    assert user["stripe_subscription_id"] is None


def test_webhook_unknown_event_ignored(db, enable_stripe):
    event = _fake_event("some.unrelated.event", {})
    with patch.object(stripe_service.stripe.Webhook, "construct_event", return_value=event):
        result = stripe_service.handle_webhook(b"p", "sig")
    assert result["applied"] is None


def test_webhook_subscription_user_not_found(db, enable_stripe):
    sub_obj = {
        "id": "sub_x",
        "customer": "cus_ghost",
        "items": {"data": [{"price": {"id": "price_pro_dummy"}}]},
    }
    event = _fake_event("customer.subscription.created", sub_obj)
    with patch.object(stripe_service.stripe.Webhook, "construct_event", return_value=event):
        result = stripe_service.handle_webhook(b"p", "sig")
    assert result["applied"] is None
    assert result["reason"] == "user_not_found"


# ─── Price → tier mapping ────────────────────────────────────

def test_tier_from_subscription_premium_monthly(enable_stripe):
    sub = {"items": {"data": [{"price": {"id": "price_premium_monthly_dummy"}}]}}
    assert stripe_service._tier_from_subscription(sub) == "premium"


def test_tier_from_subscription_premium_yearly(enable_stripe):
    """Yearly price mappe au même tier (cycle change pas les features)."""
    sub = {"items": {"data": [{"price": {"id": "price_premium_yearly_dummy"}}]}}
    assert stripe_service._tier_from_subscription(sub) == "premium"


def test_tier_from_subscription_pro_monthly(enable_stripe):
    sub = {"items": {"data": [{"price": {"id": "price_pro_monthly_dummy"}}]}}
    assert stripe_service._tier_from_subscription(sub) == "pro"


def test_tier_from_subscription_pro_yearly(enable_stripe):
    sub = {"items": {"data": [{"price": {"id": "price_pro_yearly_dummy"}}]}}
    assert stripe_service._tier_from_subscription(sub) == "pro"


def test_tier_from_subscription_unknown_price_defaults_free(enable_stripe):
    sub = {"items": {"data": [{"price": {"id": "price_unknown_xxx"}}]}}
    assert stripe_service._tier_from_subscription(sub) == "free"


def test_tier_from_subscription_empty_items(enable_stripe):
    assert stripe_service._tier_from_subscription({}) == "free"


# ─── Checkout session creation (mocked) ──────────────────────

def test_create_checkout_session_returns_url(db, enable_stripe):
    fake_session = MagicMock()
    fake_session.url = "https://checkout.stripe.com/c/pay/cs_test_123"
    with patch.object(stripe_service.stripe.checkout.Session, "create", return_value=fake_session) as mk:
        url = stripe_service.create_checkout_session(
            user_id=1, user_email="x@y.com", tier="pro"
        )
    assert url == "https://checkout.stripe.com/c/pay/cs_test_123"
    kwargs = mk.call_args.kwargs
    # Défaut = monthly.
    assert kwargs["line_items"][0]["price"] == "price_pro_monthly_dummy"
    assert kwargs["customer_email"] == "x@y.com"
    assert kwargs["client_reference_id"] == "1"
    assert kwargs["metadata"]["billing_cycle"] == "monthly"


def test_create_checkout_session_yearly(db, enable_stripe):
    fake_session = MagicMock()
    fake_session.url = "https://checkout.stripe.com/yearly"
    with patch.object(stripe_service.stripe.checkout.Session, "create", return_value=fake_session) as mk:
        stripe_service.create_checkout_session(
            user_id=1, user_email="x@y.com", tier="premium", billing_cycle="yearly"
        )
    kwargs = mk.call_args.kwargs
    assert kwargs["line_items"][0]["price"] == "price_premium_yearly_dummy"
    assert kwargs["metadata"]["billing_cycle"] == "yearly"


def test_create_checkout_reuses_existing_customer(db, enable_stripe):
    fake_session = MagicMock()
    fake_session.url = "https://checkout.stripe.com/x"
    with patch.object(stripe_service.stripe.checkout.Session, "create", return_value=fake_session) as mk:
        stripe_service.create_checkout_session(
            user_id=1, user_email="x@y.com", tier="premium",
            existing_customer_id="cus_existing",
        )
    kwargs = mk.call_args.kwargs
    assert kwargs["customer"] == "cus_existing"
    assert "customer_email" not in kwargs
