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
from config.settings import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TELEGRAM_MIN_STRENGTH,
)

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

_strength_order = {"weak": 0, "moderate": 1, "strong": 2}


def _should_send(signal: ScalpingSignal) -> bool:
    min_rank = _strength_order.get(TELEGRAM_MIN_STRENGTH.lower(), 2)
    sig_rank = _strength_order.get(signal.signal_strength.value.lower(), 0)
    return sig_rank >= min_rank


def is_configured() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def _format_signal(signal: ScalpingSignal) -> str:
    emoji = {"strong": "🔥", "moderate": "⚡", "weak": "💡"}.get(signal.signal_strength.value, "📊")
    lines = [
        f"{emoji} *Signal {signal.signal_strength.value.upper()}* — `{signal.pair}`",
        f"Tendance : {signal.trend.direction.value} ({int(signal.trend.strength * 100)}%)",
        f"Volatilite : {signal.volatility.level.value} ({signal.volatility.volatility_ratio:.1f}x)",
    ]
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
    if signal.confidence_score:
        lines.append(f"\nConfiance : *{signal.confidence_score:.0f}/100*")
    if signal.nearby_events:
        evs = ", ".join(f"{e.event_name} ({e.impact.value})" for e in signal.nearby_events[:3])
        lines.append(f"\n⚠️ Evenements : {evs}")
    return "\n".join(lines)


async def send_signal(signal: ScalpingSignal) -> None:
    """Envoie un signal a Telegram si la configuration le permet."""
    if not is_configured():
        return
    if not _should_send(signal):
        return
    # Mode silencieux : si -X% atteint aujourd'hui, on coupe tout
    if trade_log_service.silent_mode_active():
        logger.info(f"Mode silencieux actif, signal {signal.pair} non envoye a Telegram")
        return

    url = TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": _format_signal(signal),
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code != 200:
                logger.warning(f"Telegram erreur {response.status_code}: {response.text[:200]}")
            else:
                logger.info(f"Signal Telegram envoye pour {signal.pair} ({signal.signal_strength.value})")
    except Exception as e:
        logger.warning(f"Erreur envoi Telegram: {e}")


async def send_signals(signals: list[ScalpingSignal]) -> None:
    """Envoie plusieurs signaux en parallele."""
    if not is_configured() or not signals:
        return
    await asyncio.gather(*(send_signal(s) for s in signals), return_exceptions=True)
