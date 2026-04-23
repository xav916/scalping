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

import json

import bcrypt

logger = logging.getLogger(__name__)

_DB_PATH = Path("/app/data/trades.db") if Path("/app").exists() else Path("trades.db")
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

VALID_TIERS = ("free", "pro", "premium")

# Ordre des tiers pour feature gating : free < pro < premium.
TIER_RANK = {"free": 0, "pro": 1, "premium": 2}


def tier_rank(tier: str) -> int:
    return TIER_RANK.get(tier, 0)


def has_min_tier(user_tier: str, min_tier: str) -> bool:
    """True si user_tier >= min_tier. Défaut 'free' pour les unknowns."""
    return tier_rank(user_tier) >= tier_rank(min_tier)


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


# ─── Broker config + watched pairs (Chantier 4 SaaS onboarding) ──────

def get_broker_config(user_id: int) -> dict:
    """Retourne le dict broker_config du user. {} si non configuré."""
    user = get_user_by_id(user_id)
    if not user or not user.get("broker_config"):
        return {}
    try:
        return json.loads(user["broker_config"])
    except (json.JSONDecodeError, TypeError):
        return {}


def update_broker_config(
    user_id: int,
    *,
    bridge_url: str,
    bridge_api_key: str,
    broker_name: Optional[str] = None,
) -> None:
    """Persiste la config broker du user (bridge URL + API key).

    Validation basique : URL non vide, api_key min 16 chars pour éviter les
    entrées vides accidentelles.
    """
    if not bridge_url or "://" not in bridge_url:
        raise ValueError("bridge_url invalide (doit contenir http:// ou https://)")
    if not bridge_api_key or len(bridge_api_key) < 16:
        raise ValueError("bridge_api_key trop court (16 caractères min)")

    payload = {
        "bridge_url": bridge_url.rstrip("/"),
        "bridge_api_key": bridge_api_key,
    }
    if broker_name:
        payload["broker_name"] = broker_name

    with _conn() as c:
        c.execute(
            "UPDATE users SET broker_config = ? WHERE id = ?",
            (json.dumps(payload), user_id),
        )


def get_watched_pairs(user_id: int) -> list[str]:
    """Liste des paires surveillées par le user. [] si non configuré."""
    user = get_user_by_id(user_id)
    if not user or not user.get("watched_pairs"):
        return []
    try:
        val = json.loads(user["watched_pairs"])
        return val if isinstance(val, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


# Cap nombre de pairs par tier (SaaS).
MAX_PAIRS_PER_TIER = {"free": 1, "pro": 5, "premium": 16}


def update_watched_pairs(user_id: int, pairs: list[str]) -> list[str]:
    """Remplace les paires surveillées, cap selon tier. Retourne la liste
    persistée (tronquée si au-delà du tier).
    """
    if not isinstance(pairs, list):
        raise ValueError("pairs doit être une liste")
    user = get_user_by_id(user_id)
    if not user:
        raise ValueError(f"user_id {user_id} introuvable")

    tier = user.get("tier", "free")
    cap = MAX_PAIRS_PER_TIER.get(tier, 1)

    # Dédup + normalise (uppercase).
    clean = []
    seen = set()
    for p in pairs:
        if not isinstance(p, str):
            continue
        norm = p.strip().upper()
        if norm and norm not in seen:
            seen.add(norm)
            clean.append(norm)

    truncated = clean[:cap]

    with _conn() as c:
        c.execute(
            "UPDATE users SET watched_pairs = ? WHERE id = ?",
            (json.dumps(truncated), user_id),
        )
    return truncated


# ─── Stripe IDs + tier transitions (Chantier 5 SaaS) ────────────

def update_stripe_customer_id(user_id: int, customer_id: str) -> None:
    """Persiste le customer_id Stripe lors du 1er checkout."""
    with _conn() as c:
        c.execute(
            "UPDATE users SET stripe_customer_id = ? WHERE id = ?",
            (customer_id, user_id),
        )


def update_stripe_subscription(
    user_id: int,
    *,
    subscription_id: Optional[str],
    tier: str,
) -> None:
    """Met à jour la subscription active + tier. Appelé depuis le webhook
    subscription.created/updated/deleted.

    Si subscription_id est None + tier='free' : la sub a été cancellée,
    le user retombe sur le plan gratuit.
    """
    if tier not in VALID_TIERS:
        raise ValueError(f"tier invalide : {tier!r}")
    with _conn() as c:
        c.execute(
            "UPDATE users SET stripe_subscription_id = ?, tier = ? WHERE id = ?",
            (subscription_id, tier, user_id),
        )


def get_user_by_stripe_customer_id(customer_id: str) -> Optional[dict]:
    """Résolution utilisée par le webhook pour retrouver le user par son id Stripe."""
    if not customer_id:
        return None
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM users WHERE stripe_customer_id = ?", (customer_id,)
        ).fetchone()
        return dict(row) if row else None


def is_onboarding_complete(user_id: int) -> dict:
    """Retourne l'état d'onboarding du user pour le front.

    - `has_broker` : broker_config contient bridge_url ET bridge_api_key
    - `has_pairs`  : watched_pairs non vide
    - `needs_onboarding` : at least one step missing
    """
    broker = get_broker_config(user_id)
    has_broker = bool(broker.get("bridge_url") and broker.get("bridge_api_key"))
    pairs = get_watched_pairs(user_id)
    has_pairs = len(pairs) > 0

    return {
        "has_broker": has_broker,
        "has_pairs": has_pairs,
        "needs_onboarding": not (has_broker and has_pairs),
    }
