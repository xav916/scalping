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
