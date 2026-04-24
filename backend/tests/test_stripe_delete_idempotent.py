"""Tests du garde-fou customer.subscription.deleted.

Le handler ne doit downgrader le tier que si la sub cancellée correspond
bien à la sub courante du user. Sinon c'est une sub en doublon (user a
cliqué plusieurs fois checkout) dont la suppression ne doit pas toucher
la sub active actuelle.

Reproduit le bug : user id=10 avec 2 subs (sub_OLD annulée, sub_NEW
active) passait à `free` quand `sub_OLD.deleted` arrivait même si
`sub_NEW` restait active — uniquement parce que le handler ignorait le
sub.id de l'event.
"""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from backend.services import stripe_service, users_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_file = tmp_path / "trades.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE personal_trades (id INTEGER PRIMARY KEY, user TEXT, user_id INTEGER)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(users_service, "_DB_PATH", db_file)
    users_service.init_users_schema()
    return db_file


def _stub_event(event_type, obj):
    return {"id": "evt_test", "type": event_type, "data": {"object": obj}}


@pytest.fixture
def patch_webhook(monkeypatch):
    """Court-circuite la vérif HMAC et le gate STRIPE_ENABLED."""
    import stripe as _stripe
    monkeypatch.setattr(
        _stripe.Webhook, "construct_event", lambda payload, sig, secret: payload
    )
    monkeypatch.setattr(stripe_service, "_assert_enabled", lambda: None)
    # Injecte un secret non vide.
    from config import settings
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", "whsec_stub")


class TestSubscriptionDeletedGuard:
    def test_deleted_ignored_if_user_has_different_active_sub(self, db, patch_webhook):
        """Si la sub annulée n'est pas la sub courante, on ignore."""
        uid = users_service.create_user("dup@test.com", "password123")
        users_service.update_stripe_customer_id(uid, "cus_ABC")
        users_service.update_stripe_subscription(
            uid, subscription_id="sub_NEW", tier="pro", billing_cycle="monthly"
        )
        event = _stub_event(
            "customer.subscription.deleted",
            {"id": "sub_OLD", "customer": "cus_ABC"},
        )
        result = stripe_service.handle_webhook(event, "sig")
        assert result == {"applied": None, "reason": "sub_not_current"}
        user = users_service.get_user_by_id(uid)
        assert user["tier"] == "pro"
        assert user["stripe_subscription_id"] == "sub_NEW"

    def test_deleted_downgrades_if_matches_current(self, db, patch_webhook):
        """Si la sub annulée est bien la sub courante, downgrade à free."""
        uid = users_service.create_user("match@test.com", "password123")
        users_service.update_stripe_customer_id(uid, "cus_XYZ")
        users_service.update_stripe_subscription(
            uid, subscription_id="sub_ONLY", tier="pro", billing_cycle="monthly"
        )
        event = _stub_event(
            "customer.subscription.deleted",
            {"id": "sub_ONLY", "customer": "cus_XYZ"},
        )
        # Patch email service pour ne pas envoyer
        with patch("backend.services.user_email_service.dispatch_subscription_event"):
            result = stripe_service.handle_webhook(event, "sig")
        assert result["applied"] == "downgrade"
        user = users_service.get_user_by_id(uid)
        assert user["tier"] == "free"
        assert user["stripe_subscription_id"] is None

    def test_deleted_downgrades_if_user_has_no_current_sub(self, db, patch_webhook):
        """User sans stripe_subscription_id : downgrade quand même (safe default)."""
        uid = users_service.create_user("nosub@test.com", "password123")
        users_service.update_stripe_customer_id(uid, "cus_FOO")
        # Pas de update_stripe_subscription → user.stripe_subscription_id est None
        event = _stub_event(
            "customer.subscription.deleted",
            {"id": "sub_SOMETHING", "customer": "cus_FOO"},
        )
        with patch("backend.services.user_email_service.dispatch_subscription_event"):
            result = stripe_service.handle_webhook(event, "sig")
        assert result["applied"] == "downgrade"
