#!/usr/bin/env python3
"""Le coeur partage des rattrapages (paliers 1 et 2).

Extrait de `rattrapage_crypto.py` le 2026-10-26 au moment d'ecrire le palier 2
forex : les deux rattrapages ne different que par la SOURCE de bougies. Tout le
reste -- selection de la file, chargement en bloc, service des fenetres par
dichotomie, boucle de resolution -- est identique, et le dupliquer aurait
garanti que l'un des deux derive de l'autre.

⛔ CE QUI EST NON NEGOCIABLE ICI, et pourquoi :

- On passe par `reconcile_pending_setups`, le MEME chemin de calcul d'issue que
  la production. Une seconde implementation de la regle de sortie produirait
  des issues subtilement differentes de celles vecues, et plus personne ne
  saurait lesquelles comparer.
- On passe TOUJOURS un filtre de paires. La file est servie
  `ORDER BY bar_timestamp`, donc un rattrapage non filtre resoudrait au passage
  des setups d'un autre instrument avec les bougies de celui-ci.
- On ecrit TOUJOURS avec `marque_rattrapage=True`. Sans le drapeau
  `resolved_backfill`, la donnee rattrapee deviendrait indistinguable de la
  donnee vecue et aucun banc ne pourrait jamais mesurer AVEC et SANS.
- Une paire dont la source ne rend AUCUNE bougie n'est pas servable : ses
  setups restent en file, **non marques**. Une source muette ne prouve pas
  qu'une donnee est irrecuperable -- c'est la lecon du `NO_DATA` du matin.
"""
from __future__ import annotations

import bisect
import logging
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone

from backend.models.schemas import Candle
from backend.services import shadow_reconciliation as recon
from backend.services.shadow_v2_core_long import DB_PATH

logger = logging.getLogger("rattrapage")

# Marge avant la plus ancienne barre et apres la plus recente : la fenetre de
# resolution court APRES la barre, et une bougie juste avant sert de bord.
MARGE_AVANT = timedelta(hours=6)
MARGE_APRES = timedelta(hours=120)


def date_utc(s: str) -> datetime:
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def paires_en_file(filtre, db_path=None) -> dict[str, tuple[datetime, datetime]]:
    """Les paires encore en file que `filtre(paire)` accepte, avec leur plage.

    `filtre` est la seule difference entre les paliers : `is_crypto_pair` pour
    Binance, « ni crypto ni pont » pour Twelve Data.
    """
    with sqlite3.connect(f"file:{db_path or DB_PATH}?mode=ro", uri=True) as c:
        lignes = c.execute(
            "SELECT pair, MIN(bar_timestamp), MAX(bar_timestamp), COUNT(*)"
            "  FROM shadow_setups WHERE outcome IS NULL"
            " GROUP BY pair ORDER BY COUNT(*) DESC"
        ).fetchall()
    retenues: dict[str, tuple[datetime, datetime]] = {}
    for paire, mn, mx, n in lignes:
        if not filtre(paire):
            continue
        retenues[paire] = (date_utc(mn), date_utc(mx))
        logger.info(f"  retenue {paire:10s} {n:6d} en file  {mn[:10]} -> {mx[:10]}")
    return retenues


def fabrique_source(blocs: dict[str, list[Candle]]):
    """Rend une `fetch_5min_fn` qui SERT depuis la memoire, sans requete.

    🔑 Recherche dichotomique et non filtre lineaire : appelee une fois par
    setup sur ~20 000 bougies par paire, un filtre complet couterait des
    milliards de comparaisons pour rien.
    """
    index = {p: [c.timestamp for c in cs] for p, cs in blocs.items()}

    async def source(pair: str, start: datetime, end: datetime) -> list[Candle]:
        cs = blocs.get(pair)
        if not cs:
            return []
        ts = index[pair]
        return cs[bisect.bisect_left(ts, start):bisect.bisect_right(ts, end)]

    return source


async def charge_les_blocs(paires: dict[str, tuple[datetime, datetime]],
                           chargeur) -> dict[str, list[Candle]]:
    """Charge, une fois par paire, tout l'intervalle utile.

    `chargeur(paire, debut, fin)` est la source du palier.
    """
    blocs: dict[str, list[Candle]] = {}
    for paire, (mn, mx) in paires.items():
        debut, fin = mn - MARGE_AVANT, mx + MARGE_APRES
        bougies = await chargeur(paire, debut, fin)
        blocs[paire] = bougies
        if not bougies:
            logger.warning(
                f"  {paire:10s} AUCUNE bougie pour {debut:%Y-%m-%d}->{fin:%Y-%m-%d}"
                f" : cette paire ne sera PAS rattrapee (setups laisses en file,"
                f" NON marques)")
            continue
        logger.info(
            f"  {paire:10s} {len(bougies):6d} bougies,"
            f" {bougies[0].timestamp:%Y-%m-%d} -> {bougies[-1].timestamp:%Y-%m-%d}"
            f" ({(bougies[-1].timestamp - bougies[0].timestamp).days} j)")
    return blocs


def etat(db_path=None) -> tuple[int, Counter]:
    with sqlite3.connect(f"file:{db_path or DB_PATH}?mode=ro", uri=True) as c:
        n = c.execute(
            "SELECT COUNT(*) FROM shadow_setups WHERE outcome IS NULL"
        ).fetchone()[0]
        issues = Counter(dict(c.execute(
            "SELECT outcome, COUNT(*) FROM shadow_setups"
            " WHERE resolved_backfill = 1 GROUP BY outcome").fetchall()))
    return n, issues


async def resout(blocs: dict[str, list[Candle]], limite: int | None = None) -> int:
    """Resout la file des paires servables, par lots, jusqu'a stagnation."""
    servables = [p for p, cs in blocs.items() if cs]
    if not servables:
        logger.error("aucune bougie obtenue : on n'ecrit RIEN")
        return 0

    source = fabrique_source(blocs)
    faits = 0
    sterile = 0
    while limite is None or faits < limite:
        lot = 100 if limite is None else min(100, limite - faits)
        stats = await recon.reconcile_pending_setups(
            max_per_run=lot,
            fetch_5min_fn=source,
            paires=servables,
            marque_rattrapage=True,
        )
        avance = stats["resolved"]
        faits += avance
        if avance == 0:
            sterile += 1
            # Deux passages sans une resolution : la file ne bouge plus (vide,
            # ou tetes irresolubles). On ne tourne pas en rond.
            if sterile >= 2:
                logger.info("deux passages sans avancee : arret")
                break
        else:
            sterile = 0
            logger.info(f"  +{avance} resolus (total {faits}),"
                        f" file {stats['pending_remaining']}")
    return faits
