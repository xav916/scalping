"""Programme parrainage v1 — tracking simple, commission manuelle.

V1 minimaliste :
- Chaque user authentifié peut générer un code unique (ex 'XAV-A7B3')
- Lien partageable : https://scalping-radar.online/v2/?ref=XAV-A7B3
- Au signup, le code est stocké côté visiteur (localStorage 30j) puis
  envoyé au backend qui enregistre le parrainage
- Quand le filleul devient payant Pro/Premium, on crédite le parrain
  (commission 20% sur 6 premiers mois, à payer manuellement par admin
  pour V1 — Stripe coupons en V2)

Tables :
- referral_codes : user_id (PK), code (unique), created_at
- referral_signups : id, code, referred_user_id (FK users), signed_up_at,
  converted_at, commission_eur, paid_at
"""
from __future__ import annotations

import logging
import secrets
import sqlite3
import string
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path("/app/data/trades.db") if Path("/app").exists() else Path("trades.db")

CODE_PREFIX_LEN = 3  # 3 letters from email or "REF" fallback
CODE_SUFFIX_LEN = 4  # 4 random alphanumerics


def init_referrals_schema() -> None:
    """Crée tables referral_codes + referral_signups. Idempotent."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS referral_codes (
                user_id INTEGER PRIMARY KEY,
                code TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_ref_codes_code ON referral_codes(code)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS referral_signups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                referred_user_id INTEGER,
                referred_email TEXT,
                signed_up_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                converted_at TIMESTAMP,
                commission_eur REAL DEFAULT 0,
                paid_at TIMESTAMP,
                UNIQUE (referred_user_id)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_ref_signups_code ON referral_signups(code)")


def _generate_unique_code(email_prefix: str) -> str:
    """Génère un code unique format ABC-X7K9 (3 letters from email + 4 random)."""
    init_referrals_schema()
    prefix = (email_prefix or "REF").upper()[:CODE_PREFIX_LEN].ljust(CODE_PREFIX_LEN, "X")
    # Strip non-alphanumeric
    prefix = "".join(c for c in prefix if c.isalnum())
    if len(prefix) < CODE_PREFIX_LEN:
        prefix = (prefix + "REF")[:CODE_PREFIX_LEN]

    alphabet = string.ascii_uppercase + string.digits
    for _ in range(20):
        suffix = "".join(secrets.choice(alphabet) for _ in range(CODE_SUFFIX_LEN))
        code = f"{prefix}-{suffix}"
        with sqlite3.connect(DB_PATH) as c:
            existing = c.execute("SELECT 1 FROM referral_codes WHERE code = ?", (code,)).fetchone()
            if not existing:
                return code
    raise RuntimeError("Failed to generate unique code after 20 attempts")


def get_or_create_code(user_id: int, email: str) -> str:
    """Retourne le code de parrainage du user (créé si absent). Idempotent."""
    init_referrals_schema()
    with sqlite3.connect(DB_PATH) as c:
        row = c.execute("SELECT code FROM referral_codes WHERE user_id = ?", (user_id,)).fetchone()
        if row:
            return row[0]

    # Générer un nouveau code basé sur l'email
    email_prefix = email.split("@")[0] if email and "@" in email else "REF"
    code = _generate_unique_code(email_prefix)
    with sqlite3.connect(DB_PATH) as c:
        c.execute(
            "INSERT INTO referral_codes (user_id, code) VALUES (?, ?)",
            (user_id, code),
        )
    logger.info(f"new referral code for user {user_id}: {code}")
    return code


def validate_code(code: str) -> dict:
    """Vérifie qu'un code existe. Retourne {valid, owner_email_prefix, n_signups}.

    Tolérant à l'absence de la table users (cas tests isolés).
    """
    init_referrals_schema()
    code = (code or "").strip().upper()
    if not code:
        return {"valid": False}
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT user_id, code FROM referral_codes WHERE code = ?",
            (code,),
        ).fetchone()
        if not row:
            return {"valid": False}
        # Tente de fetch l'email du parrain (peut échouer si table users absente)
        email = ""
        try:
            user_row = c.execute(
                "SELECT email FROM users WHERE id = ?", (row["user_id"],)
            ).fetchone()
            if user_row:
                email = user_row["email"] or ""
        except sqlite3.OperationalError:
            email = ""
        n = c.execute("SELECT COUNT(*) FROM referral_signups WHERE code = ?", (code,)).fetchone()[0]
    return {
        "valid": True,
        "owner_email_initials": (email[:1] + "***" + email.split("@")[0][-1:]) if email else "***",
        "n_signups": n,
    }


def track_signup(code: str, referred_user_id: int, referred_email: str) -> bool:
    """Enregistre un nouveau signup parrainé. Idempotent par referred_user_id."""
    init_referrals_schema()
    code = (code or "").strip().upper()
    if not code:
        return False
    # Check code valide
    with sqlite3.connect(DB_PATH) as c:
        if not c.execute("SELECT 1 FROM referral_codes WHERE code = ?", (code,)).fetchone():
            return False

    try:
        with sqlite3.connect(DB_PATH) as c:
            c.execute(
                """
                INSERT INTO referral_signups (code, referred_user_id, referred_email)
                VALUES (?, ?, ?)
                """,
                (code, referred_user_id, referred_email),
            )
        logger.info(f"referral signup tracked: code={code} → user={referred_user_id}")
        return True
    except sqlite3.IntegrityError:
        # Already tracked
        return True


def on_conversion(referred_user_id: int, paid_amount_eur: float) -> None:
    """Crédite le parrain (20% sur 6 premiers mois). Manuel par admin pour V1."""
    init_referrals_schema()
    commission = round(paid_amount_eur * 0.20, 2)
    with sqlite3.connect(DB_PATH) as c:
        c.execute(
            """
            UPDATE referral_signups
               SET converted_at = CURRENT_TIMESTAMP,
                   commission_eur = commission_eur + ?
             WHERE referred_user_id = ?
            """,
            (commission, referred_user_id),
        )
        logger.info(f"referral conversion: user {referred_user_id} → commission +{commission}€")


def get_my_stats(user_id: int) -> dict:
    """Stats parrainage du user : code, signups, commissions earned/paid."""
    init_referrals_schema()
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        code_row = c.execute("SELECT code FROM referral_codes WHERE user_id = ?", (user_id,)).fetchone()
        if not code_row:
            return {"code": None, "n_signups": 0, "n_converted": 0,
                    "commission_total_eur": 0.0, "commission_paid_eur": 0.0,
                    "commission_pending_eur": 0.0}
        code = code_row["code"]
        signups = c.execute("""
            SELECT
                COUNT(*) as n,
                SUM(CASE WHEN converted_at IS NOT NULL THEN 1 ELSE 0 END) as n_conv,
                COALESCE(SUM(commission_eur), 0) as total_eur,
                COALESCE(SUM(CASE WHEN paid_at IS NOT NULL THEN commission_eur ELSE 0 END), 0) as paid_eur
            FROM referral_signups WHERE code = ?
        """, (code,)).fetchone()
    return {
        "code": code,
        "n_signups": signups["n"] or 0,
        "n_converted": signups["n_conv"] or 0,
        "commission_total_eur": float(signups["total_eur"] or 0),
        "commission_paid_eur": float(signups["paid_eur"] or 0),
        "commission_pending_eur": float((signups["total_eur"] or 0) - (signups["paid_eur"] or 0)),
    }
