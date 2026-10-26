#!/usr/bin/env python3
"""Palier 1 du rattrapage : resout les setups CRYPTO restes en file.

CONTEXTE (2026-10-26). La reconciliation est morte le 2026-08-21 : 22 592
setups detectes, aucun resolu. La cause racine n'etait PAS une retention de
donnee epuisee -- c'etait que `fetch_candles` n'accepte qu'un `outputsize`,
jamais une plage de dates. Il demandait les 1 500 DERNIERES bougies puis
filtrait par fenetre : pour une barre d'aout, vide PAR CONSTRUCTION. Personne
n'avait jamais demande la bonne periode.

POURQUOI LA CRYPTO D'ABORD. 84 % de la file (19 003 lignes sur 22 592) est de
la crypto, et la crypto ne passe pas par Twelve Data : elle vient de l'API
publique Binance Futures, qui accepte `startTime`/`endTime` nativement,
gratuitement et sans quota. C'est le gros du trou et le cas le moins cher.

LA STRATEGIE, ET POURQUOI ELLE EST ECONOME. Chaque setup demande une fenetre
de ~96 h, soit ~1 150 bougies : une requete par setup serait 19 003 requetes
pour des fenetres qui se CHEVAUCHENT presque toutes. On charge donc une fois
par paire tout l'intervalle utile (~14 appels pagines par paire), on garde en
memoire, et on sert les fenetres par tranche. 7 paires => ~100 appels au lieu
de 19 003.

CE QU'IL NE FAUT PAS FAIRE, ET QUI EST GARDE ICI :

- ⛔ Ne pas recalculer l'issue soi-meme. On passe par
  `reconcile_pending_setups`, le MEME chemin que la production, en lui
  injectant seulement la source de bougies. Une seconde implementation de la
  regle de sortie produirait des issues subtilement differentes de celles
  vecues, et plus personne ne saurait lesquelles comparer.
- ⛔ Ne pas lancer sans filtre de paires. La file est servie
  `ORDER BY bar_timestamp`, donc un rattrapage non filtre resoudrait au
  passage des setups XAU avec des bougies BINANCE.
- ⛔ Ne pas ecrire sans etiquette. `resolved_backfill = 1` est ce qui permettra
  a un banc futur de mesurer AVEC et SANS la donnee rattrapee.

Usage :
    python -m scripts.rattrapage_crypto --essai           # ne rien ecrire
    python -m scripts.rattrapage_crypto --limite 200      # un lot borne
    python -m scripts.rattrapage_crypto                   # tout le reste
"""
from __future__ import annotations

import argparse
import asyncio
import bisect
import logging
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from backend.models.schemas import Candle  # noqa: E402
from backend.services import binance_klines_service as bks  # noqa: E402
from backend.services import shadow_reconciliation as recon  # noqa: E402
from backend.services.shadow_v2_core_long import DB_PATH, ensure_schema  # noqa: E402

logger = logging.getLogger("rattrapage_crypto")

# Marge avant la plus ancienne barre et apres la plus recente : la fenetre de
# resolution court APRES la barre (jusqu'a TIMEOUT_HOURS_MIN), et une bougie
# juste avant sert de bord. Large volontairement : les bougies sont gratuites.
MARGE_AVANT = timedelta(hours=6)
MARGE_APRES = timedelta(hours=120)


def paires_crypto_en_file(db_path=None) -> dict[str, tuple[datetime, datetime]]:
    """Les paires crypto encore en file, avec leur intervalle de barres.

    Ne rend QUE les paires que Binance sait coter : une paire absente de la
    table de correspondance n'a rien a faire dans un rattrapage Binance.
    """
    with sqlite3.connect(f"file:{db_path or DB_PATH}?mode=ro", uri=True) as c:
        lignes = c.execute(
            "SELECT pair, MIN(bar_timestamp), MAX(bar_timestamp), COUNT(*)"
            "  FROM shadow_setups WHERE outcome IS NULL"
            " GROUP BY pair ORDER BY COUNT(*) DESC"
        ).fetchall()
    retenues: dict[str, tuple[datetime, datetime]] = {}
    for paire, mn, mx, n in lignes:
        if not bks.is_crypto_pair(paire):
            logger.info(f"  (ignoree, pas sur Binance) {paire:10s} {n:6d} en file")
            continue
        retenues[paire] = (_date(mn), _date(mx))
        logger.info(f"  retenue {paire:10s} {n:6d} en file  {mn[:10]} -> {mx[:10]}")
    return retenues


def _date(s: str) -> datetime:
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def fabrique_source(blocs: dict[str, list[Candle]]):
    """Rend une fonction `fetch_5min_fn` qui SERT depuis la memoire.

    Signature identique a `fetch_5min_for_window` pour pouvoir etre injectee
    telle quelle. Aucune requete : les bougies ont deja ete chargees.

    🔑 Recherche dichotomique et non filtre lineaire : appelee une fois par
    setup sur ~20 000 bougies par paire, un filtre complet couterait 19 003 x
    20 000 comparaisons pour rien.
    """
    index = {p: [c.timestamp for c in cs] for p, cs in blocs.items()}

    async def source(pair: str, start: datetime, end: datetime) -> list[Candle]:
        cs = blocs.get(pair)
        if not cs:
            return []
        ts = index[pair]
        g = bisect.bisect_left(ts, start)
        d = bisect.bisect_right(ts, end)
        return cs[g:d]

    return source


async def charge_les_blocs(paires: dict[str, tuple[datetime, datetime]]
                           ) -> dict[str, list[Candle]]:
    """Charge, une fois par paire, tout l'intervalle utile."""
    blocs: dict[str, list[Candle]] = {}
    for paire, (mn, mx) in paires.items():
        debut, fin = mn - MARGE_AVANT, mx + MARGE_APRES
        bougies = await bks.fetch_klines_fenetre(paire, "5min", debut, fin)
        blocs[paire] = bougies
        if not bougies:
            logger.warning(
                f"  {paire:10s} AUCUNE bougie rendue pour"
                f" {debut:%Y-%m-%d}->{fin:%Y-%m-%d} : cette paire ne sera PAS"
                f" rattrapee (et ses setups restent en file, pas marques)")
            continue
        couverture = (bougies[-1].timestamp - bougies[0].timestamp).days
        logger.info(
            f"  {paire:10s} {len(bougies):6d} bougies,"
            f" {bougies[0].timestamp:%Y-%m-%d} -> {bougies[-1].timestamp:%Y-%m-%d}"
            f" ({couverture} j)")
    return blocs


def _etat(db_path=None) -> tuple[int, Counter]:
    with sqlite3.connect(f"file:{db_path or DB_PATH}?mode=ro", uri=True) as c:
        n = c.execute(
            "SELECT COUNT(*) FROM shadow_setups WHERE outcome IS NULL"
        ).fetchone()[0]
        issues = Counter(dict(c.execute(
            "SELECT outcome, COUNT(*) FROM shadow_setups"
            " WHERE resolved_backfill = 1 GROUP BY outcome").fetchall()))
    return n, issues


async def _principal(args) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ensure_schema()

    logger.info("=== la file, par paire")
    paires = paires_crypto_en_file()
    if not paires:
        logger.info("aucune paire crypto en file : rien a faire")
        return 0

    logger.info("=== chargement des bougies (Binance, fenetre de dates)")
    blocs = await charge_les_blocs(paires)
    servables = [p for p, cs in blocs.items() if cs]
    if not servables:
        logger.error("aucune bougie obtenue : on n'ecrit RIEN")
        return 1

    if args.essai:
        logger.info("=== ESSAI : rien ne sera ecrit")
        source = fabrique_source(blocs)
        total = 0
        for p in servables:
            mn, mx = paires[p]
            cs = await source(p, mn, mn + timedelta(hours=96))
            logger.info(f"  {p:10s} la 1re fenetre rendrait {len(cs)} bougies")
            total += len(cs)
        logger.info(f"=== essai termine, {total} bougies servies, 0 ecriture")
        return 0

    avant, _ = _etat()
    logger.info(f"=== resolution (file : {avant})")
    source = fabrique_source(blocs)
    faits = 0
    sterile = 0
    while args.limite is None or faits < args.limite:
        lot = 100
        if args.limite is not None:
            lot = min(lot, args.limite - faits)
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
            # Deux passages sans une resolution : la file crypto ne bouge plus
            # (soit vide, soit tetes irresolubles). On ne tourne pas en rond.
            if sterile >= 2:
                logger.info("deux passages sans avancee : arret")
                break
        else:
            sterile = 0
            logger.info(f"  +{avance} resolus (total {faits}),"
                        f" file {stats['pending_remaining']}")

    apres, issues = _etat()
    logger.info("=== bilan")
    logger.info(f"  resolus par ce rattrapage : {faits}")
    logger.info(f"  file : {avant} -> {apres}")
    logger.info(f"  issues etiquetees resolved_backfill=1 : {dict(issues)}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--essai", action="store_true",
                   help="charge et mesure, n'ecrit RIEN")
    p.add_argument("--limite", type=int, default=None,
                   help="s'arreter apres N resolutions")
    return asyncio.run(_principal(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
