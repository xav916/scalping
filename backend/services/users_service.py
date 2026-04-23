"""Table users + helpers auth bcrypt pour le SaaS multi-tenant.

Chantier 1 du plan SaaS (docs/superpowers/specs/2026-04-23-saas-transformation-plan.md).

Fait :
- Table `users` dans trades.db (même DB que personal_trades pour colocaliser).
- Helpers bcrypt : hash_password / verify_password.
- CRUD de base : create_user / get_user_by_email / get_user_by_id.
- Migration douce : ajoute `user_id INTEGER NULL` à personal_trades, sans
  toucher au comportement existant (colonne `user` TEXT reste la source
  d'autorité jusqu'au chantier 3).

Ne fait PAS (volontairement, scope chantier 1) :
- Refactor des services existants pour utiliser user_id (chantier 3).
- Parcours signup complet / login self-service (chantier 2).
- Stripe / tiers gated (chantier 5-6).
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import bcrypt

logger = logging.getLogger(__name__)

_DB_PATH = Path("/app/data/trades.db") if Path("/app").exists() else Path("trades.db")
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

VALID_TIERS = ("free", "pro", "premium")


@contextmanager
def _conn():
    conn = sqlite3.connect(str(_DB_PATH), isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_users_schema() -> None:
    """Crée la table users + ajoute user_id à personal_trades.

    Idempotent : peut être appelée à chaque démarrage sans effet de bord.
    """
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                tier TEXT NOT NULL DEFAULT 'free',
                stripe_customer_id TEXT,
                stripe_subscription_id TEXT,
                trial_ends_at TEXT,
                created_at TEXT NOT NULL,
                last_login_at TEXT,
                broker_config TEXT,
                watched_pairs TEXT,
                settings TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_users_tier ON users(tier)")

        # Migration douce : personal_trades.user_id (nullable) — pas encore
        # utilisé, simple placeholder pour chantier 3.
        cols = [r[1] for r in c.execute("PRAGMA table_info(personal_trades)").fetchall()]
        if cols and "user_id" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN user_id INTEGER")
            c.execute("CREATE INDEX IF NOT EXISTS idx_pt_user_id ON personal_trades(user_id)")


# ─── Password hashing ─────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Hash bcrypt cost=12. Retourne une str UTF-8 stockable directement."""
    if not password:
        raise ValueError("password ne peut pas être vide")
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Vérifie un password vs un hash bcrypt. False sur hash mal formé."""
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ─── CRUD users ─────────────────────────────────────────────────

def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def create_user(
    email: str,
    password: str,
    tier: str = "free",
    trial_ends_at: Optional[str] = None,
) -> int:
    """Crée un user et retourne son id. Lève ValueError si email déjà pris
    ou tier invalide.
    """
    email_norm = _normalize_email(email)
    if not email_norm or "@" not in email_norm:
        raise ValueError("email invalide")
    if tier not in VALID_TIERS:
        raise ValueError(f"tier invalide : {tier!r} (attendu {VALID_TIERS})")

    pw_hash = hash_password(password)
    now = datetime.now(timezone.utc).isoformat()

    with _conn() as c:
        try:
            cur = c.execute(
                """
                INSERT INTO users (email, password_hash, tier, trial_ends_at, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (email_norm, pw_hash, tier, trial_ends_at, now),
            )
            return int(cur.lastrowid)
        except sqlite3.IntegrityError as e:
            raise ValueError(f"email déjà utilisé : {email_norm}") from e


def get_user_by_email(email: str) -> Optional[dict]:
    email_norm = _normalize_email(email)
    if not email_norm:
        return None
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE email = ?", (email_norm,)).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[dict]:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def touch_last_login(user_id: int) -> None:
    """Met à jour last_login_at — à appeler depuis le flow login (chantier 2)."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, user_id))
