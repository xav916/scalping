#!/usr/bin/env python3
"""Pourquoi mon banc du 30/09 rend −0,0451 R là où celui du 15/09 publiait −0,0306.

L'écart vaut **−0,0145 R** sur des coûts (0,0213 vs 0,0207) et des effectifs
(8 386 vs 8 362) quasi identiques. Deux différences de méthode peuvent
l'expliquer, et on les sépare au lieu d'en supposer une :

1. **la FENÊTRE** — leur 90 jours s'arrêtait le 15/09, le mien le 30/09 ;
2. **l'OBJECTIF** — la ligne « 1,8 R » du banc du 15/09 FORÇAIT 1,8 R pour
   tous les setups, alors que mon rejeu prend l'objectif PROPRE à chaque
   setup (médiane 1,789, mais qui varie).

⛔ Ne pas conclure d'un seul essai : si aucune des deux ne referme l'écart, la
cause est ailleurs et il faut le dire plutôt que d'attribuer au hasard.

Plan 2×2 : {objectif propre, objectif forcé à 1,8} × {fenêtre au 30/09,
fenêtre au 15/09}. Spread épinglé à 0,20 dans les quatre cas — sinon le tick
vivant déplacerait tout.
"""

from __future__ import annotations

import os
import statistics as st
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services import laboratoire_or as labo  # noqa: E402
from backend.services import reglage_or as reg  # noqa: E402

SPREAD = float(os.getenv("REC_SPREAD", "0.20"))
JOURS = int(os.getenv("REC_JOURS", "90"))
# Le banc de reference a tourne le 15/09 ; on recule donc la fin de fenetre
# de ce nombre de jours pour reconstituer SA fenetre.
DECALAGE = int(os.getenv("REC_DECALAGE_JOURS", "15"))
PUBLIE_R, PUBLIE_COUT = -0.0306, 0.0207


def _t(b):
    for c in ("t", "time", "ts", "date", "datetime"):
        if c in b:
            return b[c]
    raise KeyError("pas de champ de temps")


def _d(v):
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, tz=timezone.utc)
    s = str(v).replace("Z", "+00:00")
    x = datetime.fromisoformat(s)
    return x if x.tzinfo else x.replace(tzinfo=timezone.utc)


def rejouer(bougies, releve, motif, sens, spread, objectif_force=None):
    """Rejeu séquentiel d'une cellule. `objectif_force` impose la cible en R."""
    trades = []
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
        propre = abs(float(s.take_profit_1) - entree) / risque
        objectif = objectif_force if objectif_force else propre
        if objectif <= 0:
            i += 1
            continue
        signe = 1 if sens == "buy" else -1
        R, sortie = labo._issue(bougies, i, entree, risque, objectif, signe,
                                spread / risque)
        trades.append({"R": R, "cout": spread / risque, "objectif": objectif})
        i = sortie + 1
    return trades


def variante(bougies, spread, objectif_force):
    releve = labo.detections(bougies, "XAU/USD")
    cellules = sorted({(labo._nom_motif(s), labo._sens(s))
                       for lot in releve.values() for s in lot})
    tous = []
    for motif, sens in cellules:
        tous.extend(rejouer(bougies, releve, motif, sens, spread, objectif_force))
    if not tous:
        return None
    R = [t["R"] for t in tous]
    moyenne, t_stat = labo._stat(R)
    return {"n": len(R), "r_moyen": moyenne, "t": t_stat,
            "cout": st.median(t["cout"] for t in tous),
            "objectif": st.median(t["objectif"] for t in tous),
            "cellules": len(cellules)}


def main() -> int:
    print("RECONCILIATION du banc de l'or — publie %+.4f R, cout %.4f"
          % (PUBLIE_R, PUBLIE_COUT))
    print("  spread epingle %.2f · fenetre %d jours · decalage %d jours\n"
          % (SPREAD, JOURS, DECALAGE))

    # Une seule lecture, large, puis on découpe : deux appels réseau
    # donneraient deux spreads et deux populations légèrement différentes.
    total = JOURS + DECALAGE + 5
    bougies, _ = reg._bougies_et_spread(total, "XAU/USD")
    print("  %d bougies lues sur %d jours" % (len(bougies), total))
    if len(bougies) < 3000:
        print("  ⛔ pas assez de bougies")
        return 1

    maintenant = _d(_t(bougies[-1]))
    fen = {
        "au 30/09 (la mienne)": [b for b in bougies
                                 if _d(_t(b)) > maintenant - timedelta(days=JOURS)],
        "au 15/09 (la leur)": [
            b for b in bougies
            if maintenant - timedelta(days=JOURS + DECALAGE)
            < _d(_t(b)) <= maintenant - timedelta(days=DECALAGE)],
    }
    for nom, b in fen.items():
        print("  fenetre %-22s %s -> %s  (%d bougies)"
              % (nom, _d(_t(b[0])).date(), _d(_t(b[-1])).date(), len(b)))

    print("\n%-24s %-14s %6s %7s %10s %9s %9s"
          % ("fenetre", "objectif", "n", "cell.", "R moyen", "t", "cout R"))
    res = {}
    for nom_f, b in fen.items():
        for nom_o, forc in (("propre (~1,79)", None), ("force a 1,8", 1.8)):
            v = variante(b, SPREAD, forc)
            if not v:
                print("%-24s %-14s  (aucun trade)" % (nom_f, nom_o))
                continue
            res[(nom_f, nom_o)] = v
            print("%-24s %-14s %6d %7d %+10.4f %+9.2f %9.4f"
                  % (nom_f, nom_o, v["n"], v["cellules"], v["r_moyen"],
                     v["t"], v["cout"]))

    ref = res.get(("au 30/09 (la mienne)", "propre (~1,79)"))
    cible = res.get(("au 15/09 (la leur)", "force a 1,8"))
    print("\n=== DECOMPOSITION de l'ecart de %+.4f R" % (PUBLIE_R - (ref or {}).get("r_moyen", 0)))
    if ref and cible:
        effet_obj = (res[("au 30/09 (la mienne)", "force a 1,8")]["r_moyen"]
                     - ref["r_moyen"])
        effet_fen = (res[("au 15/09 (la leur)", "propre (~1,79)")]["r_moyen"]
                     - ref["r_moyen"])
        reste = PUBLIE_R - cible["r_moyen"]
        print("  effet de l'OBJECTIF force   : %+.4f R" % effet_obj)
        print("  effet de la FENETRE         : %+.4f R" % effet_fen)
        print("  variante la plus proche du banc publie : %+.4f R (publie %+.4f)"
              % (cible["r_moyen"], PUBLIE_R))
        print("  RESTE inexplique            : %+.4f R" % reste)
        print("\n  => %s" % (
            "les deux differences de methode SUFFISENT a refermer l'ecart"
            if abs(reste) < 0.008 else
            "elles NE SUFFISENT PAS : la cause est ailleurs, il faut le dire"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
