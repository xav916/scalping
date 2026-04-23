"""Seed du premier user admin à partir de AUTH_USERS (env existant).

Chantier 1 SaaS : on crée un user `premium` (toi, propriétaire) dans la table
`users` à partir du AUTH_USERS env actuel, sans casser le fallback env
(qui reste la source d'autorité pour l'auth tant que chantier 2 n'est pas
livré).

Idempotent : si l'email existe déjà en DB, on ne touche à rien. Le password
est hashé à partir de la valeur env actuelle — aucune resynchro automatique
ensuite (si tu changes le password env, ré-exécute le script).

Usage :
    python scripts/seed_admin_user.py [--tier premium]
    python scripts/seed_admin_user.py --email foo@bar.com --password "xxx"
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services import users_service  # noqa: E402
from config.settings import AUTH_USERS  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tier",
        default="premium",
        choices=list(users_service.VALID_TIERS),
        help="tier à attribuer (défaut: premium)",
    )
    parser.add_argument(
        "--email",
        help="email à seed (défaut: premier user trouvé dans AUTH_USERS)",
    )
    parser.add_argument(
        "--password",
        help="password à utiliser (défaut: password AUTH_USERS correspondant)",
    )
    args = parser.parse_args()

    users_service.init_users_schema()

    if args.email and args.password:
        email, password = args.email, args.password
    else:
        if not AUTH_USERS:
            logger.error("AUTH_USERS est vide : fournir --email + --password")
            return 1
        if args.email:
            if args.email not in AUTH_USERS:
                logger.error("Email %s absent de AUTH_USERS", args.email)
                return 1
            email = args.email
            password = AUTH_USERS[email]
        else:
            email = next(iter(AUTH_USERS))
            password = AUTH_USERS[email]

    existing = users_service.get_user_by_email(email)
    if existing:
        logger.info(
            "User %s existe déjà (id=%s, tier=%s) — rien à faire",
            email, existing["id"], existing["tier"],
        )
        return 0

    uid = users_service.create_user(email, password, tier=args.tier)
    logger.info("User créé : id=%s email=%s tier=%s", uid, email, args.tier)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
