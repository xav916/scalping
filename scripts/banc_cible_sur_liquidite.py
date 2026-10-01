#!/usr/bin/env python3
"""Banc de la CIBLE SUR LA LIQUIDITÉ — prédictions déclarées dans `3c522e8`.

Question : poser l'objectif sur un plafond DÉJÀ ATTEINT par le prix vaut-il
mieux que le `risque × 1,8` arithmétique en place ?

⛔ CE QUI EST RÉUTILISÉ, JAMAIS RÉÉCRIT
`_issue`, `detections`, `controle_aleatoire`, `_stat`, `_welch`,
`plafond_hasard`, `PLACEBO_PCT`, `FENETRE`, `_bougies_et_spread`,
`niveaux_liquidite`, `POC_RR_MIN`. Une seconde arithmétique du risque ou de la
sortie produirait des chiffres incomparables à ceux du laboratoire.

⛔ LE NIVEAU EST LU DANS LA FENÊTRE VUE PAR LE DÉTECTEUR
`bougies[i-FENETRE:i]`, pas une bougie de plus. La bougie d'entrée porte le
haut qui déclenche le motif : l'inclure placerait la cible sur un sommet que le
détecteur n'a pas vu, et fabriquerait l'edge qu'on cherche à mesurer.

⛔ LE REJEU EST SÉQUENTIEL PAR VARIANTE
Un objectif plus proche sort plus tôt et décale toutes les entrées suivantes.
Chaque variante a donc SA suite d'entrées — c'est voulu, la question est « que
vaut le système avec cette cible-là ». Conséquence à dire : l'écart entre deux
variantes mêle un effet de GESTION et un effet de POPULATION, et c'est
précisément pourquoi D existe.

⛔ D PORTE L'ADMISSION DE B, PAS CELLE DE A
Le placebo de longueur doit refuser exactement ce que B refuse, sinon il
mesurerait aussi le filtre. Il ne regarde ensuite AUCUN niveau : son objectif
est un nombre fixe, la médiane de ceux de B.
"""

from __future__ import annotations

import os
import statistics as st
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.models.schemas import Candle  # noqa: E402
from backend.services import laboratoire_or as labo  # noqa: E402
from backend.services import market_profile as mp  # noqa: E402
from backend.services import reglage_or as reg  # noqa: E402
from backend.services.pattern_detector import POC_RR_MIN  # noqa: E402

PAIRE = os.getenv("BANC_PAIRE", "XAU/USD")
JOURS_TOTAL = int(os.getenv("BANC_JOURS_TOTAL", "365"))
JOURS_VUS = int(os.getenv("BANC_JOURS_VUS", "90"))
GRAINES = int(os.getenv("BANC_GRAINES", "30"))
SPREAD = os.getenv("BANC_SPREAD")

VARIANTES = ("A_reference", "B_plafonnee", "C_niveau_seul", "D_placebo_longueur")

# Reprise telle quelle du garde-fou de `test_hors_echantillon_fvg_up.py` : une
# mesure doit REFUSER de publier un chiffre absurde plutôt que de rendre un `t`
# calculé sur deux distributions ruinées par le coût.
COUT_MAX_R = float(os.getenv("BANC_COUT_MAX_R", "0.25"))


def _horodatage(b):
    for cle in ("t", "time", "ts", "date", "datetime"):
        if cle in b:
            return b[cle]
    raise KeyError("aucun champ de temps dans la bougie : %s" % list(b)[:8])


def _en_date(v):
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, tz=timezone.utc)
    d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _objets(bougies, debut: int, fin: int) -> list[Candle]:
    """Bougies brutes -> `Candle`, meme conversion que `detections._obj`."""
    out = []
    for x in bougies[debut:fin]:
        d = x["t"]
        if not isinstance(d, datetime):
            d = _en_date(d)
        out.append(Candle(timestamp=d, open=float(x["o"]), high=float(x["h"]),
                          low=float(x["l"]), close=float(x["c"]),
                          volume=float(x.get("tv") or 0.0)))
    return out


def _objectif_niveau(bougies, i: int, entree: float, risque: float,
                     signe: int):
    """L'objectif EN R porte par le niveau de liquidite, ou `None`.

    `None` quand le profil ne rend aucun niveau, ou quand le niveau est du
    mauvais cote de l'entree — c'est-a-dire quand le prix entre DANS son
    plafond. C'est un refus, pas un repli.
    """
    fen = _objets(bougies, i - labo.FENETRE, i)
    liq = mp.niveaux_liquidite(fen)
    niveau = liq.get("au_dessus") if signe > 0 else liq.get("en_dessous")
    if niveau is None:
        return None
    distance = signe * (float(niveau) - entree)
    if distance <= 0:
        return None
    return distance / risque


def rejeu(bougies, releve, motif, sens, spread, variante, objectif_fixe=None):
    """Les trades de cette cellule sous cette variante d'objectif."""
    trades = []
    signe = 1 if sens == "buy" else -1
    i, n = labo.FENETRE, len(bougies)
    while i < n:
        cands = [s for s in releve.get(i, ())
                 if labo._nom_motif(s) == motif and labo._sens(s) == sens]
        if not cands:
            i += 1
            continue
        s = cands[0]
        entree = float(s.entry_price)
        risque = abs(entree - float(s.stop_loss))
        if risque <= 0 or entree <= 0 or risque / entree < labo.PLACEBO_PCT:
            i += 1
            continue
        objectif_ref = abs(float(s.take_profit_1) - entree) / risque
        if objectif_ref <= 0:
            i += 1
            continue

        if variante == "A_reference":
            objectif = objectif_ref
        else:
            niveau_r = _objectif_niveau(bougies, i, entree, risque, signe)
            if niveau_r is None:
                i += 1
                continue
            if variante == "B_plafonnee":
                objectif = min(objectif_ref, niveau_r)
            elif variante == "C_niveau_seul":
                objectif = niveau_r
            elif variante == "D_placebo_longueur":
                # Admission de B — puis un objectif qui ne regarde RIEN.
                if min(objectif_ref, niveau_r) < POC_RR_MIN:
                    i += 1
                    continue
                objectif = float(objectif_fixe)
            else:
                raise KeyError("variante inconnue : %r" % variante)
            if variante != "D_placebo_longueur" and objectif < POC_RR_MIN:
                i += 1
                continue

        R, sortie = labo._issue(bougies, i, entree, risque, objectif, signe,
                                spread / risque)
        trades.append({"R": R, "risque": risque, "objectif_r": objectif,
                       "cout": spread / risque, "sens": sens})
        i = sortie + 1
    return trades


def mesurer(bougies, spread, cellules, releve, variante, objectif_fixe=None):
    tous, n_sens = [], {"buy": 0, "sell": 0}
    for motif, sens in cellules:
        tr = rejeu(bougies, releve, motif, sens, spread, variante, objectif_fixe)
        tous.extend(tr)
        n_sens[sens] = n_sens.get(sens, 0) + len(tr)
    if len(tous) < 10:
        return None
    R = [t["R"] for t in tous]
    moyenne, t_brut = labo._stat(R)
    risque_med = st.median(t["risque"] for t in tous)
    objectif_med = st.median(t["objectif_r"] for t in tous)
    cout = spread / risque_med if risque_med > 0 else float("inf")
    if cout > COUT_MAX_R:
        return {"n": len(R), "refus": "cout %.2f R/trade > %.2f" % (cout, COUT_MAX_R)}

    Rc = []
    for g in range(GRAINES):
        for sens, combien in n_sens.items():
            if combien <= 0:
                continue
            Rc.extend(x["R"] for x in labo.controle_aleatoire(
                bougies, spread, combien, risque_med, objectif_med,
                graine=g, sens=sens))
    if len(Rc) < 10:
        return {"n": len(R), "refus": "controle vide"}
    moy_c, ec_c = st.mean(Rc), st.pstdev(Rc)
    t_vs = labo._welch(moyenne, st.pstdev(R), len(R), moy_c, ec_c, len(Rc))
    return {"n": len(R), "r_moyen": moyenne, "t_brut": t_brut,
            "objectif_med": objectif_med, "cout": cout, "r_hasard": moy_c,
            "ecart_hasard": ec_c, "t_vs_hasard": t_vs, "refus": None,
            "objectifs": [t["objectif_r"] for t in tous]}


def fenetre(bougies, spread, titre):
    print("\n=== %s — %d bougies M5, spread %.4f" % (titre, len(bougies), spread))
    releve = labo.detections(bougies, PAIRE)
    cellules = sorted({(labo._nom_motif(s), labo._sens(s))
                       for lot in releve.values() for s in lot})
    print("  %d cellules motif x sens" % len(cellules))

    res = {}
    # B d'abord : D a besoin de la mediane de ses objectifs.
    for v in ("A_reference", "B_plafonnee", "C_niveau_seul"):
        res[v] = mesurer(bougies, spread, cellules, releve, v)
    med_b = None
    if res.get("B_plafonnee") and res["B_plafonnee"].get("objectifs"):
        med_b = st.median(res["B_plafonnee"]["objectifs"])
    res["D_placebo_longueur"] = None
    if med_b:
        print("  objectif FIXE du placebo D : %.3f R (mediane de B)" % med_b)
        res["D_placebo_longueur"] = mesurer(
            bougies, spread, cellules, releve, "D_placebo_longueur", med_b)

    print("\n  %-20s %6s %9s %9s %9s %9s %9s"
          % ("variante", "n", "obj med", "R moyen", "t brut", "hasard", "t_vs"))
    for v in VARIANTES:
        r = res.get(v)
        if r is None:
            print("  %-20s   (moins de 10 trades)" % v)
            continue
        if r.get("refus"):
            print("  %-20s %6d   NON MESURABLE : %s" % (v, r["n"], r["refus"]))
            continue
        print("  %-20s %6d %9.3f %+9.4f %+9.2f %+9.4f %+9.2f"
              % (v, r["n"], r["objectif_med"], r["r_moyen"], r["t_brut"],
                 r["r_hasard"], r["t_vs_hasard"]))
    return res


def main() -> int:
    plafond = labo.plafond_hasard(len(VARIANTES))
    print("banc CIBLE SUR LA LIQUIDITE — %s, declaration 3c522e8" % PAIRE)
    print("  %d variantes -> plafond du hasard %.3f · %d graines de controle"
          % (len(VARIANTES), plafond, GRAINES))

    bougies, vivant = reg._bougies_et_spread(JOURS_TOTAL, PAIRE)
    spread = float(SPREAD) if SPREAD else vivant
    if SPREAD:
        print("  spread EPINGLE a %.4f (vivant %.4f ignore)" % (spread, vivant))
    print("  %d bougies sur %d jours demandes" % (len(bougies), JOURS_TOTAL))
    if len(bougies) < 2000:
        print("  pas assez de bougies")
        return 1

    coupure = datetime.now(timezone.utc) - timedelta(days=JOURS_VUS)
    vieilles = [b for b in bougies if _en_date(_horodatage(b)) < coupure]
    recentes = [b for b in bougies if _en_date(_horodatage(b)) >= coupure]
    if not vieilles or not recentes:
        print("  decoupage impossible")
        return 1
    fin_oos = _en_date(_horodatage(vieilles[-1]))
    deb_vues = _en_date(_horodatage(recentes[0]))
    if fin_oos >= deb_vues:
        print("  RECOUVREMENT NON NUL — aucun verdict")
        return 1
    print("  fenetre VUE  : %s -> %s (%d bougies)"
          % (deb_vues.date(), _en_date(_horodatage(recentes[-1])).date(),
             len(recentes)))
    print("  fenetre OOS  : %s -> %s (%d bougies) · recouvrement NUL"
          % (_en_date(_horodatage(vieilles[0])).date(), fin_oos.date(),
             len(vieilles)))

    vue = fenetre(recentes, spread, "FENETRE VUE (90 derniers jours)")
    oos = fenetre(vieilles, spread, "FENETRE JAMAIS VUE (jours 90 -> 365)")

    def _r(d, v):
        x = (d or {}).get(v)
        return x["r_moyen"] if x and not x.get("refus") else None

    print("\n=== VERDICT contre les predictions de 3c522e8")
    a, b = _r(vue, "A_reference"), _r(vue, "B_plafonnee")
    d = _r(vue, "D_placebo_longueur")
    if a is None or b is None:
        print("  mesure incomplete sur la fenetre vue — aucun verdict")
        return 1
    print("  P1 R(B) < R(A) sur 90 j : %s  [%+.4f vs %+.4f]"
          % ("VRAIE" if b < a else "FAUSSE", b, a))
    franchis = [v for v in VARIANTES
                if (vue.get(v) and not vue[v].get("refus")
                    and vue[v]["t_vs_hasard"] > plafond and vue[v]["r_moyen"] > 0)]
    print("  P2 aucune variante ne franchit %.3f : %s%s"
          % (plafond, "VRAIE" if not franchis else "FAUSSE",
             "" if not franchis else " — %s" % franchis))
    if d is None:
        print("  P3 placebo D non mesurable — ecart B/D indecidable")
    else:
        ec = vue["B_plafonnee"]["ecart_hasard"]
        print("  P3 |R(B)-R(D)| < ecart du hasard (%.4f) : %s  [%.4f]"
              % (ec, "VRAIE" if abs(b - d) < ec else "FAUSSE", abs(b - d)))
    a2, b2 = _r(oos, "A_reference"), _r(oos, "B_plafonnee")
    if a2 is None or b2 is None:
        print("  P4 hors echantillon non mesurable")
    else:
        meme = (b - a) * (b2 - a2) > 0
        print("  P4 le signe de R(B)-R(A) NE TIENT PAS hors echantillon : %s"
              % ("FAUSSE — il tient" if meme else "VRAIE"))
        print("     vue %+.4f   ·   hors echantillon %+.4f" % (b - a, b2 - a2))

    retenu = (b > a and d is not None and b > d
              and vue["B_plafonnee"]["t_vs_hasard"] > plafond
              and a2 is not None and b2 is not None and (b2 - a2) > 0)
    print("\n  decision : %s" % ("RETENU — les quatre conditions tiennent"
                                 if retenu
                                 else "NON RETENU — 1,8 R reste en place"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
