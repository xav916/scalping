"""Bot Telegram pour pousser les signaux de scalping sur votre telephone.

Configuration :
- Creer un bot via @BotFather sur Telegram, recuperer le token
- Envoyer un message au bot depuis votre compte Telegram
- Recuperer votre chat_id via https://api.telegram.org/bot<TOKEN>/getUpdates
- Renseigner TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID dans .env

Le bot envoie uniquement les signaux "strong" par defaut (configurable).
"""

import asyncio
import logging

import httpx

from backend.models.schemas import ScalpingSignal
from backend.services import trade_log_service
from backend.services.shadow_v2_core_long import SHADOW_PAIRS as _STAR_PAIRS
from datetime import date

from config.settings import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TELEGRAM_CHATS,
    TELEGRAM_MIN_STRENGTH,
    TELEGRAM_SETUP_MIN_CONFIDENCE,
    TELEGRAM_SETUP_VERDICTS,
)

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

_strength_order = {"weak": 0, "moderate": 1, "strong": 2}

# Filtre paires : on ne pousse Telegram QUE pour les "stars" du portefeuille
# Phase 4 (XAU/XAG/WTI/ETH/XLI/XLK). Évite la pollution par les setups des
# 12 autres paires WATCHED_PAIRS (forex/SPX/NDX/BTC) sans edge confirmé.
_STAR_PAIRS_SET: frozenset[str] = frozenset(_STAR_PAIRS)


def _should_send(signal: ScalpingSignal) -> bool:
    if signal.pair not in _STAR_PAIRS_SET:
        return False
    min_rank = _strength_order.get(TELEGRAM_MIN_STRENGTH.lower(), 2)
    sig_rank = _strength_order.get(signal.signal_strength.value.lower(), 0)
    return sig_rank >= min_rank


def is_configured() -> bool:
    """True si au moins un destinataire est configure."""
    return bool(TELEGRAM_BOT_TOKEN and (TELEGRAM_CHATS or TELEGRAM_CHAT_ID))


def _destinataires() -> list[tuple[str, str]]:
    """Retourne la liste (user, chat_id) a qui envoyer (config env legacy).

    Si TELEGRAM_CHATS est defini : un (user, chat_id) par user configure.
    Sinon fallback sur TELEGRAM_CHAT_ID (broadcast a 1 destinataire anonymous).
    """
    if TELEGRAM_CHATS:
        return list(TELEGRAM_CHATS.items())
    if TELEGRAM_CHAT_ID:
        return [("__any__", TELEGRAM_CHAT_ID)]
    return []


def _per_user_chat_ids_for_setup(setup) -> list[tuple[str, str]]:
    """Liste des (email, chat_id) des users DB qui doivent recevoir ce setup.

    Filtre par les prefs personnelles du user :
    - watched_pairs : le pair du setup doit y être
    - min_confidence : confidence_score doit ≥ seuil
    Chantier 2026-06-14 : feature notifs perso par client.
    """
    try:
        from backend.services import users_service
        candidates = users_service.list_users_with_telegram()
    except Exception as e:
        logger.warning(f"_per_user_chat_ids_for_setup: list users failed: {e}")
        return []
    pair = getattr(setup, "pair", None)
    conf = getattr(setup, "confidence_score", None) or 0.0
    out = []
    for u in candidates:
        if pair and pair not in u.get("watched_pairs", []):
            continue
        if conf < u.get("min_confidence", 70.0):
            continue
        out.append((u["email"], u["chat_id"]))
    return out


async def send_test_to_chat_id(chat_id: str, display_name: str) -> tuple[bool, str]:
    """Envoie un message test à un chat_id pour valider la liaison Telegram.

    Utilisé par l'endpoint POST /api/user/telegram/link au moment où le user
    clique "Connecter". Retourne (True, "") si OK, (False, err_msg) si échec.
    """
    if not (TELEGRAM_BOT_TOKEN and chat_id):
        return False, "Telegram bot non configuré côté serveur"
    msg = (
        f"✅ *Connexion réussie !*\n\n"
        f"Tu es maintenant connecté à Scalping Radar en tant que *{display_name}*.\n\n"
        f"Tu recevras ici tes signaux personnalisés selon tes paires sélectionnées "
        f"et ton niveau de confiance choisis dans /v2/settings.\n\n"
        f"Pour te déconnecter à tout moment : /v2/settings → section Telegram → Déconnecter."
    )
    url = TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json={
                "chat_id": chat_id,
                "text": msg,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            })
            if r.status_code == 200:
                return True, ""
            # Parser le message d'erreur Telegram pour aider le user
            try:
                err_json = r.json()
                err_desc = err_json.get("description", r.text[:200])
            except Exception:
                err_desc = r.text[:200]
            return False, f"Telegram a refusé : {err_desc}"
    except Exception as e:
        return False, f"Erreur réseau : {e}"


def _format_signal(signal: ScalpingSignal) -> str:
    emoji = {"strong": "🔥", "moderate": "⚡", "weak": "💡"}.get(signal.signal_strength.value, "📊")
    lines = [
        f"{emoji} *Signal {signal.signal_strength.value.upper()}* — `{signal.pair}`",
    ]

    # Verdict en premier (pour que le user voie immediatement la reco)
    if signal.trade_setup and signal.trade_setup.verdict_action:
        s = signal.trade_setup
        verdict_icon = {"TAKE": "✅", "WAIT": "⏳", "SKIP": "⛔"}.get(s.verdict_action, "")
        lines.append(f"\n{verdict_icon} *{s.verdict_action}* — {s.verdict_summary}")

    lines.extend([
        f"\nTendance : {signal.trend.direction.value} ({int(signal.trend.strength * 100)}%)",
        f"Volatilite : {signal.volatility.level.value} ({signal.volatility.volatility_ratio:.1f}x)",
    ])

    if signal.trade_setup:
        s = signal.trade_setup
        dir_label = "ACHAT 🟢" if s.direction.value == "buy" else "VENTE 🔴"
        lines.extend([
            "",
            f"*{dir_label}*",
            f"Entry : `{s.entry_price:.4f}`",
            f"SL : `{s.stop_loss:.4f}` ({s.risk_pips:.1f} pips risque)",
            f"TP1 : `{s.take_profit_1:.4f}` (R:R {s.risk_reward_1:.1f})",
            f"TP2 : `{s.take_profit_2:.4f}` (R:R {s.risk_reward_2:.1f})",
        ])
        # Raisons & warnings si presents
        if s.verdict_reasons:
            lines.append("\n👍 " + " | ".join(s.verdict_reasons[:3]))
        if s.verdict_warnings:
            lines.append("⚠️ " + " | ".join(s.verdict_warnings[:3]))
    if signal.confidence_score:
        lines.append(f"\nConfiance : *{signal.confidence_score:.0f}/100*")
    return "\n".join(lines)


async def _send_to(chat_id: str, signal: ScalpingSignal, who: str) -> None:
    """Envoi effectif vers un chat_id precis."""
    url = TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": chat_id,
        "text": _format_signal(signal),
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code != 200:
                logger.warning(f"Telegram erreur {response.status_code} pour {who}: {response.text[:200]}")
            else:
                logger.info(f"Signal Telegram envoye a {who} pour {signal.pair} ({signal.signal_strength.value})")
    except Exception as e:
        logger.warning(f"Erreur envoi Telegram {who}: {e}")


async def send_text(text: str, parse_mode: str = "Markdown") -> None:
    """Envoie un texte libre a tous les destinataires (alertes systeme)."""
    if not is_configured():
        return
    destinataires = _destinataires()
    if not destinataires:
        return
    url = TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN)
    for user, chat_id in destinataires:
        if user != "__any__" and trade_log_service.silent_mode_active_for_user(user):
            continue
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(url, json={
                    "chat_id": chat_id, "text": text, "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                })
        except Exception as e:
            logger.warning(f"Erreur Telegram text {user}: {e}")


async def send_infra_text(text: str, parse_mode: str = "HTML") -> bool:
    """Envoie un texte vers le canal infra dédié (@xav_scalping_infra_bot).

    Sépare les alertes système (rafales rejections, monitoring infra,
    routine alerts) du canal user-facing qui est réservé aux signaux de
    trading. Lit INFRA_TELEGRAM_BOT_TOKEN + INFRA_TELEGRAM_CHAT_ID depuis
    config.settings — si non configuré, no-op silencieux + log.

    parse_mode HTML par défaut depuis 2026-05-13 : Markdown legacy Telegram
    cassait dès qu'un message contenait un underscore non échappé (ex:
    reason_code "MIN_RR_BELOW_THRESHOLD" → 88 HTTP 400 sur 96h observés).
    HTML est plus strict côté tags mais ignore complètement les caractères
    _ * ` [ qui sont littéraux. Tout caller passant parse_mode="Markdown"
    bascule silencieusement en plain (pas de parse_mode) pour éviter la
    régression — il faut passer explicitement "HTML" pour formater.

    Retourne True si envoyé, False sinon.
    """
    from config.settings import INFRA_TELEGRAM_BOT_TOKEN, INFRA_TELEGRAM_CHAT_ID
    if not INFRA_TELEGRAM_BOT_TOKEN or not INFRA_TELEGRAM_CHAT_ID:
        logger.info("send_infra_text: INFRA_TELEGRAM_* non configure, skip")
        return False
    url = TELEGRAM_API.format(token=INFRA_TELEGRAM_BOT_TOKEN)
    payload: dict = {
        "chat_id": INFRA_TELEGRAM_CHAT_ID,
        "text": text[:4000],
        "disable_web_page_preview": True,
    }
    if parse_mode == "HTML":
        payload["parse_mode"] = "HTML"
    elif parse_mode == "Markdown" or parse_mode == "MarkdownV2":
        # Legacy callers — on les laisse passer mais sans parse_mode pour
        # éviter de re-déclencher le bug d'underscore. Le contenu sera
        # affiché en clair (les * et _ resteront visibles).
        logger.info(
            "send_infra_text: parse_mode=%s deprecated, envoi en plain text",
            parse_mode,
        )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=payload)
        if r.status_code != 200:
            logger.warning(f"send_infra_text: HTTP {r.status_code} {r.text[:200]}")
            return False
        return True
    except Exception as e:
        logger.warning(f"send_infra_text: erreur {e}")
        return False


async def send_sales_text(text: str, parse_mode: str = "HTML") -> bool:
    """Envoie un texte vers le canal business/sales dédié.

    Sépare les notifs commerciales (nouveau client payant, upgrade, churn)
    du bruit infra et des signaux user. Lit SALES_TELEGRAM_BOT_TOKEN +
    SALES_TELEGRAM_CHAT_ID — si non configuré, no-op silencieux. Même
    contrat que send_infra_text (HTML par défaut, fallback plain pour
    Markdown legacy).

    Retourne True si envoyé, False sinon.
    """
    from config.settings import SALES_TELEGRAM_BOT_TOKEN, SALES_TELEGRAM_CHAT_ID
    if not SALES_TELEGRAM_BOT_TOKEN or not SALES_TELEGRAM_CHAT_ID:
        logger.info("send_sales_text: SALES_TELEGRAM_* non configure, skip")
        return False
    url = TELEGRAM_API.format(token=SALES_TELEGRAM_BOT_TOKEN)
    payload: dict = {
        "chat_id": SALES_TELEGRAM_CHAT_ID,
        "text": text[:4000],
        "disable_web_page_preview": True,
    }
    if parse_mode == "HTML":
        payload["parse_mode"] = "HTML"
    elif parse_mode == "Markdown" or parse_mode == "MarkdownV2":
        logger.info(
            "send_sales_text: parse_mode=%s deprecated, envoi en plain text",
            parse_mode,
        )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=payload)
        if r.status_code != 200:
            logger.warning(f"send_sales_text: HTTP {r.status_code} {r.text[:200]}")
            return False
        return True
    except Exception as e:
        logger.warning(f"send_sales_text: erreur {e}")
        return False


async def send_signal(signal: ScalpingSignal) -> None:
    """DEPRECIE — le path "signal-based" Telegram pollue le canal :
    il filtre uniquement par signal_strength (weak/moderate/strong) sans
    vérifier le confidence_score, ce qui produit des messages STRONG à
    51/100 que le bridge n'exécute jamais (seuil bridge = 65). Le path
    `send_setup` (setup-based) gère correctement le filtrage par score
    + verdict + dedup. Ce path reste comme no-op pour ne pas casser les
    appels existants depuis le scheduler.
    """
    return  # no-op — voir send_setup()


async def send_signals(signals: list[ScalpingSignal]) -> None:
    """Envoie plusieurs signaux en parallele."""
    if not is_configured() or not signals:
        return
    await asyncio.gather(*(send_signal(s) for s in signals), return_exceptions=True)


# ─── Trade setups (potentiels) — chemin distinct des signaux ────────────────
#
# Motivation : un "signal" ne part sur Telegram qu'à partir de strength=strong
# par défaut. Les setups haute confiance avec verdict TAKE méritent d'être
# poussés même sans signal "strong" formel. Sinon le user ne voit les
# opportunités que dans l'UI web.
#
# Dedup : on ne re-pousse pas le même (pair, direction, entry arrondi) dans
# la journée. Reset à minuit (clé date incluse dans le set).

_sent_setups_today: set[tuple[str, str, str, str]] = set()


def _setup_dedup_key(setup) -> tuple[str, str, str, str]:
    """Clé de dédup stable : (date_iso, pair, direction, entry arrondi)."""
    # entry arrondi à 5 décimales pour tolérer des micro-variations entre cycles.
    entry_rounded = f"{setup.entry_price:.5f}"
    return (
        date.today().isoformat(),
        setup.pair,
        setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction),
        entry_rounded,
    )


def _cleanup_old_dedup_keys() -> None:
    """Purge les entrées d'hier. Appelée à chaque push : coût négligeable."""
    today = date.today().isoformat()
    # on crée une nouvelle set avec seulement les entrées du jour
    for key in list(_sent_setups_today):
        if key[0] != today:
            _sent_setups_today.discard(key)


def _should_push_setup(setup) -> bool:
    """Filtre : (pair, direction) éligible Telegram + verdict dans la liste
    autorisée + score au-dessus du seuil.

    Éligibilité Telegram = state in (TELEGRAM, AUTO_EXEC, PAUSED) via
    pair_admission_controller. Fallback sur _STAR_PAIRS_SET hardcodé si
    controller indisponible ou si (pair, direction) jamais vue.
    """
    setup_direction = getattr(setup, "direction", None)
    if hasattr(setup_direction, "value"):
        setup_direction = setup_direction.value
    try:
        from backend.services import pair_admission_controller
        if pair_admission_controller.has_explicit_state(setup.pair, setup_direction):
            if not pair_admission_controller.is_telegram_eligible(setup.pair, setup_direction):
                return False
        else:
            if setup.pair not in _STAR_PAIRS_SET:
                return False
    except Exception:
        if setup.pair not in _STAR_PAIRS_SET:
            return False
    if not setup.verdict_action:
        return False
    if setup.verdict_action.upper() not in TELEGRAM_SETUP_VERDICTS:
        return False
    score = getattr(setup, "confidence_score", None) or 0
    if score < TELEGRAM_SETUP_MIN_CONFIDENCE:
        return False
    return True


_PAIR_FR_LABEL: dict[str, str] = {
    "XAU/USD": "Or",
    "XAG/USD": "Argent",
    "WTI/USD": "Pétrole WTI",
    "ETH/USD": "Ethereum",
    "BTC/USD": "Bitcoin",
    # 6 cryptos promues AUTO_EXEC le 2026-06-13 (cf. project_manual_crypto_promotion_2026_06_13)
    # → ajout 2026-06-16 pour uniformiser les notifs Telegram trade_opened / close.
    "SOL/USD": "Solana",
    "ADA/USD": "Cardano",
    "XRP/USD": "Ripple",
    "LTC/USD": "Litecoin",
    "BCH/USD": "Bitcoin Cash",
    "DOT/USD": "Polkadot",
    # Autres paires watched (forex majors + équités) — labels lisibles pour
    # cohérence en cas de push futur.
    "EUR/USD": "Euro / Dollar",
    "GBP/USD": "Livre / Dollar",
    "USD/JPY": "Dollar / Yen",
    "EUR/GBP": "Euro / Livre",
    "USD/CHF": "Dollar / Franc Suisse",
    "AUD/USD": "Dollar Australien",
    "USD/CAD": "Dollar / Dollar Canadien",
    "EUR/JPY": "Euro / Yen",
    "GBP/JPY": "Livre / Yen",
    "SPX": "S&P 500",
    "NDX": "Nasdaq 100",
}

_PATTERN_EXPLAIN_FR: dict[str, str] = {
    "momentum_up": "fort élan haussier — la dernière bougie absorbe la pression vendeuse et accélère vers le haut",
    "momentum_down": "fort élan baissier — la dernière bougie casse la dynamique acheteuse",
    "engulfing_bullish": "bougie englobante haussière — un retournement net après une phase baissière",
    "engulfing_bearish": "bougie englobante baissière — un retournement net après une phase haussière",
    "breakout_up": "cassure de résistance — le prix franchit un plafond technique avec volume",
    "breakout_down": "cassure de support — le prix casse un plancher technique avec volume",
    "range_bounce_up": "rebond sur support — le prix repart d'un plancher dans un range établi",
    "range_bounce_down": "rejet sur résistance — le prix échoue à casser un plafond dans un range",
    "pin_bar_up": "pin bar haussière — rejet visible du bas, signal de retournement court terme",
    "pin_bar_down": "pin bar baissière — rejet visible du haut, signal de retournement court terme",
}


# Labels lisibles pour chaque destination admin connue. Utilisé pour annoter
# le badge "Auto-exécuté" du push Telegram avec les brokers réels touchés.
# Cf. project_live_icmarkets_active_2026_06_12.
_ADMIN_DEST_LABELS = {
    "admin_legacy": "🧪 Demo Pepperstone",
    "admin_live": "💰 Live IC Markets (€300)",
}


# Valeur en EUR par UNITÉ DE PRIX (= la valeur de `risk_pips` dans le système,
# qui est en réalité la distance brute entry−stop, pas des pips au sens classique)
# pour 0.01 lot (volume minimum). Approximations specs broker standards 2026-06
# + EUR/USD ~1.10 + USD/JPY ~150. Utilisé pour estimer risque/gain € user-facing
# dans les messages Telegram. Volatile, approximation.
#
# Pour Demo (max_lot 0.10) : multiplier mentalement par 10.
# Pour Live IC Markets (max_lot 0.02) : multiplier par 2.
#
# Forex : le système stocke risk_pips = abs(entry-stop) arrondi à 2 décimales.
# Pour les majors quote USD (pip = 0.0001), un SL typique de 10-30 pips = 0.001
# à 0.003 → arrondi à 0.00, le champ est inexploitable. On skip forex pour ne
# pas afficher €0.00 trompeur.
_PIP_VALUE_AT_001_LOT_EUR: dict[str, float] = {
    # Metals (1 lot = 100 oz pour XAU, 5000 oz pour XAG)
    "XAU/USD": 0.90,   # 1 unité prix × 100 × 0.01 = $1 ≈ €0.90
    "XAG/USD": 45.0,   # 1 unité prix × 5000 × 0.01 = $50 ≈ €45
    # Energy (1 lot = 1000 barrels)
    "WTI/USD": 9.0,    # 1 unité prix × 1000 × 0.01 = $10 ≈ €9
    # Crypto (1 lot = 1 unité de la crypto ; pip_value uniforme par convention
    # broker = 1 tick × 0.01 lot × $1/unit ≈ €0.009). Ajout 2026-06-16 des 6
    # cryptos promues 13/06 pour uniformiser notifs Telegram trade_opened/close.
    "ETH/USD": 0.009,
    "BTC/USD": 0.009,
    "SOL/USD": 0.009,
    "ADA/USD": 0.009,
    "XRP/USD": 0.009,
    "LTC/USD": 0.009,
    "BCH/USD": 0.009,
    "DOT/USD": 0.009,
    # Forex : NON mappé volontairement (risk_pips arrondi à 0.00 → affichage
    # €0.00 trompeur). À reactiver quand on aura un pipeline qui conserve la
    # précision (e.g. risk_money directement en EUR).
}


# Margin (= "argent engagé" pour ouvrir la position) estimée en EUR par 0.01 lot.
# Approximations basées sur leverages ESMA retail UE (forex 1:30, métaux 1:20,
# énergie 1:10, crypto 1:2) + prix typiques 2026-06 + USD→EUR ~0.90.
# Pour Demo (max_lot 0.10) ≈ ×10. Pour Live (max_lot 0.02) ≈ ×2.
_MARGIN_AT_001_LOT_EUR: dict[str, float] = {
    # Forex majors (1:30 leverage) — 0.01 lot = 1000 base ÷ 30 ≈ €33
    "EUR/USD": 33.0,
    "GBP/USD": 39.0,
    "AUD/USD": 22.0,
    "NZD/USD": 20.0,
    "USD/JPY": 33.0,
    "EUR/JPY": 33.0,
    "GBP/JPY": 38.0,
    # Metals (1:20 leverage)
    "XAU/USD": 190.0,  # 1 oz × $4200 ÷ 20 ≈ $210 ≈ €190
    "XAG/USD": 113.0,  # 50 oz × $50 ÷ 20 ≈ $125 ≈ €113
    # Energy (1:10 leverage)
    "WTI/USD": 67.0,   # 10 barrels × $75 ÷ 10 ≈ $75 ≈ €67
    # Crypto (1:2 leverage retail EU)
    "ETH/USD": 8.0,    # 0.01 ETH × $1700 ÷ 2 ≈ $8.50 ≈ €7.65
    "BTC/USD": 450.0,  # 0.01 BTC × $100000 ÷ 2 ≈ €450 (probable NO_MONEY sur €300 cap)
    # 6 altcoins promues 2026-06-13 (ajout 2026-06-16). Prix ~mi-juin 2026.
    "SOL/USD": 0.30,   # 0.01 × $67 ÷ 2 ≈ €0.30
    "BCH/USD": 1.00,   # 0.01 × $220 ÷ 2 ≈ €1.00
    "LTC/USD": 0.20,   # 0.01 × $45 ÷ 2 ≈ €0.20
    "ADA/USD": 0.01,   # 0.01 × $0.17 ÷ 2 — trop petit pour affichage utile
    "XRP/USD": 0.01,   # 0.01 × $1.14 ÷ 2 — idem
    "DOT/USD": 0.01,   # 0.01 × $1.0 ÷ 2 — idem
}


def _estimate_eur_amounts(setup) -> dict | None:
    """Retourne dict {margin, risk, reward_1, reward_2} en EUR estimé pour 0.01 lot.

    - ``margin`` : "argent engagé" pour ouvrir la position (= notional ÷ leverage).
      None si la pair n'a pas de mapping margin (le bloc est rendu sans cette ligne).
    - ``risk`` / ``reward_*`` : pertes/gains potentiels si SL/TP touchés.

    None retourné globalement si la pair n'a pas de mapping pip_value ou si
    risk_pips manquant. Best-effort, approximation.
    """
    pair = getattr(setup, "pair", "")
    risk_pips = float(getattr(setup, "risk_pips", 0) or 0)
    reward_pips_1 = float(getattr(setup, "reward_pips_1", 0) or 0)
    reward_pips_2 = float(getattr(setup, "reward_pips_2", 0) or 0)
    pip_eur = _PIP_VALUE_AT_001_LOT_EUR.get(pair)
    if not pip_eur or risk_pips <= 0:
        return None
    return {
        "margin": _MARGIN_AT_001_LOT_EUR.get(pair),  # None si non mappé
        "risk": pip_eur * risk_pips,
        "reward_1": pip_eur * reward_pips_1,
        "reward_2": pip_eur * reward_pips_2 if reward_pips_2 > 0 else None,
    }


def _describe_admin_destinations(setup) -> list[str]:
    """Liste les destinations admin qui exécuteront effectivement ce setup.

    Filtre sur ``confidence_score`` et ``asset_class`` pour matcher ce que
    ``mt5_bridge._check_rejection()`` accepterait par destination. Retourne
    une liste de labels lisibles (ex. ["🧪 Demo Pepperstone", "💰 Live IC
    Markets (€100)"]). Les user destinations (Premium EA queue) sont
    exclues — elles ne concernent pas le push Telegram admin.

    Best-effort : exceptions retournent [] pour ne jamais casser le format
    du message Telegram principal.
    """
    try:
        from backend.services import bridge_destinations
        from config.settings import asset_class_for

        from config.settings import MT5_BRIDGE_ALLOWED_PATTERNS
        from backend.services.mt5_bridge import _pattern_value

        score = float(getattr(setup, "confidence_score", 0) or 0)
        pair = getattr(setup, "pair", None)
        if not pair:
            return []
        # Whitelist de patterns (2026-08-04) : elle s'applique à toutes les
        # destinations, donc un setup hors whitelist n'en exécutera aucune.
        # Sans ce test, le message annoncerait « 💰 Live IC Markets » pour un
        # setup que le bridge rejettera — une promesse fausse au lecteur.
        if MT5_BRIDGE_ALLOWED_PATTERNS:
            if _pattern_value(setup) not in MT5_BRIDGE_ALLOWED_PATTERNS:
                return []
        try:
            aclass = asset_class_for(pair)
        except Exception:
            aclass = None

        labels = []
        for dest in bridge_destinations.resolve_destinations(setup):
            if dest.user_id is not None:
                continue  # ignore user destinations (Premium EA queue)
            if not dest.auto_exec_enabled:
                continue
            if score < dest.min_confidence:
                continue
            if aclass and aclass not in dest.allowed_asset_classes:
                continue
            label = _ADMIN_DEST_LABELS.get(dest.destination_id, dest.destination_id)
            labels.append(label)
        return labels
    except Exception:
        return []


def _format_setup(setup) -> str:
    """Format Telegram pédagogique : vulgarise l'analyse pour le user-facing.

    Structure :
    1. Header (pair label FR, direction, score, heure Paris)
    2. Lecture du radar (pattern explained + verdict_summary si dispo)
    3. Plan de trade (entry/SL/TP1/TP2 avec gain/perte concrets)
    4. Comment lire ce R:R (explication chiffrée)
    5. Forces validant le setup (verdict_reasons)
    6. Vigilances (verdict_warnings)
    7. Validité

    Vise les Premium qui veulent comprendre POURQUOI le radar émet, pas
    juste recevoir des chiffres bruts.
    """
    from datetime import datetime, timezone, timedelta

    verdict_icon = {"TAKE": "✅", "WAIT": "⏳", "SKIP": "⛔"}.get(
        setup.verdict_action or "", "📊"
    )
    dir_value = (
        setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction)
    )
    dir_label = "ACHAT 🟢" if dir_value == "buy" else "VENTE 🔴"
    score = getattr(setup, "confidence_score", 0) or 0

    paris_now = datetime.now(timezone.utc) + timedelta(hours=2)
    time_str = paris_now.strftime("%H:%M")

    pair_label = _PAIR_FR_LABEL.get(setup.pair, setup.pair)

    # Pattern explanation
    pattern_obj = getattr(setup, "pattern", None)
    pattern_value = ""
    if pattern_obj is not None:
        ptype = getattr(pattern_obj, "pattern", None)
        pattern_value = ptype.value if hasattr(ptype, "value") else str(ptype or "")
    pattern_explain = _PATTERN_EXPLAIN_FR.get(pattern_value, pattern_value or "signal technique détecté")

    risk = float(getattr(setup, "risk_pips", 0) or 0)
    reward_1 = float(getattr(setup, "reward_pips_1", 0) or 0)
    reward_2 = float(getattr(setup, "reward_pips_2", 0) or 0)
    rr1 = float(getattr(setup, "risk_reward_1", 0) or 0)
    rr2 = float(getattr(setup, "risk_reward_2", 0) or 0)

    # Statut d'exécution PAC : distingue clairement "trade auto-exécuté chez
    # ton broker" vs "signal info uniquement (paire en surveillance/PAUSED)".
    # Évite la confusion vécue le 2026-06-09 où un signal GBP/USD buy avec
    # verdict TAKE et summary "passez l'ordre" arrivait alors que la paire
    # était PAUSED depuis 6 jours et que le bridge n'exécutait rien.
    pac_auto = None
    pac_state = None
    try:
        from backend.services import pair_admission_controller as _pac
        if _pac.has_explicit_state(setup.pair, dir_value):
            pac_state = _pac.get_current_state(setup.pair, dir_value)
            pac_auto = (pac_state == "AUTO_EXEC")
        else:
            # Fallback legacy stars : si pair dans _STAR_PAIRS_SET, considère auto
            pac_auto = setup.pair in _STAR_PAIRS_SET
            pac_state = "AUTO_EXEC (legacy)" if pac_auto else "non-éligible"
    except Exception:
        pac_auto = None  # PAC indisponible → on n'affiche pas de badge

    if pac_auto is True:
        # Liste les destinations admin qui recevront ce setup (Demo, Live, ...).
        # Filtré sur confidence + asset class pour matcher ce que mt5_bridge
        # routera effectivement. Cf. project_live_icmarkets_active_2026_06_12
        # depuis 2026-06-12 : Demo Pepperstone + Live IC Markets en parallèle.
        dest_labels = _describe_admin_destinations(setup)
        if dest_labels:
            exec_badge = f"🤖 *Auto-exécuté* → {' + '.join(dest_labels)}"
        else:
            # Fallback legacy si resolve_destinations n'a rien retourné
            # (filtres en amont, edge case).
            exec_badge = "🤖 *Auto-exécuté* — ordre envoyé chez ton broker."
    elif pac_auto is False:
        exec_badge = (
            f"👁 *Signal info uniquement* — paire en `{pac_state}`, "
            f"**pas d'auto-exécution**. À placer manuellement si tu veux."
        )
    else:
        exec_badge = None

    lines = [
        f"{verdict_icon} *{pair_label}* ({setup.pair}) — {dir_label}",
        f"Score *{score:.0f}/100* · {time_str} Paris",
    ]
    if exec_badge:
        lines.append(exec_badge)
    lines.extend([
        "",
        "🧭 *Lecture du radar*",
        f"Pattern détecté : *{pattern_explain}*.",
    ])

    verdict_summary = getattr(setup, "verdict_summary", None)
    if verdict_summary:
        lines.append(f"_{verdict_summary}_")

    lines.extend([
        "",
        "💰 *Plan de trade*",
        f"Entrée  `{setup.entry_price:.5f}`",
        f"Stop    `{setup.stop_loss:.5f}`  _(perte si invalidé : {risk:.1f} pts)_",
        f"TP1     `{setup.take_profit_1:.5f}`  _(+{reward_1:.1f} pts, soit {rr1:.1f}× la perte)_",
        f"TP2     `{setup.take_profit_2:.5f}`  _(+{reward_2:.1f} pts, soit {rr2:.1f}× la perte)_",
    ])

    if rr1 > 0:
        lines.extend([
            "",
            "📊 *Comment lire ce trade*",
            f"Tu risques *{risk:.1f} pts* pour viser *+{reward_1:.1f} pts* (R:R {rr1:.1f}). "
            f"Avec ce ratio, le trade devient gagnant si tu touches TP1 plus de "
            f"{int(round(100/(1+rr1)))}% du temps.",
        ])

    # Conversion EUR estimée (lot baseline 0.01 = volume minimum). Pour Demo
    # (max_lot 0.10) multiplier mentalement par 10, pour Live IC Markets
    # (max_lot 0.02) multiplier par 2. Approximation : EUR/USD ~1.10 + specs
    # broker standards. Cf. _PIP_VALUE_AT_001_LOT_EUR.
    eur = _estimate_eur_amounts(setup)
    if eur is not None:
        eur_lines = ["", "💵 *En euros (estimation, lot 0.01)*"]
        if eur.get("margin") is not None:
            eur_lines.append(f"Argent engagé : *~€{eur['margin']:.0f}* (margin requise)")
        eur_lines.extend([
            f"Risque max    : *−€{eur['risk']:.2f}* si SL touché",
            f"Gain TP1      : *+€{eur['reward_1']:.2f}*"
            + (f"  ·  TP2 : *+€{eur['reward_2']:.2f}*" if eur.get("reward_2") else ""),
            "_Demo (×0.10 lot) ≈ ×10  ·  Live IC Markets (0.02 lot) ≈ ×2_",
        ])
        lines.extend(eur_lines)

    reasons = getattr(setup, "verdict_reasons", None) or []
    warnings = getattr(setup, "verdict_warnings", None) or []
    if reasons:
        lines.append("")
        lines.append("✅ *Pourquoi entrer*")
        for r in reasons[:3]:
            lines.append(f"• {r}")
    if warnings:
        lines.append("")
        lines.append("⚠️ *Vigilance*")
        for w in warnings[:3]:
            lines.append(f"• {w}")

    validity = getattr(setup, "validity_minutes", None)
    if validity:
        lines.append("")
        lines.append(f"⏱ *Validité* {validity} min — passé ce délai, le marché aura bougé, recalculer ou attendre le prochain signal.")

    return "\n".join(lines)


async def _send_setup_to(chat_id: str, setup, who: str) -> None:
    url = TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": chat_id,
        "text": _format_setup(setup),
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code != 200:
                logger.warning(f"Telegram setup erreur {response.status_code} pour {who}: {response.text[:200]}")
            else:
                logger.info(
                    f"Setup Telegram envoye a {who} pour {setup.pair} "
                    f"({setup.verdict_action} {getattr(setup, 'confidence_score', 0):.0f})"
                )
    except Exception as e:
        logger.warning(f"Erreur envoi setup Telegram {who}: {e}")


async def send_setup(setup) -> None:
    """Push un trade_setup unique sur Telegram si verdict + seuil + dedup OK."""
    if not is_configured() or not _should_push_setup(setup):
        return
    key = _setup_dedup_key(setup)
    _cleanup_old_dedup_keys()
    if key in _sent_setups_today:
        return
    _sent_setups_today.add(key)

    # Envoi legacy (Xavier env TELEGRAM_CHATS / TELEGRAM_CHAT_ID)
    destinataires = _destinataires()
    for user, chat_id in destinataires:
        if user != "__any__" and trade_log_service.silent_mode_active_for_user(user):
            logger.info(f"Mode silencieux actif pour {user}, setup {setup.pair} skip")
            continue
        await _send_setup_to(chat_id, setup, who=user)

    # Envoi per-user DB (chantier 2026-06-14) : chaque user Premium qui a
    # connecté son Telegram reçoit UNIQUEMENT les setups qui matchent ses
    # watched_pairs + min_confidence. Filtrage déjà appliqué dans
    # _per_user_chat_ids_for_setup. Aucune intervention env.
    per_user = _per_user_chat_ids_for_setup(setup)
    for email, chat_id in per_user:
        await _send_setup_to(chat_id, setup, who=f"db:{email}")


async def send_setups(setups: list) -> None:
    """Push plusieurs trade_setups en parallèle. Dedup + filtres s'appliquent."""
    if not is_configured() or not setups:
        return
    await asyncio.gather(*(send_setup(s) for s in setups), return_exceptions=True)


# ─── Notifications de fermeture (TP/SL/TIMEOUT/MANUAL) ──────────────────────
# Pendant logique : send_setup pousse à l'OUVERTURE d'un setup détecté.
# send_close pousse à la FERMETURE d'un trade auto-exec (mt5_ticket connu).
# Dédup ticket-based : un trade ne notifie qu'une fois sa clôture.

_notified_closes: set[int] = set()


def _format_close(trade: dict) -> str:
    """Format vulgarisé fermeture : 'résultat + impact sur ton solde'.

    Réécrit 2026-06-13 pour parler au lambda.
    """
    from datetime import datetime, timezone, timedelta

    pair = trade.get("pair") or "?"
    pair_label = _PAIR_FR_LABEL.get(pair, pair)
    direction = (trade.get("direction") or "").lower()
    verb_open = "Acheté" if direction == "buy" else "Vendu"
    verb_close = "revendu" if direction == "buy" else "racheté"
    entry = float(trade.get("entry_price") or 0)
    exit_price = float(trade.get("exit_price") or 0)
    pnl = float(trade.get("pnl") or 0)
    close_reason = (trade.get("close_reason") or "UNKNOWN").upper()
    ticket = trade.get("mt5_ticket") or "—"

    # Header + impact compte
    if close_reason in ("TP1", "TP2"):
        outcome_icon = "✅"
        outcome_word = "Trade GAGNÉ"
        impact = "ton solde a augmenté"
        explain = "Objectif de gain atteint comme prévu."
    elif close_reason == "SL":
        outcome_icon = "❌"
        outcome_word = "Trade PERDU"
        impact = "ton solde a baissé"
        explain = "Le marché s'est retourné, le stop de sécurité a coupé la perte."
    elif close_reason == "TIMEOUT":
        outcome_icon = "⏱"
        outcome_word = "Trade clos au temps"
        impact = "ni gain ni perte significatifs"
        explain = "Le marché n'a pas bougé assez. Position libérée pour faire place à d'autres signaux."
    elif close_reason == "MANUAL":
        outcome_icon = "👋"
        outcome_word = "Trade fermé à la main"
        impact = "fermé manuellement"
        explain = "Tu as clôturé la position toi-même depuis MT5 — le radar n'a pas pris la décision."
    else:
        outcome_icon = "🔚"
        outcome_word = "Trade fermé"
        impact = ""
        explain = "Sortie de cause inconnue — vérifier l'historique MT5."

    # Durée
    duration_str = "—"
    try:
        ca = trade.get("created_at")
        cb = trade.get("closed_at")
        if ca and cb:
            t0 = datetime.fromisoformat(str(ca).replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(str(cb).replace("Z", "+00:00"))
            delta = t1 - t0
            mins = int(delta.total_seconds() / 60)
            if mins < 60:
                duration_str = f"{mins} min"
            elif mins < 24 * 60:
                duration_str = f"{mins // 60}h{mins % 60:02d}"
            else:
                duration_str = f"{mins // (24*60)}j{(mins % (24*60)) // 60}h"
    except Exception:
        pass

    pnl_sign = "+" if pnl >= 0 else ""
    # Prix au format FR
    decimals = 2 if any(k in pair for k in ("XAU", "XAG", "BTC", "ETH", "SOL", "LTC", "BCH", "DOT", "ADA", "XRP", "WTI")) else 5
    entry_str = f"{entry:.{decimals}f}".replace(".", ",")
    exit_str = f"{exit_price:.{decimals}f}".replace(".", ",")

    header_impact = f" · {impact}" if impact else ""
    lines = [
        f"{outcome_icon} *{outcome_word}* · {pair_label} ({pair})",
        f"*{pnl_sign}€{pnl:.2f}* en {duration_str}{header_impact}",
        "",
        "📋 *Détail*",
        f"{verb_open} à {entry_str} → {verb_close} à {exit_str}",
        explain,
        "",
    ]
    # Rappel de la justification d'origine (pattern + score IA), si dispo
    just_lines = _build_trade_justification(
        trade.get("signal_pattern"),
        trade.get("signal_confidence"),
        pair=trade.get("pair"),
    )
    if just_lines:
        lines.extend(just_lines)
        lines.append("")
    lines.append(f"`#{ticket}`")
    return "\n".join(lines)


async def send_close(trade: dict) -> None:
    """Push une notification de fermeture sur le canal user-facing.

    Filtre : pair stars-only + LIVE_EXTRA_PAIRS (forex majors autorisés pour
    le Live IC Markets depuis 2026-06-12). Avant cette date, forex EUR/USD,
    GBP/USD, USD/JPY etaient skipped car non-stars → user ne voyait jamais
    la cloture de ses trades Live forex.

    Dedup en mémoire par mt5_ticket — reset au reboot (peu grave, pire cas
    re-notif au redémarrage si un trade vient de fermer).
    """
    pair = trade.get("pair")
    ticket = trade.get("mt5_ticket")
    if ticket and int(ticket) in _notified_closes:
        return
    if ticket:
        _notified_closes.add(int(ticket))

    text = _format_close(trade)

    # Miroir @xav_scalping_sales_bot (2026-08-02) : Xavier admin reçoit
    # TOUTES les clôtures (y compris pairs non-stars — SPX/NDX/altcoins/
    # xStocks) pour tracking business, indépendamment du filtre stars-only
    # qui protège les customers user-facing. Best-effort silent fail.
    try:
        from config.settings import SALES_TELEGRAM_BOT_TOKEN, SALES_TELEGRAM_CHAT_ID
        if SALES_TELEGRAM_BOT_TOKEN and SALES_TELEGRAM_CHAT_ID:
            sales_url = TELEGRAM_API.format(token=SALES_TELEGRAM_BOT_TOKEN)
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(sales_url, json={
                    "chat_id": SALES_TELEGRAM_CHAT_ID,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                })
                if r.status_code != 200:
                    logger.warning(f"Telegram close sales miroir {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.warning(f"send_close sales mirror error: {e}")

    # User-facing bot : filtre stars-only + LIVE_EXTRA_PAIRS pour customers
    if not is_configured():
        return
    try:
        from config.settings import MT5_BRIDGE_LIVE_EXTRA_PAIRS as _live_extras
    except Exception:
        _live_extras = frozenset()
    allowed_pairs = _STAR_PAIRS_SET | _live_extras
    if pair not in allowed_pairs:
        return
    destinataires = _destinataires()
    if not destinataires:
        return
    url = TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN)
    for user, chat_id in destinataires:
        if user != "__any__" and trade_log_service.silent_mode_active_for_user(user):
            continue
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                })
                if response.status_code != 200:
                    logger.warning(f"Telegram close erreur {response.status_code} pour {user}: {response.text[:200]}")
                else:
                    logger.info(f"Close Telegram envoye a {user} pour {pair} ticket={ticket}")
        except Exception as e:
            logger.warning(f"Erreur envoi close Telegram {user}: {e}")


# ─── Refonte notifs user (2026-06-10) ────────────────────────────────
# Suite à la demande user du 2026-06-10 minuit : virer les push setup
# verbeux (TELEGRAM_SETUP_VERDICTS="" en .env coupe send_setup) et envoyer
# uniquement des notifs actionnables :
#   - send_trade_opened : confirme un fill broker réussi
#   - send_close       : (déjà existant) confirme une clôture
#   - send_veto_alert  : 1er match d'une règle veto dans la journée
#   - send_pac_transition_user : changement d'état AUTO_EXEC/PAUSED/etc.
#   - send_daily_recap : récap 23h59 Paris (PnL + scope + transitions + vetos)

# Dedup en mémoire pour la notif veto : 1 push max par (date, rule_id, pair)
_veto_notified_today: set[tuple[str, str, str]] = set()


# Pattern → texte vulgarisé (1 phrase courte, < 110 chars pour rentrer en mobile).
# Indexé par string PatternType.value pour pouvoir être appelé à la close
# (le dict trade ne contient qu'une string signal_pattern, pas l'enum).
_PATTERN_FR_SHORT: dict[str, str] = {
    "breakout_up": "Cassure de résistance — accélération haussière probable.",
    "breakout_down": "Cassure de support — accélération baissière probable.",
    "momentum_up": "Élan acheteur (plusieurs bougies vertes successives).",
    "momentum_down": "Élan vendeur (plusieurs bougies rouges successives).",
    "range_bounce_up": "Rebond sur support — entrée bas dans une zone d'achat.",
    "range_bounce_down": "Rejet sur résistance — entrée haut dans une zone de vente.",
    "mean_reversion_up": "Retour à la moyenne — prix trop bas, rebond attendu.",
    "mean_reversion_down": "Retour à la moyenne — prix trop haut, baisse attendue.",
    "engulfing_bullish": "Englobante haussière — retournement à la hausse probable.",
    "engulfing_bearish": "Englobante baissière — retournement à la baisse probable.",
    "pin_bar_up": "Pin bar haussière — rejet violent du prix bas.",
    "pin_bar_down": "Pin bar baissière — rejet violent du prix haut.",
}


def _build_trade_justification(pattern_value, confidence_score, pair: str | None = None) -> list[str]:
    """Retourne 0-4 lignes vulgarisées expliquant pourquoi le radar a pris ce trade.

    Args:
        pattern_value: string PatternType.value (ex: "breakout_up") ou None
        confidence_score: score IA 0-100 ou None
        pair: ex "BTC/USD" — active la ligne sentiment crypto si pair crypto

    Renvoie une liste de lignes Markdown prête à splice dans le message.
    Liste vide si rien d'exploitable (silencieux, pas de bruit user).
    """
    lines: list[str] = []
    pat_text = None
    if pattern_value:
        key = str(pattern_value).lower()
        pat_text = _PATTERN_FR_SHORT.get(key)
    if not pat_text and confidence_score is None:
        return lines
    lines.append("📊 *Pourquoi ce trade ?*")
    if pat_text:
        lines.append(f"• {pat_text}")
    if confidence_score is not None:
        try:
            score = float(confidence_score)
        except (TypeError, ValueError):
            score = None
        if score is not None:
            if score >= 75:
                qual = "signal fort"
            elif score >= 65:
                qual = "signal correct"
            else:
                qual = "signal limite"
            lines.append(f"• Score IA : *{score:.0f}/100* ({qual})")
    # Climat de marché tiré du VIX (indice du stress des marchés US, proxy
    # cross-asset). Silencieux si data non disponible ou périmée.
    try:
        from backend.services import vix_service as _vix
        d = _vix.get_current()
        if d.get("available") and d.get("is_fresh"):
            v = float(d["value"])
            if v < 15:
                climate = "calme (peu de stress)"
            elif v < 25:
                climate = "normal"
            elif v < 35:
                climate = "tendu (stress modéré)"
            else:
                climate = "panique"
            lines.append(f"• Climat de marché : *{climate}* (VIX {v:.1f})")
    except Exception:
        pass
    # Sentiment crypto (alternative.me F&G) — pertinent uniquement BTC/ETH/altcoins.
    # Silencieux si pair non crypto ou cache périmé (>2 jours).
    if pair:
        try:
            from backend.services import crypto_fear_greed_service as _cfg
            feats = _cfg.get_features(pair)
            if feats.get("cfg_available"):
                v = float(feats.get("cfg_value") or 0)
                if v < 25:
                    label = "peur extrême (souvent fond de marché)"
                elif v < 50:
                    label = "peur"
                elif v < 75:
                    label = "optimisme"
                else:
                    label = "euphorie (souvent top de marché)"
                lines.append(f"• Sentiment crypto : *{label}* (F&G {v:.0f}/100)")
        except Exception:
            pass
    return lines


def _format_trade_opened(
    setup, ticket: int, fill_price: float, volume: float,
    mode: str, destination_id: str | None = None,
) -> str:
    """Format vulgarisé : 'qu'est-ce qui se passe, combien je gagne/perds, pourquoi'.

    Réécrit 2026-06-13 pour parler au lambda (cf. memo
    feedback_telegram_messages_vulgarized_2026_06_13).

    2026-06-18 fix : "LIVE (argent réel)" ne dépend plus du `mode` du
    bridge (toujours "live" en exécution réelle, qu'on tape sur Demo
    Pepperstone ou Live IC Markets), mais du destination_id. Seul
    `admin_live` = argent réel. Tous les autres (admin_legacy, user:N
    Premium en Demo, etc.) = Démo.
    """
    from datetime import datetime, timezone, timedelta
    dir_value = setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction)
    dir_word = "ACHAT" if dir_value == "buy" else "VENTE"
    pair_label = _PAIR_FR_LABEL.get(setup.pair, setup.pair)
    paris_now = datetime.now(timezone.utc) + timedelta(hours=2)
    time_str = paris_now.strftime("%H:%M")
    # Label broker + statut. destination_id discrimine :
    # - admin_live   = IC Markets, argent réel (le seul vrai LIVE)
    # - admin_legacy = Pepperstone, compte Démo
    # - admin_binance = Binance USDⓈ-M testnet (shadow R&D)
    # - user:N        = Premium user (bridge MT5 Démo Pepperstone côté EA)
    if destination_id == "admin_live":
        mode_label = "IC Markets · LIVE (argent réel)"
    elif destination_id == "admin_legacy":
        mode_label = "Pepperstone · Démo"
    elif destination_id == "admin_binance":
        mode_label = "Binance · Testnet (R&D)"
    elif destination_id and destination_id.startswith("user:"):
        mode_label = "Premium · Démo"
    else:
        mode_label = "Démo"

    # Prix au format FR (virgule, 2 décimales pour métaux/crypto, 5 pour forex)
    decimals = 2 if any(k in setup.pair for k in ("XAU", "XAG", "BTC", "ETH", "SOL", "LTC", "BCH", "DOT", "ADA", "XRP", "WTI")) else 5
    fill_str = f"{fill_price:.{decimals}f}".replace(".", ",")

    lines = [
        f"🟢 *Nouveau trade* · {pair_label} ({setup.pair})",
        f"Position *{dir_word}* à {fill_str} · {time_str}",
        "",
    ]

    eur = _estimate_eur_amounts(setup)
    if eur is not None:
        gain_visee = eur.get("reward_1") or 0
        perte_max = eur.get("risk") or 0
        lines.append(f"💰 Gain visé : *+€{gain_visee:.2f}*")
        lines.append(f"🛑 Perte max : *−€{perte_max:.2f}*")
        lines.append(f"⏱ Durée moyenne : 1 à 4h")
        lines.append("")

    # Justification du trade (pattern + score IA), vulgarisée
    try:
        pat_val = setup.pattern.pattern.value if hasattr(setup.pattern.pattern, "value") else str(setup.pattern.pattern)
    except AttributeError:
        pat_val = None
    just_lines = _build_trade_justification(
        pat_val,
        getattr(setup, "confidence_score", None),
        pair=getattr(setup, "pair", None),
    )
    if just_lines:
        lines.extend(just_lines)
        lines.append("")

    lines.append("ℹ️ Le radar a lancé un ordre auto chez ton broker. Le trade tourne seul jusqu'à toucher son objectif ou son stop.")
    lines.append("")
    lines.append(f"`#{ticket}` · compte {mode_label}")
    return "\n".join(lines)


async def send_trade_opened(
    setup, ticket: int, fill_price: float, volume: float,
    mode: str, destination_id: str | None = None,
) -> None:
    """Push une notif user-facing à la confirmation d'un fill broker.

    Appelée depuis ``mt5_bridge._push_to_destination`` après status 200.
    Le ticket vient de la réponse bridge.
    ``destination_id`` discrimine admin_live (argent réel) du reste.
    Best-effort : toute exception silencieuse, ne casse jamais le flow trade.
    """
    if not is_configured():
        return
    try:
        text = _format_trade_opened(
            setup, ticket, fill_price, volume, mode,
            destination_id=destination_id,
        )
        destinataires = _destinataires()
        url = TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN)
        for user, chat_id in destinataires:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(url, json={
                        "chat_id": chat_id, "text": text,
                        "parse_mode": "Markdown", "disable_web_page_preview": True,
                    })
                    if r.status_code != 200:
                        logger.warning(f"Telegram trade_opened {r.status_code}: {r.text[:200]}")
            except Exception as e:
                logger.warning(f"Erreur envoi trade_opened {user}: {e}")
    except Exception as e:
        logger.warning(f"send_trade_opened error: {e}")


async def send_veto_alert(pair: str, direction: str, rules_matched: list[str], reasons: list[str]) -> None:
    """Push une alerte user au 1er match veto géopolitique du jour pour
    (pair, rule). Dedup en mémoire par (date_iso, rule_id, pair) — évite le
    spam si la même règle déclenche plusieurs cycles.
    """
    if not is_configured() or not rules_matched:
        return
    from datetime import date
    today_iso = date.today().isoformat()
    new_rules = []
    for rule_id in rules_matched:
        key = (today_iso, rule_id, pair)
        if key in _veto_notified_today:
            continue
        _veto_notified_today.add(key)
        new_rules.append(rule_id)
    if not new_rules:
        return
    try:
        # Vulgarisation des noms de règles techniques (2026-06-13)
        _RULE_FR = {
            "FED_HAWKISH": "Fed (banque centrale US) en mode restrictif",
            "GDELT_STRESS": "Climat géopolitique stressé (actualité internationale)",
            "POLYMARKET_RISK": "Marché prédictif signale un risque imminent",
            "TARIFF": "Annonce de hausse de tarifs douaniers",
            "ECB_HAWKISH": "BCE (banque centrale Europe) en mode restrictif",
        }
        import html as _html
        pair_label = _PAIR_FR_LABEL.get(pair, pair)
        rules_friendly = [_RULE_FR.get(r, r) for r in new_rules]
        causes_str = "\n".join(f"• {_html.escape(r)}" for r in rules_friendly[:3])
        # HTML depuis 2026-08-02 : Markdown legacy cassait sur les parenthèses /
        # apostrophes / underscores des règles vulgarisées (HTTP 400 "can't parse
        # entities at byte offset 131/132"). html.escape neutralise <>& variables.
        text = (
            f"🌍 <b>Trades suspendus</b> · {_html.escape(pair_label)} ({_html.escape(pair)})\n"
            f"\n"
            f"⚠️ Le contexte macro est trop tendu pour trader sereinement.\n"
            f"Cause(s) :\n{causes_str}\n"
            f"\n"
            f"ℹ️ Le radar surveille l'actualité économique et géopolitique en continu. "
            f"Si ça devient risqué, il bloque les trades pour te protéger.\n"
            f"\n"
            f"🔁 Reprise auto dès que la situation se calme — rien à faire de ton côté."
        )
        destinataires = _destinataires()
        url = TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN)
        for user, chat_id in destinataires:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(url, json={
                        "chat_id": chat_id, "text": text,
                        "parse_mode": "HTML", "disable_web_page_preview": True,
                    })
                    if r.status_code != 200:
                        logger.warning(f"Telegram veto_alert {r.status_code}: {r.text[:200]}")
            except Exception as e:
                logger.warning(f"Erreur envoi veto_alert {user}: {e}")
    except Exception as e:
        logger.warning(f"send_veto_alert error: {e}")


async def send_pac_transition_user(pair: str, direction: str | None, from_state: str | None, to_state: str, reason: str) -> None:
    """Push une notif user d'une transition PAC (en plus de la notif infra existante).

    Filtré : on n'envoie PAS les backfills (transitioned_by='auto:backfill').
    Les states PAUSED/AUTO_EXEC/DEMOTED/OBSERVED/TELEGRAM intéressent le user
    pour comprendre quelles paires deviennent éligibles ou pas.
    """
    if not is_configured():
        return
    try:
        # Vulgarisation 2026-06-13 : explication impact + glossaire états en bas
        _STATE_FR = {
            "OBSERVED": "👁 simplement surveillée (pas d'ordres)",
            "TELEGRAM": "📱 signal envoyé en notif (à toi de jouer)",
            "AUTO_EXEC": "🤖 trades automatiques (le radar exécute seul)",
            "PAUSED": "⏸ en pause (résultats récents insuffisants)",
            "DEMOTED": "📉 rétrogradée (performance dégradée)",
        }
        arrow = "📈" if to_state in ("TELEGRAM", "AUTO_EXEC") else "📉" if to_state == "DEMOTED" else "⏸" if to_state == "PAUSED" else "🔄"
        action_word = {
            "AUTO_EXEC": "activée en mode auto",
            "TELEGRAM": "activée en mode notif",
            "PAUSED": "mise en pause",
            "DEMOTED": "rétrogradée",
            "OBSERVED": "remise en simple surveillance",
        }.get(to_state, "modifiée")
        pair_label = _PAIR_FR_LABEL.get(pair, pair)
        dir_str = ""
        if direction == "buy":
            dir_str = " (sens achat)"
        elif direction == "sell":
            dir_str = " (sens vente)"
        new_state_fr = _STATE_FR.get(to_state, to_state)
        reason_short = (reason or "")[:140]

        if to_state == "AUTO_EXEC":
            effect_line = "Effet : le radar prendra les ordres seul sur cette paire quand un signal apparaît."
        elif to_state == "TELEGRAM":
            effect_line = "Effet : tu vas recevoir les signaux par notif, à toi de placer l'ordre manuellement si tu veux."
        elif to_state in ("PAUSED", "DEMOTED"):
            effect_line = "Effet : plus de trades auto sur cette paire jusqu'à amélioration des résultats."
        else:
            effect_line = "Effet : la paire est juste observée pour le moment."

        text = (
            f"{arrow} *{pair_label}* {action_word} · {pair}{dir_str}\n"
            f"\n"
            f"Nouveau mode : *{new_state_fr}*\n"
            f"{effect_line}\n"
            f"\n"
            f"ℹ️ Une paire peut basculer entre 4 modes selon ses performances. "
            f"Tu reçois ce message à chaque changement.\n"
            f"\n"
            f"_Raison : {reason_short}_"
        )
        destinataires = _destinataires()
        url = TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN)
        for user, chat_id in destinataires:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(url, json={
                        "chat_id": chat_id, "text": text,
                        "parse_mode": "Markdown", "disable_web_page_preview": True,
                    })
                    if r.status_code != 200:
                        logger.warning(f"Telegram pac_transition_user {r.status_code}: {r.text[:200]}")
            except Exception as e:
                logger.warning(f"Erreur envoi pac_transition_user {user}: {e}")
    except Exception as e:
        logger.warning(f"send_pac_transition_user error: {e}")


async def send_daily_recap() -> None:
    """Récap 23h59 Paris : PnL du jour + scope auto-exec + transitions du jour + vetos.

    Cron job appelé depuis scheduler.py via CronTrigger(timezone="Europe/Paris",
    hour=23, minute=59). Le récap couvre la fenêtre Paris [00:00 → 23:59] du jour.
    Best-effort : toute erreur SQL → message minimal sans crash.
    """
    if not is_configured():
        return
    try:
        from datetime import datetime, timezone, timedelta
        import sqlite3
        from backend.services.trade_log_service import _DB_PATH

        paris_now = datetime.now(timezone.utc) + timedelta(hours=2)
        today_paris = paris_now.date().isoformat()
        today_label = paris_now.strftime("%d/%m/%Y")

        con = sqlite3.connect(str(_DB_PATH))
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        # PnL du jour (Xavier auto)
        pnl_row = cur.execute(
            """SELECT COUNT(*) n, COALESCE(SUM(pnl),0) pnl,
                      SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) wins,
                      SUM(CASE WHEN pnl<0 THEN 1 ELSE 0 END) losses
               FROM personal_trades
               WHERE is_auto=1 AND status='CLOSED'
                 AND DATE(closed_at)=DATE(?)""",
            (today_paris,),
        ).fetchone()

        # Scope auto-exec : la table pair_admission_state est append-only
        # (insert à chaque transition), donc filtrer state='AUTO_EXEC' direct
        # remonte aussi les paires qui ONT ÉTÉ AUTO_EXEC un jour. Il faut
        # joindre sur MAX(id) par (pair, direction) pour avoir l'état courant.
        scope_rows = cur.execute(
            """SELECT pas.pair, pas.direction
               FROM pair_admission_state pas
               JOIN (
                   SELECT pair, direction, MAX(id) AS max_id
                   FROM pair_admission_state
                   GROUP BY pair, direction
               ) t
                 ON pas.pair = t.pair
                AND IFNULL(pas.direction,'') = IFNULL(t.direction,'')
                AND pas.id = t.max_id
               WHERE pas.state = 'AUTO_EXEC' AND pas.direction IS NOT NULL
               ORDER BY pas.pair, pas.direction"""
        ).fetchall()

        # Transitions du jour
        trans_rows = cur.execute(
            """SELECT pair, direction, state, reason
               FROM pair_admission_state
               WHERE DATE(state_since)=DATE(?)
                 AND transitioned_by != 'auto:backfill'
               ORDER BY state_since DESC LIMIT 15""",
            (today_paris,),
        ).fetchall()

        # Vetos du jour
        veto_row = cur.execute(
            """SELECT COUNT(*) n FROM signal_rejections
               WHERE reason_code='geopolitical_veto'
                 AND DATE(created_at)=DATE(?)""",
            (today_paris,),
        ).fetchone()

        con.close()

        # Format
        lines = [f"📊 *Récap du {today_label}*", ""]
        n = pnl_row["n"] or 0
        if n > 0:
            pnl = pnl_row["pnl"] or 0
            wins = pnl_row["wins"] or 0
            losses = pnl_row["losses"] or 0
            emoji = "🟢" if pnl > 0 else ("🔴" if pnl < 0 else "⚪")
            lines.append(f"{emoji} *PnL du jour : {pnl:+.2f} $*")
            wr = (100.0 * wins / n) if n > 0 else 0
            lines.append(f"   {n} trades clôturés · {wins} gagnants / {losses} perdants · WR {wr:.0f}%")
        else:
            lines.append("💤 Aucun trade clôturé aujourd'hui.")

        lines.append("")
        lines.append(f"📋 *Scope auto-exec* ({len(scope_rows)} paires actives) :")
        if scope_rows:
            for r in scope_rows[:20]:
                lines.append(f"   • {r['pair']} {r['direction']}")
        else:
            lines.append("   _(aucune paire AUTO_EXEC)_")

        if trans_rows:
            lines.append("")
            lines.append(f"🔄 *Transitions du jour* ({len(trans_rows)})")
            for r in trans_rows[:8]:
                reason_short = (r["reason"] or "")[:60]
                dir_str = r["direction"] or "*"
                lines.append(f"   • {r['pair']} {dir_str} → *{r['state']}* — {reason_short}")
        else:
            lines.append("")
            lines.append("🔄 Pas de transition PAC aujourd'hui.")

        n_veto = veto_row["n"] or 0
        lines.append("")
        if n_veto > 0:
            lines.append(f"🌍 *{n_veto} setup(s) bloqué(s) par veto géopolitique aujourd'hui.*")
        else:
            lines.append("🌍 Aucun veto géopolitique aujourd'hui.")

        await send_text("\n".join(lines))

    except Exception as e:
        logger.warning(f"send_daily_recap error: {e}")
