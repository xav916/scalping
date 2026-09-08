"""Détecter les motifs sur une échelle AGRÉGÉE depuis les bougies de 5 minutes.

Demandé par Xavier le 2026-09-08, après avoir constaté que le chemin 5 min
n'agrège rien : son détecteur le plus profond regarde 30 bougies, soit
**2 h 30**, et `momentum` n'en regarde que 5 — **25 minutes**.

## ⛔ Ce qui a été mesuré AVANT de construire

Rejeu séquentiel sur 60 jours, spread facturé, mêmes détecteurs :

```
                 n     R moyen       t    spread payé
XAU/USD   M5   109     +0,029    +0,23      0,029 R
          M15   47     +0,142    +0,71      0,017 R
          M30   24     +0,561    +1,98      0,013 R
EUR/USD   M5   124     −0,324    −2,73      0,162 R
          M15   48     −0,156    −0,82      0,091 R
          M30   19     +0,004    +0,01      0,055 R
```

🔑 **Monotone sur les DEUX instruments**, et le mécanisme est visible : le
spread payé, exprimé en R, s'effondre quand l'échelle grandit — parce que le
stop s'élargit. C'est la mesure de « le 5 min ne paie pas ses frais », avec son
remède.

⚠️ n=19 à 24 sur M30, sur deux instruments et 60 jours. C'est une piste
DÉCLARÉE, pas une conclusion : elle se juge sur le futur.

## Portée volontairement étroite

Les setups agrégés portent l'horizon `15min` / `30min`. **Aucune route MT5 ne
les accepte tant qu'on ne l'a pas dit** : `MT5_ECHELLES_AGREGEES_ROUTES` est
vide par défaut, et on n'y met que `admin_legacy` — le démo.

⛔ Ma première version se contentait de compter sur
`MT5_BRIDGE_LIVE_ALLOWED_HORIZONS=5min,4h` pour écarter le réel. C'était juste
pour le réel et **faux pour le démo** : `_mt5_horizons` filtre sur
`{CANDLE_INTERVAL}` pour les DEUX routes, donc les setups agrégés n'auraient
atteint personne. Le dispositif aurait été inerte, sans le dire.

🔑 L'argent réel est désormais protégé **deux fois** : par le défaut vide de la
route, et par la déclaration du réel qui restreint par intersection.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

# Échelles servies, en nombre de bougies de 5 minutes agrégées.
# ⚠️ Réglable : `ECHELLES_AGREGEES="3,6"` (M15 et M30). Vide = désarmé.
_BRUT = os.getenv("ECHELLES_AGREGEES", "3,6")
FACTEURS: tuple[int, ...] = tuple(
    int(x) for x in _BRUT.split(",") if x.strip().isdigit() and int(x) > 1)

# Il faut au moins ce nombre de bougies agrégées pour que les détecteurs aient
# de quoi travailler — `detect_patterns` en regarde jusqu'à 30.
MIN_BOUGIES = 40


def horizon_pour(facteur: int) -> str:
    """L'étiquette d'horizon d'une échelle. 3 → `15min`, 6 → `30min`."""
    return f"{5 * facteur}min"


def agreger(candles: list, facteur: int) -> list:
    """Agrège des bougies de 5 min en bougies de 5×facteur minutes.

    ⛔ **Aligné sur l'horloge**, jamais par paquets successifs. Un découpage
    décalé produirait des bougies qui n'existent chez aucun courtier — le rejeu,
    puis la production, mesureraient un instrument imaginaire.

    ⚠️ Une bougie INCOMPLÈTE (le groupe en cours) est écartée : la détection
    verrait un plus haut et un plus bas qui ne sont pas encore les siens, et
    changerait d'avis à chaque cycle sur la même bougie.
    """
    if facteur <= 1 or not candles:
        return list(candles or [])
    pas = 5 * facteur
    groupes: dict[datetime, list] = {}
    for c in candles:
        d = getattr(c, "timestamp", None)
        if d is None:
            continue
        cle = d.replace(minute=(d.minute // pas) * pas, second=0, microsecond=0)
        groupes.setdefault(cle, []).append(c)

    from backend.models.schemas import Candle
    out = []
    cles = sorted(groupes)
    for cle in cles:
        g = groupes[cle]
        # ⛔ Groupe incomplet = bougie en cours. On ne la sert pas.
        if len(g) < facteur:
            continue
        out.append(Candle(
            timestamp=cle, open=g[0].open, close=g[-1].close,
            high=max(x.high for x in g), low=min(x.low for x in g),
            volume=sum(getattr(x, "volume", 0.0) or 0.0 for x in g)))
    return out


def setups_agreges(candles_m5: list, pair: str, is_simulated: bool = False) -> list:
    """Les setups détectés sur les échelles agrégées, horizon estampillé.

    Best-effort : une échelle qui échoue n'empêche pas les autres, et aucune
    n'empêche le chemin 5 min. ⛔ Une piste en observation ne doit jamais
    pouvoir casser le flux qui, lui, trade.
    """
    if not FACTEURS or not candles_m5:
        return []
    from backend.services.pattern_detector import (calculate_trade_setup,
                                                   detect_patterns)
    out = []
    for facteur in FACTEURS:
        try:
            agregees = agreger(candles_m5, facteur)
            if len(agregees) < MIN_BOUGIES:
                continue
            for motif in detect_patterns(agregees, pair):
                s = calculate_trade_setup(pair, motif, agregees,
                                          is_simulated=is_simulated)
                if s is None:
                    continue
                # 🔑 L'horizon est pose ICI, avant `enrich_trade_setup` qui ne
                # l'ecrase pas s'il existe. C'est lui qui tient la portee : le
                # compte reel n'autorise que `5min,4h`.
                s.horizon = horizon_pour(facteur)
                out.append(s)
        except Exception as e:  # noqa: BLE001
            logger.debug("echelle_agregee %s x%d : %s", pair, facteur, e)
    return out
