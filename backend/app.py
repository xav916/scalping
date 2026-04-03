"""FastAPI application for the Scalping Decision Tool."""

import asyncio
import hashlib
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from config.settings import AUTH_USERS

from backend.services.notification_service import (
    get_signal_history,
    register_client,
    unregister_client,
)
from backend.services.scheduler import (
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
    yield
    stop_scheduler()
    logger.info("Scalping Decision Tool stopped.")


app = FastAPI(
    title="Scalping Radar",
    description="Scalping decision tool - market analysis and signal detection",
    version="1.0.0",
    lifespan=lifespan,
)

# ─── Authentification HTTP Basic ────────────────────────────────────
security = HTTPBasic()


def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    """Vérifie le login/mot de passe parmi les utilisateurs configurés."""
    if not AUTH_USERS:
        return  # Pas d'auth configurée = accès libre
    expected_password = AUTH_USERS.get(credentials.username)
    if expected_password is None or not secrets.compare_digest(credentials.password, expected_password):
        raise HTTPException(
            status_code=401,
            detail="Identifiants incorrects",
            headers={"WWW-Authenticate": "Basic"},
        )


# Serve static files
app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")


@app.get("/")
async def index(credentials: HTTPBasicCredentials = Depends(verify_credentials)):
    """Serve the main dashboard page."""
    return FileResponse(str(FRONTEND_DIR / "index.html"))


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


@app.post("/api/refresh")
async def refresh_analysis(_=Depends(verify_credentials)):
    """Manually trigger a new analysis cycle."""
    asyncio.create_task(run_analysis_cycle())
    return {"status": "ok", "message": "Analysis refresh triggered"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time signal notifications."""
    await websocket.accept()
    register_client(websocket)
    try:
        while True:
            # Keep connection alive, handle client messages
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        unregister_client(websocket)
    except Exception:
        unregister_client(websocket)
