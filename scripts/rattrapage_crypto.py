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
import logging
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from backend.models.schemas import Candle  # noqa: E402
from backend.services import binance_klines_service as bks  # noqa: E402
from backend.services.shadow_v2_core_long import ensure_schema  # noqa: E402
from scripts import rattrapage_commun as commun  # noqa: E402

logger = logging.getLogger("rattrapage_crypto")

# ⛔ LE COEUR EST PARTAGE avec le palier 2 (`rattrapage_commun`). Extrait le
# 2026-10-26 : les deux paliers ne different que par la SOURCE de bougies, et
# dupliquer la selection, le chargement et la boucle aurait garanti que l un
# derive de l autre. Les noms publics d ici sont conserves : les tests du
# palier 1 les visent.
MARGE_AVANT = commun.MARGE_AVANT
MARGE_APRES = commun.MARGE_APRES
fabrique_source = commun.fabrique_source


def paires_crypto_en_file(db_path=None) -> dict[str, tuple[datetime, datetime]]:
    """Les paires crypto encore en file, avec leur intervalle de barres.

    Ne rend QUE les paires que Binance sait coter : une paire absente de la
    table de correspondance n a rien a faire dans un rattrapage Binance.
    """
    return commun.paires_en_file(bks.is_crypto_pair, db_path)


async def chargeur(paire: str, debut: datetime, fin: datetime) -> list[Candle]:
    return await bks.fetch_klines_fenetre(paire, "5min", debut, fin)


async def charge_les_blocs(paires: dict[str, tuple[datetime, datetime]]
                           ) -> dict[str, list[Candle]]:
    """Charge, une fois par paire, tout l intervalle utile."""
    return await commun.charge_les_blocs(paires, chargeur)


def _etat(db_path=None):
    return commun.etat(db_path)


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
    faits = await commun.resout(blocs, limite=args.limite)

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
