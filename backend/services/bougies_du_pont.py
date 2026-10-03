"""Bougies lues CHEZ LE COURTIER, pour les paires ou Twelve Data ment.

⛔ **Le constat du 2026-10-03.** Dernier trade WTI le **4 aout**, et 13 078
refus `price_divergence` en 7 jours (seuil 0,5 %). Mesure sur tout l'univers du
reel, le meme soir :

    WTI/USD   XTIUSD   radar  90,3076   courtier  93,4800   ecart 3,394 %  <- SEUL
    UNI/USD            radar   9,2370   courtier   9,2235   ecart 0,146 %  <- le 2e
    les 22 autres                                           ecart <= 0,07 %

Le WTI est seul, et de 23 fois. Un ecart constant de cette taille n'est pas de
la latence : ce sont **deux instruments differents**. Le << WTI/USD >> de Twelve
Data n'est pas le `XTIUSD` d'IC Markets, et l'ecart GRANDIT — 1,6 a 1,9 % le
29/08, 3,4 % aujourd'hui.

🔑 Le radar DECIDE sur un prix et le courtier EXECUTE sur un autre. Avec un stop
WTI de l'ordre de 1 %, cela fait trois stops d'erreur avant que le marche ait
bouge. La porte a raison de refuser ; c'est la SOURCE qu'il faut corriger.

## ⚠️ Une source unique ne peut pas servir les deux destinations

    IC Markets  XTIUSD     93,4800
    Pepperstone SpotCrude  94,1770    <- 0,75 % entre les deux COURTIERS

0,75 % depasse le seuil de 0,5 %. On source donc depuis le pont du **reel** :
le WTI y passe, et reste refuse sur la demo. Aujourd'hui il est refuse PARTOUT,
donc c'est strictement mieux — et le refus de la demo devient honnete, puisqu'il
viendra d'un desaccord reel entre son courtier et la source.

## ⛔ Aucun repli sur Twelve Data

Un pont injoignable rend une liste VIDE : la paire est absente du cycle. Retomber
sur Twelve Data reintroduirait **en silence** la divergence qu'on corrige, et la
porte refuserait de toute facon — on aurait paye un appel reseau pour le meme
refus.

Precedent suivi : la crypto est deja routee vers Binance plutot que Twelve Data,
derriere un drapeau, pour la meme raison.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Paires dont les bougies viennent du pont. ⚠️ VIDE par defaut : sans reglage,
# rien ne change pour personne.
PAIRES_DU_PONT: frozenset[str] = frozenset(
    p.strip() for p in os.getenv("PAIRES_BOUGIES_PONT", "").split(",") if p.strip())

# La destination dont on lit les bougies. C'est celle qui TRADE la paire avec de
# l'argent reel : decider sur le prix d'un autre courtier n'aurait pas de sens.
DESTINATION = os.getenv("BOUGIES_PONT_DESTINATION", "admin_live")

# ⛔ Le radar dit `5min`, MT5 dit `M5`. Une traduction ratee rendrait des bougies
# d'une AUTRE echelle sans lever la moindre erreur.
_ECHELLES = {"5min": "M5", "15min": "M15", "30min": "M30",
             "1h": "H1", "60min": "H1", "4h": "H4", "1d": "D1"}


def paire_du_pont(pair: str) -> bool:
    """Cette paire decide-t-elle sur les bougies du courtier ?"""
    return str(pair) in PAIRES_DU_PONT


def _destination():
    """Le `BridgeConfig` dont on lit les bougies, ou `None`."""
    try:
        from backend.services.bridge_destinations import admin_destinations
        for d in admin_destinations():
            if (str(getattr(d, "destination_id", "")) == DESTINATION
                    and getattr(d, "bridge_url", "")):
                return d
    except Exception as e:  # noqa: BLE001
        logger.warning("bougies_du_pont: registre illisible (%s)", e)
    return None


# Duree d'une bougie, par echelle du pont. Sert a calculer la fenetre.
_MINUTES = {"M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}

# ⚠️ On demande TROIS fois la duree theorique, et au moins deux jours. Le
# marche ferme la nuit et le week-end : 50 bougies de 5 min couvrent 250
# minutes en theorie, mais peuvent enjamber 60 heures de fermeture. Demander
# trop peu rendrait silencieusement moins de bougies que le detecteur n'en
# attend — et `detect_patterns` travaillerait sur une fenetre tronquee sans
# qu'aucune erreur ne le dise.
_MARGE = 3
_PLANCHER_JOURS = 2


def _fenetre(timeframe: str, combien: int, maintenant=None):
    """`(debut, fin)` a demander au pont pour obtenir `combien` bougies."""
    from datetime import timedelta
    fin = maintenant or datetime.now(timezone.utc)
    minutes = _MINUTES.get(timeframe)
    if minutes is None or combien <= 0:
        return None, None
    duree = timedelta(minutes=minutes * combien * _MARGE)
    if duree < timedelta(days=_PLANCHER_JOURS):
        duree = timedelta(days=_PLANCHER_JOURS)
    return fin - duree, fin


def _lire_rates(dest, symbole: str, timeframe: str, combien: int) -> dict | None:
    """`GET /rates`, ou `None` si la lecture rate.

    ⛔ Le pont exige `from` et `to` en ISO 8601 — il n'a PAS de parametre
    `count`. Lui en envoyer un rend un 400 << from et to requis >>, a chaque
    cycle, pour toujours.
    """
    base = (getattr(dest, "bridge_url", "") or "").rstrip("/")
    if not base:
        return None
    debut, fin = _fenetre(timeframe, combien)
    if debut is None:
        return None
    entetes = {}
    if getattr(dest, "bridge_api_key", None):
        entetes["X-API-Key"] = dest.bridge_api_key
    q = urllib.parse.urlencode({
        "pair": symbole, "timeframe": timeframe,
        "from": debut.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to": fin.strftime("%Y-%m-%dT%H:%M:%SZ")})
    try:
        with urllib.request.urlopen(
                urllib.request.Request(f"{base}/rates?{q}", headers=entetes),
                timeout=15) as r:
            return json.load(r)
    except Exception as e:  # noqa: BLE001 — toute panne = on ne sait pas
        logger.info("bougies_du_pont: /rates %s %s illisible (%s)",
                    symbole, timeframe, e)
        return None


def _en_candle(x):
    from backend.models.schemas import Candle
    d = x["t"]
    if not isinstance(d, datetime):
        d = datetime.fromisoformat(str(d).replace("Z", "+00:00"))
    if not d.tzinfo:
        d = d.replace(tzinfo=timezone.utc)
    return Candle(timestamp=d, open=float(x["o"]), high=float(x["h"]),
                  low=float(x["l"]), close=float(x["c"]),
                  volume=float(x.get("tv") or 0.0))


async def fetch_candles(pair: str, interval: str, outputsize: int) -> list:
    """Les bougies du courtier pour cette paire. Liste VIDE si indecidable.

    ⛔ Vide, jamais un repli : voir l'entete du module.
    """
    timeframe = _ECHELLES.get(str(interval))
    if timeframe is None:
        logger.info("bougies_du_pont: echelle %r inconnue du pont — rien", interval)
        return []
    dest = _destination()
    if dest is None:
        logger.warning("bougies_du_pont: destination %r introuvable — %s absente "
                       "du cycle", DESTINATION, pair)
        return []
    from backend.services.mt5_bridge import _symbole_courtier_pour
    symbole = _symbole_courtier_pour(pair, dest)
    brut = _lire_rates(dest, symbole, timeframe, outputsize)
    if not isinstance(brut, dict):
        return []
    if brut.get("tronque"):
        # ⛔ Le pont coupe avec `brut[:5000]` : il garde les plus ANCIENNES.
        # Prendre la fin d'une reponse tronquee rendrait des bougies vieilles
        # de plusieurs semaines, et `detect_patterns` deciderait dessus sans
        # qu'une seule erreur ne remonte. On refuse plutot que de deviner.
        logger.warning("bougies_du_pont: %s %s TRONQUEE par le pont (n=%s) — "
                       "paire ecartee du cycle, fenetre trop large",
                       pair, timeframe, brut.get("n"))
        return []
    bougies = []
    for x in (brut.get("bougies") or []):
        try:
            bougies.append(_en_candle(x))
        except Exception:  # noqa: BLE001
            # ⚠️ Une bougie abimee est ECARTEE, elle n'emporte pas le cycle.
            continue
    bougies.sort(key=lambda c: c.timestamp)
    if not bougies:
        logger.info("bougies_du_pont: %s %s — aucune bougie exploitable",
                    pair, timeframe)
    return bougies[-outputsize:] if outputsize else bougies
