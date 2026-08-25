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
#
# ⚠️ `docker run --env-file` NE retire PAS les guillemets, contrairement au
# shell : `WATCHED_PAIRS="EUR/USD,...,LINK/USD"` produit alors une premiere
# paire `"EUR/USD` et une derniere `LINK/USD"`. Elles ne correspondent plus a
# rien — mesure du 2026-08-23 : `LINK/USD"` tombait en classe `forex` par
# defaut et sortait silencieusement de l'univers crypto.
#
# On nettoie donc a la lecture plutot que de compter sur la discipline de
# celui qui edite le `.env`. Le meme piege guette toute variable de liste.
def _liste_env(nom: str, defaut: str) -> list[str]:
    brut = os.getenv(nom, defaut).strip().strip('"').strip("'")
    return [x.strip().strip('"').strip("'") for x in brut.split(",") if x.strip()]


WATCHED_PAIRS = _liste_env(
    "WATCHED_PAIRS",
    "XAU/USD,EUR/USD,GBP/USD,USD/JPY,EUR/GBP,USD/CHF,AUD/USD,USD/CAD,EUR/JPY,GBP/JPY,"
    "BTC/USD,ETH/USD,XAG/USD,WTI/USD,SPX,NDX",
)

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

# Canal Telegram dédié aux TRADES (2026-08-19) : ouvertures, clôtures, refus
# de push. Le bot sales mélangeait les ordres avec les digests d'analyse,
# l'état des marchés et le récap quotidien — un ordre parti s'y noyait.
#
# ⚠️ Si vide, l'endpoint retombe sur le canal `sales` plutôt que d'échouer :
# perdre la notification d'un ordre réel serait pire que la poster sur le
# mauvais fil. Le repli est journalisé, il ne passe pas en silence.
TRADES_TELEGRAM_BOT_TOKEN = os.getenv("TRADES_TELEGRAM_BOT_TOKEN", "")
TRADES_TELEGRAM_CHAT_ID = os.getenv("TRADES_TELEGRAM_CHAT_ID", "")
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

# ─── Garde-fou SL/TP sur position déjà ouverte (2026-08-06) ──────────
# Détecte les positions LIVE sans SL sur les bridges MT5 (legacy Demo +
# live IC Markets) et, si activé, demande au bridge de leur poser un stop
# d'urgence via /position/sltp. Cf. backend/services/sltp_guard_check.py.
#
# Driver : incident 2026-08-05, position XAU/USD ouverte sans SL/TP à
# 02:09 UTC, découverte 7h après à -51€. La cause (échec silencieux de la
# pose SL/TP côté bridge) est corrigée en amont (mt5-bridge/bridge.py,
# _apply_sltp_from_fill retourne désormais un résultat exploitable) ; ce
# garde-fou reste le filet de sécurité si un mode d'échec similaire
# réapparaît malgré tout.
#
# Désactivé par défaut, et volontairement DOUBLÉ avec SLTP_GUARD_ENABLED
# côté bridge (mt5-bridge/.env) : les deux drapeaux doivent être vrais pour
# qu'un ordre parte. Si un seul est vrai, ce module détecte et alerte mais
# n'agit jamais — comportement historique du garde-fou avant ce chantier.
SLTP_GUARD_AUTO_PROTECT_ENABLED = os.getenv(
    "SLTP_GUARD_AUTO_PROTECT_ENABLED", "false"
).lower() in ("1", "true", "yes", "on")
# Distance du stop d'urgence, en % du prix d'entrée (price_open) de la
# position nue. Volontairement large : ce n'est pas un stop de scalping
# calibré par le scoring, c'est un filet qui borne une perte qui serait
# sinon illimitée.
SLTP_GUARD_EMERGENCY_SL_PCT = float(os.getenv("SLTP_GUARD_EMERGENCY_SL_PCT", "1.0"))
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

# ─── IBKR actions (voie C, dispatch ouvert le 2026-08-10) ──────────────
#
# Le bridge (`ibkr-bridge/bridge.py`, port 8792) existait depuis le
# 2026-08-04 en lecture seule ; ce bloc ouvre le chemin de dispatch.
#
# ⚠️ DEUX interrupteurs, et ils sont indépendants :
#   - `IBKR_BRIDGE_ENABLED` côté radar — le setup est-il routé ici ?
#   - `IBKR_ALLOW_ORDERS` côté BRIDGE — le Gateway accepte-t-il d'écrire ?
#     Tant qu'il est faux, la session IB est ouverte en `readonly=True` et
#     c'est le Gateway LUI-MÊME qui refuse : un bug applicatif ne peut pas
#     passer d'ordre. Ne jamais confondre les deux.
IBKR_BRIDGE_ENABLED = os.getenv("IBKR_BRIDGE_ENABLED", "false").lower() in ("1", "true", "yes", "on")
IBKR_BRIDGE_URL = os.getenv("IBKR_BRIDGE_URL", "")
IBKR_BRIDGE_API_KEY = os.getenv("IBKR_BRIDGE_API_KEY", "")
IBKR_BRIDGE_MIN_CONFIDENCE = float(os.getenv("IBKR_BRIDGE_MIN_CONFIDENCE", "60"))

# ⚠️ L'edge attendu, en R. `None` par défaut, et ce n'est PAS un oubli : la
# porte de coût refuse une route dont l'edge n'est pas mesuré, ce qui est la
# bonne réponse tant qu'il ne l'est pas.
#
# Sur les 4 actions US individuelles, il est mesuré NÉGATIF — Δ = −0,182 R
# contre une entrée au hasard, p < 0,001 (project_edge_actions_us_h4_2026_08_05).
# Sur XLI/XLK il est « non tranché » après vingt ans : estimation ponctuelle
# négative, IC contenant zéro.
#
# Renseigner cette variable est donc un acte DÉLIBÉRÉ, qui déclare un edge que
# la mesure ne soutient pas aujourd'hui. Elle existe pour que cet acte soit
# nommé et tracé, jamais implicite.
_edge = os.getenv("IBKR_BRIDGE_EXPECTED_EDGE_R", "").strip()
IBKR_BRIDGE_EXPECTED_EDGE_R = float(_edge) if _edge else None
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

# Une paire « indécidable » (moins de PAC_MIN_REAL_TRADES trades RÉELS) peut-elle
# franchir TELEGRAM → AUTO_EXEC après son palier temporel ?
#
# ⚠️ `true` par défaut, et c'est le correctif du 2026-08-06. Sans lui, le
# garde-fou ci-dessus devient une PORTE À SENS UNIQUE : seule une paire en
# AUTO_EXEC produit des trades réels, donc exiger 30 trades réels AVANT
# d'accorder l'exécution est insatisfaisable par construction. L'univers
# tradable ne pouvait plus que rétrécir — constaté en production, 11 couples
# le 04/08 puis 8 le 05/08.
#
# La preuve attendue ne peut d'ailleurs jamais être concluante : la promotion
# par paire est statistiquement indécidable à cette échelle (~1500 trades
# requis par paire, 1561 existent au total).
#
# La distinction retenue : « on ne sait pas » (INDETERMINATE) passe, « on sait
# que c'est mauvais » (OBSERVED sur données réelles) bloque. Le risque du
# premier passage à l'argent réel est porté par les contenants en aval —
# palier temporel, plafonds de lot, ajustement à la marge, porte de coût,
# rétrogradation sur drawdown mesuré.
PAC_ALLOW_INDETERMINATE_PROMOTION = os.getenv(
    "PAC_ALLOW_INDETERMINATE_PROMOTION", "true"
).strip().lower() in ("1", "true", "yes", "on")

# Débit maximal de promotions AUTOMATIQUES vers AUTO_EXEC (argent réel), sur
# une fenêtre glissante de 7 jours. Les promotions manuelles ne le consomment
# pas : une décision humaine explicite n'a pas à être bridée par un garde-fou
# conçu contre l'emballement automatique.
#
# ⚠️ Ce plafond existe à cause d'une vague mesurée. Au moment de corriger la
# porte à sens unique (2026-08-06), **37 couples** étaient bloqués en OBSERVED.
# Sans débit, ils seraient tous entrés en TELEGRAM au même cycle, donc arrivés
# à maturité le MÊME JOUR : l'exposition serait passée de 11 à 47 couples d'un
# coup, sur un système dont aucun avantage n'est démontré.
#
# Réparer une porte bloquée ne doit pas revenir à l'arracher.
PAC_MAX_AUTO_PROMOTIONS_PER_WEEK = int(
    os.getenv("PAC_MAX_AUTO_PROMOTIONS_PER_WEEK", "2")
)

# Borne SUPÉRIEURE de la durée de détention (heures), utilisée pour estimer le
# coût de portage tant qu'aucune médiane n'est mesurable sur l'échantillon
# propre (30 setups résolus depuis le 2026-08-05).
#
# ⚠️ Sans ce repli, la route Kraken restait fermée à l'argent réel pendant un à
# deux mois : mesuré le 2026-08-06, les systèmes crypto journaliers avaient
# ZÉRO setup résolu propre et en produisent au plus un par jour, chacun mettant
# des jours à se résoudre. « Incalculable donc refus » devenait un blocage à vie.
#
# La détention ne peut pas dépasser le délai de sortie : cette valeur MAJORE
# donc le portage réel. Un trade qui passe la porte de coût avec elle passerait
# a fortiori avec la vraie médiane — c'est fail-safe, pas permissif.
#
# ⚠️ Ne JAMAIS descendre sous le délai de sortie effectif : ce serait
# sous-estimer les frais. Mettre 0 restaure l'ancien comportement (portage
# incalculable ⇒ refus de tout argent réel sur les routes à funding).
#
# Vérifié aux taux de funding réels : au pire cas, un setup crypto journalier à
# 7,69 % de stop consomme 24,8 % de l'edge sur BTC et 19,1 % sur ETH, sous le
# plafond de 30 %.
HOLDING_WORST_CASE_HOURS = float(os.getenv("HOLDING_WORST_CASE_HOURS", "96"))

# Le compte de DÉMONSTRATION pilote-t-il le compte RÉEL ?
#
# Demandé le 2026-08-06 : plutôt que les deux comptes décidant en parallèle
# depuis le même signal, un fill confirmé en démo déclenche l'ouverture d'un
# ordre identique sur le réel.
#
# ⚠️ Les portes de DÉCISION du backend ne sont pas rejouées sur la copie — le
# démo vient de décider, les rejouer reproduirait la divergence qu'on supprime.
# Tous les garde-fous de SÉCURITÉ restent actifs : plafonds de lot par classe,
# nombre de positions, perte journalière, ajustement à la marge disponible, et
# le refus du courtier. La copie ne peut pas ouvrir ce que le compte réel ne
# peut pas porter.
#
# ⚠️ Ce que le miroir ne transporte PAS : la marge. Mesuré le 2026-08-06, sur
# les 8 fills du démo ce jour-là, ZÉRO aurait pu être copié — le compte réel
# avait une marge libre négative toute la journée. Le miroir supprime la
# divergence de DÉCISION, jamais celle de CAPACITÉ.
MIRROR_DEMO_TO_LIVE_ENABLED = os.getenv(
    "MIRROR_DEMO_TO_LIVE_ENABLED", "true"
).strip().lower() in ("1", "true", "yes", "on")

# Nombre de pushes `admin_legacy` pendant lesquels le filtre de patterns ET
# la porte de coût sont LEVÉS (routes MT5 uniquement). Mécanisme à usage unique et AUTO-RÉARMANT.
#
# Posé le 2026-08-06 pour observer l'alignement démo → réel sur un trade, sans
# attendre les ~10 jours que la porte de coût impose sur `range_bounce` seul.
#
# ⚠️ Pourquoi un quota plutôt que vider la whitelist : une fenêtre ouverte
# « le temps de voir » reste toujours ouverte plus longtemps que prévu, parce
# que personne ne revient la refermer. Le quota borne l'expérience par
# construction — le filtre se remet seul dès le premier push.
#
# ⚠️ Le filtre qu'il lève repose sur un edge REFUTÉ : `range_bounce` +0,129 R
# est une espérance ABSOLUE, pas un avantage de sélection (mesuré le
# 2026-08-05). Le lever ne dégrade donc aucune protection démontrée — mais ne
# fait pas gagner non plus : plus de trades = plus de frais certains pour une
# espérance de sélection nulle.
#
# 0 = filtre toujours actif (comportement par défaut).
TRADE_DEROGATION_PUSHES = int(os.getenv("TRADE_DEROGATION_PUSHES", "0"))

# Instant d'ARMEMENT de la levée ci-dessus (ISO 8601 UTC). Les pushes sont
# comptés à partir de là, PAS depuis minuit.
#
# ⚠️ Compter par jour calendaire avait deux défauts : le quota était consommé
# par les pushes déjà passés le matin, et il se remettait à zéro à minuit —
# ce qui aurait rouvert la vanne en grand pendant la nuit sans que personne
# le demande. Vide ⇒ filtre maintenu (on ne compte pas depuis une base
# inconnue).
TRADE_DEROGATION_SINCE = os.getenv("TRADE_DEROGATION_SINCE", "").strip()

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

# Tickets retirés du SCORING d'admission — et de rien d'autre (2026-08-25).
#
# Un trade que le système n'a pas géré ne doit pas le noter. Le cas fondateur :
# le ticket 1353960866, tenu SANS STOP sur consigne explicite de Xavier
# (« ne pas le compter dans l'équation, le laisser vivre sa vie ») puis fermé à
# la main à -265,11 €. Il avait bien été exclu du garde-fou de perte journalière
# du bridge (`DAILY_LOSS_EXCLUDED_TICKETS`) mais JAMAIS du calcul d'admission :
# à lui seul il faisait passer le côté vente de l'or de +230,39 € à -34,72 €,
# donc sous le plancher de -3 %, donc en PAUSED.
#
# ⛔ Cette liste ne retire rien au risque, au P&L, ni à aucun relevé d'argent.
# L'argent a réellement été perdu. Elle retire une décision qui n'était pas
# celle du système d'un bulletin qui juge le système.
#
# ⚠️ Pourquoi une liste explicite et pas « tous les close_reason = MANUAL » :
# `MANUAL` est la BRANCHE PAR DÉFAUT du classement de sortie
# (cf. project_close_reason_manual_invente_2026_08_10) — il est autant « on n'a
# pas su » que « fermé à la main ». Exclure sur ce motif jetterait en silence
# des trades réellement gérés par le système. Une exception doit être nommée.
#
# Vide par défaut : sans réglage explicite, aucun comportement ne change.
PAC_EXCLUDED_TICKETS = frozenset(
    int(t.strip())
    for t in os.getenv("PAC_EXCLUDED_TICKETS", "").split(",")
    if t.strip().lstrip("-").isdigit()
)

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

# Fenetre horaire autorisee PAR INSTRUMENT, en heures UTC, bornes incluses.
# Format : {"XAU/USD": "06-19"}. Une fenetre peut enjamber minuit ("22-05").
#
# Mesure du 2026-08-11 sur 15 150 bougies M1 / 14 jours : le spread de l'or est
# a un plateau de 06h a 19h UTC puis DOUBLE (x2,13) a 20h et 22h.
#
# ⚠️ Vide par defaut. Un profil de spread appartient au couple (courtier,
# instrument) : le figer dans le code le rendrait faux au premier changement de
# courtier, et silencieusement.
try:
    _raw_heures = os.getenv("PAIR_TRADING_HOURS_UTC", "")
    PAIR_TRADING_HOURS_UTC = _json_min_sl.loads(_raw_heures) if _raw_heures else {}
    if not isinstance(PAIR_TRADING_HOURS_UTC, dict):
        PAIR_TRADING_HOURS_UTC = {}
except (ValueError, _json_min_sl.JSONDecodeError):
    PAIR_TRADING_HOURS_UTC = {}

# Whitelist de patterns SURCHARGEE par (paire, horizon).
# Format : {"XAU/USD": {"4h": ["momentum_up", ...]}}
#
# Mesure du 2026-08-11 : l'or produit 76 setups 4h en 30 jours, dont ZERO
# dispatchable — son jeu de patterns au 4h ne contient aucun `range_bounce`,
# seul motif que la whitelist globale accepte. L'instrument qui porte 87,6 %
# du resultat etait absent du seul horizon qui paie ses frais.
#
# ⚠️ La whitelist globale vient d'un edge valide hors echantillon sur le flux
# 5 MINUTES. Le controle aleatoire a montre depuis que cet edge etait du beta
# de marche, pas de la selection. La regle survit a sa justification, et elle
# n'a jamais ete testee a 4h.
#
# ⚠️ Vide par defaut. Le petrole 4h reste ferme : mesure a -0,128 R, negatif
# ETABLI. Seul l'or est ouvert, en sachant que les metaux 4h sont a -0,045 R,
# intervalle [-0,100 ; +0,012] — non tranche.
try:
    _raw_pat = os.getenv("MT5_BRIDGE_PATTERN_OVERRIDES", "")
    MT5_BRIDGE_PATTERN_OVERRIDES = _json_min_sl.loads(_raw_pat) if _raw_pat else {}
    if not isinstance(MT5_BRIDGE_PATTERN_OVERRIDES, dict):
        MT5_BRIDGE_PATTERN_OVERRIDES = {}
except (ValueError, _json_min_sl.JSONDecodeError):
    MT5_BRIDGE_PATTERN_OVERRIDES = {}

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

# Le flux long-horizon atteint-il le DISPATCH (et donc l'exécution), ou
# seulement la mesure et Telegram ?
#
# Branché le 2026-08-06. Jusque-là, `run_shadow_log` n'appelait jamais
# `send_setup` : le flux 4h/1d produisait des setups que personne ne pouvait
# exécuter — la plomberie manquante du plan 2.
#
# Aucune destination n'est choisie par ce drapeau : les portes d'horizon
# routent seules. MT5 n'admet que `CANDLE_INTERVAL` (5min) et refuse ces
# setups ; Kraken n'admet que {4h, 1d} et les accepte.
#
# Pourquoi c'est le SEUL horizon économiquement viable sur Kraken, mesuré le
# 2026-08-06 sur `shadow_setups` : au journalier, 100 % des setups crypto
# passent la porte de coût (distance au stop médiane 7,69 % contre un seuil de
# viabilité à 3,03 %) ; en 1h et 5min, aucun. Les frais Kraken ne tuent pas la
# crypto — ils tuent le scalping.
LONG_HORIZON_DISPATCH_ENABLED = os.getenv(
    "LONG_HORIZON_DISPATCH_ENABLED", "true"
).strip().lower() in ("1", "true", "yes", "on")

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

# Paires pour lesquelles on NE recupere PAS les bougies 5 min (2026-08-08).
#
# Une paire servie uniquement par un systeme JOURNALIER n'a aucun usage du
# 5 min : ses signaux V1 seraient de toute facon refuses faute de whitelist.
# Chaque paire epargnee libere une requete Twelve Data par cycle.
#
# ⚠️ Pose apres mesure : le pic de consommation atteignait 40 requetes sur la
# minute la plus chargee, pour une limite de 55. Ajouter 5 paires l'aurait
# porte a ~47, soit 85 % — la marge exacte qui a fait echouer un rattrapage
# le matin meme. Liberer avant d'ajouter, plutot que l'inverse.
#
# Vide par defaut : sans reglage, comportement inchange.
CANDLE_5MIN_SKIP_PAIRS = frozenset(
    p.strip().upper()
    for p in os.getenv("CANDLE_5MIN_SKIP_PAIRS", "").split(",")
    if p.strip()
)

# Mataf URL
MATAF_VOLATILITY_URL = "https://www.mataf.net/en/forex/tools/volatility"

# Forex Factory URL
FOREXFACTORY_CALENDAR_URL = "https://www.forexfactory.com/calendar"

# ─── Macro context scoring (Vague 1 enrichissement) ─────────────
# Feature flags
MACRO_SCORING_ENABLED = os.getenv("MACRO_SCORING_ENABLED", "false").lower() in ("1", "true", "yes", "on")
MACRO_VETO_ENABLED = os.getenv("MACRO_VETO_ENABLED", "false").lower() in ("1", "true", "yes", "on")

# Audit du 2026-08-05 : macro_context_service.vix_value (ci-dessus) vaut
# 17.0 dans 100% des lignes en production depuis des mois — c'est la valeur
# de repli codée en dur, la vraie donnée n'a jamais été récupérée. Deux
# historiques réels existaient déjà dans le dépôt sans être branchés :
# macro_daily (backend.services.macro_data, VIX/DXY/SPX/10Y/BTC quotidien
# depuis 2024) et fear_greed_snapshots (backend.services.fear_greed_service,
# CNN Fear & Greed quotidien depuis mai 2026). `macro_history_features`
# les expose désormais en lecture point-in-time (jamais de look-ahead,
# jamais de constante de repli — None si inconnu).
#
# DÉSACTIVÉ PAR DÉFAUT. Les seuils de décision actuels (42, 61, 71) ont été
# calibrés avec une couche macro constante (donc neutre pour le modèle) ;
# la rendre vivante déplacerait la distribution des scores sans qu'on sache
# si c'est en mieux. Avant d'activer :
#   1. Réentraîner/ré-évaluer le modèle ML avec les nouvelles features
#      (préfixe `mh_`) et confirmer un gain d'AUC hors échantillon.
#   2. Vérifier qu'aucun des thresholds figés (42/61/71) ne dérive une fois
#      la couche macro non-constante — comparer la distribution des scores
#      avant/après sur un échantillon shadow.
#   3. Confirmer côté prod que macro_daily et fear_greed_snapshots restent
#      alimentés (crons actifs, pas de régression silencieuse comme celle
#      qui a touché macro_context_service).
# Aujourd'hui ce flag ne gouverne que l'enrichissement des features ML en
# shadow log (backend/services/ml_features.py) — aucune décision live n'en
# dépend tant qu'il reste à false.
MACRO_HISTORY_FEATURES_ENABLED = os.getenv("MACRO_HISTORY_FEATURES_ENABLED", "false").lower() in ("1", "true", "yes", "on")

# ── Réparation VIX du multiplicateur macro live (2026-08-05) ────────────
#
# Cause réelle, vérifiée en production avec la clé Twelve Data live : le
# symbole configuré pour le VIX (`MACRO_SYMBOL_VIX`, "VIX" par défaut)
# n'existe PAS côté Twelve Data — HTTP 404 "symbol or figi parameter is
# missing or invalid" à 100%, sur "VIX", "^VIX" et "VIX.INDX" testés. Ce
# n'est pas une panne intermittente : `spot.get("vix", 17.0)` retombait donc
# STRUCTURELLEMENT et en permanence sur la constante de repli, jamais sur
# une vraie mesure — confirmé sur les 277 610 lignes de `signals.macro_context`
# en base (`backtest.db`) : vix_value=17.0 et dxy="neutral" à 100%.
#
# (Découverte annexe, hors périmètre ici : le symbole "SPX" configuré ne
# pointe pas non plus vers le S&P 500 mais vers une action TSXV canadienne
# homonyme — cotée en CAD à ~0,08. Le dxy_direction est également mort. Ces
# deux défauts restent non réparés par ce chantier, volontairement limité au
# VIX comme demandé.)
#
# Pendant ce temps, une source VIX réelle et DÉJÀ VIVANTE en production
# existe dans le même dépôt sans être branchée ici : `vix_service.py`
# interroge Yahoo Finance (^VIX, symbole valide) toutes les 5 min via un job
# scheduler indépendant ("vix_refresh", non gated par MACRO_SCORING_ENABLED)
# et alimente déjà le soft-veto equity de `vix_scoring.py`. macro_context_service
# ignorait cette source vivante et refaisait (mal, et pour rien) sa propre
# tentative de fetch.
#
# Réparation (derrière ce drapeau) : vix_value est désormais résolu dans
# l'ordre (1) Twelve Data direct si un jour corrigé — conservé, coût nul —
# (2) `vix_service.get_current()` (Yahoo, déjà live, quasi temps réel), (3)
# `macro_daily` (backend/services/macro_data.py, Yahoo quotidien depuis
# 2024, asof T-1 jour, no look-ahead) — (4) None si tout échoue. Plus aucun
# retour furtif à 17.0 : une mesure absente reste None et se voit.
#
# Mesure d'impact (rejeu de 277 651 signaux de mai-août 2026, VIX réel via
# macro_daily contre le VIX constant actuel, à base_score et tout le reste
# identiques — seule la variable VIX change entre les deux passes) :
#   - VIX affecte le multiplicateur sur 3,2% des signaux (8 841 / 277 651) —
#     seules les paires où VIX intervient dans macro_scoring._primaries_for
#     (JPY, CHF, XAU/XAG, crypto, indices actions) sont concernées.
#   - Distribution quasi inchangée globalement (médiane 58,4 -> 58,4,
#     écart-type 9,97 -> 10,16) : l'effet est réel mais localisé, pas un
#     décalage uniforme façon barème v2.
#   - Bascules de seuil sur les lignes affectées : seuil 42 -> 1 853
#     bascules (0,67%, majorité en défaveur : 1 489 perdent le seuil contre
#     364 qui le gagnent) ; seuil 61 -> 2 966 (1,07%, quasi équilibré :
#     1 433 gagnent / 1 533 perdent) ; seuil 71 -> 1 417 (0,51%, très
#     majoritairement EN FAVEUR : 1 264 gagnent le seuil contre 153 qui le
#     perdent).
#   - Concentré sur les pics de volatilité, pas diffus : le VIX réel n'est
#     sorti de la zone "normal" (15-20) qu'en juin-juillet 2026 (5,8% des
#     lignes en "elevated", jamais "high" ni "low" sur la fenêtre) — mai et
#     août montrent un delta strictement nul (VIX resté dans le même bucket
#     que la constante 17.0 tout le mois).
#   - Paires les plus concernées : XAU/USD, USD/CHF, ETH/USD, BTC/USD,
#     USD/JPY, XAG/USD, GBP/JPY, EUR/JPY.
#
# DÉSACTIVÉ PAR DÉFAUT — MACRO_SCORING_ENABLED est déjà `true` en production
# aujourd'hui : ce drapeau agit directement sur le multiplicateur consulté
# par le dispatch réel (macro_scoring.apply, appelé depuis analysis_engine),
# pas seulement sur du logging shadow. Les seuils 42/61/71 ont été calibrés
# avec cette couche VIX morte (donc neutre côté seuil bas 42, où VIX ne
# jouait déjà aucun rôle). Avant d'activer :
#   1. Confirmer que le job "vix_refresh" reste actif en prod (5 min, Yahoo)
#      et que macro_daily continue d'être alimenté (cron fetch-all).
#   2. Vérifier sur un échantillon shadow récent que la répartition
#      "3,2% des signaux affectés / bascules concentrées sur seuil 61" tient
#      toujours (les chiffres ci-dessus datent d'une fenêtre calme en VIX).
#   3. Décider si le seuil 61 (le plus sensible, quasi 50/50 gagnants vs
#      perdants) doit être recalibré avant activation, ou si le déséquilibre
#      42 (défavorable) / 71 (favorable) est acceptable tel quel.
MACRO_VIX_REAL_SOURCE_ENABLED = os.getenv("MACRO_VIX_REAL_SOURCE_ENABLED", "false").lower() in ("1", "true", "yes", "on")

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

# Paires pour lesquelles le veto geopolitique est CONSULTATIF (2026-08-08) :
# il se prononce et reste enregistre, mais ne bloque pas. Vide par defaut.
#
# Pose apres constat : la regle `gdelt_stress` est documentee pour les indices
# europeens, son seuil a ete assoupli de `high` a `{high, elevated}` parce
# qu'elle ne matchait jamais, puis son perimetre etendu a BTC/ETH. Les deux
# seules fois ou elle s'est declenchee en 30 jours (2 refus sur 72 081), elle
# a bloque 100 % du flux crypto journalier. Aucune preuve mesuree ne la
# soutient -- le controle aleatoire du 2026-08-05 couvre toute la pile de
# vetos sans lui trouver d'apport.
#
# Le verdict contrefactuel continue d'etre calcule et logue par le shadow :
# on garde de quoi juger la regle plus tard, on retire seulement le blocage.
GEOPOLITICAL_VETO_ADVISORY_PAIRS = frozenset(
    p.strip().upper()
    for p in os.getenv("GEOPOLITICAL_VETO_ADVISORY_PAIRS", "").split(",")
    if p.strip()
)

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
