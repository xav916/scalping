#!/usr/bin/env python3
"""LE recouvrement a mesurer avant toute lecture de R sur la structure M15.

⛔ POURQUOI AVANT. Le carnet declare l'objection : `structure_m15_*` et
`biais_*` appellent la MEME fonction — `_tendance_de_structure` — l'un sur
`FENETRE` bougies M15 agregees (150 bougies de 5 min), l'autre sur
`BIAIS_FENETRE` bougies de 5 min (400). Fenetres differentes, lecture
identique, resultats correles.

Si le recouvrement est quasi-total, les chaines M15 n'ajoutent RIEN et
dupliqueraient une cellule deja payee sur le plafond du hasard. Il faut alors
NE PAS les declarer, ou choisir laquelle des deux echelles porte le contexte.

⚠️ LE RECOUVREMENT EST MESURE DANS LES DEUX SENS. Un seul sens peut cacher une
inclusion : si 100 % des M15-haussiers sont des biais-haussiers mais seulement
40 % de l'inverse, la chaine est un SOUS-ENSEMBLE du biais — redondante dans un
sens, pas dans l'autre. Une seule proportion ne le dirait pas.

⚠️ ECHANTILLONNAGE. Les deux predicats reconstruisent des objets `Candle` a
chaque appel (556 par indice). On echantillonne donc un indice sur `PAS`, ce qui
est sans effet sur un TAUX. Le nombre d'observations est affiche : c'est lui qui
dit ce que le taux vaut.

Bougies : la fixture FIGEE du 2026-09-09. Aucun appel reseau.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services import laboratoire_or as labo  # noqa: E402

FIXTURE = (Path(__file__).resolve().parents[1] / "backend" / "tests"
           / "fixtures" / "bougies_xauusd_5min.json")
PAS = int(sys.argv[1]) if len(sys.argv) > 1 else 10


def main() -> int:
    brut = json.loads(FIXTURE.read_text(encoding="utf-8"))
    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    bougies = [{"t": t0 + timedelta(minutes=5 * k), "o": o, "h": h,
                "l": b, "c": c, "tv": 0.0}
               for k, (o, h, b, c) in enumerate(brut)]

    p = labo._PREDICATS
    depart = max(labo.BIAIS_FENETRE, (labo.FENETRE + 2) * labo.M15_FACTEUR) + 2
    couples = (("haussier", "structure_m15_haussiere", "biais_haussier"),
               ("baissier", "structure_m15_baissiere", "biais_baissier"))

    print(f"Fixture : {len(bougies)} bougies | un indice sur {PAS} | "
          f"depart a {depart}")
    print(f"M15 : {labo.FENETRE} bougies agregees (facteur "
          f"{labo.M15_FACTEUR}) | biais : {labo.BIAIS_FENETRE} bougies\n")

    for sens, nom_m15, nom_biais in couples:
        m15 = biais = deux = ni = 0
        observations = 0
        for i in range(depart, len(bougies), PAS):
            observations += 1
            a = p[nom_m15](bougies, i)
            b = p[nom_biais](bougies, i)
            m15 += a
            biais += b
            deux += a and b
            ni += (not a) and (not b)

        print(f"— {sens} ({observations} observations)")
        print(f"    structure M15 vraie   : {m15}")
        print(f"    biais vrai            : {biais}")
        print(f"    les DEUX              : {deux}")
        print(f"    aucun des deux        : {ni}")
        if m15:
            print(f"    part des M15 qui sont AUSSI des biais : "
                  f"{100*deux/m15:.1f} %")
        else:
            print("    ⚠️ structure M15 JAMAIS vraie — predicat muet, "
                  "rien a conclure")
        if biais:
            print(f"    part des biais qui sont AUSSI des M15 : "
                  f"{100*deux/biais:.1f} %")
        else:
            print("    ⚠️ biais JAMAIS vrai sur cet echantillon")
        print()

    print("LECTURE : deux parts hautes = redondance, ne pas declarer les "
          "chaines.\n          une haute et une basse = inclusion, une seule "
          "echelle suffit.\n          deux basses = les deux mesurent autre "
          "chose, les chaines se justifient.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
