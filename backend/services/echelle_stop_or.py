"""Échelle de stop sur l'or — remonte le stop par paliers de profit.

Demandée par Xavier le 2026-10-09, après qu'il ait lu la mesure contraire deux
fois et l'ait levée deux fois. Déclarée dans `docs/concepts-trading.md` au
commit `87d3ee0`, **avant** cette ligne de code.

| profit atteint | stop porté à |
|---|---|
| +1,00 € | +0,75 € |
| +1,25 € | +1,00 € |
| +1,75 € | +1,50 € |
| +2,00 € | la cible ferme le trade |

Le stop suit **0,25 €** derrière le palier franchi, et ne **redescend jamais**.

## ⛔ CE QUE LA MESURE DIT DE CETTE RÈGLE

Le pont porte déjà ce mécanisme (`equilibre_auto`), **gardé à 1,0 R de
coussin**, et son commentaire chiffre pourquoi :

> *« Sous ce coussin de profit, un stop posé à l'équilibre est collé au marché
> et se fait sortir par le bruit — la mécanique exacte qui a coûté −0,329 R
> par trade sur l'or. »*

Le palier de Xavier à +1 € vaut **0,0500 R** : vingt fois sous ce garde-fou. Et
la distance réelle au déclenchement, bid-ask déduit, vaut **0,131 $**.

⇒ Ce module ne prétend pas que la règle soit bonne. Il la réalise **exactement**
comme demandée, **inerte par défaut**, et de façon mesurable.

## 🔑 CE QU'IL NE PEUT PAS GARANTIR, et il faut le savoir

Le radar **sonde** ; il ne vit pas dans le marché. Entre deux sondages le prix
peut franchir un palier **et revenir** sans que l'échelle l'ait vu. L'échelle
réelle est donc **moins réactive** que l'échelle simulée, et l'écart grandit
avec l'intervalle de sondage.

⛔ Seule une logique côté MT5 (un Expert Advisor) serait continue. Promettre
autre chose serait mentir sur ce que fait un sondage.

## Les gardes

1. **Inerte par défaut** (`ECHELLE_STOP_OR=0`).
2. **L'or seul**, et seulement les positions **du radar** (commentaire
   `scalping-radar`) : une position ouverte à la main dans le terminal n'est
   pas la nôtre, on n'y touche pas.
3. **Cliquet** : on ne pose un stop que s'il est **meilleur** que l'actuel.
   Sans ça, un sondage pendant un repli ferait *redescendre* le stop — soit
   l'inverse d'une protection.
4. **Jamais au-delà du prix** : un stop posé du mauvais côté serait refusé par
   le courtier, et masquerait un défaut de signe.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# (profit atteint en EUR, stop porté à en EUR) — l'échelle de Xavier, telle
# qu'il l'a dictée. Triée par palier CROISSANT.
ECHELLE_DEFAUT = ((1.00, 0.75), (1.25, 1.00), (1.75, 1.50))

MARQUE_RADAR = "scalping-radar"


def arme() -> bool:
    """⛔ Inerte par défaut : une échelle qui s'allume au déploiement
    modifierait les stops de l'argent réel sans que personne l'ait demandé."""
    return os.getenv("ECHELLE_STOP_OR", "0").strip().lower() in (
        "1", "true", "yes", "on")


# ⛔ TOLERANCE SUR LA COMPARAISON DE SEUIL, et ce n'est PAS defensif.
#
# Un cours pile au palier ne le franchissait PAS. Mesure : pour une entree a
# 4190,00 et un taux de 1,1235, un cours a +1,00 EUR vaut
# `4190 + 1.00 * 1.1235`, et le profit recalcule par division rend
# **0.9999999999999999**. Le seuil de 1,00 n'etait donc jamais atteint a
# l'euro exact.
#
# 🔑 Trouve par un test qui construisait le prix DEPUIS le seuil -- c'est-a-dire
# exactement le cas limite que la production rencontre quand le prix arrive
# pile au palier. Un dix-milliardieme d'euro de tolerance le couvre, et aucune
# decision reelle ne se joue a cette echelle.
_TOLERANCE = 1e-9

# ⚠️ Ecart par defaut entre le palier et l'objectif (regle du 2026-10-09).
TP_ECART_DEFAUT = 2.0


def echelle() -> tuple[tuple[float, float], ...]:
    """Les paliers, surchargeables par `ECHELLE_STOP_OR_PALIERS`.

    Format : `1.0:0.75,1.25:1.0,1.75:1.5`. ⛔ Un réglage illisible rend
    l'échelle de Xavier plutôt qu'une liste vide : une échelle vide serait
    silencieusement inerte alors que le drapeau est armé.
    """
    brut = os.getenv("ECHELLE_STOP_OR_PALIERS", "").strip()
    if not brut:
        return ECHELLE_DEFAUT
    try:
        paliers = []
        for bout in brut.split(","):
            seuil, cible = bout.split(":")
            paliers.append((float(seuil), float(cible)))
        if not paliers:
            raise ValueError("aucun palier")
        for seuil, cible in paliers:
            if cible >= seuil:
                raise ValueError(
                    f"palier {seuil} -> {cible} : le stop doit rester SOUS "
                    f"le profit atteint, sinon il est deja depasse")
        return tuple(sorted(paliers))
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "ECHELLE_STOP_OR_PALIERS illisible (%s) — repli sur l'echelle "
            "declaree %s", e, ECHELLE_DEFAUT)
        return ECHELLE_DEFAUT


def palier_atteint(profit_eur: float) -> float | None:
    """Le stop à poser, en euros de profit, pour ce profit atteint.

    Rend `None` sous le premier palier. 🔑 On prend le palier le PLUS HAUT
    franchi, pas le premier : à +1,80 € le stop va à +1,50 €, pas à +0,75 €.
    """
    retenu = None
    for seuil, cible in echelle():
        if profit_eur >= seuil - _TOLERANCE:
            retenu = cible
    return retenu


def tp_ecart_eur() -> float:
    """L'ecart entre le palier et l'objectif, en euros. Defaut 2,00.

    ⚠️ UN ECART NUL OU ILLISIBLE RETOMBE SUR 2,00, jamais sur zero : un
    objectif colle au cours ferait sortir le trade instantanement, et un
    reglage illisible ne doit pas produire ce comportement en silence.
    """
    brut = os.getenv("ECHELLE_TP_ECART_EUR", "").strip()
    if not brut:
        return TP_ECART_DEFAUT
    try:
        v = float(brut)
        if v <= 0:
            raise ValueError(f"ecart {v} <= 0")
        return v
    except Exception as e:  # noqa: BLE001
        logger.warning("ECHELLE_TP_ECART_EUR illisible (%s) — repli sur "
                       "%.2f EUR", e, TP_ECART_DEFAUT)
        return TP_ECART_DEFAUT


def tp_vise_eur(profit_eur: float) -> float | None:
    """L'objectif a poser, en euros de profit, ou ``None``.

    Regle de Xavier le 2026-10-09 : << toujours 2 euros d'ecart quand on se
    rapproche du TP : quand 1 euro est atteint, update SL:1 et TP:3 ; si 1,5
    est atteint, SL:1,5 et TP:3,5, etc. >>

    🔑 L'objectif suit le PALIER FRANCHI, pas le profit instantane : sinon il
    bougerait a chaque tick et le courtier recevrait un ordre de modification
    toutes les 15 s pour trois centimes.

    ⛔ `None` sous le premier palier : deplacer l'objectif d'une position qui
    n'a rien prouve serait gratuit.

    ⚠️ Et le SL, lui, ne change PAS d'un centime : la marge de 0,25 EUR choisie
    par Xavier apres mesure du spread (0,151 EUR) fait que `niveau - 0,25` est
    EXACTEMENT l'echelle deja en production. Seul le TP est nouveau.
    """
    # ⛔ ON PART DU SEUIL FRANCHI, PAS DE LA CIBLE DU STOP, et ma premiere
    # version confondait les deux. `palier_atteint` rend la CIBLE (0,75 pour un
    # seuil de 1,00) : l'objectif en aurait valu 2,75 au lieu des 3,00 que
    # Xavier a dictes. Son exemple est sans ambiguite -- << quand 1 euro est
    # atteint, TP:3 >> -- donc l'ecart se compte depuis le NIVEAU ATTEINT.
    seuil = seuil_atteint(profit_eur)
    if seuil is None:
        return None
    return seuil + tp_ecart_eur()


def seuil_atteint(profit_eur: float) -> float | None:
    """Le SEUIL de palier le plus haut franchi, ou ``None``.

    🔑 A distinguer de `palier_atteint`, qui rend la CIBLE DU STOP. Les deux
    existent parce que le stop et l'objectif ne se comptent pas depuis le meme
    point : le stop depuis sa cible, l'objectif depuis le niveau atteint.
    """
    retenu = None
    for seuil, _cible in echelle():
        if profit_eur >= seuil - _TOLERANCE:
            retenu = seuil
    return retenu


def stop_vise(entree: float, sens: str, profit_eur: float,
              taux_eur_usd: float) -> float | None:
    """Le prix du stop à poser, ou `None` s'il n'y a rien à faire.

    ⚠️ `entree` est le prix d'OUVERTURE de la position chez le courtier, pas
    le niveau du signal : c'est depuis lui que le profit se compte.
    """
    cible_eur = palier_atteint(profit_eur)
    if cible_eur is None:
        return None
    if not taux_eur_usd or taux_eur_usd <= 0:
        # ⛔ On ne devine pas une distance en euros sans le taux.
        return None
    signe = 1 if str(sens).lower() == "buy" else -1
    return entree + signe * cible_eur * taux_eur_usd


def _mieux(nouveau: float, actuel: float | None, sens: str) -> bool:
    """🔑 LE CLIQUET. Un stop ne remonte que dans le sens du profit.

    Sans cette comparaison, un sondage pendant un repli ferait REDESCENDRE le
    stop — l'inverse exact d'une protection, et le genre de défaut qui ne se
    voit qu'une fois qu'il a coûté.
    """
    if actuel is None or actuel == 0:
        return True
    return nouveau > actuel if str(sens).lower() == "buy" else nouveau < actuel


def decision(position: dict, taux_eur_usd: float,
             prix_courant: float | None = None) -> dict | None:
    """Ce qu'il faut faire de CETTE position, ou `None` si rien.

    Rend `{"ticket", "sl", "profit_eur", "palier"}`. Ne lève jamais : appelée
    en boucle sur des positions dont la forme vient du courtier.
    """
    try:
        if not arme():
            return None
        sym = str(position.get("symbol") or "").upper()
        if "XAU" not in sym and "GOLD" not in sym:
            return None
        # ⛔ Les positions ouvertes A LA MAIN dans le terminal ne portent pas
        # notre marque. Elles ne sont pas les notres : on n'y touche pas.
        if MARQUE_RADAR not in str(position.get("comment") or ""):
            return None
        sens = str(position.get("type") or "").lower()
        if sens not in ("buy", "sell"):
            return None
        entree = float(position.get("price_open") or 0)
        if entree <= 0:
            return None
        courant = float(prix_courant if prix_courant is not None
                        else (position.get("price_current") or 0))
        if courant <= 0:
            return None
        # 🔑 Le profit se compte en PRIX, pas depuis le champ `profit` du
        # courtier : celui-la inclut swap et commission, donc il franchirait
        # les paliers a des prix differents de ceux que Xavier a dictes.
        signe = 1 if sens == "buy" else -1
        profit_usd = signe * (courant - entree)
        profit_eur = profit_usd / taux_eur_usd if taux_eur_usd else 0.0
        cible = palier_atteint(profit_eur)
        if cible is None:
            return None
        sl = stop_vise(entree, sens, profit_eur, taux_eur_usd)
        if sl is None:
            return None
        actuel = position.get("sl")
        actuel = float(actuel) if actuel else None
        if not _mieux(sl, actuel, sens):
            return None
        # ⛔ Un stop du mauvais cote du prix serait refuse par le courtier, et
        # masquerait un defaut de signe derriere une erreur reseau.
        if sens == "buy" and sl >= courant:
            logger.warning("echelle[%s]: stop %.2f au-dessus du prix %.2f — "
                           "ignore", position.get("ticket"), sl, courant)
            return None
        if sens == "sell" and sl <= courant:
            logger.warning("echelle[%s]: stop %.2f sous le prix %.2f — "
                           "ignore", position.get("ticket"), sl, courant)
            return None
        # 🔑 L'OBJECTIF SUIT, a `tp_ecart_eur()` devant le palier. On rend un
        # PRIX, comme pour le stop : la lecon du defaut de signe du matin --
        # une distance se lit dans les deux sens, un prix non.
        tp = None
        vise_tp = tp_vise_eur(profit_eur)
        if vise_tp is not None:
            signe_tp = 1 if sens == "buy" else -1
            tp = round(entree + signe_tp * vise_tp * taux_eur_usd, 2)
        return {"ticket": position.get("ticket"), "sl": round(sl, 2),
                "tp": tp, "tp_eur": vise_tp,
                "profit_eur": round(profit_eur, 3), "palier": cible,
                "sl_actuel": actuel}
    except Exception as e:  # noqa: BLE001
        logger.warning("echelle: position illisible (%s)", e)
        return None
