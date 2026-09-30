"""Mesure du risque engagé, un dialecte par type de bridge (2026-08-25).

Chaque courtier rend ses positions dans une forme différente. MT5 porte le
stop DANS la position et permet de dériver le risque du profit rapporté ;
Kraken et IBKR n'ont ni profit ni prix courant dans leur charge de position,
et leur stop vit dans un ordre séparé.

⛔ La mesure MT5 n'est PAS réécrite ici : elle est importée de
`scripts/notify_saturation_risque.py`, couverte par 24 tests et vérifiée au
centime près contre les positions réelles du 23/08. Une seconde
implémentation serait l'endroit exact où les deux chiffres divergeraient.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

DELAI = 10

DESTINATIONS_MESUREES = (
    "admin_live", "admin_legacy", "admin_kraken",
    "admin_kraken_spot", "admin_ibkr_us",
)


def _appel(dest, chemin: str):
    """GET sur un bridge. Rend `(charge, lecture_reussie)`."""
    url = os.environ.get(getattr(dest, "url_env", "") or "", "")
    if not url:
        return None, False
    cle = os.environ.get(getattr(dest, "key_env", "") or "", "")
    entete = getattr(dest, "key_header", "") or ""
    entetes = {entete: cle} if cle and entete else {}
    try:
        rq = urllib.request.Request(url.rstrip("/") + chemin, headers=entetes)
        with urllib.request.urlopen(rq, timeout=DELAI) as r:
            if r.status != 200:
                return None, False
            return json.load(r), True
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        logger.info("risque_engage: %s injoignable (%s)", chemin, e)
        return None, False


def evaluation_illisible(devise: str = "EUR") -> dict:
    """⛔ Muet n'est pas sain. Un bridge injoignable ne vaut pas « 0 € »."""
    return {
        "lisible": False, "indecidable": True,
        "risque_total": None, "plafond": None, "pct": None, "restant": None,
        "nues": 0, "non_mesurables": 0, "positions": 0,
        "candidats": 0, "liberable": 0.0, "login": None, "devise": devise,
    }


def _dialecte_mt5(dest) -> dict:
    from scripts.notify_saturation_risque import _lire_destination
    e = _lire_destination(dest)
    e["devise"] = "EUR"
    return e


def risque_position_stop(entree, stop, taille) -> float | None:
    """`|entrée − stop| × taille`, en devise de cotation.

    ⛔ Rend `None`, jamais `0.0`, dès qu'une donnée manque : zéro dirait
    « aucun risque » quand la vérité est « on ne sait pas ». Seul un stop
    EXACTEMENT à l'entrée rend un vrai zéro — la position ne peut plus perdre,
    et c'est une mesure.
    """
    try:
        e, s, t = float(entree), float(stop), float(taille)
    except (TypeError, ValueError):
        return None
    if e <= 0 or t <= 0 or s < 0:
        return None
    return abs(e - s) * t


def _stops_reduce_only(charge: dict) -> dict:
    """`{symbole: prix de déclenchement}` depuis les ordres vivants.

    ⛔ Un ordre ne protège une position que s'il la RÉDUIT. Un ordre d'entrée
    en attente sur le même symbole n'est pas une protection ; le compter ferait
    passer pour bornée une position qui ne l'est pas.
    """
    stops = {}
    for o in (charge or {}).get("orders") or []:
        if not isinstance(o, dict):
            continue
        if not o.get("reduceOnly"):
            continue
        if (o.get("orderType") or "").lower() not in ("stp", "stop"):
            continue
        sym, prix = o.get("symbol"), o.get("stopPrice")
        if sym and prix is not None:
            try:
                stops[sym] = float(prix)
            except (TypeError, ValueError):
                continue
    return stops


def evaluer_positions_stop(positions, stops, devise,
                           cle_symbole="symbol", cle_entree="price",
                           cle_taille="size") -> dict:
    """Somme les risques de positions dont le stop vit dans un ordre séparé.

    ⛔ Pas de plafond sur ces destinations : `plafond`, `pct` et `restant`
    valent `None`. Inventer un pourcentage donnerait un chiffre d'apparence
    comparable à MT5 sans mesurer la même chose.
    """
    total, nues, non_mesurables = 0.0, 0, 0
    for p in positions or []:
        if not isinstance(p, dict):
            non_mesurables += 1
            continue
        sym = p.get(cle_symbole)
        if sym not in stops:
            nues += 1
            continue
        r = risque_position_stop(p.get(cle_entree), stops[sym], p.get(cle_taille))
        if r is None:
            non_mesurables += 1
            continue
        total += r
    return {
        "lisible": True,
        "indecidable": bool(nues or non_mesurables),
        "risque_total": total, "plafond": None, "pct": None, "restant": None,
        "nues": nues, "non_mesurables": non_mesurables,
        "positions": len(positions or []),
        "candidats": 0, "liberable": 0.0, "login": None, "devise": devise,
        "sans_plafond": True,
    }


def _dialecte_kraken_futures(dest) -> dict:
    """Kraken Futures : ni profit, ni prix courant dans la position — le
    stop vit dans un ordre `reduceOnly` séparé, lu sur `/openorders`.

    ⛔ Aucun changement de bridge : `/openorders` expose déjà `stopPrice`,
    `reduceOnly` et `orderType`. Les tailles PF_* sont en actif de base
    direct, donc aucun multiplicateur de contrat.
    """
    pos, ok = _appel(dest, "/positions")
    if not ok or not isinstance(pos, dict) or not isinstance(pos.get("positions"), list):
        return evaluation_illisible("USD")
    oo, ok = _appel(dest, "/openorders")
    if not ok or not isinstance(oo, dict):
        return evaluation_illisible("USD")
    return evaluer_positions_stop(pos.get("positions"), _stops_reduce_only(oo),
                                  devise="USD")


def evaluation_spot(charge: dict) -> dict:
    """Risque du spot Kraken, dont le stop vit dans un watcher LOGICIEL.

    ⚠️ `stop_logiciel=True` n'est pas cosmétique : un watcher est un thread du
    bridge, pas un ordre du carnet. Il meurt avec le processus. Le présenter
    comme un stop courtier surestimerait la protection.
    """
    watchers = (charge or {}).get("active_watchers") or []
    total, non_mesurables = 0.0, 0
    for w in watchers:
        if not isinstance(w, dict):
            non_mesurables += 1
            continue
        r = risque_position_stop(w.get("entry"), w.get("sl"), w.get("qty"))
        if r is None:
            non_mesurables += 1
            continue
        total += r
    positions = (charge or {}).get("positions") or []
    # Une position sans watcher n'a AUCUN stop : risque non borné.
    nues = max(0, len(positions) - len(watchers))
    return {
        "lisible": True,
        "indecidable": bool(nues or non_mesurables),
        "risque_total": total, "plafond": None, "pct": None, "restant": None,
        "nues": nues, "non_mesurables": non_mesurables,
        "positions": len(positions),
        "candidats": 0, "liberable": 0.0, "login": None, "devise": "USD",
        "sans_plafond": True, "stop_logiciel": True,
    }


def _dialecte_kraken_spot(dest) -> dict:
    charge, ok = _appel(dest, "/positions")
    if not ok or not isinstance(charge, dict):
        return evaluation_illisible("USD")
    return evaluation_spot(charge)


def _stops_ibkr(charge: dict, sens_position: dict) -> dict:
    """`{symbole: prix de déclenchement}` pour les ordres qui RÉDUISENT.

    ⛔ Un ordre de même sens que la position l'agrandit, il ne la protège pas.
    Une position longue est protégée par un stop `SELL`, et l'inverse.
    """
    stops = {}
    for o in (charge or {}).get("orders") or []:
        if not isinstance(o, dict):
            continue
        if (o.get("orderType") or "").upper() not in ("STP", "STP LMT"):
            continue
        sym = o.get("symbol")
        if not sym or sym not in sens_position:
            continue
        reduit = ((o.get("action") or "").upper() == "SELL"
                  if sens_position[sym] > 0
                  else (o.get("action") or "").upper() == "BUY")
        if not reduit:
            continue
        prix = o.get("auxPrice")
        if prix is None:
            continue
        try:
            stops[sym] = float(prix)
        except (TypeError, ValueError):
            continue
    return stops


def evaluation_ibkr(positions_charge: dict, ordres_charge: dict) -> dict:
    """Risque engagé chez IBKR : le stop est un ordre ENFANT de bracket.

    ⛔ `/positions` ne porte ni stop ni prix courant — le risque d'une
    position n'y est donc pas dérivable. L'appariement se fait par symbole
    ET par sens.
    """
    positions = (positions_charge or {}).get("positions") or []
    sens = {}
    for p in positions:
        if not isinstance(p, dict):
            continue
        try:
            sens[p.get("symbol")] = float(p.get("position") or 0.0)
        except (TypeError, ValueError):
            continue
    stops = _stops_ibkr(ordres_charge, sens)
    normalisees = []
    for p in positions:
        if not isinstance(p, dict):
            normalisees.append(None)
            continue
        try:
            taille = abs(float(p.get("position") or 0.0))
        except (TypeError, ValueError):
            taille = 0.0
        normalisees.append({"symbol": p.get("symbol"),
                            "price": p.get("avg_cost"), "size": taille})
    return evaluer_positions_stop(normalisees, stops, devise="USD")


def _dialecte_ibkr(dest) -> dict:
    pos, ok = _appel(dest, "/positions")
    if not ok or not isinstance(pos, dict):
        return evaluation_illisible("USD")
    oo, ok = _appel(dest, "/openorders")
    if not ok or not isinstance(oo, dict):
        return evaluation_illisible("USD")
    return evaluation_ibkr(pos, oo)


# Clés = `Destination.bridge_type`, relevées dans le registre le 2026-08-25 :
#   admin_legacy / admin_live -> "mt5"      admin_kraken      -> "kraken"
#   admin_kraken_spot         -> "kraken_spot"  admin_ibkr_us -> "ibkr"
DIALECTES = {
    "mt5": _dialecte_mt5,
    "kraken": _dialecte_kraken_futures,
    "kraken_spot": _dialecte_kraken_spot,
    "ibkr": _dialecte_ibkr,
}


def mesurer_destination(dest) -> dict:
    """Mesure une destination via son dialecte. Toute panne ⇒ `illisible`."""
    dialecte = DIALECTES.get(getattr(dest, "bridge_type", ""))
    if dialecte is None:
        logger.warning("risque_engage: aucun dialecte pour bridge_type=%r "
                       "(destination %s)", getattr(dest, "bridge_type", None),
                       getattr(dest, "id", "?"))
        return evaluation_illisible()
    try:
        return dialecte(dest)
    except Exception:
        logger.exception("risque_engage: dialecte en échec sur %s",
                         getattr(dest, "id", "?"))
        return evaluation_illisible()


def verdict_destination(evaluation: dict, seuil_pct: float) -> str:
    """Verdict d'une destination, plafond ou pas.

    ⛔ `verdict()` de la sonde rend `indecidable` dès que `pct is None`. C'est
    juste pour MT5 — un pourcentage absent y signale une mesure impossible —
    et faux pour Kraken et IBKR : **n'avoir aucun plafond n'est pas ne pas
    savoir.** Sans ce filtre, la production dirait `indecidable` sur toutes
    les destinations non-MT5.

    ⛔ Et `verdict()` ne peut PAS être corrigée à la place : elle est partagée
    avec la sonde horaire de saturation, dont elle commande le seuil d'alerte.
    """
    from scripts.notify_saturation_risque import verdict

    if (evaluation.get("sans_plafond")
            and evaluation.get("lisible")
            and not evaluation.get("indecidable")):
        return "sans_plafond"
    return verdict(evaluation, seuil_pct)


def taux_eurusd() -> float | None:
    """Combien d'USD pour 1 EUR, lu sur un bridge MT5 déjà authentifié.

    ⛔ Rend `None` sur toute lecture ratée. L'appelant refuse alors de
    convertir et de sommer : un taux approximatif produirait un total
    crédible et faux.
    """
    from backend.services.destinations_registry import DESTINATIONS
    for did in ("admin_live", "admin_legacy"):
        dest = DESTINATIONS.get(did)
        if dest is None:
            continue
        charge, ok = _appel(dest, "/tick/EUR/USD")
        if not ok or not isinstance(charge, dict):
            continue
        try:
            bid, ask = float(charge["bid"]), float(charge["ask"])
        except (TypeError, ValueError, KeyError):
            continue
        if bid > 0 and ask > 0:
            return (bid + ask) / 2.0
    return None


def en_euros(montant, devise: str, taux) -> float | None:
    """Convertit en euros. `None` dès que la conversion n'est pas sûre."""
    if montant is None:
        return None
    if (devise or "EUR").upper() == "EUR":
        return montant
    try:
        t = float(taux)
    except (TypeError, ValueError):
        return None
    if t <= 0:
        return None
    return montant / t


def mesurer(destination_ids: tuple[str, ...] = DESTINATIONS_MESUREES) -> list[dict]:
    """Une mesure par destination, dans l'ordre donné. Bloquant."""
    from backend.services.destinations_registry import DESTINATIONS
    from scripts.notify_saturation_risque import SEUIL_PCT

    mesures = []
    for did in destination_ids:
        dest = DESTINATIONS.get(did)
        if dest is None:
            continue
        evaluation = mesurer_destination(dest)
        mesures.append({
            "id": did, "badge": dest.badge,
            "evaluation": evaluation,
            "verdict": verdict_destination(evaluation, SEUIL_PCT),
        })
    return mesures
