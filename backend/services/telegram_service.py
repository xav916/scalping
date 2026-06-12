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


# Pip-value en EUR par 0.01 lot (= volume minimum). Approximations basées sur
# specs broker standards 2026-06 + EUR/USD ~1.10. Utilisé pour estimer le
# risque/gain en € user-facing dans les messages Telegram. Volatile.
# Pour Demo (max_lot 0.10) : multiplier par 10.
# Pour Live IC Markets (max_lot 0.02) : multiplier par 2.
_PIP_VALUE_AT_001_LOT_EUR: dict[str, float] = {
    # Forex majors quote USD : pip = 0.0001, 0.01 lot = 1000 base → $0.10/pip ≈ €0.09
    "EUR/USD": 0.09,
    "GBP/USD": 0.09,
    "AUD/USD": 0.09,
    "NZD/USD": 0.09,
    # Forex JPY quote : pip = 0.01, 0.01 lot ≈ ¥10 → $0.07 ≈ €0.06
    "USD/JPY": 0.06,
    "EUR/JPY": 0.06,
    "GBP/JPY": 0.06,
    # Metals (oz)
    "XAU/USD": 0.009,  # 0.01 lot = 1 oz, 1 pip = $0.01 ≈ €0.009
    "XAG/USD": 0.045,  # 0.01 lot = 50 oz, 1 pip = $0.05 ≈ €0.045
    # Energy (barrels)
    "WTI/USD": 0.09,   # 0.01 lot = 10 barrels, 1 pip = $0.10 ≈ €0.09
    # Crypto (rough)
    "ETH/USD": 0.009,
    "BTC/USD": 0.009,
}


def _estimate_eur_amounts(setup) -> dict | None:
    """Retourne dict {risk, reward_1, reward_2} en EUR estimé pour 0.01 lot.
    None si pair non mappée ou risk_pips manquant. Best-effort, approximation.
    """
    pair = getattr(setup, "pair", "")
    risk_pips = float(getattr(setup, "risk_pips", 0) or 0)
    reward_pips_1 = float(getattr(setup, "reward_pips_1", 0) or 0)
    reward_pips_2 = float(getattr(setup, "reward_pips_2", 0) or 0)
    pip_eur = _PIP_VALUE_AT_001_LOT_EUR.get(pair)
    if not pip_eur or risk_pips <= 0:
        return None
    return {
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

        score = float(getattr(setup, "confidence_score", 0) or 0)
        pair = getattr(setup, "pair", None)
        if not pair:
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
        lines.extend([
            "",
            "💵 *En euros (estimation, lot 0.01)*",
            f"Risque max : *−€{eur['risk']:.2f}* si SL touché",
            f"Gain TP1   : *+€{eur['reward_1']:.2f}*"
            + (f"  ·  TP2 : *+€{eur['reward_2']:.2f}*" if eur.get("reward_2") else ""),
            "_Demo (×0.10 lot) ≈ ×10  ·  Live IC Markets (0.02 lot) ≈ ×2_",
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


# ─── Notifications de fermeture (TP/SL/TIMEOUT/MANUAL) ──────────────────────
# Pendant logique : send_setup pousse à l'OUVERTURE d'un setup détecté.
# send_close pousse à la FERMETURE d'un trade auto-exec (mt5_ticket connu).
# Dédup ticket-based : un trade ne notifie qu'une fois sa clôture.

_notified_closes: set[int] = set()


def _format_close(trade: dict) -> str:
    """Format pédagogique pour la fermeture d'un trade auto-exec.

    Champs attendus dans `trade` (depuis personal_trades) :
    - pair, direction, entry_price, exit_price, pnl, close_reason
    - signal_confidence, mt5_ticket, created_at, closed_at, size_lot

    Sections : Header (outcome + pnl) / Détails / Lecture du résultat.
    """
    from datetime import datetime, timezone, timedelta

    pair = trade.get("pair") or "?"
    pair_label = _PAIR_FR_LABEL.get(pair, pair)
    direction = (trade.get("direction") or "").lower()
    dir_label = "ACHAT 🟢" if direction == "buy" else "VENTE 🔴"
    entry = float(trade.get("entry_price") or 0)
    exit_price = float(trade.get("exit_price") or 0)
    pnl = float(trade.get("pnl") or 0)
    close_reason = (trade.get("close_reason") or "UNKNOWN").upper()
    score = float(trade.get("signal_confidence") or 0)
    ticket = trade.get("mt5_ticket") or "—"
    size_lot = trade.get("size_lot")

    # Outcome icon + verdict text
    if close_reason in ("TP1", "TP2"):
        outcome_icon = "✅"
        outcome_word = f"GAIN ({close_reason} touché)"
    elif close_reason == "SL":
        outcome_icon = "❌"
        outcome_word = "PERTE (Stop Loss touché)"
    elif close_reason == "TIMEOUT":
        outcome_icon = "⏱"
        outcome_word = "FERMÉ AU TEMPS (Timeout — ni TP ni SL touché)"
    elif close_reason == "MANUAL":
        outcome_icon = "👋"
        outcome_word = "FERMÉ MANUELLEMENT"
    else:
        outcome_icon = "🔚"
        outcome_word = f"FERMÉ ({close_reason})"

    # Pts mouvement
    pts_moved = exit_price - entry if direction == "buy" else entry - exit_price

    # Durée du trade
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

    paris_now = datetime.now(timezone.utc) + timedelta(hours=2)
    time_str = paris_now.strftime("%H:%M")

    pnl_sign = "+" if pnl >= 0 else ""
    pts_sign = "+" if pts_moved >= 0 else ""

    lines = [
        f"{outcome_icon} *{pair_label}* ({pair}) — {dir_label}",
        f"*{outcome_word}*",
        f"PnL : *{pnl_sign}{pnl:.2f} €* · Mouvement : {pts_sign}{pts_moved:.2f} pts · {time_str} Paris",
        "",
        "📋 *Détails du trade*",
        f"Entrée  `{entry:.5f}`",
        f"Sortie  `{exit_price:.5f}`",
        f"Durée   {duration_str}",
    ]
    if size_lot:
        lines.append(f"Volume  {size_lot} lot")
    if score:
        lines.append(f"Score initial  {score:.0f}/100")
    lines.append(f"Ticket MT5  `{ticket}`")

    # Lecture pédagogique du résultat
    lines.extend(["", "📊 *Lecture du résultat*"])
    if close_reason in ("TP1", "TP2"):
        lines.append(
            f"Le marché est allé dans la direction prévue jusqu'à toucher le {close_reason}. "
            f"Setup gagnant : la thèse du radar (pattern + tendance) s'est confirmée."
        )
    elif close_reason == "SL":
        lines.append(
            "Le marché s'est inversé contre la position et a touché le Stop Loss. "
            "Perte limitée comme prévu — le SL a fait son job de protection."
        )
    elif close_reason == "TIMEOUT":
        lines.append(
            "Ni TP ni SL touchés dans la fenêtre. Le marché a stagné ou bougé "
            "trop lentement. Sortie au temps écoulé pour libérer le capital."
        )
    elif close_reason == "MANUAL":
        lines.append("Tu as fermé la position manuellement — le radar n'a pas conduit la sortie.")
    else:
        lines.append("Sortie de cause inconnue — voir le journal MT5 pour le détail.")

    return "\n".join(lines)


async def send_close(trade: dict) -> None:
    """Push une notification de fermeture sur le canal user-facing.

    Filtre : pair stars-only, ticket non encore notifié, Telegram configuré.
    Dedup en mémoire par mt5_ticket — reset au reboot (peu grave, pire cas
    re-notif au redémarrage si un trade vient de fermer).
    """
    if not is_configured():
        return
    pair = trade.get("pair")
    if pair not in _STAR_PAIRS_SET:
        return
    ticket = trade.get("mt5_ticket")
    if ticket and int(ticket) in _notified_closes:
        return
    if ticket:
        _notified_closes.add(int(ticket))

    text = _format_close(trade)
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


def _format_trade_opened(setup, ticket: int, fill_price: float, volume: float, mode: str) -> str:
    from datetime import datetime, timezone, timedelta
    dir_value = setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction)
    dir_label = "ACHAT 🟢" if dir_value == "buy" else "VENTE 🔴"
    pair_label = _PAIR_FR_LABEL.get(setup.pair, setup.pair)
    paris_now = datetime.now(timezone.utc) + timedelta(hours=2)
    time_str = paris_now.strftime("%H:%M")
    sl = float(getattr(setup, "stop_loss", 0) or 0)
    tp1 = float(getattr(setup, "take_profit_1", 0) or 0)
    tp2 = float(getattr(setup, "take_profit_2", 0) or 0)
    rr1 = float(getattr(setup, "risk_reward_1", 0) or 0)
    lines = [
        f"🟢 *Trade OUVERT* · {pair_label} ({setup.pair}) · {dir_label}",
        f"Fill `{fill_price:.5f}` · volume `{volume}` · ticket `{ticket}` · {time_str} Paris",
        f"SL `{sl:.5f}` · TP1 `{tp1:.5f}` (R:R {rr1:.1f}) · TP2 `{tp2:.5f}`",
        f"Mode broker : *{mode}*",
    ]
    return "\n".join(lines)


async def send_trade_opened(setup, ticket: int, fill_price: float, volume: float, mode: str) -> None:
    """Push une notif user-facing à la confirmation d'un fill broker.

    Appelée depuis ``mt5_bridge._push_to_destination`` après status 200
    sur le path admin_legacy. Le ticket vient de la réponse bridge.
    Best-effort : toute exception silencieuse, ne casse jamais le flow trade.
    """
    if not is_configured():
        return
    try:
        text = _format_trade_opened(setup, ticket, fill_price, volume, mode)
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
        rules_str = ", ".join(new_rules)
        reasons_str = "\n".join(f"• {r}" for r in (reasons or [])[:3])
        text = (
            f"🌍 *Veto géopolitique activé* · {pair} {direction}\n"
            f"Règle(s) déclenchée(s) : *{rules_str}*\n"
            f"{reasons_str}\n"
            f"_Les setups concernés ne seront pas auto-exécutés tant que la condition macro tient._"
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
        arrow = "📈" if to_state in ("TELEGRAM", "AUTO_EXEC") else "📉" if to_state == "DEMOTED" else "⏸" if to_state == "PAUSED" else "🔄"
        dir_str = direction or "*"
        reason_short = (reason or "")[:120]
        text = (
            f"{arrow} *Transition paire* · {pair} {dir_str}\n"
            f"*{from_state or 'NEW'}* → *{to_state}*\n"
            f"_{reason_short}_"
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
