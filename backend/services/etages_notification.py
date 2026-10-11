"""Trois etages pour le fil IC Markets : AGIR, DIGEST, INFRA.

> Xavier, 2026-10-11 : « je veux rationaliser les messages qui me sont envoyes
> par Telegram sur le fil IC Markets. » Puis, mis devant l'inventaire, il a
> choisi la regle des **trois etages**.

## LE CONSTAT, mesure avant de proposer quoi que ce soit

**17 emetteurs** peuvent ecrire sur son fil, plus le radar lui-meme. Les
cadences de TENTATIVE :

    chaque minute   une position tourne sans stop
    2 min           un ordre pousse jamais confirme par le courtier
    5 min           un palier franchi · le labo veut reajuster l'or
    15 min          capture des niveaux · premier metal · watchdog des paires
    1x/jour         recap + digest d'equite + ledger, en TROIS messages

⛔ Et ce que je n'ai PAS pu mesurer : combien arrivent vraiment. **Aucun envoi
n'est journalise** — ni table, ni log. C'est precisement ce qui a laisse passer
les **huit copies du meme message** le 2026-10-07.

## LA REGLE : un message reste immediat s'il change ce que Xavier FAIT

    AGIR     il doit decider ou intervenir MAINTENANT
    DIGEST   c'est une mesure, elle attend le bilan du jour
    INFRA    ca ne parle pas de SON argent  ->  canal ⚙️

## 🔑 LE PLUS GROS LEVIER EST GRATUIT : l'or est SEUL

`LIVE_WHITELIST_PAIRS=XAU/USD` depuis le 2026-10-08. Donc **IBKR, l'energie,
le WTI, les clients payants** et le watchdog des autres paires ne peuvent plus
rien dire d'utile sur son fil. Les deplacer ne coute AUCUNE information.

## ⛔ LE DEFAUT PAR DEFAUT EST `AGIR`, ET C'EST LE POINT LE PLUS IMPORTANT

Une cle inconnue **reste sur son fil**, et l'inconnue est JOURNALISEE. L'autre
choix — ranger l'inconnu en infra — rendrait muet, en silence, tout emetteur
ajoute plus tard : exactement le defaut du `channel` par defaut a `infra`, qui
a fait atterrir quatre notificateurs de trading sur le mauvais bot entre le
04/08 et le 19/08 (voir le docstring de la route dans `app.py`).

⇒ Se tromper doit rendre le systeme BAVARD, jamais MUET.

## ⛔ INERTE PAR DEFAUT

`ETAGES_NOTIFICATION` absent ⇒ `router()` ne change rien, et chaque message
part ou il partait. L'etage est *calcule* et *journalise* quand meme, pour
qu'on puisse lire ce que l'armement ferait AVANT de l'armer.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

AGIR = "agir"
DIGEST = "digest"
INFRA = "infra"

# ─── La table, par PREFIXE de `dedup_key` ────────────────────────────────
#
# 🔑 PAR PREFIXE, parce que les cles portent une identite variable :
# `tiers_objectif:12345:1.8` ou `metal_parti:admin_live:0.35`. Le prefixe est
# la seule partie STABLE, et c'est lui qui dit de quoi parle le message.
#
# ⚠️ Les prefixes ci-dessous ne sont pas inventes : ils sont releves dans le
# depot (`grep` sur les constructions de `dedup_key`). Un prefixe ecrit de
# memoire aurait range des messages dans un etage que personne n'atteint.
ETAGES: dict[str, str] = {
    # ── AGIR : il doit decider ou intervenir maintenant ──────────────────
    "nue": AGIR,                     # une position tourne SANS stop
    "nue-illisible": AGIR,           # on ne PEUT PAS savoir si elle en a un
    "push_echec": AGIR,              # un ordre pousse, jamais confirme
    "saturation": AGIR,              # le plafond va fermer l'admission
    "metal_parti": AGIR,             # le premier ordre d'or est parti
    "metal_silence": AGIR,           # ... et sinon, ce qui l'arrete
    "interrupteur_desarme": AGIR,    # REM-002 est tombe
    "fermeture_metaux": AGIR,        # fermeture avant la cloture du vendredi

    # ── DIGEST : une mesure, elle attend le bilan du jour ────────────────
    "tiers_objectif": DIGEST,        # un palier franchi, toutes les 5 min
    "capture-niveaux-illisible": DIGEST,
    "capture-niveaux-manquantes": DIGEST,
    "capture-niveaux-verification": DIGEST,
    "echelles_or_journee": DIGEST,
    "equilibre-activations": DIGEST,
    "equilibre-illisible": DIGEST,
    "interrupteur_bilan": DIGEST,
    "divergence-univers": DIGEST,
    "divergence-muet": DIGEST,

    # ── INFRA : ca ne parle pas de SON argent ────────────────────────────
    #
    # 🔑 Les cinq premiers sont gratuits : l'or est SEUL sur le compte reel
    # depuis le 08/10, donc aucun de ces sujets ne peut plus produire une
    # information qui le concerne.
    "ibkr-digest": INFRA,
    "ibkr-illisible": INFRA,
    "ibkr-mvt-": INFRA,
    "energie-weekend": INFRA,
    "exec-client": INFRA,            # un CLIENT payant, pas son compte
    "exec-client-illisible": INFRA,
}

# ⚠️ Les prefixes sont testes du PLUS LONG au plus court : `exec-client-illisible`
# doit gagner contre `exec-client`, sinon la cle la plus precise n'est jamais
# atteinte. Calcule une fois, a l'import.
_PREFIXES_TRIES: tuple[str, ...] = tuple(
    sorted(ETAGES, key=len, reverse=True))

# Le fil de Xavier. Les autres canaux ne sont pas concernes : rationaliser le
# fil d'un compte ne doit pas deplacer les messages d'un autre.
CANAL_CONCERNE = "ic_markets"


def arme() -> bool:
    """⛔ Inerte par defaut : sans ca, `router()` ne change RIEN."""
    return os.getenv("ETAGES_NOTIFICATION", "0").strip().lower() in (
        "1", "true", "on", "yes", "oui")


def etage(dedup_key: str | None) -> tuple[str, bool]:
    """``(etage, connu)`` pour cette cle.

    ⛔ Une cle absente ou inconnue rend ``(AGIR, False)`` — le message RESTE
    sur le fil de Xavier. Voir l'en-tete : se tromper doit rendre bavard,
    jamais muet.
    """
    cle = (dedup_key or "").strip()
    if not cle:
        return (AGIR, False)
    for p in _PREFIXES_TRIES:
        if cle.startswith(p):
            return (ETAGES[p], True)
    return (AGIR, False)


def router(canal: str, dedup_key: str | None,
           ) -> tuple[str, bool, str]:
    """``(canal_effectif, differer, etage)``.

    `differer=True` veut dire : **ne pas envoyer maintenant**, ranger dans le
    bilan du jour. L'appelant est responsable de le ranger — cette fonction ne
    decide, elle n'envoie pas.

    ⚠️ Ne touche QUE `ic_markets`. Un message d'infra, de Kraken ou de la demo
    ressort inchange : rationaliser un fil ne doit pas en remuer un autre.
    """
    et, connu = etage(dedup_key)

    if not connu:
        # 🔑 On le DIT. Un emetteur ajoute plus tard doit se voir dans le
        # journal, pas se decouvrir six mois apres en cherchant un message
        # qu'on n'a jamais recu.
        logger.info("etages_notification: cle %r inconnue — reste en AGIR "
                    "(a classer dans ETAGES)", dedup_key)

    if canal != CANAL_CONCERNE:
        return (canal, False, et)

    if not arme():
        # Inerte : on calcule et on journalise ce que l'armement FERAIT, sans
        # rien changer. C'est ce qui permet de lire la decision avant de la
        # prendre.
        if et != AGIR:
            logger.info("etages_notification: DESARME — %r irait en %s",
                        dedup_key, et)
        return (canal, False, et)

    if et == INFRA:
        logger.info("etages_notification: %r -> canal infra", dedup_key)
        return (INFRA, False, et)
    if et == DIGEST:
        logger.info("etages_notification: %r -> differe au bilan du jour",
                    dedup_key)
        return (canal, True, et)
    return (canal, False, et)
