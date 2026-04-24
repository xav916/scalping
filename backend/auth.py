"""Session auth par cookie HttpOnly (remplace/complète Basic Auth).

Stratégie retenue — simple, sans dépendance externe :
- Sessions en mémoire (dict {sid -> {user, expires}}). OK pour un outil mono-instance.
  Un redémarrage du serveur = tout le monde doit se reconnecter — acceptable.
- SID = secrets.token_urlsafe(32) → 256 bits d'entropie.
- Cookie HttpOnly + Secure + SameSite=Strict + Path=/ → pas de lecture JS, pas d'envoi cross-site.
- TTL 7 jours, glissant (rechargé à chaque requête authentifiée).
- Basic Auth garde en fallback : les anciens bookmarks avec auth dans l'URL continuent
  de fonctionner, et les scripts (curl, monitoring) restent utilisables.

Si un jour on veut persister les sessions (Redis / SQLite), ce fichier est l'unique
point de changement.
"""

import base64
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, Response

from config.settings import AUTH_USERS

logger = logging.getLogger(__name__)

SESSION_COOKIE = "scalping_session"
SESSION_TTL = timedelta(days=7)

# sid -> {"user": str, "user_id": int | None, "expires": datetime}
# user_id vaut None pour les users AUTH_USERS env (legacy), sinon users.id.
_sessions: dict[str, dict] = {}


@dataclass(frozen=True)
class AuthContext:
    """Contexte d'auth exposé aux routes (Chantier 3 SaaS).

    - `username` : identifiant de session (email lowercase pour DB users,
      valeur brute pour users env legacy).
    - `user_id` : id numérique de la table users si le user existe en DB,
      None pour les users AUTH_USERS env (pas de colonne user_id sur leurs
      trades historiques).
    """

    username: str
    user_id: int | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_session(username: str, user_id: int | None = None) -> str:
    """Crée une nouvelle session et retourne le SID à déposer dans le cookie."""
    sid = secrets.token_urlsafe(32)
    _sessions[sid] = {
        "user": username,
        "user_id": user_id,
        "expires": _now() + SESSION_TTL,
    }
    return sid


def validate_session(sid: str | None) -> str | None:
    """Retourne le username si la session existe et n'a pas expiré, sinon None.

    Le TTL est glissant : chaque validation le repousse à now + SESSION_TTL.
    """
    session = _load_session(sid)
    return session["user"] if session else None


def _load_session(sid: str | None) -> dict | None:
    """Helper interne : charge + renouvelle TTL, renvoie le dict brut ou None."""
    if not sid:
        return None
    session = _sessions.get(sid)
    if session is None:
        return None
    if session["expires"] < _now():
        _sessions.pop(sid, None)
        return None
    session["expires"] = _now() + SESSION_TTL
    return session


def destroy_session(sid: str | None) -> None:
    if sid:
        _sessions.pop(sid, None)


def _basic_auth_user(authorization: str | None) -> str | None:
    """Décode un header Authorization: Basic xxx et vérifie les identifiants."""
    if not authorization or not authorization.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(authorization[6:]).decode("utf-8")
        username, _, password = decoded.partition(":")
    except Exception:
        return None
    expected = AUTH_USERS.get(username)
    if expected is None:
        return None
    if not secrets.compare_digest(expected, password):
        return None
    return username


def authenticate(request: Request) -> str:
    """Dépendance FastAPI : accepte une session cookie OU Basic Auth, sinon 401.

    Si AUTH_USERS est vide, tout le monde est "anonymous" (pas d'auth configurée).

    Back-compat : ne retourne que le username. Préférer `auth_context()` pour
    récupérer aussi le user_id (Chantier 3 data isolation).
    """
    ctx = auth_context(request)
    return ctx.username


def _resolve_user_id(username: str) -> int | None:
    """Lookup users.id pour un username. None si pas trouvé (users env legacy)."""
    try:
        from backend.services import users_service

        user = users_service.get_user_by_email(username)
        return int(user["id"]) if user else None
    except Exception:
        logger.exception("resolve_user_id a échoué pour %s", username)
        return None


def auth_context(request: Request) -> AuthContext:
    """Dépendance FastAPI : renvoie un AuthContext (username + user_id), sinon 401.

    Utiliser cette dep pour les routes qui doivent scoper leurs queries par
    user_id (Chantier 3 SaaS data isolation).
    """
    if not AUTH_USERS:
        return AuthContext(username="anonymous", user_id=None)

    # 1. Cookie de session : user_id déjà résolu au login, stocké dans le dict.
    sid = request.cookies.get(SESSION_COOKIE)
    session = _load_session(sid)
    if session:
        return AuthContext(username=session["user"], user_id=session.get("user_id"))

    # 2. Fallback Basic Auth : pas de session, on résout le user_id à la volée.
    user = _basic_auth_user(request.headers.get("Authorization"))
    if user:
        return AuthContext(username=user, user_id=_resolve_user_id(user))

    # Pas de header WWW-Authenticate : on veut que le navigateur NE déclenche
    # PAS sa popup Basic Auth native (UX catastrophique dans une SPA). Le
    # front React gère lui-même les 401 en redirigeant vers /v2/login.
    # Les scripts curl/monitoring peuvent envoyer un header Authorization
    # explicitement sans avoir besoin du challenge.
    raise HTTPException(
        status_code=401,
        detail="Authentification requise",
    )


def _authenticate_credentials(username: str, password: str) -> tuple[str, int | None] | None:
    """Vérifie login/password. Ordre : table users (SaaS) → AUTH_USERS env (fallback).

    Retourne (username_normalisé, user_id) sur succès, ou None sur échec.
    user_id vaut l'id de la table users pour les DB users, None pour env.
    """
    try:
        from backend.services import users_service

        user = users_service.get_user_by_email(username)
        if user and user.get("is_active", 1) and users_service.verify_password(
            password, user["password_hash"]
        ):
            try:
                users_service.touch_last_login(user["id"])
            except Exception:
                logger.exception("touch_last_login a échoué pour uid=%s", user["id"])
            return user["email"], int(user["id"])
    except Exception:
        logger.exception("Lookup users DB a échoué — fallback env")

    expected = AUTH_USERS.get(username)
    if expected is not None and secrets.compare_digest(expected, password):
        return username, None
    return None


def login_and_set_cookie(response: Response, username: str, password: str) -> bool:
    """Vérifie les identifiants, crée une session et dépose le cookie. Retourne le succès."""
    result = _authenticate_credentials(username, password)
    if result is None:
        return False
    auth_user, user_id = result
    sid = create_session(auth_user, user_id=user_id)
    # SameSite=Lax (et non Strict) : permet d'envoyer le cookie sur les
    # WebSocket upgrades initiés depuis la même origine. Chrome applique
    # Strict de manière suffisamment stricte pour bloquer le cookie sur
    # WS dans certains contextes (cross-site navigation puis same-origin
    # WS), donnant 403 côté backend. Lax reste sécure pour notre usage
    # (CSRF protection identique pour les GET navigations).
    response.set_cookie(
        key=SESSION_COOKIE,
        value=sid,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return True


def logout_and_clear_cookie(request: Request, response: Response) -> None:
    destroy_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
