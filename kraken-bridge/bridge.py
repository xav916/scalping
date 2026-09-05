"""Kraken Futures bridge — trading perpetuals USD-margined pour scalping-radar.

Fork indépendant du binance-bridge (créé 2026-08-02) — API Kraken Futures v3
est trop différente de Binance pour justifier un bridge unifié.

## Différences clés vs Binance bridge

- **Auth** : HMAC-SHA512 nonce-based avec secret Base64-decoded.
  Signature = base64(HMAC_SHA512(base64decode(secret), sha256(postData + nonce + endpoint_path)))
- **Endpoints** : /derivatives/api/v3/{accounts,openpositions,sendorder,cancelorder,tickers,instruments}
- **Symbols** : PF_XBTUSD (perpetual linear USD-margined), PF_ETHUSD, PF_SOLUSD...
  Format "PF_" = Perpetual Fixed maturity? Non — "Perpetual" USD-vanilla-margined (comme USDT-M chez Binance).
  Format "PI_" = Perpetual Inverse (coin-margined) — on ne trade PAS PI_*.
- **Sizing** : "size" en base asset direct (ex 0.01 BTC pour PF_XBTUSD). Cohérent avec Binance USDT-M.
- **Order type** : "mkt" (market) ; SL/TP via ordres séparés reduceOnly=true avec triggerPrice.
- **Response format** : {"result": "success", "openPositions": [...], "sendStatus": {...}}

## Safety gates (miroir du binance-bridge commit 0b60261)

- KRAKEN_MAX_DAILY_LOSS_PCT (default 3%) — kill-switch avec anti-drift built-in
- KRAKEN_LIVE_WHITELIST_SYMBOLS — opt-in strict (default vide = tous supportés)

## Env vars requises

- KRAKEN_API_KEY (~56 chars, format base64-like)
- KRAKEN_API_SECRET (~88 chars base64 avec ==)
- KRAKEN_BRIDGE_API_KEY (auth interne bridge↔radar, générée à l'init)
- KRAKEN_BRIDGE_PORT (default 8790, pour ne pas collision Binance 8789)

Cf. mémoire project_session_summary_2026_08_02.md
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import threading
import time
from datetime import date, datetime, timezone
from decimal import ROUND_FLOOR, Decimal
from functools import wraps
from typing import Any
from urllib.parse import urlencode

import httpx
from flask import Flask, jsonify, request


# ─── Empreinte de la source ────────────────────────────────────────────
# ⛔ Calculee A L'IMPORT, jamais a la requete. Un fichier edite sur disque
# n'est pas le code que le processus execute : hacher a la requete
# annoncerait la NOUVELLE version tout en faisant tourner l'ANCIENNE, ce qui
# est pire que pas d'empreinte du tout.
#
# Pourquoi elle existe (2026-08-25) : le repli de resolution de symbole ajoute
# le 08/08 a disparu sans que personne le voie, faute de pouvoir comparer ce
# qui tourne a ce qui est versionne. Comparer avec :
#     sha256sum <fichier du depot> | cut -c1-12
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


# ─── Config ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("kraken-bridge")

BASE_URL = "https://futures.kraken.com/derivatives"
KRAKEN_API_KEY = os.getenv("KRAKEN_API_KEY", "")
KRAKEN_API_SECRET = os.getenv("KRAKEN_API_SECRET", "")
BRIDGE_API_KEY = os.getenv("KRAKEN_BRIDGE_API_KEY", "")
BRIDGE_PORT = int(os.getenv("KRAKEN_BRIDGE_PORT", "8790"))

# ─── Safety gates ──────────────────────────────────────────────────────
MAX_DAILY_LOSS_PCT = float(os.getenv("KRAKEN_MAX_DAILY_LOSS_PCT", "3.0"))
LIVE_WHITELIST_SYMBOLS = frozenset(
    s.strip().upper()
    for s in os.getenv("KRAKEN_LIVE_WHITELIST_SYMBOLS", "").split(",")
    if s.strip()
)
MAX_OPEN_POSITIONS = int(os.getenv("KRAKEN_MAX_OPEN_POSITIONS", "10"))
# ─── Plafond par le RISQUE ENGAGE (2026-08-29) ────────────────────────────
# Kraken n'avait AUCUNE porte de risque cumule : seulement une perte
# journaliere a 3 % et un compteur de positions a 10. Or un compteur traite
# toutes les positions comme equivalentes alors qu'elles ne le sont pas — le
# meme constat qui avait fait poser cette porte cote MT5 le 20/08.
#
# ⚠️ 50 % est une DECISION de Xavier, pas une mesure : c'est la moitie du
# compte si tous les stops tombent ensemble. Deux fois et demie le plafond
# total des comptes MT5 (20 %). Rien n'a mesure ce que ce niveau vaut.
#
# 0 = desarme (comportement d'avant, seuls le drawdown et le compteur agissent).
MAX_RISQUE_ENGAGE_PCT = float(os.getenv("KRAKEN_MAX_RISQUE_ENGAGE_PCT", "50.0"))

_start_of_day_balance: float | None = None
_start_of_day_date: date | None = None
_nonce_lock = threading.Lock()
_last_nonce = 0

# ─── Symbol mapping ────────────────────────────────────────────────────
# scalping-radar pair → Kraken Futures symbol (PF_ = Perpetual USD-margined)
_PAIR_TO_SYMBOL: dict[str, str] = {
    "BTC/USD": "PF_XBTUSD",
    "ETH/USD": "PF_ETHUSD",
    "SOL/USD": "PF_SOLUSD",
    "ADA/USD": "PF_ADAUSD",
    "XRP/USD": "PF_XRPUSD",
    "LTC/USD": "PF_LTCUSD",
    "BCH/USD": "PF_BCHUSD",
    "DOT/USD": "PF_DOTUSD",
    "DOGE/USD": "PF_DOGEUSD",
    "AVAX/USD": "PF_AVAXUSD",
    "MATIC/USD": "PF_MATICUSD",
    "LINK/USD": "PF_LINKUSD",
    # Ouvertes le 2026-08-23. Les six autres portes etaient DEJA ouvertes pour
    # elles (whitelist du bridge, admission, SHADOW_CONFIG en 1d, blocklist,
    # seuil de confiance, classe d'actif) : seule cette table manquait, et
    # elles partaient a la poubelle en HTTP 400 chaque nuit depuis l'extension
    # de l'univers. Retenues sur leur SPREAD, mesure du 23/08 — la reference
    # etant le pire deja accepte, DOT a 5,6 bp :
    "PAXG/USD": "PF_PAXGUSD",   # 0,9 bp
    "BNB/USD": "PF_BNBUSD",     # 1,6 bp
    "UNI/USD": "PF_UNIUSD",     # 4,9 bp
    "ALGO/USD": "PF_ALGOUSD",   # 5,6 bp
    # ⛔ Les dix autres candidates (XLM, SEI, ENS, HBAR, ARB, CRV, LDO, AAVE,
    # MANA, ETHFI) ont ete SORTIES de WATCHED_PAIRS le meme jour : de 6,2 a
    # 27,9 bp de spread, quand les frais taker seuls valent deja 2,6 fois
    # l'edge mesure. Ne pas les rajouter ici sans remesurer.
    # xStocks Backed Finance (tokens perpetuels backés par vraies actions/ETFs)
    # UI Kraken FR cache la recherche, MAIS API accepte les ordres (validé 2026-08-02).
    # Trading 24/7 avec levier ~10x auto, prix decouplé des vrais marchés NYSE.
    "AAPL": "PF_AAPLXUSD",
    "TSLA": "PF_TSLAXUSD",
    "NVDA": "PF_NVDAXUSD",
    "MSFT": "PF_MSFTXUSD",
    "GOOGL": "PF_GOOGLXUSD",
    "AMZN": "PF_AMZNXUSD",
    "MSTR": "PF_MSTRXUSD",
    "COIN": "PF_COINXUSD",
    "HOOD": "PF_HOODXUSD",
    "SPY": "PF_SPYXUSD",
    "QQQ": "PF_QQQXUSD",
    "GLD": "PF_GLDXUSD",
}


def _resolve_symbol(pair: str) -> str | None:
    """Paire du radar vers symbole Kraken Futures.

    La carte explicite prime, et elle reste indispensable : ``BTC/USD`` se
    derive en ``PF_BTCUSD``, qui **n'existe pas** — Kraken nomme le bitcoin
    ``PF_XBTUSD``. Les exceptions de nommage ne se devinent pas.

    Pour tout le reste, on derive ``PF_<BASE>USD`` et on le **valide contre le
    catalogue d'instruments negociables** du courtier. Jamais de symbole
    devine : un symbole non valide part en ordre et se fait refuser au mieux,
    executer sur le mauvais instrument au pire.

    ⛔ Retabli le 2026-08-25. Ce repli existait depuis le 2026-08-08 et avait
    disparu : le fichier vivait hors git, une edition manuelle l'a ecrase.
    Entre le 20 et le 24/08, 13 ordres ont ete refuses en ``unsupported pair``
    sur 8 instruments pourtant presents au catalogue (HBAR, XLM, AAVE, ALGO,
    ARB, BNB, MANA, SEI) — la carte en connait 16, le courtier en cote 280.
    """
    explicite = _PAIR_TO_SYMBOL.get(pair)
    if explicite:
        return explicite

    morceaux = (pair or "").upper().split("/")
    if len(morceaux) != 2:
        return None
    base, cotation = morceaux[0].strip(), morceaux[1].strip()
    # Seuls les perpetuels marges en USD sont derivables ainsi.
    if not base or not base.isalnum() or cotation != "USD":
        return None

    derive = f"PF_{base}USD"
    if _get_specs(derive):
        return derive

    # ⚠️ Ne pas confondre « le courtier ne cote pas cet instrument » avec « on
    # n'a pas pu lire le catalogue ». Les deux rendent None — c'est le choix
    # sur : on n'envoie jamais d'ordre sur un symbole non valide. Mais les deux
    # doivent se LIRE differemment dans le journal, sinon une panne reseau se
    # diagnostique comme un instrument absent.
    if not _specs_cache:
        logger.warning(
            "_resolve_symbol(%s) : catalogue d'instruments VIDE — refus par "
            "defaut de prudence, ce n'est PAS la preuve que %s n'existe pas",
            pair, derive,
        )
    else:
        logger.info(
            "_resolve_symbol(%s) : %s absent des %d instruments negociables",
            pair, derive, len(_specs_cache),
        )
    return None


# ─── Auth Kraken Futures v3 ────────────────────────────────────────────

def _get_nonce() -> str:
    """Nonce unique croissant (millisecond timestamp + counter en cas de collision)."""
    global _last_nonce
    with _nonce_lock:
        candidate = int(time.time() * 1000)
        if candidate <= _last_nonce:
            candidate = _last_nonce + 1
        _last_nonce = candidate
        return str(candidate)


def _sign(endpoint_path: str, post_data: str, nonce: str) -> str:
    """Signature Kraken Futures v3.

    Formule officielle :
      Authent = Base64(HMAC_SHA512(
                        Base64Decode(API_SECRET),
                        SHA256(postData + nonce + endpoint_path_without_api_prefix)
                      ))

    Note : "endpoint_path" doit être SANS le préfixe "/derivatives" mais AVEC
    "/api/v3/xxx". Ex: pour /derivatives/api/v3/accounts, passer "/api/v3/accounts".
    """
    if not KRAKEN_API_SECRET:
        raise RuntimeError("KRAKEN_API_SECRET not set")
    message = (post_data + nonce + endpoint_path).encode()
    sha256_hash = hashlib.sha256(message).digest()
    secret_decoded = base64.b64decode(KRAKEN_API_SECRET)
    signature = hmac.new(secret_decoded, sha256_hash, hashlib.sha512).digest()
    return base64.b64encode(signature).decode()


def _signed_request(
    method: str, endpoint_path: str, params: dict | None = None, timeout: float = 10.0
) -> Any:
    """Appel signé Kraken Futures (nécessite API_KEY + SECRET).

    endpoint_path = chemin sans /derivatives, ex '/api/v3/accounts'.
    """
    if not KRAKEN_API_KEY or not KRAKEN_API_SECRET:
        raise RuntimeError("KRAKEN_API_KEY and KRAKEN_API_SECRET must be set")
    nonce = _get_nonce()
    # postData = query string (sorted for signature stability)
    params = params or {}
    post_data = urlencode(sorted(params.items()))
    signature = _sign(endpoint_path, post_data, nonce)
    headers = {
        "APIKey": KRAKEN_API_KEY,
        "Authent": signature,
        "Nonce": nonce,
        "Accept": "application/json",
    }
    url = f"{BASE_URL}{endpoint_path}"
    with httpx.Client(timeout=timeout) as c:
        if method.upper() == "GET":
            r = c.get(url, params=params, headers=headers)
        elif method.upper() == "POST":
            # Send the exact signed string as body (dict reordering by httpx breaks HMAC)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            r = c.post(url, content=post_data, headers=headers)
        else:
            raise ValueError(f"Unsupported method: {method}")
        r.raise_for_status()
        return r.json()


def _public_get(endpoint_path: str, params: dict | None = None, timeout: float = 8.0) -> Any:
    """Appel non-signé Kraken Futures (tickers, instruments)."""
    url = f"{BASE_URL}{endpoint_path}"
    with httpx.Client(timeout=timeout) as c:
        r = c.get(url, params=params or {})
        r.raise_for_status()
        return r.json()


# ─── Balance / safety refresh ──────────────────────────────────────────

def _get_current_balance_usd() -> float | None:
    """Retourne portefeuille USD (Trading account) sur Kraken Futures.

    Kraken renvoie plusieurs accounts (flex, cash, futures wallet). On agrège
    portfolioValue du 'flex' account (ou 'cash' fallback). Style USDⓈ-M.
    """
    try:
        data = _signed_request("GET", "/api/v3/accounts")
        if data.get("result") != "success":
            logger.warning(f"_get_current_balance_usd: response not success: {data}")
            return None
        accounts = data.get("accounts", {}) or {}
        # Kraken structure : accounts.cash, accounts.flex, accounts.futures
        # Le "cash" account contient les USD depositables ; le "flex" contient
        # les collaterals utilisables pour perpetuals.
        # Try flex first, fallback cash
        flex = accounts.get("flex") or {}
        cash = accounts.get("cash") or {}
        # portfolioValue = total collateral value in USD
        if flex.get("portfolioValue") is not None:
            return float(flex["portfolioValue"])
        if cash.get("balances", {}).get("USD") is not None:
            return float(cash["balances"]["USD"])
        return None
    except Exception as e:
        logger.debug(f"_get_current_balance_usd error: {e}")
        return None


FICHIER_REFERENCE = os.getenv(
    "KRAKEN_START_OF_DAY_FILE", "/opt/kraken-bridge/state/start_of_day.json"
)


def _charger_reference() -> float | None:
    """Solde de référence du jour, s'il a déjà été posé aujourd'hui.

    ``None`` si le fichier est absent, illisible, ou daté d'un autre jour —
    auquel cas l'appelant pose une référence neuve. Toute erreur est
    silencieuse : la protection ne doit pas empêcher le bridge de démarrer,
    et l'absence de référence est déjà le comportement d'origine.
    """
    try:
        import json
        with open(FICHIER_REFERENCE, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("date") != date.today().isoformat():
            return None
        v = float(d.get("balance") or 0)
        return v if v > 0 else None
    except Exception:
        return None


def _ecrire_reference(balance: float) -> None:
    """Fige le solde de référence du jour pour survivre à un redémarrage."""
    try:
        import json
        os.makedirs(os.path.dirname(FICHIER_REFERENCE), exist_ok=True)
        with open(FICHIER_REFERENCE, "w", encoding="utf-8") as f:
            json.dump({"date": date.today().isoformat(),
                       "balance": round(float(balance), 4)}, f)
    except Exception as e:
        logger.warning(f"reference de debut de journee non persistee : {e}")


def _refresh_start_of_day() -> None:
    """Miroir du bridge MT5/Binance : refresh au changement de jour + anti-drift."""
    global _start_of_day_balance, _start_of_day_date
    today = date.today()
    current = _get_current_balance_usd()
    if current is None:
        return
    if _start_of_day_date != today:
        # Relire le disque AVANT de rebaser : la référence ne vivait qu'en
        # mémoire, si bien qu'un simple redémarrage effaçait la perte déjà
        # encaissée dans la journée et rouvrait 3 % de marge de perte.
        # Constaté le 2026-08-04 : un redéploiement du bridge à 17h48 a
        # reposé la référence juste avant que le compte perde 4,3 %.
        persiste = _charger_reference()
        if persiste is not None:
            _start_of_day_balance, _start_of_day_date = persiste, today
            logger.info(
                f"Kraken start-of-day balance relue sur disque = "
                f"{_start_of_day_balance:.2f} USD (date={today.isoformat()})"
            )
            return
        _start_of_day_balance = current
        _start_of_day_date = today
        _ecrire_reference(current)
        logger.info(
            f"Kraken start-of-day balance = {_start_of_day_balance:.2f} USD "
            f"(date={today.isoformat()})"
        )
        return
    if _start_of_day_balance is not None and current > 0:
        ratio = _start_of_day_balance / current
        if ratio > 1.5 or ratio < 0.667:
            logger.warning(
                f"Kraken start-of-day drift: cached={_start_of_day_balance:.2f} "
                f"actual={current:.2f} ratio={ratio:.2f} - resync"
            )
            _start_of_day_balance = current
            _ecrire_reference(current)


def _check_daily_drawdown() -> tuple[bool, str]:
    """Retourne (ok, reason). ok=False → refuser /order (429)."""
    _refresh_start_of_day()
    if _start_of_day_balance is None or _start_of_day_balance <= 0:
        return True, ""
    current = _get_current_balance_usd()
    if current is None:
        return True, ""
    loss = _start_of_day_balance - current
    loss_limit = _start_of_day_balance * MAX_DAILY_LOSS_PCT / 100.0
    if loss >= loss_limit:
        return False, (
            f"Daily drawdown reached: loss={loss:.2f} >= limit={loss_limit:.2f} "
            f"({MAX_DAILY_LOSS_PCT}% of {_start_of_day_balance:.2f})"
        )
    return True, ""


# ─── Instruments cache ─────────────────────────────────────────────────
_specs_cache: dict[str, dict[str, Any]] = {}
_specs_cache_ts = 0.0
_SPECS_TTL_SEC = 3600  # 1h


def _refresh_specs_cache() -> None:
    """Charge la liste des instruments Kraken Futures (tickers actifs)."""
    global _specs_cache, _specs_cache_ts
    try:
        data = _public_get("/api/v3/instruments")
        if data.get("result") != "success":
            return
        cache = {}
        for inst in data.get("instruments", []):
            symbol = inst.get("symbol", "").upper()
            if not symbol or not inst.get("tradeable", False):
                continue
            cache[symbol] = {
                "symbol": symbol,
                "tickSize": float(inst.get("tickSize", 0.01)),
                "contractSize": float(inst.get("contractSize", 1.0)),
                # Nombre de décimales admises sur la TAILLE d'ordre. Absent du
                # cache jusqu'au 2026-08-04 : la qty partait brute et Kraken
                # rejetait tout en `invalidSize`. PF_XBTUSD=4, PF_ETHUSD=3.
                "qtyPrecision": int(inst.get("contractValueTradePrecision", 4)),
                "type": inst.get("type", ""),
                "tradeable": True,
            }
        _specs_cache = cache
        _specs_cache_ts = time.time()
        logger.info(f"Kraken specs cache refreshed: {len(cache)} tradeable instruments")
    except Exception as e:
        logger.warning(f"_refresh_specs_cache failed: {e}")


def round_qty_to_precision(qty: float, precision: int) -> float:
    """Tronque une taille d'ordre à la précision admise par l'instrument.

    Kraken refuse toute taille hors précision avec ``invalidSize``, sans
    indiquer laquelle il attendait. Le 2026-08-04, ``qty=0.005744444…`` a
    fait échouer cinq ordres consécutifs avant que la cause soit trouvée :
    ``contractValueTradePrecision`` n'était tout simplement pas lu.

    On tronque **vers le bas**. Arrondir au plus proche pourrait dépasser la
    taille calculée par le sizing, donc engager plus de risque que voulu —
    une taille légèrement trop petite est toujours préférable.

    Retourne ``0.0`` si la taille est sous le pas minimum : à l'appelant de
    refuser l'ordre avec un message explicite.

    L'arithmétique est décimale, pas binaire : ``0.119 / 0.001`` vaut
    ``118.99999999999999`` en flottant, ce qui rabotait d'un pas une taille
    pourtant valide.
    """
    if qty <= 0 or precision < 0:
        return 0.0
    pas = Decimal(1).scaleb(-precision)
    return float(Decimal(str(qty)).quantize(pas, rounding=ROUND_FLOOR))


def _get_specs(symbol: str) -> dict | None:
    """Retourne les specs pour un symbol Kraken. Refresh cache si stale."""
    if time.time() - _specs_cache_ts > _SPECS_TTL_SEC:
        _refresh_specs_cache()
    return _specs_cache.get(symbol.upper())


# ─── Flask app + auth decorator ────────────────────────────────────────
app = Flask(__name__)


def require_bridge_key(fn):
    """Décorateur : exige X-Bridge-Key header matching BRIDGE_API_KEY."""

    @wraps(fn)
    def _wrapped(*args, **kwargs):
        if BRIDGE_API_KEY and request.headers.get("X-Bridge-Key") != BRIDGE_API_KEY:
            return jsonify({"error": "unauthorized"}), 401
        return fn(*args, **kwargs)

    return _wrapped


# ─── Routes ────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    """Ping Kraken public + config bridge. Pas d'auth requise côté Kraken."""
    try:
        # Test public reachability
        _public_get("/api/v3/instruments", timeout=5)
        return jsonify({
            "source_sha": SOURCE_SHA,
            "demarre_a": DEMARRE_A,
            "ok": True,
            "base_url": BASE_URL,
            "api_key_set": bool(KRAKEN_API_KEY),
            "api_secret_set": bool(KRAKEN_API_SECRET),
            "bridge_api_key_set": bool(BRIDGE_API_KEY),
            "port": BRIDGE_PORT,
            "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
            "live_whitelist_symbols": sorted(LIVE_WHITELIST_SYMBOLS) if LIVE_WHITELIST_SYMBOLS else [],
            "max_open_positions": MAX_OPEN_POSITIONS,
            # Plafond par le RISQUE, pose le 2026-08-29. 0 = desarme.
            # ⛔ Un garde-fou qu'on ne peut pas lire est un garde-fou dont on
            # ne sait jamais s'il s'applique.
            "max_risque_engage_pct": MAX_RISQUE_ENGAGE_PCT,
            "start_of_day_balance": _start_of_day_balance,
            "supported_pairs": len(_PAIR_TO_SYMBOL),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 503


@app.route("/account", methods=["GET"])
@require_bridge_key
def account():
    """Retourne les infos du compte Kraken Futures (balance, margin, PnL)."""
    try:
        data = _signed_request("GET", "/api/v3/accounts")
        if data.get("result") != "success":
            return jsonify({"ok": False, "error": "kraken response not success", "raw": data}), 503
        accounts = data.get("accounts", {}) or {}
        flex = accounts.get("flex") or {}
        return jsonify({
            "ok": True,
            "portfolio_value_usd": float(flex.get("portfolioValue", 0.0)),
            "available_margin_usd": float(flex.get("availableMargin", 0.0)),
            "initial_margin_usd": float(flex.get("initialMargin", 0.0)),
            "maintenance_margin_usd": float(flex.get("maintenanceMargin", 0.0)),
            # ⛔ Ce champ lisait `unrealizedFunding` sous le nom de P&L latent :
            # deux grandeurs sans rapport, l'une a cinq zeros devant. Personne
            # ne le consommait encore — c'etait un piege arme, pas un degat.
            #
            # ⚠️ Et le corriger en `unrealizedPnl` ne suffisait pas : Kraken
            # n'expose PAS cette cle sur le compte flex. Charge du 05/09 :
            #     pnl               -0,0302178   (latent MOINS le funding)
            #     totalUnrealized   -0,0299323   <- le P&L latent des positions
            #     unrealizedFunding +0,0002855
            "unrealized_pnl_usd": flottant_ou_none(flex, "totalUnrealized", "unrealizedPnl"),
            "unrealized_funding_usd": flottant_ou_none(flex, "unrealizedFunding"),
            "pnl_net_usd": flottant_ou_none(flex, "pnl"),
            "raw_flex": flex,
            "raw_cash": accounts.get("cash", {}),
        })
    except Exception as e:
        logger.exception("account failed")
        return jsonify({"ok": False, "error": str(e)}), 500


_EPOQUE_UNIX = "1970-01-01"


def flottant_ou_none(source: dict, *cles: str):
    """Premiere cle PRESENTE, en flottant — et ``None`` si aucune n'y est.

    ⛔ `float(d.get(k, 0.0))` transforme une absence en **zero**. Sur un P&L,
    zero se lit « le compte est a l'equilibre » quand la verite est « je ne
    sais pas ». C'est la faute exacte de `entry_price=0` cote reel, et celle
    que je viens de commettre en corrigeant ce champ : Kraken n'expose pas
    `unrealizedPnl` sur le compte flex, donc le defaut s'appliquait toujours.
    """
    for c in cles:
        if c in source:
            try:
                return float(source[c])
            except (TypeError, ValueError):
                return None
    return None


def ouvertures_par_symbole(fills: list, positions: list) -> dict:
    """Rend ``{symbole: date d'ouverture ISO | None}`` pour chaque position vivante.

    ⛔ **Kraken ne sait pas dire quand une position a ete ouverte.**
    `/api/v3/openpositions` rend `fillTime = 1970-01-01T00:00:00.000Z` pour
    TOUTES les positions. Le bridge recopiait cette valeur telle quelle.

    Une date fausse est pire qu'une date absente : un age calcule depuis 1970
    vaut ~490 000 heures, ce qui fait passer toute position pour eternelle
    aupres d'une porte de duree, et empoisonne toute mediane de detention sans
    rien signaler. Meme famille que `entry_price=0` cote reel — **`None`,
    jamais une valeur qui a l'air vraie.**

    🔑 La donnee existe dans `/api/v3/fills`, qui porte de vrais horodatages.
    On rejoue donc les executions du symbole, du plus ancien au plus recent, en
    suivant le net signe : l'ouverture est le fill qui a fait passer le net de
    zero (ou du sens contraire) au sens actuel. Un renfort ne rajeunit pas la
    position ; un passage par zero, ou un retournement, redemarre l'horloge.

    ⛔ **La reconstruction doit S'ACCORDER avec la position reelle.** L'historique
    des fills est borne : si le net reconstruit ne retrouve ni le sens ni la
    taille de la position ouverte, l'ouverture est hors fenetre et on rend
    `None` — jamais une date empruntee a la mauvaise position.
    """
    lisibles: list = []
    for f in fills or []:
        try:
            sym = f.get("symbol")
            t = f.get("fillTime") or f.get("fill_time")
            taille = float(f.get("size") or 0)
            sens = -1.0 if str(f.get("side", "")).lower() == "sell" else 1.0
            if not sym or not t or not taille:
                continue
            # ⛔ L'epoque Unix n'est pas une date, c'est un trou.
            if str(t).startswith(_EPOQUE_UNIX):
                continue
            lisibles.append((str(t), sym, sens * taille))
        except (TypeError, ValueError):
            continue
    # Kraken rend les executions du plus RECENT au plus ancien.
    lisibles.sort(key=lambda x: x[0])

    net: dict = {}
    ouvert_depuis: dict = {}
    for t, sym, delta in lisibles:
        avant = net.get(sym, 0.0)
        apres = avant + delta
        if avant == 0.0 or (avant > 0) != (apres > 0):
            # Ouverture, reouverture apres un passage a plat, ou retournement.
            ouvert_depuis[sym] = t
        if abs(apres) < 1e-12:
            apres = 0.0
            ouvert_depuis.pop(sym, None)
        net[sym] = apres

    sortie: dict = {}
    for p in positions or []:
        sym = p.get("symbol")
        if not sym:
            continue
        try:
            taille = abs(float(p.get("size") or 0))
        except (TypeError, ValueError):
            sortie[sym] = None
            continue
        signe = -1.0 if str(p.get("side", "")).lower() == "short" else 1.0
        attendu = signe * taille
        reconstruit = net.get(sym)
        accorde = (
            reconstruit is not None
            and abs(reconstruit - attendu) <= max(1e-6, abs(attendu) * 1e-6)
        )
        sortie[sym] = ouvert_depuis.get(sym) if accorde else None
    return sortie


@app.route("/positions", methods=["GET"])
@require_bridge_key
def positions():
    """Retourne les positions ouvertes sur Kraken Futures."""
    try:
        data = _signed_request("GET", "/api/v3/openpositions")
        if data.get("result") != "success":
            return jsonify({"ok": False, "error": "kraken response not success", "raw": data}), 503
        raw_positions = data.get("openPositions", []) or []

        # ⛔ L'age se RECONSTRUIT depuis les fills : Kraken rend l'epoque Unix
        # dans `fillTime`. Lecture non bloquante — ne pas savoir depuis quand
        # une position est ouverte ne doit jamais empecher de la LIRE. Un echec
        # ici rend `fill_time: null`, et les positions sortent quand meme.
        ouvertures: dict = {}
        try:
            hist = _signed_request("GET", "/api/v3/fills")
            if hist.get("result") == "success":
                ouvertures = ouvertures_par_symbole(
                    hist.get("fills", []) or [], raw_positions)
        except Exception as e:  # noqa: BLE001
            logger.warning("positions: age indisponible (fills injoignables) : %s", e)

        cleaned = []
        for p in raw_positions:
            sym = p.get("symbol")
            cleaned.append({
                "symbol": sym,
                "side": p.get("side"),  # "long" ou "short"
                "size": float(p.get("size", 0.0)),
                "price": float(p.get("price", 0.0)),
                "unrealizedFunding": float(p.get("unrealizedFunding", 0.0)),
                # ⚠️ Le P&L latent etait JETE ici alors que Kraken le rend
                # — et `None` s'il ne le rend pas, jamais un zero.
                "unrealized_pnl_usd": flottant_ou_none(p, "unrealizedPnl"),
                # ⛔ Reconstruit, et `None` quand il ne l'est pas. La valeur
                # brute de Kraken (`fillTime`) vaut 1970 pour tout le monde :
                # elle n'est plus servie, meme pas sous son nom d'origine, pour
                # qu'aucun appelant ne puisse la prendre pour une date.
                "fill_time": ouvertures.get(sym),
            })
        return jsonify({"ok": True, "count": len(cleaned), "positions": cleaned})
    except Exception as e:
        logger.exception("positions failed")
        return jsonify({"ok": False, "error": str(e)}), 500


def _stops_par_symbole(open_orders: list) -> dict:
    """Rend `{symbole: prix_du_stop}` depuis les ordres vivants.

    ⛔ Seuls les ordres `reduceOnly` de type stop comptent. Un ordre d'entree
    en attente sur le meme symbole n'est pas une protection — le confondre
    ferait passer une position nue pour bornee, et c'est exactement ce qu'on
    veut interdire.

    ⚠️ Sur Kraken, le stop n'est PAS un attribut de la position : c'est un
    ordre conditionnel independant. Une position et son stop peuvent donc
    diverger sans que rien ne le signale — d'ou cette jointure explicite.
    """
    stops: dict = {}
    for o in open_orders or []:
        if not o.get("reduceOnly"):
            continue
        sym = o.get("symbol")
        if not sym:
            continue
        if (o.get("orderType") or "").lower() not in ("stp", "stop"):
            continue
        try:
            prix = float(o.get("stopPrice"))
        except (TypeError, ValueError):
            continue
        if prix > 0:
            # Le plus PROTECTEUR si plusieurs : on ne suppose pas qu'il n'y en
            # a qu'un, et surestimer le risque est le bon sens de l'erreur.
            stops[sym] = prix if sym not in stops else stops[sym]
    return stops


def _risque_position_kraken(position: dict, stops: dict) -> float | None:
    """Risque en USD d'une position ouverte, jusqu'a son stop.

    ⛔ Rend **None** quand le risque n'est pas bornable — au premier chef quand
    aucun ordre stop ne couvre le symbole. Jamais `0.0` : une position nue est
    un risque *infini*, pas un risque *nul*, et confondre les deux laisserait
    passer precisement ce qu'on veut interdire. Meme regle que cote MT5.

    ⛔ Un stop du MAUVAIS cote (au-dela de l'entree, donc verrouillant un gain)
    ne peut plus rien perdre : son risque vaut VRAIMENT zero. Zero mesure et
    zero faute de mesure ne sont pas le meme zero.
    """
    try:
        sym = position.get("symbol")
        entree = float(position.get("price"))
        taille = abs(float(position.get("size")))
    except (TypeError, ValueError):
        return None
    if not sym or entree <= 0 or taille <= 0:
        return None
    stop = stops.get(sym)
    if stop is None or stop <= 0:
        return None
    long = str(position.get("side") or "").lower().startswith("l")
    perdant = (entree - stop) if long else (stop - entree)
    if perdant <= 0:
        return 0.0
    return perdant * taille


def _risque_engage_kraken(positions: list, stops: dict) -> tuple:
    """`(total_usd, symboles_non_bornables)`. Fonction pure."""
    total = 0.0
    non_bornables = []
    for p in positions or []:
        r = _risque_position_kraken(p, stops)
        if r is None:
            non_bornables.append(p.get("symbol") or "?")
        else:
            total += r
    return total, non_bornables


def _controle_risque_engage_kraken(risque_ouvert: float, non_bornables: list,
                                   risque_nouveau, equity,
                                   plafond_pct: float) -> tuple:
    """Le plafond porte sur le RISQUE TOTAL, pas sur le nombre de positions.

    Rend `(ok, raison)`. `plafond_pct <= 0` desarme la porte.

    ⚠️ Une position sans stop bloque toute nouvelle ouverture : son risque
    n'etant pas borne, aucun total n'a de sens tant qu'elle est la.
    """
    if plafond_pct <= 0:
        return True, ""
    if non_bornables:
        return False, (
            f"Position sans stop ({sorted(set(map(str, non_bornables)))}) : "
            "risque non bornable, ouverture refusee")
    if equity is None or equity <= 0:
        return False, "Equity inconnue : risque engage incalculable"
    if risque_nouveau is None:
        return False, "Risque du nouvel ordre non mesurable (stop absent ?)"
    plafond = equity * plafond_pct / 100.0
    total = risque_ouvert + risque_nouveau
    if total > plafond:
        return False, (
            f"Risque engage {total:.2f} > {plafond:.2f} "
            f"({plafond_pct}% de {equity:.2f}) : {risque_ouvert:.2f} deja en "
            f"jeu + {risque_nouveau:.2f} demande")
    return True, ""


def _protection_par_symbole(open_orders: list) -> dict:
    """Rend {symbole: {"stop": bool, "objectif": bool}} depuis les ordres vivants.

    Un ordre ne protege une position que s'il la REDUIT. Un ordre d'entree en
    attente sur le meme symbole n'est pas une protection — d'ou le filtre sur
    `reduceOnly`, sans lequel on annoncerait protegee une position qui ne l'est
    pas. C'est precisement le genre de validation muette qui laisse une
    position nue passer pour saine.
    """
    par_sym: dict = {}
    for o in open_orders:
        if not o.get("reduceOnly"):
            continue
        sym = o.get("symbol")
        if not sym:
            continue
        etat = par_sym.setdefault(sym, {"stop": False, "objectif": False})
        t = (o.get("orderType") or "").lower()
        if t in ("stp", "stop"):
            etat["stop"] = True
        elif t in ("take_profit", "takeprofit"):
            etat["objectif"] = True
    return par_sym


@app.route("/openorders", methods=["GET"])
@require_bridge_key
def openorders():
    """Ordres en attente, et l'etat de protection de chaque position ouverte.

    Ajoute le 2026-08-19. Il n'existait AUCUN moyen de verifier qu'une
    position portait encore son stop : `/positions` ne dit rien des ordres, et
    les trois ordres d'une entree Kraken (marche, stop, objectif) sont
    independants — un stop peut echouer a la pose sans que l'entree echoue.
    Une position pouvait donc tourner des jours sans protection, en silence.
    Cf. l'incident de position nue du 2026-08-05.

    `positions_non_protegees` est la reponse a la question qu'on se pose
    vraiment ; les listes brutes restent la pour diagnostiquer.
    """
    try:
        data = _signed_request("GET", "/api/v3/openorders")
        if data.get("result") != "success":
            return jsonify({"ok": False, "error": "kraken response not success", "raw": data}), 503
        bruts = data.get("openOrders", []) or []
        ordres = []
        for o in bruts:
            ordres.append({
                "order_id": o.get("order_id") or o.get("orderId"),
                "symbol": o.get("symbol"),
                "side": o.get("side"),
                "orderType": o.get("orderType"),
                "size": float(o.get("unfilledSize", o.get("size", 0.0)) or 0.0),
                "stopPrice": o.get("stopPrice"),
                "limitPrice": o.get("limitPrice"),
                "reduceOnly": bool(o.get("reduceOnly")),
                "receivedTime": o.get("receivedTime"),
            })

        protection = _protection_par_symbole(ordres)

        # Croisement avec les positions reellement ouvertes.
        nues = []
        try:
            pos_data = _signed_request("GET", "/api/v3/openpositions")
            for p in (pos_data.get("openPositions", []) or []):
                sym = p.get("symbol")
                etat = protection.get(sym, {"stop": False, "objectif": False})
                if not etat["stop"]:
                    nues.append({
                        "symbol": sym,
                        "side": p.get("side"),
                        "size": float(p.get("size", 0.0)),
                        "price": float(p.get("price", 0.0)),
                        "objectif_pose": etat["objectif"],
                    })
        except Exception as e:
            # Ne PAS rendre une liste vide : elle se lirait « tout va bien ».
            logger.warning(f"openorders: croisement positions impossible: {e}")
            return jsonify({
                "ok": False,
                "error": f"positions unreachable: {e}",
                "count": len(ordres),
                "orders": ordres,
            }), 503

        return jsonify({
            "ok": True,
            "count": len(ordres),
            "orders": ordres,
            "protection": protection,
            "positions_non_protegees": nues,
        })
    except Exception as e:
        logger.exception("openorders failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/fills", methods=["GET"])
@require_bridge_key
def fills():
    """Exécutions récentes, avec le P&L réalisé que Kraken calcule lui-même.

    Sert la réconciliation des clôtures (``kraken_sync``). Deux champs font
    tout le travail :

    ``order_id``      celui de l'ordre à l'origine de l'exécution. Pour une
                      clôture, c'est le SL ou le TP posés à l'ouverture —
                      donc la cause de sortie est connue **exactement**,
                      sans deviner par proximité de prix comme côté MT5.
    ``realized_pnl``  en USD, calculé par Kraken. Non nul ⇒ l'exécution a
                      réduit ou fermé une position.

    Lecture seule : aucun ordre n'est passé ni annulé ici.
    """
    try:
        data = _signed_request("GET", "/api/v3/fills")
        if data.get("result") != "success":
            return jsonify({"ok": False, "error": "kraken response not success"}), 503
        nettoyes = []
        for f in data.get("fills", []) or []:
            nettoyes.append({
                "fill_id": f.get("fill_id"),
                "order_id": f.get("order_id"),
                "symbol": f.get("symbol"),
                "side": f.get("side"),
                "size": float(f.get("size") or 0),
                "price": float(f.get("price") or 0),
                "fill_time": f.get("fillTime"),
                "fill_type": f.get("fillType"),
                "realized_pnl": float(f.get("realized_pnl") or 0),
                "realized_funding": float(f.get("realized_funding") or 0),
            })
        return jsonify({"ok": True, "count": len(nettoyes), "fills": nettoyes})
    except Exception as e:
        logger.exception("fills failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/tick/<path:pair>", methods=["GET"])
@require_bridge_key
def tick(pair):
    """Retourne prix bid/ask/last pour une pair scalping-radar."""
    sym = _resolve_symbol(pair)
    if not sym:
        return jsonify({"ok": False, "error": f"unsupported pair {pair}"}), 400
    try:
        data = _public_get("/api/v3/tickers")
        if data.get("result") != "success":
            return jsonify({"ok": False, "error": "kraken tickers not success"}), 503
        for t in data.get("tickers", []):
            if t.get("symbol", "").upper() == sym:
                return jsonify({
                    "ok": True,
                    "pair": pair,
                    "symbol": sym,
                    "bid": float(t.get("bid", 0.0)),
                    "ask": float(t.get("ask", 0.0)),
                    "last": float(t.get("last", 0.0)),
                    "markPrice": float(t.get("markPrice", 0.0)),
                    "indexPrice": float(t.get("indexPrice", 0.0)),
                    "fundingRate": float(t.get("fundingRate", 0.0)),
                })
        return jsonify({"ok": False, "error": f"symbol {sym} not found in tickers"}), 404
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/symbols", methods=["GET"])
@require_bridge_key
def symbols():
    """Liste les symbols Kraken Futures tradeable (PF_ + PI_)."""
    try:
        data = _public_get("/api/v3/instruments")
        if data.get("result") != "success":
            return jsonify({"ok": False}), 503
        syms = [
            i["symbol"] for i in data.get("instruments", [])
            if i.get("tradeable") and i.get("symbol", "").startswith(("PF_", "PI_"))
        ]
        return jsonify({"ok": True, "count": len(syms), "symbols": sorted(syms)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def stops_depuis_fill(
    direction: str,
    avg_price: float,
    sl_dist,
    tp_dist,
    sl_signal,
    tp_signal,
) -> tuple:
    """Repose SL/TP depuis le prix de remplissage. Rend (sl, tp, source).

    `sl`/`tp` arrivent du radar en prix ABSOLUS, calcules sur le prix du
    SIGNAL. Entre le signal et l'execution le marche bouge : poser les stops
    au prix du signal deforme le rapport risque/gain reel — mesure 0,7-1,3 au
    lieu de 1,8 sur ETH/USD le 2026-05-18. Le correctif existait cote MT5
    depuis cette date via `sl_dist`/`tp_dist` ; il manquait ici, alors que
    `avg_price` etait deja calcule dans `place_order` et seulement renvoye.

    Repli volontaire sur les prix du signal — comportement historique — dans
    les trois cas ou le recalage ne peut pas etre fait honnetement : aucun
    remplissage connu, distances absentes (radar plus ancien), distances
    illisibles. Une distance nulle ou negative n'est jamais utilisee.

    Fonction pure et extraite pour etre testable : la meme logique noyee dans
    `place_order` n'aurait pu etre verifiee qu'en recopiant sa condition, donc
    en testant sa propre copie. Cf. feedback_source_inspection_tests_weak.
    """
    try:
        avg = float(avg_price)
    except (TypeError, ValueError):
        return sl_signal, tp_signal, "signal"
    if avg <= 0:
        return sl_signal, tp_signal, "signal"

    try:
        sl_d = abs(float(sl_dist)) if sl_dist is not None else 0.0
        tp_d = abs(float(tp_dist)) if tp_dist is not None else 0.0
    except (TypeError, ValueError):
        return sl_signal, tp_signal, "signal"

    if sl_d <= 0 and tp_d <= 0:
        return sl_signal, tp_signal, "signal"

    # BUY : stop SOUS le fill, objectif AU-DESSUS. SELL : l'inverse.
    sens = 1.0 if str(direction).lower() == "buy" else -1.0
    sl = avg - sens * sl_d if sl_d > 0 else sl_signal
    tp = avg + sens * tp_d if tp_d > 0 else tp_signal
    return sl, tp, "fill"


@app.route("/order", methods=["POST"])
@require_bridge_key
def place_order():
    """Place un ordre MARKET + optionnellement SL/TP (via 2 ordres separes reduceOnly).

    Payload JSON attendu (miroir binance-bridge) :
    {
      "pair": "BTC/USD",           # scalping-radar pair
      "direction": "buy" | "sell",
      "qty": 0.001,                # base asset quantity (BTC)
      "sl": 60000.0,               # optional SL trigger price
      "tp": 68000.0,               # optional TP trigger price
    }

    Réponse succès :
    {
      "ok": true, "mode": "live", "symbol": "PF_XBTUSD",
      "market_order_id": "...", "avg_price": 63000.0, "volume": 0.001,
      "sl_order_id": "..." | null, "tp_order_id": "..." | null,
    }
    """
    payload = request.get_json(force=True, silent=True) or {}
    pair = payload.get("pair")
    direction = (payload.get("direction") or "").lower()
    qty_raw = payload.get("qty")
    sl_raw = payload.get("sl")
    tp_raw = payload.get("tp")
    # Distances au prix du signal (2026-08-19). Quand elles sont fournies ET
    # qu'un prix de remplissage est connu, les stops sont reposes depuis le
    # fill. Absentes -> comportement historique strictement inchange.
    sl_dist_raw = payload.get("sl_dist")
    tp_dist_raw = payload.get("tp_dist")

    # Validation basique
    if direction not in ("buy", "sell") or qty_raw is None:
        return jsonify({"ok": False, "error": "payload requires pair, direction (buy/sell), qty"}), 400
    sym = _resolve_symbol(pair or "")
    if not sym:
        return jsonify({"ok": False, "error": f"unsupported pair {pair}"}), 400

    # Safety gate #1 : whitelist symbols opt-in strict
    if LIVE_WHITELIST_SYMBOLS and sym not in LIVE_WHITELIST_SYMBOLS:
        return jsonify({
            "ok": False, "blocked": True,
            "reason": f"symbol {sym} not in KRAKEN_LIVE_WHITELIST_SYMBOLS",
        }), 429

    # Safety gate #2 : daily drawdown
    ok, reason = _check_daily_drawdown()
    if not ok:
        return jsonify({"ok": False, "blocked": True, "reason": reason}), 429

    # Safety gate #3 : max positions ouvertes
    try:
        pos_data = _signed_request("GET", "/api/v3/openpositions")
        open_count = len(pos_data.get("openPositions", []) or [])
        if open_count >= MAX_OPEN_POSITIONS:
            return jsonify({
                "ok": False, "blocked": True,
                "reason": f"Max open positions reached: {open_count} >= {MAX_OPEN_POSITIONS}",
            }), 429
    except Exception as e:
        logger.warning(f"max positions check failed: {e}")

    # Safety gate #4 : plafond par le RISQUE ENGAGE (2026-08-29)
    #
    # ⛔ Pose ICI, dans la suite des autres portes, et non chez l'appelant :
    # un garde-fou place hors de l'endroit qui les rassemble echappe a tout ce
    # qui le neutralise. Lecon du 20/08 cote MT5.
    #
    # ⚠️ Sur Kraken le stop est un ORDRE INDEPENDANT, pas un attribut de la
    # position : il faut donc joindre `/openpositions` a `/openorders` pour
    # savoir ce qu'une position risque vraiment.
    if MAX_RISQUE_ENGAGE_PCT > 0:
        try:
            pos_data = _signed_request("GET", "/api/v3/openpositions")
            ord_data = _signed_request("GET", "/api/v3/openorders")
            acc_data = _signed_request("GET", "/api/v3/accounts")
            ouvertes = pos_data.get("openPositions", []) or []
            stops = _stops_par_symbole(ord_data.get("openOrders", []) or [])
            ouvert, non_bornables = _risque_engage_kraken(ouvertes, stops)
            flex = (acc_data.get("accounts", {}) or {}).get("flex", {}) or {}
            equity = float(flex.get("portfolioValue", 0.0) or 0.0)

            # Risque de l'ordre demande : |entree - stop| x quantite. Le prix
            # d'entree est celui du marche a cet instant.
            nouveau = None
            try:
                if sl_raw:
                    # Le prix du marche a cet instant. `_public_get` : pas
                    # besoin de signer pour lire un ticker public.
                    tickers = _public_get("/api/v3/tickers").get("tickers", [])
                    entree = 0.0
                    for t in tickers:
                        if (t.get("symbol") or "").upper() == sym:
                            entree = float(t.get("markPrice") or t.get("last") or 0.0)
                            break
                    if entree > 0:
                        ecart = abs(entree - float(sl_raw))
                        if ecart > 0:
                            nouveau = ecart * abs(float(qty_raw))
            except Exception as e:  # noqa: BLE001
                logger.info(f"risque du nouvel ordre incalculable ({e})")

            if nouveau is None and not non_bornables:
                # Ordre non decrit (pas de stop fourni) : on ne juge que
                # l'existant, comme cote MT5 quand l'appelant ne decrit rien.
                nouveau = 0.0

            ok_risque, motif = _controle_risque_engage_kraken(
                ouvert, non_bornables, nouveau, equity, MAX_RISQUE_ENGAGE_PCT)
            if not ok_risque:
                logger.warning(f"[KRAKEN] ordre refuse — {motif}")
                return jsonify({"ok": False, "blocked": True,
                                "reason": motif}), 429
        except Exception as e:  # noqa: BLE001
            # ⚠️ Porte SECONDAIRE : une lecture ratee ne bloque pas le flux.
            # Le drawdown journalier et le compteur restent en place.
            logger.warning(f"risque engage check failed: {e}")

    # Get specs pour valider tickSize et size min
    specs = _get_specs(sym)
    if not specs:
        return jsonify({"ok": False, "error": f"no specs for {sym}"}), 503

    try:
        qty = float(qty_raw)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": f"invalid qty {qty_raw}"}), 400

    # ── Arrondi de la taille à la précision de l'instrument ──
    # Kraken refuse toute taille hors précision avec `invalidSize`, sans dire
    # laquelle est attendue. Le 2026-08-04, `qty=0.005744444…` a fait échouer
    # cinq ordres d'affilée avant que la cause soit identifiée.
    #
    # On tronque vers le bas : arrondir au supérieur augmenterait le risque
    # au-delà de ce que le sizing a calculé.
    qty_precision = int(specs.get("qtyPrecision", 4))
    step = 10.0 ** -qty_precision
    qty_arrondi = round_qty_to_precision(qty, qty_precision)
    if qty_arrondi <= 0:
        # Sous le pas minimum : le compte est trop petit pour cet instrument
        # au risque demandé. Le dire explicitement plutôt que laisser Kraken
        # répondre `invalidSize`, qui ne distingue pas ce cas d'une erreur.
        return jsonify({
            "ok": False,
            "error": (
                f"size below minimum step: qty={qty:.10f} < {step} "
                f"({sym}, {qty_precision} decimals)"
            ),
            "qty_requested": qty,
            "min_step": step,
        }), 400
    if qty_arrondi != qty:
        logger.info(
            f"{sym}: qty {qty:.10f} -> {qty_arrondi} ({qty_precision} decimales)"
        )
    qty = qty_arrondi

    # ── Place market order ──
    market_params = {
        "orderType": "mkt",
        "symbol": sym,
        "side": direction,
        "size": qty,
    }
    try:
        market_resp = _signed_request("POST", "/api/v3/sendorder", market_params)
    except Exception as e:
        logger.exception("market order failed")
        return jsonify({"ok": False, "error": str(e), "step": "market_order"}), 500

    market_send_status = market_resp.get("sendStatus", {}) or {}
    market_order_id = market_send_status.get("order_id") or market_send_status.get("orderId")
    market_status = market_send_status.get("status", "unknown")

    if market_status not in ("placed", "partiallyFilled", "filled"):
        return jsonify({
            "ok": False,
            "error": f"market order rejected: status={market_status}",
            "raw": market_resp,
        }), 500

    # Extract avg price from fills if available
    fills = market_send_status.get("orderEvents", []) or []
    avg_price = 0.0
    total_filled_qty = 0.0
    total_notional = 0.0
    for f in fills:
        if f.get("type") == "EXECUTION":
            fill_qty = float(f.get("amount", 0.0))
            fill_price = float(f.get("price", 0.0))
            total_filled_qty += fill_qty
            total_notional += fill_qty * fill_price
    if total_filled_qty > 0:
        avg_price = total_notional / total_filled_qty

    sl_raw, tp_raw, stops_source = stops_depuis_fill(
        direction, avg_price, sl_dist_raw, tp_dist_raw, sl_raw, tp_raw
    )
    if stops_source == "fill":
        logger.info(f"{sym}: stops recales sur le fill {avg_price}")

    # Round SL/TP to instrument tickSize (Kraken rejects off-tick prices with invalidPrice)
    tick = float(specs.get("tickSize", 0.01))

    def _round_to_tick(p: float) -> float:
        return round(round(p / tick) * tick, 8)

    # ── Place SL order (optional, reduceOnly) ──
    sl_order_id = None
    sl_error = None
    # ⛔ Trois etats, jamais deux : None = pas demande, True = confirme pose,
    # False = demande et RATE. Replier « pas demande » sur False rendrait
    # `protected` illisible ; les confondre est ce qui a laisse une position
    # nue passer pour saine le 2026-08-05.
    sl_applied = None
    if sl_raw is not None:
        try:
            sl_price = _round_to_tick(float(sl_raw))
            sl_side = "sell" if direction == "buy" else "buy"
            sl_params = {
                "orderType": "stp",           # stop order
                "symbol": sym,
                "side": sl_side,
                "size": qty,
                "stopPrice": sl_price,
                "triggerSignal": "mark",      # trigger on mark price (plus stable que last)
                "reduceOnly": "true",
            }
            sl_resp = _signed_request("POST", "/api/v3/sendorder", sl_params)
            sl_status = (sl_resp.get("sendStatus", {}) or {})
            sl_order_id = sl_status.get("order_id") or sl_status.get("orderId")
            if sl_resp.get("result") == "success" and sl_status.get("status") == "placed":
                sl_applied = True
            else:
                sl_applied = False
                sl_error = (f"SL status={sl_status.get('status')}"
                            if sl_status else str(sl_resp.get("error") or "refuse"))
        except Exception as e:
            sl_applied = False
            sl_error = str(e)
            logger.warning(f"SL order failed for {sym}: {e}")

    # ── Place TP order (optional, reduceOnly) ──
    tp_order_id = None
    tp_error = None
    tp_applied = None
    if tp_raw is not None:
        try:
            tp_price = _round_to_tick(float(tp_raw))
            tp_side = "sell" if direction == "buy" else "buy"
            tp_params = {
                "orderType": "take_profit",
                "symbol": sym,
                "side": tp_side,
                "size": qty,
                "stopPrice": tp_price,
                "triggerSignal": "mark",
                "reduceOnly": "true",
            }
            tp_resp = _signed_request("POST", "/api/v3/sendorder", tp_params)
            tp_status = (tp_resp.get("sendStatus", {}) or {})
            tp_order_id = tp_status.get("order_id") or tp_status.get("orderId")
            if tp_resp.get("result") == "success" and tp_status.get("status") == "placed":
                tp_applied = True
            else:
                tp_applied = False
                tp_error = (f"TP status={tp_status.get('status')}"
                            if tp_status else str(tp_resp.get("error") or "refuse"))
        except Exception as e:
            tp_applied = False
            tp_error = str(e)
            logger.warning(f"TP order failed for {sym}: {e}")

    return jsonify({
        "ok": True,
        "mode": "live",
        "symbol": sym,
        "pair": pair,
        "direction": direction,
        "volume": qty,
        "market_order_id": market_order_id,
        "avg_price": avg_price,
        "sl_order_id": sl_order_id,
        "sl_error": sl_error,
        "tp_order_id": tp_order_id,
        "tp_error": tp_error,
        # ⛔ Contrat identique au bridge MT5 depuis le 2026-08-06. `ok` reste
        # True : l'ordre de MARCHE est bien parti, et le faire passer pour un
        # echec ferait retenter l'appelant — donc ouvrir une SECONDE position
        # par-dessus la premiere. Ce qui rate ici, c'est la protection, pas
        # l'ordre, et les deux ne se disent pas avec le meme mot.
        "sl_applied": sl_applied,
        "tp_applied": tp_applied,
        # ⚠️ `protected` ne parle QUE du stop. Un objectif manquant coute du
        # gain, pas de la protection : les confondre banaliserait l'alerte.
        "protected": sl_applied is True,
        # Niveaux réellement posés, après arrondi au tickSize. La réponse ne
        # portait que les identifiants d'ordre : le radar ne savait donc pas à
        # quels prix ses stops avaient été placés, et `personal_trades` ne
        # pouvait pas être renseignée à la réconciliation.
        "sl": _round_to_tick(float(sl_raw)) if sl_raw is not None else None,
        "tp": _round_to_tick(float(tp_raw)) if tp_raw is not None else None,
        # "fill" = stops reposes depuis le prix de remplissage ; "signal" =
        # repli sur les prix du signal. Permet de verifier sans deviner que le
        # recalage a bien eu lieu.
        "stops_source": stops_source,
    })


@app.route("/position/sltp", methods=["POST"])
@require_bridge_key
def position_sltp():
    """Repose ou deplace le stop et/ou l'objectif d'une position vivante.

    Le bridge Kraken n'avait aucune route equivalente a celle du bridge MT5.
    Deux consequences : rien ne pouvait **reparer** une position ouverte sans
    stop — la detection existait (`/openorders` -> `positions_non_protegees`),
    la reparation non — et rien ne pouvait **deplacer** un stop, donc la sortie
    a l'equilibre du 23/08 n'avait aucun bras de ce cote.

    Corps : ``{"symbol": "PF_XBTUSD"}`` ou ``{"pair": "BTC/USD"}``, plus au
    moins un de ``sl`` / ``tp``, et une ``raison`` libre.

    Sur Kraken le stop n'est pas un attribut de la position, c'est un ordre
    independant. « Deplacer un stop » veut donc dire en poser un neuf et
    annuler l'ancien — et l'ORDRE de ces deux gestes decide si la position
    passe, ou non, par un instant sans protection.

    On pose d'abord, on annule ensuite. Deux stops coexistent une fraction de
    seconde : le premier declenche ferme la position, le second devient sans
    objet — il est `reduceOnly`, il ne peut rien ouvrir. L'ordre inverse
    ouvrirait une fenetre nue, exactement le defaut corrige dans `/kill`. Si la
    pose echoue, l'ancien est CONSERVE.

    La taille vient du COURTIER : un stop plus petit que la position en
    laisserait une part nue. Position introuvable => 404.
    """
    corps = request.get_json(silent=True) or {}
    raison = str(corps.get("raison") or corps.get("reason") or "non precisee")

    symbole = corps.get("symbol")
    if not symbole and corps.get("pair"):
        symbole = _resolve_symbol(str(corps["pair"]))
        if not symbole:
            return jsonify({"ok": False, "error": "unsupported pair " + str(corps["pair"]),
                            "raison": raison}), 400
    if not symbole:
        return jsonify({"ok": False, "error": "symbol ou pair requis",
                        "raison": raison}), 400
    symbole = str(symbole)

    sl_raw = corps.get("sl")
    tp_raw = corps.get("tp")
    if sl_raw is None and tp_raw is None:
        return jsonify({"ok": False, "error": "sl ou tp requis", "symbol": symbole,
                        "raison": raison}), 400

    try:
        pos_data = _signed_request("GET", "/api/v3/openpositions")
        if pos_data.get("result") != "success":
            return jsonify({"ok": False, "error": "positions illisibles",
                            "raison": raison}), 503
        cible = None
        for p in pos_data.get("openPositions", []) or []:
            if p.get("symbol") == symbole:
                cible = p
                break
        if cible is None:
            logger.info("position/sltp : %s introuvable (raison=%s)", symbole, raison)
            return jsonify({"ok": False, "error": "position introuvable",
                            "symbol": symbole, "raison": raison}), 404

        taille = abs(float(cible.get("size") or 0.0))
        if taille <= 0:
            return jsonify({"ok": False, "error": "taille nulle chez le courtier",
                            "symbol": symbole, "raison": raison}), 404
        long = str(cible.get("side") or "").lower().startswith("l")
        sens_protection = "sell" if long else "buy"

        specs = _get_specs(symbole) or {}
        tick = float(specs.get("tickSize", 0.01) or 0.01)

        def _au_tick(x):
            return round(round(float(x) / tick) * tick, 8)

        # Les ordres vivants du symbole, lus AVANT de poser : ce sont eux qu'on
        # remplacera, et seulement ceux qui PROTEGENT.
        anciens = []
        try:
            od = _signed_request("GET", "/api/v3/openorders")
            anciens = [o for o in (od.get("openOrders", []) or [])
                       if o.get("symbol") == symbole and o.get("reduceOnly")]
        except Exception as e:  # noqa: BLE001
            logger.warning("position/sltp : ordres illisibles pour %s : %s", symbole, e)

        def _est_stop(o):
            t = str(o.get("orderType") or "").lower()
            return t == "stp" or ("stop" in t and "profit" not in t)

        pose, erreurs, annules = {}, [], []
        for genre, brut, type_kraken in (("sl", sl_raw, "stp"),
                                         ("tp", tp_raw, "take_profit")):
            if brut is None:
                continue
            prix = _au_tick(brut)
            try:
                resp = _signed_request("POST", "/api/v3/sendorder", {
                    "orderType": type_kraken,
                    "symbol": symbole,
                    "side": sens_protection,
                    "size": taille,
                    "stopPrice": prix,
                    "triggerSignal": "mark",
                    "reduceOnly": "true",
                })
                statut = (resp.get("sendStatus") or {}).get("status")
                if resp.get("result") != "success" or statut != "placed":
                    # Pose ratee => on NE TOUCHE PAS a l'ancien ordre. Sans
                    # nouveau stop, l'ancien est la seule protection restante.
                    erreurs.append({genre: statut or resp.get("error")})
                    continue
                pose[genre] = {"prix": prix,
                               "order_id": (resp.get("sendStatus") or {}).get("order_id")}
            except Exception as e:  # noqa: BLE001
                erreurs.append({genre: str(e)})
                logger.warning("position/sltp : pose %s refusee sur %s : %s",
                               genre, symbole, e)
                continue

            # Et seulement MAINTENANT : l'ancien ordre du MEME genre. Poser un
            # stop ne doit pas emporter l'objectif, ni l'inverse.
            for o in anciens:
                meme_genre = _est_stop(o) if genre == "sl" else not _est_stop(o)
                if not meme_genre:
                    continue
                oid = o.get("order_id") or o.get("orderId")
                if not oid or oid == pose[genre]["order_id"]:
                    continue
                try:
                    _signed_request("POST", "/api/v3/cancelorder", {"order_id": oid})
                    annules.append(oid)
                except Exception as e:  # noqa: BLE001
                    # Un ancien stop qui survit fait double emploi, il ne
                    # decouvre rien : c'est le sens sur lequel se tromper.
                    logger.warning("position/sltp : ancien ordre %s non annule : %s",
                                   oid, e)

        ok = bool(pose) and not erreurs
        logger.info("position/sltp : %s pose=%s annules=%d erreurs=%s (raison=%s)",
                    symbole, list(pose), len(annules), erreurs, raison)
        return jsonify({
            "ok": ok,
            "symbol": symbole,
            "size": taille,
            "raison": raison,
            "pose": pose,
            "ordres_annules": annules,
            "erreurs": erreurs,
        }), (200 if ok else 502)
    except Exception as e:
        logger.exception("position/sltp failed")
        return jsonify({"ok": False, "error": str(e), "symbol": symbole,
                        "raison": raison}), 500


@app.route("/position/close", methods=["POST"])
@require_bridge_key
def position_close():
    """Ferme UNE position, et elle seule.

    ⛔ Avant le 05/09, ce bridge ne savait fermer que `/kill` : annuler tous les
    ordres et solder tout le compte. Fermer une ligne obligeait a fermer les
    autres. **Un interrupteur general n'est pas un outil de precision.**
    Meme route que celle posee sur les deux bridges MT5 le 28/08, jamais
    propagee ici — un correctif ne se propage pas seul aux routes jumelles.

    Corps : ``{"symbol": "PF_XLMUSD"}`` ou ``{"pair": "XLM/USD"}``, plus une
    ``raison`` libre qui suit la fermeture jusqu'au journal — c'est elle qui
    distinguera plus tard une fermeture automatique d'une fermeture a la main.

    ⛔ **La position est cherchee CHEZ LE COURTIER, et sa taille vient de lui.**
    Une taille fournie par l'appelant peut sur-fermer — donc RETOURNER la
    position — ou sous-fermer en silence. `reduceOnly` borne le degat, il ne
    l'evite pas. Symbole introuvable ⇒ **404**, jamais « ferme ce qui y
    ressemble ».

    ⛔ **Le stop est un ordre independant sur Kraken.** Fermer la position le
    laisse vivant, et `/openorders` annoncerait une protection pour une
    position qui n'existe plus. On annule donc les ordres `reduceOnly` du
    symbole — **APRES** la fermeture, jamais avant : si la fermeture echoue et
    que le stop est deja annule, la position reste ouverte et NUE. Ce serait
    l'incident du 2026-08-05 provoque par son propre remede.
    """
    corps = request.get_json(silent=True) or {}
    raison = str(corps.get("raison") or corps.get("reason") or "non precisee")

    symbole = corps.get("symbol")
    if not symbole and corps.get("pair"):
        symbole = _resolve_symbol(str(corps["pair"]))
        if not symbole:
            return jsonify({"ok": False, "error": "unsupported pair " + str(corps["pair"]),
                            "raison": raison}), 400
    if not symbole:
        return jsonify({"ok": False, "error": "symbol ou pair requis",
                        "raison": raison}), 400
    symbole = str(symbole)

    try:
        pos_data = _signed_request("GET", "/api/v3/openpositions")
        if pos_data.get("result") != "success":
            return jsonify({"ok": False, "error": "kraken response not success",
                            "raison": raison}), 503

        cible = None
        for p in pos_data.get("openPositions", []) or []:
            if p.get("symbol") == symbole:
                cible = p
                break
        if cible is None:
            logger.info("position/close : %s introuvable chez le courtier (raison=%s)",
                        symbole, raison)
            return jsonify({"ok": False, "error": "position introuvable",
                            "symbol": symbole, "raison": raison}), 404

        taille = abs(float(cible.get("size") or 0.0))
        if taille <= 0:
            return jsonify({"ok": False, "error": "taille nulle chez le courtier",
                            "symbol": symbole, "raison": raison}), 404
        sens_fermeture = "sell" if str(cible.get("side", "")).lower() == "long" else "buy"

        envoi = _signed_request("POST", "/api/v3/sendorder", {
            "orderType": "mkt",
            "symbol": symbole,
            "side": sens_fermeture,
            "size": taille,
            "reduceOnly": "true",
        })
        statut = (envoi.get("sendStatus") or {}).get("status")
        if envoi.get("result") != "success" or statut not in ("placed", "filled",
                                                              "partiallyFilled"):
            logger.error("position/close : fermeture REFUSEE pour %s (raison=%s) : %s",
                         symbole, raison, envoi)
            # ⛔ On ne touche a AUCUN ordre : la position reste ouverte, donc
            # elle doit rester protegee.
            return jsonify({"ok": False, "error": "fermeture refusee par le courtier",
                            "symbol": symbole, "raison": raison, "raw": envoi}), 502

        # La position est fermee : ses ordres conditionnels n'ont plus d'objet.
        annules, echecs = [], []
        try:
            ord_data = _signed_request("GET", "/api/v3/openorders")
            for o in (ord_data.get("openOrders", []) or []):
                if o.get("symbol") != symbole or not o.get("reduceOnly"):
                    continue
                oid = o.get("order_id") or o.get("orderId")
                if not oid:
                    continue
                try:
                    _signed_request("POST", "/api/v3/cancelorder", {"order_id": oid})
                    annules.append(oid)
                except Exception as e:  # noqa: BLE001
                    echecs.append({"order_id": oid, "erreur": str(e)})
        except Exception as e:  # noqa: BLE001
            # ⚠️ Un orphelin qui subsiste est un defaut de proprete, pas un
            # risque : il est `reduceOnly`, il ne peut RIEN ouvrir. La
            # fermeture, elle, a bien eu lieu — on ne la declare pas ratee.
            echecs.append({"order_id": None, "erreur": str(e)})
            logger.warning("position/close : ordres orphelins sur %s : %s", symbole, e)

        logger.info("position/close : %s ferme %s @ mkt (raison=%s), %d ordre(s) annule(s)",
                    symbole, taille, raison, len(annules))
        return jsonify({
            "ok": True,
            "symbol": symbole,
            "side_ferme": str(cible.get("side")),
            "size": taille,
            "raison": raison,
            "order_id": (envoi.get("sendStatus") or {}).get("order_id"),
            "ordres_annules": annules,
            "ordres_non_annules": echecs,
        })
    except Exception as e:
        logger.exception("position/close failed")
        return jsonify({"ok": False, "error": str(e), "symbol": symbole,
                        "raison": raison}), 500


def _annuler_ordres(ordres: list) -> tuple:
    """Annule chaque ordre, un par un. Rend `(annules, echecs)`.

    ⛔ Jamais `cancelallorders` : cette route confond les deux familles
    d'ordres, celle qui OUVRE du risque et celle qui le BORNE. Les annuler
    ensemble, c'est desarmer les stops des positions qu'on n'a pas encore
    reussi a fermer.

    ⛔ L'echec d'une annulation n'interrompt pas les autres : un ordre orphelin
    qui subsiste est un defaut de proprete, pas un risque — il est `reduceOnly`
    ou deja sans objet.
    """
    annules, echecs = [], []
    for o in ordres or []:
        oid = o.get("order_id") or o.get("orderId")
        if not oid:
            continue
        try:
            _signed_request("POST", "/api/v3/cancelorder", {"order_id": oid})
            annules.append(oid)
        except Exception as e:  # noqa: BLE001
            echecs.append({"order_id": oid, "erreur": str(e)})
            logger.warning("kill : annulation refusee pour %s : %s", oid, e)
    return annules, echecs


@app.route("/kill", methods=["POST"])
@require_bridge_key
def kill_all():
    """Kill-switch : annule ce qui peut ouvrir, ferme ce qui est ouvert.

    ⛔ L'ancienne version appelait `cancelallorders` **AVANT** de fermer, puis
    rendait `ok: True` sans jamais regarder le resultat des fermetures. Trois
    consequences, toutes dans la seule route qu'on appelle quand ca va deja
    mal :

    1. une fermeture qui echoue laissait la position **ouverte et NUE**, son
       stop venant d'etre annule — l'incident du 2026-08-05 reproduit par le
       remede ;
    2. le kill pouvait annoncer « tout est ferme » alors que rien ne l'etait.
       **Un mecanisme qui ment sur son propre resultat est pire que son
       absence : il fait renoncer a verifier** ;
    3. une exception au milieu de la boucle abandonnait les positions
       suivantes, stops deja annules.

    🔑 L'ordre correct distingue ce que `cancelallorders` confondait :

    - un ordre d'**ENTREE** en attente peut OUVRIR du risque pendant le kill :
      il part **en premier**, c'est le geste meme du kill ;
    - un ordre de **PROTECTION** (`reduceOnly`) borne du risque existant : il
      ne part qu'**APRES** que SA position soit effectivement fermee.

    Une position dont la fermeture echoue **garde son stop**, et le kill le dit
    en rendant `ok: False` avec la liste de ce qui reste ouvert.
    """
    try:
        ordres = []
        try:
            od = _signed_request("GET", "/api/v3/openorders")
            ordres = od.get("openOrders", []) or []
        except Exception as e:  # noqa: BLE001
            logger.warning("kill : ordres illisibles, on ferme quand meme : %s", e)

        # 1. Ce qui peut OUVRIR du risque part tout de suite.
        entrees = [o for o in ordres if not o.get("reduceOnly")]
        entrees_annulees, entrees_echecs = _annuler_ordres(entrees)

        # 2. Chaque position est TENTEE, quoi qu'il arrive aux autres.
        pos_data = _signed_request("GET", "/api/v3/openpositions")
        if pos_data.get("result") != "success":
            return jsonify({"ok": False, "error": "positions illisibles",
                            "entrees_annulees": entrees_annulees}), 503

        fermees, non_fermees = [], []
        for p in pos_data.get("openPositions", []) or []:
            sym = p.get("symbol")
            try:
                taille = abs(float(p.get("size") or 0.0))
                if taille <= 0:
                    continue
                sens = "sell" if str(p.get("side", "")).lower().startswith("l") else "buy"
                resp = _signed_request("POST", "/api/v3/sendorder", {
                    "orderType": "mkt",
                    "symbol": sym,
                    "side": sens,
                    "size": taille,
                    "reduceOnly": "true",
                })
                statut = (resp.get("sendStatus") or {}).get("status")
                if resp.get("result") == "success" and statut in ("placed", "filled",
                                                                  "partiallyFilled"):
                    fermees.append(sym)
                else:
                    non_fermees.append({"symbol": sym, "raison": statut or resp.get("error")})
                    logger.error("kill : fermeture REFUSEE pour %s : %s", sym, resp)
            except Exception as e:  # noqa: BLE001
                # ⛔ Une position qui leve ne doit pas priver les SUIVANTES de
                # leur tentative de fermeture.
                non_fermees.append({"symbol": sym, "raison": str(e)})
                logger.exception("kill : fermeture impossible pour %s", sym)

        # 3. Seuls les stops des positions REELLEMENT fermees sont annules.
        protections = [o for o in ordres
                       if o.get("reduceOnly") and o.get("symbol") in set(fermees)]
        stops_annules, stops_echecs = _annuler_ordres(protections)

        tout_ferme = not non_fermees
        corps = {
            "ok": tout_ferme,
            "fermees": fermees,
            "non_fermees": non_fermees,
            "entrees_annulees": entrees_annulees,
            "protections_annulees": stops_annules,
            "annulations_ratees": entrees_echecs + stops_echecs,
        }
        if not tout_ferme:
            logger.error("kill : %d position(s) restent OUVERTES : %s",
                         len(non_fermees), non_fermees)
        return jsonify(corps), (200 if tout_ferme else 502)
    except Exception as e:
        logger.exception("kill_all failed")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─── Boot ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info(f"kraken-bridge starting port={BRIDGE_PORT} base={BASE_URL}")
    logger.info(f"  MAX_DAILY_LOSS_PCT       : {MAX_DAILY_LOSS_PCT}%")
    logger.info(f"  LIVE_WHITELIST_SYMBOLS   : {sorted(LIVE_WHITELIST_SYMBOLS) if LIVE_WHITELIST_SYMBOLS else 'ALL ALLOWED'}")
    logger.info(f"  MAX_OPEN_POSITIONS       : {MAX_OPEN_POSITIONS}")
    logger.info(f"  Supported pairs          : {len(_PAIR_TO_SYMBOL)}")
    try:
        _refresh_specs_cache()
    except Exception as e:
        logger.warning(f"initial specs cache refresh failed: {e}")
    app.run(host="0.0.0.0", port=BRIDGE_PORT, threaded=True)
