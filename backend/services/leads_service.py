"""Service leads — capture email pour beta closed (avant ouverture 2026-06-07).

Stockage simple dans `trades.db` (même DB que users). Permet de notifier les
prospects à l'ouverture officielle du signup, et de mesurer le funnel beta.

Pas d'envoi mail confirmation pour l'instant (ajoutable via Resend si besoin).
"""
from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path("/app/data/trades.db") if Path("/app").exists() else Path("trades.db")

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def init_leads_schema() -> None:
    """Crée la table leads si absente. Idempotent."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                source TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                ip TEXT,
                user_agent TEXT,
                converted_user_id INTEGER,
                UNIQUE (email)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads(created_at DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_leads_source ON leads(source)")


def add_lead(
    email: str,
    source: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, str | bool]:
    """Inscrit un email à la liste beta. Retourne dict avec 'ok' bool + msg.

    - Valide format email
    - Idempotent : email déjà présent → returns ok=True (pas d'erreur exposée)
    - Source typique : 'landing', 'pricing', 'live', 'track-record'
    """
    email = (email or "").strip().lower()
    if not EMAIL_REGEX.match(email):
        return {"ok": False, "message": "Email invalide"}

    init_leads_schema()
    try:
        with sqlite3.connect(DB_PATH) as c:
            c.execute(
                "INSERT INTO leads (email, source, ip, user_agent) VALUES (?, ?, ?, ?)",
                (email, source, ip, user_agent),
            )
        logger.info(f"new lead: {email} (source={source})")
        return {"ok": True, "message": "Tu es sur la liste."}
    except sqlite3.IntegrityError:
        # Email déjà inscrit — on ne dit pas "déjà inscrit" pour éviter le
        # email-enum (savoir si une adresse est dans la base via le message).
        return {"ok": True, "message": "Tu es sur la liste."}
    except Exception as e:
        logger.error(f"add_lead failed: {e}")
        return {"ok": False, "message": "Erreur serveur"}


def count_leads() -> int:
    """Total leads inscrits (admin uniquement)."""
    init_leads_schema()
    with sqlite3.connect(DB_PATH) as c:
        return c.execute("SELECT COUNT(*) FROM leads").fetchone()[0]


def list_leads(limit: int = 100) -> list[dict]:
    """Liste les leads récents (admin uniquement)."""
    init_leads_schema()
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT * FROM leads ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
