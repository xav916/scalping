"""
MT5 Bridge — pilote MT5 Desktop depuis un HTTP local.

Architecture :
    Scalping Radar (EC2)
        └── POST /order ──► Bridge HTTP (ce fichier, tourne sur le PC Windows)
                              └── MetaTrader5 package ──► MT5 Desktop (local)

Sécurité :
- Bind sur 127.0.0.1 par défaut (pas exposé sur le réseau).
- Tous les endpoints sensibles demandent l'en-tête X-API-Key.
- PAPER_MODE=true par défaut : aucun ordre réel n'est envoyé à MT5.
- Les credentials sont lus depuis .env (gitignored).
"""

import hashlib
import logging
import json
import math
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone, date
from functools import wraps
from pathlib import Path

import MetaTrader5 as mt5
from dotenv import load_dotenv
from flask import Flask, jsonify, request

# ─── Empreinte de la source ────────────────────────────────────────────
# ⛔ Calculee A L'IMPORT, jamais a la requete. Un fichier edite sur disque
# n'est pas le code que le processus execute : hacher a la requete
# annoncerait la NOUVELLE version tout en faisant tourner l'ANCIENNE, ce qui
# est pire que pas d'empreinte du tout. Le champ dit donc ce qui a ete CHARGE.
#
# Pourquoi elle existe (2026-08-25) : sur le bridge Kraken, un repli de
# resolution de symbole a disparu sans que personne le voie, faute de pouvoir
# comparer ce qui tourne a ce qui est versionne. Meme raison que le bloc
# `garde_fous` ci-dessous : un ecart qu'on ne peut pas lire est un ecart dont
# on ne sait jamais s'il existe. Comparer avec :
#     sha256sum mt5-bridge/bridge.py | cut -c1-12
def _empreinte_source() -> str:
    try:
        with open(__file__, "rb") as fichier:
            octets = fichier.read()
    except Exception:  # noqa: BLE001 — une empreinte absente ne casse rien
        return "inconnue"
    # ⚠️ Fins de ligne normalisees AVANT le hachage. Les fichiers du VPS sont
    # en CRLF, le depot est stocke en LF, et git reconvertit a la sortie : sans
    # cela, deux copies au contenu IDENTIQUE annonceraient des empreintes
    # differentes, et la comparaison — seule raison d'etre de ce champ —
    # crierait a la derive en permanence.
    # Sequences construites par code : ecrire une sequence d echappement
    # dans un fichier qui en contient deja est une source d erreur inutile.
    return hashlib.sha256(
        octets.replace(bytes([13, 10]), bytes([10]))
    ).hexdigest()[:12]


SOURCE_SHA = _empreinte_source()
DEMARRE_A = datetime.now(timezone.utc).isoformat(timespec="seconds")



load_dotenv()

# ─── Configuration ──────────────────────────────────────────────────
MT5_LOGIN = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "MetaQuotes-Demo")
# v2026-06-12 : path explicite vers terminal64.exe quand 2 MT5 tournent en
# parallèle (Demo Pepperstone + Live IC Markets). Sans path, le Python lib
# attache au 1er terminal trouvé via registry, ce qui crée un conflit. Avec
# MT5_TERMINAL_PATH set, chaque bridge.py attache à son propre terminal.
# Vide = comportement legacy (auto-discovery via registry).
MT5_TERMINAL_PATH = os.getenv("MT5_TERMINAL_PATH", "")
BRIDGE_API_KEY = os.getenv("BRIDGE_API_KEY", "")
PAPER_MODE = os.getenv("PAPER_MODE", "true").lower() in ("1", "true", "yes", "on")
MAX_LOT = float(os.getenv("MAX_LOT", "0.1"))
# Caps par asset class en plus du MAX_LOT global. JSON env var, ex:
# MAX_LOT_PER_CLASS='{"forex":0.1,"metal":0.1,"crypto":0.01,"equity_index":0.05,"energy":0.1}'
# Le lot final = min(MAX_LOT, MAX_LOT_PER_CLASS[class]). Une classe absente
# tombe sur MAX_LOT global (pas de cap supplémentaire).
try:
    _max_lot_per_class_raw = os.getenv("MAX_LOT_PER_CLASS", "").strip()
    MAX_LOT_PER_CLASS = json.loads(_max_lot_per_class_raw) if _max_lot_per_class_raw else {}
    if not isinstance(MAX_LOT_PER_CLASS, dict):
        MAX_LOT_PER_CLASS = {}
except (json.JSONDecodeError, TypeError):
    MAX_LOT_PER_CLASS = {}
LISTEN_HOST = os.getenv("LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(os.getenv("LISTEN_PORT", "8787"))
BREAKEVEN_TRIGGER_PCT = float(os.getenv("BREAKEVEN_TRIGGER_PCT", "50"))
MONITOR_INTERVAL_SEC = int(os.getenv("MONITOR_INTERVAL_SEC", "5"))
# Rails LIVE
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", "3.0"))
# Tickets dont le flottant NE COMPTE PAS dans le drawdown journalier
# (2026-08-07). Une position tenue volontairement hors du système — sans stop,
# conservée jusqu'à son objectif — confisque sinon le garde-fou de TOUTES les
# autres : le drawdown mesure la perte LATENTE, donc un flottant de -179 EUR
# sur un compte de 531 EUR bloquait le compte entier, et relever le plafond ne
# faisait que déplacer le seuil (il aurait fallu dépasser 34 %).
#
# ⚠️ Nominatif, jamais global : chaque ticket listé est une protection en
# moins. Vide par défaut. L'exclusion s'éteint d'elle-même à la fermeture de
# la position — un ticket fermé n'est plus rendu par `positions_get()`.
DAILY_LOSS_EXCLUDED_TICKETS = frozenset(
    int(t.strip())
    for t in os.getenv("DAILY_LOSS_EXCLUDED_TICKETS", "").split(",")
    if t.strip().isdigit()
)
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "3"))
# ─── Plafond par le RISQUE, et non par le nombre (2026-08-20) ──────────────
# Un compteur traite toutes les positions comme equivalentes alors qu'elles ne
# le sont pas : 0,01 lot de forex immobilise ~37 EUR et risque ~5,5 EUR, 0,01
# lot d'or immobilise ~191 EUR. « 3 positions » peut donc valoir 110 EUR ou
# 570 EUR d'engagement. Et le chiffre ne suit pas le capital.
#
# On borne donc la somme des risques REELS — chaque position, sa distance a
# son stop — plus celui de l'ordre demande. La limite s'ajuste alors seule
# selon l'instrument et grandit avec l'equity.
#
# 0 = desarme (comportement d'avant, seul le compteur agit).
MAX_RISQUE_ENGAGE_PCT = float(os.getenv("MAX_RISQUE_ENGAGE_PCT", "6.0"))
# Plancher de marge libre, en % de l'equity. Second garde-fou, CONTRE UN AUTRE
# DANGER : la marge protege de la liquidation, le risque protege de la perte.
# Des stops tres serres autorisent beaucoup de positions a risque constant —
# c'est precisement le cas ou la marge sature sans que le risque ne bouge.
MARGE_LIBRE_MIN_PCT = float(os.getenv("MARGE_LIBRE_MIN_PCT", "30.0"))
# ─── Deux POCHES de risque, jamais fongibles (2026-08-28) ──────────────────
# Demande de Xavier : porter le risque cumule autorise de 6 % a 20 %, mais
# **pas en un seul reservoir**. Les 6 % d'origine restent a tout ce qui n'est
# pas de l'or, et 14 % supplementaires sont reserves a l'OR SEUL, pour lui
# laisser du mouvement sans que le reste du portefeuille en profite.
#
# ⛔ Non fongibles dans les DEUX sens : l'or ne peut pas manger le budget du
# forex, et le forex ne peut pas manger celui de l'or. Un reservoir unique de
# 20 % aurait aussi autorise 20 % de forex — ce n'est pas ce qui est demande,
# et ca n'a jamais ete mesure.
#
# 0 = l'or retombe dans la poche commune : l'etat exact d'avant le 28/08.
MAX_RISQUE_ENGAGE_OR_PCT = float(os.getenv("MAX_RISQUE_ENGAGE_OR_PCT", "14.0"))

# ─── Remontee du stop a l'EQUILIBRE pour liberer du risque (2026-08-23) ───
# Quand la porte des 6 % refuserait un ordre, on remonte a l'entree le stop de
# positions deja largement gagnantes : leur risque tombe a zero sans rien
# fermer, sans payer de spread, sans tronquer leur potentiel.
#
# ⚠️ `EQUILIBRE_MARGE_R` est le garde-fou qui separe ce mecanisme d'un
# SUIVEUR. Sous ce coussin de profit, un stop pose a l'equilibre est colle au
# marche et se fait sortir par le bruit — la mecanique exacte qui a coute
# −0,329 R par trade sur l'or. 1,0 R = on ne touche qu'une position ayant
# deja acquis l'equivalent de son propre risque.
EQUILIBRE_AUTO_ENABLED = os.getenv("EQUILIBRE_AUTO_ENABLED", "true").lower() == "true"
EQUILIBRE_MARGE_R = float(os.getenv("EQUILIBRE_MARGE_R", "1.0"))

# ─── Porte de BRUIT, en ecarts-types journaliers (2026-08-24) ──────────
# ⛔ Le defaut du seuil en R n'est pas sa valeur, c'est son UNITE. Le meme
# `0,40 R` place le stop a des distances du bruit qui varient d'un facteur
# 4,5 selon l'instrument — mesure sur 1067 bougies H1 chez le courtier :
#
#     EUR/GBP 1,07 σ · GBP/USD 0,80 σ · GBP/JPY 0,48 σ · USD/JPY 0,24 σ
#
# A 0,24 σ on est au BE 0 %, la seule politique SANS suiveur mesuree
# significativement destructrice (−0,099 R, t = −2,61).
#
# ⇒ Les deux conditions se CUMULENT : le plancher en R (politique) ET la
# porte de bruit en σ. La plus stricte des deux mord.
# 0 desarme la porte et rend exactement le comportement d'avant.
EQUILIBRE_MARGE_SIGMA = float(os.getenv("EQUILIBRE_MARGE_SIGMA", "1.0"))
# Fenetre de mesure de la volatilite, en heures. 720 h = 30 jours : assez
# pour un ecart-type stable, assez court pour decrire le regime courant.
EQUILIBRE_VOL_HEURES = int(os.getenv("EQUILIBRE_VOL_HEURES", "720"))
# La volatilite ne bouge pas d'une minute a l'autre : un calcul par jour
# suffit, et evite d'appeler MT5 sur le chemin d'un ordre.
EQUILIBRE_VOL_TTL_SEC = int(os.getenv("EQUILIBRE_VOL_TTL_SEC", "86400"))
# ⛔ Plancher de plausibilite : sous cette volatilite journaliere RELATIVE, on
# refuse de conclure. Un flux gele rend un sigma minuscule mais positif, ce qui
# rendrait TOUTE position eligible (fail-open). Le forex reel vaut 0,15-0,75 %.
# ⚠️ Duplique dans `scripts/notify_saturation_risque.py` : les deux tournent
# sur des machines differentes. Toute modification ici doit y etre repercutee.
SIGMA_REL_MIN = float(os.getenv("SIGMA_REL_MIN", "0.0001"))
DEDUP_WINDOW_SEC = int(os.getenv("DEDUP_WINDOW_SEC", "300"))
DEVIATION_POINTS = int(os.getenv("DEVIATION_POINTS", "20"))
MAGIC_NUMBER = int(os.getenv("MAGIC_NUMBER", "20260419"))
TRADING_HOURS_UTC = os.getenv("TRADING_HOURS_UTC", "").strip()
# Partial close + trailing
PARTIAL_CLOSE_PCT = float(os.getenv("PARTIAL_CLOSE_PCT", "50"))
TRAIL_DISTANCE_POINTS = int(os.getenv("TRAIL_DISTANCE_POINTS", "150"))

# Broker-specific symbol mapping. Surcharge la résolution par défaut quand
# le broker utilise un alias non-trivial (ex. Pepperstone : WTI/USD → USOIL).
# Format env : MT5_SYMBOL_MAP="WTI/USD:USOIL,XYZ:ABC". Le mapping s'applique
# AVANT les fallbacks classiques (suffixes .c/.m/.pro/.raw) — donc même si on
# mappe vers USOIL, on tente USOIL, USOIL.c, USOIL.m, etc. au cas où le
# broker re-suffixe.
def _parse_symbol_map(raw: str) -> dict[str, str]:
    m: dict[str, str] = {}
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if ":" not in entry:
            continue
        k, v = entry.split(":", 1)
        k, v = k.strip(), v.strip()
        if k and v:
            m[k] = v
    return m

MT5_SYMBOL_MAP = _parse_symbol_map(os.getenv("MT5_SYMBOL_MAP", ""))

# ─── Garde-fou SL/TP sur position déjà ouverte ───────────────────────
# Route dédiée (/position/sltp, cf. plus bas) + garde-fou cron côté EC2
# (scripts/check-live-positions-sltp.sh) qui pose un SL sur une position
# LIVE découverte sans stop. Désactivé par défaut : poser un ordre
# automatique sur de l'argent réel est un changement de comportement qui
# doit s'allumer sciemment.
#
# Incident déclencheur (2026-08-05) : position XAU/USD ouverte à 02:09 UTC
# sans SL ni TP (échec silencieux de _apply_sltp_from_fill, cf. plus bas),
# découverte 7h après à -51€. Elle est restée volontairement sans stop sur
# décision assumée du propriétaire — d'où l'exigence absolue ci-dessous :
# ce garde-fou ne doit JAMAIS toucher une position déjà ouverte au moment
# de sa mise en service.
SLTP_GUARD_ENABLED = os.getenv("SLTP_GUARD_ENABLED", "false").lower() in ("1", "true", "yes", "on")
# Horodatage ISO8601 UTC à partir duquel une position devient éligible au
# garde-fou (ex: "2026-08-06T12:00:00+00:00"). Fixé UNE FOIS, à la main, au
# moment de l'activation — jamais recalculé automatiquement au démarrage
# (sinon une position ouverte avant un simple redémarrage du bridge
# deviendrait éligible par erreur). Une position ouverte à cet instant ou
# avant reste gelée pour toujours. Vide = on ne sait pas dater l'activation
# ⇒ fail-closed, aucune position n'est éligible (cf. `_sltp_guard_eligible`).
SLTP_GUARD_ACTIVATED_AT = os.getenv("SLTP_GUARD_ACTIVATED_AT", "").strip()
# Gel explicite par ticket, en plus de l'horodatage — ceinture et bretelles
# pour une position nommément identifiée (ex: la position XAU/USD de
# l'incident, dont le propriétaire a refusé explicitement qu'un stop y soit
# posé). Format : "123456,789012".
SLTP_GUARD_FROZEN_TICKETS = frozenset(
    int(t) for t in os.getenv("SLTP_GUARD_FROZEN_TICKETS", "").split(",")
    if t.strip().isdigit()
)


def _parse_iso_to_epoch(raw: str) -> int | None:
    """Parse un horodatage ISO8601 en epoch UTC. None si vide ou invalide —
    jamais une valeur par défaut plausible (cf. SLTP_GUARD_ACTIVATED_AT)."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        return None


_SLTP_GUARD_ACTIVATED_AT_EPOCH = _parse_iso_to_epoch(SLTP_GUARD_ACTIVATED_AT)


def _sltp_guard_eligible(ticket: int, position_open_epoch: int) -> tuple[bool, str]:
    """Décide si une position peut recevoir un stop automatique du garde-fou.

    Exclusion à double verrou, chacun suffisant seul pour bloquer :
    1. Liste explicite de tickets gelés (SLTP_GUARD_FROZEN_TICKETS) — gèle
       une position précise pour toujours, quelle que soit sa date d'ouverture.
    2. Horodatage d'activation (SLTP_GUARD_ACTIVATED_AT) — une position
       ouverte AVANT (ou au même instant que) cet horodatage n'est JAMAIS
       éligible, même après un redémarrage du bridge. Non défini = on ne
       sait pas si la position est antérieure à l'activation ⇒ fail-closed,
       rien n'est éligible plutôt que de deviner.
    """
    if ticket in SLTP_GUARD_FROZEN_TICKETS:
        return False, "ticket explicitement gelé (SLTP_GUARD_FROZEN_TICKETS)"
    if _SLTP_GUARD_ACTIVATED_AT_EPOCH is None:
        return False, "SLTP_GUARD_ACTIVATED_AT non défini — impossible de dater l'activation"
    if position_open_epoch <= _SLTP_GUARD_ACTIVATED_AT_EPOCH:
        return False, "position ouverte avant (ou à) l'activation du garde-fou"
    return True, "OK"


# Génère une clé si absente (affichée au démarrage pour copie dans le client)
if not BRIDGE_API_KEY:
    BRIDGE_API_KEY = secrets.token_urlsafe(24)
    _KEY_AUTOGENERATED = True
else:
    _KEY_AUTOGENERATED = False

# ─── Logging ────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bridge.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("bridge")

# ─── App Flask ──────────────────────────────────────────────────────
app = Flask(__name__)


def require_api_key(f):
    """Décorateur : exige l'en-tête X-API-Key, comparé en constant-time."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        provided = request.headers.get("X-API-Key", "")
        if not secrets.compare_digest(provided, BRIDGE_API_KEY):
            return jsonify({"error": "Invalid or missing X-API-Key"}), 401
        return f(*args, **kwargs)
    return wrapped


# ─── Connexion MT5 ──────────────────────────────────────────────────

def ensure_mt5_connected() -> bool:
    """Initialise MT5 si pas déjà fait. Retourne True si connecté."""
    # Si déjà initialisé et un compte est attaché, on ne reconnecte pas.
    if mt5.account_info() is not None:
        return True
    # Avec path explicite (parallèle Demo+Live), on cible un terminal précis.
    init_kwargs = {"login": MT5_LOGIN, "password": MT5_PASSWORD, "server": MT5_SERVER}
    if MT5_TERMINAL_PATH:
        init_kwargs["path"] = MT5_TERMINAL_PATH
    if not mt5.initialize(**init_kwargs):
        err = mt5.last_error()
        logger.error(f"mt5.initialize() a échoué : {err}")
        return False
    info = mt5.account_info()
    if info is None:
        err = mt5.last_error()
        logger.error(f"account_info() None après init : {err}")
        return False
    logger.info(
        f"MT5 connecté : login={info.login} server={MT5_SERVER} "
        f"balance={info.balance} {info.currency}"
    )
    return True


def resolve_symbol(pair_str: str):
    """Traduit un format 'EUR/USD' vers le symbole réel du broker.

    MetaQuotes-Demo utilise typiquement 'EURUSD', mais les brokers peuvent
    suffixer (.c, .m, .pro, etc.). On tente plusieurs variantes et on
    retourne la première qui existe et est sélectionnable.

    Si la pair est dans MT5_SYMBOL_MAP (env var), le mapping broker-specific
    est testé en priorité (ex. Pepperstone WTI/USD → USOIL).
    """
    base = pair_str.replace("/", "")
    candidates: list[str] = []
    # 1) Override broker-specific (priorité haute)
    mapped = MT5_SYMBOL_MAP.get(pair_str)
    if mapped:
        mapped_base = mapped.replace("/", "")
        candidates.extend([
            mapped,
            mapped_base,
            mapped_base + ".c",
            mapped_base + ".m",
            mapped_base + "m",
            mapped_base + ".pro",
            mapped_base + ".raw",
        ])
    # 2) Variantes par défaut
    candidates.extend([
        pair_str,        # EUR/USD littéral
        base,            # EURUSD
        base + ".c",
        base + ".m",
        base + "m",
        base + ".pro",
        base + ".raw",
    ])
    for c in candidates:
        info = mt5.symbol_info(c)
        if info is None:
            continue
        if not info.visible:
            if not mt5.symbol_select(c, True):
                continue
        return c
    return None


# ─── Audit DB (SQLite local, persiste entre redémarrages) ──────────

_DB_PATH = Path(__file__).parent / "bridge_audit.db"
_db_lock = threading.Lock()


def _db_init() -> None:
    """Crée la table d'audit si elle n'existe pas + migre les colonnes manquantes."""
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                mode TEXT NOT NULL,       -- 'paper' | 'live'
                status TEXT NOT NULL,     -- 'filled' | 'rejected' | 'blocked' | 'error' | 'closed'
                pair TEXT,
                symbol TEXT,
                direction TEXT,
                lots REAL,
                entry REAL,
                sl REAL,
                tp REAL,
                risk_money REAL,
                ticket INTEGER,
                retcode INTEGER,
                message TEXT,
                client_comment TEXT
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_ticket ON orders(ticket);")
        # Migration : ajoute exit_price + pnl + confidence si DB ancienne
        cols = [r[1] for r in conn.execute("PRAGMA table_info(orders)").fetchall()]
        if "exit_price" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN exit_price REAL")
        if "pnl" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN pnl REAL")
        if "confidence" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN confidence REAL")
        # Migration 2026-08-06 — mesure du coût d'exécution.
        #
        # ⚠️ La colonne `entry` contient le prix OBTENU (`result.price`), pas le
        # prix demandé : le planifié était écrasé à l'écriture. Le backend
        # comparait donc le fill à lui-même, ce qui explique `slippage_pips`
        # vide sur 1581/1581 trades. `entry` reste inchangée par continuité —
        # `personal_trades.entry_price` en dépend — et les deux colonnes
        # ci-dessous apportent la moitié manquante de la comparaison.
        if "entry_requested" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN entry_requested REAL")
        if "fill_price" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN fill_price REAL")
        if "fill_source" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN fill_source TEXT")
        # Migration 2026-08-17 — la cause de clôture à la SOURCE.
        #
        # MT5 sait pourquoi une position s'est fermée (`deal.reason`), et
        # `_log_closed_position` avait cette valeur sous la main sans l'écrire.
        # Le radar recevait donc une clôture SANS cause et la devinait par
        # proximité de prix : trois sorties décidées à la main le 08-17 ont été
        # créditées au stop suiveur, le mécanisme désarmé le 08-11 pour
        # destruction de valeur.
        if "close_reason" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN close_reason TEXT")
        # Niveaux VIVANTS au moment de la clôture (2026-08-24). MT5 ne garde
        # aucune trace des `TRADE_ACTION_SLTP` : sans cette capture, le niveau
        # réellement porté par la position est perdu à la seconde où elle
        # ferme. 44 % des niveaux stockés en base se sont révélés faux.
        # Cf. `_derniers_niveaux`.
        if "sl_at_close" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN sl_at_close REAL")
        if "tp_at_close" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN tp_at_close REAL")
        if "niveau_declencheur" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN niveau_declencheur REAL")
        # `monitor` (niveaux vus vivants) vs `ordre_declencheur` (reconstruit
        # après coup, partiel). Sans ce champ, les deux se liraient pareil.
        if "niveaux_source" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN niveaux_source TEXT")
        conn.commit()


def _db_log_order(**fields) -> None:
    """Insère une ligne d'audit. Tous les champs sont optionnels (sauf status/mode)."""
    fields.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    cols = list(fields.keys())
    placeholders = ",".join("?" * len(cols))
    sql = f"INSERT INTO orders ({','.join(cols)}) VALUES ({placeholders})"
    try:
        with _db_lock, sqlite3.connect(_DB_PATH) as conn:
            conn.execute(sql, tuple(fields.values()))
            conn.commit()
    except Exception as e:
        logger.warning(f"audit DB write failed: {e}")


# ─── Rails de sécurité LIVE ─────────────────────────────────────────

# Balance de début de journée (pour le drawdown) — réinitialisée à chaque jour.
_start_of_day_balance: float | None = None
_start_of_day_date: date | None = None


def _refresh_start_of_day() -> None:
    """Relit la balance au début de chaque jour trading.

    Ajout 2026-07-31 : filet de sécurité anti-drift. Si le cache diverge de la
    balance actuelle d'un facteur > 1.5x (dans un sens ou l'autre), resync
    immédiat. Couvre les retraits/dépôts entre les redémarrages du bridge, ou
    les états stale d'anciennes sessions où la balance était très différente.
    """
    global _start_of_day_balance, _start_of_day_date
    today = date.today()
    info = mt5.account_info()
    if info is None:
        return
    # Refresh normal au changement de jour UTC
    if _start_of_day_date != today:
        _start_of_day_balance = info.balance
        _start_of_day_date = today
        logger.info(
            f"Start-of-day balance = {_start_of_day_balance:.2f} "
            f"(date={today.isoformat()})"
        )
        return
    # Anti-drift : cache irréaliste vs balance actuelle → resync
    if _start_of_day_balance is not None and info.balance > 0:
        ratio = _start_of_day_balance / info.balance
        if ratio > 1.5 or ratio < 0.667:
            logger.warning(
                f"Start-of-day balance drift detected: cached="
                f"{_start_of_day_balance:.2f} actual={info.balance:.2f} "
                f"ratio={ratio:.2f} - resync"
            )
            _start_of_day_balance = info.balance


def _flottant_exclu(positions) -> tuple[float, list[int]]:
    """Flottant cumulé des positions explicitement exclues du drawdown.

    Rendu séparément de l'``equity`` pour que le garde-fou puisse mesurer ce
    que font les trades du système SANS le flottant d'une position tenue à
    part. Pur et testable : reçoit les positions, n'interroge pas MT5.

    Signe : on rend la somme des ``profit`` telle quelle. L'appelant fait
    ``equity - exclu``, ce qui neutralise aussi bien une perte latente
    (l'equity remonte) qu'un gain latent (elle redescend) — sans quoi une
    position exclue en profit masquerait les pertes des autres.
    """
    if not DAILY_LOSS_EXCLUDED_TICKETS:
        return 0.0, []
    total = 0.0
    vus: list[int] = []
    for p in positions or []:
        if getattr(p, "ticket", None) in DAILY_LOSS_EXCLUDED_TICKETS:
            total += float(getattr(p, "profit", 0.0) or 0.0)
            vus.append(p.ticket)
    return total, vus


def _parse_trading_hours(window: str) -> list[tuple[int, int]]:
    """Parse 'HH:MM-HH:MM,HH:MM-HH:MM' en [(minutes_from_midnight_start, end)]."""
    ranges = []
    if not window:
        return ranges
    for chunk in window.split(","):
        chunk = chunk.strip()
        if "-" not in chunk:
            continue
        a, b = chunk.split("-", 1)
        try:
            ah, am = [int(x) for x in a.split(":")]
            bh, bm = [int(x) for x in b.split(":")]
            ranges.append((ah * 60 + am, bh * 60 + bm))
        except ValueError:
            continue
    return ranges


def _in_trading_hours() -> bool:
    """Vrai si TRADING_HOURS_UTC est vide OU si maintenant (UTC) est dans une plage."""
    if not TRADING_HOURS_UTC:
        return True
    now_utc = datetime.now(timezone.utc)
    now_min = now_utc.hour * 60 + now_utc.minute
    for start, end in _parse_trading_hours(TRADING_HOURS_UTC):
        if start <= now_min <= end:
            return True
    return False


def _check_safety_gates(mt5_symbol: str, direction: str,
                        lots: float | None = None,
                        entry: float | None = None,
                        sl: float | None = None) -> tuple[bool, str]:
    """Vérifie tous les garde-fous avant d'envoyer un ordre LIVE.

    Retourne (ok, reason). Si ok=False, 'reason' est la raison du blocage
    (à remonter dans la réponse HTTP et loggée dans l'audit DB).

    ``lots`` / ``entry`` / ``sl`` (2026-08-20) décrivent l'ordre demandé et
    n'activent que les portes qui en dépendent — risque engagé et marge
    libre. Absents, ces deux portes sont sautées : le reste des garde-fous
    ne change pas.

    ⚠️ Ces portes vivent **ici** et non dans `/order`. Un garde-fou pose hors
    de la fonction qui les rassemble echappe a tout ce qui la neutralise —
    les tests qui isolent un autre sujet en stubbant `_check_safety_gates`
    l'auraient contourne sans que personne ne le voie.
    """
    if not _in_trading_hours():
        return False, f"Outside TRADING_HOURS_UTC ({TRADING_HOURS_UTC})"

    info = mt5.account_info()
    if info is None:
        return False, "Cannot read account_info"

    # Lu une seule fois : sert au drawdown (exclusions) puis au plafond.
    positions = mt5.positions_get() or []

    # Drawdown journalier
    _refresh_start_of_day()
    if _start_of_day_balance is not None:
        loss_limit = _start_of_day_balance * MAX_DAILY_LOSS_PCT / 100.0
        exclu, tickets_exclus = _flottant_exclu(positions)
        equity_retenue = info.equity - exclu
        current_loss = _start_of_day_balance - equity_retenue
        if tickets_exclus:
            # Tracé à chaque passage : une protection affaiblie qui ne se voit
            # pas dans les logs est une protection qu'on oublie d'avoir levée.
            logger.info(
                f"Drawdown: flottant exclu {exclu:+.2f} "
                f"(tickets {sorted(tickets_exclus)}) — equity retenue "
                f"{equity_retenue:.2f} au lieu de {info.equity:.2f}"
            )
        if current_loss >= loss_limit:
            return False, (
                f"Daily drawdown reached: loss={current_loss:.2f} "
                f">= limit={loss_limit:.2f} ({MAX_DAILY_LOSS_PCT}% of "
                f"{_start_of_day_balance:.2f})"
            )

    # Max positions ouvertes — garde-fou d'EMBALLEMENT, pas de risque : il ne
    # distingue pas 0,01 lot de forex (~5,5 EUR risques) de 0,01 lot d'or
    # (~27 EUR). Le plafond qui compte est celui du risque engage, juste en
    # dessous ; celui-ci ne reste que comme borne dure.
    if len(positions) >= MAX_OPEN_POSITIONS:
        return False, (
            f"Max open positions reached: {len(positions)} >= {MAX_OPEN_POSITIONS}"
        )

    # ─── Plafond par le RISQUE ENGAGE (2026-08-20) ────────────────────────
    # N'agit que si l'ordre demande est decrit : c'est le lot REELLEMENT
    # retenu et son stop qu'il faut juger, pas ceux qu'on souhaitait.
    if lots is not None and sl is not None and entry is not None:
        specs = mt5.symbol_info(mt5_symbol)
        # ─── Deux poches depuis le 2026-08-28 : l'or a la sienne ──────────
        # L'ordre demande n'est juge que contre SA poche, et le budget de
        # l'autre ne lui est jamais pretable — meme vide. C'est toute la
        # difference avec un reservoir unique de 20 %.
        or_separe = MAX_RISQUE_ENGAGE_OR_PCT > 0
        poche = _poche_du_symbole(mt5_symbol) if or_separe else _POCHE_HORS_OR
        plafond_pct = (MAX_RISQUE_ENGAGE_OR_PCT if poche == _POCHE_OR
                       else MAX_RISQUE_ENGAGE_PCT)
        totaux, non_bornables = _risque_engage_par_poche(
            positions, mt5.symbol_info, or_separe=or_separe)
        ouvert = totaux[poche]
        nouveau = (_risque_realise(entry, sl, lots, specs.point,
                                   specs.trade_tick_value)
                   if specs is not None else None)

        ok_risque, motif = _controle_risque_engage(
            ouvert, non_bornables, nouveau, float(info.equity),
            plafond_pct, poche=poche)

        # ─── Dernier recours : libérer du risque plutôt que refuser ───────
        # Demandé explicitement le 2026-08-23. Plutôt que de renoncer au
        # nouveau setup, on remonte à l'ÉQUILIBRE le stop de positions déjà
        # largement gagnantes : leur risque tombe à zéro sans rien fermer,
        # sans payer de spread, sans tronquer leur potentiel de hausse.
        #
        # ⚠️ Ce mécanisme reste de la GESTION DE SORTIE, la famille qui a
        # mesuré −0,329 R sur l'or. Trois différences le rendent défendable :
        # il ne se déclenche QUE lorsqu'un trade serait refusé (mesuré : 1
        # fois en 30 jours), il exige un coussin de profit d'au moins
        # `EQUILIBRE_MARGE_R`, et chaque activation est journalisée pour
        # qu'on puisse un jour la JUGER au lieu d'y croire.
        if (not ok_risque and EQUILIBRE_AUTO_ENABLED and not non_bornables
                and nouveau is not None and float(info.equity) > 0):
            plafond = float(info.equity) * plafond_pct / 100.0
            manque = (ouvert + nouveau) - plafond
            # ⛔ Seules les positions de LA MEME poche liberent le budget qui
            # manque ici : remonter le stop d'un forex ne rend pas un euro a
            # l'or. Les chercher partout ferait deplacer des stops vivants
            # pour un refus qui tiendrait quand meme.
            memes_poche = [
                p for p in positions
                if not or_separe
                or _poche_du_symbole(getattr(p, "symbol", None)) == poche
            ]
            candidats = _candidats_equilibre(
                memes_poche, mt5.symbol_info, EQUILIBRE_MARGE_R,
                # La porte de BRUIT, en ecarts-types journaliers : le seuil en
                # R seul vaut 1,07 σ sur EUR/GBP et 0,24 σ sur USD/JPY, donc
                # aucune valeur ne peut etre bonne partout. Volatilite
                # inconnue ⇒ position ECARTEE, jamais laissee passer.
                sigmas=_sigma_journalier,
                marge_min_sigma=EQUILIBRE_MARGE_SIGMA)
            retenus = _choisir_pour_liberer(candidats, manque)
            if not retenus:
                logger.info(
                    f"equilibre: rien a liberer (manque {manque:.2f}, "
                    f"{len(candidats)} candidat(s) a >= {EQUILIBRE_MARGE_R}R) "
                    f"— refus maintenu")
            else:
                faits = _remonter_a_l_equilibre(retenus, positions)
                # ⛔ On RELIT les positions chez le courtier. Le nombre de
                # stops deplaces ne dit rien du risque reellement libere :
                # un clamp a pu laisser du risque, un ordre a pu echouer.
                positions = mt5.positions_get() or []
                totaux, non_bornables = _risque_engage_par_poche(
                    positions, mt5.symbol_info, or_separe=or_separe)
                ouvert = totaux[poche]
                ok_risque, motif = _controle_risque_engage(
                    ouvert, non_bornables, nouveau, float(info.equity),
                    plafond_pct, poche=poche)
                logger.info(
                    f"equilibre: {len(faits)}/{len(retenus)} stop(s) deplace(s), "
                    f"risque engage [{poche}] -> {ouvert:.2f} / plafond "
                    f"{plafond:.2f} — "
                    f"ordre {'ACCEPTE' if ok_risque else 'toujours refuse'}")

        if not ok_risque:
            return False, motif

        try:
            action = (mt5.ORDER_TYPE_BUY if direction == "buy"
                      else mt5.ORDER_TYPE_SELL)
            marge_nouvelle = mt5.order_calc_margin(
                action, mt5_symbol, lots, entry)
        except Exception as e:  # noqa: BLE001 — garde-fou secondaire
            logger.info(f"marge du nouvel ordre incalculable ({e}) — porte passee")
            marge_nouvelle = None

        ok_marge, motif_marge = _controle_marge_libre(
            float(info.margin_free), marge_nouvelle, float(info.equity),
            MARGE_LIBRE_MIN_PCT)
        if not ok_marge:
            return False, motif_marge

    # Dedup : refuse si même symbole + même sens ouvert depuis < DEDUP_WINDOW_SEC
    now_ts = int(datetime.now(timezone.utc).timestamp())
    wanted_type = mt5.POSITION_TYPE_BUY if direction == "buy" else mt5.POSITION_TYPE_SELL
    for p in positions:
        if p.symbol == mt5_symbol and p.type == wanted_type:
            if now_ts - p.time < DEDUP_WINDOW_SEC:
                age = now_ts - p.time
                return False, (
                    f"Duplicate: {direction} {mt5_symbol} already open (age {age}s "
                    f"< DEDUP_WINDOW_SEC={DEDUP_WINDOW_SEC}s, ticket #{p.ticket})"
                )

    return True, "OK"


# Bitmask des filling modes (certaines versions du package MT5 n'exposent pas
# les constantes mt5.SYMBOL_FILLING_* → on hardcode depuis la doc MQL5).
_SYMBOL_FILLING_FOK = 1
_SYMBOL_FILLING_IOC = 2
_SYMBOL_FILLING_BOC = 4


def _pick_filling_mode(symbol: str) -> int:
    """Choisit le filling mode compatible avec le broker pour ce symbole.

    symbol_info.filling_mode est un bitmask des modes supportés.
    On prend le premier qui matche : IOC > FOK > RETURN."""
    try:
        info = mt5.symbol_info(symbol)
        if info is None:
            return mt5.ORDER_FILLING_IOC
        fm = getattr(info, "filling_mode", 0) or 0
        if fm & _SYMBOL_FILLING_IOC:
            return mt5.ORDER_FILLING_IOC
        if fm & _SYMBOL_FILLING_FOK:
            return mt5.ORDER_FILLING_FOK
        return mt5.ORDER_FILLING_RETURN
    except Exception as e:
        logger.warning(f"_pick_filling_mode fallback (IOC): {e}")
        return mt5.ORDER_FILLING_IOC


def _fit_volume_to_free_margin(
    volume: float,
    marge_pour,
    marge_libre: float | None,
    volume_min: float,
    step: float,
    part_utilisable: float = 0.90,
) -> tuple[float | None, str | None]:
    """Réduit un volume pour qu'il tienne dans la marge disponible.

    Fonction PURE : `marge_pour` est un appelable ``volume -> marge exigée``
    (ou ``None`` si le courtier ne sait pas la calculer). Aucun appel MT5 ici,
    pour que la règle soit testable sans terminal.

    Rend ``(volume_ajusté, motif)``. ``volume_ajusté = None`` signifie que même
    le lot minimum ne tient pas — mieux vaut le dire que d'envoyer un ordre
    condamné.

    Contexte (2026-08-06) : le compte Demo disposait de 564 € libres alors que
    le plafond métal était à 0,1 lot, soit ~1300 € de marge exigée sur l'or.
    Chaque ordre repartait en `No money` (retcode 10019) et le compte ne
    tradait plus du tout. Un plafond statique par classe ne peut pas régler ça :
    il redevient faux dès que le solde bouge.

    ⚠️ **Fail-open sur l'incalculable.** Si la marge exigée ou la marge libre
    est inconnue, on renvoie le volume inchangé plutôt que de bloquer : le
    courtier reste l'arbitre final, et une panne de calcul ne doit pas arrêter
    le trading. On ne bloque que sur une information *positive* d'insuffisance.

    `part_utilisable` garde une réserve (10 % par défaut) : consommer la marge
    au dernier centime placerait le compte en appel de marge au premier tick
    défavorable.
    """
    if marge_libre is None:
        return volume, None
    budget = marge_libre * part_utilisable
    if budget <= 0:
        return None, "marge_libre_epuisee"

    exigee = marge_pour(volume)
    if exigee is None:
        return volume, None
    if exigee <= budget:
        return volume, None

    # Réduction proportionnelle, arrondie VERS LE BAS au pas du courtier.
    if exigee <= 0 or step <= 0:
        return None, "marge_insuffisante"
    cible = volume * budget / exigee
    crans = int((cible + 1e-9) // step)
    ajuste = round(crans * step, 8)

    if ajuste < volume_min:
        # Le minimum du courtier tient-il malgré tout ?
        exigee_min = marge_pour(volume_min)
        if exigee_min is not None and exigee_min <= budget:
            return volume_min, "reduit_au_lot_minimum"
        return None, "marge_insuffisante_meme_au_lot_minimum"

    # Vérification finale : l'arrondi peut avoir laissé le volume trop gros.
    verif = marge_pour(ajuste)
    if verif is not None and verif > budget:
        return None, "marge_insuffisante"
    return ajuste, "reduit_pour_tenir_dans_la_marge"


def _marge_libre() -> float | None:
    """Marge libre du compte, ou None si indisponible (fail-open)."""
    try:
        info = mt5.account_info()
        return float(info.margin_free) if info is not None else None
    except Exception as e:
        logger.warning(f"_marge_libre indisponible: {e}")
        return None


def _marge_requise(order_type, symbol: str, volume: float, price: float) -> float | None:
    """Marge exigée par le courtier pour ce volume, ou None si incalculable."""
    try:
        m = mt5.order_calc_margin(order_type, symbol, volume, price)
        return float(m) if m is not None else None
    except Exception as e:
        logger.warning(f"_marge_requise indisponible ({symbol} {volume}): {e}")
        return None


def _send_market_order(
    symbol: str, direction: str, lots: float, sl: float, tp: float, comment: str,
    sl_dist: float = 0.0, tp_dist: float = 0.0,
) -> dict:
    """Envoie un ordre MARKET à MT5. Retourne un dict
    {ok, ticket, retcode, message, price, volume,
    sl_applied, tp_applied, sl_error, tp_error}.

    Si ``sl_dist`` et ``tp_dist`` sont > 0 (envoyés par le backend depuis
    2026-05-18) : market order **sans** SL/TP puis modification de la
    position avec SL/TP recalculés depuis le fill price effectif. Élimine
    le biais slippage qui dégradait le R:R réel (mesuré 0.7-1.3 au lieu de
    1.8 sur ETH/USD le 2026-05-18). Sinon : legacy avec SL/TP absolus.
    """
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return {"ok": False, "message": f"No tick data for {symbol}"}

    price = tick.ask if direction == "buy" else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if direction == "buy" else mt5.ORDER_TYPE_SELL
    use_dist = (sl_dist > 0.0 and tp_dist > 0.0)

    # Ajustement à la marge disponible (2026-08-06) — cf. `_fit_volume_to_free_margin`.
    # Placé ici plutôt que dans le calcul de sizing pour couvrir AUSSI les lots
    # imposés par le payload (`data["lots"]`), qui ne passent pas par
    # `_compute_lots_from_symbol`.
    _sinfo = mt5.symbol_info(symbol)
    _vmin = float(getattr(_sinfo, "volume_min", 0.01) or 0.01) if _sinfo else 0.01
    _step = float(getattr(_sinfo, "volume_step", 0.01) or 0.01) if _sinfo else 0.01
    lots_ajustes, motif_marge = _fit_volume_to_free_margin(
        volume=lots,
        marge_pour=lambda v: _marge_requise(order_type, symbol, v, price),
        marge_libre=_marge_libre(),
        volume_min=_vmin,
        step=_step,
    )
    if lots_ajustes is None:
        # Refus explicite et journalisé, plutôt qu'un `No money` opaque du
        # courtier que le backend ne sait pas distinguer d'une panne.
        logger.warning(
            f"[LIVE] ordre refusé avant envoi : {motif_marge} "
            f"({symbol} {direction} {lots} lot)"
        )
        return {"ok": False, "message": f"Marge insuffisante : {motif_marge}",
                "margin_reason": motif_marge}
    if motif_marge:
        logger.info(
            f"[LIVE] volume ajusté à la marge : {lots} → {lots_ajustes} "
            f"({symbol}, {motif_marge})"
        )
        lots = lots_ajustes

    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lots,
        "type": order_type,
        "price": price,
        # Si use_dist : SL/TP posés après fill via TRADE_ACTION_SLTP.
        "sl": 0.0 if use_dist else sl,
        "tp": 0.0 if use_dist else tp,
        "deviation": DEVIATION_POINTS,
        "magic": MAGIC_NUMBER,
        "comment": comment[:30],  # MT5 limite le comment
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": _pick_filling_mode(symbol),
    }
    result = mt5.order_send(req)
    if result is None:
        return {"ok": False, "message": f"order_send returned None: {mt5.last_error()}"}
    ok = result.retcode == mt5.TRADE_RETCODE_DONE

    # État de protection SL/TP — cf. `_apply_sltp_from_fill` et le endpoint
    # /order pour la sémantique complète. None = jamais tenté par CE chemin
    # (paper, échec du fill, etc.) ; renseigné juste après si use_dist.
    sl_applied = None
    tp_applied = None
    sl_error = None
    tp_error = None

    if ok and not use_dist:
        # Legacy : sl/tp envoyés DANS la requête TRADE_ACTION_DEAL initiale.
        # MT5 accepte ou rejette le TOUT en une seule transaction atomique —
        # c'est justement pour contourner ce couplage (rejets en cascade sous
        # slippage) que le chemin use_dist existe (cf. commentaire ci-dessus,
        # incident 2026-05-18). Un ok=True ici signifie donc que sl/tp ont
        # été acceptés avec l'ordre : pas de second call, pas de fenêtre où
        # le fill réussit sans ses stops.
        sl_applied = True
        tp_applied = True

    # Prix RÉELLEMENT obtenu. Hissé hors de la branche `use_dist` le
    # 2026-08-06 : cette valeur était calculée puis jetée, alors qu'elle est
    # la seule mesure du coût d'exécution dont dispose le système (audit du
    # 2026-08-06 : `slippage_pips` vide sur 1581/1581 trades réels).
    #
    # `None` si l'ordre n'a pas abouti — jamais 0.0, qui se confondrait avec
    # un prix valide.
    fill_price, fill_source = (
        _resolve_fill_price(result, price) if ok else (None, None)
    )

    if ok and use_dist:
        # Pose SL/TP relatifs au fill price — cf. `_resolve_fill_price` pour
        # les 3 sources et le bug broker qui les rend nécessaires.
        sltp_result = _apply_sltp_from_fill(
            symbol=symbol,
            ticket=result.order,
            is_buy=(direction == "buy"),
            fill=fill_price,
            sl_dist=sl_dist,
            tp_dist=tp_dist,
        )
        # TRADE_ACTION_SLTP pose SL et TP en UN seul appel MT5 atomique : les
        # deux réussissent ou échouent ensemble, d'où sl_applied == tp_applied
        # ici (contrairement à Kraken où SL et TP sont deux ordres distincts
        # qui peuvent échouer indépendamment — cf. sl_order_id/tp_order_id
        # dans kraken-futures-bridge/bridge.py).
        sl_applied = sltp_result["ok"]
        tp_applied = sltp_result["ok"]
        if sltp_result["ok"] is not True:
            sl_error = sltp_result.get("error")
            tp_error = sltp_result.get("error")

    return {
        "ok": ok,
        "ticket": result.order,
        "retcode": result.retcode,
        "message": result.comment,
        "price": result.price,
        "volume": result.volume,
        # Champs additifs (2026-08-06) — cf. `/order` pour la sémantique.
        "sl_applied": sl_applied,
        "tp_applied": tp_applied,
        "sl_error": sl_error,
        "tp_error": tp_error,
        # `price` ci-dessus est le brut MT5, qui vaut 0.0 chez certains
        # brokers malgré un fill réussi. `fill_price` est la valeur résolue
        # et c'est elle qu'il faut mesurer. `fill_source` dit d'où elle vient :
        # sans lui, les replis « requested » se lisent comme un slippage nul
        # et diluent la mesure.
        "fill_price": fill_price,
        "fill_source": fill_source,
    }


def _prix_pour_audit(result: dict) -> float | None:
    """Le prix d'entrée à écrire dans l'audit. ``None`` si aucune source.

    ⛔ **Pourquoi cette fonction existe** (mesuré le 2026-08-24). Le site
    d'écriture faisait ``entry=result["price"]`` — le champ MT5 **brut**. Or
    IC Markets rend ``result.price = 0.0`` sur un ordre pourtant rempli :

        compte REEL, filled + live, 60 jours   57 lignes, entry>0 sur  0
        compte DEMO, meme periode              39 lignes, entry>0 sur 39

    Le repli existait déjà — ``_resolve_fill_price()``, trois sources, posé le
    2026-06-12 — et son résultat était **dans le même dict**, juste à côté,
    inutilisé pour ``entry``.

    > **Un correctif ne se propage pas seul aux autres consommateurs de la
    > même donnée.** Le repli avait été posé pour la pose du SL/TP ; personne
    > n'avait rebranché l'audit dessus.

    En aval, ``mt5_sync`` fait ``entry_price = row.get("entry") or 0`` : les
    **217** trades du compte réel portent donc ``entry_price = 0``, ce qui
    rend indécidable toute analyse en R du réel.

    ⚠️ **Rend ``None``, jamais ``0.0``, quand rien n'est lisible.** Un zéro se
    ferait passer pour une mesure et serait avalé par la première moyenne —
    c'est précisément le défaut qu'on répare. ``None`` se lit « absent ».

    ⚠️ Appelée **après** un ordre réussi : elle ne doit jamais lever, sinon on
    perdrait la trace d'un trade réel pour un champ de journalisation.
    """
    for cle in ("fill_price", "price"):
        try:
            v = float(result.get(cle))
        except (TypeError, ValueError, AttributeError):
            continue
        if v > 0:
            return v
    return None


def _resolve_fill_price(result, requested_price: float) -> tuple[float, str]:
    """Prix réellement obtenu, avec 3 sources en repli. Retourne (prix, source).

    Bug fix 2026-06-12 : certains brokers (observé sur IC Markets EU avec
    ETH/USD) renvoient `result.price = 0.0` alors même que l'ordre est rempli.
    S'en tenir à `result.price` laissait la position SANS SL/TP.

    Sources, par ordre de fiabilité :
      1. `result`    — `result.price`, le cas nominal MT5
      2. `position`  — `positions_get(ticket).price_open`, la source de vérité
      3. `requested` — le tick au moment de l'envoi, dernier recours

    ⚠️ La source 3 n'est PAS une mesure du fill : elle vaut par construction le
    prix demandé, donc un slippage de zéro. C'est le bon comportement pour
    poser un SL, mais c'est un poison pour la statistique — d'où la source
    retournée. Toute analyse de slippage doit écarter `requested`, sinon elle
    mélange « aucun glissement » et « glissement inconnu ».
    """
    fill = result.price if result.price > 0 else 0.0
    if fill > 0:
        return fill, "result"

    try:
        positions = mt5.positions_get(ticket=result.order)
        if positions and len(positions) > 0:
            fill = positions[0].price_open
            if fill > 0:
                logger.info(
                    f"[LIVE] result.price=0, fallback positions_get → {fill}"
                )
                return fill, "position"
    except Exception as _e:
        logger.warning(f"[LIVE] positions_get fallback failed: {_e}")

    logger.warning(
        f"[LIVE] all fallbacks failed, using tick price {requested_price} "
        f"(slippage non mesurable pour cet ordre)"
    )
    return requested_price, "requested"


def _clamp_stops(symbol: str, is_buy: bool, new_sl: float, new_tp: float) -> tuple[float, float]:
    """Repousse SL/TP hors de la "forbidden zone" du broker autour du prix
    courant (`trade_stops_level` points), pour éviter un retcode 10016
    "Invalid stops" plutôt que de renoncer à poser le stop.

    Fix 2026-06-14 incident : retcode 10016 observé sur IC Markets EU
    ETH/USD weekend. Avant ce fix, le SL/TP n'était jamais posé en cas de
    stops_level élevé, laissant la position non protégée.

    Extrait de `_apply_sltp_from_fill` (2026-08-06) pour être réutilisé par
    la route `/position/sltp` (garde-fou sur position déjà ouverte) sans
    dupliquer ce calcul.

    `new_tp == 0` signifie "pas de take-profit" et n'est JAMAIS transformé
    en une valeur inventée — seul un TP non nul est repoussé hors zone
    interdite. Idem pour `new_sl == 0` par symétrie/robustesse, même si les
    deux appelants actuels fournissent toujours un SL non nul.

    Best-effort : si les specs symbole ou le tick sont indisponibles,
    retourne sl/tp inchangés (rien à clamper sans référence de prix).
    """
    info = mt5.symbol_info(symbol)
    if not info:
        return new_sl, new_tp
    point = info.point
    stops_lvl = getattr(info, "trade_stops_level", 0) or 0
    tick = mt5.symbol_info_tick(symbol)
    if not (tick and tick.bid > 0 and tick.ask > 0):
        return new_sl, new_tp
    # Buffer mini = max(stops_level × 1.2, 5 ticks). Le `5 ticks` est
    # crucial pour les brokers qui retournent stops_level=0 (observé
    # 2026-06-14 sur Pepperstone Demo ETHUSD) : sans floor minimum, le
    # SL d'un SELL pouvait être posé SOUS l'ask courant, ce que MT5
    # rejette avec retcode=10016 puisque l'ask est le prix de clôture
    # d'un SELL (le SL serait déjà touché).
    min_dist = max(stops_lvl * point * 1.2, point * 5)
    if is_buy:
        # BUY position : SL closes via SELL (price=bid). Doit être
        # bid - min_dist au plus haut (sinon "trop près").
        if new_sl > 0:
            max_sl = tick.bid - min_dist
            if new_sl > max_sl:
                new_sl = max_sl
        # TP closes via SELL : doit être bid + min_dist au plus bas.
        if new_tp > 0:
            min_tp = tick.bid + min_dist
            if new_tp < min_tp:
                new_tp = min_tp
    else:
        # SELL position : SL closes via BUY (price=ask). Doit être
        # ask + min_dist au plus bas.
        if new_sl > 0:
            min_sl = tick.ask + min_dist
            if new_sl < min_sl:
                new_sl = min_sl
        # TP closes via BUY : doit être ask - min_dist au plus haut.
        if new_tp > 0:
            max_tp = tick.ask - min_dist
            if new_tp > max_tp:
                new_tp = max_tp
    return new_sl, new_tp


def _apply_stops(*, symbol: str, ticket: int, new_sl: float, new_tp: float) -> dict:
    """Envoie TRADE_ACTION_SLTP pour poser sl/tp (déjà calculés et clampés
    par l'appelant — cette fonction ne décide d'aucune valeur elle-même) sur
    une position existante.

    Retourne un dict structuré ``{ok, sl, tp, retcode, error}`` :
    - ``ok=True``  : MT5 confirme sl/tp posés (retcode DONE).
    - ``ok=False`` : MT5 a répondu mais a rejeté la modification (retcode
      != DONE) — ``error``/``retcode`` portent le détail.
    - ``ok=None``  : ``order_send()`` a retourné None (pas de réponse MT5).
      L'état réel de la position est alors INCONNU — ni protégée ni nue de
      façon certaine — d'où None plutôt qu'une supposition dans un sens ou
      l'autre (``mt5.last_error()`` dans ``error``).

    Réutilisée par `_apply_sltp_from_fill` (pose juste après le fill d'un
    ordre) et par la route `/position/sltp` (garde-fou sur position déjà
    ouverte) : même mécanique TRADE_ACTION_SLTP, même forme de résultat.

    Best-effort : ne raise jamais, une exception MT5 imprévue remonte à
    l'appelant qui doit l'attraper (aucun try/except ici pour ne pas masquer
    une erreur de programmation dans les deux seuls call-sites internes).
    """
    req = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "symbol": symbol,
        "sl": new_sl,
        "tp": new_tp,
    }
    r = mt5.order_send(req)
    if r is None:
        return {
            "ok": None, "sl": new_sl, "tp": new_tp, "retcode": None,
            "error": f"order_send returned None: {mt5.last_error()}",
        }
    if r.retcode != mt5.TRADE_RETCODE_DONE:
        return {
            "ok": False, "sl": new_sl, "tp": new_tp, "retcode": r.retcode,
            "error": r.comment,
        }
    return {"ok": True, "sl": new_sl, "tp": new_tp, "retcode": r.retcode, "error": None}


def _apply_sltp_from_fill(*, symbol: str, ticket: int, is_buy: bool, fill: float,
                          sl_dist: float, tp_dist: float) -> dict:
    """Pose SL/TP relatifs au fill price via TRADE_ACTION_SLTP.

    Préserve le R:R du backend (sl_dist / tp_dist appliqués depuis fill)
    quand c'est possible. Le clamp anti-Invalid-stops est délégué à
    `_clamp_stops` (extrait 2026-08-06, cf. sa docstring).

    Retourne un dict structuré (même forme que `_apply_stops`, cf. sa
    docstring) — **avant le 2026-08-06, cette fonction ne retournait rien**
    et son appelant (`_send_market_order`) ignorait totalement le résultat :
    un échec de pose SL/TP finissait en warning dans un log local du VPS,
    et l'appelant HTTP recevait `{"ok": true}` — identique à une position
    protégée. C'est la cause structurelle de l'incident 2026-08-05 (position
    XAU/USD ouverte sans SL/TP, découverte 7h après). Le retour explicite
    permet à `_send_market_order` puis à `/order` de dire la vérité.

    Best-effort : ne raise jamais. `ok=False` avec `error` renseigné pour
    tout cas où rien n'a été tenté (paramètres invalides, symbol_info
    indisponible) — ce n'est PAS un cas "inconnu" (`ok=None`) puisqu'on SAIT
    qu'aucun ordre n'est parti. `ok=None` est réservé au seul cas où MT5 ne
    répond pas à la tentative (cf. `_apply_stops`).
    """
    if fill <= 0 or sl_dist <= 0 or tp_dist <= 0:
        msg = "paramètres invalides (fill/sl_dist/tp_dist doivent être > 0)"
        logger.warning(f"[SLTP] {msg} ticket={ticket} fill={fill} sl_dist={sl_dist} tp_dist={tp_dist}")
        return {"ok": False, "sl": None, "tp": None, "retcode": None, "error": msg}
    info = mt5.symbol_info(symbol)
    if not info:
        msg = f"symbol_info None pour {symbol}"
        logger.warning(f"[SLTP] {msg}, abort ticket={ticket}")
        return {"ok": False, "sl": None, "tp": None, "retcode": None, "error": msg}
    digits = info.digits
    # Base : SL/TP relatifs au fill (préserve le R:R souhaité par le backend)
    new_sl = fill + sl_dist if not is_buy else fill - sl_dist
    new_tp = fill - tp_dist if not is_buy else fill + tp_dist
    new_sl, new_tp = _clamp_stops(symbol, is_buy, new_sl, new_tp)
    new_sl = round(new_sl, digits)
    new_tp = round(new_tp, digits)

    result = _apply_stops(symbol=symbol, ticket=ticket, new_sl=new_sl, new_tp=new_tp)
    if result["ok"] is True:
        logger.info(
            f"[SLTP] ticket={ticket} SL/TP posé fill={fill} sl={new_sl} tp={new_tp}"
        )
    elif result["ok"] is False:
        logger.warning(
            f"[SLTP] modify retcode={result['retcode']} ticket={ticket} "
            f"sl={new_sl} tp={new_tp} msg={result['error']}"
        )
    else:
        logger.warning(
            f"[SLTP] modify returned None ticket={ticket} err={result['error']}"
        )
    return result


def _close_position(p) -> dict:
    """Ferme une position ouverte en envoyant un ordre opposé."""
    opposite = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
    tick = mt5.symbol_info_tick(p.symbol)
    if tick is None:
        return {"ok": False, "ticket": p.ticket, "message": "no tick"}
    price = tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask
    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": p.symbol,
        "volume": p.volume,
        "type": opposite,
        "position": p.ticket,
        "price": price,
        "deviation": DEVIATION_POINTS,
        "magic": MAGIC_NUMBER,
        "comment": f"kill-{p.ticket}"[:30],
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": _pick_filling_mode(p.symbol),
    }
    r = mt5.order_send(req)
    if r is None:
        return {"ok": False, "ticket": p.ticket, "message": str(mt5.last_error())}
    return {
        "ok": r.retcode == mt5.TRADE_RETCODE_DONE,
        "ticket": p.ticket,
        "retcode": r.retcode,
        "message": r.comment,
    }


# ─── Monitor de positions (background thread) ──────────────────────
#
# Tourne en continu, regarde toutes les N secondes les positions ouvertes
# et applique le break-even (SL déplacé à entry + 1 pip) dès que le prix
# a parcouru BREAKEVEN_TRIGGER_PCT % du chemin vers TP1.
#
# En PAPER_MODE : log seulement ce qui SERAIT fait (utile pour observer
# la logique avant de passer en LIVE).
# En LIVE : envoie un mt5.order_send(TRADE_ACTION_SLTP) pour modifier le SL.
# ────────────────────────────────────────────────────────────────────

_monitor_stop = threading.Event()
_breakeven_applied: set[int] = set()  # tickets déjà passés en BE
_last_known_tickets: set[int] = set()  # positions ouvertes au dernier passage du monitor

# Métadonnées par ticket : TP1, TP2, état partial-close, trailing
# Stockées en mémoire. Perdues au redémarrage du bridge — acceptable puisque
# les positions existantes gardent leur SL/TP MT5 natifs comme filet.
_position_meta: dict[int, dict] = {}
_meta_lock = threading.Lock()

# Derniers SL/TP VIVANTS observés sur chaque position ouverte (2026-08-24).
#
# ⛔ Pourquoi cette mémoire existe. MT5 ne garde AUCUNE trace des
# `TRADE_ACTION_SLTP` : une modification de stop ne crée pas d'ordre, elle
# mute la position. Dès qu'elle est fermée, le niveau qu'elle portait
# réellement à cet instant est perdu — définitivement, pour tout le monde.
#
# La base, elle, garde les niveaux d'ORIGINE. Mesure du 2026-08-24 sur les 39
# clôtures à la main : sur 36 rejouées minute par minute, **16 (44 %) ont vu
# leur niveau stocké franchi AVANT l'heure réelle de clôture** — preuve directe
# que le niveau stocké n'était pas celui du courtier. Toute simulation de
# sortie assise dessus est fausse dans ~4 cas sur 10.
#
# Le monitor a ces niveaux sous la main à chaque passage. Il suffisait de s'en
# souvenir un tour de plus.
_derniers_niveaux: dict[int, dict] = {}

# Volatilite par symbole, pour la porte de bruit de la soupape d'equilibre.
# ⚠️ Declare ICI et non a cote de `_sigma_journalier` : les tests extraient la
# plage `_risque_realise` -> `_controle_marge_libre` du source et l'executent
# seule, sans les imports du module. Une AFFECTATION de module dans cette
# plage y leve `NameError: threading`. Les fonctions, elles, ne resolvent
# leurs noms qu'a l'appel — donc elles passent.
_vol_cache: dict[str, tuple[float, float]] = {}   # symbole -> (sigma_prix, t)
_vol_lock = threading.Lock()


def _register_position_meta(ticket: int, tp1: float, tp2: float | None) -> None:
    """Mémorise TP1/TP2 pour un ordre qui vient d'être passé.
    Appelé depuis /order après un order_send réussi en LIVE."""
    with _meta_lock:
        _position_meta[ticket] = {
            "tp1": tp1,
            "tp2": tp2 if (tp2 is not None and tp2 > 0) else None,
            "partial_closed": False,
            "trailing_active": False,
        }


def _cleanup_closed_meta(open_tickets: set[int]) -> None:
    """Purge les meta des tickets qui ne sont plus ouverts."""
    with _meta_lock:
        for t in list(_position_meta.keys()):
            if t not in open_tickets:
                del _position_meta[t]


def _pip_size(symbol: str) -> float:
    """Taille d'un pip selon la paire (JPY ≈ 0.01, autres = 0.0001).
    XAU/XAG/crypto utilisent 0.01 ou 0.001 — on reste simple pour l'instant."""
    if "JPY" in symbol.upper():
        return 0.01
    if "XAU" in symbol.upper() or "XAG" in symbol.upper():
        return 0.01
    return 0.0001


def _maybe_move_to_breakeven(p) -> None:
    """Si la position a atteint X% du chemin vers TP1, déplace le SL à BE.
    Idempotent via _breakeven_applied (dedup par ticket)."""
    if p.ticket in _breakeven_applied:
        return
    if p.tp == 0 or p.sl == 0:
        return  # pas de SL/TP défini → rien à faire

    pip = _pip_size(p.symbol)
    if p.type == mt5.POSITION_TYPE_BUY:
        tp_distance = p.tp - p.price_open
        current_progress = p.price_current - p.price_open
        if tp_distance <= 0:
            return
        if current_progress / tp_distance < BREAKEVEN_TRIGGER_PCT / 100.0:
            return
        new_sl = p.price_open + pip
        if new_sl <= p.sl:
            return  # SL déjà mieux placé
    else:  # SELL
        tp_distance = p.price_open - p.tp
        current_progress = p.price_open - p.price_current
        if tp_distance <= 0:
            return
        if current_progress / tp_distance < BREAKEVEN_TRIGGER_PCT / 100.0:
            return
        new_sl = p.price_open - pip
        if new_sl >= p.sl:
            return

    if PAPER_MODE:
        logger.info(
            f"[PAPER BE] pos#{p.ticket} {p.symbol} {p.volume}L "
            f"progress={current_progress / tp_distance * 100:.0f}% "
            f"SL {p.sl:.5f} → {new_sl:.5f}"
        )
        _breakeven_applied.add(p.ticket)
        return

    # LIVE — modifie le SL via TRADE_ACTION_SLTP
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": p.ticket,
        "symbol": p.symbol,
        "sl": new_sl,
        "tp": p.tp,
    }
    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        logger.info(
            f"[LIVE BE] pos#{p.ticket} {p.symbol} SL → {new_sl:.5f} ✓"
        )
        _breakeven_applied.add(p.ticket)
    else:
        rc = getattr(result, "retcode", "?")
        cm = getattr(result, "comment", "?")
        logger.warning(
            f"[LIVE BE FAIL] pos#{p.ticket} retcode={rc} comment={cm}"
        )


def _maybe_partial_close_and_trail(p) -> None:
    """Gestion active d'une position : partial close à TP1 + trailing stop.

    Flux :
    1. Si position pas encore en partial-close ET prix a atteint TP1 :
       - ferme PARTIAL_CLOSE_PCT % du volume (ordre opposé partiel)
       - modifie le reste : SL → entry (BE), TP → TP2 (si fourni)
       - active le trailing
    2. Si trailing actif :
       - remonte le SL à price_current ± TRAIL_DISTANCE_POINTS selon direction
       - mais seulement si ça améliore le SL actuel
    """
    meta = _position_meta.get(p.ticket)
    if meta is None:
        return  # position pas tracée (ouverte avant le bridge, ou en manuel)

    info = mt5.symbol_info(p.symbol)
    if info is None or info.point <= 0:
        return

    # ─── Phase 1 : partial close à TP1 ─────────────────────────
    if not meta["partial_closed"]:
        tp1 = meta.get("tp1")
        if tp1 is None or tp1 <= 0:
            return  # pas de TP1 → on ne fait rien
        reached_tp1 = (
            p.price_current >= tp1 if p.type == mt5.POSITION_TYPE_BUY
            else p.price_current <= tp1
        )
        if not reached_tp1:
            return

        # Taille à fermer = PARTIAL_CLOSE_PCT % du volume, arrondi au step broker
        close_volume = round(
            p.volume * PARTIAL_CLOSE_PCT / 100.0 / info.volume_step
        ) * info.volume_step
        remaining = round(p.volume - close_volume, 3)
        # Garde-fous : si les 2 portions tombent sous volume_min, skip
        if close_volume < info.volume_min or remaining < info.volume_min:
            logger.info(
                f"pos#{p.ticket}: volume trop petit pour partial close "
                f"(close={close_volume}, remaining={remaining}, "
                f"min={info.volume_min}) — laisse courir entier"
            )
            meta["partial_closed"] = True  # évite de re-checker
            meta["trailing_active"] = bool(TRAIL_DISTANCE_POINTS)
            return

        if PAPER_MODE:
            logger.info(
                f"[PAPER PARTIAL] pos#{p.ticket} close {close_volume}L / keep {remaining}L "
                f"+ move SL→BE + TP→{meta.get('tp2') or 'same'}"
            )
            meta["partial_closed"] = True
            meta["trailing_active"] = bool(TRAIL_DISTANCE_POINTS)
            return

        # LIVE : envoie un ordre opposite partiel
        opposite = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(p.symbol)
        if tick is None:
            return
        close_price = tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask
        close_req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": p.symbol,
            "volume": close_volume,
            "type": opposite,
            "position": p.ticket,
            "price": close_price,
            "deviation": DEVIATION_POINTS,
            "magic": MAGIC_NUMBER,
            "comment": f"partial-{p.ticket}"[:30],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": _pick_filling_mode(p.symbol),
        }
        r = mt5.order_send(close_req)
        if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
            rc = getattr(r, "retcode", "?")
            cm = getattr(r, "comment", "?")
            logger.warning(f"[LIVE PARTIAL FAIL] pos#{p.ticket} retcode={rc} {cm}")
            return

        logger.info(
            f"[LIVE PARTIAL ✓] pos#{p.ticket} closed {close_volume}L "
            f"@ {close_price} ({PARTIAL_CLOSE_PCT}%)"
        )

        # Modifie le reste : SL → entry (BE), TP → TP2 (si dispo, sinon laisse TP1)
        new_tp = meta.get("tp2") or p.tp
        new_sl = p.price_open  # break-even exact (pas entry+1pip ici : trailing suivra)
        modify_req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": p.ticket,
            "symbol": p.symbol,
            "sl": new_sl,
            "tp": new_tp,
        }
        r2 = mt5.order_send(modify_req)
        if r2 and r2.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(
                f"[LIVE PARTIAL BE] pos#{p.ticket} SL→{new_sl:.5f} TP→{new_tp:.5f}"
            )
        else:
            logger.warning(
                f"[LIVE PARTIAL BE FAIL] pos#{p.ticket} "
                f"retcode={getattr(r2, 'retcode', '?')}"
            )

        meta["partial_closed"] = True
        meta["trailing_active"] = bool(TRAIL_DISTANCE_POINTS)
        _breakeven_applied.add(p.ticket)  # pas besoin de BE classique
        return

    # ─── Phase 2 : trailing stop sur le reste ──────────────────
    if not meta["trailing_active"] or TRAIL_DISTANCE_POINTS <= 0:
        return
    trail_distance = TRAIL_DISTANCE_POINTS * info.point
    if p.type == mt5.POSITION_TYPE_BUY:
        new_sl = p.price_current - trail_distance
        if new_sl <= p.sl:
            return  # pas mieux
    else:
        new_sl = p.price_current + trail_distance
        if new_sl >= p.sl:
            return

    if PAPER_MODE:
        logger.info(
            f"[PAPER TRAIL] pos#{p.ticket} SL {p.sl:.5f} → {new_sl:.5f} "
            f"(price={p.price_current:.5f}, distance={TRAIL_DISTANCE_POINTS}pts)"
        )
        return

    # LIVE modify
    req = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": p.ticket,
        "symbol": p.symbol,
        "sl": new_sl,
        "tp": p.tp,
    }
    r = mt5.order_send(req)
    if r and r.retcode == mt5.TRADE_RETCODE_DONE:
        logger.info(f"[LIVE TRAIL] pos#{p.ticket} SL → {new_sl:.5f}")
    else:
        logger.warning(
            f"[LIVE TRAIL FAIL] pos#{p.ticket} retcode={getattr(r, 'retcode', '?')}"
        )


def _log_closed_position(ticket: int, niveaux: dict | None = None) -> None:
    """Quand un ticket disparaît des positions ouvertes, log sa fermeture
    avec exit_price + pnl dans l'audit DB. Lit l'historique MT5 des deals.

    `niveaux` porte les SL/TP **vivants** au dernier passage du monitor, que
    MT5 ne conservera pas. Cf. `_derniers_niveaux`.
    """
    try:
        # Deals liés à ce ticket (ouvre + clôture). On somme profit+swap+commission.
        deals = mt5.history_deals_get(position=ticket)
        if not deals:
            logger.info(f"[CLOSE] ticket #{ticket} fermé — pas d'historique disponible")
            return
        total_pnl = 0.0
        exit_price = None
        exit_time = None
        symbol = None
        volume = None
        cause = None
        for d in deals:
            total_pnl += (d.profit or 0) + (d.swap or 0) + (d.commission or 0)
            if d.entry == mt5.DEAL_ENTRY_OUT or d.entry == mt5.DEAL_ENTRY_OUT_BY:
                exit_price = d.price
                exit_time = d.time
                symbol = d.symbol
                volume = d.volume
                cause = _deal_reason_label(d)
        logger.info(
            f"[CLOSE] ticket #{ticket} {symbol} exit @ {exit_price} "
            f"PnL={total_pnl:+.2f} cause={cause}"
        )
        champs = dict(
            mode="live",
            status="closed",
            symbol=symbol,
            lots=volume,
            ticket=ticket,
            exit_price=exit_price,
            pnl=round(total_pnl, 2),
            message=f"Closed at {exit_price}" if exit_price else "Closed",
        )
        # ⚠️ Une cause illisible n'est PAS écrite. Le radar a une heuristique de
        # repli sur les prix ; rien ne rattrape une cause affirmée à tort, car
        # `close_reason` y est protégé par COALESCE — la première valeur posée
        # est définitive. Cf. [[feedback_detection_par_absence]].
        if cause and cause != "INCONNU":
            champs["close_reason"] = cause
        # Niveaux vivants au dernier passage du monitor. À défaut, le niveau
        # déclencheur reconstruit depuis l'ordre de clôture. Un zéro MT5
        # signifie « pas de stop », pas « stop à 0 » : il n'est pas écrit.
        n = dict(niveaux or {})
        if not n:
            n = _niveaux_depuis_historique(ticket)
        for cle in ("sl_at_close", "tp_at_close", "niveau_declencheur"):
            v = n.get(cle)
            if v:
                champs[cle] = float(v)
        if n.get("niveaux_source"):
            champs["niveaux_source"] = n["niveaux_source"]
        _db_log_order(**champs)
    except Exception as e:
        logger.warning(f"_log_closed_position({ticket}) error: {e}")


def _niveaux_depuis_historique(ticket: int) -> dict:
    """Repli quand le monitor n'a pas vu la position vivante (bridge redémarré).

    ⛔ **MESURÉ LE 2026-08-25 : ce repli ne se déclenche JAMAIS, et il faut le
    dire plutôt que de le laisser passer pour un filet.** J'avais écrit qu'un
    stop touché laissait son niveau dans `price_open` de l'ordre de clôture.
    C'est faux : MT5 ferme sur un **ordre au marché**, pas sur un ordre-stop en
    attente. Vérifié sur trois tickets `reason=SL` du démo après déploiement —
    `niveau_declencheur` vaut `None` sur les trois.

    ⇒ **Il n'existe aucune route rétroactive.** Une fois la position fermée, le
    niveau qu'elle portait est perdu : MT5 ne journalise pas les
    `TRADE_ACTION_SLTP`. Seule la capture EN AVANT du monitor
    (`_derniers_niveaux`) produit la donnée.

    La fonction est conservée parce qu'elle ne peut rien inventer — elle rend
    `{}` — et parce que la plomberie en aval (`niveaux_source`, rangement par
    cause) reste juste si un courtier venait à exposer ce niveau. Mais **ne pas
    compter dessus** : la seule source prouvée est le monitor.

    Cf. [[feedback_detection_par_absence]] · [[project_analyse_clotures_main_2026_08_24]]
    """
    try:
        ordres = mt5.history_orders_get(position=ticket) or []
    except Exception as e:
        logger.debug(f"_niveaux_depuis_historique({ticket}): {e}")
        return {}
    # ⚠️ Les `None` sont écartés : un `getattr` manqué laisserait `{None}` dans
    # le set, et tout ordre sans attribut `type` y correspondrait. Un trou de
    # lecture deviendrait une correspondance.
    declencheurs = {
        c for c in (
            getattr(mt5, n, None)
            for n in ("ORDER_TYPE_BUY_STOP", "ORDER_TYPE_SELL_STOP",
                      "ORDER_TYPE_BUY_LIMIT", "ORDER_TYPE_SELL_LIMIT")
        ) if c is not None
    }
    if not declencheurs:
        return {}
    for o in sorted(ordres, key=lambda x: getattr(x, "time_done", 0) or 0,
                    reverse=True):
        if getattr(o, "type", None) in declencheurs and getattr(o, "price_open", 0):
            return {
                "niveau_declencheur": float(o.price_open),
                "niveaux_source": "ordre_declencheur",
            }
    return {}


def _position_monitor_loop():
    """Boucle principale du monitor. S'arrête via _monitor_stop.set()."""
    global _last_known_tickets
    logger.info(
        f"Monitor de positions démarré "
        f"(interval={MONITOR_INTERVAL_SEC}s, "
        f"BE={BREAKEVEN_TRIGGER_PCT}%, "
        f"partial={PARTIAL_CLOSE_PCT}%, "
        f"trail={TRAIL_DISTANCE_POINTS}pts)"
    )
    while not _monitor_stop.is_set():
        try:
            if ensure_mt5_connected():
                positions = mt5.positions_get() or []
                open_tickets = {p.ticket for p in positions}
                # Détection des fermetures : tickets présents au dernier tour
                # mais plus là maintenant. Log l'event dans l'audit DB.
                closed_tickets = _last_known_tickets - open_tickets
                for t in closed_tickets:
                    # Les niveaux du TOUR PRÉCÉDENT : la position n'existe
                    # plus, MT5 ne les rendra jamais. Purgés après usage.
                    _log_closed_position(t, _derniers_niveaux.pop(t, None))
                _last_known_tickets = open_tickets
                # Mémoriser les niveaux vivants pour le tour suivant. Un 0
                # MT5 vaut « aucun niveau » — on garde 0.0 tel quel ici,
                # `_log_closed_position` se charge de ne pas l'écrire.
                for p in positions:
                    _derniers_niveaux[p.ticket] = {
                        "sl_at_close": float(getattr(p, "sl", 0) or 0),
                        "tp_at_close": float(getattr(p, "tp", 0) or 0),
                        "niveaux_source": "monitor",
                    }
                for t in list(_derniers_niveaux):
                    if t not in open_tickets:
                        del _derniers_niveaux[t]
                # Purge les tickets fermés des sets de tracking
                _breakeven_applied.intersection_update(open_tickets)
                _cleanup_closed_meta(open_tickets)
                for p in positions:
                    # Gestion active d'abord (partial + trail) pour les positions
                    # que nous avons ouvertes et tracées.
                    _maybe_partial_close_and_trail(p)
                    # Break-even fallback pour les positions sans meta (ex: anciens)
                    if p.ticket not in _position_meta:
                        _maybe_move_to_breakeven(p)
        except Exception as e:
            logger.warning(f"Monitor loop error: {e}")
        if _monitor_stop.wait(timeout=MONITOR_INTERVAL_SEC):
            break
    logger.info("Monitor de positions arrêté")


# ─── Endpoints ──────────────────────────────────────────────────────

_TIMEFRAMES = {
    "M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30", "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}
MAX_BOUGIES = 5000


def _decalage_serveur_sec() -> float | None:
    """Ecart entre l'heure SERVEUR du courtier et l'heure UTC reelle.

    MT5 exprime `deal.time` et `rates['time']` en heure serveur, pas en UTC,
    et ne le signale nulle part. Mesure le 2026-08-10 : 3 h sur ICMarketsEU.
    Sans cette correction, toute fenetre demandee en UTC recupere les mauvaises
    bougies — decalage silencieux, resultat faux mais plausible.

    On le mesure au lieu de le supposer : le dernier tick porte l'heure serveur,
    et il vient d'arriver.
    """
    try:
        for sym in (mt5.symbols_get() or [])[:1]:
            tick = mt5.symbol_info_tick(sym.name)
            if tick and tick.time:
                return round(tick.time - datetime.now(timezone.utc).timestamp())
    except Exception as e:
        logger.debug(f"_decalage_serveur_sec: {e}")
    return None


@app.route("/rates", methods=["GET"])
@require_api_key
def rates():
    """Bougies OHLC entre deux instants, pour rejouer le CHEMIN d'un trade.

    Ajoute le 2026-08-11. Sans le chemin du prix pendant le trade, on ne peut
    pas savoir si le recul a precede ou suivi l'avancee — et toute simulation
    de gestion de sortie (mise a zero du risque, stop suiveur) reste bornee au
    lieu d'etre exacte. `mfe_pct` / `mae_pct` sont des maxima sans ordre : ils
    ne suffisent pas.

    Parametres : pair, timeframe (M1 par defaut), from, to (ISO 8601, UTC).

    ATTENTION : les bornes envoyees sont en UTC et converties en heure SERVEUR ici.
    Le decalage mesure est renvoye dans la reponse pour que l'appelant puisse
    verifier plutot que croire.
    """
    pair = request.args.get("pair", "")
    tf_nom = request.args.get("timeframe", "M1").upper()
    if not pair:
        return jsonify({"error": "pair requis"}), 400
    if tf_nom not in _TIMEFRAMES:
        return jsonify({"error": f"timeframe inconnu, attendu {sorted(_TIMEFRAMES)}"}), 400
    try:
        debut = datetime.fromisoformat(request.args["from"].replace("Z", "+00:00"))
        fin = datetime.fromisoformat(request.args["to"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return jsonify({"error": "from et to requis, en ISO 8601"}), 400
    if fin <= debut:
        return jsonify({"error": "to doit suivre from"}), 400

    if not ensure_mt5_connected():
        return jsonify({"error": "MT5 not connected"}), 503

    symbole = resolve_symbol(pair)
    if not symbole:
        return jsonify({"error": f"symbole introuvable pour {pair}"}), 404

    decalage = _decalage_serveur_sec() or 0
    tf = getattr(mt5, _TIMEFRAMES[tf_nom])
    # copy_rates_range attend des datetime interpretes en heure serveur.
    d_srv = datetime.fromtimestamp(debut.timestamp() + decalage, tz=timezone.utc)
    f_srv = datetime.fromtimestamp(fin.timestamp() + decalage, tz=timezone.utc)
    brut = mt5.copy_rates_range(symbole, tf, d_srv, f_srv)
    if brut is None:
        return jsonify({"error": f"copy_rates_range a echoue: {mt5.last_error()}"}), 502

    bougies = []
    for b in brut[:MAX_BOUGIES]:
        bougies.append({
            # Reconverti en UTC reel : l'appelant recoit des instants comparables
            # a ses propres horodatages.
            "t": datetime.fromtimestamp(
                float(b["time"]) - decalage, tz=timezone.utc).isoformat(),
            "o": float(b["open"]), "h": float(b["high"]),
            "l": float(b["low"]), "c": float(b["close"]),
            # Spread en POINTS, tel que MT5 le stocke par bougie. Ajoute le
            # 2026-08-11 : la commission est nulle sur ces comptes et le swap
            # negligeable (mesure sur 191 trades), donc le spread est le cout
            # d'execution — et rien ne l'exposait.
            "s": int(b["spread"]) if "spread" in b.dtype.names else None,
        })

    return jsonify({
        "pair": pair,
        "symbole": symbole,
        "timeframe": tf_nom,
        "decalage_serveur_sec": decalage,
        # Necessaire pour convertir le spread (en points) en unites de prix.
        "point": float(getattr(mt5.symbol_info(symbole), "point", 0) or 0),
        "tronque": len(brut) > MAX_BOUGIES,
        "n": len(bougies),
        "bougies": bougies,
    })


@app.route("/order_check", methods=["POST"])
@require_api_key
def order_check():
    """Valide un ordre SANS l'executer, et rend le motif exact du courtier.

    Ajoute le 2026-08-12. Le compte reel a refuse un achat XAUUSD avec
    `retcode=10006 msg=Request rejected` — un motif generique, identique dans
    le journal MT5 (<< accepted >> puis << rejected >> a la meme milliseconde).
    Aucun des elements visibles n'expliquait le refus : trading autorise,
    symbole pleinement negociable, 552 EUR de marge libre, volume conforme.

    `mt5.order_check()` interroge le serveur avec la MEME requete que
    `order_send`, mais sans passer d'ordre. Il rend la marge requise, la marge
    restante, et surtout le `comment` du courtier — la seule source qui puisse
    dire pourquoi.

    ⚠️ Ne place RIEN. C'est un diagnostic, pas une execution.
    """
    data = request.get_json(silent=True) or {}
    pair = data.get("pair", "")
    direction = str(data.get("direction", "buy")).lower()
    try:
        lots = float(data.get("lots", 0.01))
    except (TypeError, ValueError):
        return jsonify({"error": "lots must be numeric"}), 400
    if not pair:
        return jsonify({"error": "pair requis"}), 400
    if not ensure_mt5_connected():
        return jsonify({"error": "MT5 not connected"}), 503

    symbole = resolve_symbol(pair)
    if not symbole:
        return jsonify({"error": f"symbole introuvable pour {pair}"}), 404
    tick = mt5.symbol_info_tick(symbole)
    if tick is None:
        return jsonify({"error": "pas de cotation"}), 503

    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbole,
        "volume": lots,
        "type": mt5.ORDER_TYPE_BUY if direction == "buy" else mt5.ORDER_TYPE_SELL,
        "price": tick.ask if direction == "buy" else tick.bid,
        "deviation": DEVIATION_POINTS,
        "magic": MAGIC_NUMBER,
        "comment": "order-check",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": _pick_filling_mode(symbole),
    }
    res = mt5.order_check(req)
    if res is None:
        return jsonify({"erreur_mt5": str(mt5.last_error()), "requete": {
            k: (str(v) if not isinstance(v, (int, float, str)) else v)
            for k, v in req.items()}}), 502

    info = mt5.symbol_info(symbole)
    return jsonify({
        "symbole": symbole,
        "volume": lots,
        "retcode": res.retcode,
        # C'est CE champ qui porte l'explication du courtier.
        "commentaire_courtier": res.comment,
        "marge_requise": getattr(res, "margin", None),
        "marge_restante": getattr(res, "margin_free", None),
        "niveau_marge": getattr(res, "margin_level", None),
        "solde_apres": getattr(res, "balance", None),
        "mode_remplissage_utilise": req["type_filling"],
        "modes_autorises_par_le_courtier": getattr(info, "filling_mode", None),
        "derniere_erreur_mt5": str(mt5.last_error()),
    })


@app.route("/limits", methods=["GET"])
@require_api_key
def limits():
    """Ce que le COURTIER autorise, par opposition a ce que NOUS nous imposons.

    Ajoute le 2026-08-11 : la question << y a-t-il une limitation en nombre de
    trades ? >> ne se deduit pas de la documentation, elle se mesure sur le
    compte. Aucun de nos plafonds (MAX_OPEN_POSITIONS, anti-doublon,
    coupe-circuit) ne renseigne sur ceux du courtier.

    - limit_orders : nombre maximal d'ordres EN ATTENTE simultanes (0 = illimite)
    - fifo_close   : le courtier impose-t-il de fermer dans l'ordre d'ouverture
    - volume_limit : volume cumule maximal par symbole et par sens (0 = illimite)
    - trade_mode   : le symbole est-il pleinement negociable

    ATTENTION : MT5 ne publie AUCUN plafond sur le nombre de POSITIONS ouvertes ni sur
    le nombre d'ordres par jour : ces notions n'existent pas dans son API. Une
    limite de ce genre serait une regle interne du courtier, invisible ici, et
    se manifesterait par un rejet a l'execution.
    """
    if not ensure_mt5_connected():
        return jsonify({"error": "MT5 not connected"}), 503

    a = mt5.account_info()
    compte = {}
    if a is not None:
        for champ in ("login", "limit_orders", "fifo_close", "trade_allowed",
                      "trade_expert", "margin_mode", "leverage", "currency"):
            compte[champ] = getattr(a, champ, None)

    # Paires a inspecter : celles passees en parametre, sinon les overrides
    # connus. Le bridge n'a pas la liste surveillee par le radar — la lui
    # demander serait deviner ; on la recoit.
    demandees = request.args.get("pairs", "")
    paires = [x.strip() for x in demandees.split(",") if x.strip()]
    if not paires:
        paires = sorted(MT5_SYMBOL_MAP.keys())

    symboles = {}
    for pair in paires:
        sym = resolve_symbol(pair)
        info = mt5.symbol_info(sym) if sym else None
        if info is None:
            symboles[pair] = {"symbole": sym, "erreur": "inconnu du courtier"}
            continue
        symboles[pair] = {
            "symbole": sym,
            "volume_min": info.volume_min,
            "volume_max": info.volume_max,
            "volume_limit": info.volume_limit,
            "volume_step": info.volume_step,
            "trade_mode": info.trade_mode,
        }

    return jsonify({
        "compte": compte,
        "nos_plafonds": {
            "max_open_positions": MAX_OPEN_POSITIONS,
            "max_lot": MAX_LOT,
        },
        "symboles": symboles,
    })


@app.route("/health", methods=["GET"])
def health():
    """Ping public (pas d'auth). Utile pour vérifier que le bridge tourne.

    ⚠️ Champs existants **jamais retirés ni renommés** : le moniteur et le
    radar les consomment. `garde_fous` (2026-08-20) s'y ajoute.

    Pourquoi ce bloc : `MAX_DAILY_LOSS_PCT` valait **10.0** sur les deux
    bridges MT5 alors que le défaut du code est 3.0 — un plafond de perte
    journalière 3,3× trop large, resté en place des semaines. Le vérifier a
    exigé une session RDP sur le VPS, parce que rien ne l'exposait ; le bridge
    Kraken, lui, publie déjà le sien dans son `/health`.

    > **Un garde-fou qu'on ne peut pas lire est un garde-fou dont on ne sait
    > jamais s'il s'applique.** Ces valeurs ne sont pas des secrets : les
    > cacher ne protège personne et empêche de les surveiller.
    """
    connected = ensure_mt5_connected()
    return jsonify({
        "source_sha": SOURCE_SHA,
        "demarre_a": DEMARRE_A,
        "ok": connected,
        "paper_mode": PAPER_MODE,
        "server": MT5_SERVER,
        "login": MT5_LOGIN,
        "mt5_version": mt5.__version__,
        "max_lot": MAX_LOT,
        "max_lot_per_class": MAX_LOT_PER_CLASS,
        "garde_fous": {
            "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
            "max_open_positions": MAX_OPEN_POSITIONS,
            # Plafond par le RISQUE plutot que par le nombre (2026-08-20).
            # 0 = desarme, seul le compteur agit alors.
            "max_risque_engage_pct": MAX_RISQUE_ENGAGE_PCT,
            # Poche reservee a l'OR SEUL (2026-08-28). 0 = l'or retombe dans
            # la poche ci-dessus. Les deux budgets ne se pretent RIEN : la
            # sonde de saturation doit donc les mesurer separement.
            "max_risque_engage_or_pct": MAX_RISQUE_ENGAGE_OR_PCT,
            "marge_libre_min_pct": MARGE_LIBRE_MIN_PCT,
            # Lisible a distance : sans ca, savoir si ce mecanisme est arme
            # demanderait une session RDP.
            "equilibre_auto_enabled": EQUILIBRE_AUTO_ENABLED,
            "equilibre_marge_r": EQUILIBRE_MARGE_R,
            # La porte de bruit. 0 = desarmee, seul le seuil en R agit alors —
            # et il vaut 4,5 fois moins de marge sur USD/JPY que sur EUR/GBP.
            "equilibre_marge_sigma": EQUILIBRE_MARGE_SIGMA,
            "deviation_points": DEVIATION_POINTS,
            # 0 = desarme. Le suiveur detruisait 0,329 R/trade sur l'or ;
            # desarme le 2026-08-11, +21 % a la cle. Doit rester a 0.
            "trail_distance_points": TRAIL_DISTANCE_POINTS,
            "partial_close_pct": PARTIAL_CLOSE_PCT,
            "trading_hours_utc": TRADING_HOURS_UTC or None,
            # Un ticket ferme qui traine ici ne fait plus rien (l'exclusion ne
            # porte que sur les positions OUVERTES), mais il ment sur l'etat.
            "daily_loss_excluded_tickets": sorted(DAILY_LOSS_EXCLUDED_TICKETS),
        },
    })


@app.route("/account", methods=["GET"])
@require_api_key
def account():
    """État du compte : balance, equity, positions ouvertes."""
    if not ensure_mt5_connected():
        return jsonify({"error": "MT5 not connected"}), 503
    info = mt5.account_info()
    if info is None:
        return jsonify({"error": "no account info"}), 503
    return jsonify({
        "login": info.login,
        "balance": info.balance,
        "equity": info.equity,
        "profit": info.profit,
        "margin": info.margin,
        "margin_free": info.margin_free,
        "currency": info.currency,
        "leverage": info.leverage,
        "positions_count": mt5.positions_total() or 0,
    })


@app.route("/tick/<path:pair>", methods=["GET"])
@require_api_key
def tick(pair):
    """Prix bid/ask courant d'une paire. Utile pour valider SL/TP avant un ordre."""
    if not ensure_mt5_connected():
        return jsonify({"error": "MT5 not connected"}), 503
    sym = resolve_symbol(pair)
    if not sym:
        return jsonify({"error": f"symbol not found for {pair}"}), 404
    t = mt5.symbol_info_tick(sym)
    if t is None:
        return jsonify({"error": f"no tick for {sym}"}), 503
    info = mt5.symbol_info(sym)
    return jsonify({
        "pair": pair,
        "symbol": sym,
        "bid": t.bid,
        "ask": t.ask,
        "spread": round((t.ask - t.bid) / info.point) if info else None,
        "stops_level_points": info.trade_stops_level if info else None,
        "point": info.point if info else None,
        "time": datetime.fromtimestamp(t.time, tz=timezone.utc).isoformat(),
    })


@app.route("/symbol_specs/<path:pair>", methods=["GET"])
@require_api_key
def symbol_specs(pair):
    """Specs broker complètes pour une pair : volume_min/max/step,
    trade_contract_size, trade_tick_value, point, digits — utilisé pour
    debugger les retcode=10014 (INVALID_VOLUME).
    """
    if not ensure_mt5_connected():
        return jsonify({"error": "MT5 not connected"}), 503
    sym = resolve_symbol(pair)
    if not sym:
        return jsonify({"error": f"symbol not found for {pair}"}), 404
    info = mt5.symbol_info(sym)
    if info is None:
        return jsonify({"error": f"symbol_info None for {sym}"}), 503
    return jsonify({
        "pair": pair,
        "symbol": sym,
        "volume_min": info.volume_min,
        "volume_max": info.volume_max,
        "volume_step": info.volume_step,
        "trade_contract_size": info.trade_contract_size,
        "trade_tick_value": info.trade_tick_value,
        "point": info.point,
        "digits": info.digits,
        "trade_stops_level": info.trade_stops_level,
        "filling_mode": info.filling_mode,
        "trade_mode": info.trade_mode,
    })


@app.route("/symbols", methods=["GET"])
@require_api_key
def symbols():
    """Liste les symboles disponibles sur le compte.

    Query params :
      ?query=BTC   filtre substring insensible a la casse
      ?limit=500   cap sur le nombre de resultats (defaut : pas de cap)
    """
    if not ensure_mt5_connected():
        return jsonify({"error": "MT5 not connected"}), 503
    all_syms = mt5.symbols_get() or []
    names = [s.name for s in all_syms]
    query = request.args.get("query", "").strip().upper()
    if query:
        names = [n for n in names if query in n.upper()]
    limit_str = request.args.get("limit", "").strip()
    if limit_str:
        try:
            names = names[: int(limit_str)]
        except ValueError:
            pass
    return jsonify({"count": len(names), "symbols": names})


@app.route("/positions", methods=["GET"])
@require_api_key
def positions():
    """Positions ouvertes en temps réel."""
    if not ensure_mt5_connected():
        return jsonify({"error": "MT5 not connected"}), 503
    pos_list = mt5.positions_get() or []
    return jsonify({
        "count": len(pos_list),
        "positions": [
            {
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": "buy" if p.type == mt5.POSITION_TYPE_BUY else "sell",
                "volume": p.volume,
                "price_open": p.price_open,
                "price_current": p.price_current,
                "sl": p.sl,
                "tp": p.tp,
                "profit": p.profit,
                "time": datetime.fromtimestamp(p.time, tz=timezone.utc).isoformat(),
                "comment": p.comment,
            }
            for p in pos_list
        ],
    })


def _deal_reason_label(deal) -> str:
    """Traduit `deal.reason` (MT5) en une etiquette stable pour le backend.

    MT5 SAIT pourquoi une position s'est fermee. Le bridge ne le remontait pas,
    obligeant le backend a deviner en comparant le prix de sortie aux SL/TP
    stockes en base. Cette heuristique ne pouvait pas reconnaitre le stop
    suiveur (le stop avait bouge, la base gardait celui d'origine) et declarait
    "fermee a la main" tout ce qu'elle ne savait pas classer : 215 trades au
    2026-08-10, dont zero reellement ferme a la main.

    ⚠️ STOP_OUT (DEAL_REASON_SO) est une LIQUIDATION par le courtier faute de
    marge, pas un stop-loss. Les confondre effacerait la difference entre une
    sortie choisie et une sortie subie.

    ⚠️ Le stop suiveur ferme via un SL deplace : MT5 rapporte donc SL. C'est
    au backend de distinguer, en regardant si le stop avait bouge.
    """
    codes = {
        "DEAL_REASON_CLIENT": "MANUAL",
        "DEAL_REASON_MOBILE": "MANUAL",
        "DEAL_REASON_WEB": "MANUAL",
        "DEAL_REASON_EXPERT": "EXPERT",
        "DEAL_REASON_SL": "SL",
        "DEAL_REASON_TP": "TP",
        "DEAL_REASON_SO": "STOP_OUT",
        "DEAL_REASON_ROLLOVER": "ROLLOVER",
        "DEAL_REASON_VMARGIN": "VMARGIN",
        "DEAL_REASON_SPLIT": "SPLIT",
    }
    brut = getattr(deal, "reason", None)
    if brut is None:
        return "INCONNU"
    for nom, etiquette in codes.items():
        valeur = getattr(mt5, nom, None)
        if valeur is not None and brut == valeur:
            return etiquette
    return f"MT5_{brut}"


@app.route("/deals", methods=["GET"])
@require_api_key
def deals():
    """Retourne le deal de fermeture (DEAL_ENTRY_OUT) pour un ticket donné.

    Utilisé par le radar (_reconcile_open_trades) pour mettre à jour
    personal_trades.status/exit_price/pnl quand MT5 a fermé la position
    naturellement (SL/TP touchés) sans passer par /kill ni /close.

    Réponses :
    - closed=true  : position fermée, exit_price + pnl + closed_at renseignés
    - closed=false : position encore ouverte côté MT5
    - closed=null  : aucun deal trouvé (ticket inconnu ou history purgée)
    """
    try:
        ticket = int(request.args.get("ticket", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "ticket must be int"}), 400
    if ticket <= 0:
        return jsonify({"error": "ticket required"}), 400

    if not ensure_mt5_connected():
        return jsonify({"error": "MT5 not connected"}), 503

    pos = mt5.positions_get(ticket=ticket)
    if pos:
        return jsonify({"ticket": ticket, "closed": False})

    deals_list = mt5.history_deals_get(position=ticket) or []
    out_deal = next(
        (d for d in deals_list if d.entry == mt5.DEAL_ENTRY_OUT), None
    )
    if out_deal is None:
        return jsonify({
            "ticket": ticket,
            "closed": None,
            # ⚠️ PAS "reason" : le backend lit `reason` comme la CAUSE DE
            # CLÔTURE (mt5_sync._update_closed_trade). Y mettre un message
            # d'erreur ferait enregistrer "no deals found" comme cause.
            "message": "no deals found",
        })

    # Decomposition des couts. `profit` seul cache la commission et le swap :
    # le courtier les porte sur des deals distincts (souvent l'entree), donc on
    # somme sur TOUS les deals de la position, pas seulement celui de sortie.
    # Ajoute le 2026-08-11 : l'ecart entre la simulation sans frais (+0,278 R)
    # et le reel (+0,115 R) vaut 0,163 R sans qu'on sache de quoi il est fait.
    profit = swap = commission = fee = 0.0
    in_deal = None
    for d in deals_list:
        profit += float(getattr(d, "profit", 0) or 0)
        swap += float(getattr(d, "swap", 0) or 0)
        commission += float(getattr(d, "commission", 0) or 0)
        fee += float(getattr(d, "fee", 0) or 0)
        if getattr(d, "entry", None) == mt5.DEAL_ENTRY_IN and in_deal is None:
            in_deal = d

    return jsonify({
        "ticket": ticket,
        "closed": True,
        "exit_price": float(out_deal.price),
        "entry_price": float(in_deal.price) if in_deal is not None else None,
        "volume": float(getattr(out_deal, "volume", 0) or 0),
        # `pnl` reste le profit BRUT du deal de sortie, comme avant : ne pas
        # changer le sens d'un champ que le backend consomme deja.
        "pnl": float(out_deal.profit),
        "profit_brut": round(profit, 4),
        "swap": round(swap, 4),
        "commission": round(commission, 4),
        "fee": round(fee, 4),
        "pnl_net": round(profit + swap + commission + fee, 4),
        "n_deals": len(deals_list),
        # La cause vient de MT5 lui-même. Sans elle, le backend en était réduit
        # à comparer le prix de sortie aux SL/TP stockés — ce qui a fait
        # étiqueter « fermé à la main » 215 sorties du stop suiveur (08-10),
        # parce que le stop avait bougé et que la base gardait celui d'origine.
        "reason": _deal_reason_label(out_deal),
        # ⚠️ Ce que ces champs NE disent PAS. MT5 ne garde pas l'historique des
        # modifications de stop : sur une position déjà fermée, seul le niveau
        # qui l'a DÉCLENCHÉE est récupérable (il est dans l'ordre de clôture).
        # Les autres cas rendent {} — une absence, pas un niveau supposé. Pour
        # les positions à venir, c'est le monitor qui capture les vrais niveaux
        # vivants (cf. `_derniers_niveaux`), et lui les a tous.
        **_niveaux_depuis_historique(ticket),
        # ⚠️ `deal.time` est l'heure SERVEUR du courtier, pas un instant UTC.
        # L'habiller de tz=utc décale la valeur (mesuré : 3 h sur ICMarketsEU,
        # base 01:05:21 contre 04:05:19 annoncé UTC). Sans effet sur les
        # montants, mais fausse toute analyse par heure de séance. À corriger
        # en mesurant le décalage serveur ; laissé tel quel pour ne pas
        # déplacer en silence toutes les dates déjà enregistrées.
        "closed_at": datetime.fromtimestamp(out_deal.time, tz=timezone.utc).isoformat(),
    })


def _asset_class_for_symbol(symbol: str) -> str:
    """Dérive la classe d'asset depuis le symbole MT5 (EURUSD, XAUUSD, BTCUSD, etc.).

    Le radar passe par l'asset_class_for(pair) de config.settings ; ici on
    reproduit la même logique côté bridge sans importer le package radar.
    """
    s = (symbol or "").upper()
    if any(k in s for k in ("BTC", "ETH", "LTC", "XRP", "DOGE", "SOL", "ADA")):
        return "crypto"
    if any(k in s for k in ("XAU", "XAG", "GOLD", "SILVER", "PALL", "PLAT")):
        return "metal"
    if any(k in s for k in ("SPX", "NDX", "NAS", "DJ", "DAX", "FTSE", "NIKK", "CAC", "STOXX", "ASX")):
        return "equity_index"
    if any(k in s for k in ("WTI", "OIL", "BRENT", "USOIL", "UKOIL", "GAS")):
        return "energy"
    return "forex"


def _max_lot_for_symbol(symbol: str) -> float:
    """Retourne le cap effectif : min(MAX_LOT global, MAX_LOT_PER_CLASS[class])."""
    cls = _asset_class_for_symbol(symbol)
    class_cap = MAX_LOT_PER_CLASS.get(cls)
    if class_cap is None:
        return MAX_LOT
    return min(MAX_LOT, float(class_cap))


RISK_RATIO_MIN = float(os.getenv("RISK_RATIO_MIN", "0.5"))
RISK_RATIO_MAX = float(os.getenv("RISK_RATIO_MAX", "0"))   # 0 = desarme


def _risque_realise(entry: float, sl: float, lots: float,
                    point: float, tick_value: float) -> float | None:
    """Combien ce lot risque VRAIMENT, en devise du compte.

    Meme formule que `_compute_lots_from_symbol`, prise a l'envers : on part du
    lot reellement obtenu au lieu du lot souhaite.

    Rend **None** si une donnee manque. Surtout pas 0.0 : c'est ce zero-qui-
    passe-pour-une-mesure qui a laisse 455 ordres partir a 1/1000 du risque
    voulu sans que rien ne bronche.
    """
    distance = abs(entry - sl)
    if distance <= 0 or lots <= 0 or point <= 0 or tick_value <= 0:
        return None
    return (distance / point) * tick_value * lots


_POCHE_OR = "or"
_POCHE_HORS_OR = "hors_or"


def _poche_du_symbole(symbole: str) -> str:
    """Dans quelle poche de risque ce symbole compte-t-il ? (2026-08-28)

    ⚠️ Volontairement PAS `_asset_class_for_symbol` : celle-ci rend `metal`,
    qui verserait l'ARGENT (XAG) dans la poche de l'or. Les 14 % sont demandes
    pour l'or SEUL — l'argent, comme tout le reste, reste sur les 6 %.
    """
    s = (symbole or "").upper()
    return _POCHE_OR if ("XAU" in s or "GOLD" in s) else _POCHE_HORS_OR


# MT5 : POSITION_TYPE_BUY == 0, POSITION_TYPE_SELL == 1. Ecrit en clair pour
# que ce bloc reste executable SANS le module MetaTrader5 — les tests en
# extraient les fonctions du source et les lancent seules.
_TYPE_ACHAT = 0


def _distance_perdante(type_position, entry: float, sl: float) -> float:
    """Distance jusqu'au stop **du cote ou l'on perd**. Zero au-dela.

    `abs(entry - sl)` traite un stop a +50 points comme un risque de 50
    points, alors qu'une position dont le stop verrouille un gain **ne peut
    plus rien perdre**. Son risque est nul, pas symetrique.
    """
    if type_position == _TYPE_ACHAT:
        return max(0.0, entry - sl)
    return max(0.0, sl - entry)


def _risque_position(p, info) -> float | None:
    """Risque en devise du compte d'une position OUVERTE, jusqu'a son stop.

    ⚠️ Rend **None** quand le risque n'est pas bornable — au premier chef
    lorsque la position n'a **pas de stop** (`sl == 0`). Ne jamais rendre
    `0.0` dans ce cas : une position nue est un risque *infini*, pas un risque
    nul, et confondre les deux est exactement ce qui laisserait passer ce
    qu'on veut interdire.

    ⛔ Mais un stop **A L'EQUILIBRE ou au-dela** est l'exact oppose : la
    position ne peut plus perdre, son risque vaut VRAIMENT zero. Avant le
    2026-08-23, `abs(entry - sl)` donnait `distance == 0` a l'equilibre, donc
    `_risque_realise` rendait `None`, donc la position passait pour **nue** et
    **bloquait toute nouvelle ouverture** — sur un message affirmant
    faussement « Position sans stop ». Un stop au-dela, lui, comptait un
    risque fantome egal a la distance du gain verrouille.

    > **Zero mesure et zero faute de mesure ne sont pas le meme zero.** Ici
    > les deux existent, et il fallait les distinguer par leur CAUSE.

    ⚠️ La marge, elle, reste immobilisee : c'est `_controle_marge_libre` qui
    la couvre. Les deux portes restent complementaires.
    """
    try:
        sl = float(getattr(p, "sl", 0.0) or 0.0)
        if sl <= 0:
            return None
        if info is None:
            return None
        entry = float(p.price_open)
        type_position = getattr(p, "type", None)
        if type_position is None:
            # Sens inconnu : on compte le PIRE des deux cotes plutot que de
            # risquer un zero a tort. Sur donnee manquante, on surestime.
            distance_perdante = abs(entry - sl)
        else:
            distance_perdante = _distance_perdante(
                int(type_position), entry, sl)
        if distance_perdante <= 0:
            return 0.0
        return _risque_realise(
            entry, entry - distance_perdante, float(p.volume),
            float(info.point), float(info.trade_tick_value))
    except (TypeError, ValueError, AttributeError):
        return None


def _risque_engage_par_poche(positions, specs,
                             or_separe: bool = True) -> tuple[dict, list]:
    """Somme des risques ouverts, VENTILEE par poche (2026-08-28).

    Rend `({poche: total}, tickets_non_bornables)`. Les deux poches sont
    TOUJOURS presentes, a 0.0 si vides : un `.get()` sur une cle absente
    rendrait `None`, et un total absent finirait par se lire comme un total
    nul — le meme zero-qui-passe-pour-une-mesure que `_risque_realise` refuse.

    `or_separe=False` verse l'or dans la poche commune : c'est l'etat d'avant
    le 28/08, et ce que produit `MAX_RISQUE_ENGAGE_OR_PCT=0`.

    ⛔ Les positions NON BORNABLES (sans stop) restent rendues a part et sans
    poche : leur risque est infini, il ne se range dans aucun budget. Elles
    bloquent les deux poches, pas seulement la leur.
    """
    totaux = {_POCHE_HORS_OR: 0.0, _POCHE_OR: 0.0}
    non_bornables = []
    for p in positions or []:
        symbole = getattr(p, "symbol", None)
        r = _risque_position(p, specs(symbole))
        if r is None:
            non_bornables.append(getattr(p, "ticket", "?"))
            continue
        totaux[_poche_du_symbole(symbole) if or_separe else _POCHE_HORS_OR] += r
    return totaux, non_bornables


def _risque_engage(positions, specs) -> tuple[float, list]:
    """Somme des risques des positions ouvertes, TOUTES poches confondues.

    Rend `(total, tickets_non_bornables)`. `specs` est une fonction
    `symbole -> symbol_info`, injectee pour rester testable sans MT5.
    """
    totaux, non_bornables = _risque_engage_par_poche(positions, specs,
                                                     or_separe=False)
    return totaux[_POCHE_HORS_OR], non_bornables


def _controle_risque_engage(risque_ouvert: float, non_bornables: list,
                            risque_nouveau: float | None, equity: float,
                            plafond_pct: float,
                            poche: str = "") -> tuple[bool, str]:
    """Le plafond porte sur le RISQUE TOTAL, pas sur le nombre de positions.

    Rend `(ok, raison)`. `plafond_pct <= 0` desarme la porte.

    ⚠️ Une position sans stop bloque toute nouvelle ouverture : son risque
    etant non borne, aucun total n'a de sens tant qu'elle est la. C'est
    volontaire — ca rend visible immediatement ce que la sonde de positions
    nues ne signale qu'apres coup.
    """
    if plafond_pct <= 0:
        return True, ""
    if non_bornables:
        return False, (
            f"Position sans stop (tickets {sorted(map(str, non_bornables))}) : "
            "risque non bornable, ouverture refusee"
        )
    if equity is None or equity <= 0:
        return False, "Equity inconnue : risque engage incalculable"
    if risque_nouveau is None:
        return False, "Risque du nouvel ordre non mesurable (stop absent ?)"
    plafond = equity * plafond_pct / 100.0
    total = risque_ouvert + risque_nouveau
    if total > plafond:
        # `poche` nomme le budget refuse : sans elle, un refus a 6 % et un
        # refus a 14 % s'ecrivent pareil et on ne sait pas lequel a mordu.
        ou = f" [{poche}]" if poche else ""
        return False, (
            f"Risque engage{ou} {total:.2f} > {plafond:.2f} "
            f"({plafond_pct}% de {equity:.2f}) : {risque_ouvert:.2f} deja en "
            f"jeu + {risque_nouveau:.2f} demande"
        )
    return True, ""


def _marge_de_profit_r(p, info) -> float | None:
    """Combien de « R » cette position a-t-elle déjà engrangés ?

    `R` = sa propre distance d'entrée à son stop. Rend `None` si la mesure
    n'est pas possible — jamais 0.0, qui se confondrait avec « à l'entrée ».
    """
    try:
        entry = float(p.price_open)
        sl = float(getattr(p, "sl", 0.0) or 0.0)
        courant = float(getattr(p, "price_current", 0.0) or 0.0)
        if sl <= 0 or courant <= 0 or info is None:
            return None
        est_achat = int(getattr(p, "type", _TYPE_ACHAT)) == _TYPE_ACHAT
        risque = _distance_perdante(_TYPE_ACHAT if est_achat else 1, entry, sl)
        if risque <= 0:
            return None
        acquis = (courant - entry) if est_achat else (entry - courant)
        return acquis / risque
    except (TypeError, ValueError, AttributeError):
        return None


def _sigma_journalier(symbole: str) -> float | None:
    """Écart-type journalier du symbole, en unités de PRIX. ``None`` si
    incalculable — jamais une valeur par défaut.

    Mesuré sur `EQUILIBRE_VOL_HEURES` bougies H1, en rendements log, puis
    ramené au jour par `× √24` et converti en prix.

    ⚠️ **Rend `None`, jamais 0.0 ni une valeur inventée.** L'appelant écarte
    la position quand la volatilité est inconnue (fail-closed) : une valeur
    de repli le ferait agir en croyant savoir.

    ⚠️ Appelée sur le chemin d'un ordre : mise en cache `EQUILIBRE_VOL_TTL_SEC`
    (un jour) pour ne pas interroger MT5 à chaque décision, et **ne lève
    jamais** — au pire elle rend `None`.
    """
    if not symbole:
        return None
    maintenant = time.time()
    with _vol_lock:
        hit = _vol_cache.get(symbole)
        if hit and (maintenant - hit[1]) < EQUILIBRE_VOL_TTL_SEC:
            return hit[0]
    try:
        brut = mt5.copy_rates_from_pos(
            symbole, mt5.TIMEFRAME_H1, 0, EQUILIBRE_VOL_HEURES)
        if brut is None or len(brut) < 100:
            logger.info(
                f"equilibre/vol: {symbole} — seulement "
                f"{0 if brut is None else len(brut)} bougies, insuffisant")
            return None
        clotures = [float(b["close"]) for b in brut if float(b["close"]) > 0]
        if len(clotures) < 100:
            return None
        rend = [math.log(clotures[i] / clotures[i - 1])
                for i in range(1, len(clotures))]
        moy = sum(rend) / len(rend)
        var = sum((r - moy) ** 2 for r in rend) / (len(rend) - 1)
        sigma_rel = math.sqrt(var) * math.sqrt(24.0)     # relatif, par jour
        # ⛔ Un flux GELE rend un sigma minuscule mais POSITIF, donc
        # `acquis >= 1,0 x sigma` devient trivialement vrai et TOUTE position
        # devient eligible — fail-OPEN, l'inverse exact du but de cette porte.
        # La volatilite journaliere reelle vaut 0,15 a 0,75 % sur ces paires ;
        # sous 0,01 % ce n'est pas un marche calme, c'est un flux casse.
        if sigma_rel < SIGMA_REL_MIN:
            logger.warning(
                f"equilibre/vol: {symbole} volatilite implausible "
                f"({100 * sigma_rel:.5f} %) — flux gele ? position ecartee")
            return None
        sigma_prix = sigma_rel * clotures[-1]
        if sigma_prix <= 0:
            return None
        with _vol_lock:
            _vol_cache[symbole] = (sigma_prix, maintenant)
        logger.info(
            f"equilibre/vol: {symbole} sigma_jour={sigma_prix:.5f} "
            f"({100 * sigma_rel:.3f} %) sur {len(rend)} rendements H1")
        return sigma_prix
    except Exception as e:
        logger.warning(
            f"equilibre/vol: {symbole} illisible ({type(e).__name__}: {e})")
        return None


def _acquis_en_prix(p) -> float | None:
    """Profit acquis par la position, en unités de PRIX. Signé par le sens."""
    try:
        entree = float(p.price_open)
        courant = float(getattr(p, "price_current", 0.0) or 0.0)
        if courant <= 0:
            return None
        est_achat = int(getattr(p, "type", _TYPE_ACHAT)) == _TYPE_ACHAT
        return (courant - entree) if est_achat else (entree - courant)
    except (TypeError, ValueError, AttributeError):
        return None


def _candidats_equilibre(positions, specs, marge_min_r: float,
                         sigmas=None, marge_min_sigma: float = 0.0) -> list[dict]:
    """Positions dont le stop peut remonter à l'équilibre SANS danger.

    Fonction pure. Rend `[{ticket, symbole, risque_libere, marge_r}]`, les
    plus généreuses d'abord.

    ⚠️ La condition de marge est ce qui sépare ce mécanisme d'un suiveur.
    Un stop posé à l'équilibre sur une position à peine en profit se trouve
    **collé au marché** et se fait sortir par le premier bruit — c'est
    exactement la mécanique qui a coûté −0,329 R sur l'or.

    ## Deux conditions, la plus STRICTE des deux (2026-08-24)

    1. `marge_min_r` — le plancher de politique, en R ;
    2. `marge_min_sigma` — la porte de BRUIT, en écarts-types journaliers.

    ⛔ **Pourquoi le R ne suffit pas.** Son unité est mauvaise : le même
    `0,40 R` place le stop à des distances du bruit qui varient d'un facteur
    **4,5** selon l'instrument, mesuré sur 1067 bougies H1 chez le courtier :

        EUR/GBP 1,07 σ · GBP/USD 0,80 σ · GBP/JPY 0,48 σ · USD/JPY 0,24 σ

    À 0,24 σ on est au BE 0 %, la seule politique sans suiveur mesurée
    significativement destructrice (−0,099 R, t = −2,61). **Aucune valeur en
    R ne peut être bonne partout** — le σ supprime l'arbitrage au lieu de le
    trancher.

    ⛔ **Volatilité inconnue ⇒ PAS candidat.** Retomber sur le R seul serait
    fail-open, et précisément sur l'instrument dangereux. Le coût est que la
    soupape ne se déclenche pas, donc l'ordre reste refusé : c'est le côté
    sûr de l'erreur.

    `sigmas` est une fonction `symbole -> écart-type journalier en PRIX`, ou
    `None`. `marge_min_sigma <= 0` désarme la porte de bruit et rend
    exactement le comportement d'avant.
    """
    sortie = []
    for p in positions or []:
        info = specs(getattr(p, "symbol", None))
        risque = _risque_position(p, info)
        if not risque or risque <= 0:
            continue                      # nue, ou déjà à l'équilibre
        marge = _marge_de_profit_r(p, info)
        # ⚠️ Tolerance : `0.005 / 0.005` ne rend pas exactement 1.0 en
        # flottant. Sans elle, le seuil annonce comme inclusif exclut son
        # propre cas limite — un ecart qu'on relirait plus tard comme un bug.
        if marge is None or marge < marge_min_r - 1e-9:
            continue                      # pas assez de coussin : on ne touche pas

        symbole = getattr(p, "symbol", None)
        if marge_min_sigma > 0:
            # ⚠️ Ne JAMAIS laisser une source de volatilite faire tomber un
            # ordre : c'est une aide a la decision, pas le chemin critique.
            try:
                sigma = sigmas(symbole) if sigmas else None
            except Exception as e:
                logger.warning(
                    f"equilibre: volatilite illisible pour {symbole} "
                    f"({type(e).__name__}: {e}) — position ecartee")
                sigma = None
            if not sigma or sigma <= 0:
                logger.info(
                    f"equilibre: {symbole} ecarte, volatilite inconnue "
                    f"(fail-closed : on ne pose pas un stop dans le bruit "
                    f"en croyant le contraire)")
                continue
            acquis = _acquis_en_prix(p)
            if acquis is None or acquis < marge_min_sigma * sigma - 1e-12:
                continue

        sortie.append({
            "ticket": getattr(p, "ticket", None),
            "symbole": symbole,
            "risque_libere": risque,
            "marge_r": marge,
        })
    return sorted(sortie, key=lambda c: -c["risque_libere"])


def _choisir_pour_liberer(candidats: list[dict], manque: float) -> list[dict]:
    """Le moins de positions possible pour couvrir `manque`. Fonction pure.

    On prend les plus généreuses d'abord : libérer le déficit en touchant
    UNE position vaut mieux qu'en toucher trois. Chaque stop déplacé est une
    intervention sur un trade vivant, et on en veut le moins possible.

    Rend `[]` si l'ensemble des candidats ne suffit pas — **on ne déplace
    aucun stop pour un résultat qui échouera quand même**.
    """
    if manque <= 0:
        return []
    total, retenus = 0.0, []
    for c in candidats:
        retenus.append(c)
        total += c["risque_libere"]
        if total >= manque:
            return retenus
    return []


def _remonter_a_l_equilibre(retenus: list[dict], positions) -> list[dict]:
    """Pose le stop À L'ENTRÉE — jamais au-delà. Rend le détail.

    ⛔ Quatre refus possibles, chacun laissant la position INTACTE :

    1. `_clamp_stops` repousse un stop trop proche du marché hors de la zone
       interdite du courtier. Le stop obtenu peut donc ne PAS être à
       l'équilibre — on le vérifie au lieu de le supposer.
    2. Un stop **au-delà de l'entrée** est refusé : il verrouillerait un gain
       sans libérer un euro de plus, et se rapprocherait du marché pour rien.
    3. Si le stop clampé est **moins protecteur** que l'actuel, on renonce :
       ce mécanisme ne doit jamais AUGMENTER le risque d'une position.
    4. Si `_apply_stops` échoue côté courtier, on le trace et on continue.

    Chaque déplacement est journalisé : un mécanisme qui se déclenche une
    fois par mois ne devient mesurable que si chaque activation laisse une
    trace exploitable.
    """
    par_ticket = {getattr(p, "ticket", None): p for p in positions or []}
    faits = []
    for c in retenus:
        p = par_ticket.get(c["ticket"])
        if p is None:
            continue
        entree = float(p.price_open)
        sl_actuel = float(getattr(p, "sl", 0.0) or 0.0)
        est_achat = int(getattr(p, "type", _TYPE_ACHAT)) == _TYPE_ACHAT
        tp = float(getattr(p, "tp", 0.0) or 0.0)

        sl_vise, _ = _clamp_stops(c["symbole"], est_achat, entree, tp)

        # (1) le clamp a-t-il rendu un stop VRAIMENT a l'equilibre ?
        reste = _distance_perdante(_TYPE_ACHAT if est_achat else 1,
                                   entree, sl_vise)

        # (2) ⛔ JAMAIS AU-DELA DE L'ENTREE — tranche le 2026-08-23.
        # Verrouiller un gain ne libere pas un euro de plus : `_risque_position`
        # clampe a zero des l'equilibre, donc un stop positif rend le MEME
        # risque nul. Il ne fait que rapprocher le stop du marche, donc
        # augmenter la chance d'une sortie par le bruit — la definition d'un
        # suiveur, la famille mesuree a -0,329 R sur l'or.
        #
        # ⚠️ Le spread ne justifie pas de decaler : `price_open` d'un achat est
        # l'ask du fill et `price_current` vaut le BID (mesure sur 4 positions
        # reelles le 23/08), donc un stop a `price_open` rend zero EXACT. La
        # commission est nulle et le swap negligeable sur ces comptes (191
        # trades). Le cout d'execution est deja dans le compte.
        depasse = (sl_vise > entree) if est_achat else (sl_vise < entree)
        if depasse:
            logger.warning(
                f"equilibre[{c['ticket']}] {c['symbole']} REFUSE : le stop "
                f"{sl_vise} depasse l'entree {entree} — ce serait une prise de "
                f"profit deguisee, zero budget en plus. Position intacte")
            continue

        # (3) ne JAMAIS reculer le stop
        recule = (sl_vise < sl_actuel) if est_achat else (sl_vise > sl_actuel)
        if recule:
            logger.warning(
                f"equilibre[{c['ticket']}] {c['symbole']} REFUSE : le stop "
                f"clampe {sl_vise} recule par rapport a {sl_actuel} — "
                f"position laissee intacte")
            continue

        res = _apply_stops(symbol=c["symbole"], ticket=c["ticket"],
                           new_sl=sl_vise, new_tp=tp)
        ok = bool(res.get("ok"))
        logger.info(
            f"equilibre[{c['ticket']}] {c['symbole']} "
            f"entree={entree} sl {sl_actuel} -> {sl_vise} "
            f"marge={c['marge_r']:.2f}R risque_libere~{c['risque_libere']:.2f} "
            f"reste_a_risque={reste:.5f} ok={ok} {res.get('error') or ''}")
        if ok:
            faits.append({**c, "sl_avant": sl_actuel, "sl_apres": sl_vise,
                          "reste_a_risque": reste})
            # ⚠️ Une ligne d'AUDIT, pas seulement un log. Un `logger.info` sur
            # le VPS ne se compte pas, ne se joint pas au devenir de la
            # position, et ne survit pas a une rotation de fichier. Un
            # mecanisme qu'on ne peut pas compter est un mecanisme auquel on
            # ne peut que CROIRE — or celui-ci appartient a la famille mesuree
            # a -0,329 R, donc il doit rester JUGEABLE.
            #
            # ⛔ Ne jamais laisser la journalisation faire echouer le
            # deplacement : le stop est DEJA pose chez le courtier a cet
            # instant. Lever ici ferait croire qu'il n'a pas eu lieu.
            try:
                _db_log_order(
                    mode="live", status="equilibre",
                    symbol=c["symbole"], ticket=c["ticket"],
                    entry=entree, sl=sl_vise, tp=tp or None,
                    client_comment="equilibre",
                    message=(f"marge={c['marge_r']:.2f}R "
                             f"libere={c['risque_libere']:.2f} "
                             f"reste={reste:.5f} sl_avant={sl_actuel}"),
                )
            except Exception as e:
                logger.warning(
                    f"equilibre[{c['ticket']}] stop DEPLACE mais audit non "
                    f"ecrit ({type(e).__name__}: {e}) — activation invisible "
                    f"pour la sonde")
    return faits


def _controle_marge_libre(marge_libre: float | None, marge_nouvelle: float | None,
                          equity: float, plancher_pct: float) -> tuple[bool, str]:
    """Plancher de marge libre APRES l'ordre. Protege de la liquidation.

    Rend `(ok, raison)`. `plancher_pct <= 0` desarme la porte.

    ⚠️ Garde-fou SECONDAIRE : quand la marge du nouvel ordre n'est pas
    calculable, on **laisse passer** en le signalant, plutot que de bloquer
    sur une donnee manquante. Le plafond de risque reste la porte principale.
    """
    if plancher_pct <= 0:
        return True, ""
    if equity is None or equity <= 0 or marge_libre is None:
        return True, ""
    if marge_nouvelle is None:
        return True, ""
    plancher = equity * plancher_pct / 100.0
    restant = marge_libre - marge_nouvelle
    if restant < plancher:
        return False, (
            f"Marge libre apres ordre {restant:.2f} < {plancher:.2f} "
            f"({plancher_pct}% de {equity:.2f})"
        )
    return True, ""


def _controle_risque(risque_reel: float | None, risk_money: float | None,
                     mini: float, maxi: float):
    """Compare le risque obtenu au risque voulu. Rend (rapport, cause_du_refus).

    Mesure du 2026-08-11 sur 610 trades du demo : **455 risquaient un millieme
    de ce qui etait prevu** (cryptos ecrasees par MAX_LOT). Ils ont paye le
    spread sans prendre de position, pour −11 EUR au total, et **rien ne l'a
    signale**.

    ⚠️ Asymetrie assumee dans les valeurs par defaut :

    - **Sous-dimensionnement refuse** (`RISK_RATIO_MIN=0.5`). Une position qui
      risque moins de la moitie du voulu ne peut rien rapporter : refuser est
      strictement benefique.
    - **Sur-dimensionnement seulement MESURE** (`RISK_RATIO_MAX=0`, desarme).
      L'or au lot minimum risque 2 a 5x le voulu sur un petit compte ; le
      refuser par defaut arreterait tout le trading. C'est un probleme de
      CAPITAL, pas une erreur d'execution — a Xavier de trancher, pas a un
      defaut de code.

    ⚠️ Un risque incalculable ne bloque JAMAIS : une panne de calcul ne doit
    pas arreter le trading, le courtier reste l'arbitre. Meme principe que
    l'ajustement a la marge.
    """
    # ⚠️ `risk_money` arrive du JSON : il peut etre une chaine, ou illisible.
    # Comparer directement leverait TypeError et ferait echouer TOUS les
    # ordres — un garde-fou qui casse le trading est pire que pas de garde-fou.
    # Et une valeur illisible n'est PAS un << risque trop faible >> : on ne
    # refuse jamais sur un chiffre qu'on n'a pas su lire.
    try:
        voulu = float(risk_money)
    except (TypeError, ValueError):
        return None, None
    if risque_reel is None or voulu <= 0:
        return None, None
    rapport = risque_reel / voulu
    if mini and rapport < mini:
        return rapport, "risque_realise_trop_faible"
    if maxi and rapport > maxi:
        return rapport, "risque_realise_trop_eleve"
    return rapport, None


def _compute_lots_from_symbol(symbol: str, entry: float, sl: float, risk_money: float) -> float:
    """Sizing précis basé sur les specs RÉELLES du broker pour ce symbole.

    Utilise mt5.symbol_info() pour obtenir :
    - trade_contract_size : unités par lot (forex 100000, XAU 100, etc.)
    - point : taille d'un point (EURUSD=0.00001, XAU=0.01)
    - trade_tick_value : valeur en devise du compte d'un tick pour 1 lot
    - volume_min/max/step : bornes autorisées par le broker

    Formule :
        tick_size = point
        ticks_to_sl = distance / tick_size
        risk_per_lot = ticks_to_sl * tick_value
        lots = risk_money / risk_per_lot

    Tombe en 0.01 si le symbole est inconnu ou si les données sont corrompues.
    """
    info = mt5.symbol_info(symbol)
    if info is None:
        return 0.01
    distance = abs(entry - sl)
    if distance <= 0 or info.point <= 0:
        return 0.01
    ticks_to_sl = distance / info.point
    tick_value = info.trade_tick_value
    if tick_value <= 0:
        return 0.01
    risk_per_lot = ticks_to_sl * tick_value
    if risk_per_lot <= 0:
        return 0.01
    raw_lots = risk_money / risk_per_lot
    # Clamp sur les bornes broker + sur MAX_LOT interne
    step = info.volume_step or 0.01
    lots = round(raw_lots / step) * step
    lots = max(info.volume_min or 0.01, min(info.volume_max or 100.0, lots))
    lots = min(_max_lot_for_symbol(symbol), lots)
    return round(lots, 2)


@app.route("/order", methods=["POST"])
@require_api_key
def place_order():
    """Reçoit un trade_setup et le place (PAPER ou LIVE selon PAPER_MODE).

    Payload JSON attendu (deux modes de sizing possibles) :

    Mode A — lots explicites fournis par le client :
        { "pair": "EUR/USD", "direction": "buy", "entry": ..., "sl": ...,
          "tp": ..., "lots": 0.05, "comment": "..." }

    Mode B — risque ciblé (le bridge calcule les lots selon les specs broker) :
        { "pair": "EUR/USD", "direction": "buy", "entry": ..., "sl": ...,
          "tp": ..., "risk_money": 100, "comment": "..." }

    Si les deux sont présents, risk_money gagne (calcul précis).
    Si aucun n'est présent, erreur 400.

    Réponse LIVE réussie (champs 2026-08-06 en plus des champs historiques
    ok/mode/ticket/price/volume/sizing_mode/tp2_tracked, jamais retirés ni
    renommés — le backend en prod les consomme) :
        "sl_applied": bool | None,  # True = SL confirmé posé sur MT5
        "tp_applied": bool | None,
        "sl_error": str | None,
        "tp_error": str | None,
        "protected": bool,          # True ssi sl_applied est True
    """
    data = request.get_json(silent=True) or {}

    # ─── Validation des champs de base ────────────────────────────
    for field in ("pair", "direction", "entry", "sl", "tp"):
        if field not in data:
            return jsonify({"error": f"missing field: {field}"}), 400
    if "lots" not in data and "risk_money" not in data:
        return jsonify({
            "error": "one of 'lots' or 'risk_money' is required"
        }), 400

    direction = str(data["direction"]).lower()
    if direction not in ("buy", "sell"):
        return jsonify({"error": "direction must be 'buy' or 'sell'"}), 400

    try:
        entry = float(data["entry"])
        sl = float(data["sl"])
        tp = float(data["tp"])
    except (ValueError, TypeError):
        return jsonify({"error": "entry/sl/tp must be numeric"}), 400

    # Cohérence SL/TP selon la direction — vérifié avant sizing pour fail fast
    if direction == "buy" and not (sl < entry < tp):
        return jsonify({"error": "BUY: expected sl < entry < tp"}), 400
    if direction == "sell" and not (tp < entry < sl):
        return jsonify({"error": "SELL: expected tp < entry < sl"}), 400

    # ─── MT5 ──────────────────────────────────────────────────────
    if not ensure_mt5_connected():
        return jsonify({"error": "MT5 not connected"}), 503

    pair = data["pair"]
    # broker_symbol prioritaire si fourni par le radar (multi-tenant symbol
    # mapping cote serveur via MT5_BRIDGE_LIVE_SYMBOL_MAP). Fallback
    # resolve_symbol si absent -> comportement legacy inchange pour les
    # payloads sans broker_symbol (Cedric EA MQL5 payload legacy). Fix
    # 2026-07-29 : dispatch admin_live cassé pendant 14j car bridge ignorait
    # broker_symbol et cherchait pair="WTI/USD" au lieu de "XTIUSD".
    broker_symbol = data.get("broker_symbol")
    if broker_symbol:
        if not mt5.symbol_info(broker_symbol):
            return jsonify({
                "error": f"broker_symbol '{broker_symbol}' not found on {MT5_SERVER}. "
                         f"Try /symbols to see available symbols."
            }), 404
        mt5_symbol = broker_symbol
    else:
        mt5_symbol = resolve_symbol(pair)
        if not mt5_symbol:
            return jsonify({
                "error": f"No MT5 symbol found for {pair}. "
                         f"Try /symbols to see what's available on {MT5_SERVER}."
            }), 404

    # ─── Sizing : lots explicites OU calcul depuis risk_money ────
    risk_money = None      # reste None en sizing explicite : rien a comparer
    if "risk_money" in data:
        try:
            risk_money = float(data["risk_money"])
        except (ValueError, TypeError):
            return jsonify({"error": "risk_money must be numeric"}), 400
        if risk_money <= 0:
            return jsonify({"error": "risk_money must be > 0"}), 400
        lots = _compute_lots_from_symbol(mt5_symbol, entry, sl, risk_money)
        sizing_mode = "risk-based"
    else:
        try:
            lots = float(data["lots"])
        except (ValueError, TypeError):
            return jsonify({"error": "lots must be numeric"}), 400
        sizing_mode = "explicit"

    # ─── Garde-fous lots ──────────────────────────────────────────
    if lots <= 0:
        return jsonify({"error": f"lots must be > 0 (got {lots})"}), 400
    effective_max = _max_lot_for_symbol(mt5_symbol)
    if lots > effective_max:
        return jsonify({
            "error": f"lots {lots} > cap {effective_max} for {mt5_symbol} "
                     f"(class={_asset_class_for_symbol(mt5_symbol)}, "
                     f"MAX_LOT global={MAX_LOT})"
        }), 400

    # ─── Le lot obtenu correspond-il au risque demande ? ──────────
    #
    # Pose le 2026-08-11. Sur 610 trades du demo, 455 (75 %) risquaient un
    # MILLIEME du voulu : le lot calcule pour risquer ~17 EUR sur les cryptos
    # etait ecrase par MAX_LOT, la position partait quand meme, et rien ne le
    # signalait. Ces 455 ordres ont paye le spread sans prendre de position.
    #
    # Le controle vient APRES les plafonds : c'est le lot reellement retenu
    # qu'il faut juger, pas celui qu'on souhaitait.
    rapport_risque = None
    _info_ctrl = mt5.symbol_info(mt5_symbol)
    if _info_ctrl is not None:
        rapport_risque, _cause = _controle_risque(
            _risque_realise(entry, sl, lots, _info_ctrl.point,
                            _info_ctrl.trade_tick_value),
            risk_money if sizing_mode == "risk-based" else None,
            RISK_RATIO_MIN, RISK_RATIO_MAX,
        )
        if _cause:
            logger.warning(
                f"[RISQUE] {mt5_symbol} {lots} lot : risque realise = "
                f"{rapport_risque:.3f}x le voulu ({data.get('risk_money')} EUR) "
                f"-> {_cause}"
            )
            return jsonify({
                "ok": False,
                "blocked": True,
                "reason": _cause,
                "rapport_risque": round(rapport_risque, 4),
                "risk_money": data.get("risk_money"),
                "lots": lots,
            }), 422

    log_prefix = "[PAPER]" if PAPER_MODE else "[LIVE]"
    logger.info(
        f"{log_prefix} {direction.upper()} {lots} {mt5_symbol} "
        f"entry={entry} sl={sl} tp={tp} "
        f"sizing={sizing_mode} "
        f"comment={data.get('comment', '')}"
    )

    client_comment = data.get("comment", "")

    if PAPER_MODE:
        _db_log_order(
            mode="paper", status="paper", pair=pair, symbol=mt5_symbol,
            direction=direction, lots=lots, entry=entry, sl=sl, tp=tp,
            risk_money=data.get("risk_money"), confidence=data.get("confidence"), client_comment=client_comment,
            message="PAPER_MODE=true",
        )
        return jsonify({
            "ok": True,
            "mode": "paper",
            "message": "Ordre simulé uniquement. PAPER_MODE=true dans .env.",
            "sizing_mode": sizing_mode,
            "echo": {
                "pair": pair, "resolved_symbol": mt5_symbol, "direction": direction,
                "entry": entry, "sl": sl, "tp": tp, "lots": lots,
                "comment": client_comment,
            },
        })

    # ─── LIVE mode ──────────────────────────────────────────────
    try:
        return _handle_live_order(
            data=data, pair=pair, mt5_symbol=mt5_symbol, direction=direction,
            lots=lots, entry=entry, sl=sl, tp=tp, sizing_mode=sizing_mode,
            client_comment=client_comment,
        )
    except Exception as e:
        logger.exception(f"LIVE order exception: {e}")
        _db_log_order(
            mode="live", status="error", pair=pair, symbol=mt5_symbol,
            direction=direction, lots=lots, entry=entry, sl=sl, tp=tp,
            risk_money=data.get("risk_money"), confidence=data.get("confidence"), client_comment=client_comment,
            message=f"Python exception: {type(e).__name__}: {e}"[:500],
        )
        return jsonify({
            "ok": False, "mode": "live",
            "error": f"{type(e).__name__}: {e}",
        }), 500


def _handle_live_order(*, data, pair, mt5_symbol, direction, lots, entry, sl, tp, sizing_mode, client_comment):
    """Extrait de place_order pour isoler les exceptions LIVE dans un try/except."""
    ok_gate, reason = _check_safety_gates(
        mt5_symbol, direction, lots=lots, entry=entry, sl=sl)
    if not ok_gate:
        logger.warning(f"[LIVE BLOCKED] {reason}")
        _db_log_order(
            mode="live", status="blocked", pair=pair, symbol=mt5_symbol,
            direction=direction, lots=lots, entry=entry, sl=sl, tp=tp,
            risk_money=data.get("risk_money"), confidence=data.get("confidence"), client_comment=client_comment,
            message=reason,
        )
        return jsonify({"ok": False, "blocked": True, "reason": reason}), 429

    # Distances relatives optionnelles (backend 2026-05-18+) pour neutraliser
    # le biais slippage. Si absentes ou nulles, fallback legacy absolu.
    try:
        sl_dist = float(data.get("sl_dist") or 0.0)
        tp_dist = float(data.get("tp_dist") or 0.0)
    except (ValueError, TypeError):
        sl_dist = 0.0
        tp_dist = 0.0
    result = _send_market_order(
        mt5_symbol, direction, lots, sl, tp,
        comment=client_comment or "scalping-radar",
        sl_dist=sl_dist, tp_dist=tp_dist,
    )

    if result["ok"]:
        logger.info(
            f"[LIVE ✓] ticket #{result['ticket']} {direction} {result['volume']} "
            f"{mt5_symbol} @ {result['price']} SL={sl} TP={tp}"
        )
        # Mémorise TP1/TP2 pour le partial close + trailing dans le monitor.
        tp2_val = data.get("tp2")
        try:
            tp2_float = float(tp2_val) if tp2_val else None
        except (ValueError, TypeError):
            tp2_float = None
        _register_position_meta(result["ticket"], tp1=tp, tp2=tp2_float)
        _db_log_order(
            mode="live", status="filled", pair=pair, symbol=mt5_symbol,
            direction=direction, lots=result["volume"],
            # ⛔ 2026-08-24 : c'était `result["price"]`, le champ MT5 BRUT, qui
            # vaut 0.0 chez IC Markets sur un ordre pourtant rempli — 57 ordres
            # réels enregistrés avec entry=0, contre 39/39 corrects sur le démo.
            # `_prix_pour_audit` prend le prix RÉSOLU, déjà présent dans ce même
            # dict, et rend None plutôt que zéro si rien n'est lisible.
            entry=_prix_pour_audit(result), sl=sl, tp=tp,
            risk_money=data.get("risk_money"), confidence=data.get("confidence"),
            ticket=result["ticket"], retcode=result["retcode"],
            message=result["message"], client_comment=client_comment,
            # Mesure du coût d'exécution (2026-08-06). `entry` ci-dessus reste
            # le prix obtenu pour ne pas changer la sémantique consommée par
            # `personal_trades.entry_price` ; `entry_requested` est le prix que
            # le backend avait demandé, seule référence permettant de calculer
            # un glissement.
            entry_requested=entry,
            fill_price=result.get("fill_price"),
            fill_source=result.get("fill_source"),
        )
        return jsonify({
            "ok": True, "mode": "live",
            "ticket": result["ticket"], "price": result["price"],
            "volume": result["volume"],
            "sizing_mode": sizing_mode,
            "tp2_tracked": tp2_float is not None,
            # ── Champs additifs (2026-08-06) — ne PAS retirer ni renommer
            # les champs ci-dessus, le backend en prod les consomme déjà
            # (cf. backend/services/mt5_bridge.py). Ceux-ci permettent à
            # l'appelant de distinguer une position PROTÉGÉE d'une position
            # NUE sans lire les logs du VPS (incident 2026-08-05 : position
            # XAU/USD ouverte sans SL/TP, invisible dans la réponse HTTP).
            #
            # sl_applied / tp_applied : True = confirmé posé, False =
            # tentative confirmée en échec, None = jamais tenté (paper
            # n'atteint pas ce code) ou MT5 n'a pas répondu à la tentative
            # (état réellement inconnu — cf. `_apply_stops`).
            "sl_applied": result.get("sl_applied"),
            "tp_applied": result.get("tp_applied"),
            "sl_error": result.get("sl_error"),
            "tp_error": result.get("tp_error"),
            # `price` ci-dessus est le brut MT5 (0.0 chez certains brokers
            # malgré un fill réussi) ; `fill_price` est la valeur résolue, et
            # `fill_source` indique si elle est mesurée ou repliée sur le prix
            # demandé — auquel cas le glissement n'est pas observable.
            "fill_price": result.get("fill_price"),
            "fill_source": result.get("fill_source"),
            # Sucre syntaxique : True seulement si le SL est confirmé posé.
            # C'est LE champ à checker pour savoir si le risque est borné.
            "protected": result.get("sl_applied") is True,
        })
    else:
        logger.error(
            f"[LIVE REJECTED] {direction} {mt5_symbol} retcode={result.get('retcode')} "
            f"msg={result.get('message')}"
        )
        _db_log_order(
            mode="live", status="rejected", pair=pair, symbol=mt5_symbol,
            direction=direction, lots=lots, entry=entry, sl=sl, tp=tp,
            risk_money=data.get("risk_money"), confidence=data.get("confidence"),
            retcode=result.get("retcode"), message=result.get("message"),
            client_comment=client_comment,
        )
        return jsonify({
            "ok": False, "mode": "live",
            "retcode": result.get("retcode"),
            "message": result.get("message"),
        }), 500


@app.route("/position/sltp", methods=["POST"])
@require_api_key
def set_position_sltp():
    """Pose un SL (garde-fou) sur une position DÉJÀ OUVERTE et actuellement nue.

    Payload JSON : { "ticket": int, "sl_dist": float }
    ``sl_dist`` est une distance en unités de prix, appliquée depuis le prix
    d'ouverture de la position (``price_open``) — pas depuis le prix courant,
    pour que le stop reflète un risque fixé une fois pour toutes, indépendant
    du moment où le garde-fou tourne.

    Le TP existant n'est JAMAIS modifié : la valeur actuelle de la position
    (``p.tp``, 0 si aucun) est repassée telle quelle dans la requête
    TRADE_ACTION_SLTP — MT5 exige les deux champs dans le même appel, mais
    "repasser tel quel" n'est pas "inventer une valeur".

    Écrite pour `scripts/check-live-positions-sltp.sh` (garde-fou cron EC2)
    suite à l'incident 2026-08-05 (position XAU/USD ouverte sans SL/TP,
    découverte 7h après). Avant ce endpoint, le bridge n'exposait AUCUNE
    route de modification SL/TP — un garde-fou pouvait détecter une position
    nue mais jamais agir.

    ⚠️ Trois verrous, chacun suffisant seul pour refuser d'agir :
    1. ``SLTP_GUARD_ENABLED=false`` (défaut) → route entièrement désactivée.
    2. Ticket dans ``SLTP_GUARD_FROZEN_TICKETS`` → gel explicite permanent.
    3. Position ouverte avant ``SLTP_GUARD_ACTIVATED_AT`` (ou variable non
       définie) → jamais éligible. C'est ce verrou qui garantit qu'une
       position déjà ouverte au moment de la mise en service du garde-fou
       n'est JAMAIS touchée, quelle que soit la configuration ultérieure.

    Une position déjà protégée (``p.sl != 0``) n'est PAS modifiée : la route
    répond ``{"ok": true, "already_protected": true}`` sans envoyer d'ordre.

    Best-effort : ne raise jamais, un échec MT5 est rapporté dans la
    réponse JSON (jamais propagé en exception HTTP 500 sauf cas imprévu).
    """
    if not SLTP_GUARD_ENABLED:
        return jsonify({
            "ok": False, "error": "SLTP_GUARD_ENABLED=false — route désactivée",
        }), 403

    data = request.get_json(silent=True) or {}
    try:
        ticket = int(data.get("ticket"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "ticket requis (int)"}), 400
    try:
        sl_dist = float(data.get("sl_dist"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "sl_dist requis (float > 0)"}), 400
    if sl_dist <= 0:
        return jsonify({"ok": False, "error": "sl_dist doit être > 0"}), 400

    if not ensure_mt5_connected():
        return jsonify({"ok": False, "error": "MT5 not connected"}), 503

    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        return jsonify({
            "ok": False,
            "error": f"position #{ticket} introuvable (fermée ou inexistante)",
        }), 404
    p = positions[0]

    eligible, reason = _sltp_guard_eligible(ticket, int(p.time))
    if not eligible:
        logger.warning(f"[SLTP GUARD] refus ticket={ticket} — {reason}")
        return jsonify({
            "ok": False, "excluded": True, "reason": reason, "ticket": ticket,
        }), 403

    if p.sl and float(p.sl) != 0.0:
        logger.info(f"[SLTP GUARD] ticket={ticket} déjà protégé (sl={p.sl}), no-op")
        return jsonify({
            "ok": True, "already_protected": True, "ticket": ticket,
            "sl": p.sl, "tp": p.tp,
        })

    is_buy = p.type == mt5.POSITION_TYPE_BUY
    new_sl = p.price_open - sl_dist if is_buy else p.price_open + sl_dist
    new_tp = p.tp or 0.0  # préserve le TP existant tel quel (0 = pas de TP)

    info = mt5.symbol_info(p.symbol)
    digits = info.digits if info else 5
    new_sl, new_tp = _clamp_stops(p.symbol, is_buy, new_sl, new_tp)
    new_sl = round(new_sl, digits)
    new_tp = round(new_tp, digits)

    try:
        result = _apply_stops(symbol=p.symbol, ticket=ticket, new_sl=new_sl, new_tp=new_tp)
    except Exception as e:
        logger.exception(f"[SLTP GUARD] exception ticket={ticket}: {e}")
        return jsonify({
            "ok": False, "error": f"{type(e).__name__}: {e}", "ticket": ticket,
        }), 500

    _db_log_order(
        mode="live",
        status="filled" if result["ok"] else "rejected",
        symbol=p.symbol, ticket=ticket, sl=new_sl, tp=new_tp,
        retcode=result.get("retcode"),
        message=result.get("error") or "sltp-guard",
        client_comment="sltp-guard",
    )
    if result["ok"] is True:
        logger.warning(f"[SLTP GUARD] ✓ ticket={ticket} {p.symbol} SL posé à {new_sl}")
    else:
        logger.warning(f"[SLTP GUARD] échec ticket={ticket} {p.symbol}: {result.get('error')}")

    return jsonify({
        "ok": result["ok"],
        "ticket": ticket,
        "symbol": p.symbol,
        "sl": result["sl"],
        "tp": result["tp"],
        "retcode": result.get("retcode"),
        "error": result.get("error"),
    })


@app.route("/audit", methods=["GET"])
@require_api_key
def audit():
    """Liste les ordres enregistrés en DB.

    Query params :
    - limit : max lignes (défaut 50, max 500)
    - since_id : ne retourne que les id > since_id (ordre croissant, pour sync
      incrémentale côté backend Scalping-Radar)
    - status : filtre sur status ('filled', 'closed', 'rejected', 'paper', ...)
    """
    try:
        limit = min(500, int(request.args.get("limit", "50")))
    except ValueError:
        limit = 50
    since_id = request.args.get("since_id")
    status = request.args.get("status")
    try:
        with sqlite3.connect(_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            where = []
            params = []
            if since_id is not None:
                try:
                    where.append("id > ?")
                    params.append(int(since_id))
                except ValueError:
                    pass
            if status:
                where.append("status = ?")
                params.append(status)
            where_sql = ("WHERE " + " AND ".join(where)) if where else ""
            # Si since_id fourni : ordre croissant (pour que le backend sache
            # le dernier id traité). Sinon ordre décroissant (UI humain).
            order_sql = "ORDER BY id ASC" if since_id else "ORDER BY id DESC"
            params.append(limit)
            rows = conn.execute(
                f"SELECT * FROM orders {where_sql} {order_sql} LIMIT ?",
                params,
            ).fetchall()
            return jsonify({
                "count": len(rows),
                "orders": [dict(r) for r in rows],
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/kill", methods=["POST"])
@require_api_key
def kill_switch():
    """Ferme toutes les positions ouvertes immédiatement.

    Respecte PAPER_MODE : en paper, retourne seulement la liste simulée.
    """
    if not ensure_mt5_connected():
        return jsonify({"error": "MT5 not connected"}), 503

    pos_list = mt5.positions_get() or []
    if not pos_list:
        return jsonify({"closed": [], "message": "No open positions"})

    if PAPER_MODE:
        logger.warning(
            f"[PAPER KILL] Aurait fermé {len(pos_list)} position(s) : "
            f"{[p.ticket for p in pos_list]}"
        )
        return jsonify({
            "mode": "paper",
            "would_close": [p.ticket for p in pos_list],
        })

    # LIVE : envoie un ordre opposite sur chaque position
    results = []
    for p in pos_list:
        r = _close_position(p)
        results.append(r)
        _db_log_order(
            mode="live",
            status="filled" if r.get("ok") else "rejected",
            symbol=p.symbol,
            direction="close-" + ("sell" if p.type == mt5.POSITION_TYPE_BUY else "buy"),
            lots=p.volume,
            ticket=p.ticket,
            retcode=r.get("retcode"),
            message=f"KILL: {r.get('message')}",
            client_comment="kill-switch",
        )
    ok = sum(1 for r in results if r.get("ok"))
    logger.warning(f"[LIVE KILL] fermé {ok}/{len(results)} position(s)")
    return jsonify({"mode": "live", "total": len(results), "ok": ok, "results": results})


# ─── Démarrage ──────────────────────────────────────────────────────

def main():
    _db_init()
    logger.info("=" * 60)
    logger.info(f"Bridge MT5 démarrage")
    logger.info(f"  MT5 Python package : {mt5.__version__}")
    logger.info(f"  Compte              : {MT5_LOGIN}@{MT5_SERVER}")
    logger.info(f"  MT5_TERMINAL_PATH   : {MT5_TERMINAL_PATH or '(auto-discover via registry)'}")
    logger.info(f"  PAPER_MODE          : {PAPER_MODE}")
    logger.info(f"  MAX_LOT             : {MAX_LOT}")
    logger.info(f"  Listen              : http://{LISTEN_HOST}:{LISTEN_PORT}")
    logger.info(f"  MAX_DAILY_LOSS_PCT  : {MAX_DAILY_LOSS_PCT}%")
    if DAILY_LOSS_EXCLUDED_TICKETS:
        logger.warning(
            f"  DRAWDOWN - tickets EXCLUS : {sorted(DAILY_LOSS_EXCLUDED_TICKETS)} "
            f"(leur flottant ne compte pas ; retirer a la fermeture)"
        )
    logger.info(f"  MAX_OPEN_POSITIONS  : {MAX_OPEN_POSITIONS}")
    logger.info(f"  DEDUP_WINDOW_SEC    : {DEDUP_WINDOW_SEC}")
    logger.info(f"  TRADING_HOURS_UTC   : {TRADING_HOURS_UTC or '(toujours)'}")
    logger.info(f"  Audit DB            : {_DB_PATH}")
    logger.info(
        f"  SLTP_GUARD_ENABLED  : {SLTP_GUARD_ENABLED} "
        f"(activated_at={SLTP_GUARD_ACTIVATED_AT or '(non défini — fail-closed)'}, "
        f"frozen_tickets={sorted(SLTP_GUARD_FROZEN_TICKETS) or '(aucun)'})"
    )
    if _KEY_AUTOGENERATED:
        logger.warning("=" * 60)
        logger.warning(f"BRIDGE_API_KEY généré automatiquement :")
        logger.warning(f"    {BRIDGE_API_KEY}")
        logger.warning("Copie-le dans .env (BRIDGE_API_KEY=...) pour le garder stable.")
        logger.warning("=" * 60)

    # Test de connexion à MT5 au démarrage — échec rapide si MT5 fermé
    if not ensure_mt5_connected():
        logger.error(
            "Impossible de se connecter à MT5 Desktop. Vérifier que :\n"
            "  1. MT5 Desktop Windows est lancé et affiche le compte.\n"
            "  2. Login/password/server dans .env sont corrects.\n"
            "  3. Aucun autre script n'utilise déjà la session MT5."
        )
        # On continue quand même (pour que /health réponde et dise pourquoi)

    # Démarre le monitor de positions (break-even auto)
    monitor_thread = threading.Thread(
        target=_position_monitor_loop, name="position-monitor", daemon=True
    )
    monitor_thread.start()

    try:
        app.run(host=LISTEN_HOST, port=LISTEN_PORT, debug=False)
    finally:
        _monitor_stop.set()
        monitor_thread.join(timeout=3)


if __name__ == "__main__":
    main()
