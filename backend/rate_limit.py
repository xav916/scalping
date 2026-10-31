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
    """La clé de limitation : `X-Real-IP`, puis l'IP du socket. JAMAIS XFF.

    ## Le défaut corrigé (audit S-2, ÉLEVÉ)

    Cette fonction prenait le **premier saut** de `X-Forwarded-For` :

        xff.split(",")[0].strip()

    Or nginx transmet `X-Forwarded-For $proxy_add_x_forwarded_for`, directive
    qui **AJOUTE** l'IP réelle à la valeur fournie par le client. Un client
    envoyant `X-Forwarded-For: 1.2.3.4` produisait donc
    `1.2.3.4, <ip_reelle>`, et l'application retenait `1.2.3.4` — **une
    valeur entièrement choisie par l'attaquant**.

    ⇒ Le rate limiting était contournable à volonté sur `login`, `signup`,
    `password-reset`, `email-verify`, `stripe-checkout` et `delete-account` :
    il suffisait de changer un en-tête à chaque requête. **La protection
    anti-force-brute des comptes était nulle en pratique.**

    ## Pourquoi `X-Real-IP` est digne de confiance ICI

    🔑 Deux conditions, et il faut les DEUX :

    1. nginx pose `proxy_set_header X-Real-IP $remote_addr` — il **écrase**
       ce que le client a envoyé, là où `$proxy_add_x_forwarded_for`
       **concatène** (vérifié : 6 emplacements dans `deploy/nginx.conf` et
       `deploy/nginx-app-scalping-online.conf`) ;
    2. l'application n'est pas joignable directement : systemd la publie sur
       `127.0.0.1:8000`, donc tout trafic passe par nginx.

    ⚠️ **Si l'une des deux tombe, ce correctif est nul** : exposer le port
    8000, ou retirer la directive, rend `X-Real-IP` aussi forgeable que XFF
    l'était. Ce n'est pas l'en-tête qui est sûr, c'est le chemin.

    ⛔ `X-Forwarded-For` n'est plus lu DU TOUT. Prendre son dernier élément
    marcherait aussi, mais ferait dépendre la sécurité du **nombre de
    proxys** — une valeur que personne ne vérifie et qui change en silence
    le jour où un CDN s'ajoute.
    """
    reel = (request.headers.get("x-real-ip") or "").strip()
    if reel:
        return reel
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
