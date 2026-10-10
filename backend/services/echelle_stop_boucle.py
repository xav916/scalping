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
from backend.services import equiper_trades_main as EQ

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


async def _poser(base: str, cle: str, ticket: int, sl: float,
                 tp: float | None = None) -> dict:
    """Appelle `/position/sltp` avec le PRIX du stop et `deplacer: true`.

    ⛔ CORRIGÉ LE 2026-10-09, et c'était un vrai défaut sur l'argent réel.
    Je passais `sl_dist`, une DISTANCE — or la route calcule toujours
    `price_open − sl_dist` pour un achat. Mon `abs()` perdait donc le signe, et
    un stop voulu à **+0,75 €** était posé à **−0,75 €** : au lieu de
    verrouiller un gain, ça plafonnait une perte.

    🔑 Mesuré sur deux trades réels avant correction : `#2013` et `#2014`, stop
    final à **−0,840 $ = −0,75 €** de l'entrée, du mauvais côté. Xavier l'a vu
    avant moi.

    ⇒ On passe désormais `sl_absolu`, un PRIX. Une « distance négative » aurait
    marché aussi, mais la prochaine lecture du code se demanderait dans quel
    sens — un prix ne laisse aucune ambiguïté.
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(
                base.rstrip("/") + "/position/sltp",
                json={"ticket": int(ticket), "sl_absolu": float(sl),
                      # 🔑 L'OBJECTIF SUIT AUSSI (2026-10-09). Omis quand il
                      # n'y a rien a poser : le pont PRESERVE alors le TP
                      # existant, il ne l'efface pas.
                      **({"tp_absolu": float(tp)} if tp else {}),
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
    # ⛔ L'EQUIPEUR NE DOIT PAS DEPENDRE DE L'ECHELLE (2026-10-10). Un
    # `ECHELLE_STOP_OR=0` laisserait sinon les trades a la main NUS, sans que
    # personne ne comprenne pourquoi : deux dispositifs distincts, deux
    # interrupteurs distincts.
    if not E.arme() and not EQ.arme():
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
             "deja_protege": 0, "refus_cliquet": 0, "echecs": [],
             # 2026-10-10 : les trades ouverts A LA MAIN qu'on vient de borner,
             # et ceux dont une borne etait DEJA FRANCHIE — ce dernier cas doit
             # se LIRE, pas disparaitre.
             "equipes": [], "alertes": []}
    for p in positions:
        # ─── Equiper les trades A LA MAIN (2026-10-10) ──────────────────
        #
        # 🔑 Mesure du 09/10 : 40 des 43 trades que Xavier ouvre dans le
        # terminal MT5 n'ont NI stop NI objectif chez le courtier, donc aucun
        # garde-fou ne les voit. Ses trois pires (258 min, 296 min, 19 min)
        # font -41,72 EUR a eux seuls.
        #
        # ⚠️ C'est fait ICI et non dans une seconde boucle : celle-ci lit deja
        # les positions et sait appeler `/position/sltp`. Un second sondeur
        # aurait double la lecture et derive.
        eq = EQ.decision(p, taux)
        if eq is not None:
            if eq.get("alerte"):
                bilan["alertes"].append(
                    {"ticket": eq["ticket"], "alerte": eq["alerte"],
                     "profit_eur": eq.get("profit_eur")})
            if eq.get("sl") or eq.get("tp"):
                r = await _poser(base, cle, eq["ticket"], eq.get("sl"),
                                 eq.get("tp"))
                if r.get("ok"):
                    bilan["equipes"].append(
                        {"ticket": eq["ticket"], "sl": eq.get("sl"),
                         "tp": eq.get("tp"), "motif": eq["motif"]})
                else:
                    bilan["echecs"].append(
                        {"ticket": eq["ticket"], "etape": "equipement",
                         "reponse": r})
                # 🔑 On ne passe PAS a l'echelle dans le meme tour : la
                # position vient d'etre bornee, l'echelle la verra au tour
                # suivant avec ses vraies bornes. Enchainer les deux ferait
                # deux ordres de modification pour le meme ticket.
                continue

        d = E.decision(p, taux)
        if d is None:
            continue
        # 🔑 On transmet le PRIX, pas la distance : c'est tout le correctif.
        if not d.get("sl"):
            continue
        r = await _poser(base, cle, d["ticket"], d["sl"], d.get("tp"))
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
                 "sl": r.get("sl"), "profit_eur": d["profit_eur"],
                 "clampe": bool(r.get("sl_clampe_par_le_courtier"))})
            if r.get("sl_clampe_par_le_courtier"):
                # ⛔ Croire qu'un stop est a +0,75 quand le courtier l'a
                # repousse ailleurs rendrait toute la mesure fausse.
                bilan["clampes"] = bilan.get("clampes", 0) + 1
                logger.warning(
                    "echelle: ticket %s — le COURTIER a repousse le stop : "
                    "demande %s, pose %s", d["ticket"],
                    r.get("sl_demande"), r.get("sl"))
            logger.warning(
                "echelle: ticket %s profit %.2f EUR -> palier %.2f, "
                "stop porte a %s", d["ticket"], d["profit_eur"],
                d["palier"], r.get("sl"))
        else:
            bilan["echecs"].append({"ticket": d["ticket"],
                                    "erreur": str(r)[:150]})
    return bilan
