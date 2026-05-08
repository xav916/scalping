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
    """Retourne la liste (user, chat_id) a qui envoyer.

    Si TELEGRAM_CHATS est defini : un (user, chat_id) par user configure.
    Sinon fallback sur TELEGRAM_CHAT_ID (broadcast a 1 destinataire anonymous).
    """
    if TELEGRAM_CHATS:
        return list(TELEGRAM_CHATS.items())
    if TELEGRAM_CHAT_ID:
        return [("__any__", TELEGRAM_CHAT_ID)]
    return []


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


async def send_infra_text(text: str, parse_mode: str = "Markdown") -> bool:
    """Envoie un texte vers le canal infra dédié (@xav_scalping_infra_bot).

    Sépare les alertes système (rafales rejections, monitoring infra,
    routine alerts) du canal user-facing qui est réservé aux signaux de
    trading. Lit INFRA_TELEGRAM_BOT_TOKEN + INFRA_TELEGRAM_CHAT_ID depuis
    config.settings — si non configuré, no-op silencieux + log.

    Retourne True si envoyé, False sinon.
    """
    from config.settings import INFRA_TELEGRAM_BOT_TOKEN, INFRA_TELEGRAM_CHAT_ID
    if not INFRA_TELEGRAM_BOT_TOKEN or not INFRA_TELEGRAM_CHAT_ID:
        logger.info("send_infra_text: INFRA_TELEGRAM_* non configure, skip")
        return False
    url = TELEGRAM_API.format(token=INFRA_TELEGRAM_BOT_TOKEN)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json={
                "chat_id": INFRA_TELEGRAM_CHAT_ID,
                "text": text[:4000],
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            })
        if r.status_code != 200:
            logger.warning(f"send_infra_text: HTTP {r.status_code} {r.text[:200]}")
            return False
        return True
    except Exception as e:
        logger.warning(f"send_infra_text: erreur {e}")
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
    """Filtre : star pair + verdict dans la liste autorisée + score au-dessus du seuil."""
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

    lines = [
        f"{verdict_icon} *{pair_label}* ({setup.pair}) — {dir_label}",
        f"Score *{score:.0f}/100* · {time_str} Paris",
        "",
        "🧭 *Lecture du radar*",
        f"Pattern détecté : *{pattern_explain}*.",
    ]

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

    destinataires = _destinataires()
    if not destinataires:
        return
    for user, chat_id in destinataires:
        if user != "__any__" and trade_log_service.silent_mode_active_for_user(user):
            logger.info(f"Mode silencieux actif pour {user}, setup {setup.pair} skip")
            continue
        await _send_setup_to(chat_id, setup, who=user)


async def send_setups(setups: list) -> None:
    """Push plusieurs trade_setups en parallèle. Dedup + filtres s'appliquent."""
    if not is_configured() or not setups:
        return
    await asyncio.gather(*(send_setup(s) for s in setups), return_exceptions=True)
