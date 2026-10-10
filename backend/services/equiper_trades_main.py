"""Donner un stop et un objectif aux positions d'or ouvertes À LA MAIN.

Demandé par Xavier le 2026-10-10, après la mesure des chemins du vendredi :
*« la version qui équipe tes trades à la main »*.

## 🔑 LA MESURE QUI MOTIVE CE MODULE, et c'est la seule

Sur les 43 trades qu'il a ouverts dans le terminal MT5 le 2026-10-09 :

```
40 sur 43  n'ont NI stop NI objectif enregistrés chez le courtier
```

⇒ Ni l'échelle de gains, ni la protection des pertes à 5 min, ni les sondes P0
ne les voient. Ses trois pires de la journée — **258 min, 296 min, 19 min** —
font **−41,72 €** à eux seuls ; sans eux la main finissait à **+19,34 €**.

## ⛔ CE MODULE NE PRÉTEND RIEN SUR LA DIRECTION

Mesuré le 2026-10-10 sur 5 jours : la direction du radar est **indiscernable du
hasard** (horizons 1 à 60 min, aucune p-valeur sous 0,27, réussite 42-54 %), et
celle de Xavier n'est mesurable que sur **un** jour — l'adoption des positions
du courtier ne date que du 09/10 — où elle ne bat pas un biais acheteur
constant. Il n'y avait donc aucune base pour qu'un algorithme lui impose un
sens. Ce module **borne le risque de ce qu'il ouvre lui-même**, point.
→ `project_direction_sans_information_2026_10_10`

## Les quatre gardes, et la raison de chacune

1. **Inerte par défaut** (`EQUIPER_TRADES_MAIN=0`). Même choix que
   `XAU_TP_FIXE_EUR` et `LANCEUR_SUR_FERMETURE` : rien ne bouge sans armement.
2. **Il COMBLE, il ne REMPLACE jamais.** Une borne déjà posée n'est pas
   touchée : resserrer la protection que quelqu'un a choisie, sans le lui dire,
   serait pire que de ne rien faire.
3. ⛔ **Jamais de sortie immédiate.** Si la borne calculée est **déjà
   franchie** — la position perd plus que le stop, ou gagne plus que
   l'objectif — on ne la pose pas. Un stop du mauvais côté du cours **ferme**
   la position : fermer n'est pas protéger, et ce n'est pas ce qui a été
   demandé. Le cas est signalé (`alerte`) plutôt que tranché tout seul.
4. **L'or seul, et seulement ce que le radar n'a PAS ouvert.** Les positions du
   radar ont déjà leurs bornes et leur échelle ; les toucher ici créerait deux
   autorités sur le même stop.

## 🔑 Les bornes viennent des RÉGLAGES du radar, pas d'ici

`XAU_SL_FIXE_EUR` et `XAU_TP_FIXE_EUR` — exactement ceux du chemin
automatique. Écrire 20 et 2 dans ce fichier aurait créé une seconde source de
vérité, qui dérive le jour où l'une des deux bouge.
→ `feedback_router_une_source_en_laisser_deux`

⛔ Et un réglage **illisible rend le module muet** au lieu de retomber sur une
valeur par défaut : ici le repli serait posé sur de l'argent réel.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# La marque que le pont pose sur ce que le radar ouvre. Partagée avec
# `echelle_stop_or` pour qu'il n'y ait qu'une definition.
MARQUE_RADAR = "scalping-radar"

SYMBOLES_OR = ("XAUUSD", "XAU/USD", "GOLD")

# ⚠️ Marge de securite avant de declarer une borne << deja franchie >>, en
# euros. A zero, un cours pile sur la borne donnerait un ordre que le courtier
# execute immediatement.
MARGE_FRANCHIE_EUR = 0.10


def arme() -> bool:
    """⚠️ Garde n°1 : inerte par défaut."""
    return os.getenv("EQUIPER_TRADES_MAIN", "0").strip().lower() in (
        "1", "true", "on", "yes", "oui")


def _reglage(nom: str) -> float | None:
    """Un réglage en euros, strictement positif, ou ``None``.

    ⛔ Pas de valeur de repli : voir l'en-tête.
    """
    brut = (os.getenv(nom) or "").strip()
    if not brut:
        logger.warning("equiper_trades_main: %s absent — rien ne sera posé", nom)
        return None
    try:
        v = float(brut.replace(",", "."))
    except (TypeError, ValueError):
        logger.warning("equiper_trades_main: %s illisible (%r) — rien ne sera "
                       "posé", nom, brut)
        return None
    if v <= 0:
        logger.warning("equiper_trades_main: %s = %s, non strictement positif "
                       "— rien ne sera posé", nom, v)
        return None
    return v


def stop_eur() -> float | None:
    return _reglage("XAU_SL_FIXE_EUR")


def objectif_eur() -> float | None:
    return _reglage("XAU_TP_FIXE_EUR")


def est_de_l_or(position: dict) -> bool:
    sym = str(position.get("symbol") or "").upper().replace(" ", "")
    return any(sym == s.upper().replace("/", "").replace(" ", "")
               or sym == s.upper() for s in SYMBOLES_OR)


def est_du_radar(position: dict) -> bool:
    return MARQUE_RADAR in str(position.get("comment") or "")


def concerne(position: dict) -> bool:
    """Cette position est-elle dans la portée du module ?

    🔑 Partagée avec `echelle_stop_or` : c'est elle qui fait que l'échelle et
    la protection des pertes **adoptent** ces positions une fois équipées.
    Sans cette adoption, le stop serait posé une fois et ne suivrait jamais le
    gain — tout l'intérêt disparaîtrait.
    """
    return arme() and est_de_l_or(position) and not est_du_radar(position)


def decision(position: dict, taux_eur_usd: float) -> dict | None:
    """Ce qu'il faut poser sur cette position, ou ``None``.

    Rend ``{"ticket", "sl", "tp", "motif", "alerte"}`` où ``sl``/``tp`` valent
    ``None`` quand il n'y a rien à poser de ce côté.
    """
    if not concerne(position):
        return None
    try:
        taux = float(taux_eur_usd or 0)
        entree = float(position.get("price_open") or 0)
        courant = float(position.get("price_current") or 0)
    except (TypeError, ValueError):
        return None
    if taux <= 0 or entree <= 0 or courant <= 0:
        return None

    sens = str(position.get("type") or "").lower()
    if sens not in ("buy", "sell"):
        return None
    signe = 1 if sens == "buy" else -1

    sl_pose = float(position.get("sl") or 0) > 0
    tp_pose = float(position.get("tp") or 0) > 0
    if sl_pose and tp_pose:
        return None                      # ⚠️ Garde n°2 : rien a combler.

    # Le profit courant, en euros, du point de vue de la position.
    profit_eur = signe * (courant - entree) / taux

    d_sl, d_tp = stop_eur(), objectif_eur()
    sl = tp = None
    alerte = None

    if not sl_pose and d_sl is not None:
        # ⛔ Garde n°3 : un stop deja franchi FERMERAIT la position.
        if profit_eur <= -(d_sl - MARGE_FRANCHIE_EUR):
            alerte = (f"stop de {d_sl:.2f} € deja franchi "
                      f"(position a {profit_eur:+.2f} €) — RIEN pose, "
                      f"a trancher a la main")
            logger.warning("equiper_trades_main: ticket %s — %s",
                           position.get("ticket"), alerte)
        else:
            sl = round(entree - signe * d_sl * taux, 2)

    if not tp_pose and d_tp is not None:
        # ⛔ Meme raison dans l'autre sens : un objectif derriere le cours
        # encaisse immediatement. C'est une sortie, pas une protection.
        if profit_eur >= (d_tp - MARGE_FRANCHIE_EUR):
            msg = (f"objectif de {d_tp:.2f} € deja depasse "
                   f"(position a {profit_eur:+.2f} €) — RIEN pose")
            alerte = f"{alerte} ; {msg}" if alerte else msg
            logger.warning("equiper_trades_main: ticket %s — %s",
                           position.get("ticket"), msg)
        else:
            tp = round(entree + signe * d_tp * taux, 2)

    if sl is None and tp is None:
        # On rend quand meme la decision quand il y a une ALERTE : un cas
        # non traitable doit se LIRE, pas disparaitre.
        if alerte:
            return {"ticket": position.get("ticket"), "sl": None, "tp": None,
                    "motif": "borne_deja_franchie", "alerte": alerte,
                    "profit_eur": round(profit_eur, 2)}
        return None

    return {"ticket": position.get("ticket"), "sl": sl, "tp": tp,
            "motif": "nue" if (not sl_pose and not tp_pose) else "partielle",
            "alerte": alerte, "profit_eur": round(profit_eur, 2)}
