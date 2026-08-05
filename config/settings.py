"""Application settings and configuration."""

import os
from dotenv import load_dotenv

load_dotenv()

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Authentification (laisser vide = pas d'auth)
# Format multi-utilisateurs : "user1:pass1,user2:pass2"
AUTH_USERNAME = os.getenv("AUTH_USERNAME", "")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "")
AUTH_USERS_RAW = os.getenv("AUTH_USERS", "")

# Construire le dict {username: password}
AUTH_USERS: dict[str, str] = {}
if AUTH_USERS_RAW:
    for entry in AUTH_USERS_RAW.split(","):
        entry = entry.strip()
        if ":" in entry:
            u, p = entry.rsplit(":", 1)  # rsplit pour gerer les emails dans le username
            AUTH_USERS[u.strip()] = p.strip()
# Fallback : ancien format simple AUTH_USERNAME/AUTH_PASSWORD
if AUTH_USERNAME and AUTH_PASSWORD and AUTH_USERNAME not in AUTH_USERS:
    AUTH_USERS[AUTH_USERNAME] = AUTH_PASSWORD

# Mapping username -> nom affiche dans l'UI (format: "user1:Xav,user2:Ced")
# Utile quand les usernames sont des emails et qu'on veut un prenom a la place.
_AUTH_DISPLAY_NAMES_RAW = os.getenv("AUTH_DISPLAY_NAMES", "")
AUTH_DISPLAY_NAMES: dict[str, str] = {}
if _AUTH_DISPLAY_NAMES_RAW:
    for entry in _AUTH_DISPLAY_NAMES_RAW.split(","):
        entry = entry.strip()
        if ":" in entry:
            u, name = entry.rsplit(":", 1)
            AUTH_DISPLAY_NAMES[u.strip()] = name.strip()


def display_name_for(username: str) -> str:
    """Retourne le nom affichable : mapping explicite, ou partie avant @ si email, sinon username."""
    if username in AUTH_DISPLAY_NAMES:
        return AUTH_DISPLAY_NAMES[username]
    if "@" in username:
        return username.split("@", 1)[0]
    return username

# Scraping intervals (seconds)
MATAF_POLL_INTERVAL = int(os.getenv("MATAF_POLL_INTERVAL", "300"))  # 5 min
FOREXFACTORY_POLL_INTERVAL = int(os.getenv("FOREXFACTORY_POLL_INTERVAL", "600"))  # 10 min

# Analysis thresholds
VOLATILITY_THRESHOLD_HIGH = float(os.getenv("VOLATILITY_THRESHOLD_HIGH", "1.5"))  # multiplier vs average
VOLATILITY_THRESHOLD_MEDIUM = float(os.getenv("VOLATILITY_THRESHOLD_MEDIUM", "1.2"))
TREND_STRENGTH_MIN = float(os.getenv("TREND_STRENGTH_MIN", "0.6"))  # 0-1 scale

# Currency pairs to monitor
WATCHED_PAIRS = os.getenv(
    "WATCHED_PAIRS",
    "XAU/USD,EUR/USD,GBP/USD,USD/JPY,EUR/GBP,USD/CHF,AUD/USD,USD/CAD,EUR/JPY,GBP/JPY,"
    "BTC/USD,ETH/USD,XAG/USD,WTI/USD,SPX,NDX"
).split(",")

# Asset class per pair (used for UI filtering, scoring mapping, bridge routing).
# "forex" = forex majors/crosses
# "metal" = precious metals (XAU, XAG)
# "crypto" = crypto (BTC, ETH, ...)
# "energy" = oil, gas
# "equity_index" = stock indices (SPX, NDX, DAX, ...)
ASSET_CLASS_OVERRIDES_RAW = os.getenv("ASSET_CLASS_OVERRIDES", "")
_asset_overrides: dict[str, str] = {}
if ASSET_CLASS_OVERRIDES_RAW:
    for entry in ASSET_CLASS_OVERRIDES_RAW.split(","):
        entry = entry.strip()
        if ":" in entry:
            k, v = entry.split(":", 1)
            _asset_overrides[k.strip().upper()] = v.strip().lower()


def asset_class_for(pair: str) -> str:
    """Return the asset class for a pair using known patterns + overrides."""
    p = pair.upper()
    if p in _asset_overrides:
        return _asset_overrides[p]
    if p.startswith(("BTC", "ETH", "LTC", "XRP", "SOL", "ADA", "DOGE", "BCH", "DOT")) or p.endswith(("/BTC", "/ETH")):
        return "crypto"
    if p.startswith(("XAU", "XAG", "XPT", "XPD")):
        return "metal"
    if p.startswith(("WTI", "BRENT", "XTI", "XBR", "NGAS", "NATGAS")):
        return "energy"
    if p in {"SPX", "NDX", "DJI", "RUT", "DAX", "N225", "NIKKEI", "FTSE", "CAC40", "UK100", "US30", "US500", "NAS100", "DE40", "EU50", "JP225"}:
        return "equity_index"
    # US individual equities (NYSE/NASDAQ CFDs via IC Markets, format broker AAPL.NAS)
    if p in {"AAPL", "TSLA", "NVDA", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "AMD", "NFLX", "COIN", "PLTR", "SHOP", "JPM", "V", "MA", "DIS", "WMT"}:
        return "equity"
    # default = forex
    return "forex"

# Source de prix : "mt5" (MetaTrader 5 temps réel) ou "twelvedata" (polling)
PRICE_SOURCE = os.getenv("PRICE_SOURCE", "twelvedata").lower()

# Twelve Data API (gratuit: 8 req/min, 800/jour)
# Inscription: https://twelvedata.com/register
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")

# WebSocket Twelve Data (temps reel tick <1s, necessite plan Grow ou plus)
# Grow: 2 symboles max en WebSocket simultane. Pro: jusqu'a 80 symboles.
TWELVEDATA_WS_ENABLED = os.getenv("TWELVEDATA_WS_ENABLED", "false").lower() in ("1", "true", "yes")
TWELVEDATA_WS_MAX_SYMBOLS = int(os.getenv("TWELVEDATA_WS_MAX_SYMBOLS", "2"))

# Telegram bot (notifications mobiles des signaux)
# Setup:
#   1. Parler a @BotFather sur Telegram, /newbot, recuperer le token
#   2. Parler a votre nouveau bot (envoyer "bonjour"), puis ouvrir
#      https://api.telegram.org/bot<TOKEN>/getUpdates pour recuperer chat_id
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Bot Telegram dédié infra (canal séparé du bot user-facing scalping radar).
# Utilisé par /api/admin/notify-infra-telegram pour relayer les alertes
# système (verdict counterfactual, monitoring, etc.) au bot @xav_scalping_infra_bot.
INFRA_TELEGRAM_BOT_TOKEN = os.getenv("INFRA_TELEGRAM_BOT_TOKEN", "")
INFRA_TELEGRAM_CHAT_ID = os.getenv("INFRA_TELEGRAM_CHAT_ID", "")

# Canal Telegram dédié aux notifs business (nouveau client payant, churn,
# upgrades). Sépare le bruit infra (bridge down, EA crash) du business.
# Si vide, les notifs sales sont skip silencieusement.
SALES_TELEGRAM_BOT_TOKEN = os.getenv("SALES_TELEGRAM_BOT_TOKEN", "")
SALES_TELEGRAM_CHAT_ID = os.getenv("SALES_TELEGRAM_CHAT_ID", "")
# Secret du webhook Telegram sales bot. Telegram envoie ce header
# `X-Telegram-Bot-Api-Secret-Token` sur chaque POST → l'endpoint webhook le
# compare en compare_digest. Si vide, le webhook accepte tout (mode dev).
TELEGRAM_SALES_WEBHOOK_SECRET = os.getenv("TELEGRAM_SALES_WEBHOOK_SECRET", "")

# ─── Bridge MT5 (auto-exec sur MetaTrader 5 desktop local) ──────────
# URL du bridge MT5 accessible via Tailscale (ex: http://100.122.188.8:8787).
# Le bridge doit tourner sur le PC Windows de l'utilisateur.
MT5_BRIDGE_URL = os.getenv("MT5_BRIDGE_URL", "")
MT5_BRIDGE_API_KEY = os.getenv("MT5_BRIDGE_API_KEY", "")
# Activation globale : si false, le radar détecte les setups mais NE POUSSE
# RIEN au bridge. true = push auto (bridge en paper par défaut → sans risque
# financier tant que le bridge est en PAPER_MODE).
MT5_BRIDGE_ENABLED = os.getenv("MT5_BRIDGE_ENABLED", "false").lower() in ("1", "true", "yes", "on")
# ─── Bridge MT5 LIVE (destination admin parallèle) ──────────────────
# Permet de pousser les setups vers UN SECOND bridge en plus du Demo (admin_legacy).
# Cas d'usage : Demo Pepperstone continue + Live IC Markets sur un nouveau MT5
# terminal + bridge.py port 8788. Les deux destinations sont admin (user_id=None),
# donc poussées en HTTP synchrone (pas via la queue EA des users Premium).
# Driver 2026-06-12 : Pepperstone bloqué par AMF (MT5 inaccessible retail FR),
# pivot IC Markets Cyprus en parallèle du Demo Pepperstone.
MT5_BRIDGE_LIVE_ENABLED = os.getenv("MT5_BRIDGE_LIVE_ENABLED", "false").lower() in ("1", "true", "yes", "on")
MT5_BRIDGE_LIVE_URL = os.getenv("MT5_BRIDGE_LIVE_URL", "")
MT5_BRIDGE_LIVE_API_KEY = os.getenv("MT5_BRIDGE_LIVE_API_KEY", "")
# Le min_confidence Live peut être plus strict que Demo pour limiter le risque
# capital réel (default = même valeur que Demo = MT5_BRIDGE_MIN_CONFIDENCE).
MT5_BRIDGE_LIVE_MIN_CONFIDENCE = float(os.getenv("MT5_BRIDGE_LIVE_MIN_CONFIDENCE", os.getenv("MT5_BRIDGE_MIN_CONFIDENCE", "90")))
# Asset classes acceptées pour le bridge Live (IC Markets Cyprus supporte tout
# par défaut). Par défaut = même que Demo si non set.
MT5_BRIDGE_LIVE_ALLOWED_ASSET_CLASSES = [
    c.strip().lower()
    for c in os.getenv("MT5_BRIDGE_LIVE_ALLOWED_ASSET_CLASSES",
                       os.getenv("MT5_BRIDGE_ALLOWED_ASSET_CLASSES", "forex,metal")).split(",")
    if c.strip()
]
# Pairs SUPPLÉMENTAIRES autorisées sur admin_live en plus de _STAR_PAIRS_SET.
# Cas d'usage 2026-06-12 : Live IC Markets €100 capital trop petit pour XAU
# (margin €130) et ETH (margin €80+) à 0.01 lot. Élargir Live aux forex majors
# où 0.01 lot ne consomme que €30 de margin. Demo Pepperstone garde stars-only.
# Format CSV : "EUR/USD,GBP/USD,USD/JPY". Vide = pas d'extension (stars-only).
MT5_BRIDGE_LIVE_EXTRA_PAIRS = frozenset(
    p.strip().upper() for p in os.getenv("MT5_BRIDGE_LIVE_EXTRA_PAIRS", "").split(",") if p.strip()
)
# Symbol map propre au bridge Live IC Markets (indépendant de MT5_SYMBOL_MAP
# global utilisé par le flux MT5 direct legacy). Chez IC Markets Cyprus le CFD
# WTI s'appelle XTIUSD (pas SpotCrude comme Pepperstone). Format identique à
# MT5_SYMBOL_MAP : "WTI/USD:XTIUSD,SPX:US500,...". Vide = pas de mapping,
# admin_live envoie la pair Scalping Radar brute au bridge.
_MT5_BRIDGE_LIVE_SYMBOL_MAP_RAW = os.getenv("MT5_BRIDGE_LIVE_SYMBOL_MAP", "")
MT5_BRIDGE_LIVE_SYMBOL_MAP: dict[str, str] = {}
if _MT5_BRIDGE_LIVE_SYMBOL_MAP_RAW:
    for entry in _MT5_BRIDGE_LIVE_SYMBOL_MAP_RAW.split(","):
        entry = entry.strip()
        if ":" in entry:
            k, v = entry.split(":", 1)
            MT5_BRIDGE_LIVE_SYMBOL_MAP[k.strip()] = v.strip()

# ─── Binance Futures bridge (Phase 2 R&D Palier 2 — 2026-06-17) ───────
# Routing destination parallèle aux bridges MT5 pour cryptos. En testnet :
# zéro coût, validation comparative MT5 Demo vs Binance USDⓈ-M sur fills
# et slippage. Le binance-bridge tourne sur EC2 port 8789 (systemd-run
# binance-bridge-rd.service), watcher SL/TP émulé côté bridge car le
# testnet Binance rejette STOP_MARKET via /fapi/v1/order (-4120).
BINANCE_BRIDGE_ENABLED = os.getenv("BINANCE_BRIDGE_ENABLED", "false").lower() in ("1", "true", "yes", "on")
BINANCE_BRIDGE_URL = os.getenv("BINANCE_BRIDGE_URL", "")
BINANCE_BRIDGE_API_KEY = os.getenv("BINANCE_BRIDGE_API_KEY", "")
BINANCE_BRIDGE_MIN_CONFIDENCE = float(os.getenv("BINANCE_BRIDGE_MIN_CONFIDENCE", "50"))
BINANCE_BRIDGE_LEVERAGE = int(os.getenv("BINANCE_BRIDGE_LEVERAGE", "5"))
# Bougies Binance Futures natives (gratuit + illimité) en remplacement de
# Twelve Data pour les paires crypto uniquement. Forex/métaux/WTI/indices
# restent sur Twelve Data. Feature flag pour rollback instantané. Cf.
# project_binance_phase2_chantier1_native_klines_2026_06_18.md
BINANCE_KLINES_ENABLED = os.getenv("BINANCE_KLINES_ENABLED", "false").lower() in ("1", "true", "yes", "on")
# Phase 2 Palier 2 chantier #2 (2026-06-18) : funding rate Binance comme
# filtre contrarien soft sur les setups crypto. Multiplier 0.85 (= veto soft)
# si funding extrême + direction surcrowdée. Feature flag pour rollback.
BINANCE_FUNDING_SCORING_ENABLED = os.getenv("BINANCE_FUNDING_SCORING_ENABLED", "false").lower() in ("1", "true", "yes", "on")
# Chantier #3 (2026-06-18) : LSR Binance comme filtre contrarien soft.
BINANCE_LSR_SCORING_ENABLED = os.getenv("BINANCE_LSR_SCORING_ENABLED", "false").lower() in ("1", "true", "yes", "on")
# Chantier #4 (2026-06-18) : order book depth (spread top-of-book) comme filtre thin market.
BINANCE_ORDERBOOK_SCORING_ENABLED = os.getenv("BINANCE_ORDERBOOK_SCORING_ENABLED", "false").lower() in ("1", "true", "yes", "on")
# Chantier #5 (2026-06-18) : aggressor side / taker buy ratio comme filtre orderflow.
BINANCE_ORDERFLOW_SCORING_ENABLED = os.getenv("BINANCE_ORDERFLOW_SCORING_ENABLED", "false").lower() in ("1", "true", "yes", "on")
# Chantier #6 (2026-06-18) : OI divergence comme filtre squeeze/liquidation 1h.
BINANCE_OI_SCORING_ENABLED = os.getenv("BINANCE_OI_SCORING_ENABLED", "false").lower() in ("1", "true", "yes", "on")
# Tier 2 chantier #14 (2026-06-18) : multi-timeframe alignment (HTF 15m+1h vs setup 5m).
BINANCE_MTF_SCORING_ENABLED = os.getenv("BINANCE_MTF_SCORING_ENABLED", "false").lower() in ("1", "true", "yes", "on")
# P1 (2026-08-03) : Veto calendrier économique pre/post news HIGH impact
# (NFP, CPI, FOMC, ECB, BoE, GDP...). Soft veto ×0.70 si un event HIGH
# est dans ±30 min de now. Filtre par currency impactée par la paire.
# No-op crypto/equity. Cache SQLite economic_events peuplé par refresh hebdo.
ECONOMIC_CALENDAR_VETO_ENABLED = os.getenv("ECONOMIC_CALENDAR_VETO_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# Gap 1 MVP (2026-08-02) : VIX regime veto pour signaux equity/equity_index.
# Multiplicateurs : calme(×1.0) modéré(×0.95) stress(×0.85) panique(×0.70).
# Utilise vix_service.get_current() (cache SQLite 5 min). Best-effort : si VIX
# indisponible, le scoring continue sans modification.
VIX_SCORING_ENABLED = os.getenv("VIX_SCORING_ENABLED", "true").lower() in ("1", "true", "yes", "on")
# P2 (2026-08-03) : Earnings calendar veto — soft veto ×0.60 si earnings dans
# les 24h à venir, ×0.70 si earnings dans les 24h passées. Equity individuel
# uniquement (AAPL/TSLA/NVDA/MSFT/etc.). No-op sur indices/crypto/forex/metal.
# Source : yfinance (pip install yfinance). Cache SQLite 24h dans macro.db.
EARNINGS_VETO_ENABLED = os.getenv("EARNINGS_VETO_ENABLED", "true").lower() in ("1", "true", "yes", "on")
# No-weekend-hold energy (2026-08-03) : bloque nouveaux pushes energy (WTI,
# Brent, NatGas) vendredi après HOUR_UTC. Motif : incident 2026-08-03 →
# 2 WTI Live gardées 3 nuits weekend, gap réouverture dimanche a slippé les
# SL de -4 USD chacun, coût final €20.75 au lieu de €4-5 attendus (gap risk).
# Défaut : vendredi 18h UTC = 20h Paris (marge sécurité vs close forex 22h UTC).
NO_FRIDAY_LATE_OPEN_ENERGY_ENABLED = os.getenv("NO_FRIDAY_LATE_OPEN_ENERGY_ENABLED", "true").lower() in ("1", "true", "yes", "on")
NO_FRIDAY_LATE_OPEN_ENERGY_HOUR_UTC = int(os.getenv("NO_FRIDAY_LATE_OPEN_ENERGY_HOUR_UTC", "18"))
# Gel de détention longue à travers le week-end (2026-08-05, suivi revue tâche 7) :
# généralise le gel énergie ci-dessus à TOUTE classe d'actif qui ferme (hors
# crypto, marché continu) pour les horizons longs (4h/1j) — une position ouverte
# vendredi soir franchit la clôture et ne peut plus être fermée avant le gap de
# réouverture. Interrupteur dédié et indépendant du gel énergie ci-dessus : les
# deux règles coexistent, se coupent séparément. Défaut activé (comportement
# inchangé au déploiement).
WEEKEND_HOLD_BLOCK_ENABLED = os.getenv("WEEKEND_HOLD_BLOCK_ENABLED", "true").lower() in ("1", "true", "yes", "on")
# Gap 2 (2026-08-02) : Kraken Futures scoring = miroir des 3 features Binance
# (funding, OI, orderbook) pour signaux routés vers admin_kraken. Données natives
# Kraken complémentaires aux 6 features Binance (les 2 sources cumulées, le pire
# veto l'emporte). LSR skip (non exposé par Kraken API publique). Orderflow et
# klines reportés en sprint dédié.
KRAKEN_FUNDING_SCORING_ENABLED = os.getenv("KRAKEN_FUNDING_SCORING_ENABLED", "false").lower() in ("1", "true", "yes", "on")
KRAKEN_OI_SCORING_ENABLED = os.getenv("KRAKEN_OI_SCORING_ENABLED", "false").lower() in ("1", "true", "yes", "on")
KRAKEN_ORDERBOOK_SCORING_ENABLED = os.getenv("KRAKEN_ORDERBOOK_SCORING_ENABLED", "false").lower() in ("1", "true", "yes", "on")
# Kraken Futures bridge (2026-08-02) — perpetuals USD-margined PF_* après
# blocker AMF Binance Futures FR + Bybit UE Spot only + OKX EU MTF format
# non-standard. Kraken Futures régulé Ireland/EU, accessible résidents FR.
# Bridge dédié sur EC2 port 8790 (kraken-bridge.service), auth HMAC-SHA512
# nonce-based. Manqué dans commit 9d685f8, fix 2026-08-02 après deploy.
KRAKEN_BRIDGE_ENABLED = os.getenv("KRAKEN_BRIDGE_ENABLED", "false").lower() in ("1", "true", "yes", "on")
KRAKEN_BRIDGE_URL = os.getenv("KRAKEN_BRIDGE_URL", "")
KRAKEN_BRIDGE_API_KEY = os.getenv("KRAKEN_BRIDGE_API_KEY", "")
KRAKEN_BRIDGE_MIN_CONFIDENCE = float(os.getenv("KRAKEN_BRIDGE_MIN_CONFIDENCE", "60"))
KRAKEN_BRIDGE_LEVERAGE = int(os.getenv("KRAKEN_BRIDGE_LEVERAGE", "5"))
# Kraken Spot bridge (2026-08-02) — trading Spot BTC/ETH sur marché réel
# Long-only, sans levier, watcher SL/TP émulé. Port 8791 par défaut.
KRAKEN_SPOT_BRIDGE_ENABLED = os.getenv("KRAKEN_SPOT_BRIDGE_ENABLED", "false").lower() in ("1", "true", "yes", "on")
KRAKEN_SPOT_BRIDGE_URL = os.getenv("KRAKEN_SPOT_BRIDGE_URL", "")
KRAKEN_SPOT_BRIDGE_API_KEY = os.getenv("KRAKEN_SPOT_BRIDGE_API_KEY", "")
KRAKEN_SPOT_BRIDGE_MIN_CONFIDENCE = float(os.getenv("KRAKEN_SPOT_BRIDGE_MIN_CONFIDENCE", "75"))
KRAKEN_SPOT_BRIDGE_LEVERAGE = int(os.getenv("KRAKEN_SPOT_BRIDGE_LEVERAGE", "1"))  # spot = pas de levier
# Kraken xStocks bridge (2026-08-02) — Voie A. Actions US tokenisées (PF_AAPLXUSD,
# PF_TSLAXUSD...) via même bridge Kraken Futures port 8790, mais destination
# séparée admin_kraken_stocks pour tracking PnL indépendant du crypto. UI Kraken FR
# cache la recherche xStocks mais l'API accepte les ordres (découvert 2026-08-02).
# Risques : Kraken peut couper l'accès, prix decouplés des vrais marchés NYSE.
KRAKEN_STOCKS_BRIDGE_ENABLED = os.getenv("KRAKEN_STOCKS_BRIDGE_ENABLED", "false").lower() in ("1", "true", "yes", "on")
KRAKEN_STOCKS_BRIDGE_URL = os.getenv("KRAKEN_STOCKS_BRIDGE_URL", "")
KRAKEN_STOCKS_BRIDGE_API_KEY = os.getenv("KRAKEN_STOCKS_BRIDGE_API_KEY", "")
KRAKEN_STOCKS_BRIDGE_MIN_CONFIDENCE = float(os.getenv("KRAKEN_STOCKS_BRIDGE_MIN_CONFIDENCE", "75"))
KRAKEN_STOCKS_BRIDGE_LEVERAGE = int(os.getenv("KRAKEN_STOCKS_BRIDGE_LEVERAGE", "5"))
# Paires supplémentaires autorisées globalement (Demo + Live + autres
# destinations multi-tenant) en plus des stars XAU/XAG/WTI/ETH. Sert à
# élargir l'auto-exec aux paires promues manuellement en AUTO_EXEC via
# pair_admission_state sans toucher au filtre _STAR_PAIRS_SET legacy.
# Format CSV : "BTC/USD,SOL/USD,ADA/USD".
MT5_BRIDGE_EXTRA_PAIRS_GLOBAL = frozenset(
    p.strip().upper() for p in os.getenv("MT5_BRIDGE_EXTRA_PAIRS_GLOBAL", "").split(",") if p.strip()
)
# Seuil strict — 90 par défaut. Stricter que le push Telegram (80) : on
# n'auto-trade qu'avec haute conviction.
MT5_BRIDGE_MIN_CONFIDENCE = float(os.getenv("MT5_BRIDGE_MIN_CONFIDENCE", "90"))
# Taille de position par défaut pour l'auto-exec (en lots MT5).
MT5_BRIDGE_LOTS = float(os.getenv("MT5_BRIDGE_LOTS", "0.01"))
# Asset classes the current broker supports for auto-execution.
# MetaQuotes-Demo = forex + metal only. Pepperstone-Demo (migration B) = all classes.
# Comma-separated: forex,metal,crypto,equity_index,energy
MT5_BRIDGE_ALLOWED_ASSET_CLASSES = [
    c.strip().lower()
    for c in os.getenv("MT5_BRIDGE_ALLOWED_ASSET_CLASSES", "forex,metal").split(",")
    if c.strip()
]
# Pairs explicitement bloquées de l'auto-exec bridge même si elles sont dans
# _STAR_PAIRS_SET. Permet de retirer un instrument sans rebuild ni redéploiement.
# Cas d'usage 2026-05-13 : XAG/USD accumule 80% des pertes du portefeuille
# (-783€ sur 76 trades, WR 30%) car V1 ne génère que des setups SHORT sur un
# actif en uptrend. Garde le scoring/Telegram actifs mais bloque l'exec en
# attendant V2 long-only au gate S6 (2026-06-06).
MT5_BRIDGE_BLOCKED_PAIRS = frozenset(
    p.strip().upper() for p in os.getenv("MT5_BRIDGE_BLOCKED_PAIRS", "").split(",") if p.strip()
)
# Pair PnL Regulator : auto-pause par pair quand sum_pnl < seuil sur fenêtre
# glissante. Capture le saignement chronique (cas XAG/USD diffus) invisible
# au watchdog rafale stop_loss_alerts.
# Cf. backend/services/pair_pnl_regulator.py
PAIR_PNL_REGULATOR_ENABLED = os.getenv("PAIR_PNL_REGULATOR_ENABLED", "true").lower() in ("true", "1", "yes")
PAIR_PNL_REGULATOR_WINDOW_TRADES = int(os.getenv("PAIR_PNL_REGULATOR_WINDOW_TRADES", "30"))
PAIR_PNL_REGULATOR_MIN_SAMPLE = int(os.getenv("PAIR_PNL_REGULATOR_MIN_SAMPLE", "10"))
PAIR_PNL_REGULATOR_PAUSE_THRESHOLD_PCT = float(os.getenv("PAIR_PNL_REGULATOR_PAUSE_THRESHOLD_PCT", "-3.0"))
PAIR_PNL_REGULATOR_PAUSE_DURATION_DAYS = int(os.getenv("PAIR_PNL_REGULATOR_PAUSE_DURATION_DAYS", "14"))

# Circuit breaker démotions PAC : bloque les auto-demotes si trop de demotions
# dans une fenêtre glissante. Anti-cascade conçu suite à l'observation du
# 2026-06-07/08 (17 demotions auto en 48h). Quand le seuil est atteint, les
# auto-demotes sont gelées jusqu'à ce que le compteur retombe sous le seuil.
# Une notification Telegram user+infra est envoyée à chaque blocage.
PAC_CIRCUIT_BREAKER_ENABLED = os.getenv("PAC_CIRCUIT_BREAKER_ENABLED", "true").lower() in ("true", "1", "yes")
PAC_CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("PAC_CIRCUIT_BREAKER_THRESHOLD", "5"))
PAC_CIRCUIT_BREAKER_WINDOW_DAYS = int(os.getenv("PAC_CIRCUIT_BREAKER_WINDOW_DAYS", "7"))

# Délai minimum (jours) en état TELEGRAM avant promotion auto vers AUTO_EXEC.
# Restaure le palier loss-averse asymétrique du design d'origine : la première
# promotion automatique (OBSERVED → TELEGRAM) capture les signaux user-facing,
# puis seule la stabilité prolongée déclenche le passage AUTO_EXEC sans humain.
# Default 7j ≈ 1 cycle hebdo macro complet.
PAC_TELEGRAM_TO_AUTOEXEC_DAYS = int(os.getenv("PAC_TELEGRAM_TO_AUTOEXEC_DAYS", "7"))

# Nombre minimum de trades RÉELS (personal_trades / ea_closed_trades, argent
# effectivement engagé) requis pour qu'une transition automatique d'admission
# (promotion OU rétrogradation) soit autorisée. En dessous de ce seuil, le
# score est jugé INDÉCIDABLE — cf. `pair_admission_controller.STATE_INDETERMINATE`
# — et `evaluate_pair` / `check_and_regulate` ne transitionnent rien, quel que
# soit le résultat calculé sur l'échantillon complété par des signaux simulés.
#
# ⚠️ Avant le 2026-08-05, ce plancher n'existait pas (= 0) : une pair sans
# aucun trade réel pouvait être promue OU rétrogradée sur un échantillon
# 100 % simulé. C'est ce qui a verrouillé 28 pairs en DEMOTED sur des
# métriques mathématiquement impossibles (jusqu'à −251 % de capital sur une
# fenêtre de 30, cf. bug de déduplication shadow corrigé le 2026-08-04).
#
# Défaut = 30, aligné sur la fenêtre d'évaluation (`PROMOTE_MIN_SAMPLE` dans
# pair_admission_controller.py) : zéro tolérance à la contamination simulée —
# une décision qui engage ou retire l'accès à de l'argent réel exige une
# fenêtre 100 % réelle. Une analyse de puissance du 2026-08-05 montre qu'à
# n=30 seul un écart ≥ 0,44 R est détectable (6 à 24× le plancher de
# rentabilité des routes disponibles) : 30 est déjà un seuil faible pour
# discriminer quoi que ce soit — en dessous, l'échantillon ne mesure plus
# rien d'utile à la décision.
#
# PAC_MIN_REAL_TRADES=0 restaure explicitement le comportement antérieur au
# 2026-08-05 (permissif : complète toujours avec des signaux simulés, aucun
# garde-fou de fraîcheur de données).
PAC_MIN_REAL_TRADES = int(os.getenv("PAC_MIN_REAL_TRADES", "30"))

# ─── Retour de pause : délai + comparaison inter-paires (2026-08-05) ─────
#
# Jusqu'ici, `evaluate_pair` rendait l'argent réel à une pair PAUSED après un
# simple délai écoulé (14j codé en dur), sans aucune condition de score — le
# `score` calculé était enregistré en snapshot mais jamais consulté pour cette
# décision précise. Une pair mise en pause pour avoir perdu > 3% du capital
# ressortait donc automatiquement, sans preuve qu'elle méritait cette confiance.
#
# Décision d'architecture (Xavier, 2026-08-05) : le retour est désormais
# conditionné à « la pair fait-elle mieux que la moyenne des autres pairs de
# la MÊME CLASSE D'ACTIF ? » — une comparaison ENTRE PAIRES, PAS un tirage
# réellement aléatoire (cf. `pair_admission_controller` section « Retour de
# pause » pour la mise en garde complète : condition nécessaire, jamais
# suffisante) —, pas à un seuil de rentabilité absolu. Les seuils absolus
# (PROMOTE_MIN_PF, PROMOTE_MIN_WR_PCT) sont franchis par des entrées VRAIMENT
# prises au hasard dans un marché haussier (jusqu'à +0.216 R/trade mesuré sur
# des actions US 2021-2026 — ceci est une mesure distincte, contre une VRAIE
# entrée aléatoire), donc ne discriminent pas une vraie compétence d'une
# dérive de marché. La porte de coût (frais mesurés) reste seule responsable
# de la question de rentabilité — deux questions distinctes, deux mécanismes.

# Délai de refroidissement avant réévaluation d'une pair PAUSED. Anciennement
# 14 codé en dur dans `pair_admission_controller.evaluate_pair` — même valeur
# par défaut, désormais un réglage.
PAC_PAUSE_COOLOFF_DAYS = int(os.getenv("PAC_PAUSE_COOLOFF_DAYS", "14"))

# Taille de bloc (en positions consécutives du domaine trié par temps) du
# bootstrap par blocs apparié — cf. `backend.services.random_entry_control`.
# Défaut aligné sur celui du module (10).
PAC_PEER_CONTROL_BLOCK_SIZE = int(os.getenv("PAC_PEER_CONTROL_BLOCK_SIZE", "10"))

# Nombre de tirages bootstrap. Le défaut du module est 2000 (aligné sur les
# rapports source) ; ici 1000 par défaut — compromis coût/précision explicite
# pour un contrôle qui tourne dans `evaluate_pair`, potentiellement pour
# plusieurs pairs à chaque cycle planifié (60 min). Diviser n_boot par 2
# double approximativement l'instabilité de l'IC d'un run à l'autre (pas son
# exactitude en espérance) et divise le temps de calcul par ~2. Combiné à la
# mise en cache (`PAC_PEER_CONTROL_CACHE_HOURS`), le coût réel par cycle
# planifié reste marginal — voir le rapport de la tâche.
PAC_PEER_CONTROL_N_BOOT = int(os.getenv("PAC_PEER_CONTROL_N_BOOT", "1000"))

# Nombre minimum de blocs dans le domaine pour qu'un bootstrap soit jugé
# fiable (cf. `min_domain_blocks` de `paired_block_bootstrap_delta`). Défaut
# aligné sur celui du module (3). Le domaine est désormais restreint à la
# classe d'actif de la pair testée (cf. `pair_admission_controller.
# _build_peer_control_populations`) : ce seuil est donc mécaniquement plus
# dur à atteindre pour les classes à faible effectif (ex. `energy` = une
# seule pair par défaut) — voir le rapport de la tâche pour l'effet mesuré
# classe par classe, et le commentaire de `_build_peer_control_populations`
# pour le cas structurel d'une classe mono-pair (jamais tranchable en
# faveur de la pair, quelle que soit la quantité de données).
PAC_PEER_CONTROL_MIN_DOMAIN_BLOCKS = int(os.getenv("PAC_PEER_CONTROL_MIN_DOMAIN_BLOCKS", "3"))

# Graine du bootstrap — reproductibilité d'un cycle à l'autre pour une même
# fenêtre de données (cf. `random_entry_control`, jamais l'état global de
# `random`).
PAC_PEER_CONTROL_SEED = int(os.getenv("PAC_PEER_CONTROL_SEED", "0"))

# Durée (heures) pendant laquelle un résultat de contrôle par comparaison
# inter-paires est réutilisé sans recalcul pour un (pair, direction) donné.
# `evaluate_pair` tourne sur tout l'univers à chaque cycle planifié (60 min) ;
# sans ce cache, une pair PAUSED restée éligible (délai écoulé, disjoncteur
# non déclenché) relancerait le bootstrap à CHAQUE cycle tant qu'elle reste
# PAUSED. Défaut 6h = au plus 4 calculs/jour par pair éligible au lieu de 24.
PAC_PEER_CONTROL_CACHE_HOURS = float(os.getenv("PAC_PEER_CONTROL_CACHE_HOURS", "6"))
# Cap par pair : N positions max SIMULTANÉMENT sur la même paire. Forcé
# de diversifier, évite la concentration aveugle (ex: 4 XAU/USD ouverts
# qui tombent ensemble sur un mouvement défavorable).
#
# Dict JSON par asset class. Surchargeable via env MT5_BRIDGE_MAX_POSITIONS_PER_PAIR.
MT5_BRIDGE_MAX_POSITIONS_PER_PAIR_DEFAULT = {
    "forex": 2,
    "metal": 2,
    "equity_index": 1,
    "equity": 1,
    "crypto": 1,
    "energy": 1,
}
try:
    import json as _json_maxpp
    _raw_mpp = os.getenv("MT5_BRIDGE_MAX_POSITIONS_PER_PAIR", "")
    MT5_BRIDGE_MAX_POSITIONS_PER_PAIR = (
        _json_maxpp.loads(_raw_mpp) if _raw_mpp else MT5_BRIDGE_MAX_POSITIONS_PER_PAIR_DEFAULT
    )
except (ValueError, _json_maxpp.JSONDecodeError):
    MT5_BRIDGE_MAX_POSITIONS_PER_PAIR = MT5_BRIDGE_MAX_POSITIONS_PER_PAIR_DEFAULT

# Distance SL minimale en % du prix d'entrée (|entry-sl|/entry*100). Évite
# les setups scalping trop serrés rejetés rc=10016 INVALID_STOPS par MT5.
# Défaut legacy 0.05% = 5.9 pips sur EUR/USD@1.18, 9.4 pips sur EUR/JPY@187.
#
# Problème observé 2026-04-22 : les pairs JPY concentrent 90% des rejections
# sl_too_close (86/96), car leur pip size étant 10× plus grand en valeur
# absolue, leur % de SL équivalent est plus faible. 0.05% sur EUR/JPY = 9.4
# pips, infaisable en scalping ; cible 4-5 pips → rejet systématique.
#
# Seuils par asset class (surchargeable via MT5_BRIDGE_MIN_SL_DISTANCE_PCT_PER_CLASS
# en JSON). MT5_BRIDGE_MIN_SL_DISTANCE_PCT reste le fallback.
MT5_BRIDGE_MIN_SL_DISTANCE_PCT = float(os.getenv("MT5_BRIDGE_MIN_SL_DISTANCE_PCT", "0.05"))

import json as _json_min_sl

_DEFAULT_MIN_SL_DISTANCE_PCT_PER_CLASS = {
    "forex_major": 0.04,    # EUR/USD, GBP/USD, USD/CHF, etc. (5-dp)
    "forex_jpy": 0.02,      # USD/JPY, EUR/JPY, GBP/JPY (3-dp, pip 10x)
    "metal": 0.05,          # XAU/USD, XAG/USD
    "equity_index": 0.03,   # SPX, NDX
    "equity": 0.05,         # AAPL, TSLA, NVDA (US stocks intraday volatile)
    "crypto": 0.15,         # BTC/USD, ETH/USD (volatilité plus large)
    "energy": 0.05,         # WTI, BRENT
}
try:
    _raw = os.getenv("MT5_BRIDGE_MIN_SL_DISTANCE_PCT_PER_CLASS", "")
    MT5_BRIDGE_MIN_SL_DISTANCE_PCT_PER_CLASS = (
        _json_min_sl.loads(_raw) if _raw else _DEFAULT_MIN_SL_DISTANCE_PCT_PER_CLASS
    )
except (ValueError, _json_min_sl.JSONDecodeError):
    MT5_BRIDGE_MIN_SL_DISTANCE_PCT_PER_CLASS = _DEFAULT_MIN_SL_DISTANCE_PCT_PER_CLASS

# Filtres diagnostiques anti-saigne (ajoutés 2026-04-24 après diagnostic
# des 124 trades CLOSED post-fix pipeline). Basés sur buckets qui
# perdent systématiquement — override env si le dataset change.
#
# Format `PAIR:direction` séparé par virgules. `*` matche toutes les pairs.
# Ex : "XAU/USD:buy,GBP/JPY:buy,*:buy" bloque tous les BUY sur metals +
# GBP/JPY + globalement tous les BUY. Direction en lowercase.
_blocked_raw = os.getenv("MT5_BRIDGE_BLOCKED_DIRECTIONS", "")
MT5_BRIDGE_BLOCKED_DIRECTIONS: set[tuple[str, str]] = set()
for _e in _blocked_raw.split(","):
    _e = _e.strip()
    if ":" in _e:
        _pair, _dir = _e.rsplit(":", 1)
        MT5_BRIDGE_BLOCKED_DIRECTIONS.add((_pair.strip().upper(), _dir.strip().lower()))

# Journalisation des drops silencieux (2026-08-04).
#
# Les reason codes privés (préfixe "_") ne laissaient aucune trace : ni push,
# ni rejet, rien. `_not_admitted` bloquait ainsi 85 % des signaux Kraken et
# `_not_a_star` a empêché les Voies A/B de trader une seule action, sans que
# rien ne l'indique. Une destination pouvait rester morte des semaines.
#
# Ils sont désormais comptés, **agrégés par jour** dans `silent_drop_counters`
# (~200 lignes/jour) plutôt qu'une ligne par événement (~30 000/jour).
# Le drapeau permet de couper l'écriture sans redéploiement en cas d'incident.
SILENT_DROPS_LOG_ENABLED = os.getenv(
    "SILENT_DROPS_LOG_ENABLED", "true"
).strip().lower() in ("1", "true", "yes")

# Whitelist de patterns propre à Kraken Futures (2026-08-04).
#
# Non défini  -> hérite de MT5_BRIDGE_ALLOWED_PATTERNS (comportement global)
# Défini vide -> AUCUN filtre pattern sur Kraken
# Défini      -> cette liste, pour Kraken seulement
#
# Motif : Kraken est une destination d'observation à espérance négative
# assumée, où l'on cherche du volume pour valider la chaîne d'exécution.
# L'argent réel MT5 doit lui garder `range_bounce`. Mesure : sans filtre,
# ~113 signaux/jour au lieu de 24, mais espérance brute de +0,190 à +0,100.
_kraken_patterns_raw = os.getenv("KRAKEN_BRIDGE_ALLOWED_PATTERNS")
KRAKEN_BRIDGE_ALLOWED_PATTERNS: frozenset[str] | None = (
    None if _kraken_patterns_raw is None
    else frozenset(p.strip().lower() for p in _kraken_patterns_raw.split(",") if p.strip())
)

# Barème de confiance v2 (2026-08-04). Voir analysis_engine._factors_v2.
#
# v1 comportait 50 points constants sur 100 et comptait la volatilité deux
# fois ; hors échantillon il classait à l'envers (corrélation de rang −0,71
# sur juillet-août contre +0,90 pour v2).
#
# ⚠️ v2 déplace la distribution du score — médiane 57 → 65. Basculer ce
# drapeau SANS remonter les seuils au même moment rendrait le dispatch bien
# plus permissif, en argent réel. Correspondance à sélectivité égale :
#
#     v1 >= 40  ->  v2 >= 42        v1 >= 60  ->  v2 >= 71
#     v1 >= 50  ->  v2 >= 54        v1 >= 70  ->  v2 >= 85
#     v1 >= 55  ->  v2 >= 61        v1 >= 75  ->  v2 >= 87
#
# ⚠️ Ces valeurs incluent les 14 couches multiplicatives appliquées APRÈS le
# barème de base (macro, funding, orderbook, orderflow, VIX, vetos…). Une
# première dérivation les avait omises et donnait 49/64/66/82/86 — trop
# restrictif de 5 à 10 points sur les seuils bas. Le produit des
# multiplicateurs se reconstitue depuis l'historique par
# `confidence_score / somme(5 facteurs de base)`.
CONFIDENCE_SCORE_V2 = os.getenv("CONFIDENCE_SCORE_V2", "false").strip().lower() in ("1", "true", "yes")

# Whitelist de patterns autorisés à l'auto-exec (2026-08-04).
#
# Motif : l'analyse de 100 657 trades suivis en direct montre que le filtre
# de production (`confidence >= 60`) n'apporte rien — +0,030 R/trade contre
# +0,032 sans aucun filtre — alors qu'il écarte 64 % du flux. Le pattern,
# lui, discrimine : `range_bounce_up/down` donne +0,129 R/trade, validé
# hors échantillon (règle figée sur mai-juin, testée sur juillet-août :
# +0,115 R/trade, z = +9,08, positif sur 19 paires / 19 et 4 mois / 4).
#
# À l'inverse `momentum_up` (−0,037), `pin_bar_up` (−0,082) et
# `breakout_up` (−0,088) détruisent de la valeur : tous les patterns hors
# range_bounce totalisent −1 241 R sur la période.
#
# Ce filtre s'ajoute au seuil de confidence, il ne le remplace pas — les
# deux doivent passer. Vide = désactivé (comportement historique).
# Valeurs = `PatternType` en lowercase, séparées par des virgules.
_allowed_patterns_raw = os.getenv("MT5_BRIDGE_ALLOWED_PATTERNS", "")
MT5_BRIDGE_ALLOWED_PATTERNS: frozenset[str] = frozenset(
    p.strip().lower() for p in _allowed_patterns_raw.split(",") if p.strip()
)

# Heures UTC à éviter (format "17-21" inclusif ou liste "17,18,19,20,21").
# Le filtre compare l'heure d'entrée au moment du push, pas au moment où le
# signal a été généré (cohérent avec le timing réel du fill).
_avoid_raw = os.getenv("MT5_BRIDGE_AVOID_HOURS_UTC", "")
MT5_BRIDGE_AVOID_HOURS_UTC: set[int] = set()
if _avoid_raw:
    for _part in _avoid_raw.split(","):
        _part = _part.strip()
        if "-" in _part:
            _a, _b = _part.split("-", 1)
            try:
                MT5_BRIDGE_AVOID_HOURS_UTC.update(range(int(_a), int(_b) + 1))
            except ValueError:
                pass
        elif _part.isdigit():
            MT5_BRIDGE_AVOID_HOURS_UTC.add(int(_part))
# Sync bridge → personal_trades : pull périodique des ordres LIVE depuis le
# bridge pour que les positions auto apparaissent dans le dashboard
# (sections Mes trades, Risque ouvert, Courbe d'équité, Détecteur d'erreurs).
MT5_SYNC_ENABLED = os.getenv("MT5_SYNC_ENABLED", "true").lower() in ("1", "true", "yes", "on")
MT5_SYNC_INTERVAL_SEC = int(os.getenv("MT5_SYNC_INTERVAL_SEC", "60"))
# Utilisateur auquel les trades auto sont attribués dans personal_trades.
# Doit matcher une clé de AUTH_USERS (ou 'anonymous' si auth désactivée).
AUTO_TRADE_USER = os.getenv("AUTO_TRADE_USER", "")
# Confiance minimum (0-100) pour qu'un trade_setup soit poussé sur Telegram.
# Filtre distinct du MIN_CONFIDENCE_SCORE (qui est juste l'affichage).
TELEGRAM_SETUP_MIN_CONFIDENCE = float(os.getenv("TELEGRAM_SETUP_MIN_CONFIDENCE", "80"))
# Verdicts acceptés : liste séparée par virgule (TAKE,WAIT par défaut).
# Par défaut on ne pousse pas les SKIP — trop de bruit.
TELEGRAM_SETUP_VERDICTS = [
    v.strip().upper()
    for v in os.getenv("TELEGRAM_SETUP_VERDICTS", "TAKE,WAIT").split(",")
    if v.strip()
]

# ── Canal long-horizon (2026-08-05) ──────────────────────────────────────
# Le flux 4h/1d obtient son propre canal parce que `TELEGRAM_SETUP_VERDICTS`
# est vide en production : les alertes setup temps-réel sont éteintes et les
# rallumer produirait ~2000 messages/jour. Le flux long-horizon, lui, pèse
# quelques setups par jour.
TELEGRAM_LONG_HORIZON_ENABLED = os.getenv(
    "TELEGRAM_LONG_HORIZON_ENABLED", "true"
).strip().lower() in ("1", "true", "yes", "on")
TELEGRAM_LONG_HORIZON_MIN_CONFIDENCE = float(
    os.getenv("TELEGRAM_LONG_HORIZON_MIN_CONFIDENCE", "61")
)

# Mapping par utilisateur : "user1:chat_id1,user2:chat_id2"
# Si defini, chaque user recoit les signaux sur son propre chat Telegram et
# son mode silencieux est verifie individuellement. Si vide, fallback sur
# TELEGRAM_CHAT_ID (ancien comportement, un seul destinataire).
_TELEGRAM_CHATS_RAW = os.getenv("TELEGRAM_CHATS", "")
TELEGRAM_CHATS: dict[str, str] = {}
if _TELEGRAM_CHATS_RAW:
    for entry in _TELEGRAM_CHATS_RAW.split(","):
        entry = entry.strip()
        if ":" in entry:
            u, cid = entry.rsplit(":", 1)
            TELEGRAM_CHATS[u.strip()] = cid.strip()

# MetaTrader 5 (utilisé uniquement si PRICE_SOURCE=mt5)
# Le terminal MT5 doit être installé et lancé sur la machine.
MT5_LOGIN = os.getenv("MT5_LOGIN", "")  # ex: 62789843
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")  # ex: OANDATMS-MT5
MT5_TERMINAL_PATH = os.getenv("MT5_TERMINAL_PATH", "")  # optionnel, chemin vers terminal64.exe

# Mapping paire Scalping Radar -> symbole MT5 (dépend du broker)
# Format: "XAU/USD:GOLD.pro,EUR/USD:EURUSD.pro,..."
# Pour OANDA TMS : XAU/USD:GOLD.pro, EUR/USD:EURUSD.pro, GBP/USD:GBPUSD.pro, etc.
_MT5_SYMBOL_MAP_RAW = os.getenv("MT5_SYMBOL_MAP", "")
MT5_SYMBOL_MAP: dict[str, str] = {}
if _MT5_SYMBOL_MAP_RAW:
    for entry in _MT5_SYMBOL_MAP_RAW.split(","):
        entry = entry.strip()
        if ":" in entry:
            k, v = entry.split(":", 1)
            MT5_SYMBOL_MAP[k.strip()] = v.strip()

# Money management
TRADING_CAPITAL = float(os.getenv("TRADING_CAPITAL", "10000"))  # Capital en USD
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "1.0"))  # % du capital risqué par trade
MIN_CONFIDENCE_SCORE = float(os.getenv("MIN_CONFIDENCE_SCORE", "75"))  # Score min pour afficher un setup (0-100)
# Limite de perte journaliere : au-dela, mode silencieux (pas de bip, pas de telegram)
DAILY_LOSS_LIMIT_PCT = float(os.getenv("DAILY_LOSS_LIMIT_PCT", "3.0"))

# Watchdog rafale stops loss : si True, le watchdog déclenche une pause
# auto-exec quand un seuil de SL est franchi. Smart resume basé sur
# l'activité réelle de V1 plutôt qu'un countdown fixe.
RAFALE_AUTO_PAUSE_ENABLED = os.getenv("RAFALE_AUTO_PAUSE_ENABLED", "true").lower() == "true"
# Cool-off minimum après pause avant de considérer un resume (anti-flapping)
RAFALE_MIN_COOL_OFF_MIN = int(os.getenv("RAFALE_MIN_COOL_OFF_MIN", "30"))
# Fenêtre d'observation : si V1 ne tente plus le pattern depuis X min → safe to resume
RAFALE_QUIET_WINDOW_MIN = int(os.getenv("RAFALE_QUIET_WINDOW_MIN", "15"))
# Plafond max : force resume après cette durée même si V1 essaie encore
RAFALE_MAX_PAUSE_HOURS = int(os.getenv("RAFALE_MAX_PAUSE_HOURS", "6"))

# Email summary quotidien (SMTP)
EMAIL_SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "465"))
EMAIL_SMTP_USER = os.getenv("EMAIL_SMTP_USER", "")
EMAIL_SMTP_PASSWORD = os.getenv("EMAIL_SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_RECIPIENTS = [e.strip() for e in os.getenv("EMAIL_RECIPIENTS", "").split(",") if e.strip()]

# Intervalles bougies pour l'analyse de patterns
CANDLE_INTERVAL = os.getenv("CANDLE_INTERVAL", "5min")
CANDLE_COUNT = int(os.getenv("CANDLE_COUNT", "50"))

# Mataf URL
MATAF_VOLATILITY_URL = "https://www.mataf.net/en/forex/tools/volatility"

# Forex Factory URL
FOREXFACTORY_CALENDAR_URL = "https://www.forexfactory.com/calendar"

# ─── Macro context scoring (Vague 1 enrichissement) ─────────────
# Feature flags
MACRO_SCORING_ENABLED = os.getenv("MACRO_SCORING_ENABLED", "false").lower() in ("1", "true", "yes", "on")
MACRO_VETO_ENABLED = os.getenv("MACRO_VETO_ENABLED", "false").lower() in ("1", "true", "yes", "on")

# Chantier 1 SaaS : feature-flag du parcours signup self-service. OFF par
# défaut tant que les chantiers 2-3 (login UI + data isolation) ne sont pas
# livrés. L'endpoint existe mais répond 404 si désactivé.
SAAS_SIGNUP_ENABLED = os.getenv("SAAS_SIGNUP_ENABLED", "false").lower() in ("1", "true", "yes", "on")

# Whitelist signup : emails autorisés à s'inscrire même quand
# SAAS_SIGNUP_ENABLED=false. Permet de tester le funnel en prod pendant
# qu'il est fermé au public. Support du wildcard `*` en partie locale
# (ex: `couderc.xavier+*@gmail.com` match tous les alias Gmail plus).
SIGNUP_WHITELIST = [e.strip().lower() for e in os.getenv("SIGNUP_WHITELIST", "").split(",") if e.strip()]


def email_in_whitelist(email: str, patterns: list[str] | None = None) -> bool:
    """True si `email` match un pattern SIGNUP_WHITELIST.

    Support : match exact (insensible à la casse) ou wildcard `*` dans la
    partie locale (avant @). Le `*` match 0+ caractères. Utilisé pour
    autoriser des alias Gmail type `foo+test1@gmail.com`, `foo+test2@...`
    via un seul pattern `foo+*@gmail.com`.
    """
    if not email:
        return False
    patterns = patterns if patterns is not None else SIGNUP_WHITELIST
    if not patterns:
        return False
    import fnmatch
    e = email.strip().lower()
    return any(fnmatch.fnmatchcase(e, p) for p in patterns)


# Whitelist admin (Chantier 12 SaaS). Emails séparés par virgule. Les users
# whitelistés voient /admin avec users list + MRR + trials.
ADMIN_EMAILS = [e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]

# Stripe (Chantier 5 SaaS) : ouverture des endpoints checkout/portal/webhook
# gated par STRIPE_ENABLED. OFF par défaut pour ne pas exposer en prod tant
# que les clés + produits Stripe ne sont pas configurés.
STRIPE_ENABLED = os.getenv("STRIPE_ENABLED", "false").lower() in ("1", "true", "yes", "on")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
# Ids des prix Stripe pour chaque tier + cycle (configurables dans Stripe Dashboard).
# Back-compat : STRIPE_PRICE_PRO sert de fallback pour STRIPE_PRICE_PRO_MONTHLY.
STRIPE_PRICE_PRO_MONTHLY = os.getenv("STRIPE_PRICE_PRO_MONTHLY") or os.getenv("STRIPE_PRICE_PRO", "")
STRIPE_PRICE_PRO_YEARLY = os.getenv("STRIPE_PRICE_PRO_YEARLY", "")
STRIPE_PRICE_PREMIUM_MONTHLY = os.getenv("STRIPE_PRICE_PREMIUM_MONTHLY") or os.getenv("STRIPE_PRICE_PREMIUM", "")
STRIPE_PRICE_PREMIUM_YEARLY = os.getenv("STRIPE_PRICE_PREMIUM_YEARLY", "")
# Alias legacy (tests existants référencent STRIPE_PRICE_PRO).
STRIPE_PRICE_PRO = STRIPE_PRICE_PRO_MONTHLY
STRIPE_PRICE_PREMIUM = STRIPE_PRICE_PREMIUM_MONTHLY
# URL publique pour rediriger après checkout success/cancel.
STRIPE_SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL", "https://app.scalping-radar.online/v2/?upgrade=success")
STRIPE_CANCEL_URL = os.getenv("STRIPE_CANCEL_URL", "https://app.scalping-radar.online/v2/pricing?upgrade=cancelled")

# Refresh cadence and cache tolerance
MACRO_REFRESH_INTERVAL_SEC = int(os.getenv("MACRO_REFRESH_INTERVAL_SEC", "900"))  # 15 min
MACRO_CACHE_MAX_AGE_SEC = int(os.getenv("MACRO_CACHE_MAX_AGE_SEC", "7200"))  # 2h fallback

# Symbols mapping (logical name → Twelve Data ticker)
MACRO_SYMBOL_DXY = os.getenv("MACRO_SYMBOL_DXY", "DXY")
MACRO_SYMBOL_SPX = os.getenv("MACRO_SYMBOL_SPX", "SPX")
MACRO_SYMBOL_VIX = os.getenv("MACRO_SYMBOL_VIX", "VIX")
MACRO_SYMBOL_US10Y = os.getenv("MACRO_SYMBOL_US10Y", "TNX")
MACRO_SYMBOL_DE10Y = os.getenv("MACRO_SYMBOL_DE10Y", "DE10Y")
MACRO_SYMBOL_OIL = os.getenv("MACRO_SYMBOL_OIL", "WTI")
MACRO_SYMBOL_NIKKEI = os.getenv("MACRO_SYMBOL_NIKKEI", "NKY")
MACRO_SYMBOL_GOLD = os.getenv("MACRO_SYMBOL_GOLD", "XAU/USD")

# Thresholds (overridable for tuning)
MACRO_ZSCORE_STRONG = float(os.getenv("MACRO_ZSCORE_STRONG", "1.5"))
MACRO_ZSCORE_WEAK = float(os.getenv("MACRO_ZSCORE_WEAK", "0.5"))
MACRO_VIX_HIGH = float(os.getenv("MACRO_VIX_HIGH", "30.0"))
MACRO_VIX_ELEVATED = float(os.getenv("MACRO_VIX_ELEVATED", "20.0"))
MACRO_VIX_LOW = float(os.getenv("MACRO_VIX_LOW", "15.0"))
MACRO_DXY_VETO_SIGMA = float(os.getenv("MACRO_DXY_VETO_SIGMA", "2.0"))

# ─── Geopolitical news scoring (GDELT — shadow only) ────────────
# Branche le service `geopolitical_news_service` qui fetch GDELT toutes les
# heures et stocke les snapshots. OFF par défaut : tant que le signal n'est
# pas validé (4-6 semaines de données), pas d'impact sur le scoring trade.
# Affichage seul (cockpit + /api/geopolitical).
GEOPOLITICAL_NEWS_ENABLED = os.getenv("GEOPOLITICAL_NEWS_ENABLED", "false").lower() in ("1", "true", "yes", "on")
GEOPOLITICAL_REFRESH_INTERVAL_SEC = int(os.getenv("GEOPOLITICAL_REFRESH_INTERVAL_SEC", "3600"))  # 1h
GEOPOLITICAL_TIMESPAN = os.getenv("GEOPOLITICAL_TIMESPAN", "24h")  # fenêtre fetch GDELT

# ─── Polymarket prediction markets (shadow only) ────────────────
# Branche le service `polymarket_service` qui fetch toutes les 5 min les top
# marchés actifs sur Polymarket Gamma API. Donne des probabilités chiffrées
# sur les événements géopolitiques/macro (Fed, Iran, Hormuz, BTC, élections).
# Shadow only : pas branché au scoring tant que la corrélation avec les
# retournements n'est pas validée sur 4-6 semaines.
POLYMARKET_ENABLED = os.getenv("POLYMARKET_ENABLED", "false").lower() in ("1", "true", "yes", "on")
POLYMARKET_REFRESH_INTERVAL_SEC = int(os.getenv("POLYMARKET_REFRESH_INTERVAL_SEC", "300"))  # 5 min

# ─── Geopolitical veto (hard-rule sur scoring) ─────────────────
# Bloque les setups dans la mauvaise direction quand un event Polymarket/GDELT
# signale un risque direct. Ajouté en aval du macro_scoring.apply() dans
# analysis_engine.enrich_trade_setup. Master switch + 1 flag par règle pour
# rollback instantané d'une règle individuelle sans toucher au code.
# Voir backend/services/geopolitical_veto.py pour les règles.
GEOPOLITICAL_VETO_ENABLED = os.getenv("GEOPOLITICAL_VETO_ENABLED", "false").lower() in ("1", "true", "yes", "on")

# Règle 1 : Iran peace deal prob ≥ X% à <Y jours → veto longs XAU/XAG/WTI.
GEOPOLITICAL_VETO_IRAN_HORMUZ_ENABLED = os.getenv("GEOPOLITICAL_VETO_IRAN_HORMUZ_ENABLED", "true").lower() in ("1", "true", "yes", "on")
GEOPOLITICAL_VETO_IRAN_HORMUZ_PROB = float(os.getenv("GEOPOLITICAL_VETO_IRAN_HORMUZ_PROB", "0.30"))
GEOPOLITICAL_VETO_IRAN_HORMUZ_DAYS = int(os.getenv("GEOPOLITICAL_VETO_IRAN_HORMUZ_DAYS", "14"))

# Règle 2 : Fed rate cut prob ≥ X% à <Y jours → veto positions USD-fort.
GEOPOLITICAL_VETO_FED_DOVISH_ENABLED = os.getenv("GEOPOLITICAL_VETO_FED_DOVISH_ENABLED", "true").lower() in ("1", "true", "yes", "on")
GEOPOLITICAL_VETO_FED_DOVISH_PROB = float(os.getenv("GEOPOLITICAL_VETO_FED_DOVISH_PROB", "0.70"))
GEOPOLITICAL_VETO_FED_DOVISH_DAYS = int(os.getenv("GEOPOLITICAL_VETO_FED_DOVISH_DAYS", "14"))

# Règle 3 : Recession prob ≥ X% → veto longs indices US.
GEOPOLITICAL_VETO_RECESSION_ENABLED = os.getenv("GEOPOLITICAL_VETO_RECESSION_ENABLED", "true").lower() in ("1", "true", "yes", "on")
GEOPOLITICAL_VETO_RECESSION_PROB = float(os.getenv("GEOPOLITICAL_VETO_RECESSION_PROB", "0.50"))

# Règle 4 : GDELT stress geopolitical=high → veto longs indices européens.
GEOPOLITICAL_VETO_GDELT_STRESS_ENABLED = os.getenv("GEOPOLITICAL_VETO_GDELT_STRESS_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# Règle 5 : Tariff / trade war prob ≥ X% à <Y jours → veto longs risk-on (indices US, crypto).
GEOPOLITICAL_VETO_TARIFF_ENABLED = os.getenv("GEOPOLITICAL_VETO_TARIFF_ENABLED", "true").lower() in ("1", "true", "yes", "on")
GEOPOLITICAL_VETO_TARIFF_PROB = float(os.getenv("GEOPOLITICAL_VETO_TARIFF_PROB", "0.40"))
GEOPOLITICAL_VETO_TARIFF_DAYS = int(os.getenv("GEOPOLITICAL_VETO_TARIFF_DAYS", "30"))

# Track A shadow filtered twin : pour chaque setup Track A baseline, si
# le veto contrefactuel laisse passer (would_veto=False), logger AUSSI un
# 2e setup avec system_id suffixé `_FILTERED`. Permet la comparaison live
# directe "sans veto" vs "avec veto" sur Track A, sans dépendre du seul
# script counterfactual posthoc. Le baseline reste loggé toujours (lecture
# seule pure). Le twin n'apparaît que si le veto laisse passer.
SHADOW_FILTERED_TWIN_ENABLED = os.getenv("SHADOW_FILTERED_TWIN_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# ─── Shadow V1 — paires journalisées hors admission OBSERVED (2026-08-05) ──
# `log_v1_shadows_for_tracked_pairs` (backend/services/shadow_v1.py) ne
# journalisait historiquement que les paires en état OBSERVED côté
# pair_admission_controller. Mesuré en prod le 2026-08-05 : aucune paire
# crypto n'atteint cet état (BTC/USD, ETH/USD sont DEMOTED en global ou
# AUTO_EXEC par destination) → ~1 seule ligne shadow crypto/semaine, contre
# ~2900 côté actions observées. Or la crypto est bloquée au dispatch par la
# porte d'horizon et la porte de coût (cf. project_crypto_fees_kill_edge) :
# économiquement, elle est dans la même situation qu'une paire observée —
# jamais de vraie exécution, donc la mesurer sans risquer de capital a un sens.
# Liste de classes d'actif (cf. `asset_class_for`) à journaliser dans le flux
# shadow V1 INDÉPENDAMMENT de leur état d'admission. Vide = comportement
# historique (observées uniquement). Défaut = "crypto". Couper par .env +
# redémarrage si le volume `shadow_setups` devient un problème.
SHADOW_V1_UNOBSERVED_ASSET_CLASSES = [
    c.strip().lower()
    for c in os.getenv("SHADOW_V1_UNOBSERVED_ASSET_CLASSES", "crypto").split(",")
    if c.strip()
]

# ─── Reddit sentiment scoring (P3 MVP — 2026-08-03) ─────────────────
# Filtre contrarien soft ×0.90 sur BTC/USD et ETH/USD quand le sentiment
# Reddit (r/CryptoCurrency + r/Bitcoin + r/ethtrader) est extrême et
# crowd-following (setup dans le même sens que la foule retail surcrowdée).
# Source : JSON public Reddit hot.json, no auth, refresh horaire scheduler.
# Désactivé par défaut — activer après validation qualité signal sur 2-4 semaines.
# Pour activer : REDDIT_SENTIMENT_ENABLED=true dans .env
REDDIT_SENTIMENT_ENABLED = os.getenv("REDDIT_SENTIMENT_ENABLED", "false").lower() in ("1", "true", "yes", "on")
