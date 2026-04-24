"""Crée automatiquement les 4 produits Stripe du SaaS Scalping Radar.

Usage :
    python scripts/setup_stripe_products.py --secret-key sk_test_xxx...

Crée :
- Produit `Scalping Radar Pro` avec 2 prix : 19 EUR/mois, 190 EUR/an
- Produit `Scalping Radar Premium` avec 2 prix : 39 EUR/mois, 390 EUR/an

Idempotent : skip la création si un produit du même nom existe déjà
(lookup par `name` dans la liste des produits actifs). Les prix sont
toujours créés (Stripe ne permet pas de modifier un prix existant, il
faut en créer un nouveau et archiver l'ancien).

Imprime à la fin les 4 `price_XXX` à copier dans /opt/scalping/.env EC2.
"""

from __future__ import annotations

import argparse
import sys

import stripe


PRODUCTS = {
    "Scalping Radar Pro": {
        "description": "Dashboard complet, 5 paires, alertes Telegram, analytics illimitées.",
        "prices": [
            ("STRIPE_PRICE_PRO_MONTHLY", 1900, "month"),
            ("STRIPE_PRICE_PRO_YEARLY", 19000, "year"),  # 2 mois offerts
        ],
    },
    "Scalping Radar Premium": {
        "description": "Tout Pro + backtest + multi-broker + auto-exec MT5 bridge.",
        "prices": [
            ("STRIPE_PRICE_PREMIUM_MONTHLY", 3900, "month"),
            ("STRIPE_PRICE_PREMIUM_YEARLY", 39000, "year"),
        ],
    },
}


def _find_existing_product(name: str) -> stripe.Product | None:
    """Retourne le produit actif du nom donné, None sinon.

    Note : limite 100 produits sur l'account, suffisant pour ce besoin.
    """
    products = stripe.Product.list(active=True, limit=100)
    for p in products.auto_paging_iter():
        if p.name == name:
            return p
    return None


def setup_products() -> dict[str, str]:
    """Crée (ou retrouve) les 4 produits + prix. Retourne un dict
    `{env_var_name: price_id}` à copier dans .env.
    """
    env_vars: dict[str, str] = {}

    for product_name, meta in PRODUCTS.items():
        existing = _find_existing_product(product_name)
        if existing:
            print(f"✓ Produit existant trouvé : {product_name} (id={existing.id})")
            product = existing
        else:
            print(f"+ Création produit : {product_name}")
            product = stripe.Product.create(
                name=product_name,
                description=meta["description"],
            )

        for env_name, unit_amount, interval in meta["prices"]:
            # Stripe recommande de créer un nouveau prix plutôt que de modifier
            # un prix existant. On crée systématiquement un prix pour garantir
            # des unit_amounts à jour si on re-lance le script.
            price = stripe.Price.create(
                product=product.id,
                unit_amount=unit_amount,
                currency="eur",
                recurring={"interval": interval},
                nickname=f"{product_name} — {interval}",
            )
            env_vars[env_name] = price.id
            eur = unit_amount / 100
            print(f"  + Prix {interval} {eur:.2f} EUR → {price.id}")

    return env_vars


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--secret-key",
        required=True,
        help="Stripe secret key (sk_test_xxx ou sk_live_xxx)",
    )
    args = parser.parse_args()

    if not args.secret_key.startswith(("sk_test_", "sk_live_")):
        print("ERREUR : --secret-key doit commencer par sk_test_ ou sk_live_", file=sys.stderr)
        sys.exit(1)

    stripe.api_key = args.secret_key
    mode = "LIVE" if args.secret_key.startswith("sk_live_") else "TEST"
    print(f"=== Stripe mode {mode} ===")

    env_vars = setup_products()

    print("\n=== À copier dans /opt/scalping/.env EC2 ===")
    for k, v in env_vars.items():
        print(f"{k}={v}")


if __name__ == "__main__":
    main()
