"""Applique l'échelle de stop de l'or aux positions ouvertes.

Branchée sur le réel à la demande explicite de Xavier, 2026-10-09.
Décision et prédictions : `docs/concepts-trading.md`, commit `87d3ee0`.
Les paliers vivent dans `echelle_stop_or` ; ce module ne fait que **sonder,
décider, appeler**.

## 🔑 Pourquoi `deplacer: true` est nécessaire

`/position/sltp` était un **no-op** dès que la position avait un stop : elle est
écrite pour protéger une position **nue**. Sans le paramètre ajouté le même
jour, cette boucle aurait tourné en rendant `already_protected: true` à chaque
passage — elle aurait eu l'air de fonctionner sans **jamais** rien déplacer.

⛔ C'est précisément la forme de silence que ce dépôt a déjà payée plusieurs
fois. D'où le décompte explicite des `already_protected` dans le bilan.

## Ce que le sondage ne peut pas faire

Entre deux passages, le prix peut franchir un palier **et revenir** sans que
l'échelle l'ait vu. Elle est donc **moins réactive** que l'échelle simulée, et
l'écart grandit avec l'intervalle. Seule une logique côté MT5 serait continue.
"""
from __future__ import annotations

import logging
import os

import httpx

from backend.services import echelle_stop_or as E

logger = logging.getLogger(__name__)

TIMEOUT = 10.0


def _taux() -> float | None:
    from backend.services.pattern_detector import _eur_usd_courant
    return _eur_usd_courant()


async def _positions(base: str, cle: str) -> list[dict] | None:
    """Les positions du courtier, ou ``None`` s'il est muet.

    ⛔ ``None`` et non ``[]`` : « je ne sais pas » n'est pas « il n'y a rien ».
    Une liste vide ferait conclure qu'aucune position n'a besoin de l'échelle.
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get(base.rstrip("/") + "/positions",
                            headers={"X-API-Key": cle})
            if r.status_code != 200:
                logger.warning("echelle: /positions a rendu %s", r.status_code)
                return None
            return (r.json() or {}).get("positions") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("echelle: pont muet (%s)", e)
        return None


async def _poser(base: str, cle: str, ticket: int, sl_dist: float) -> dict:
    """Appelle `/position/sltp` avec `deplacer: true`.

    ⚠️ `sl_dist` est une DISTANCE depuis `price_open`, jamais un prix absolu :
    c'est le contrat de la route, et lui passer un prix placerait le stop à des
    milliers de dollars de l'entrée.
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(
                base.rstrip("/") + "/position/sltp",
                json={"ticket": int(ticket), "sl_dist": float(sl_dist),
                      "deplacer": True},
                headers={"X-API-Key": cle})
            try:
                corps = r.json()
            except Exception:
                corps = {"brut": r.text[:200]}
            return {"status": r.status_code, **corps}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def appliquer() -> dict:
    """Un passage. Rend un bilan lisible, ne lève jamais."""
    if not E.arme():
        return {"arme": False}
    base = os.getenv("MT5_BRIDGE_LIVE_URL", "")
    cle = os.getenv("MT5_BRIDGE_LIVE_API_KEY", "")
    if not base or not cle:
        return {"arme": True, "erreur": "pont live non configure"}

    taux = _taux()
    if not taux or taux <= 0:
        # ⛔ Sans le taux, les paliers en euros sont inconvertibles. On ne
        # devine pas une distance de stop sur l'argent reel.
        logger.warning("echelle: taux EUR/USD illisible — aucun deplacement")
        return {"arme": True, "erreur": "taux illisible"}

    positions = await _positions(base, cle)
    if positions is None:
        return {"arme": True, "erreur": "positions illisibles"}

    bilan = {"arme": True, "positions": len(positions), "deplaces": [],
             "deja_protege": 0, "refus_cliquet": 0, "echecs": []}
    for p in positions:
        d = E.decision(p, taux)
        if d is None:
            continue
        entree = float(p.get("price_open") or 0)
        sl_dist = abs(entree - d["sl"])
        if sl_dist <= 0:
            continue
        r = await _poser(base, cle, d["ticket"], sl_dist)
        # 🔑 `already_protected` est compte A PART : c'est le symptome exact du
        # cas ou la route refuse de deplacer. Le confondre avec un succes
        # ferait croire que l'echelle tourne alors qu'elle ne fait rien.
        if r.get("already_protected"):
            bilan["deja_protege"] += 1
            logger.warning(
                "echelle: ticket %s NON deplace — %s. Le drapeau "
                "SLTP_DEPLACEMENT_ENABLED est-il pose sur le pont ?",
                d["ticket"], r.get("motif_no_op"))
        elif r.get("refus_cliquet"):
            bilan["refus_cliquet"] += 1
        elif r.get("ok"):
            bilan["deplaces"].append(
                {"ticket": d["ticket"], "palier": d["palier"],
                 "sl": r.get("sl"), "profit_eur": d["profit_eur"]})
            logger.warning(
                "echelle: ticket %s profit %.2f EUR -> palier %.2f, "
                "stop porte a %s", d["ticket"], d["profit_eur"],
                d["palier"], r.get("sl"))
        else:
            bilan["echecs"].append({"ticket": d["ticket"],
                                    "erreur": str(r)[:150]})
    return bilan
