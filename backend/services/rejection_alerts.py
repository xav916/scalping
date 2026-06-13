"""Alertes Telegram sur rafales de rejections auto-exec.

Tourne périodiquement (scheduler toutes les 5 min). Pour chaque
reason_code, compte les rejections sur la dernière heure ; si > seuil
(10 par défaut) ET pas d'alerte déjà envoyée sur ce code dans les
dernières 60 min, déclenche un message Telegram.

Évite de spammer : 1 alerte par code toutes les 60 min max.
"""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.services.rejection_service import REASON_LABELS_FR, _db_path, _ensure_schema

logger = logging.getLogger(__name__)

# Seuil : > N rejections du même code sur la dernière heure déclenche
RAFALE_THRESHOLD = 10
# Fenêtre de recherche
WINDOW_HOURS = 1
# Cooldown par code pour ne pas spammer Telegram
COOLDOWN_MINUTES = 60

# Reason codes silencieux : trackés dans signal_rejections pour traçabilité
# (RejectionsCard les rend) mais jamais d'alerte Telegram parce qu'ils
# reflètent un état calendaire / fonctionnel attendu, pas un incident.
# - market_closed : marché fermé week-end ou daily break — par design
SILENT_REASONS: frozenset[str] = frozenset({"market_closed"})

# État en mémoire : reason_code → last_alert_ts. Reset au reboot, peu grave.
_last_alert_at: dict[str, datetime] = {}


def _count_by_reason(since_iso: str, until_iso: str) -> dict[str, int]:
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        rows = c.execute(
            """
            SELECT reason_code, COUNT(*) AS cnt
              FROM signal_rejections
             WHERE created_at >= ? AND created_at <= ?
             GROUP BY reason_code
            """,
            (since_iso, until_iso),
        ).fetchall()
    return {r[0]: r[1] for r in rows}


# Mapping vulgarisé 2026-06-13 : explication "qu'est-ce qui se passe + pourquoi"
# pour les reason_codes les plus fréquents. Affiché sur le bot infra.
_REASON_EXPLAIN_FR = {
    "verdict_blocker": (
        "Signaux refusés par le filtre qualité du radar",
        "Le radar a détecté des opportunités mais son analyse interne (contexte macro, "
        "patterns, indicateurs) a jugé qu'elles n'étaient pas assez fiables pour être "
        "exécutées. Cas typique : marché fermé, contexte tendu, ou pattern incomplet."
    ),
    "below_confidence": (
        "Signaux jugés trop faibles",
        "Le score de confiance des signaux est tombé sous le seuil configuré "
        "(Demo 70, Live 50). Sans atteindre ce seuil, on préfère ne pas trader."
    ),
    "sl_too_close": (
        "Stop loss trop proche du prix actuel",
        "Le stop de sécurité serait collé au prix d'entrée — risque de se faire stopper "
        "immédiatement sur le bruit du marché. Trade abandonné pour éviter une perte sèche."
    ),
    "bridge_error": (
        "Erreur de communication avec le broker",
        "Le tunnel entre le radar et MT5 a renvoyé une erreur (timeout, refus broker, "
        "ou rejet d'ordre). Vérifier l'état des bridges si récurrent."
    ),
    "market_closed": (
        "Marché fermé",
        "Le marché concerné est fermé (weekend ou pause quotidienne). Comportement attendu."
    ),
    "rafale_pause": (
        "Pair mise en pause après trop de pertes",
        "Une paire a accumulé plusieurs stops perdants récents — le radar la met en pause "
        "temporaire pour éviter de tomber dans une mauvaise série."
    ),
    "geopolitical_veto": (
        "Trade bloqué par le contexte géopolitique",
        "Une règle macro (Fed restrictive, climat tendu, tarifs douaniers, etc.) a bloqué "
        "ce trade en sécurité. Reprise auto dès que la situation se calme."
    ),
}


def _format_message(reason_code: str, count: int, top_pairs: list[tuple[str, int]]) -> str:
    """Format vulgarisé pour le bot infra (2026-06-13).
    Tout le monde doit comprendre : qu'est-ce qui se passe, pourquoi, quel impact.
    """
    import html
    label = REASON_LABELS_FR.get(reason_code, reason_code)
    explain = _REASON_EXPLAIN_FR.get(reason_code, (label, ""))
    short_title, why = explain
    safe_code = html.escape(reason_code)

    # Mapping FR des pairs pour vulgarisation
    _PAIR_FR_LOCAL = {
        "XAU/USD": "OR",
        "XAG/USD": "Argent",
        "WTI/USD": "Pétrole",
        "BTC/USD": "Bitcoin",
        "ETH/USD": "Ethereum",
        "SPX": "S&P 500",
        "NDX": "Nasdaq",
    }
    pairs_lines = []
    for p, c in top_pairs[:5]:
        p_fr = _PAIR_FR_LOCAL.get(p, p)
        if p_fr != p:
            pairs_lines.append(f"• {html.escape(p_fr)} ({html.escape(p)}) : {c}")
        else:
            pairs_lines.append(f"• {html.escape(p)} : {c}")

    lines = [
        f"⚠️ <b>Beaucoup de signaux refusés</b> · <b>{count} en 1h</b>",
        "",
        f"<b>Type :</b> {html.escape(short_title)}",
        f"<b>Code technique :</b> <code>{safe_code}</code>",
    ]
    if pairs_lines:
        lines.append("")
        lines.append("📊 <b>Top paires concernées :</b>")
        lines.extend(pairs_lines)
    if why:
        lines.append("")
        lines.append(f"ℹ️ {html.escape(why)}")
    lines.append("")
    lines.append(
        "🔁 Pourquoi ce message ? Plus de 10 signaux refusés en 1h pour la même raison = "
        "soit un contexte de marché difficile (normal, ça passera), soit un vrai souci à "
        "vérifier."
    )
    lines.append("")
    lines.append("Vérification optionnelle : <code>/v2/cockpit</code> → RejectionsCard")
    return "\n".join(lines)


def _top_pairs_for(reason_code: str, since_iso: str, until_iso: str) -> list[tuple[str, int]]:
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        rows = c.execute(
            """
            SELECT pair, COUNT(*) AS cnt
              FROM signal_rejections
             WHERE created_at >= ? AND created_at <= ?
               AND reason_code = ?
             GROUP BY pair
             ORDER BY cnt DESC
             LIMIT 5
            """,
            (since_iso, until_iso, reason_code),
        ).fetchall()
    return [(r[0] or "?", r[1]) for r in rows]


async def check_and_alert() -> dict[str, Any]:
    """Job scheduler : check les rafales, envoie un Telegram si besoin.

    Retourne un résumé pour les tests / debug. Best-effort : toute erreur
    est loggée, pas propagée (ne doit pas planter le scheduler).
    """
    try:
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=WINDOW_HOURS)

        counts = _count_by_reason(since.isoformat(), now.isoformat())
        alerts_sent: list[str] = []
        alerts_suppressed: list[str] = []
        alerts_skipped_silent: list[str] = []

        for reason, count in counts.items():
            if count < RAFALE_THRESHOLD:
                continue
            if reason in SILENT_REASONS:
                alerts_skipped_silent.append(reason)
                continue
            last = _last_alert_at.get(reason)
            if last and (now - last) < timedelta(minutes=COOLDOWN_MINUTES):
                alerts_suppressed.append(reason)
                continue

            # Rafale détectée hors cooldown → envoie
            top_pairs = _top_pairs_for(reason, since.isoformat(), now.isoformat())
            msg = _format_message(reason, count, top_pairs)

            try:
                # Bascule 2026-05-08 : route vers le canal infra
                # (@xav_scalping_infra_bot) au lieu du canal user-facing,
                # cohérent avec project_telegram_bot_infra.md. Le canal
                # user-facing reste dédié aux signaux de trading.
                from backend.services.telegram_service import send_infra_text
                sent = await send_infra_text(msg, parse_mode="HTML")
                if sent:
                    _last_alert_at[reason] = now
                    alerts_sent.append(reason)
                    logger.warning(
                        f"rejection_alerts: rafale {reason} ({count}/h) — alert infra envoyée"
                    )
                else:
                    logger.info(f"rejection_alerts: infra Telegram non configuré, skip {reason}")
            except Exception as e:
                logger.warning(f"rejection_alerts: send failed pour {reason}: {e}")

        return {
            "checked_at": now.isoformat(),
            "counts": counts,
            "alerts_sent": alerts_sent,
            "alerts_suppressed_cooldown": alerts_suppressed,
            "alerts_skipped_silent": alerts_skipped_silent,
        }

    except Exception:
        logger.exception("rejection_alerts: erreur globale check_and_alert")
        return {"error": "crash, voir logs"}
