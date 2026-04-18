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
    "XAU/USD,EUR/USD,GBP/USD,USD/JPY,EUR/GBP,USD/CHF,AUD/USD,USD/CAD,EUR/JPY,GBP/JPY"
).split(",")

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
