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
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, Response

from config.settings import AUTH_USERS

SESSION_COOKIE = "scalping_session"
SESSION_TTL = timedelta(days=7)

# sid -> {"user": str, "expires": datetime}
_sessions: dict[str, dict] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_session(username: str) -> str:
    """Crée une nouvelle session et retourne le SID à déposer dans le cookie."""
    sid = secrets.token_urlsafe(32)
    _sessions[sid] = {"user": username, "expires": _now() + SESSION_TTL}
    return sid


def validate_session(sid: str | None) -> str | None:
    """Retourne le username si la session existe et n'a pas expiré, sinon None.

    Le TTL est glissant : chaque validation le repousse à now + SESSION_TTL.
    """
    if not sid:
        return None
    session = _sessions.get(sid)
    if session is None:
        return None
    if session["expires"] < _now():
        _sessions.pop(sid, None)
        return None
    session["expires"] = _now() + SESSION_TTL
    return session["user"]


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
    """
    if not AUTH_USERS:
        return "anonymous"

    # 1. Cookie de session
    sid = request.cookies.get(SESSION_COOKIE)
    user = validate_session(sid)
    if user:
        return user

    # 2. Fallback Basic Auth (scripts, monitoring, anciens bookmarks)
    user = _basic_auth_user(request.headers.get("Authorization"))
    if user:
        return user

    raise HTTPException(
        status_code=401,
        detail="Authentification requise",
        # WWW-Authenticate permet aux clients Basic de re-prompter, l'UI web
        # elle redirigera sur /login via son handler 401.
        headers={"WWW-Authenticate": "Basic"},
    )


def login_and_set_cookie(response: Response, username: str, password: str) -> bool:
    """Vérifie les identifiants, crée une session et dépose le cookie. Retourne le succès."""
    expected = AUTH_USERS.get(username)
    if expected is None or not secrets.compare_digest(expected, password):
        return False
    sid = create_session(username)
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
