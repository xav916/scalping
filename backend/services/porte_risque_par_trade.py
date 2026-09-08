"""Refuse un trade qu'on ne peut PAS dimensionner dans le budget de risque.

Posé le 2026-09-08. Mesure qui l'a motivé, sur les 21 trades or du compte réel
depuis le 25/08 :

```
cible configurée   : 1 % par trade   →   6,50 €
or, en médiane     : 2,6 %           →  18,61 €
or, au pire        : 9,2 %           →  65,64 €
plafond de perte journalière : 3 %
```

⛔ **Une seule position pouvait engager trois fois la perte maximale de la
journée.** Ces deux réglages sont logiquement incompatibles, et c'est le
plafond par trade qui manquait.

## 🔑 Pourquoi la porte juge au LOT MINIMUM

Les 21 trades or sont partis à `0,01 lot` — le plancher du courtier, sans
exception. Le dimensionnement calcule bien ~6,50 €, mais il tombe SOUS ce
plancher et le bridge remonte au minimum. Le risque réel n'est donc pas choisi,
il est **subi** : il vaut ce que la distance du stop en fait.

Réduire la taille est impossible — elle est déjà au plus bas. La seule décision
qui reste est binaire : **prendre le trade, ou le refuser**. C'est exactement ce
que fait cette porte, et c'est pourquoi elle ne « clampe » rien.

⚠️ Elle ne juge PAS la qualité du signal, seulement la taille de la perte
possible. Un signal excellent dont le stop est trop loin reste refusé — et
c'est voulu : aucune conviction ne rend acceptable de risquer 9 % du compte sur
une position quand la journée entière est bornée à 3 %.

## Portée volontairement étroite

Restreinte aux routes **MT5**. Sur Kraken le volume est une quantité à
granularité fine : le dimensionnement y descend réellement, le plancher ne mord
pas, et poser la porte là refuserait des trades correctement dimensionnés.
Nommer ce qui est EXCLU plutôt que filtrer par classe — la leçon des 14 cryptos
recoupées le 23/08.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Plancher du courtier, par famille de bridge. C'est lui qui rend le risque
# incompressible : en dessous, l'ordre est remonté.
LOT_MINIMUM: dict[str, float] = {"mt5": 0.01}

# ⚠️ 5 % et non 3 % (la limite journalière) : à 3 % la porte refusait 8 trades
# sur 21 et remodelait la population, ce qui aurait changé ce qu'on mesure en
# même temps qu'on le mesure. À 5 % elle refuse les DEUX extrêmes et laisse le
# reste intact. Réglable sans redéploiement.
PLAFOND_PCT = float(os.environ.get("PLAFOND_RISQUE_PAR_TRADE_PCT", "5.0"))

MOTIF = "risque_par_trade_excessif"


def _lot_minimum(dest) -> float | None:
    return LOT_MINIMUM.get(getattr(dest, "bridge_type", "") or "")


def risque_au_lot_minimum(setup, dest) -> float | None:
    """Risque en EUROS du plus petit ordre que ce courtier accepte.

    ``None`` si la question ne se pose pas (route hors MT5) ou si le montant
    est indécidable. ⛔ Indécidable ne vaut jamais zéro : l'appelant ne doit
    pas lire « pas de risque » là où on n'a pas su le calculer.
    """
    lot = _lot_minimum(dest)
    if lot is None:
        return None
    try:
        entree = float(getattr(setup, "entry_price", 0) or 0)
        stop = float(getattr(setup, "stop_loss", 0) or 0)
    except (TypeError, ValueError):
        return None
    if entree <= 0 or stop <= 0 or entree == stop:
        return None

    from backend.services.risk_eur import calculer
    sens = 1 if str(getattr(setup, "direction", "")).lower().endswith("buy") else -1
    distance = abs(entree - stop)
    try:
        r = calculer(pair=getattr(setup, "pair", None), entry=entree, sl=stop,
                     tp=entree + sens * distance * 1.8, volume=lot,
                     bridge_type=getattr(dest, "bridge_type", "mt5"))
    except Exception as e:  # noqa: BLE001
        logger.debug(f"porte_risque_par_trade: calcul impossible — {e}")
        return None
    return r.get("risque_eur") if isinstance(r, dict) else None


def refus(setup, dest) -> str | None:
    """``MOTIF`` si même l'ordre minimal dépasse le plafond, sinon ``None``.

    ⛔ Fail-OUVERT délibéré : un risque qu'on ne sait pas calculer ne bloque
    pas. Cette porte est un plafond ajouté par-dessus des portes existantes —
    la rendre bloquante sur l'inconnu couperait le flux entier le jour où le
    taux EUR/USD ou le capital devient illisible, pour un défaut qui n'est pas
    le sien. Le risque non borné, lui, est déjà refusé en amont.
    """
    if dest is None or PLAFOND_PCT <= 0:
        return None
    risque = risque_au_lot_minimum(setup, dest)
    if risque is None:
        return None

    from backend.services.sizing import destination_capital
    capital, _ = destination_capital(dest)
    if not capital or capital <= 0:
        return None

    plafond = float(capital) * PLAFOND_PCT / 100.0
    if risque <= plafond:
        return None
    logger.info(
        "porte_risque_par_trade[%s] %s : %.2f EUR au lot minimum (%.2f) "
        "> plafond %.2f EUR (%.1f %% de %.2f) — indimensionnable, refusé",
        getattr(dest, "destination_id", "?"), getattr(setup, "pair", "?"),
        risque, _lot_minimum(dest) or 0, plafond, PLAFOND_PCT, float(capital))
    return MOTIF
