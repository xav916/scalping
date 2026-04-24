"""Backfill personal_trades.user_id depuis personal_trades.user (email).

Chantier 3 SaaS : les trades existants ont un champ `user` TEXT (email) mais
pas encore de `user_id`. Ce script matche chaque trade à un user en DB via
l'email et remplit `user_id`.

Idempotent :
- ne touche que les rows où user_id IS NULL
- ne touche pas si aucun user matching trouvé (rapport en warning)
- peut être relancé à l'infini sans effet de bord

Usage :
    python scripts/backfill_user_id.py              # full backfill
    python scripts/backfill_user_id.py --dry-run    # rapport seul
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services import users_service  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="N'écrit rien, affiche le rapport seul",
    )
    args = parser.parse_args()

    users_service.init_users_schema()
    db_path = users_service._DB_PATH

    if not Path(db_path).exists():
        logger.error("DB %s absente", db_path)
        return 1

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, user FROM personal_trades "
            "WHERE user_id IS NULL AND user IS NOT NULL AND user != ''"
        ).fetchall()

        if not rows:
            logger.info("Rien à backfiller (toutes les rows ont déjà un user_id)")
            return 0

        # Map email → users.id (1 seul lookup par email).
        unique_emails = sorted({r["user"] for r in rows})
        email_to_id: dict[str, int | None] = {}
        for email in unique_emails:
            u = users_service.get_user_by_email(email)
            email_to_id[email] = u["id"] if u else None

        resolved = {e: uid for e, uid in email_to_id.items() if uid is not None}
        orphans = [e for e, uid in email_to_id.items() if uid is None]

        logger.info("Rows à traiter : %d (uniques emails : %d)", len(rows), len(unique_emails))
        logger.info("Emails matchés  : %d → %s", len(resolved), resolved)
        if orphans:
            logger.warning(
                "Emails sans user en DB (trades resteront orphelins user_id=NULL) : %s",
                orphans,
            )

        if args.dry_run:
            logger.info("--dry-run : aucune écriture")
            return 0

        # Batched update.
        updated_by_user: Counter[str] = Counter()
        for row in rows:
            uid = email_to_id.get(row["user"])
            if uid is None:
                continue
            conn.execute(
                "UPDATE personal_trades SET user_id = ? WHERE id = ?",
                (uid, row["id"]),
            )
            updated_by_user[row["user"]] += 1
        conn.commit()

    logger.info("Backfill terminé. Updates par email : %s", dict(updated_by_user))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
