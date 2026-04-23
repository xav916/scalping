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


VALID_BILLING_CYCLES = ("monthly", "yearly")


def _price_for_tier(tier: str, billing_cycle: str = "monthly") -> str:
    """Résout le price_id Stripe pour (tier, cycle).

    Lève ValueError si non configuré ou cycle invalide.
    """
    if billing_cycle not in VALID_BILLING_CYCLES:
        raise ValueError(
            f"billing_cycle invalide : {billing_cycle!r} (attendu {VALID_BILLING_CYCLES})"
        )
    mapping = {
        ("pro", "monthly"): settings.STRIPE_PRICE_PRO_MONTHLY,
        ("pro", "yearly"): settings.STRIPE_PRICE_PRO_YEARLY,
        ("premium", "monthly"): settings.STRIPE_PRICE_PREMIUM_MONTHLY,
        ("premium", "yearly"): settings.STRIPE_PRICE_PREMIUM_YEARLY,
    }
    price_id = mapping.get((tier, billing_cycle))
    if not price_id:
        raise ValueError(
            f"Pas de price_id Stripe configuré pour tier={tier!r} cycle={billing_cycle!r}"
        )
    return price_id


def create_checkout_session(
    user_id: int,
    user_email: str,
    tier: str,
    *,
    billing_cycle: str = "monthly",
    existing_customer_id: str | None = None,
) -> str:
    """Crée une Checkout Session pour upgrade du user au tier donné.

    `billing_cycle` : 'monthly' (défaut) ou 'yearly'.
    Retourne l'URL Stripe à laquelle rediriger le front.
    """
    _assert_enabled()
    price_id = _price_for_tier(tier, billing_cycle)

    kwargs: dict[str, Any] = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": settings.STRIPE_SUCCESS_URL,
        "cancel_url": settings.STRIPE_CANCEL_URL,
        "client_reference_id": str(user_id),
        "metadata": {"user_id": str(user_id), "tier": tier, "billing_cycle": billing_cycle},
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

# Mapping price_id → tier pour dériver le tier d'une subscription. On map les
# 4 prices (monthly + yearly × pro + premium) au même tier — le billing cycle
# n'influe pas sur les features accordées, juste sur la facturation.
def _price_to_tier_map() -> dict[str, str]:
    m: dict[str, str] = {}
    for price_id in (settings.STRIPE_PRICE_PRO_MONTHLY, settings.STRIPE_PRICE_PRO_YEARLY):
        if price_id:
            m[price_id] = "pro"
    for price_id in (settings.STRIPE_PRICE_PREMIUM_MONTHLY, settings.STRIPE_PRICE_PREMIUM_YEARLY):
        if price_id:
            m[price_id] = "premium"
    return m


def _tier_from_subscription(sub: dict) -> str:
    """Extrait le tier d'une Subscription Stripe via son price_id."""
    items = (sub.get("items") or {}).get("data") or []
    if not items:
        return "free"
    price_id = (items[0].get("price") or {}).get("id", "")
    return _price_to_tier_map().get(price_id, "free")


def _price_to_cycle_map() -> dict[str, str]:
    """Mapping price_id → billing_cycle ('monthly'|'yearly')."""
    m: dict[str, str] = {}
    for p in (settings.STRIPE_PRICE_PRO_MONTHLY, settings.STRIPE_PRICE_PREMIUM_MONTHLY):
        if p:
            m[p] = "monthly"
    for p in (settings.STRIPE_PRICE_PRO_YEARLY, settings.STRIPE_PRICE_PREMIUM_YEARLY):
        if p:
            m[p] = "yearly"
    return m


def _cycle_from_subscription(sub: dict) -> str | None:
    """Extrait le billing_cycle d'une Subscription Stripe via son price_id."""
    items = (sub.get("items") or {}).get("data") or []
    if not items:
        return None
    price_id = (items[0].get("price") or {}).get("id", "")
    return _price_to_cycle_map().get(price_id)


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
        cycle = _cycle_from_subscription(obj)
        user = users_service.get_user_by_stripe_customer_id(customer_id)
        if not user:
            logger.warning("Webhook %s : aucun user avec customer_id=%s", event_type, customer_id)
            return {"applied": None, "reason": "user_not_found"}
        users_service.update_stripe_subscription(
            user["id"],
            subscription_id=obj.get("id"),
            tier=tier,
            billing_cycle=cycle,
        )
        return {
            "applied": "subscription",
            "user_id": user["id"],
            "tier": tier,
            "billing_cycle": cycle,
        }

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
