"""Les heures d'ouverture des places — declarees UNE fois, pour tout le monde.

⛔ **Pourquoi ce module existe** (2026-09-14). La table des sessions vivait
dans `laboratoire_or`, et l'`opening range` en avait besoin dans
`pattern_detector`. Recopier la table aurait cree deux verites : le jour ou
l'une change, deux mesures portent le meme nom en decrivant deux fenetres
differentes — et rien ne le dit. Ce depot a deja paye ce defaut avec
`/opt/scalping/scripts`, divergent du depot pendant une journee entiere.

⚠️ **Heures LOCALES de chaque place, jamais un UTC fige.** Londres et New York
changent d'heure a des dates differentes ; un UTC fixe decalerait la killzone
de soixante minutes pendant trois semaines par an, deux fois par an.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# nom -> (zone, ouverture, fermeture) en heure LOCALE de la place
SESSIONS: dict[str, tuple[str, tuple[int, int], tuple[int, int]]] = {
    "session_londres":   ("Europe/London",    (8, 0),  (16, 30)),
    "killzone_londres":  ("Europe/London",    (8, 0),  (11, 0)),
    "session_newyork":   ("America/New_York", (9, 30), (16, 0)),
    "killzone_newyork":  ("America/New_York", (9, 30), (12, 30)),
    "session_asie":      ("Asia/Tokyo",       (9, 0),  (15, 0)),
}

# Les trois ouvertures qui fabriquent un « range d'open ». Les killzones sont
# des SOUS-fenetres des memes sessions : les compter aussi ferait deux fois le
# meme range sous deux noms.
OUVERTURES = ("session_londres", "session_newyork", "session_asie")


def derniere_ouverture(quand: datetime) -> datetime | None:
    """La derniere ouverture de session **encore en cours** avant `quand`.

    Rend `None` hors de toute session — et c'est un resultat, pas un echec :
    il n'y a alors pas de range d'open a casser.

    ⚠️ Rend `None` aussi si la base de fuseaux est absente. Retomber sur un
    UTC fixe mesurerait une autre fenetre sous le meme nom.
    """
    try:
        from zoneinfo import ZoneInfo
    except Exception as e:  # noqa: BLE001 — base tz absente
        logger.warning("sessions_marche: zoneinfo indisponible (%s)", e)
        return None

    candidates: list[datetime] = []
    for nom in OUVERTURES:
        zone, (h, m), (hf, mf) = SESSIONS[nom]
        try:
            tz = ZoneInfo(zone)
        except Exception as e:  # noqa: BLE001
            logger.warning("sessions_marche: zone %s indisponible (%s)", zone, e)
            continue
        local = quand.astimezone(tz)
        # la veille aussi : une session ouverte hier peut courir encore.
        for jours in (0, 1):
            jour = (local - timedelta(days=jours)).date()
            ouverture = datetime(jour.year, jour.month, jour.day, h, m, tzinfo=tz)
            fermeture = datetime(jour.year, jour.month, jour.day, hf, mf, tzinfo=tz)
            if ouverture <= local < fermeture:
                candidates.append(ouverture.astimezone(quand.tzinfo or tz))
    return max(candidates) if candidates else None
