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
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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

# Lookback max analytics (days) par tier. Free est limité à 7 jours glissants
# pour encourager l'upgrade ; Pro/Premium ont accès illimité (None = no cap).
TIER_MAX_LOOKBACK_DAYS = {"free": 7, "pro": None, "premium": None}

# Trial Pro gratuit à l'inscription (Chantier 9 SaaS).
SIGNUP_TRIAL_DAYS = 14
SIGNUP_TRIAL_TIER = "pro"

# Version courante des documents légaux acceptés à l'inscription (CGU, CGV,
# Privacy). À incrémenter chaque fois qu'un de ces documents change : les
# users existants devront ré-accepter (UI non implémentée ici, v1 suffit
# pour le lancement public).
TERMS_CURRENT_VERSION = "1.0"


def new_trial_end_iso() -> str:
    """Retourne l'ISO UTC du trial_ends_at pour un signup maintenant."""
    return (datetime.now(timezone.utc) + timedelta(days=SIGNUP_TRIAL_DAYS)).isoformat()


def tier_rank(tier: str) -> int:
    return TIER_RANK.get(tier, 0)


def has_min_tier(user_tier: str, min_tier: str) -> bool:
    """True si user_tier >= min_tier. Défaut 'free' pour les unknowns."""
    return tier_rank(user_tier) >= tier_rank(min_tier)


def effective_tier(user: Optional[dict]) -> str:
    """Retourne le tier réellement applicable pour le gating.

    - Paying sub active (stripe_subscription_id set) → tier stocké (source de
      vérité : Stripe dicte).
    - Pas de sub, trial encore actif (trial_ends_at > now) → tier stocké.
    - Pas de sub, trial expiré → 'free' (downgrade silencieux sans muter la DB).
    - Tier 'free' → toujours 'free'.
    """
    if not user:
        return "free"
    stored = user.get("tier", "free")
    if stored == "free":
        return "free"
    # Paying subscription active → tier stocké.
    if user.get("stripe_subscription_id"):
        return stored
    # Pas de sub payante : trial éventuellement actif.
    trial_end = user.get("trial_ends_at")
    if trial_end:
        try:
            end_dt = datetime.fromisoformat(trial_end.replace("Z", "+00:00"))
            if end_dt > datetime.now(timezone.utc):
                return stored
        except (ValueError, AttributeError):
            pass
    # Trial absent ou expiré, pas de sub → effectivement free.
    return "free"


def trial_status(user: Optional[dict]) -> dict:
    """Retourne {trial_active: bool, trial_ends_at: str|None, trial_days_left: int|None}.

    `trial_active` = True seulement si trial_ends_at > now ET pas de sub payante
    (un user qui a upgradé pendant le trial a trial_active=False).
    """
    if not user:
        return {"trial_active": False, "trial_ends_at": None, "trial_days_left": None}
    trial_end = user.get("trial_ends_at")
    if not trial_end or user.get("stripe_subscription_id"):
        return {"trial_active": False, "trial_ends_at": trial_end, "trial_days_left": None}
    try:
        end_dt = datetime.fromisoformat(trial_end.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return {"trial_active": False, "trial_ends_at": trial_end, "trial_days_left": None}
    now = datetime.now(timezone.utc)
    if end_dt <= now:
        return {"trial_active": False, "trial_ends_at": trial_end, "trial_days_left": 0}
    days_left = max(0, (end_dt - now).days)
    return {"trial_active": True, "trial_ends_at": trial_end, "trial_days_left": days_left}


def max_lookback_days(user_tier: str) -> Optional[int]:
    """Nombre max de jours d'historique consultable sur les endpoints
    insights/analytics. None = illimité."""
    return TIER_MAX_LOOKBACK_DAYS.get(user_tier, 7)


def clamp_since_iso(since_iso: Optional[str], user_tier: str) -> Optional[str]:
    """Si le tier a un cap, ramène `since_iso` à max(since_iso, today - cap).
    None reste None.
    """
    cap = max_lookback_days(user_tier)
    if cap is None:
        return since_iso
    floor = (datetime.now(timezone.utc) - timedelta(days=cap)).isoformat()
    if since_iso is None:
        return floor
    return max(since_iso, floor)


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

        # Migration douce Chantier 5.1 : cycle de facturation Stripe.
        # Vaut 'monthly' | 'yearly' | NULL (users gratuits / legacy).
        user_cols = [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
        if "stripe_billing_cycle" not in user_cols:
            c.execute("ALTER TABLE users ADD COLUMN stripe_billing_cycle TEXT")
        # Chantier 11 : tracker des rappels trial envoyés (JSON list ['3d', '1d']).
        if "trial_reminders_sent" not in user_cols:
            c.execute("ALTER TABLE users ADD COLUMN trial_reminders_sent TEXT")
        # Password reset flow (lien magic link via email).
        if "password_reset_token" not in user_cols:
            c.execute("ALTER TABLE users ADD COLUMN password_reset_token TEXT")
        if "password_reset_expires_at" not in user_cols:
            c.execute("ALTER TABLE users ADD COLUMN password_reset_expires_at TEXT")
        # Email verification (double opt-in signup, anti-bot).
        if "email_verified_at" not in user_cols:
            c.execute("ALTER TABLE users ADD COLUMN email_verified_at TEXT")
        if "email_verification_token" not in user_cols:
            c.execute("ALTER TABLE users ADD COLUMN email_verification_token TEXT")
        # Consentement CGU/CGV/Privacy à l'inscription (obligation UE).
        # `terms_accepted_at` = timestamp ISO du clic sur "J'accepte".
        # `terms_version` = version courante (TERMS_CURRENT_VERSION) au moment
        #   du clic — preuve de ce qui a été accepté en cas de litige.
        if "terms_accepted_at" not in user_cols:
            c.execute("ALTER TABLE users ADD COLUMN terms_accepted_at TEXT")
        if "terms_version" not in user_cols:
            c.execute("ALTER TABLE users ADD COLUMN terms_version TEXT")

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
    terms_version: Optional[str] = None,
) -> int:
    """Crée un user et retourne son id. Lève ValueError si email déjà pris
    ou tier invalide.

    Si `terms_version` est fourni, stocke aussi `terms_accepted_at=now` —
    preuve de consentement CGU/CGV/Privacy (obligatoire pour les signups
    publics UE). Laisser à None pour les users créés par script admin
    (seed, migration) qui ne passent pas par la checkbox front.
    """
    email_norm = _normalize_email(email)
    if not email_norm or "@" not in email_norm:
        raise ValueError("email invalide")
    if tier not in VALID_TIERS:
        raise ValueError(f"tier invalide : {tier!r} (attendu {VALID_TIERS})")

    pw_hash = hash_password(password)
    now = datetime.now(timezone.utc).isoformat()
    terms_accepted_at = now if terms_version else None

    with _conn() as c:
        try:
            cur = c.execute(
                """
                INSERT INTO users (
                    email, password_hash, tier, trial_ends_at, created_at,
                    terms_accepted_at, terms_version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email_norm, pw_hash, tier, trial_ends_at, now,
                    terms_accepted_at, terms_version,
                ),
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


# ─── Password reset (magic link email) ───────────────────────

PASSWORD_RESET_TTL_HOURS = 1


def request_password_reset(email: str) -> Optional[str]:
    """Génère un token de reset pour l'email. Retourne le token si le user
    existe et est actif, None sinon (anti-énumération côté caller : le caller
    doit répondre 200 dans TOUS les cas, mais n'envoie l'email que si token).
    """
    user = get_user_by_email(email)
    if not user or not user.get("is_active", 1):
        return None
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=PASSWORD_RESET_TTL_HOURS)).isoformat()
    with _conn() as c:
        c.execute(
            "UPDATE users SET password_reset_token = ?, password_reset_expires_at = ? WHERE id = ?",
            (token, expires, user["id"]),
        )
    return token


def validate_reset_token(token: str) -> Optional[dict]:
    """Retourne le user si le token est valide (existe + non expiré), sinon None."""
    if not token:
        return None
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM users WHERE password_reset_token = ?", (token,)
        ).fetchone()
    if not row:
        return None
    user = dict(row)
    expires_at = user.get("password_reset_expires_at")
    if not expires_at:
        return None
    try:
        exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if exp <= datetime.now(timezone.utc):
        return None
    return user


# ─── Email verification (double opt-in signup) ───────────────

def generate_email_verification_token(user_id: int) -> str:
    """Génère + persiste un token de vérification email. Remplace tout token
    précédent (un seul actif à la fois). Pas d'expiry côté DB : le lien est
    actif jusqu'à utilisation (ou re-génération).
    """
    token = secrets.token_urlsafe(32)
    with _conn() as c:
        c.execute(
            "UPDATE users SET email_verification_token = ? WHERE id = ?",
            (token, user_id),
        )
    return token


def verify_email_token(token: str) -> Optional[int]:
    """Valide un token de vérification. Retourne user_id en cas de succès
    (et marque email_verified_at), None sinon.
    """
    if not token:
        return None
    with _conn() as c:
        row = c.execute(
            "SELECT id FROM users WHERE email_verification_token = ?", (token,)
        ).fetchone()
        if not row:
            return None
        user_id = int(row[0])
        now = datetime.now(timezone.utc).isoformat()
        c.execute(
            "UPDATE users SET email_verified_at = ?, email_verification_token = NULL "
            "WHERE id = ?",
            (now, user_id),
        )
    return user_id


def is_email_verified(user: Optional[dict]) -> bool:
    """True si l'user a vérifié son email OU si l'user est legacy env (None)."""
    if not user:
        return False
    return bool(user.get("email_verified_at"))


def change_password(user_id: int, current_password: str, new_password: str) -> bool:
    """Change le password après vérif de l'ancien. Lève ValueError si invalide.
    Retourne True en cas de succès, False si current_password incorrect.
    """
    if not new_password or len(new_password) < 8:
        raise ValueError("new_password trop court (min 8 caractères)")
    user = get_user_by_id(user_id)
    if not user:
        return False
    if not verify_password(current_password, user["password_hash"]):
        return False
    with _conn() as c:
        c.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(new_password), user_id),
        )
    return True


def delete_account(user_id: int, current_password: str) -> bool:
    """Anonymise le compte user (RGPD droit à l'effacement).

    - Anonymise email en `deleted_{id}@anon.local`
    - Remplace password_hash par un hash random non-réversible
    - is_active=0 (empêche login)
    - Clear tous les tokens (reset, verification)
    - Nullifie broker_config / watched_pairs / stripe_*
    - Conserve l'enregistrement (vs DELETE) pour intégrité référentielle
      des trades historiques (user_id reste valide pour archive comptable).

    Retourne False si current_password incorrect.
    """
    user = get_user_by_id(user_id)
    if not user:
        return False
    if not verify_password(current_password, user["password_hash"]):
        return False
    anon_email = f"deleted_{user_id}@anon.local"
    random_hash = hash_password(secrets.token_urlsafe(32))
    with _conn() as c:
        c.execute(
            "UPDATE users SET email = ?, password_hash = ?, is_active = 0, "
            "broker_config = NULL, watched_pairs = NULL, "
            "stripe_customer_id = NULL, stripe_subscription_id = NULL, "
            "stripe_billing_cycle = NULL, trial_ends_at = NULL, "
            "trial_reminders_sent = NULL, password_reset_token = NULL, "
            "password_reset_expires_at = NULL, email_verification_token = NULL "
            "WHERE id = ?",
            (anon_email, random_hash, user_id),
        )
    return True


def has_trades(user_id: int) -> bool:
    """True si le user a au moins un trade lié (personal_trades.user_id=?).

    Utilisé par l'admin delete pour décider entre hard delete (aucun trade,
    user de test) et soft delete/anonymisation (trades historiques à
    préserver pour l'archive comptable).
    """
    with _conn() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(personal_trades)").fetchall()]
        if "user_id" not in cols:
            return False
        row = c.execute(
            "SELECT 1 FROM personal_trades WHERE user_id = ? LIMIT 1",
            (user_id,),
        ).fetchone()
    return row is not None


def admin_hard_delete_user(user_id: int) -> bool:
    """Suppression définitive d'un user par un admin (backoffice).

    Usage réservé aux cleanup de users de test. Pour un user "réel" qui
    demande la suppression RGPD, préférer `delete_account` (soft delete /
    anonymisation) qui préserve l'intégrité des trades historiques.

    Retourne True si un row a été supprimé.
    """
    with _conn() as c:
        cur = c.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return cur.rowcount > 0


def mark_email_auto_verified(user_id: int) -> None:
    """Pour les envs où SMTP n'est pas configuré : on considère l'email
    verified automatiquement (sinon les users seraient coincés sans pouvoir
    recevoir de mail). À appeler au signup si is_configured() == False.
    """
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "UPDATE users SET email_verified_at = ?, email_verification_token = NULL "
            "WHERE id = ?",
            (now, user_id),
        )


def consume_reset_token(token: str, new_password: str) -> bool:
    """Valide le token, hash+persiste le nouveau password, invalide le token.
    Retourne True en cas de succès.
    """
    if not new_password or len(new_password) < 8:
        raise ValueError("password trop court (min 8 caractères)")
    user = validate_reset_token(token)
    if not user:
        return False
    new_hash = hash_password(new_password)
    with _conn() as c:
        c.execute(
            "UPDATE users SET password_hash = ?, password_reset_token = NULL, "
            "password_reset_expires_at = NULL WHERE id = ?",
            (new_hash, user["id"]),
        )
    return True


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

    # Préserver auto_exec_enabled existant (Phase D — sinon un PUT broker_config
    # ré-écraserait le toggle silencieusement et désactiverait l'auto-exec sans
    # action explicite du user).
    existing = get_broker_config(user_id)
    payload = {
        "bridge_url": bridge_url.rstrip("/"),
        "bridge_api_key": bridge_api_key,
    }
    if broker_name:
        payload["broker_name"] = broker_name
    if "auto_exec_enabled" in existing:
        payload["auto_exec_enabled"] = existing["auto_exec_enabled"]

    with _conn() as c:
        c.execute(
            "UPDATE users SET broker_config = ? WHERE id = ?",
            (json.dumps(payload), user_id),
        )


def update_auto_exec_enabled(user_id: int, enabled: bool) -> None:
    """Toggle ``auto_exec_enabled`` dans ``broker_config`` sans toucher au reste.

    Préserve les autres champs (``bridge_url``, ``bridge_api_key``,
    ``broker_name``). Si ``broker_config`` est vide, crée un dict minimal
    avec juste ce champ — l'user devra compléter via le wizard pour que
    le toggle ait un effet (cf. ``list_premium_auto_exec_users``).
    """
    cfg = get_broker_config(user_id)
    cfg["auto_exec_enabled"] = bool(enabled)
    with _conn() as c:
        c.execute(
            "UPDATE users SET broker_config = ? WHERE id = ?",
            (json.dumps(cfg), user_id),
        )


def find_user_by_bridge_api_key(api_key: str) -> Optional[dict]:
    """Cherche un user dont ``broker_config.bridge_api_key == api_key``.

    Utilisé par les endpoints EA (Phase MQL.B) pour résoudre le user à
    partir du api_key envoyé en query param. Full table scan + JSON
    parse — acceptable pour V1 avec ≤ 10 users Premium. À indexer en V2
    si volume.

    Returns
    -------
    dict | None
        Le user complet (cf. ``get_user_by_id``) ou ``None`` si pas trouvé.
    """
    if not api_key or len(api_key) < 16:
        return None
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM users WHERE tier = 'premium' AND broker_config IS NOT NULL"
        ).fetchall()
    for row in rows:
        try:
            cfg = json.loads(row["broker_config"])
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(cfg, dict) and cfg.get("bridge_api_key") == api_key:
            return dict(row)
    return None


def update_ea_heartbeat(user_id: int) -> None:
    """Met à jour ``broker_config.last_ea_heartbeat`` au timestamp now.

    Permet à l'admin de voir quels users ont leur EA actif (dernier poll).
    Si pas de heartbeat depuis > 1h, considérer l'EA offline.
    """
    cfg = get_broker_config(user_id)
    cfg["last_ea_heartbeat"] = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "UPDATE users SET broker_config = ? WHERE id = ?",
            (json.dumps(cfg), user_id),
        )


def list_premium_auto_exec_users() -> list[dict]:
    """Retourne les users éligibles pour l'auto-exec multi-tenant.

    Filtres (cumulatifs) :
    - ``tier='premium'`` (effective tier, pas le stored — un user 'premium' avec
      sub Stripe expirée tombe en 'free' et doit être exclu)
    - ``broker_config`` JSON parse-able
    - ``auto_exec_enabled=True``
    - ``bridge_url`` non vide ET contient ``://``
    - ``bridge_api_key`` non vide ET ≥ 16 chars
    - ``watched_pairs`` JSON parse-able (liste de strings)

    Returns
    -------
    list[dict]
        Chaque dict contient ``id``, ``email``, ``broker_config`` (parsed),
        ``watched_pairs`` (list[str]). L'appelant filtre ensuite par
        ``setup.pair in watched_pairs`` au moment de pousser un setup
        spécifique.
    """
    with _conn() as c:
        rows = c.execute(
            """
            SELECT id, email, tier, stripe_subscription_id, trial_ends_at,
                   broker_config, watched_pairs
              FROM users
             WHERE tier = 'premium' AND broker_config IS NOT NULL
            """
        ).fetchall()

    result = []
    for row in rows:
        user_dict = dict(row)
        if effective_tier(user_dict) != "premium":
            continue  # downgrade silencieux (trial expiré)
        try:
            cfg = json.loads(user_dict["broker_config"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(cfg, dict):
            continue
        if not cfg.get("auto_exec_enabled"):
            continue
        url = (cfg.get("bridge_url") or "").strip()
        key = (cfg.get("bridge_api_key") or "").strip()
        if not url or "://" not in url or len(key) < 16:
            continue
        try:
            pairs = json.loads(user_dict["watched_pairs"]) if user_dict["watched_pairs"] else []
        except (json.JSONDecodeError, TypeError):
            pairs = []
        if not isinstance(pairs, list):
            pairs = []
        result.append(
            {
                "id": user_dict["id"],
                "email": user_dict["email"],
                "broker_config": cfg,
                "watched_pairs": pairs,
            }
        )
    return result


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

# Paires pré-sélectionnées au signup pour que l'user voit immédiatement le
# radar tourner (zéro friction onboarding). Ordonnées par popularité / volume.
# Limitées par MAX_PAIRS_PER_TIER à l'application.
DEFAULT_PAIRS_ORDERED = [
    "EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD", "BTC/USD",
    "EUR/JPY", "AUD/USD", "USD/CAD", "GBP/JPY", "XAG/USD",
    "ETH/USD", "SPX", "NDX", "WTI/USD", "USD/CHF", "EUR/GBP",
]


def default_pairs_for_tier(tier: str) -> list[str]:
    """Retourne la liste par défaut des paires pour un tier, cap respecté."""
    cap = MAX_PAIRS_PER_TIER.get(tier, 1)
    return DEFAULT_PAIRS_ORDERED[:cap]


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
    billing_cycle: Optional[str] = None,
) -> None:
    """Met à jour la subscription active + tier + cycle de facturation.
    Appelé depuis le webhook subscription.created/updated/deleted.

    Si subscription_id est None + tier='free' : la sub a été cancellée,
    le user retombe sur le plan gratuit (cycle reset à NULL).
    `billing_cycle` ∈ {monthly, yearly, None}.
    """
    if tier not in VALID_TIERS:
        raise ValueError(f"tier invalide : {tier!r}")
    if billing_cycle is not None and billing_cycle not in ("monthly", "yearly"):
        raise ValueError(f"billing_cycle invalide : {billing_cycle!r}")
    # Reset du cycle quand on downgrade en free.
    if tier == "free":
        billing_cycle = None
    with _conn() as c:
        c.execute(
            "UPDATE users SET stripe_subscription_id = ?, tier = ?, "
            "stripe_billing_cycle = ? WHERE id = ?",
            (subscription_id, tier, billing_cycle, user_id),
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


def get_trial_reminders_sent(user: dict) -> list[str]:
    raw = user.get("trial_reminders_sent") if user else None
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def mark_trial_reminder_sent(user_id: int, key: str) -> None:
    """Ajoute `key` ('3d', '1d') à la liste des rappels envoyés pour ce user.
    Idempotent : ne re-ajoute pas si déjà présent.
    """
    user = get_user_by_id(user_id)
    if not user:
        return
    existing = get_trial_reminders_sent(user)
    if key in existing:
        return
    existing.append(key)
    with _conn() as c:
        c.execute(
            "UPDATE users SET trial_reminders_sent = ? WHERE id = ?",
            (json.dumps(existing), user_id),
        )


def list_all_users() -> list[dict]:
    """Retourne tous les users (pour admin backoffice), ordonnés par
    created_at DESC. Exclut password_hash pour éviter les fuites accidentelles.
    """
    with _conn() as c:
        rows = c.execute(
            "SELECT id, email, tier, stripe_customer_id, stripe_subscription_id, "
            "stripe_billing_cycle, trial_ends_at, created_at, last_login_at, "
            "is_active, trial_reminders_sent "
            "FROM users ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def list_users_with_active_trial() -> list[dict]:
    """Retourne tous les users avec un trial toujours actif (pas expiré, pas
    de sub payante). Utilisé par le job quotidien de rappels.
    """
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM users WHERE is_active = 1 "
            "AND trial_ends_at IS NOT NULL "
            "AND stripe_subscription_id IS NULL"
        ).fetchall()
    now = datetime.now(timezone.utc)
    result = []
    for row in rows:
        d = dict(row)
        try:
            end = datetime.fromisoformat(d["trial_ends_at"].replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        if end > now:
            result.append(d)
    return result


def is_onboarding_complete(user_id: int) -> dict:
    """Retourne l'état d'onboarding du user pour le front.

    Modèle signal-only (2026-04-23 pivot) : le bridge MT5 devient une option
    Premium optionnelle, seule la sélection des pairs est requise pour
    utiliser le produit (dashboard + alertes + analytics).

    - `has_pairs`  : watched_pairs non vide (seul critère bloquant)
    - `has_broker` : broker_config contient bridge_url ET bridge_api_key
                     (optionnel, info only)
    - `needs_onboarding` : `not has_pairs`
    """
    broker = get_broker_config(user_id)
    has_broker = bool(broker.get("bridge_url") and broker.get("bridge_api_key"))
    pairs = get_watched_pairs(user_id)
    has_pairs = len(pairs) > 0

    return {
        "has_broker": has_broker,
        "has_pairs": has_pairs,
        "needs_onboarding": not has_pairs,
    }
