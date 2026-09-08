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

# ⛔ Le cycle ne fournit que `CANDLE_COUNT` bougies de 5 min — **50**. Agrégées,
# cela donne 16 en M15 et 8 en M30 : sous le minimum, écartées, et rien n'aurait
# jamais été produit. C'était la vraie cause d'inertie, invisible parce que le
# `continue` ne disait rien.
#
# 🔑 On MÉMORISE donc les bougies entre les cycles, au lieu d'acheter des
# requêtes en plus. C'est exactement ce que Xavier décrivait — « capitaliser et
# agréger les analyses » — et ça ne coûte pas un appel : le quota Twelve Data a
# déjà saturé une fois (954 refus 429).
#
# ⚠️ Le tampon vit en mémoire : un redémarrage le vide et il se remplit seul.
# 400 bougies de 5 min ≈ 33 h, soit 66 bougies M30 — de quoi détecter.
MAX_MEMOIRE = int(os.getenv("ECHELLES_MEMOIRE_M5", "400"))
_memoire: dict[str, dict] = {}
# Ce qu'on a déjà dit sur chaque (paire, échelle) — on ne le redit qu'au
# CHANGEMENT. ⛔ Sinon 8 500 lignes par jour, et la trace utile s'y noie.
_dit: dict[tuple, bool] = {}
# Les paires deja preremplies — une seule tentative par processus.
_preremplies: set[str] = set()


def memoriser(pair: str, candles: list) -> list:
    """Fusionne les bougies du cycle dans le tampon, et rend le tampon complet.

    Dédoublonné par horodatage : deux cycles consécutifs se recouvrent presque
    entièrement, seule la ou les dernières bougies sont neuves.
    """
    if not candles:
        return list((_memoire.get(pair) or {}).values())
    par_date = _memoire.setdefault(pair, {})
    for c in candles:
        d = getattr(c, "timestamp", None)
        if d is not None:
            par_date[d] = c
    if len(par_date) > MAX_MEMOIRE:
        for d in sorted(par_date)[:len(par_date) - MAX_MEMOIRE]:
            del par_date[d]
    return [par_date[d] for d in sorted(par_date)]


def bougies_manquantes(pair: str) -> int:
    """Combien de bougies de 5 min manquent à cette paire pour servir TOUTES
    ses échelles. Zéro si le tampon suffit déjà."""
    if not FACTEURS:
        return 0
    besoin = MIN_BOUGIES * max(FACTEURS) + max(FACTEURS)   # + une marge d'alignement
    return max(0, min(besoin, MAX_MEMOIRE) - len(_memoire.get(pair) or {}))


async def preremplir(pair: str, fetch, interval: str = "5min") -> int:
    """Remplit le tampon d'un coup, UNE fois par paire et par processus.

    ⛔ Sans lui, le tampon met ~16 h à atteindre M30 en n'ajoutant qu'une
    bougie toutes les 5 minutes — et **chaque redéploiement le vide**. Le
    dispositif ne se serait probablement jamais allumé.

    ⛔ Le `fetch` reçu doit IGNORER le cache. Celui-ci est indexé sur
    ``(paire, intervalle)`` sans la taille : il resservirait les 50 bougies du
    cycle en cours, et le tampon ne dépasserait jamais 50. C'est exactement ce
    qui est arrivé le 2026-09-08 — voir `price_service.fetch_candles_sans_cache`.

    ⚠️ Best-effort et silencieux en cas d'échec côté appelant : un essai en
    observation ne doit pas pouvoir casser le cycle qui, lui, trade. Un seul
    appel par paire, donc négligeable devant le quota — qui a déjà saturé une
    fois (954 refus 429).
    """
    if pair in _preremplies or not FACTEURS:
        return 0
    _preremplies.add(pair)              # ⛔ posé AVANT l'appel : un échec ne
                                        # doit pas se retenter à chaque cycle
    manque = bougies_manquantes(pair)
    if manque <= 0:
        return 0
    taille = min(MAX_MEMOIRE, MIN_BOUGIES * max(FACTEURS) + max(FACTEURS))
    recues = await fetch(pair, interval=interval, outputsize=taille)
    # ⛔ `fetch_candles` rend un TUPLE `(bougies, simule)`. Le passer tel quel
    # a `memoriser` n'ajoutait rien et ne levait rien : « 0 bougie », sans
    # erreur. Mon test factice rendait une liste — il ne reproduisait pas le
    # contrat, donc il passait sur du code faux.
    if isinstance(recues, tuple):
        recues = recues[0]
    avant = len(_memoire.get(pair) or {})
    apres = len(memoriser(pair, recues or []))
    logger.info("echelle_agregee: %s preremplie — %d bougies (etait %d)",
                pair, apres, avant)
    return apres - avant


def etat_memoire() -> dict[str, int]:
    """Combien de bougies chaque paire a capitalisé. Pour les sondes."""
    return {p: len(v) for p, v in sorted(_memoire.items())}


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


def _motif(setup) -> str:
    """Le nom du motif, quelle que soit la profondeur d'emballage.

    ⚠️ `setup.pattern` est un objet Pattern dont `.pattern` est l'enum. Ma
    sonde de mesure s'est trompée de niveau et a rendu « n=1 » sur chaque
    ligne — un regroupement qui ne regroupait rien.
    """
    p = getattr(setup, "pattern", None)
    p = getattr(p, "pattern", p)
    return str(getattr(p, "value", p))


def setups_agreges(candles_m5: list, pair: str, is_simulated: bool = False) -> list:
    """Les setups détectés sur les échelles agrégées, horizon estampillé.

    Best-effort : une échelle qui échoue n'empêche pas les autres, et aucune
    n'empêche le chemin 5 min. ⛔ Une piste en observation ne doit jamais
    pouvoir casser le flux qui, lui, trade.
    """
    if not FACTEURS:
        return []
    # 🔑 On travaille sur le TAMPON, pas sur les 50 bougies du cycle.
    mem = memoriser(pair, candles_m5)
    if not mem:
        return []
    from backend.services.pattern_detector import (calculate_trade_setup,
                                                   detect_patterns)
    out = []
    for facteur in FACTEURS:
        try:
            agregees = agreger(mem, facteur)
            if len(agregees) < MIN_BOUGIES:
                # ⛔ Dit UNE fois, au changement d'état seulement. Le silence
                # d'origine ici a masqué l'inertie complète du dispositif.
                if _dit.get((pair, facteur)) is not True:
                    _dit[(pair, facteur)] = True
                    logger.info(
                        "echelle_agregee: %s %s en attente — %d bougies "
                        "agregees sur %d (tampon %d/%d bougies 5 min)",
                        pair, horizon_pour(facteur), len(agregees),
                        MIN_BOUGIES, len(mem), MAX_MEMOIRE)
                continue
            if _dit.get((pair, facteur)) is not False:
                _dit[(pair, facteur)] = False
                logger.info("echelle_agregee: %s %s ACTIVE — %d bougies",
                            pair, horizon_pour(facteur), len(agregees))
            trouves = []
            for motif in detect_patterns(agregees, pair):
                s = calculate_trade_setup(pair, motif, agregees,
                                          is_simulated=is_simulated)
                if s is None:
                    continue
                # 🔑 L'horizon est pose ICI, avant `enrich_trade_setup` qui ne
                # l'ecrase pas s'il existe. C'est lui qui tient la portee : le
                # compte reel n'autorise que `5min,4h`.
                s.horizon = horizon_pour(facteur)
                trouves.append(s)
            if trouves:
                # ⛔ Trace POSITIVE, au niveau INFO. Sans elle le dispositif
                # serait muet : on ne saurait dire s'il ne produit rien parce
                # que le marché n'offre rien, ou parce qu'il est cassé. C'est
                # le mode de défaillance déjà rencontré trois fois ici —
                # « enregistrer ≠ dire ».
                logger.info("echelle_agregee: %s %s -> %d setup(s) [%s]",
                            pair, horizon_pour(facteur), len(trouves),
                            ", ".join(sorted({_motif(x) for x in trouves})))
            out.extend(trouves)
        except Exception as e:  # noqa: BLE001
            logger.warning("echelle_agregee %s x%d : %s", pair, facteur, e)
    return out
