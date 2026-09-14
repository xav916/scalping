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

✅ **CE QUI A CHANGÉ LE 2026-09-12.** Le pont MT5 transporte désormais
`tick_volume`, et le laboratoire le câble jusqu'aux bougies. Mesuré le 14/09
sur l'or : **36 bougies sur 36** avec un volume non nul, 813 ticks sur la
dernière. Le profil de **volume** est donc devenu calculable — `profil(...,
source=VOLUME)`.

⛔ **Mais il REFUSE de se calculer sans volume**, au lieu de retomber sur le
TPO. Un repli silencieux ferait mesurer le temps en croyant mesurer le volume,
et le nom du résultat mentirait. C'est la même règle que `_volume_fort`, qui
répond NON quand le volume est absent.

⛔ **Et le TPO reste le DÉFAUT.** Tous les verdicts de `poc_return` depuis le
2026-09-04 ont été rendus en TPO : basculer en silence les rendrait
incomparables sans que rien ne le dise. Le changement de source est une
décision à prendre et à mesurer, pas un effet de bord.

⚠️ `tick_volume` compte les CHANGEMENTS DE PRIX, pas les contrats échangés.
« Profil de volume » est donc ici un profil de **ticks** — le vrai volume
négocié n'existe que sur les futures (COMEX GC/SI). Le nom doit rester honnête
partout où il apparaît.

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

# Les deux façons de pondérer un niveau de prix. Jamais fondues : l'une
# compte le TEMPS, l'autre les TICKS, et elles ne répondent pas à la même
# question.
TPO = "tpo"
VOLUME = "volume"
SOURCES = (TPO, VOLUME)


def profil(candles: list[Candle],
           n_niveaux: int = NIVEAUX_PAR_DEFAUT,
           source: str = TPO) -> list[tuple[float, float]]:
    """Poids de chaque niveau de prix : ``[(prix, poids), ...]``.

    Chaque bougie incrémente TOUS les niveaux que son ``[low, high]``
    traverse — construction TPO classique. `source` dit seulement **de combien**
    elle les incrémente : de 1 en TPO (une unité de temps), de son volume en
    VOLUME.

    ⛔ En VOLUME, rend ``[]`` si le volume total est nul. **Pas de repli sur le
    TPO** : mesurer le temps sous le nom du volume est le genre de glissement
    que ce dépôt paie ensuite pendant des semaines.

    ⛔ Une source inconnue LÈVE. Retomber en silence sur le TPO ferait passer
    une faute de frappe pour un choix.
    """
    if source not in SOURCES:
        raise ValueError(f"source inconnue : {source!r} — connues : {SOURCES}")
    if len(candles) < MIN_BOUGIES:
        return []

    if source == VOLUME:
        total = sum(float(c.volume or 0.0) for c in candles)
        if total <= 0:
            logger.info("market_profile: aucun volume sur %d bougies — profil "
                        "de volume refusé (pas de repli sur le TPO)",
                        len(candles))
            return []

    bas = min(c.low for c in candles)
    haut = max(c.high for c in candles)
    poids_de = ((lambda c: float(c.volume or 0.0)) if source == VOLUME
                else (lambda c: 1.0))
    if haut <= bas:
        # Marché parfaitement plat : un seul niveau, tout le poids dessus.
        return [(bas, sum(poids_de(c) for c in candles))]

    pas = (haut - bas) / n_niveaux
    comptes = [0.0] * n_niveaux
    for c in candles:
        i_bas = int((c.low - bas) / pas)
        i_haut = int((c.high - bas) / pas)
        p = poids_de(c)
        for i in range(max(0, i_bas), min(n_niveaux - 1, i_haut) + 1):
            comptes[i] += p
    return [(bas + (i + 0.5) * pas, n) for i, n in enumerate(comptes)]


def profil_tpo(candles: list[Candle],
               n_niveaux: int = NIVEAUX_PAR_DEFAUT) -> list[tuple[float, float]]:
    """Le profil en TEMPS. Conservé : c'est le nom qu'emploie tout l'existant."""
    return profil(candles, n_niveaux, source=TPO)


def poc(candles: list[Candle],
        n_niveaux: int = NIVEAUX_PAR_DEFAUT,
        source: str = TPO) -> float | None:
    """Le prix le plus fréquenté — en TEMPS (défaut) ou en TICKS.

    ``None`` si indécidable, y compris quand le volume est demandé et absent.
    """
    p = profil(candles, n_niveaux, source)
    if not p:
        return None
    return max(p, key=lambda x: x[1])[0]


def zone_valeur(candles: list[Candle], part: float = PART_ZONE_VALEUR,
                n_niveaux: int = NIVEAUX_PAR_DEFAUT,
                source: str = TPO) -> tuple[float, float] | None:
    """Fourchette de prix contenant ``part`` du temps, centrée sur le POC.

    Élargie depuis le POC vers le voisin le plus fréquenté, jusqu'à couvrir la
    part demandée — la construction usuelle de la *value area*.
    """
    profil_ = profil(candles, n_niveaux, source)
    if not profil_:
        return None
    total = sum(n for _, n in profil_)
    if total <= 0:
        return None

    i_poc = max(range(len(profil_)), key=lambda i: profil_[i][1])
    bas = haut = i_poc
    cumul = profil_[i_poc][1]
    while cumul < part * total and (bas > 0 or haut < len(profil_) - 1):
        gauche = profil_[bas - 1][1] if bas > 0 else -1
        droite = profil_[haut + 1][1] if haut < len(profil_) - 1 else -1
        if droite >= gauche:
            haut += 1
            cumul += droite
        else:
            bas -= 1
            cumul += gauche
    return (profil_[bas][0], profil_[haut][0])


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


# Déplacement minimal des sommets ET des creux, en part de l'amplitude
# totale, pour qu'une tendance soit déclarée.
#
# ⛔ Sans ce seuil, la structure tranchait 8 fenêtres sur 8 sur trois ans de
# BTC et ETH — un filtre qui ne filtre rien. La règle « dernier sommet plus
# haut que le premier » est presque toujours vraie : sur 200 bougies, deux
# extrêmes ne sont jamais exactement égaux. Le test « marché plat = indécis »
# passait seulement parce qu'un marché plat ne produit AUCUNE fractale.
#
# Balayage sur 477 fenêtres de 200 bougies (BTC, ETH, SOL — 3 ans réels) :
#
#     seuil   part tranchée
#     0,00        91,0 %      <- sans seuil : un filtre qui ne filtre pas
#     0,10        79,2 %
#     0,25        64,2 %      <- retenu
#     0,40        43,8 %
#     0,60        20,1 %
#
# ⚠️ Cette mesure dit à quelle FRÉQUENCE le filtre tranche, **pas s'il a
# raison** : rien ici ne compare le verdict à ce que le marché a fait ensuite.
# 0,25 est donc un réglage de sélectivité assumé, pas une validation. La
# structure n'est par ailleurs qu'une des trois conditions — le retour au POC
# et la cible de liquidité filtrent bien davantage.
DEPLACEMENT_MIN = 0.25


def structure(candles: list[Candle],
              deplacement_min: float = DEPLACEMENT_MIN) -> str:
    """``"haussiere"``, ``"baissiere"`` ou ``"indecise"``.

    Haussière = sommets ET creux montants, d'un déplacement SIGNIFICATIF.

    ⚠️ ``indecise`` est la porte la plus importante du module : sans elle, la
    stratégie prendrait position dans du bruit. Trois exigences cumulées :

    1. Assez de sommets et de creux pour parler d'une série.
    2. Les DEUX séries dans le même sens — des sommets montants avec des creux
       descendants, c'est un élargissement, pas une tendance.
    3. Un déplacement d'au moins ``deplacement_min`` de l'amplitude, sur les
       deux séries. C'est ce point qui manquait : comparer deux extrêmes sans
       exiger d'écart rend un verdict à chaque fois.
    """
    sommets, creux = _fractales(candles)
    if len(sommets) < 2 or len(creux) < 2:
        return "indecise"

    amplitude = max(c.high for c in candles) - min(c.low for c in candles)
    if amplitude <= 0:
        return "indecise"

    d_sommets = (sommets[-1] - sommets[0]) / amplitude
    d_creux = (creux[-1] - creux[0]) / amplitude
    if d_sommets >= deplacement_min and d_creux >= deplacement_min:
        return "haussiere"
    if d_sommets <= -deplacement_min and d_creux <= -deplacement_min:
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
