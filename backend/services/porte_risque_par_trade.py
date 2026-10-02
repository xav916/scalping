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


# ⛔ LE PLANCHER SE LIT CHEZ LE COURTIER (2026-10-02). `LOT_MINIMUM` etait un
# litteral jamais confronte au pont. Verifie ce jour-la sur `/symbol_specs` :
# `volume_min 0.01`, `volume_step 0.01` sur XAUUSD, reel ET demo — le litteral
# etait juste. Mais juste PAR CHANCE, et tout le calcul du risque en depend :
# le risque vaut `lot x distance au stop`, le lot est bloque au plancher, donc
# un plancher faux rend un risque faux sans qu'aucune erreur ne soit levee.
#
# ⚠️ ASYMETRIE DU REPLI, assumee. Pont muet => litteral `0.01`, soit le
# comportement d'avant, donc aucune regression ; mais si le vrai plancher etait
# PLUS GRAND, ce repli sous-estime le risque. L'alternative — refuser de trader
# quand `/symbol_specs` est injoignable — couperait tout le flux pour une panne
# qui n'est pas celle de cette porte. Une lecture REUSSIE, elle, ne peut que
# rendre la porte plus stricte.
_SPECS_TTL_S = float(os.environ.get("SYMBOL_SPECS_CACHE_S", "900"))
_specs_cache: dict[tuple[str, str], tuple[float, dict | None]] = {}


def _lire_specs(dest, symbole: str) -> dict | None:
    """`GET /symbol_specs/<symbole>`, ou `None` si la lecture rate."""
    import time

    url = (getattr(dest, "bridge_url", "") or "").rstrip("/")
    if not url or not symbole:
        return None
    cle = (str(getattr(dest, "destination_id", "") or url), symbole)
    en_cache = _specs_cache.get(cle)
    if en_cache and (time.time() - en_cache[0]) < _SPECS_TTL_S:
        return en_cache[1]
    entetes = {}
    if getattr(dest, "bridge_api_key", None):
        entetes["X-API-Key"] = dest.bridge_api_key
    specs = None
    try:
        import httpx
        with httpx.Client(timeout=5.0) as c:
            r = c.get(f"{url}/symbol_specs/{symbole}", headers=entetes)
        if r.status_code == 200:
            lu = r.json()
            specs = lu if isinstance(lu, dict) else None
    except Exception as e:  # noqa: BLE001 — toute panne = on ne sait pas
        logger.info("porte_risque_par_trade: /symbol_specs/%s illisible (%s)",
                    symbole, e)
    _specs_cache[cle] = (time.time(), specs)
    return specs


def _plancher_declare(specs: dict | None) -> float | None:
    """Le plus petit ordre REELLEMENT acceptable, ou `None` si indecidable.

    ⛔ Le PAS fait loi quand il depasse le minimum : un `volume_min` de 0,01
    avec un `volume_step` de 0,05 ne permet pas 0,01 — le plus petit ordre
    vaut 0,05. Prendre le minimum seul sous-estimerait le risque.
    """
    if not isinstance(specs, dict):
        return None
    valeurs = []
    for cle in ("volume_min", "volume_step"):
        try:
            v = float(specs.get(cle))
        except (TypeError, ValueError):
            continue
        if v > 0:
            valeurs.append(v)
    return max(valeurs) if valeurs else None


def _lot_minimum(dest, pair: str | None = None) -> float | None:
    """Le plus petit ordre acceptable : celui du COURTIER, sinon le litteral.

    `None` quand la question ne se pose pas — une route dont le `bridge_type`
    n'a pas de plancher declare.
    """
    litteral = LOT_MINIMUM.get(getattr(dest, "bridge_type", "") or "")
    if litteral is None:
        return None
    if not pair or not (getattr(dest, "bridge_url", "") or ""):
        return litteral
    try:
        from backend.services.mt5_bridge import _symbole_courtier_pour
        symbole = _symbole_courtier_pour(pair, dest)
    except Exception:  # noqa: BLE001
        return litteral
    declare = _plancher_declare(_lire_specs(dest, symbole))
    return declare if declare is not None else litteral


def risque_au_lot_minimum(setup, dest) -> float | None:
    """Risque en EUROS du plus petit ordre que ce courtier accepte.

    ``None`` si la question ne se pose pas (route hors MT5) ou si le montant
    est indécidable. ⛔ Indécidable ne vaut jamais zéro : l'appelant ne doit
    pas lire « pas de risque » là où on n'a pas su le calculer.
    """
    lot = _lot_minimum(dest, getattr(setup, "pair", None))
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
        risque, _lot_minimum(dest, getattr(setup, "pair", None)) or 0,
        plafond, PLAFOND_PCT, float(capital))
    return MOTIF
