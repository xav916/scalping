"""Profil de marché : POC, zone de valeur, structure, niveaux de liquidité.

Noyau de la stratégie demandée le 2026-09-04 — « repère ta structure, tes
niveaux de liquidité majeurs, tes zones d'accumulation, ton POC ».

⛔ **LE POC EST CALCULÉ EN TPO, PAS EN VOLUME.**

Mesuré sur la prod le 2026-09-04, via `price_service.fetch_candles` :

    WTI/USD   30 bougies, volumes non nuls   0/30
    XAU/USD   30 bougies, volumes non nuls   0/30
    EUR/USD   30 bougies, volumes non nuls   0/30

Twelve Data ne fournit **aucun** volume sur ces CFD. Un « volume profile »
construit là-dessus serait un chiffre inventé, et le POC — la pièce centrale
de la méthode — n'aurait aucun contenu.

Le **TPO** (*Time Price Opportunity*, Steidlmayer) compte le **temps passé à
chaque prix** au lieu du volume : chaque bougie marque tous les niveaux
qu'elle traverse. C'est la définition ORIGINELLE du profil de marché — le
volume profile en est la variante tardive — et elle se calcule depuis l'OHLC
seul. Ce n'est donc pas un pis-aller, c'est la version qui a du sens ici.

⚠️ Ce module ne DÉCIDE rien : il décrit. La règle d'entrée, de stop et de
sortie vit dans `pattern_detector._detect_poc_return`, où elle est nommée et
justifiée — parce que la méthode d'origine ne la donnait pas.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.models.schemas import Candle

logger = logging.getLogger(__name__)

# 50 niveaux : assez fin pour distinguer une zone d'accumulation d'un simple
# passage, assez grossier pour qu'une bougie de plus ne déplace pas le POC.
NIVEAUX_PAR_DEFAUT = 50

# 70 % du temps, convention Steidlmayer (un écart-type d'une normale).
PART_ZONE_VALEUR = 0.70

# Fractale : un sommet doit dominer 2 bougies de chaque côté. En dessous, le
# moindre soubresaut devient un « niveau de liquidité ».
LARGEUR_FRACTALE = 2

# Sous ce nombre de bougies, un profil ne décrit rien.
MIN_BOUGIES = 10


def profil_tpo(candles: list[Candle],
               n_niveaux: int = NIVEAUX_PAR_DEFAUT) -> list[tuple[float, int]]:
    """Temps passé à chaque niveau de prix : ``[(prix, nb_bougies), ...]``.

    Chaque bougie incrémente TOUS les niveaux que son ``[low, high]``
    traverse — c'est la construction TPO classique.
    """
    if len(candles) < MIN_BOUGIES:
        return []
    bas = min(c.low for c in candles)
    haut = max(c.high for c in candles)
    if haut <= bas:
        # Marché parfaitement plat : un seul niveau, tout le temps dessus.
        return [(bas, len(candles))]

    pas = (haut - bas) / n_niveaux
    comptes = [0] * n_niveaux
    for c in candles:
        i_bas = int((c.low - bas) / pas)
        i_haut = int((c.high - bas) / pas)
        for i in range(max(0, i_bas), min(n_niveaux - 1, i_haut) + 1):
            comptes[i] += 1
    return [(bas + (i + 0.5) * pas, n) for i, n in enumerate(comptes)]


def poc(candles: list[Candle],
        n_niveaux: int = NIVEAUX_PAR_DEFAUT) -> float | None:
    """Le prix où le marché a passé le plus de temps. ``None`` si indécidable."""
    profil = profil_tpo(candles, n_niveaux)
    if not profil:
        return None
    return max(profil, key=lambda x: x[1])[0]


def zone_valeur(candles: list[Candle], part: float = PART_ZONE_VALEUR,
                n_niveaux: int = NIVEAUX_PAR_DEFAUT) -> tuple[float, float] | None:
    """Fourchette de prix contenant ``part`` du temps, centrée sur le POC.

    Élargie depuis le POC vers le voisin le plus fréquenté, jusqu'à couvrir la
    part demandée — la construction usuelle de la *value area*.
    """
    profil = profil_tpo(candles, n_niveaux)
    if not profil:
        return None
    total = sum(n for _, n in profil)
    if total <= 0:
        return None

    i_poc = max(range(len(profil)), key=lambda i: profil[i][1])
    bas = haut = i_poc
    cumul = profil[i_poc][1]
    while cumul < part * total and (bas > 0 or haut < len(profil) - 1):
        gauche = profil[bas - 1][1] if bas > 0 else -1
        droite = profil[haut + 1][1] if haut < len(profil) - 1 else -1
        if droite >= gauche:
            haut += 1
            cumul += droite
        else:
            bas -= 1
            cumul += gauche
    return (profil[bas][0], profil[haut][0])


def _fractales(candles: list[Candle],
               largeur: int = LARGEUR_FRACTALE) -> tuple[list[float], list[float]]:
    """Sommets et creux locaux : ``(sommets, creux)``, dans l'ordre du temps."""
    sommets, creux = [], []
    for i in range(largeur, len(candles) - largeur):
        fenetre = candles[i - largeur:i + largeur + 1]
        if candles[i].high == max(c.high for c in fenetre) and \
                candles[i].high > candles[i - 1].high:
            sommets.append(candles[i].high)
        if candles[i].low == min(c.low for c in fenetre) and \
                candles[i].low < candles[i - 1].low:
            creux.append(candles[i].low)
    return sommets, creux


def structure(candles: list[Candle]) -> str:
    """``"haussiere"``, ``"baissiere"`` ou ``"indecise"``.

    Haussière = sommets ET creux montants. Baissière = les deux descendants.

    ⚠️ Tout le reste est ``indecise``, et c'est la porte la plus importante du
    module : sans elle, la stratégie prendrait position dans du bruit. Exiger
    que les DEUX séries aillent dans le même sens est volontairement strict —
    des sommets montants avec des creux descendants, c'est un élargissement,
    pas une tendance.
    """
    sommets, creux = _fractales(candles)
    if len(sommets) < 2 or len(creux) < 2:
        return "indecise"
    hauts_montants = sommets[-1] > sommets[0]
    bas_montants = creux[-1] > creux[0]
    if hauts_montants and bas_montants:
        return "haussiere"
    if not hauts_montants and not bas_montants:
        return "baissiere"
    return "indecise"


def niveaux_liquidite(candles: list[Candle]) -> dict[str, float | None]:
    """Où les stops s'accumulent : au-dessus du dernier sommet, sous le dernier creux.

    C'est la lecture usuelle — les ordres de protection se logent juste
    au-delà des extrêmes récents, et le prix va souvent les y chercher.
    """
    if len(candles) < MIN_BOUGIES:
        return {"au_dessus": None, "en_dessous": None}
    sommets, creux = _fractales(candles)
    return {"au_dessus": max(sommets) if sommets else None,
            "en_dessous": min(creux) if creux else None}


def decrire(candles: list[Candle]) -> dict[str, Any]:
    """Les quatre éléments d'un coup, pour journalisation et diagnostic."""
    zv = zone_valeur(candles)
    return {
        "poc": poc(candles),
        "zone_valeur": zv,
        "structure": structure(candles),
        "liquidite": niveaux_liquidite(candles),
        "n_bougies": len(candles),
    }
