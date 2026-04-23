"""Wrapper Stripe pour checkout + webhook + customer portal (Chantier 5 SaaS).

Gated par STRIPE_ENABLED en config. Tant que ça n'est pas true, les
fonctions lèvent RuntimeError → les routes qui les appellent retournent 503
"Stripe not configured".

Trois flux :
1. create_checkout_session(user, tier) → URL Stripe Checkout pour upgrade
2. create_portal_session(user) → URL Customer Portal pour gérer sub/card
3. handle_webhook(payload, sig_header) → parse event signé + update DB
"""

from __future__ import annotations

import logging
from typing import Any

import stripe

from backend.services import users_service
from config import settings

logger = logging.getLogger(__name__)


def _assert_enabled() -> None:
    if not settings.STRIPE_ENABLED:
        raise RuntimeError("Stripe désactivé (STRIPE_ENABLED=false)")
    if not settings.STRIPE_SECRET_KEY:
        raise RuntimeError("STRIPE_SECRET_KEY non configuré")
    stripe.api_key = settings.STRIPE_SECRET_KEY


def _price_for_tier(tier: str) -> str:
    mapping = {
        "pro": settings.STRIPE_PRICE_PRO,
        "premium": settings.STRIPE_PRICE_PREMIUM,
    }
    price_id = mapping.get(tier)
    if not price_id:
        raise ValueError(f"Pas de price_id Stripe configuré pour tier={tier!r}")
    return price_id


def create_checkout_session(
    user_id: int,
    user_email: str,
    tier: str,
    *,
    existing_customer_id: str | None = None,
) -> str:
    """Crée une Checkout Session pour upgrade du user au tier donné.

    Retourne l'URL Stripe à laquelle rediriger le front.
    """
    _assert_enabled()
    price_id = _price_for_tier(tier)

    kwargs: dict[str, Any] = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": settings.STRIPE_SUCCESS_URL,
        "cancel_url": settings.STRIPE_CANCEL_URL,
        "client_reference_id": str(user_id),
        "metadata": {"user_id": str(user_id), "tier": tier},
    }
    # Si le user a déjà un customer Stripe, le réutiliser (sinon Stripe
    # crée automatiquement un customer vu l'email).
    if existing_customer_id:
        kwargs["customer"] = existing_customer_id
    else:
        kwargs["customer_email"] = user_email

    session = stripe.checkout.Session.create(**kwargs)
    return session.url  # type: ignore[no-any-return]


def create_portal_session(customer_id: str, return_url: str) -> str:
    """URL du Customer Portal Stripe (gestion sub, cartes, factures)."""
    _assert_enabled()
    if not customer_id:
        raise ValueError("customer_id requis pour le portal")
    session = stripe.billing_portal.Session.create(
        customer=customer_id, return_url=return_url
    )
    return session.url  # type: ignore[no-any-return]


# ─── Webhook handler ──────────────────────────────────────────

# Mapping price_id → tier pour dériver le tier d'une subscription.
def _price_to_tier_map() -> dict[str, str]:
    return {
        settings.STRIPE_PRICE_PRO: "pro",
        settings.STRIPE_PRICE_PREMIUM: "premium",
    }


def _tier_from_subscription(sub: dict) -> str:
    """Extrait le tier d'une Subscription Stripe via son price_id."""
    items = (sub.get("items") or {}).get("data") or []
    if not items:
        return "free"
    price_id = (items[0].get("price") or {}).get("id", "")
    return _price_to_tier_map().get(price_id, "free")


def handle_webhook(payload: bytes, sig_header: str) -> dict:
    """Parse + dispatch un webhook Stripe. Applique l'event sur la DB
    (update tier, subscription_id, customer_id).

    Retourne un dict résumé pour la réponse (principalement du debug).
    """
    _assert_enabled()
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET non configuré")

    event = stripe.Webhook.construct_event(
        payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
    )

    event_type = event["type"]
    obj = event["data"]["object"]
    logger.info("Stripe webhook reçu : %s (id=%s)", event_type, event.get("id"))

    if event_type == "checkout.session.completed":
        user_id = int(obj.get("client_reference_id") or 0)
        customer_id = obj.get("customer")
        if user_id and customer_id:
            users_service.update_stripe_customer_id(user_id, customer_id)
        return {"applied": "customer_id", "user_id": user_id}

    if event_type in ("customer.subscription.created", "customer.subscription.updated"):
        customer_id = obj.get("customer")
        tier = _tier_from_subscription(obj)
        user = users_service.get_user_by_stripe_customer_id(customer_id)
        if not user:
            logger.warning("Webhook %s : aucun user avec customer_id=%s", event_type, customer_id)
            return {"applied": None, "reason": "user_not_found"}
        users_service.update_stripe_subscription(
            user["id"], subscription_id=obj.get("id"), tier=tier
        )
        return {"applied": "subscription", "user_id": user["id"], "tier": tier}

    if event_type == "customer.subscription.deleted":
        customer_id = obj.get("customer")
        user = users_service.get_user_by_stripe_customer_id(customer_id)
        if not user:
            return {"applied": None, "reason": "user_not_found"}
        users_service.update_stripe_subscription(
            user["id"], subscription_id=None, tier="free"
        )
        return {"applied": "downgrade", "user_id": user["id"], "tier": "free"}

    logger.debug("Stripe webhook %s ignoré (non géré)", event_type)
    return {"applied": None, "event_type": event_type}
