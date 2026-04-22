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
    if p.startswith(("BTC", "ETH", "LTC", "XRP", "SOL", "ADA", "DOGE")) or p.endswith(("/BTC", "/ETH")):
        return "crypto"
    if p.startswith(("XAU", "XAG", "XPT", "XPD")):
        return "metal"
    if p.startswith(("WTI", "BRENT", "XTI", "XBR", "NGAS", "NATGAS")):
        return "energy"
    if p in {"SPX", "NDX", "DJI", "RUT", "DAX", "N225", "NIKKEI", "FTSE", "CAC40", "UK100", "US30", "US500", "NAS100", "DE40", "EU50", "JP225"}:
        return "equity_index"
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
# Force minimum pour qu'un signal soit envoye : weak / moderate / strong
TELEGRAM_MIN_STRENGTH = os.getenv("TELEGRAM_MIN_STRENGTH", "strong")

# ─── Bridge MT5 (auto-exec sur MetaTrader 5 desktop local) ──────────
# URL du bridge MT5 accessible via Tailscale (ex: http://100.122.188.8:8787).
# Le bridge doit tourner sur le PC Windows de l'utilisateur.
MT5_BRIDGE_URL = os.getenv("MT5_BRIDGE_URL", "")
MT5_BRIDGE_API_KEY = os.getenv("MT5_BRIDGE_API_KEY", "")
# Activation globale : si false, le radar détecte les setups mais NE POUSSE
# RIEN au bridge. true = push auto (bridge en paper par défaut → sans risque
# financier tant que le bridge est en PAPER_MODE).
MT5_BRIDGE_ENABLED = os.getenv("MT5_BRIDGE_ENABLED", "false").lower() in ("1", "true", "yes", "on")
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
# Cap par pair : N positions max SIMULTANÉMENT sur la même paire. Forcé
# de diversifier, évite la concentration aveugle (ex: 4 XAU/USD ouverts
# qui tombent ensemble sur un mouvement défavorable).
#
# Dict JSON par asset class. Surchargeable via env MT5_BRIDGE_MAX_POSITIONS_PER_PAIR.
MT5_BRIDGE_MAX_POSITIONS_PER_PAIR_DEFAULT = {
    "forex": 2,
    "metal": 2,
    "equity_index": 1,
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
