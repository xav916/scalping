#!/usr/bin/env python3
"""LA mesure qui doit precéder toute lecture de R sur le niveau majeur.

⛔ POURQUOI ELLE PASSE AVANT. Le carnet declare l'objection : un
`liquidity_sweep_down` fait par definition un nouveau plus-haut de 30 bougies.
S'il est en plus a portee du plus-haut de 400, il fait peut-etre simplement un
nouveau plus-haut de 400 — et le predicat selectionnerait des CASSURES de la
grande fourchette, pas des balayages sur un niveau retesté. Deux populations
opposees sous un seul nom.

La mesure tranche : parmi les declenchements de la chaine, quelle part DEPASSE
le niveau preexistant (donc en fait un neuf) contre quelle part le touche sans
le depasser (donc le reteste) ?

Bougies : la fixture FIGEE de vraies bougies XAU/USD 5 min du 2026-09-09.
Aucun appel reseau — un test qui depend du reseau mesure le voisinage.

⚠️ Une seule implementation : le detecteur vient de `pattern_detector`, le
predicat de `laboratoire_or`. Rien n'est recode ici.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.models.schemas import PatternType                      # noqa: E402
from backend.services import laboratoire_or as labo                 # noqa: E402
from backend.services.pattern_detector import Candle, detect_patterns  # noqa: E402

FIXTURE = (Path(__file__).resolve().parents[1] / "backend" / "tests"
           / "fixtures" / "bougies_xauusd_5min.json")

CAS = (
    # (motif du balayage, cote du predicat, libelle)
    (PatternType.LIQUIDITY_SWEEP_DOWN.value, "haut", "balayage des HAUTS (vente)"),
    (PatternType.LIQUIDITY_SWEEP_UP.value, "bas", "balayage des BAS (achat)"),
)


def main() -> int:
    brut = json.loads(FIXTURE.read_text(encoding="utf-8"))
    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    bougies = [{"t": t0 + timedelta(minutes=5 * k), "o": o, "h": h,
                "l": b, "c": c, "tv": 0.0}
               for k, (o, h, b, c) in enumerate(brut)]
    objets = [Candle(timestamp=x["t"], open=x["o"], high=x["h"],
                     low=x["l"], close=x["c"], volume=0) for x in bougies]

    predicats = {cote: labo._sur_niveau_majeur(cote) for _, cote, _ in CAS}
    stats = {m: {"balayages": 0, "chaine": 0, "depasse": 0, "retest": 0}
             for m, _, _ in CAS}

    depart = labo.BIAIS_FENETRE + 2      # le predicat exige 400 bougies AVANT
    fenetres = 0
    for i in range(depart, len(bougies)):
        fenetres += 1
        vus = {p.pattern.value for p in
               detect_patterns(objets[i - labo.FENETRE:i], "XAU/USD")}
        for motif, cote, _ in CAS:
            if motif not in vus:
                continue
            s = stats[motif]
            s["balayages"] += 1
            if not predicats[cote](bougies, i):
                continue
            s["chaine"] += 1
            # Classement : le niveau PREEXISTANT est-il depasse ou seulement
            # touche ? Meme geometrie que le predicat, bougie courante exclue.
            fen = bougies[: i - 1][-labo.BIAIS_FENETRE:]
            if cote == "haut":
                niveau = max(x["h"] for x in fen)
                atteint = bougies[i - 1]["h"]
                depasse = atteint > niveau
            else:
                niveau = min(x["l"] for x in fen)
                atteint = bougies[i - 1]["l"]
                depasse = atteint < niveau
            s["depasse" if depasse else "retest"] += 1

    print(f"Fenetres examinees : {fenetres}  (bougies {depart} a {len(bougies)})")
    print(f"Fenetre du niveau : {labo.BIAIS_FENETRE} bougies  |  "
          f"tolerance : {labo.NIVEAU_TOLERANCE_ATR} x ATR(14)\n")
    verdict_global = []
    for motif, _, libelle in CAS:
        s = stats[motif]
        b, c = s["balayages"], s["chaine"]
        print(f"— {libelle}")
        print(f"    balayages simples          : {b}")
        if b == 0:
            print("    (aucun : rien a dire)\n")
            continue
        print(f"    dont sur niveau majeur     : {c}  ({100*c/b:.1f} %)")
        if c == 0:
            print("    ⚠️ chaine MUETTE sur la fixture — INSUFFISANT garanti\n")
            verdict_global.append((libelle, None))
            continue
        d, r = s["depasse"], s["retest"]
        print(f"      dont DEPASSE le niveau   : {d}  ({100*d/c:.1f} %)")
        print(f"      dont le RETESTE          : {r}  ({100*r/c:.1f} %)")
        print()
        verdict_global.append((libelle, 100 * d / c))

    print("VERDICT")
    for libelle, pct in verdict_global:
        if pct is None:
            print(f"  {libelle} : indecidable, chaine muette")
        elif pct > 50:
            print(f"  {libelle} : ⛔ {pct:.1f} % de CASSURES — la regle mesure "
                  "majoritairement un nouvel extreme, pas un retest. Exiger que "
                  "le niveau ne soit PAS depasse.")
        else:
            print(f"  {libelle} : ✅ {100-pct:.1f} % de retests — la regle mesure "
                  "bien un niveau preexistant touche sans etre depasse.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
