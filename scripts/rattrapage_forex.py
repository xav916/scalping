#!/usr/bin/env python3
"""Palier 2 du rattrapage : resout les setups FOREX restes en file.

CONTEXTE (2026-10-26). Apres le palier 1 (crypto, 18 986 resolus via Binance),
il reste 3 621 setups en file dont **2 875 de forex sur 38 paires**. Twelve
Data sert bien le 5 min d'aout : verifie en reel avant d'ecrire une ligne --
1 153 bougies rendues sur une fenetre de 4 jours d'aout, pour EUR/USD comme
pour GBP/USD.

⛔ LE PIEGE, ET POURQUOI `fetch_candles_fenetre` DECOUPE EN TRANCHES. Sur une
plage large, l'API rend les 5 000 bougies les plus RECENTES de la plage, pas
les premieres : [01/08 -> 26/10] rend du 08/10 au 26/10 et jette aout **en
silence**. Mesure : 5 000 bougies rendues, toutes posterieures au 08/10.

⛔ CE QUI N'EST PAS RATTRAPE, ET C'EST VOULU. XAU/USD et WTI/USD (661 lignes)
sont cables sur le pont du courtier, qui ne sert que du recent, et le magasin
de secours s'arrete au 2026-08-08 avec une donnee deja connue comme douteuse
(deux conventions melangees, decalage de +600 min). Les resoudre depuis Twelve
Data ferait exactement ce que la cascade de `price_service` interdit : juger un
contrat avec les prix d'un autre. Les laisser en file est plus honnete.

⚠️ CE RATTRAPAGE PARTAGE LE QUOTA DE LA PRODUCTION. `fetch_candles_fenetre`
passe par le limiteur de debit : si le cycle qui trade sature la bande, le
rattrapage s'arrete en le disant plutot que de prendre sa place. Un palier 2
incomplet se relance ; une detection aveugle, non.

Usage :
    python -m scripts.rattrapage_forex --essai
    python -m scripts.rattrapage_forex --limite 200
    python -m scripts.rattrapage_forex
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime

sys.path.insert(0, ".")

from backend.models.schemas import Candle  # noqa: E402
from backend.services import binance_klines_service as bks  # noqa: E402
from backend.services import bougies_du_pont  # noqa: E402
from backend.services import price_service  # noqa: E402
from backend.services.shadow_v2_core_long import ensure_schema  # noqa: E402
from scripts import rattrapage_commun as commun  # noqa: E402

logger = logging.getLogger("rattrapage")


def est_forex_rattrapable(paire: str) -> bool:
    """Ni crypto (palier 1), ni paire cablee sur le pont du courtier.

    🔑 Le test du pont est fait par `bougies_du_pont.paire_du_pont`, la MEME
    fonction que la cascade de production : si demain une paire y est ajoutee,
    ce rattrapage l'exclut automatiquement. Recopier la liste ici aurait
    garanti qu'elle derive.
    """
    if bks.is_crypto_pair(paire):
        return False
    if bougies_du_pont.paire_du_pont(paire):
        return False
    return True


# Cadence par defaut entre deux tranches. MESURE le 2026-10-26 : le plan Grow
# donne 55 credits par MINUTE, partages avec le cycle qui trade. Mon premier
# passage a tire 38 tranches en rafale et a pris un 429 sur TOUTES les paires.
# 4 s => ~15 requetes/min pour le rattrapage, le reste pour la production.
# ⓘ 38 paires x ~5 tranches = ~190 requetes, soit ~13 min. Ce rattrapage n a
# aucune urgence : la lenteur est le bon prix de la non-interference.
CADENCE_SEC = 4.0


async def chargeur(paire: str, debut: datetime, fin: datetime) -> list[Candle]:
    return await price_service.fetch_candles_fenetre(
        paire, "5min", debut, fin, pause_entre_tranches=CADENCE_SEC)


async def _principal(args) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ensure_schema()

    logger.info("=== la file forex, par paire")
    paires = commun.paires_en_file(est_forex_rattrapable)
    if not paires:
        logger.info("aucune paire forex en file : rien a faire")
        return 0
    logger.info(f"=== {len(paires)} paires retenues")

    if args.paire:
        paires = {p: v for p, v in paires.items() if p in args.paire}
        logger.info(f"=== restreint par --paire : {sorted(paires)}")
        if not paires:
            logger.error("aucune des paires demandees n'est en file")
            return 1

    logger.info("=== chargement des bougies (Twelve Data, plage de dates)")
    blocs = await commun.charge_les_blocs(paires, chargeur)

    servables = [p for p, cs in blocs.items() if cs]
    muettes = [p for p, cs in blocs.items() if not cs]
    logger.info(f"=== servables {len(servables)} / muettes {len(muettes)}"
                + (f" : {muettes}" if muettes else ""))

    if args.essai:
        logger.info("=== ESSAI : rien ne sera ecrit")
        source = commun.fabrique_source(blocs)
        for p in servables:
            mn, _ = paires[p]
            cs = await source(p, mn, mn + commun.MARGE_APRES)
            logger.info(f"  {p:10s} la 1re fenetre rendrait {len(cs)} bougies")
        return 0

    avant, _ = commun.etat()
    logger.info(f"=== resolution (file : {avant})")
    faits = await commun.resout(blocs, limite=args.limite)

    apres, issues = commun.etat()
    logger.info("=== bilan")
    logger.info(f"  resolus par ce passage : {faits}")
    logger.info(f"  file : {avant} -> {apres}")
    logger.info(f"  cumul etiquete resolved_backfill=1 : {dict(issues)}")
    return 0


def main() -> int:
    # ⛔ `global` doit preceder tout usage du nom dans la fonction, sinon
    # SyntaxError -- et `ast.parse` ne l'attrape PAS (c'est une verification de
    # table des symboles, faite a la compilation). Vu a la collecte pytest.
    global CADENCE_SEC

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--essai", action="store_true", help="charge et mesure, n'ecrit RIEN")
    p.add_argument("--limite", type=int, default=None, help="s'arreter apres N resolutions")
    p.add_argument("--paire", action="append", help="restreindre a ces paires")
    p.add_argument("--cadence", type=float, default=None,
                   help=f"secondes entre deux requetes (defaut {CADENCE_SEC})")
    args = p.parse_args()
    if args.cadence is not None:
        CADENCE_SEC = args.cadence
    return asyncio.run(_principal(args))


if __name__ == "__main__":
    raise SystemExit(main())
