"""Backfill signal_rejections.user_id pour les rows legacy (user_id IS NULL).

Chantier 3D SaaS : les rejections enregistrées avant la migration n'avaient
pas de user attribué. En mono-tenant prod actuel, toutes sont attribuables
au user admin.

Par défaut, attribue toutes les rows NULL à l'user dont l'email est passé
via --email, ou au premier user trouvé dans la table users sinon.

Usage :
    python scripts/backfill_rejections_user_id.py --dry-run
    python scripts/backfill_rejections_user_id.py --email admin@foo.com
    python scripts/backfill_rejections_user_id.py --user-id 1
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services import rejection_service, users_service  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--user-id", type=int, help="id direct à attribuer")
    parser.add_argument("--email", help="email du user à résoudre puis attribuer")
    args = parser.parse_args()

    users_service.init_users_schema()
    rejection_service._ensure_schema()

    # Résout l'id cible.
    target_id: int | None = None
    if args.user_id:
        u = users_service.get_user_by_id(args.user_id)
        if not u:
            logger.error("user_id %s absent de la table users", args.user_id)
            return 1
        target_id = args.user_id
    elif args.email:
        u = users_service.get_user_by_email(args.email)
        if not u:
            logger.error("email %s absent de la table users", args.email)
            return 1
        target_id = int(u["id"])
    else:
        # Défaut : premier user de la table (le plus ancien, typiquement l'admin).
        with sqlite3.connect(users_service._DB_PATH) as conn:
            row = conn.execute("SELECT id, email FROM users ORDER BY id ASC LIMIT 1").fetchone()
        if not row:
            logger.error(
                "Aucun user en DB — crée d'abord un user via seed_admin_user.py "
                "ou fournir --user-id / --email"
            )
            return 1
        target_id = int(row[0])
        logger.info("Target par défaut : user id=%s (%s)", target_id, row[1])

    db_path = rejection_service._db_path()
    with sqlite3.connect(db_path) as conn:
        n_null = conn.execute(
            "SELECT COUNT(*) FROM signal_rejections WHERE user_id IS NULL"
        ).fetchone()[0]
        logger.info("Rows user_id NULL : %d → target user_id=%s", n_null, target_id)

        if n_null == 0:
            logger.info("Rien à backfiller")
            return 0

        if args.dry_run:
            logger.info("--dry-run : aucune écriture")
            return 0

        conn.execute(
            "UPDATE signal_rejections SET user_id = ? WHERE user_id IS NULL",
            (target_id,),
        )
        conn.commit()
        logger.info("Backfill OK : %d rows attribuées à user_id=%s", n_null, target_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
