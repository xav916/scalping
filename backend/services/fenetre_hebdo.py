"""Fenêtre hebdomadaire de trading : lundi 00h05 → vendredi 22h40, HEURE DE PARIS.

Demande de Xavier le 2026-10-09 : « je veux des horaires hebdomadaires, de
00h05 lundi à 22h40 vendredi ».

## 🔑 POURQUOI PARIS, ET PAS UTC

Les séances du courtier sont modélisées en **UTC** dans `market_hours` : les
métaux ouvrent **dimanche 22:00 UTC** et ferment **vendredi 21:00 UTC**. Ses
horaires s'y superposent exactement s'ils sont lus en heure de Paris :

    lundi    00h05 Paris = dimanche 22h05 UTC  ->   5 min APRES l'ouverture
    vendredi 22h40 Paris = vendredi 20h40 UTC  ->  20 min AVANT la cloture

⇒ Sa fenêtre est un **sous-ensemble strict** de la séance, avec une marge de
chaque côté. Lue en UTC elle n'aurait eu aucun sens : elle aurait commencé 2 h
après l'ouverture et fini 20 min *après* la clôture.

## ⛔ ET PARIS N'EST PAS UN DÉCALAGE FIXE

UTC+2 en été, UTC+1 en hiver. Mesuré dans le conteneur : décalage de 2 h le
24 octobre 2026, de 1 h le 26. Coder « UTC+2 » ferait glisser la fenêtre d'une
heure fin octobre, **en silence** — exactement le genre de dérive que ce dépôt a
déjà payée avec le filtre « du jour » du 07/10, qui comparait une date LOCALE à
des horodatages UTC.

## Les bornes

- **début INCLUSIF** : à 00h05:00 pile, on trade ;
- **fin EXCLUSIVE** : à 22h40:00 pile, on ne trade plus. « De 00h05 à 22h40 »
  décrit une fenêtre qui *se termine* à 22h40.

## ⚠️ Cette porte s'AJOUTE, elle ne remplace rien

`market_hours` continue de refuser hors séance du courtier, et toutes les
autres portes gardent leur mot à dire. Une fenêtre plus large que la séance
n'ouvrirait donc rien de nouveau.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

MOTIF = "hors_fenetre_hebdo"

PARIS = ZoneInfo("Europe/Paris")

# ⛔ La fenêtre DÉCLARÉE par Xavier. Elle sert aussi de repli : ni fenêtre vide
# (qui bloquerait tout en silence), ni fenêtre totale (qui ouvrirait le
# week-end).
FENETRE_DECLAREE = ((0, 0, 5), (4, 22, 40))

_JOURS = {"lun": 0, "mar": 1, "mer": 2, "jeu": 3, "ven": 4, "sam": 5, "dim": 6}
_JOURS_FR = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi",
             "dimanche")


def armee() -> bool:
    """⚠️ Un interrupteur, pour revenir en arrière sans déploiement."""
    return os.getenv("FENETRE_HEBDO_ENABLED", "true").strip().lower() not in (
        "0", "false", "off", "no")


def _lire(brut: str | None) -> tuple[int, int, int] | None:
    """`"ven 22:40"` → `(4, 22, 40)`, ou ``None`` si illisible."""
    if not brut:
        return None
    bouts = brut.strip().lower().split()
    if len(bouts) != 2:
        return None
    jour, heure = bouts
    if jour not in _JOURS or ":" not in heure:
        return None
    try:
        h, m = heure.split(":")
        h, m = int(h), int(m)
    except (TypeError, ValueError):
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return (_JOURS[jour], h, m)


def fenetre() -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """``((jour, h, m) début, (jour, h, m) fin)``, en heure de Paris.

    ⛔ Un réglage illisible retombe sur la fenêtre DÉCLARÉE, jamais sur une
    fenêtre vide ni totale — même choix que `ECHELLE_STOP_OR_PALIERS`.
    """
    debut = _lire(os.getenv("FENETRE_HEBDO_DEBUT"))
    fin = _lire(os.getenv("FENETRE_HEBDO_FIN"))
    if debut is None or fin is None:
        if os.getenv("FENETRE_HEBDO_DEBUT") or os.getenv("FENETRE_HEBDO_FIN"):
            logger.warning(
                "FENETRE_HEBDO_* illisible (debut=%r fin=%r) — repli sur la "
                "fenetre declaree %s",
                os.getenv("FENETRE_HEBDO_DEBUT"), os.getenv("FENETRE_HEBDO_FIN"),
                FENETRE_DECLAREE)
        return FENETRE_DECLAREE
    return (debut, fin)


def _en_minutes(jour: int, h: int, m: int) -> int:
    """Position dans la semaine, en minutes depuis lundi 00:00."""
    return jour * 24 * 60 + h * 60 + m


def _a_paris(maintenant: datetime | None) -> datetime:
    """L'instant, converti en heure de Paris.

    ⚠️ Un `datetime` NAÏF est lu comme de l'**UTC**, pas comme l'heure locale de
    la machine : sans quoi la décision dépendrait du poste. C'est le défaut du
    filtre « du jour » du 07/10, qui était faux entre minuit et 2 h à Paris.
    """
    n = maintenant or datetime.now(timezone.utc)
    if n.tzinfo is None:
        n = n.replace(tzinfo=timezone.utc)
    return n.astimezone(PARIS)


def ouverte(maintenant: datetime | None = None) -> bool:
    """La fenêtre hebdomadaire est-elle ouverte à cet instant ?

    🔑 La comparaison se fait sur la position dans la SEMAINE, en heure de
    Paris : début inclusif, fin exclusive.
    """
    if not armee():
        return True
    try:
        (jd, hd, md), (jf, hf, mf) = fenetre()
        n = _a_paris(maintenant)
        ici = _en_minutes(n.weekday(), n.hour, n.minute)
        return _en_minutes(jd, hd, md) <= ici < _en_minutes(jf, hf, mf)
    except Exception as e:  # noqa: BLE001
        # ⛔ Une porte qui LÈVE ne doit pas arrêter le trading : le reste des
        # gardes tient, et `market_hours` refuse déjà hors séance. Mais on le
        # DIT — une porte muette qui laisse passer est le pire des deux.
        logger.warning("fenetre_hebdo: calcul impossible (%s: %s) — porte "
                       "passee, les autres gardes tiennent", type(e).__name__, e)
        return True


def detail(maintenant: datetime | None = None) -> str:
    """Le motif, lisible : la fenêtre ET l'heure de Paris du moment.

    🔑 Un refus qui ne dit pas POURQUOI oblige à relire le code.
    """
    (jd, hd, md), (jf, hf, mf) = fenetre()
    n = _a_paris(maintenant)
    return (f"hors fenetre hebdomadaire : {_JOURS_FR[jd]} {hd:02d}:{md:02d} → "
            f"{_JOURS_FR[jf]} {hf:02d}:{mf:02d} (heure de Paris). "
            f"Il est {_JOURS_FR[n.weekday()]} {n.hour:02d}:{n.minute:02d} a "
            f"Paris.")
