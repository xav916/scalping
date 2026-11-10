"""Helper partage par les skills .claude/skills/trader-* pour relayer un
event vers le canal Telegram « Scalping Radar Info ».

Zero dependance externe (stdlib seule) — meme contrainte que les skills
upstream trader-skill (MIT, Jake Schincariol). Silent no-op si les env
vars ne sont pas posees : les skills continuent a fonctionner en local
sans push.

Usage dans une skill (apres le travail utile) :

    from trader.notify import notify_radar

    notify_radar(
        skill="trader-alerts",
        title="F a touche 12.20",
        message="Stop level atteint — 12 shares en risque.",
        level="warn",
        data={"symbol": "F", "price": 12.20},
    )

Env vars attendues :

    TRADER_SKILL_RADAR_URL    base URL du radar FastAPI
                              (ex. https://scalping-radar.duckdns.org)
    TRADER_SKILL_WEBHOOK_KEY  partagee avec backend/app.py — meme valeur
                              cote .env serveur et cote machine Claude
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Literal

logger = logging.getLogger(__name__)

Level = Literal["info", "warn", "critical"]


def notify_radar(
    skill: str,
    title: str,
    message: str = "",
    level: Level = "info",
    data: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> bool:
    """POST l'event vers /api/trader-skill-event du radar.

    Retourne True si le relais a reussi, False sinon (y compris si la
    feature est desactivee cote serveur — pas d'exception).
    """
    base_url = os.getenv("TRADER_SKILL_RADAR_URL", "").rstrip("/")
    api_key = os.getenv("TRADER_SKILL_WEBHOOK_KEY", "")
    if not base_url or not api_key:
        logger.debug("notify_radar: TRADER_SKILL_RADAR_URL ou TRADER_SKILL_WEBHOOK_KEY manquant — silent noop")
        return False

    body = json.dumps({
        "api_key": api_key,
        "skill": skill,
        "level": level,
        "title": title,
        "message": message,
        "data": data or {},
    }).encode("utf-8")

    req = urllib.request.Request(
        url=f"{base_url}/api/trader-skill-event",
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "trader-skill-notify/1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        logger.warning("notify_radar: HTTP %s — %s", e.code, e.reason)
        return False
    except Exception as e:
        logger.warning("notify_radar: %s", e)
        return False


if __name__ == "__main__":
    # Smoke test manuel :
    #   TRADER_SKILL_RADAR_URL=... TRADER_SKILL_WEBHOOK_KEY=... python trader/notify.py
    logging.basicConfig(level=logging.DEBUG)
    ok = notify_radar(
        skill="trader-alerts",
        title="Smoke test notify_radar",
        message="Si vous voyez ce message dans Telegram, le relay marche.",
        level="info",
        data={"test": True, "ts": "2026-11-10"},
    )
    print("relayed:", ok)
