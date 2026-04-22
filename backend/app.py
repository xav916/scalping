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

from backend.auth import (
    SESSION_COOKIE,
    authenticate,
    login_and_set_cookie,
    logout_and_clear_cookie,
)
from config.settings import AUTH_USERS, display_name_for

from backend.services import (
    backtest_service,
    indicators,
    trade_log_service,
    twelvedata_ws,
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

# ─── Authentification (session cookie prioritaire, Basic Auth en fallback) ───
# Implémentation dans backend/auth.py. Cette fonction reste un alias pour
# minimiser le bruit sur les routes existantes.
def verify_credentials(request: Request) -> str:
    return authenticate(request)


# ─── Routes de login/logout ─────────────────────────────────────────
@app.post("/api/login")
async def api_login(payload: dict, response: Response):
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


@app.get("/login", include_in_schema=False)
async def login_page(request: Request):
    """Sert la page de login. Si déjà authentifié, redirige vers /."""
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        from backend.auth import validate_session
        if validate_session(sid):
            return RedirectResponse("/", status_code=303)
    return FileResponse(str(FRONTEND_DIR / "login.html"))


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
    _=Depends(verify_credentials),
):
    """Agrégat de performance des trades auto (is_auto=1, CLOSED).

    Query params :
    - since : ISO date pour filtrer les trades (ex: 2026-04-20T21:14:00+00:00).

    Retourne des buckets (score, asset_class, direction, risk_regime, session,
    pair) pour éclairer les décisions de remontée de seuil et d'activation
    du veto macro.
    """
    from backend.services import insights_service
    return insights_service.get_performance(since_iso=since)


@app.get("/api/insights/period-stats")
async def api_insights_period_stats(
    period: str | None = None,
    since: str | None = None,
    until: str | None = None,
    _=Depends(verify_credentials),
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
        return insights_service.get_period_stats_range(since=since, until=until)

    period = period or "day"
    if period not in {"day", "week", "month", "year", "all"}:
        raise HTTPException(status_code=400, detail="period invalide (day|week|month|year|all)")
    return insights_service.get_period_stats(period=period)


@app.get("/api/insights/equity-curve")
async def api_insights_equity_curve(
    since: str | None = None,
    _=Depends(verify_credentials),
):
    """Série temporelle du PnL cumulé (auto trades CLOSED, ordre chronologique).

    Query params :
    - since : ISO date pour filtrer (typiquement POST_FIX_CUTOFF).

    Retourne {points: [{closed_at, pnl, cumulative_pnl, trade_num, pair, direction}],
              total_trades, final_pnl, since}.
    """
    from backend.services import insights_service
    return insights_service.get_equity_curve(since_iso=since)


@app.get("/api/insights/pnl-buckets")
async def api_insights_pnl_buckets(
    since: str,
    until: str,
    granularity: str = "auto",
    _=Depends(verify_credentials),
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
    try:
        return insights_service.get_pnl_buckets(since=since, until=until, granularity=granularity)
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
async def risk_dashboard(user: str = Depends(verify_credentials)):
    """Risque cumule sur les positions ouvertes."""
    open_trades = trade_log_service.list_trades(status="OPEN", user=user)
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
async def equity_curve(user: str = Depends(verify_credentials)):
    """Courbe d'equity quotidienne calculee depuis l'historique des trades."""
    from collections import defaultdict
    from config.settings import TRADING_CAPITAL
    trades = trade_log_service.list_trades(status="CLOSED", limit=1000, user=user)
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
async def trades_csv(user: str = Depends(verify_credentials)):
    """Export CSV de l'historique des trades de l'utilisateur."""
    import io
    import csv
    from fastapi.responses import StreamingResponse
    trades = trade_log_service.list_trades(limit=10000, user=user)
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
async def stats_combos(user: str = Depends(verify_credentials)):
    """Win rate par combinaison (pattern + paire). Necessite un historique
    de trades clotures pour etre pertinent."""
    from collections import defaultdict
    trades = trade_log_service.list_trades(status="CLOSED", limit=1000, user=user)
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
async def stats_mistakes(user: str = Depends(verify_credentials)):
    """Detection d'erreurs : trades pris sans checklist + trades sans SL/TP poses."""
    trades = trade_log_service.list_trades(limit=500, user=user)
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


# Serve static files
app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")

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
    """Serve the main dashboard page. Redirige vers /login si pas authentifié
    (plus agréable qu'un prompt Basic Auth sur la route principale)."""
    try:
        authenticate(request)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    return FileResponse(str(FRONTEND_DIR / "index.html"))


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
    """Disallow indexation (l'app est derriere Basic Auth)."""
    return FileResponse(str(FRONTEND_DIR / "robots.txt"), media_type="text/plain")


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


@app.get("/mobile")
async def mobile_view(_=Depends(verify_credentials)):
    """Vue mobile-first focalisee sur les setups TAKE uniquement."""
    return FileResponse(str(FRONTEND_DIR / "mobile.html"))


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
async def list_trades(status: str | None = None, limit: int = 100, user: str = Depends(verify_credentials)):
    return trade_log_service.list_trades(status=status, limit=limit, user=user)


@app.get("/api/cockpit")
async def cockpit(user: str = Depends(verify_credentials)):
    """Snapshot consolidé pour la homepage "tour de contrôle".

    Regroupe en un seul appel : trades actifs (PnL temps réel), setups en
    attente, stats du jour, santé système, contexte macro, events imminents
    et alertes. Voir backend/services/cockpit_service.py.
    """
    from backend.services.cockpit_service import build_cockpit
    return await build_cockpit(user)


@app.get("/api/analytics")
async def analytics(_=Depends(verify_credentials)):
    """Breakdowns du win rate par features : pair, hour, pattern, confidence,
    asset_class, risk_regime. Inclut la qualité d'exécution (slippage,
    close_reason). Voir backend/services/analytics_service.py.

    Utile pour piloter le modèle : quels instruments retirer, quelles
    heures éviter, si le confidence_score est calibré."""
    from backend.services.analytics_service import build_analytics
    return build_analytics()


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
async def daily_status(user: str = Depends(verify_credentials)):
    """Statut journalier : PnL, nb trades, mode silencieux."""
    status = trade_log_service.get_daily_status(user=user)
    open_trades = trade_log_service.list_trades(status="OPEN", user=user)
    status["open_trades"] = open_trades
    status["username"] = user
    status["display_name"] = display_name_for(user)
    return status


@app.post("/api/silent-mode")
async def toggle_silent_mode(payload: dict, user: str = Depends(verify_credentials)):
    """Active/desactive le mode silencieux pour l'utilisateur connecte."""
    enabled = bool(payload.get("enabled", False))
    trade_log_service.set_manual_silent(user, enabled)
    return {"silent_mode": enabled, "user": user}


@app.get("/api/backtest/stats")
async def get_backtest_stats(_=Depends(verify_credentials)):
    """Statistiques globales des signaux backtestes."""
    return backtest_service.get_stats()


@app.get("/api/backtest/trades")
async def get_backtest_trades(limit: int = 50, _=Depends(verify_credentials)):
    """Historique des trades backtestes."""
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
