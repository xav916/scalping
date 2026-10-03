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
# ⛔ Les noms viennent du CODE APPELANT, pas de ce qui me parait lisible. Releve
# en production 40 s apres le 1er deploiement : << echelle '1day' inconnue du
# pont — rien >>. Ma table disait `1d`, le radar dit `1day` : les bougies
# journalieres rendaient une liste vide, en silence.
# ⚠️ Pas de `1week` : le pont ne connait que M1,M5,M15,M30,H1,H4,D1. Le
# declarer enverrait un timeframe refuse par un 400. Sans consequence — `1week`
# n'existe que dans la table Binance (crypto).
_ECHELLES = {"1min": "M1", "5min": "M5", "15min": "M15", "30min": "M30",
             "1h": "H1", "60min": "H1", "4h": "H4",
             "1day": "D1", "1d": "D1"}


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
_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30,
            "H1": 60, "H4": 240, "D1": 1440}

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


def sur_la_grille_instant(t, minutes: int):
    """Un instant ramene au point de grille le PLUS PROCHE.

    ⛔ POURQUOI PAR BOUGIE, et non par un residu median sur la serie. Mesure
    du 2026-10-03 sur la fenetre de 412 jours du banc : apres correction par
    une mediane globale, il restait DEUX regimes de residu — 0 s sur 41 026
    bougies et 240 s sur 38 448. Chaque page de 14 jours est lue avec le
    decalage de SON instant, et ce decalage derive ; une mediane globale est
    donc le mauvais outil. Exactement 2 760 horodatages changeaient d'un
    chargement a l'autre : la taille d'une page, pas du bruit.

    🔑 L'arrondi par bougie est local : il ne depend d'aucune autre bougie, ne
    peut pas basculer quand la mediane bouge de 3 secondes, et traite les deux
    regimes correctement d'un coup.

    ⚠️ Il reste une limite, mesuree et bornee : les etiquettes valent
    `vrai - delta` ou `vrai` est un multiple de l'echelle, donc le residu ne
    rend `delta` que modulo l'echelle. Un residu au-dela de la demi-periode
    (ici 150 s) decale toute la serie d'un cran entier par rapport aux bougies
    natives du courtier. La STRUCTURE est intacte — c'est ce dont l'agregation
    a besoin — mais la position absolue peut etre decalee de 5 minutes.
    """
    from datetime import timedelta
    periode = minutes * 60
    if periode <= 0:
        return t
    secondes = t.minute * 60 + t.second + t.microsecond / 1e6
    residu = secondes % periode
    delta = -residu if residu * 2 < periode else (periode - residu)
    return (t + timedelta(seconds=delta)).replace(microsecond=0)


def residu_de_grille(instants: list, minutes: int) -> float:
    """De combien de secondes toute la serie est-elle decalee de sa grille ?

    ⚠️ Partagee avec `scripts/banc_wti_bougies_courtier.py`, qui travaille sur
    les dicts bruts du pont. Recopier cette regle la ferait deriver du banc, et
    le banc mesurerait alors un instrument que la production ne trade pas.

    ⛔ La MEDIANE, pas la moyenne : une etiquette abimee ne doit pas tirer la
    correction de toute la serie.
    """
    if len(instants) < 3 or minutes <= 0:
        return 0.0
    periode = minutes * 60
    residus = sorted(
        (t.minute * 60 + t.second + t.microsecond / 1e6) % periode
        for t in instants)
    return residus[len(residus) // 2]


def _sur_la_grille(bougies: list, minutes: int) -> list:
    """Remet les etiquettes du pont sur la grille de l'echelle.

    ⛔ MESURE DU 2026-10-03, deux appels identiques d'affilee au pont reel :

        page 1 : decalage_serveur_sec = -26905   1re bougie 08:28:25
        page 2 : decalage_serveur_sec = -26906   1re bougie 08:28:26

    Les OHLC sont IDENTIQUES ; seules les etiquettes bougent, d'une seconde par
    appel. `_decalage_serveur_sec()` du pont se mesure sur le DERNIER TICK, et
    marche ferme, le tick vieillit : le decalage derive sans fin.

    🔑 Deux degats, et le second est en production :
      1. la mesure n'est pas reproductible — le banc WTI a rendu une cellule
         RETENUE a R=+0,4798 au 1er passage et la MEME a R=-0,1530 au second ;
      2. `echelle_agregee` range ses tranches par `minute // pas * pas`. Avec
         des etiquettes a :28, :33, :38 au lieu de :30, :35, :40, une bougie de
         15 min est batie sur les MAUVAISES trois, et sa composition change
         quand le decalage franchit une borne.

    Calibration qui tranche : regrouper les M5 en triplets consecutifs depuis
    le debut de la serie reproduit **246/246** des M15 NATIVES du courtier
    (100 %) ; aucun autre depart n'en reproduit une seule. Les prix et leur
    ordre sont donc justes — il n'y a que l'etiquette a remettre en place.

    ⚠️ La correction est UNIFORME : toutes les bougies partagent le meme
    decalage, donc on retire le meme residu a toutes. Rien n'est reordonne,
    aucun prix ne change de bougie.

    ⚠️ Ce qu'elle ne peut PAS faire : retrouver la phase absolue dans l'heure.
    Les etiquettes valent `vrai - delta` et `vrai` est un multiple de l'echelle,
    donc le residu ne rend `delta` que modulo l'echelle. La serie peut donc
    rester decalee d'un cran entier par rapport aux bougies natives du
    courtier. C'est mesure, borne, et stable — contrairement a avant.
    """
    if len(bougies) < 3 or minutes <= 0:
        return bougies
    corrige = []
    for c in bougies:
        t = sur_la_grille_instant(c.timestamp, minutes)
        corrige.append(c.model_copy(update={"timestamp": t})
                       if hasattr(c, "model_copy") else c)
    return corrige


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
    # ⛔ Les etiquettes du pont derivent d'une seconde par appel et ne sont pas
    # sur la grille. Voir `_sur_la_grille` : sans ca, ni la production ni le
    # banc ne sont reproductibles.
    bougies = _sur_la_grille(bougies, _MINUTES.get(timeframe, 0))
    if not bougies:
        logger.info("bougies_du_pont: %s %s — aucune bougie exploitable",
                    pair, timeframe)
    return bougies[-outputsize:] if outputsize else bougies


def _lire_tick(dest, pair: str) -> dict | None:
    """`GET /tick/{pair}`, ou `None`. ⚠️ Le pont resout le symbole lui-meme."""
    base = (getattr(dest, "bridge_url", "") or "").rstrip("/")
    if not base:
        return None
    entetes = {}
    if getattr(dest, "bridge_api_key", None):
        entetes["X-API-Key"] = dest.bridge_api_key
    url = f"{base}/tick/{urllib.parse.quote(str(pair), safe='')}"
    try:
        with urllib.request.urlopen(
                urllib.request.Request(url, headers=entetes), timeout=10) as r:
            return json.load(r)
    except Exception as e:  # noqa: BLE001
        logger.info("bougies_du_pont: /tick %s illisible (%s)", pair, e)
        return None


def prix_courant(pair: str) -> float | None:
    """Le prix courant CHEZ LE COURTIER — le milieu du tick. `None` si inconnu.

    ⛔ `fetch_current_price` est un chemin SEPARE de `fetch_candles`, et il est
    reste sur Twelve Data apres le premier correctif. Consequence mesurable :
    `backtest_service` juge les trades fantomes OPEN avec ce prix. L'entree
    venant des bougies du courtier (93,47) et le juge de Twelve Data (90,31),
    un ecart de 3,4 % ECRASE n'importe quel stop — chaque trade fantome WTI
    aurait ete declare touche a tort, et le journal fantome empoisonne en
    silence.

    🔑 Une paire a moitie routee est PIRE qu'une paire non routee : les deux
    chemins se contredisent, et rien ne le dit.
    """
    dest = _destination()
    if dest is None:
        return None
    t = _lire_tick(dest, pair)
    if not isinstance(t, dict):
        return None
    try:
        bid, ask = float(t.get("bid") or 0), float(t.get("ask") or 0)
    except (TypeError, ValueError):
        return None
    if bid <= 0 or ask <= 0:
        return None
    return (bid + ask) / 2.0
