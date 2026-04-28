"""FastAPI application for the Scalping Decision Tool."""

import asyncio
import hashlib
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from backend.auth import (
    SESSION_COOKIE,
    AuthContext,
    auth_context,
    authenticate,
    login_and_set_cookie,
    logout_and_clear_cookie,
)
from backend.rate_limit import limiter, rate_limit_exceeded_handler
from config.settings import (
    ADMIN_EMAILS,
    AUTH_USERS,
    SAAS_SIGNUP_ENABLED,
    STRIPE_ENABLED,
    display_name_for,
    email_in_whitelist,
)

from backend.services import (
    backtest_service,
    indicators,
    trade_log_service,
    twelvedata_ws,
    users_service,
)
from backend.services.notification_service import (
    get_signal_history,
    register_client,
    unregister_client,
)
from backend.services.scheduler import (
    get_all_pair_candles,
    get_candles_for_pair,
    get_h1_candles_for_pair,
    get_last_cycle_at,
    get_latest_overview,
    run_analysis_cycle,
    start_scheduler,
    stop_scheduler,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    logger.info("Starting Scalping Decision Tool...")
    # Chantier 1 SaaS : init table users + migration user_id. Idempotent.
    try:
        users_service.init_users_schema()
    except Exception:
        logger.exception("init_users_schema a échoué")
    # Run initial analysis
    asyncio.create_task(run_analysis_cycle())
    # Start periodic scheduler
    start_scheduler()
    # Start live-tick WebSocket (opt-in via TWELVEDATA_WS_ENABLED)
    twelvedata_ws.start()
    yield
    await twelvedata_ws.stop()
    stop_scheduler()
    logger.info("Scalping Decision Tool stopped.")


app = FastAPI(
    title="Scalping Radar",
    description="Scalping decision tool - market analysis and signal detection",
    version="1.0.0",
    lifespan=lifespan,
)

# ─── Rate limiting (brute-force + spam sur endpoints sensibles) ─────
# slowapi enregistre le limiter dans app.state ; chaque route à protéger
# ajoute `@limiter.limit("N/unit")` et `request: Request` dans sa signature.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


# ─── Authentification (session cookie prioritaire, Basic Auth en fallback) ───
# Implémentation dans backend/auth.py. Cette fonction reste un alias pour
# minimiser le bruit sur les routes existantes.
def verify_credentials(request: Request) -> str:
    return authenticate(request)


# ─── Routes de login/logout ─────────────────────────────────────────
@app.post("/api/login")
@limiter.limit("10/minute")
async def api_login(request: Request, payload: dict, response: Response):
    """Échange login/password contre un cookie de session HttpOnly."""
    username = (payload or {}).get("username", "")
    password = (payload or {}).get("password", "")
    if not login_and_set_cookie(response, username, password):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    return {"ok": True, "user": username, "display_name": display_name_for(username)}


@app.post("/api/logout")
async def api_logout(request: Request, response: Response):
    logout_and_clear_cookie(request, response)
    return {"ok": True}


# ─── SaaS : tier current user + feature gating dep (Chantier 5) ─────
@app.get("/api/user/tier")
async def api_user_tier(ctx: AuthContext = Depends(auth_context)):
    """Tier + état abonnement du user courant, pour la PricingPage/Settings.

    Expose `tier` (effectif, après trial expiry), `tier_stored` (brut en DB),
    `trial_active`, `trial_days_left` pour que le front puisse afficher les
    banners appropriés.
    """
    if ctx.user_id is None:
        return {
            "tier": "premium",
            "tier_stored": "premium",
            "stripe_customer_set": False,
            "billing_cycle": None,
            "trial_active": False,
            "trial_days_left": None,
            "trial_ends_at": None,
            "email_verified": True,
            "legacy_env": True,
        }
    user = users_service.get_user_by_id(ctx.user_id) or {}
    trial = users_service.trial_status(user)
    return {
        "tier": users_service.effective_tier(user),
        "tier_stored": user.get("tier", "free"),
        "stripe_customer_set": bool(user.get("stripe_customer_id")),
        "stripe_subscription_set": bool(user.get("stripe_subscription_id")),
        "billing_cycle": user.get("stripe_billing_cycle"),
        "trial_active": trial["trial_active"],
        "trial_days_left": trial["trial_days_left"],
        "trial_ends_at": trial["trial_ends_at"],
        "email_verified": users_service.is_email_verified(user),
        "legacy_env": False,
    }


def require_min_tier(min_tier: str):
    """Factory de dépendance FastAPI : 403 si le user courant a un tier
    inférieur à min_tier.

    Utilise le tier EFFECTIF (gère l'expiration du trial de 14j) ; users
    legacy env (user_id=None) sont traités comme premium (admin).
    """

    def _dep(ctx: AuthContext = Depends(auth_context)) -> AuthContext:
        if ctx.user_id is None:
            return ctx  # env legacy = accès total
        user = users_service.get_user_by_id(ctx.user_id)
        if not users_service.has_min_tier(users_service.effective_tier(user), min_tier):
            raise HTTPException(
                status_code=403,
                detail=f"Cette fonctionnalité nécessite le tier {min_tier} ou supérieur",
            )
        return ctx

    return _dep


def _tier_of(ctx: AuthContext) -> str:
    """Retourne le tier EFFECTIF du user (applique l'expiration du trial).

    'premium' pour les users legacy env.
    """
    if ctx.user_id is None:
        return "premium"
    user = users_service.get_user_by_id(ctx.user_id)
    return users_service.effective_tier(user)


def _is_admin(ctx: AuthContext) -> bool:
    """True si le user courant est dans la whitelist admin ou legacy env."""
    if ctx.user_id is None:
        # Users env legacy = admin historique, passent toutes les gates.
        return True
    return (ctx.username or "").lower() in ADMIN_EMAILS


def require_admin(ctx: AuthContext = Depends(auth_context)) -> AuthContext:
    """Dep FastAPI : 403 si le user courant n'est pas dans ADMIN_EMAILS."""
    if not _is_admin(ctx):
        raise HTTPException(status_code=403, detail="Accès admin requis")
    return ctx


# ─── SaaS : Stripe checkout / webhook / portal (Chantier 5) ─────────
@app.post("/api/stripe/checkout")
@limiter.limit("20/hour")
async def api_stripe_checkout(
    request: Request,
    payload: dict,
    ctx: AuthContext = Depends(auth_context),
):
    """Crée une Checkout Session Stripe pour upgrade.

    Body : {tier: 'pro'|'premium', billing_cycle?: 'monthly'|'yearly'}.
    billing_cycle default = 'monthly'.

    Nécessite email_verified=true (anti-fraude : on s'assure que l'user
    contrôle bien son email avant de lui facturer quoi que ce soit).
    """
    if not STRIPE_ENABLED:
        raise HTTPException(status_code=503, detail="Stripe désactivé")
    if ctx.user_id is None:
        raise HTTPException(status_code=400, detail="user legacy env, pas de checkout")
    user_for_verif = users_service.get_user_by_id(ctx.user_id)
    if not users_service.is_email_verified(user_for_verif):
        raise HTTPException(
            status_code=403,
            detail="Vérifie ton email avant d'accéder au paiement",
        )
    tier = (payload or {}).get("tier")
    if tier not in ("pro", "premium"):
        raise HTTPException(status_code=400, detail="tier invalide (pro|premium)")
    billing_cycle = (payload or {}).get("billing_cycle", "monthly")
    if billing_cycle not in ("monthly", "yearly"):
        raise HTTPException(
            status_code=400, detail="billing_cycle invalide (monthly|yearly)"
        )

    user = users_service.get_user_by_id(ctx.user_id) or {}
    from backend.services import stripe_service

    try:
        url = stripe_service.create_checkout_session(
            user_id=ctx.user_id,
            user_email=user.get("email", ""),
            tier=tier,
            billing_cycle=billing_cycle,
            existing_customer_id=user.get("stripe_customer_id"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Stripe checkout a échoué")
        raise HTTPException(status_code=502, detail=f"Stripe : {str(e)[:200]}")
    return {"url": url}


@app.post("/api/stripe/portal")
@limiter.limit("30/hour")
async def api_stripe_portal(request: Request, ctx: AuthContext = Depends(auth_context)):
    """URL Customer Portal Stripe (gestion sub, cartes, factures)."""
    if not STRIPE_ENABLED:
        raise HTTPException(status_code=503, detail="Stripe désactivé")
    if ctx.user_id is None:
        raise HTTPException(status_code=400, detail="user legacy env, pas de portal")
    user = users_service.get_user_by_id(ctx.user_id) or {}
    customer_id = user.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(status_code=400, detail="Pas de customer Stripe — checkout d'abord")
    from backend.services import stripe_service
    from config.settings import STRIPE_CANCEL_URL

    try:
        url = stripe_service.create_portal_session(customer_id, return_url=STRIPE_CANCEL_URL)
    except Exception as e:
        logger.exception("Stripe portal a échoué")
        raise HTTPException(status_code=502, detail=f"Stripe : {str(e)[:200]}")
    return {"url": url}


@app.post("/api/stripe/webhook")
async def api_stripe_webhook(request: Request):
    """Webhook Stripe pour subscription events. Signature vérifiée.

    Public (pas d'auth_context) — Stripe pousse depuis ses serveurs. La
    sécurité repose sur la signature HMAC (STRIPE_WEBHOOK_SECRET).
    """
    if not STRIPE_ENABLED:
        raise HTTPException(status_code=503, detail="Stripe désactivé")
    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature", "")
    from backend.services import stripe_service

    try:
        result = stripe_service.handle_webhook(payload, sig_header)
    except stripe_service.stripe.error.SignatureVerificationError:  # type: ignore[attr-defined]
        raise HTTPException(status_code=400, detail="Signature Stripe invalide")
    except Exception as e:
        logger.exception("Webhook Stripe a échoué")
        raise HTTPException(status_code=400, detail=str(e)[:200])
    return {"ok": True, **result}


# ─── SaaS Admin backoffice (Chantier 12) ────────────────────────────
@app.get("/api/admin/users")
async def api_admin_users(_ctx: AuthContext = Depends(require_admin)):
    """Liste de tous les users + KPIs résumés pour le dashboard /admin.

    KPIs calculés :
    - total_users, active_users (is_active=1)
    - signups_7d, signups_30d
    - trials_active, trials_j3_or_less
    - paying_users par tier
    - mrr_eur (revenu mensuel récurrent estimé, basé tier + cycle)

    Les MRR Yearly sont divisés par 12 pour le ramener à un équivalent mensuel.
    """
    from datetime import datetime, timedelta, timezone

    users = users_service.list_all_users()
    now = datetime.now(timezone.utc)
    d7 = now - timedelta(days=7)
    d30 = now - timedelta(days=30)

    def _parse(iso: str | None):
        if not iso:
            return None
        try:
            return datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None

    # Tarifs de référence (source = spec SaaS). Si yearly, /12 pour MRR equivalent.
    PRICING = {
        ("pro", "monthly"): 19.0,
        ("pro", "yearly"): 190.0 / 12,
        ("premium", "monthly"): 39.0,
        ("premium", "yearly"): 390.0 / 12,
    }

    signups_7d = 0
    signups_30d = 0
    trials_active = 0
    trials_j3_or_less = 0
    by_tier: dict[str, int] = {"free": 0, "pro": 0, "premium": 0}
    mrr = 0.0
    enriched: list[dict] = []

    for u in users:
        created = _parse(u.get("created_at"))
        if created:
            if created > d7:
                signups_7d += 1
            if created > d30:
                signups_30d += 1

        trial = users_service.trial_status(u)
        if trial["trial_active"]:
            trials_active += 1
            if (trial["trial_days_left"] or 0) <= 3:
                trials_j3_or_less += 1

        eff = users_service.effective_tier(u)
        by_tier[eff] = by_tier.get(eff, 0) + 1

        if u.get("stripe_subscription_id") and eff in ("pro", "premium"):
            cycle = u.get("stripe_billing_cycle") or "monthly"
            mrr += PRICING.get((eff, cycle), 0.0)

        enriched.append({
            "id": u["id"],
            "email": u["email"],
            "tier_stored": u.get("tier"),
            "tier_effective": eff,
            "billing_cycle": u.get("stripe_billing_cycle"),
            "trial_active": trial["trial_active"],
            "trial_days_left": trial["trial_days_left"],
            "trial_ends_at": trial["trial_ends_at"],
            "stripe_customer_set": bool(u.get("stripe_customer_id")),
            "stripe_subscription_set": bool(u.get("stripe_subscription_id")),
            "created_at": u.get("created_at"),
            "last_login_at": u.get("last_login_at"),
            "is_active": bool(u.get("is_active")),
        })

    return {
        "totals": {
            "total_users": len(users),
            "active_users": sum(1 for u in users if u.get("is_active")),
            "signups_7d": signups_7d,
            "signups_30d": signups_30d,
            "trials_active": trials_active,
            "trials_j3_or_less": trials_j3_or_less,
            "by_tier": by_tier,
            "mrr_eur": round(mrr, 2),
        },
        "users": enriched,
    }


@app.delete("/api/admin/users/{user_id}")
@limiter.limit("30/hour")
async def api_admin_delete_user(
    request: Request,
    user_id: int,
    ctx: AuthContext = Depends(require_admin),
):
    """Hard delete d'un user par un admin (backoffice cleanup).

    Réservé aux users de test. Pour un RGPD "right to be forgotten" sur un
    user réel avec trades historiques, l'user utilise `POST
    /api/user/delete-account` (soft delete anonymisant qui préserve les FK).

    Protection : on refuse de supprimer un user qui a des trades liés
    (personal_trades.user_id=?) pour éviter les orphans. L'admin doit
    d'abord utiliser l'endpoint soft delete, puis si besoin faire un hard
    delete manuel offline.
    """
    target = users_service.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User introuvable")
    # Empêche un admin de se supprimer lui-même accidentellement.
    if ctx.user_id == user_id:
        raise HTTPException(status_code=400, detail="Impossible de supprimer son propre compte admin")
    if users_service.has_trades(user_id):
        raise HTTPException(
            status_code=409,
            detail="User a des trades liés — utiliser soft delete (anonymisation) plutôt",
        )
    ok = users_service.admin_hard_delete_user(user_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Delete a échoué")
    logger.info("Admin %s hard-deleted user id=%s email=%s", ctx.username, user_id, target.get("email"))
    return {"ok": True, "deleted_user_id": user_id}


# ─── SaaS : onboarding utilisateur (Chantier 4) ─────────────────────
@app.get("/api/user/onboarding-status")
async def api_onboarding_status(ctx: AuthContext = Depends(auth_context)):
    """État d'onboarding du user courant.

    Le front utilise cette info pour rediriger vers /v2/onboarding si
    needs_onboarding=true. Les users env legacy (user_id=None) n'ont pas
    besoin d'onboarding (config globale via env), on renvoie needs=false.
    """
    if ctx.user_id is None:
        return {"has_broker": True, "has_pairs": True, "needs_onboarding": False}
    return users_service.is_onboarding_complete(ctx.user_id)


@app.get("/api/user/broker")
async def api_user_broker_get(ctx: AuthContext = Depends(auth_context)):
    """Retourne la config broker du user (sans exposer l'API key)."""
    if ctx.user_id is None:
        raise HTTPException(status_code=400, detail="user legacy env, pas de broker_config DB")
    cfg = users_service.get_broker_config(ctx.user_id)
    return {
        "bridge_url": cfg.get("bridge_url", ""),
        "broker_name": cfg.get("broker_name", ""),
        "api_key_set": bool(cfg.get("bridge_api_key")),
    }


@app.put("/api/user/broker")
async def api_user_broker_put(
    payload: dict,
    ctx: AuthContext = Depends(auth_context),
):
    """Persiste la config broker. Body : {bridge_url, bridge_api_key, broker_name?}."""
    if ctx.user_id is None:
        raise HTTPException(status_code=400, detail="user legacy env, edit via env .env")
    try:
        users_service.update_broker_config(
            ctx.user_id,
            bridge_url=payload.get("bridge_url", ""),
            bridge_api_key=payload.get("bridge_api_key", ""),
            broker_name=payload.get("broker_name"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@app.post("/api/user/broker/test")
async def api_user_broker_test(payload: dict, _ctx: AuthContext = Depends(auth_context)):
    """Teste la connexion à un bridge arbitraire (depuis l'onboarding wizard).

    Body : {bridge_url, bridge_api_key}. Fait GET {bridge_url}/health avec
    X-API-Key. Timeout court 3s.

    Note sécurité : endpoint authentifié (ctx requis). Users payants seulement
    plus tard via gating tier.
    """
    import httpx

    bridge_url = (payload or {}).get("bridge_url", "").rstrip("/")
    api_key = (payload or {}).get("bridge_api_key", "")
    if not bridge_url or "://" not in bridge_url:
        raise HTTPException(status_code=400, detail="bridge_url invalide")
    if not api_key:
        raise HTTPException(status_code=400, detail="bridge_api_key requis")

    url = bridge_url + "/health"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(url, headers={"X-API-Key": api_key})
            if r.status_code == 200:
                try:
                    return {"ok": True, "reachable": True, **r.json()}
                except Exception:
                    return {"ok": True, "reachable": True}
            return {
                "ok": False,
                "reachable": True,
                "status": r.status_code,
                "error": f"Bridge a répondu {r.status_code}",
            }
    except httpx.HTTPError as e:
        return {"ok": False, "reachable": False, "error": str(e)[:200]}


@app.get("/api/user/watched-pairs")
async def api_user_watched_pairs_get(ctx: AuthContext = Depends(auth_context)):
    if ctx.user_id is None:
        # Env user : renvoie la WATCHED_PAIRS globale.
        from config.settings import WATCHED_PAIRS
        return {"pairs": list(WATCHED_PAIRS), "cap": len(WATCHED_PAIRS), "tier": "legacy"}
    pairs = users_service.get_watched_pairs(ctx.user_id)
    user = users_service.get_user_by_id(ctx.user_id) or {}
    tier = user.get("tier", "free")
    cap = users_service.MAX_PAIRS_PER_TIER.get(tier, 1)
    return {"pairs": pairs, "cap": cap, "tier": tier}


@app.put("/api/user/watched-pairs")
async def api_user_watched_pairs_put(
    payload: dict,
    ctx: AuthContext = Depends(auth_context),
):
    if ctx.user_id is None:
        raise HTTPException(status_code=400, detail="user legacy env, edit via env .env")
    pairs = payload.get("pairs")
    if not isinstance(pairs, list):
        raise HTTPException(status_code=400, detail="pairs doit être une liste")
    try:
        saved = users_service.update_watched_pairs(ctx.user_id, pairs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "pairs": saved}


# ─── SaaS : signup self-service (gated par SAAS_SIGNUP_ENABLED) ─────
# Chantier 1 : l'endpoint existe pour tests locaux mais reste OFF en prod
# tant que le parcours login UI + data isolation (chantiers 2-3) ne sont
# pas livrés. On renvoie 404 si désactivé pour ne pas exposer l'API.
@app.post("/api/auth/forgot-password")
@limiter.limit("3/hour")
async def api_forgot_password(request: Request, payload: dict):
    """Génère un token de reset + envoie email. Répond 200 dans TOUS les cas
    pour éviter l'énumération d'emails existants.
    """
    email = ((payload or {}).get("email") or "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="email invalide")
    token = users_service.request_password_reset(email)
    if token:
        try:
            from backend.services import user_email_service

            user_email_service.send_password_reset(email, token)
        except Exception:
            logger.exception("send_password_reset a échoué pour %s", email)
    # Réponse identique dans les 2 cas (user existe ou pas).
    return {"ok": True}


@app.post("/api/auth/reset-password")
@limiter.limit("10/hour")
async def api_reset_password(request: Request, payload: dict):
    """Consomme un token de reset + fixe le nouveau password.
    400 si token invalide/expiré ou password trop court.
    """
    token = ((payload or {}).get("token") or "").strip()
    new_password = (payload or {}).get("new_password", "")
    if not token:
        raise HTTPException(status_code=400, detail="token requis")
    try:
        success = users_service.consume_reset_token(token, new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not success:
        raise HTTPException(status_code=400, detail="Lien invalide ou expiré")
    return {"ok": True}


@app.post("/api/auth/signup")
@limiter.limit("5/hour")
async def api_signup(request: Request, payload: dict):
    email = (payload or {}).get("email", "")
    # Gate : soit le signup public est ouvert (SAAS_SIGNUP_ENABLED=true),
    # soit l'email appartient à la whitelist d'emails de test autorisés
    # pendant la beta fermée (SIGNUP_WHITELIST). Le check whitelist se fait
    # sur l'email fourni, ce qui permet à l'admin de tester le vrai funnel
    # UI avec des alias Gmail (`+test1`, `+test2`, ...) sans rouvrir
    # l'inscription au public.
    if not SAAS_SIGNUP_ENABLED and not email_in_whitelist(email):
        raise HTTPException(status_code=404)
    password = (payload or {}).get("password", "")
    accepted_terms = bool((payload or {}).get("accepted_terms", False))
    if not email or not password:
        raise HTTPException(status_code=400, detail="email et password requis")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="password trop court (min 8)")
    # Obligation légale UE : consentement explicite aux CGU/CGV/Privacy
    # avant toute création de compte facturable. Preuve stockée en DB
    # (terms_accepted_at + terms_version).
    if not accepted_terms:
        raise HTTPException(
            status_code=400,
            detail="Vous devez accepter les CGU, CGV et la politique de confidentialité",
        )
    # Chantier 9 SaaS : 14 jours de trial Pro à l'inscription, sans CB.
    try:
        uid = users_service.create_user(
            email,
            password,
            tier=users_service.SIGNUP_TRIAL_TIER,
            trial_ends_at=users_service.new_trial_end_iso(),
            terms_version=users_service.TERMS_CURRENT_VERSION,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    # Pivot zero-friction (2026-04-23) : on pré-sélectionne les paires
    # populaires pour que l'user atterrisse direct sur le dashboard sans
    # passer par un formulaire d'onboarding. Il peut customiser ensuite
    # depuis /settings.
    try:
        users_service.update_watched_pairs(
            uid,
            users_service.default_pairs_for_tier(users_service.SIGNUP_TRIAL_TIER),
        )
    except Exception:
        logger.exception("Pré-sélection pairs par défaut a échoué pour uid=%s", uid)
    logger.info(
        "SaaS signup : user id=%s email=%s trial=%dj",
        uid, email, users_service.SIGNUP_TRIAL_DAYS,
    )
    # Welcome + verification emails. Si SMTP pas configuré OU si l'envoi
    # échoue (SMTP down, quota dépassé, sandbox Resend qui refuse l'adresse,
    # etc.), on marque le user comme verified direct — sinon il serait
    # bloqué sur le checkout Stripe sans pouvoir cliquer un lien jamais reçu.
    try:
        from backend.services import user_email_service

        if not user_email_service.is_configured():
            users_service.mark_email_auto_verified(uid)
        else:
            user_email_service.send_welcome(email, trial_days=users_service.SIGNUP_TRIAL_DAYS)
            verif_token = users_service.generate_email_verification_token(uid)
            verif_sent = user_email_service.send_email_verification(email, verif_token)
            if not verif_sent:
                # SMTP configuré mais envoi refusé → fallback auto-verify
                logger.warning(
                    "send_email_verification a retourné False pour %s, fallback auto-verify",
                    email,
                )
                users_service.mark_email_auto_verified(uid)
    except Exception:
        logger.exception("envoi emails signup a échoué pour %s", email)
        # Fallback sûr : marque verified pour ne pas bloquer l'user.
        try:
            users_service.mark_email_auto_verified(uid)
        except Exception:
            pass

    # Track parrainage si code fourni (V1 manuel — la commission sera
    # créditée par admin manuellement à la conversion en payant).
    referral_code = (payload or {}).get("referral_code", "")
    if referral_code:
        try:
            from backend.services.referrals_service import track_signup
            track_signup(referral_code, uid, email)
        except Exception:
            logger.exception("track_signup a échoué pour code=%s", referral_code)

    return {"ok": True, "user_id": uid, "trial_days": users_service.SIGNUP_TRIAL_DAYS}


@app.post("/api/auth/verify-email")
@limiter.limit("20/hour")
async def api_verify_email(request: Request, payload: dict):
    """Consomme un token de vérification email. Idempotent : si déjà
    vérifié, 200 pour UX simple."""
    token = ((payload or {}).get("token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="token requis")
    user_id = users_service.verify_email_token(token)
    if user_id is None:
        raise HTTPException(status_code=400, detail="Lien invalide")
    return {"ok": True, "user_id": user_id}


@app.post("/api/user/change-password")
@limiter.limit("5/hour")
async def api_change_password(
    request: Request,
    payload: dict,
    ctx: AuthContext = Depends(auth_context),
):
    """Change le password du user courant. Requiert le password actuel."""
    if ctx.user_id is None:
        raise HTTPException(status_code=400, detail="user legacy env, edit via .env")
    current = (payload or {}).get("current_password", "")
    new_password = (payload or {}).get("new_password", "")
    try:
        ok = users_service.change_password(ctx.user_id, current, new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=400, detail="Mot de passe actuel incorrect")
    return {"ok": True}


@app.delete("/api/user/account")
@limiter.limit("3/hour")
async def api_delete_account(
    request: Request,
    payload: dict,
    response: Response,
    ctx: AuthContext = Depends(auth_context),
):
    """Suppression RGPD du compte user courant : anonymise en DB + logout.

    Requiert `current_password` dans le body pour confirmer l'intention.
    """
    if ctx.user_id is None:
        raise HTTPException(status_code=400, detail="user legacy env, non supprimable")
    current = (payload or {}).get("current_password", "")
    if not current:
        raise HTTPException(status_code=400, detail="current_password requis")
    ok = users_service.delete_account(ctx.user_id, current)
    if not ok:
        raise HTTPException(status_code=400, detail="Mot de passe incorrect")
    # Invalide la session + cookie après anonymisation.
    logout_and_clear_cookie(request, response)
    return {"ok": True, "deleted": True}


@app.post("/api/auth/resend-verification")
@limiter.limit("3/hour")
async def api_resend_verification(
    request: Request,
    ctx: AuthContext = Depends(auth_context),
):
    """Renvoie le lien de vérification pour l'utilisateur courant."""
    if ctx.user_id is None:
        raise HTTPException(status_code=400, detail="user legacy env, déjà vérifié")
    user = users_service.get_user_by_id(ctx.user_id)
    if not user:
        raise HTTPException(status_code=404)
    if users_service.is_email_verified(user):
        return {"ok": True, "already_verified": True}
    from backend.services import user_email_service

    if not user_email_service.is_configured():
        raise HTTPException(status_code=503, detail="SMTP non configuré")
    token = users_service.generate_email_verification_token(ctx.user_id)
    try:
        user_email_service.send_email_verification(user["email"], token)
    except Exception:
        logger.exception("resend verification a échoué pour uid=%s", ctx.user_id)
        raise HTTPException(status_code=502, detail="Envoi impossible")
    return {"ok": True}


@app.get("/api/config")
async def api_public_config():
    """Config publique pour le frontend (pas d'auth requise).

    Expose uniquement des flags d'UI safe à divulguer (pas de secrets).
    """
    return {
        "signup_enabled": bool(SAAS_SIGNUP_ENABLED),
    }


@app.get("/login", include_in_schema=False)
async def login_page(request: Request):
    """Legacy login page retirée : redirige vers /v2/login."""
    return RedirectResponse("/v2/login", status_code=308)


@app.get("/api/me")
async def whoami(user: str = Depends(verify_credentials)):
    """Retourne l'utilisateur authentifie et son nom d'affichage."""
    return {"username": user, "display_name": display_name_for(user)}


@app.get("/api/health")
async def health(_=Depends(verify_credentials)):
    """Etat de sante du radar."""
    last = get_last_cycle_at()
    delta = None
    healthy = False
    if last:
        from datetime import datetime, timezone
        delta = (datetime.now(timezone.utc) - last).total_seconds()
        healthy = delta < 600  # < 10 min
    return {
        "healthy": healthy,
        "last_cycle_at": last.isoformat() if last else None,
        "seconds_since_last_cycle": delta,
    }


@app.get("/debug/macro")
async def debug_macro(_=Depends(verify_credentials)):
    """Admin-only debug view of the cached macro snapshot."""
    from datetime import datetime, timezone
    from backend.services.macro_context_service import (
        get_macro_snapshot,
        is_fresh as macro_is_fresh,
    )

    snap = get_macro_snapshot()
    if snap is None:
        return {"status": "no_snapshot_yet", "snapshot": None}

    age_sec = (datetime.now(timezone.utc) - snap.fetched_at).total_seconds()
    return {
        "status": "ok",
        "fresh": macro_is_fresh(snap.fetched_at),
        "age_seconds": round(age_sec, 1),
        "snapshot": {
            "fetched_at": snap.fetched_at.isoformat(),
            "dxy": snap.dxy_direction.value,
            "spx": snap.spx_direction.value,
            "vix_level": snap.vix_level.value,
            "vix_value": snap.vix_value,
            "us10y": snap.us10y_trend.value,
            "de10y": snap.de10y_trend.value,
            "us_de_spread_trend": snap.us_de_spread_trend,
            "oil": snap.oil_direction.value,
            "nikkei": snap.nikkei_direction.value,
            "gold": snap.gold_direction.value,
            "risk_regime": snap.risk_regime.value,
            "raw_values": snap.raw_values,
        },
    }


@app.get("/api/insights/performance")
async def api_insights_performance(
    since: str | None = None,
    ctx: AuthContext = Depends(auth_context),
):
    """Agrégat de performance des trades auto (is_auto=1, CLOSED).

    Query params :
    - since : ISO date pour filtrer les trades (ex: 2026-04-20T21:14:00+00:00).

    Retourne des buckets (score, asset_class, direction, risk_regime, session,
    pair) pour éclairer les décisions de remontée de seuil et d'activation
    du veto macro.
    """
    from backend.services import insights_service
    since = users_service.clamp_since_iso(since, _tier_of(ctx))
    return insights_service.get_performance(
        since_iso=since, user=ctx.username, user_id=ctx.user_id
    )


@app.get("/api/insights/period-stats")
async def api_insights_period_stats(
    period: str | None = None,
    since: str | None = None,
    until: str | None = None,
    ctx: AuthContext = Depends(auth_context),
):
    """Métriques consolidées par période.

    Deux modes mutuellement exclusifs :
    - Legacy : `?period=day|week|month|year|all` (backward compat)
    - Custom range : `?since=ISO&until=ISO` (les deux requis)

    Même schéma de réponse dans les deux cas. `period` dans la réponse vaut
    le preset ou 'custom'.

    Alimente le widget PeriodMetricsCard du cockpit.
    """
    from backend.services import insights_service

    if since or until:
        if not (since and until):
            raise HTTPException(status_code=400, detail="since et until requis ensemble")
        # Clamp custom range pour tier free (Free = 7 jours max).
        since = users_service.clamp_since_iso(since, _tier_of(ctx))
        return insights_service.get_period_stats_range(
            since=since, until=until, user=ctx.username, user_id=ctx.user_id
        )

    period = period or "day"
    if period not in {"day", "week", "month", "year", "all"}:
        raise HTTPException(status_code=400, detail="period invalide (day|week|month|year|all)")
    # Free : bloque les presets au-delà de 7 jours (week max côté cap 7j).
    tier = _tier_of(ctx)
    if tier == "free" and period in {"month", "year", "all"}:
        raise HTTPException(
            status_code=403,
            detail="Périodes > 7j nécessitent le tier Pro",
        )
    return insights_service.get_period_stats(
        period=period, user=ctx.username, user_id=ctx.user_id
    )


@app.get("/api/insights/equity-curve")
async def api_insights_equity_curve(
    since: str | None = None,
    ctx: AuthContext = Depends(auth_context),
):
    """Série temporelle du PnL cumulé (auto trades CLOSED, ordre chronologique).

    Query params :
    - since : ISO date pour filtrer (typiquement POST_FIX_CUTOFF).

    Retourne {points: [{closed_at, pnl, cumulative_pnl, trade_num, pair, direction}],
              total_trades, final_pnl, since}.
    """
    from backend.services import insights_service
    since = users_service.clamp_since_iso(since, _tier_of(ctx))
    return insights_service.get_equity_curve(
        since_iso=since, user=ctx.username, user_id=ctx.user_id
    )


@app.get("/api/insights/exposure-timeseries")
async def api_insights_exposure_timeseries(
    since: str,
    until: str,
    granularity: str = "auto",
    ctx: AuthContext = Depends(auth_context),
):
    """Capital à risque (€) et nb de positions ouvertes dans le temps.

    Dérivé de personal_trades : une position est comptée OPEN à t si
    created_at ≤ t et (closed_at IS NULL OR closed_at > t). Agrégé par
    granularity (5min|hour|day|month|auto, same rules as pnl-buckets).

    Alimente ExposureTimelineCard du cockpit.
    """
    from backend.services import insights_service
    if granularity not in {"5min", "hour", "day", "month", "auto"}:
        raise HTTPException(status_code=400, detail="granularity invalide")
    since = users_service.clamp_since_iso(since, _tier_of(ctx))
    try:
        return insights_service.get_exposure_timeseries(
            since=since, until=until, granularity=granularity,
            user=ctx.username, user_id=ctx.user_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/broker/account")
async def api_broker_account(_=Depends(verify_credentials)):
    """État du compte broker (équité, marge utilisée/libre, margin level).

    Proxy du bridge `/account` enrichi du `margin_level_pct` dérivé.
    """
    from backend.services.mt5_bridge import get_account
    return await get_account()


@app.get("/api/insights/rejections")
async def api_insights_rejections(
    since: str,
    until: str,
    ctx: AuthContext = Depends(require_min_tier("pro")),
):
    """Agrégat des rejections d'ordres auto-exec sur la période.

    Retourne by_reason (barres), by_hour_utc (timeline) et by_reason_hour
    (heatmap) pour la RejectionsCard du cockpit. Scopé par user_id
    (Chantier 3D) : un user ne voit que ses propres rejections.

    Feature Pro+ (Chantier 6 gating).
    """
    from backend.services import rejection_service
    return rejection_service.get_rejections(
        since=since, until=until, user_id=ctx.user_id
    )


@app.get("/api/insights/pnl-buckets")
async def api_insights_pnl_buckets(
    since: str,
    until: str,
    granularity: str = "auto",
    ctx: AuthContext = Depends(auth_context),
):
    """Série temporelle bucketisée du PnL pour le graph de la carte Performance.

    Query params :
    - since, until : bornes ISO UTC (requis).
    - granularity : '5min'|'hour'|'day'|'month'|'auto' (défaut 'auto').
      Si 'auto', résolu côté backend par span (≤36h→hour, ≤93j→day, >93j→month).

    Retourne {buckets: [{bucket_start, bucket_end, pnl, cumulative_pnl, n_trades}, ...],
              granularity_used, total_trades, final_pnl, since, until}.
    """
    from backend.services import insights_service
    if granularity not in {"5min", "hour", "day", "month", "auto"}:
        raise HTTPException(
            status_code=400,
            detail="granularity invalide (5min|hour|day|month|auto)",
        )
    since = users_service.clamp_since_iso(since, _tier_of(ctx))
    try:
        return insights_service.get_pnl_buckets(
            since=since, until=until, granularity=granularity,
            user=ctx.username, user_id=ctx.user_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/debug/smoke-test")
async def debug_smoke_test(_=Depends(verify_credentials)):
    """Admin end-to-end check : bridge, broker, mapping symboles, cycles, Telegram.

    Ne passe AUCUN ordre. Pur read-only. Retourne un rapport JSON par étape
    avec statut OK/KO et détails. Utile avant ouverture des marchés pour
    valider que toute la chaîne est opérationnelle.
    """
    import httpx
    from datetime import datetime, timezone
    from backend.services.mt5_bridge import health_check as bridge_health_check
    from backend.services.mt5_service import _resolve_symbol
    from config.settings import (
        MT5_BRIDGE_URL,
        MT5_BRIDGE_API_KEY,
        WATCHED_PAIRS,
        TELEGRAM_BOT_TOKEN,
    )

    report: dict = {}

    # 1. Bridge health
    health = await bridge_health_check()
    report["bridge_health"] = health
    bridge_ok = bool(health.get("reachable"))

    # 2. Bridge /account (connexion broker réelle)
    if bridge_ok and MT5_BRIDGE_URL and MT5_BRIDGE_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(
                    MT5_BRIDGE_URL.rstrip("/") + "/account",
                    headers={"X-API-Key": MT5_BRIDGE_API_KEY},
                )
                report["broker_account"] = {
                    "status": r.status_code,
                    "data": r.json() if r.status_code == 200 else None,
                }
        except Exception as e:
            report["broker_account"] = {"status": "error", "error": str(e)[:120]}
    else:
        report["broker_account"] = {"status": "skipped", "reason": "bridge down"}

    # 3. Bridge /symbols + vérif mapping WATCHED_PAIRS
    if bridge_ok and MT5_BRIDGE_URL and MT5_BRIDGE_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(
                    MT5_BRIDGE_URL.rstrip("/") + "/symbols",
                    headers={"X-API-Key": MT5_BRIDGE_API_KEY},
                )
                if r.status_code == 200:
                    symbols = set(r.json().get("symbols", []))
                    mapping = []
                    for pair in WATCHED_PAIRS:
                        resolved = _resolve_symbol(pair)
                        mapping.append({
                            "pair": pair,
                            "resolved": resolved,
                            "exists_at_broker": resolved in symbols,
                        })
                    missing = [m for m in mapping if not m["exists_at_broker"]]
                    report["symbol_mapping"] = {
                        "status": "ok" if not missing else "missing",
                        "total_pairs": len(mapping),
                        "missing_count": len(missing),
                        "mapping": mapping,
                    }
                else:
                    report["symbol_mapping"] = {"status": "error", "http": r.status_code}
        except Exception as e:
            report["symbol_mapping"] = {"status": "error", "error": str(e)[:120]}
    else:
        report["symbol_mapping"] = {"status": "skipped", "reason": "bridge down"}

    # 4. Dernier cycle d'analyse
    last = get_last_cycle_at()
    if last is None:
        report["analysis_cycle"] = {"status": "never_ran"}
    else:
        age = (datetime.now(timezone.utc) - last).total_seconds()
        report["analysis_cycle"] = {
            "status": "ok" if age < 600 else "stale",
            "last_at": last.isoformat(),
            "age_seconds": round(age, 1),
        }

    # 5. Telegram config
    report["telegram"] = {
        "configured": bool(TELEGRAM_BOT_TOKEN),
    }

    # Verdict global
    report["overall"] = "ok" if (
        bridge_ok
        and report["broker_account"].get("status") == 200
        and report["symbol_mapping"].get("status") == "ok"
        and report["analysis_cycle"].get("status") == "ok"
    ) else "issues"

    return report


@app.get("/api/risk")
async def risk_dashboard(ctx: AuthContext = Depends(auth_context)):
    """Risque cumule sur les positions ouvertes."""
    open_trades = trade_log_service.list_trades(
        status="OPEN", user=ctx.username, user_id=ctx.user_id
    )
    total_risk = 0.0
    rows = []
    for t in open_trades:
        risk_per_lot = abs(t["entry_price"] - t["stop_loss"]) * 100000
        risk_usd = risk_per_lot * t["size_lot"]
        total_risk += risk_usd
        rows.append({
            "pair": t["pair"], "direction": t["direction"],
            "size_lot": t["size_lot"], "risk_usd": round(risk_usd, 2),
        })
    from config.settings import TRADING_CAPITAL
    total_pct = (total_risk / TRADING_CAPITAL * 100) if TRADING_CAPITAL else 0
    warning = total_pct > 3.0
    return {
        "n_open": len(open_trades),
        "total_risk_usd": round(total_risk, 2),
        "total_risk_pct": round(total_pct, 2),
        "capital": TRADING_CAPITAL,
        "warning_over_3pct": warning,
        "by_trade": rows,
    }


@app.get("/api/equity")
async def equity_curve(ctx: AuthContext = Depends(auth_context)):
    """Courbe d'equity quotidienne calculee depuis l'historique des trades."""
    from collections import defaultdict
    from config.settings import TRADING_CAPITAL
    trades = trade_log_service.list_trades(
        status="CLOSED", limit=1000, user=ctx.username, user_id=ctx.user_id
    )
    by_day = defaultdict(float)
    for t in trades:
        if t.get("closed_at"):
            day = t["closed_at"][:10]
            by_day[day] += t["pnl"] or 0
    days = sorted(by_day.keys())
    equity = TRADING_CAPITAL
    points = [{"date": "init", "equity": round(equity, 2), "daily_pnl": 0}]
    for d in days:
        equity += by_day[d]
        points.append({"date": d, "equity": round(equity, 2), "daily_pnl": round(by_day[d], 2)})
    return {"capital_initial": TRADING_CAPITAL, "current_equity": round(equity, 2), "points": points}


@app.get("/api/trades.csv")
async def trades_csv(ctx: AuthContext = Depends(auth_context)):
    """Export CSV de l'historique des trades de l'utilisateur."""
    import io
    import csv
    from fastapi.responses import StreamingResponse
    trades = trade_log_service.list_trades(
        limit=10000, user=ctx.username, user_id=ctx.user_id
    )
    user = ctx.username
    output = io.StringIO()
    if trades:
        fieldnames = list(trades[0].keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for t in trades:
            writer.writerow(t)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=trades_{user}.csv"},
    )


@app.get("/api/stats/combos")
async def stats_combos(ctx: AuthContext = Depends(auth_context)):
    """Win rate par combinaison (pattern + paire). Necessite un historique
    de trades clotures pour etre pertinent."""
    from collections import defaultdict
    trades = trade_log_service.list_trades(
        status="CLOSED", limit=1000, user=ctx.username, user_id=ctx.user_id
    )
    combos: dict[tuple[str, str], dict] = defaultdict(lambda: {"wins": 0, "losses": 0, "total_pnl": 0.0})
    for t in trades:
        key = (t.get("signal_pattern") or "unknown", t.get("pair"))
        c = combos[key]
        if t["pnl"] > 0:
            c["wins"] += 1
        else:
            c["losses"] += 1
        c["total_pnl"] += t["pnl"] or 0
    rows = []
    for (pattern, pair), c in combos.items():
        total = c["wins"] + c["losses"]
        rows.append({
            "pattern": pattern, "pair": pair,
            "wins": c["wins"], "losses": c["losses"], "total": total,
            "win_rate_pct": round(c["wins"] / total * 100, 1) if total else 0,
            "total_pnl": round(c["total_pnl"], 2),
        })
    rows.sort(key=lambda r: r["total"], reverse=True)
    return {"min_trades_for_significance": 5, "combos": rows}


@app.get("/api/stats/mistakes")
async def stats_mistakes(ctx: AuthContext = Depends(auth_context)):
    """Detection d'erreurs : trades pris sans checklist + trades sans SL/TP poses."""
    trades = trade_log_service.list_trades(
        limit=500, user=ctx.username, user_id=ctx.user_id
    )
    no_checklist = [t for t in trades if not t.get("checklist_passed")]
    no_sl_in_mt5 = [t for t in trades if not t.get("post_entry_sl")]
    no_tp_in_mt5 = [t for t in trades if not t.get("post_entry_tp")]

    # Performance comparee
    def avg_pnl(trades):
        closed = [t for t in trades if t.get("status") == "CLOSED"]
        return round(sum(t["pnl"] or 0 for t in closed) / len(closed), 2) if closed else 0

    return {
        "total_trades": len(trades),
        "without_checklist": {
            "count": len(no_checklist),
            "avg_pnl": avg_pnl(no_checklist),
        },
        "without_sl_set": {
            "count": len(no_sl_in_mt5),
            "avg_pnl": avg_pnl(no_sl_in_mt5),
        },
        "without_tp_set": {
            "count": len(no_tp_in_mt5),
            "avg_pnl": avg_pnl(no_tp_in_mt5),
        },
        "with_checklist_avg_pnl": avg_pnl([t for t in trades if t.get("checklist_passed")]),
    }


# Docs publiques (CGU/CGV/Privacy + guide install bridge) — accessible sans auth.
# Les anciens mounts `/css` et `/js` pour le frontend V1 ont été retirés
# après le swap / → /v2 (2026-04-24).
_DOCS_DIR = FRONTEND_DIR / "docs"
if _DOCS_DIR.exists():
    app.mount("/docs", StaticFiles(directory=str(_DOCS_DIR), html=True), name="docs")

# SPA React V2 (coexiste avec l'ancien frontend servi sur /)
from pathlib import Path as _PathV2
from fastapi.responses import FileResponse as _FileResponseV2
_V2_DIST = _PathV2(__file__).parent.parent / "frontend-react" / "dist"
if _V2_DIST.exists():
    app.mount(
        "/v2/assets",
        StaticFiles(directory=str(_V2_DIST / "assets")),
        name="v2-assets",
    )

    @app.get("/v2/{path:path}", include_in_schema=False)
    async def serve_v2(path: str):
        """SPA fallback : tout ce qui n'est pas un asset tombe sur index.html,
        React Router se charge du routing côté client.

        index.html et sw.js DOIVENT être revalidés à chaque fois : sinon le
        navigateur peut servir un vieux HTML pointant vers un bundle JS qui
        n'existe plus → écran cassé ou composants manquants."""
        candidate = _V2_DIST / path
        if candidate.is_file():
            # sw.js : no-cache obligatoire (sinon le SW ne se met jamais à jour)
            if path == "sw.js":
                return _FileResponseV2(
                    str(candidate),
                    headers={"Cache-Control": "no-cache, must-revalidate"},
                )
            return _FileResponseV2(str(candidate))
        # Fallback SPA → index.html, no-cache pour garantir bundle à jour
        return _FileResponseV2(
            str(_V2_DIST / "index.html"),
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )


@app.get("/")
async def index(request: Request):
    """Racine redirige désormais vers la V2 (SPA React). L'ancien frontend
    est conservé sur disque mais plus exposé."""
    return RedirectResponse("/v2/", status_code=308)


@app.get("/manifest.json")
async def manifest():
    """Manifest PWA pour installation sur ecran d'accueil mobile."""
    return FileResponse(str(FRONTEND_DIR / "manifest.json"), media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
async def pwa_service_worker():
    """Service worker (PWA offline shell). Accessible sans auth pour que le
    navigateur puisse l'enregistrer et le mettre a jour."""
    return FileResponse(
        str(FRONTEND_DIR / "sw.js"),
        media_type="text/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache",
        },
    )


@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    """Robots.txt — autorise indexation pages publiques marketing,
    bloque dashboards authentifiés + API."""
    return FileResponse(str(FRONTEND_DIR / "robots.txt"), media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml():
    """Sitemap des pages publiques pour SEO."""
    from fastapi.responses import Response
    base = "https://scalping-radar.duckdns.org"
    pages = [
        ("/v2/", "weekly", "1.0"),
        ("/v2/live", "hourly", "0.9"),
        ("/v2/track-record", "daily", "0.9"),
        ("/v2/research", "weekly", "0.8"),
        ("/v2/pricing", "monthly", "0.7"),
        ("/v2/login", "monthly", "0.3"),
        ("/v2/signup", "monthly", "0.3"),
    ]
    today = "2026-04-26"
    urls = "\n".join(
        f"  <url>\n    <loc>{base}{path}</loc>\n    <lastmod>{today}</lastmod>\n    <changefreq>{freq}</changefreq>\n    <priority>{prio}</priority>\n  </url>"
        for path, freq, prio in pages
    )
    xml = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}\n</urlset>\n'
    return Response(content=xml, media_type="application/xml")


# ─── Icônes PNG pour manifest PWA (WebAPK Android exige du raster) ───
# Générées une fois à l'import puis mises en cache mémoire. Chrome refuse
# de promouvoir la PWA en WebAPK si les icônes sont en data URI ou SVG —
# il faut des PNG servies depuis une URL HTTP réelle.

from functools import lru_cache


def _generate_icon_png(size: int) -> bytes:
    """Crée le badge 'SR' sur fond #0d1117 en PNG. Taille en pixels (192 ou 512)."""
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFont

    bg = (13, 17, 23, 255)       # #0d1117
    fg = (88, 166, 255, 255)     # #58a6ff
    img = Image.new("RGBA", (size, size), bg)
    draw = ImageDraw.Draw(img)
    # Texte "SR" centré. Police : DejaVu Sans Bold (présente dans python:slim).
    try:
        # Taille de police ~55% du canvas — donne un rendu propre aux deux tailles.
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", int(size * 0.42))
    except Exception:
        font = ImageFont.load_default()
    text = "SR"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]), text, fill=fg, font=font)
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


@lru_cache(maxsize=4)
def _get_icon_bytes(size: int) -> bytes:
    return _generate_icon_png(size)


@app.get("/icons/icon-{size}.png", include_in_schema=False)
async def pwa_icon(size: int):
    """Icône PNG générée pour le manifest PWA. Taille autorisée : 192 ou 512."""
    if size not in (192, 512):
        raise HTTPException(status_code=404, detail="Taille inconnue")
    from fastapi.responses import Response
    return Response(
        content=_get_icon_bytes(size),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=2592000, immutable"},
    )


@app.get("/api/macro")
async def api_macro():
    """Public endpoint: current macro snapshot for the dashboard banner."""
    from backend.services.macro_context_service import get_macro_snapshot, is_fresh
    from datetime import datetime, timezone

    snap = get_macro_snapshot()
    if snap is None:
        return {"available": False}

    age_sec = (datetime.now(timezone.utc) - snap.fetched_at).total_seconds()
    return {
        "available": True,
        "fresh": is_fresh(snap.fetched_at),
        "age_seconds": round(age_sec, 1),
        "indicators": {
            "dxy": {"direction": snap.dxy_direction.value, "value": snap.raw_values.get("dxy")},
            "spx": {"direction": snap.spx_direction.value, "value": snap.raw_values.get("spx")},
            "vix": {"level": snap.vix_level.value, "value": snap.vix_value},
            "us10y": {"direction": snap.us10y_trend.value, "value": snap.raw_values.get("us10y")},
            "de10y": {"direction": snap.de10y_trend.value, "value": snap.raw_values.get("de10y")},
            "oil": {"direction": snap.oil_direction.value, "value": snap.raw_values.get("oil")},
            "nikkei": {"direction": snap.nikkei_direction.value, "value": snap.raw_values.get("nikkei")},
            "gold": {"direction": snap.gold_direction.value, "value": snap.raw_values.get("gold")},
        },
        "risk_regime": snap.risk_regime.value,
        "spread_trend": snap.us_de_spread_trend,
    }


@app.get("/api/overview")
async def get_overview(_=Depends(verify_credentials)):
    """Get the latest market overview data."""
    overview = get_latest_overview()
    if overview is None:
        return JSONResponse(
            {"status": "loading", "message": "Initial analysis in progress..."},
            status_code=202,
        )
    return overview.model_dump(mode="json")


@app.get("/api/signals")
async def get_signals(_=Depends(verify_credentials)):
    """Get current active signals."""
    overview = get_latest_overview()
    if overview is None:
        return []
    return [s.model_dump(mode="json") for s in overview.signals]


@app.get("/api/signals/history")
async def get_signals_history(_=Depends(verify_credentials)):
    """Get signal history."""
    return get_signal_history()


@app.get("/api/volatility")
async def get_volatility(_=Depends(verify_credentials)):
    """Get current volatility data."""
    overview = get_latest_overview()
    if overview is None:
        return []
    return [v.model_dump(mode="json") for v in overview.volatility_data]


@app.get("/api/events")
async def get_events(_=Depends(verify_credentials)):
    """Get economic events."""
    overview = get_latest_overview()
    if overview is None:
        return []
    return [e.model_dump(mode="json") for e in overview.economic_events]


@app.get("/api/trade-setups")
async def get_trade_setups(_=Depends(verify_credentials)):
    """Récupère les setups de trade (entrée/SL/TP)."""
    overview = get_latest_overview()
    if overview is None:
        return []
    return [s.model_dump(mode="json") for s in overview.trade_setups]


@app.get("/api/patterns")
async def get_patterns(_=Depends(verify_credentials)):
    """Récupère les patterns détectés."""
    overview = get_latest_overview()
    if overview is None:
        return []
    return [p.model_dump(mode="json") for p in overview.patterns]


@app.get("/api/glossary")
async def get_glossary(_=Depends(verify_credentials)):
    """Retourne le glossaire de tous les termes et abréviations."""
    return GLOSSARY


GLOSSARY = [
    {"term": "SL", "full": "Stop Loss", "definition": "Niveau de prix auquel la position est automatiquement coupee pour limiter les pertes. Place en dessous du prix d'entree pour un achat, au-dessus pour une vente."},
    {"term": "TP", "full": "Take Profit", "definition": "Niveau de prix auquel la position est automatiquement cloturee pour encaisser les gains."},
    {"term": "TP1", "full": "Take Profit 1 (conservateur)", "definition": "Premier objectif de gain, plus proche du prix d'entree. Ratio risque/recompense de 1.5x le risque. Atteint plus souvent que le TP2."},
    {"term": "TP2", "full": "Take Profit 2 (agressif)", "definition": "Second objectif de gain, plus eloigne. Ratio de 2.5x le risque. Moins souvent atteint mais gain plus important."},
    {"term": "R:R", "full": "Risk/Reward (Risque/Recompense)", "definition": "Ratio entre le gain potentiel et la perte potentielle. Un R:R de 2.0 signifie que le gain vise est 2x la perte maximale. Un bon trade a un R:R >= 1.5."},
    {"term": "ATR", "full": "Average True Range", "definition": "Indicateur de volatilite qui mesure l'amplitude moyenne des bougies sur N periodes. Utilise pour calibrer les SL et TP en fonction de la volatilite reelle du marche."},
    {"term": "SMA", "full": "Simple Moving Average (Moyenne Mobile Simple)", "definition": "Moyenne des prix de cloture sur N periodes. Sert de reference pour identifier la tendance et les ecarts anormaux (mean reversion)."},
    {"term": "OHLC", "full": "Open/High/Low/Close", "definition": "Les 4 prix d'une bougie : Ouverture, Plus Haut, Plus Bas, Cloture. Base de toute l'analyse technique."},
    {"term": "Pip", "full": "Point in Percentage", "definition": "Plus petite unite de variation de prix sur le forex. Pour EUR/USD : 0.0001. Pour XAU/USD (or) : 0.01 dollar."},
    {"term": "Spread", "full": "Ecart achat/vente", "definition": "Difference entre le prix d'achat (ask) et le prix de vente (bid). Cout implicite de chaque trade — plus le spread est faible, mieux c'est pour le scalping."},
    {"term": "Scalping", "full": "Scalping", "definition": "Strategie de trading ultra-court terme (quelques secondes a quelques minutes). Objectif : capturer de petits mouvements de prix avec des positions courtes et frequentes."},
    {"term": "Breakout", "full": "Cassure", "definition": "Le prix franchit un niveau de support ou resistance important. Signal de continuation du mouvement dans la direction de la cassure."},
    {"term": "Momentum", "full": "Dynamique de prix", "definition": "Force et vitesse du mouvement de prix. Un momentum fort signifie que les acheteurs (ou vendeurs) dominent clairement le marche."},
    {"term": "Range", "full": "Canal horizontal", "definition": "Le prix evolue entre deux bornes (support et resistance) sans tendance claire. Strategie : acheter en bas du range, vendre en haut."},
    {"term": "Mean Reversion", "full": "Retour a la moyenne", "definition": "Theorie selon laquelle un prix qui s'eloigne trop de sa moyenne tend a y revenir. Base des strategies contrariantes."},
    {"term": "Engulfing", "full": "Bougie englobante", "definition": "Pattern de retournement ou une bougie englobe entierement le corps de la precedente. Signal fort de changement de controle entre acheteurs et vendeurs."},
    {"term": "Pin Bar", "full": "Bougie a meche de rejet", "definition": "Bougie avec un petit corps et une longue meche dans une direction. La meche montre un rejet violent d'un niveau de prix."},
    {"term": "Bullish", "full": "Haussier", "definition": "Mouvement ou signal indiquant une hausse des prix. Les acheteurs dominent."},
    {"term": "Bearish", "full": "Baissier", "definition": "Mouvement ou signal indiquant une baisse des prix. Les vendeurs dominent."},
    {"term": "Support", "full": "Niveau de support", "definition": "Niveau de prix ou les acheteurs interviennent regulierement, empechant le prix de baisser davantage."},
    {"term": "Resistance", "full": "Niveau de resistance", "definition": "Niveau de prix ou les vendeurs interviennent regulierement, empechant le prix de monter davantage."},
    {"term": "Volatilite", "full": "Volatilite", "definition": "Mesure de l'amplitude des mouvements de prix. Haute volatilite = grands mouvements = plus d'opportunites (et plus de risque)."},
    {"term": "XAU", "full": "Or (Gold)", "definition": "Code ISO pour l'or. XAU/USD = prix de l'once d'or en dollars americains."},
    {"term": "EUR", "full": "Euro", "definition": "Devise de la zone euro. Deuxieme devise la plus echangee au monde."},
    {"term": "USD", "full": "Dollar americain", "definition": "Devise de reference mondiale. Presente dans la majorite des paires forex."},
    {"term": "GBP", "full": "Livre sterling", "definition": "Devise du Royaume-Uni. Paire volatile, appreciee des scalpeurs."},
    {"term": "JPY", "full": "Yen japonais", "definition": "Devise du Japon. Valeur refuge — monte souvent quand les marches chutent."},
    {"term": "CHF", "full": "Franc suisse", "definition": "Devise de la Suisse. Valeur refuge comme le yen."},
    {"term": "AUD", "full": "Dollar australien", "definition": "Devise de l'Australie. Correlée aux matieres premieres et a l'economie chinoise."},
    {"term": "CAD", "full": "Dollar canadien", "definition": "Devise du Canada. Fortement correlée au prix du petrole."},
    {"term": "Position", "full": "Taille de position", "definition": "Montant investi sur un trade. Calculee en fonction du risque accepte (% du capital) et de la distance au SL."},
    {"term": "Risque max", "full": "Perte maximale", "definition": "Montant maximum que vous perdez si le SL est touche. Generalement 1-2% du capital par trade pour une gestion saine."},
]


@app.get("/api/candles/{pair:path}")
async def get_candles_by_pair(pair: str, _=Depends(verify_credentials)):
    """Retourne les dernieres bougies OHLC pour une paire (ex: XAU/USD)."""
    candles = get_candles_for_pair(pair)
    return {
        "pair": pair,
        "interval": "5min",
        "candles": [c.model_dump(mode="json") for c in candles],
    }


@app.get("/api/candles")
async def get_all_candles(_=Depends(verify_credentials)):
    """Retourne toutes les bougies groupees par paire."""
    all_candles = get_all_pair_candles()
    return {
        pair: [c.model_dump(mode="json") for c in candles]
        for pair, candles in all_candles.items()
    }


@app.get("/api/trades")
async def list_trades(
    status: str | None = None,
    limit: int = 100,
    ctx: AuthContext = Depends(auth_context),
):
    return trade_log_service.list_trades(
        status=status, limit=limit, user=ctx.username, user_id=ctx.user_id
    )


@app.get("/api/cockpit")
async def cockpit(ctx: AuthContext = Depends(auth_context)):
    """Snapshot consolidé pour la homepage "tour de contrôle".

    Regroupe en un seul appel : trades actifs (PnL temps réel), setups en
    attente, stats du jour, santé système, contexte macro, events imminents
    et alertes. Voir backend/services/cockpit_service.py.
    """
    from backend.services.cockpit_service import build_cockpit
    return await build_cockpit(ctx.username, user_id=ctx.user_id)


@app.get("/api/analytics")
async def analytics(ctx: AuthContext = Depends(auth_context)):
    """Breakdowns du win rate par features : pair, hour, pattern, confidence,
    asset_class, risk_regime. Inclut la qualité d'exécution (slippage,
    close_reason) scopée sur les trades de l'utilisateur courant.

    Utile pour piloter le modèle : quels instruments retirer, quelles
    heures éviter, si le confidence_score est calibré."""
    from backend.services.analytics_service import build_analytics
    return build_analytics(user=ctx.username, user_id=ctx.user_id)


@app.get("/api/drift")
async def drift(_=Depends(verify_credentials)):
    """Detection des drifts : paires et patterns dont le win rate des 7
    derniers jours chute de plus de 15 points vs la baseline historique.
    Utile pour desactiver proactivement un signal qui perd son edge."""
    from backend.services.drift_detection import find_drifts
    return find_drifts()


@app.get("/api/status")
async def system_status(_=Depends(verify_credentials)):
    """Observabilité : dernier cycle d'analyse, dernières syncs COT / Fear & Greed,
    prochains jobs APScheduler, état du kill switch. Utile pour diagnostiquer
    un pipeline qui a l'air figé sans avoir à SSH."""
    from backend.services.scheduler import get_last_cycle_at, _scheduler
    from backend.services import fear_greed_service, cot_service, kill_switch
    import sqlite3

    last_cycle = get_last_cycle_at()
    cycle_age = None
    if last_cycle:
        cycle_age = (datetime.now(timezone.utc) - last_cycle).total_seconds()

    fg_snap = fear_greed_service.get_current()
    cot_latest = cot_service.get_latest()
    cot_last_date = max((c.get("report_date") or "" for c in cot_latest), default=None)

    # Jobs APScheduler : prochaine exécution + état
    jobs: list[dict] = []
    try:
        for job in _scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            })
    except Exception:
        pass

    # Count trades dans la DB pour contexte "progression observation"
    trade_counts: dict = {}
    try:
        from backend.services.trade_log_service import _DB_PATH
        with sqlite3.connect(_DB_PATH) as c:
            row = c.execute(
                "SELECT status, COUNT(*) FROM personal_trades GROUP BY status"
            ).fetchall()
            for status_key, n in row:
                trade_counts[status_key] = n
    except Exception:
        pass

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "analysis_cycle": {
            "last_cycle_at": last_cycle.isoformat() if last_cycle else None,
            "age_seconds": round(cycle_age, 1) if cycle_age is not None else None,
            "healthy": cycle_age is not None and cycle_age < 600,
        },
        "fear_greed": {
            "last_sync": fg_snap.get("recorded_at") if fg_snap else None,
            "value": fg_snap.get("value") if fg_snap else None,
            "classification": fg_snap.get("classification") if fg_snap else None,
        },
        "cot": {
            "last_report_date": cot_last_date,
            "contracts_tracked": len(cot_latest),
        },
        "kill_switch": kill_switch.status(),
        "trade_counts": trade_counts,
        "scheduler_jobs": jobs,
    }


@app.get("/api/cot")
async def cot_report(_=Depends(verify_credentials)):
    """Derniers rapports COT (Commitments of Traders) : positionnement
    des hedge funds (leveraged_funds) et des petits traders
    (non_reportables) sur les futures US, avec z-score 52 semaines.
    Permet de flagger les extremes contrariens."""
    from backend.services import cot_service
    return {
        "latest": cot_service.get_latest(),
        "extremes": cot_service.find_extremes(),
    }


@app.post("/api/cot/refresh")
async def cot_refresh(_=Depends(verify_credentials)):
    """Force le pull d'un rapport COT depuis la CFTC. Normalement tourne
    automatiquement chaque samedi 01h UTC via le scheduler."""
    from backend.services import cot_service
    return await cot_service.sync_latest()


@app.get("/api/fear-greed")
async def fear_greed(_=Depends(verify_credentials)):
    """Indicateur CNN Fear & Greed : valeur 0-100 + classification."""
    from backend.services import fear_greed_service
    return fear_greed_service.get_current() or {"available": False}


@app.post("/api/fear-greed/refresh")
async def fear_greed_refresh(_=Depends(verify_credentials)):
    """Force un fetch CNN. Normalement tourne quotidien a 22h30 UTC."""
    from backend.services import fear_greed_service
    snap = await fear_greed_service.fetch_latest()
    return snap or {"available": False}


@app.get("/api/kill-switch")
async def kill_switch_status(_=Depends(verify_credentials)):
    """Etat du kill switch global. Voir backend/services/kill_switch.py."""
    from backend.services import kill_switch
    return kill_switch.status()


@app.post("/api/kill-switch")
async def kill_switch_set(payload: dict, _=Depends(verify_credentials)):
    """Active/désactive manuellement le kill switch. Payload :
    `{"enabled": true, "reason": "maintenance broker"}` pour bloquer,
    `{"enabled": false}` pour débloquer."""
    from backend.services import kill_switch
    enabled = bool(payload.get("enabled", False))
    reason = payload.get("reason") if enabled else None
    kill_switch.set_manual(enabled=enabled, reason=reason)
    return kill_switch.status()


@app.get("/api/daily-status")
async def daily_status(ctx: AuthContext = Depends(auth_context)):
    """Statut journalier : PnL, nb trades, mode silencieux."""
    status = trade_log_service.get_daily_status(user=ctx.username, user_id=ctx.user_id)
    open_trades = trade_log_service.list_trades(
        status="OPEN", user=ctx.username, user_id=ctx.user_id
    )
    status["open_trades"] = open_trades
    status["username"] = ctx.username
    status["display_name"] = display_name_for(ctx.username)
    return status


@app.post("/api/silent-mode")
async def toggle_silent_mode(payload: dict, user: str = Depends(verify_credentials)):
    """Active/desactive le mode silencieux pour l'utilisateur connecte."""
    enabled = bool(payload.get("enabled", False))
    trade_log_service.set_manual_silent(user, enabled)
    return {"silent_mode": enabled, "user": user}


@app.get("/api/backtest/stats")
async def get_backtest_stats(_ctx: AuthContext = Depends(require_min_tier("premium"))):
    """Statistiques globales des signaux backtestes (Premium)."""
    return backtest_service.get_stats()


@app.get("/api/backtest/trades")
async def get_backtest_trades(
    limit: int = 50,
    _ctx: AuthContext = Depends(require_min_tier("premium")),
):
    """Historique des trades backtestes (Premium)."""
    return backtest_service.get_recent_trades(limit=limit)


@app.get("/api/indicators/{pair:path}")
async def get_indicators(pair: str, _=Depends(verify_credentials)):
    """RSI + MACD + Bollinger pour une paire a partir des dernieres bougies."""
    candles = get_candles_for_pair(pair)
    return {"pair": pair, **indicators.compute_all(candles)}


@app.get("/api/ticks")
async def get_ticks(_=Depends(verify_credentials)):
    """Derniers ticks temps reel recus via WebSocket Twelve Data."""
    ticks = twelvedata_ws.get_latest_ticks()
    return {
        "enabled": bool(ticks) or len(twelvedata_ws.get_subscribed_symbols()) > 0,
        "symbols": twelvedata_ws.get_subscribed_symbols(),
        "ticks": {pair: t.model_dump(mode="json") for pair, t in ticks.items()},
    }


@app.post("/api/refresh")
async def refresh_analysis(_=Depends(verify_credentials)):
    """Manually trigger a new analysis cycle."""
    asyncio.create_task(run_analysis_cycle())
    return {"status": "ok", "message": "Analysis refresh triggered"}


# ─── Phase 4 — Shadow log V2_CORE_LONG ─────────────────────────────────────
# Spec : docs/superpowers/specs/2026-04-25-phase4-shadow-log-spec.md

@app.get("/api/shadow/v2_core_long/setups")
async def api_shadow_setups(
    since: str | None = None,
    until: str | None = None,
    system_id: str | None = None,
    outcome: str | None = None,
    limit: int = 200,
    ctx: AuthContext = Depends(auth_context),
):
    """Liste les shadow setups V2_CORE_LONG avec filtres optionnels.

    Query params:
    - since: ISO date YYYY-MM-DD ou ISO 8601 timestamp
    - until: idem
    - system_id: ex 'V2_CORE_LONG_XAUUSD_4H' / 'V2_CORE_LONG_XAGUSD_4H'
    - outcome: 'TP1' | 'SL' | 'TIMEOUT' | 'pending' (= NULL)
    - limit: max 1000
    """
    from datetime import datetime as _dt
    from backend.services.shadow_v2_core_long import list_setups

    def _parse(s: str | None):
        if not s:
            return None
        try:
            return _dt.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return _dt.strptime(s, "%Y-%m-%d")

    return list_setups(
        since=_parse(since),
        until=_parse(until),
        system_id=system_id,
        outcome=outcome,
        limit=min(limit, 1000),
    )


@app.get("/api/shadow/v2_core_long/summary")
async def api_shadow_summary(ctx: AuthContext = Depends(auth_context)):
    """KPIs synthétiques sur les shadow setups V2_CORE_LONG.

    Retourne par système :
    - n_total / n_pending / n_tp1 / n_sl / n_timeout
    - PF observed (sur outcomes resolved)
    - WR pct
    - net_pnl_eur cumulé
    - first_bar / last_bar
    - advanced : Sharpe, Calmar, maxDD%, monthly_returns, equity_curve
    """
    from backend.services.shadow_v2_core_long import summary
    return summary()


@app.get("/api/shadow/v2_core_long/public-summary")
async def api_shadow_public_summary(token: str = ""):
    """Endpoint summary public auth-by-token (sans cookie session).

    Permet aux agents remote / monitoring externes de fetcher les KPIs
    shadow log sans avoir le cookie session. Le token est hashé côté
    backend (constante SHA256), le token clair est conservé seulement
    dans la config du routine consommateur (pas dans le repo).

    Pour révoquer : générer un nouveau token, mettre à jour le hash
    constante ci-dessous, redéployer, mettre à jour le routine.
    """
    import hashlib
    from fastapi import HTTPException

    # SHA256 du token clair. Token clair dans la config routine.
    # Régénérable via : python -c "import secrets; print('shdw_'+secrets.token_urlsafe(24))"
    SHADOW_PUBLIC_TOKEN_HASH = "e980b1ed0b45ca6873caa3f2d6ddcf27f4d8a1d0aa87cf9072f6e3e0909b31ec"

    if not token:
        raise HTTPException(status_code=403, detail="token required")

    provided_hash = hashlib.sha256(token.encode()).hexdigest()
    # Comparison time-constant pour éviter timing attacks
    import secrets as _s
    if not _s.compare_digest(provided_hash, SHADOW_PUBLIC_TOKEN_HASH):
        raise HTTPException(status_code=403, detail="invalid token")

    from backend.services.shadow_v2_core_long import summary
    return summary()


# ─── Endpoints publics shadow log (no auth) ─────────────────────────────────
# Pour pages publiques /v2/live et /v2/track-record qui affichent le track
# record en temps réel sans demander de login. Lecture seule, sanitisé
# (pas de macro_features_json sensible, pas de cycle_at interne).


@app.get("/api/public/shadow/summary")
async def api_public_shadow_summary():
    """KPIs agrégés des 6 stars en temps réel (sans auth).

    Retourne summary() du shadow_v2_core_long mais filtré pour ne pas
    exposer de données techniques internes. Utilisé par la page /v2/live.
    """
    from backend.services.shadow_v2_core_long import summary
    raw = summary()
    return {"systems": raw.get("systems", [])}


@app.get("/api/public/shadow/setups")
async def api_public_shadow_setups(
    system_id: str | None = None,
    outcome: str | None = None,
    limit: int = 100,
):
    """Liste des setups shadow récents (sans auth, lecture seule).

    Query params :
    - system_id : filtre optionnel par système
    - outcome : filtre par outcome ("pending"|"TP1"|"SL"|"TIMEOUT")
    - limit : capé à 200 (anti-abus)

    Sanitise : retire macro_features_json + cycle_at + sizing_* internes.
    Utilisé par la page /v2/track-record.
    """
    from backend.services.shadow_v2_core_long import list_setups

    rows = list_setups(
        system_id=system_id,
        outcome=outcome,
        limit=min(limit, 200),
    )

    sanitized_keys = {
        "id", "detected_at", "bar_timestamp", "system_id", "pair", "timeframe",
        "direction", "pattern", "entry_price", "stop_loss",
        "take_profit_1", "take_profit_2", "risk_pct", "rr",
        "outcome", "exit_at", "exit_price", "pnl_pct_net", "pnl_eur",
    }
    return [
        {k: v for k, v in r.items() if k in sanitized_keys}
        for r in rows
    ]


@app.get("/api/public/changelog")
async def api_public_changelog():
    """Liste les commits récents avec types.

    Stratégie :
    1. Lit `docs/changelog.json` s'il existe (pré-généré au deploy)
    2. Sinon fallback git log (hors container où .git est dispo)
    3. Sinon retour vide avec count=0
    """
    import json
    import re
    import subprocess
    from pathlib import Path

    # Stratégie 1 : fichier statique pré-généré
    for candidate in [Path("docs/changelog.json"), Path("/app/docs/changelog.json")]:
        if candidate.exists():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "commits" in data:
                    return {**data, "count": len(data.get("commits", []))}
            except Exception:
                pass

    # Stratégie 2 : git log direct (dev local avec .git)
    try:
        result = subprocess.run(
            ["git", "log", "--pretty=format:%H|%ad|%s", "--date=iso-strict", "-50"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return {"commits": [], "count": 0}
    except Exception:
        return {"commits": [], "count": 0}

    commits = []
    for line in result.stdout.split("\n"):
        if not line.strip():
            continue
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        h, date, subject = parts
        ct_match = re.match(r"^(\w+)(?:\(([^)]+)\))?(?:!)?:\s*(.+)$", subject)
        if ct_match:
            ctype = ct_match.group(1)
            cscope = ct_match.group(2)
            cmsg = ct_match.group(3)
        else:
            ctype = "other"
            cscope = None
            cmsg = subject
        commits.append({
            "hash": h[:7],
            "date": date[:10],
            "type": ctype,
            "scope": cscope,
            "subject": cmsg[:200],
        })

    return {"commits": commits, "count": len(commits)}


@app.get("/api/public/research/experiments")
async def api_public_research_experiments():
    """Expose le journal de recherche publiquement (36 expériences fermées).

    Lit `docs/superpowers/journal/INDEX.md` et parse la table markdown des
    expériences pour la rendre disponible côté page /v2/research. Cache
    mémoire 5 min (le journal change rarement).
    """
    import re
    from pathlib import Path

    INDEX_PATH = Path("docs/superpowers/journal/INDEX.md")
    if not INDEX_PATH.exists():
        # Container path
        INDEX_PATH = Path("/app/docs/superpowers/journal/INDEX.md")

    if not INDEX_PATH.exists():
        return {"experiments": [], "error": "INDEX.md non trouvé"}

    text = INDEX_PATH.read_text(encoding="utf-8")
    lines = text.split("\n")

    experiments = []
    table_started = False
    for line in lines:
        line = line.strip()
        # Détecter début de table
        if line.startswith("| #"):
            table_started = True
            continue
        if not table_started:
            continue
        # Skip séparateur markdown
        if line.startswith("|---") or not line.startswith("|"):
            if line and not line.startswith("|"):
                # Fin de la table
                break
            continue
        # Parse row : | num | date | track | title | status | verdict |
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) < 6:
            continue
        num, date, track, title_md, status, verdict = cells[:6]
        # Extract title from markdown link [text](url)
        link_match = re.match(r"\[([^\]]+)\]\(([^)]+)\)", title_md)
        title = link_match.group(1) if link_match else title_md
        link = link_match.group(2) if link_match else None

        # Strip emoji et badges du verdict
        verdict_clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", verdict)

        experiments.append({
            "num": num,
            "date": date,
            "track": track,
            "title": title,
            "link": link,
            "status": status,
            "verdict": verdict_clean[:300],
        })

    return {
        "experiments": experiments,
        "count": len(experiments),
    }


@app.post("/api/public/leads/subscribe")
async def api_public_lead_subscribe(request: Request):
    """Inscription email à la liste beta (avant ouverture signup 2026-06-07).

    Body JSON : {"email": "x@y.com", "source": "landing"}
    Réponse : {"ok": true|false, "message": "..."}

    Idempotent (email dupliqué ne crée pas d'erreur).
    """
    from backend.services.leads_service import add_lead

    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "message": "JSON invalide"}

    email = (body.get("email") or "").strip()
    source = body.get("source")
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent", "")[:200]

    return add_lead(email=email, source=source, ip=ip, user_agent=ua)


@app.get("/api/referrals/me")
async def api_referrals_me(ctx: AuthContext = Depends(auth_context)):
    """Retourne le code de parrainage du user + ses stats. Crée si absent."""
    from backend.services.referrals_service import get_or_create_code, get_my_stats

    if not ctx.user:
        raise HTTPException(status_code=401, detail="auth required")

    code = get_or_create_code(ctx.user.id, ctx.user.email)
    stats = get_my_stats(ctx.user.id)
    return {**stats, "code": code, "share_url": f"https://scalping-radar.duckdns.org/v2/?ref={code}"}


@app.get("/api/public/referrals/validate")
async def api_public_referrals_validate(code: str = ""):
    """Valide un code de parrainage et retourne info (publique, anonymisé)."""
    from backend.services.referrals_service import validate_code
    return validate_code(code)


@app.get("/api/admin/leads")
async def api_admin_leads(ctx: AuthContext = Depends(auth_context)):
    """Liste les leads (admin uniquement)."""
    from backend.services.leads_service import list_leads, count_leads

    if not ctx.user or ctx.user.email not in ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="admin only")

    return {
        "total": count_leads(),
        "leads": list_leads(limit=500),
    }


@app.get("/api/admin/equity-live")
async def api_admin_equity_live(
    points: int = 200,
    _ctx: AuthContext = Depends(require_admin),
):
    """Courbe equity/balance MT5 en quasi temps réel.

    Source : tail du JSONL `bridge_monitor.log` (1 ligne par cycle ≈ 60s).
    Pour chaque ligne, on extrait `probes.bridge_vps.account.{balance,
    equity, profit, positions_count}` plus le timestamp. Si bridge_vps
    n'a pas répondu sur ce cycle, on skip.

    points : 200 par défaut = ~3h20 d'historique. Max 5000 (~83h).
    """
    import json as _json
    import subprocess

    points = max(10, min(points, 5000))
    log_path = "/var/log/scalping/bridge_monitor.log"

    try:
        # On lit large (3x demandé) pour absorber les cycles où bridge_vps
        # était DOWN — on filtrera après.
        r = subprocess.run(
            ["tail", "-n", str(points * 3), log_path],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except subprocess.SubprocessError as e:
        raise HTTPException(status_code=502, detail=f"tail failed: {e}")
    except FileNotFoundError:
        raise HTTPException(status_code=502, detail="bridge_monitor.log absent")

    series: list[dict] = []
    for line in r.stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            rec = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        ts = rec.get("ts")
        bridge = (rec.get("probes") or {}).get("bridge_vps") or {}
        acc = bridge.get("account") or {}
        if not ts or not acc or "equity" not in acc:
            continue
        series.append(
            {
                "ts": ts,
                "balance_eur": acc.get("balance"),
                "equity_eur": acc.get("equity"),
                "profit_eur": acc.get("profit"),
                "positions_count": acc.get("positions_count"),
            }
        )

    # Garde les N derniers points avec data valide
    series = series[-points:]
    return {
        "points": series,
        "count": len(series),
        "source": "bridge_monitor.log",
    }


@app.get("/api/admin/control-tower")
async def api_admin_control_tower(_ctx: AuthContext = Depends(require_admin)):
    """Forward du status JSON depuis bridge_monitor (port 8090 sur Tailscale EC2).

    Sert la page /v2/control-tower : 8 sondes (bridges, systemd, radar_cycle,
    disk, tailscale) + historique des recovery actions. Reachable depuis EC2
    via Tailscale local (l'app radar tourne sur la même instance).
    """
    import os
    import httpx

    monitor_url = os.getenv(
        "MONITOR_STATUS_URL", "http://100.103.107.75:8090/status.json"
    )
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(monitor_url)
            r.raise_for_status()
            return r.json()
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Monitor unreachable: {type(e).__name__}",
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Monitor returned {e.response.status_code}",
        )


@app.get("/api/shadow/v2_core_long/setups.csv")
async def api_shadow_setups_csv(
    since: str | None = None,
    until: str | None = None,
    system_id: str | None = None,
    outcome: str | None = None,
    limit: int = 5000,
    ctx: AuthContext = Depends(auth_context),
):
    """Export CSV des shadow setups (téléchargement).

    Query params identiques à /setups, sauf limit max 5000.
    Headers : detected_at, bar_timestamp, system_id, pair, pattern, direction,
    entry_price, stop_loss, take_profit_1, risk_pct, rr, sizing_position_eur,
    outcome, exit_at, exit_price, pnl_pct_net, pnl_eur, macro_features_json
    """
    import csv
    import io
    from datetime import datetime as _dt
    from fastapi.responses import StreamingResponse
    from backend.services.shadow_v2_core_long import list_setups

    def _parse(s: str | None):
        if not s:
            return None
        try:
            return _dt.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return _dt.strptime(s, "%Y-%m-%d")

    rows = list_setups(
        since=_parse(since), until=_parse(until),
        system_id=system_id, outcome=outcome,
        limit=min(limit, 5000),
    )

    columns = [
        "detected_at", "bar_timestamp", "system_id", "pair", "timeframe",
        "direction", "pattern", "entry_price", "stop_loss",
        "take_profit_1", "take_profit_2", "risk_pct", "rr",
        "sizing_capital_eur", "sizing_risk_pct", "sizing_position_eur",
        "sizing_max_loss_eur", "outcome", "exit_at", "exit_price",
        "pnl_pct_net", "pnl_eur", "macro_features_json",
    ]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, "") for k in columns})

    today = _dt.now(tz=None).strftime("%Y-%m-%d")
    filename = f"shadow_setups_{today}.csv"
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\""},
    )


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket pour notifications temps réel des signaux.

    Auth : cookie de session > Basic Auth. Si aucun utilisateur n'est
    configuré (AUTH_USERS vide), la WS reste ouverte comme avant.
    """
    user: str = "anonymous"
    if AUTH_USERS:
        from backend.auth import _basic_auth_user, validate_session
        validated = validate_session(websocket.cookies.get(SESSION_COOKIE))
        if not validated:
            validated = _basic_auth_user(websocket.headers.get("authorization"))
        if not validated:
            await websocket.close(code=1008)  # Policy Violation
            return
        user = validated
    await websocket.accept()
    register_client(websocket, user=user)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        unregister_client(websocket)
    except Exception:
        unregister_client(websocket)
