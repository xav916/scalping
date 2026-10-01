#!/usr/bin/env python3
"""Pourquoi le labo rend les cellules SOUS le hasard et mon banc AU-DESSUS.

⛔ LE CONSTAT A LEVER (2026-10-01). Sur la meme paire et la meme fenetre :

    labo_or_cellules.delta_hasard, moyenne par horizon :  -0,006 a -0,036
    banc du matin, variante A, fenetre VUE             :  R -0,0431 contre
                                                          hasard -0,0607
                                                          => delta +0,0176

Les deux ne peuvent pas etre vraies au meme sens. Tant que ce n'est pas tranche,
aucune decision ne doit s'appuyer sur l'un ou l'autre.

🔑 DEUX DIFFERENCES CANDIDATES, et une seule question a chaque fois :

  1. L'AGREGATION. Le labo fait la moyenne des deltas PAR CELLULE, a poids
     egal — une cellule de 3 trades pese autant qu'une de 500. Mon banc met
     tous les trades EN COMMUN, donc les grosses cellules dominent. Si les
     cellules frequentes sont meilleures que les rares, les deux chiffres
     divergent SANS qu'aucun soit faux : c'est le paradoxe de Simpson.

  2. LE CONTROLE. Le labo tire un controle PAR CELLULE, au risque et a
     l'objectif de CETTE cellule. Mon banc en tire un seul, au risque median
     GLOBAL. Or le cout vaut `spread / risque` : un controle au stop median
     paie moins de frais qu'une cellule a stop serre, et la fait donc paraitre
     mauvaise. Le controle du labo apparie le cout, le mien non.

⛔ CE QUI EST REUTILISE, JAMAIS REECRIT
`rejouer_cellule` (et non une seconde boucle : verifie identique a la mienne
avant d'ecrire ce script), `controle_poole`, `detections`, `_stat`,
`_bougies_et_spread`. Mesurer une incoherence avec un TROISIEME appareil
n'aurait rien tranche.
"""

from __future__ import annotations

import os
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services import laboratoire_or as labo  # noqa: E402
from backend.services import reglage_or as reg  # noqa: E402

PAIRE = os.getenv("VERIF_PAIRE", "XAU/USD")
JOURS = int(os.getenv("VERIF_JOURS", str(reg.JOURS_ETUDIES)))
SPREAD = float(os.getenv("VERIF_SPREAD", "0.20"))
GRAINES = int(os.getenv("VERIF_GRAINES", str(labo.CONTROLE_GRAINES)))
MIN_TRADES = int(os.getenv("VERIF_MIN_TRADES", "10"))


def main() -> int:
    print("VERIFICATION de l'incoherence << cellules vs hasard >>")
    print("  %s · %d jours · spread epingle %.2f · %d graines de controle\n"
          % (PAIRE, JOURS, SPREAD, GRAINES))

    bougies, _vivant = reg._bougies_et_spread(JOURS, PAIRE)
    print("  %d bougies M5" % len(bougies))
    releve = labo.detections(bougies, PAIRE)
    cellules = sorted({(labo._nom_motif(s), labo._sens(s))
                       for lot in releve.values() for s in lot})
    print("  %d cellules motif x sens\n" % len(cellules))

    lignes = []
    tous_R: list[float] = []
    tous_ctrl: list[float] = []
    for motif, sens in cellules:
        trades = labo.rejouer_cellule(bougies, releve, motif, sens, SPREAD)
        if len(trades) < MIN_TRADES:
            continue
        R = [t["R"] for t in trades]
        # ⛔ Le controle du LABO : le risque et l'objectif de CETTE cellule.
        ctrl = labo.controle_poole(
            bougies, SPREAD, len(R),
            st.median(t["risque"] for t in trades),
            st.median(t["objectif_r"] for t in trades),
            graine=0, sens=sens, graines=GRAINES)
        if len(ctrl) < MIN_TRADES:
            continue
        lignes.append({"motif": motif, "sens": sens, "n": len(R),
                       "r": st.mean(R), "ctrl": st.mean(ctrl),
                       "delta": st.mean(R) - st.mean(ctrl)})
        tous_R += R
        tous_ctrl += ctrl

    if not lignes:
        print("  aucune cellule mesurable")
        return 1

    n_total = sum(x["n"] for x in lignes)
    delta_poids_egal = st.mean(x["delta"] for x in lignes)
    delta_pondere = sum(x["delta"] * x["n"] for x in lignes) / n_total
    delta_en_commun = st.mean(tous_R) - st.mean(tous_ctrl)

    print("=== LES TROIS FACONS DE LIRE LE MEME JEU DE DONNEES")
    print("  cellules retenues : %d · trades : %d\n" % (len(lignes), n_total))
    print("  1. moyenne des deltas PAR CELLULE, poids egal   : %+.4f   <- le labo"
          % delta_poids_egal)
    print("  2. moyenne des deltas PONDEREE par n            : %+.4f"
          % delta_pondere)
    print("  3. tous les trades EN COMMUN contre leurs ctrl  : %+.4f   <- mon banc"
          % delta_en_commun)

    # La question de Simpson, posee directement : les grosses cellules sont-elles
    # meilleures que les petites ?
    med_n = st.median(x["n"] for x in lignes)
    grosses = [x for x in lignes if x["n"] > med_n]
    petites = [x for x in lignes if x["n"] <= med_n]
    print("\n=== D'OU VIENT L'ECART : les cellules FREQUENTES sont-elles meilleures ?")
    print("  mediane de n = %.0f" % med_n)
    for nom, lot in (("cellules FREQUENTES (n > mediane)", grosses),
                     ("cellules RARES     (n <= mediane)", petites)):
        if not lot:
            continue
        print("  %-34s : %2d cellules · n total %5d · delta moyen %+.4f"
              % (nom, len(lot), sum(x["n"] for x in lot),
                 st.mean(x["delta"] for x in lot)))

    print("\n=== LES CINQ CELLULES QUI PESENT LE PLUS")
    print("  %-22s %-5s %6s %9s %9s %9s"
          % ("motif", "sens", "n", "R", "hasard", "delta"))
    for x in sorted(lignes, key=lambda y: -y["n"])[:5]:
        print("  %-22s %-5s %6d %+9.4f %+9.4f %+9.4f"
              % (x["motif"], x["sens"], x["n"], x["r"], x["ctrl"], x["delta"]))

    print("\n=== VERDICT")
    if (delta_poids_egal < 0) and (delta_en_commun > 0):
        print("  Les DEUX chiffres sont exacts et repondent a deux questions")
        print("  differentes. Aucun n'est a corriger ; c'est le paradoxe de")
        print("  Simpson. Il faut dire LAQUELLE on pose :")
        print("    - poids egal  : << une cellule TYPE bat-elle son hasard ? >> NON")
        print("    - en commun   : << le FLUX que le systeme prendrait bat-il")
        print("                      le hasard ? >> OUI")
    else:
        print("  L'ecart ne se reproduit PAS ainsi : chercher ailleurs")
        print("  (fenetre, graines, ou la construction du controle).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
