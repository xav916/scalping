"""Rate limiting via slowapi — brute-force + spam protection.

Cible les endpoints sensibles : login, signup, password reset, email verif,
stripe checkout/portal, change-password, delete-account. Webhook Stripe
n'est pas limité (signature HMAC vérifie déjà l'origine).

Storage in-memory par défaut : OK pour 1 instance FastAPI. Si on scale
horizontalement, passer sur redis via `Limiter(storage_uri="redis://...")`.

Désactivable via `RATE_LIMIT_ENABLED=false` (utile en dev local / tests
fonctionnels qui spament les endpoints).
"""
from __future__ import annotations

import os

from fastapi import Request
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.responses import JSONResponse


def _get_client_ip(request: Request) -> str:
    """Extrait l'IP réelle du client, même derrière le reverse proxy nginx.

    Nginx pose `X-Forwarded-For: <client>, <proxy1>, ...` et on prend le
    premier hop (l'IP d'origine). Fallback sur `request.client.host`.
    """
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


_enabled_env = os.getenv("RATE_LIMIT_ENABLED", "true").strip().lower()
RATE_LIMIT_ENABLED = _enabled_env in ("1", "true", "yes", "on")

limiter = Limiter(
    key_func=_get_client_ip,
    enabled=RATE_LIMIT_ENABLED,
)


async def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """Handler 429 JSON-friendly avec Retry-After (secondes)."""
    retry_after = getattr(exc, "retry_after", None)
    try:
        retry_after_int = int(retry_after) if retry_after is not None else 60
    except (TypeError, ValueError):
        retry_after_int = 60
    response = JSONResponse(
        status_code=429,
        content={
            "detail": "Trop de requêtes, réessayez plus tard.",
            "retry_after_seconds": retry_after_int,
        },
    )
    response.headers["Retry-After"] = str(retry_after_int)
    return response
