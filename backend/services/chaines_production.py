"""Detecter les chaines dans le radar — avec le MEME code que le laboratoire.

⛔ **Le defaut que ce module previent.** Les 18 chaines n'existaient que dans
le rejeu du laboratoire. Les porter en production en REECRIVANT leur logique
aurait cree deux implementations de la meme regle, et ce depot sait ce que ca
coute : `/opt/scalping/scripts` divergent du depot une journee entiere, deux
tables d'heures de session, deux plafonds de chaines dans deux fichiers.

🔑 **Il n'y a donc qu'une implementation.** Ce module ne fait que traduire :
il convertit les bougies du radar au format que le laboratoire parle deja,
puis appelle **son** code — memes declarations, memes predicats, meme fenetre
de sequence. Un test compare les deux chemins sur les memes bougies et exige
le meme resultat.

## ⛔ Ce qui ne change PAS

`detect_patterns` continue de recevoir exactement `CANDLE_COUNT` bougies. Lui
en passer davantage deplacerait des signaux qui tradent de l'argent reel :
`_detect_poc_return` calcule son profil sur **toute** la liste recue, pas sur
une fenetre fixe. La serie longue ne sert qu'ici.

## ⚠️ Une chaine n'est pas un `PatternType`, et ne doit jamais le devenir

La liste blanche du pont est fail-closed sur `PatternType`. Une chaine promue
en `PatternType` pourrait partir sans passer par son propre registre. Elle
garde donc son nom `chaine:<nom>`, et un test le verifie.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from backend.models.schemas import Candle

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChaineDetectee:
    """Une chaine vue sur la DERNIERE bougie."""
    pattern: str            # `chaine:<nom>`
    sens: str               # buy / sell
    indice: int             # position dans la serie longue
    setup: object           # le setup synthetique du laboratoire


def _au_format_labo(candles: list[Candle]) -> list[dict]:
    """Traduit, ne recalcule rien. `tv` porte le volume, comme le pont."""
    return [{"t": c.timestamp, "o": float(c.open), "h": float(c.high),
             "l": float(c.low), "c": float(c.close),
             "tv": float(c.volume or 0.0)} for c in candles]


def detecter_chaines(candles: list[Candle], pair: str) -> list[ChaineDetectee]:
    """Les chaines qui se declenchent sur la DERNIERE bougie.

    ⚠️ Rend `[]` plutot que de lever : une chaine indisponible ne doit pas
    couter le cycle de detection des motifs simples.
    """
    from backend.services import laboratoire_or as labo

    besoin = labo.FENETRE + labo.FENETRE_SEQUENCE + 1
    if len(candles) < besoin:
        # Fail-closed : mieux vaut aucune chaine qu'une chaine amputee de ses
        # maillons — elle porterait le meme nom en mesurant autre chose.
        return []
    # ⛔ DETECTER PAR L'ABSENCE. Une serie de 300 bougies laisse passer seize
    # chaines sur dix-huit et rend les deux chaines de BIAIS muettes : sans ce
    # cri, leur silence ressemblerait a « aucun signal ». C'est exactement la
    # forme de defaut que ce depot paie en boucle.
    if len(candles) <= labo.BIAIS_FENETRE:
        logger.warning(
            "chaines[%s] : %d bougies — les chaines de BIAIS (il en faut %d) "
            "resteront muettes ce cycle", pair, len(candles),
            labo.BIAIS_FENETRE + 1)
    try:
        bougies = _au_format_labo(candles)
        dernier = len(bougies)
        # ⚠️ On ne releve que la QUEUE : un releve complet demanderait un
        # passage de detection par bougie, soit des centaines par cycle.
        depuis = dernier - labo.FENETRE_SEQUENCE - 1
        releve = labo.detections(bougies, pair, depuis=depuis)
        sortie, _ = labo.chaines_detectees(releve, bougies)
    except Exception as e:  # noqa: BLE001
        logger.warning("chaines[%s] : detection impossible (%s)", pair, e)
        return []

    out: list[ChaineDetectee] = []
    for s in sortie.get(dernier, ()):
        out.append(ChaineDetectee(pattern=labo._nom_motif(s), sens=labo._sens(s),
                                  indice=dernier, setup=s))
    if out:
        logger.info("chaines[%s] : %s", pair, [c.pattern for c in out])
    return out


# ─── La serie longue ────────────────────────────────────────────────
#
# ⛔ PAS `price_service.fetch_candles`. Son cache est indexe sur
# `(paire, intervalle)`, SANS la taille : demander 480 bougies d'or par ce
# chemin en servirait 480 a tous les autres consommateurs pendant le TTL —
# dont `detect_patterns`, dont `_detect_poc_return` calcule son profil sur
# TOUTE la liste recue. Des signaux qui tradent de l'argent reel auraient
# bouge sans qu'aucun test ne le dise.
#
# 🔑 La serie vient du PONT, pour deux raisons qui vont dans le meme sens :
#   - il sert l'historique gratuitement, la ou le quota Twelve Data a deja
#     sature (954 refus en 429) ;
#   - c'est la source que le LABORATOIRE mesure. Production et laboratoire
#     voient donc les memes prix, ce qui est le point meme de « eprouver les
#     methodes du labo ».
#
# ⚠️ CONSEQUENCE ASSUMEE : dans un meme cycle, les motifs simples sont
# detectes sur Twelve Data et les chaines sur le pont. Les deux sources
# divergent legerement. C'est un choix, pas un oubli — et il aligne la chaine
# sur ce qui l'a mesuree plutot que sur ce qui l'entoure.

# 400 pour le biais de l'echelle superieure, + la fenetre de detection et la
# fenetre de sequence. En dessous, les chaines de biais se tairaient — en
# silence, ce que ce module existe pour empecher.
CHAINES_BOUGIES = 480

# ⛔ L'OR SEULEMENT (choix de Xavier, 2026-09-14). Etendre aux 20 instruments
# multiplierait par vingt le cout par cycle pour des chaines qu'on ne cherche
# pas encore a eprouver ailleurs.
CHAINES_PAIRES: frozenset[str] = frozenset({"XAU/USD"})


def _bougies_du_pont(pair: str, combien: int) -> list[Candle]:
    """Les `combien` dernieres bougies 5 min, lues chez le courtier MESURE."""
    import json
    import os
    import urllib.parse
    import urllib.request
    from datetime import datetime, timedelta, timezone

    from backend.services.destinations_registry import DESTINATIONS
    from backend.services.reglage_or import DESTINATION_MESUREE

    d = DESTINATIONS[DESTINATION_MESUREE]
    base = os.environ[d.url_env].rstrip("/")
    entetes = {getattr(d, "key_header", None) or "X-API-Key": os.environ[d.key_env]}
    fin = datetime.now(timezone.utc)
    # ⛔ EN JOURS, PAS EN MINUTES (corrige le 2026-09-14, mesure en
    # production). `5 min x 480` donne 40 h d'horloge — mais le marche ferme le
    # week-end et une heure par jour. Premiere mesure reelle : 276 bougies
    # recues au lieu de 480, donc les deux chaines de biais muettes EN
    # SILENCE. Sept jours couvrent largement 480 bougies de marche ouvert, et
    # le pont sert l'historique gratuitement.
    debut = fin - timedelta(days=7)
    q = urllib.parse.urlencode({
        "pair": pair.replace("/", ""), "timeframe": "M5",
        "from": debut.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to": fin.strftime("%Y-%m-%dT%H:%M:%SZ")})
    with urllib.request.urlopen(urllib.request.Request(
            base + "/rates?" + q, headers=entetes), timeout=30) as r:
        brut = json.load(r).get("bougies") or []
    vus, propre = set(), []
    for x in brut:
        if x["t"] not in vus:
            vus.add(x["t"])
            propre.append(x)
    propre.sort(key=lambda x: x["t"])
    from datetime import datetime as _dt
    return [Candle(
        timestamp=_dt.fromisoformat(str(x["t"]).replace("Z", "+00:00")),
        open=float(x["o"]), high=float(x["h"]), low=float(x["l"]),
        close=float(x["c"]), volume=float(x.get("tv") or 0.0))
        for x in propre[-combien:]]


def chaines_de_la_paire(pair: str) -> list[ChaineDetectee]:
    """Les chaines de cette paire, maintenant. `[]` si elle n'est pas suivie.

    ⚠️ **Fail-soft.** Une chaine indisponible ne doit pas couter la detection
    des motifs simples — eux tradent deja.
    """
    if pair not in CHAINES_PAIRES:
        return []
    try:
        candles = _bougies_du_pont(pair, CHAINES_BOUGIES)
    except Exception as e:  # noqa: BLE001
        logger.warning("chaines[%s] : serie longue indisponible (%s)", pair, e)
        return []
    if len(candles) < CHAINES_BOUGIES // 2:
        logger.warning("chaines[%s] : %d bougies seulement — ignore",
                       pair, len(candles))
        return []
    return detecter_chaines(candles, pair)
