#!/usr/bin/env python3
"""La MAIN, testée HORS ÉCHANTILLON — prédictions déclarées dans `accafd0`.

Le 08/09 la main sortait à +0,728 R contre le contrefactuel (t=+4,07, n=44).
Cette mesure n'a jamais été rejouée. Deux effets du projet se sont effondrés
hors échantillon le 30/09 ; celui-ci doit subir le même test.

⛔ TEST APPARIÉ : chaque trade est comparé à LUI-MÊME (ce que ses propres SL/TP
auraient donné). Comparer les trades coupés aux trades laissés serait comparer
deux populations choisies — le biais que `contrefactuels_sortie` existe pour
fermer.

⛔ DEUX UNITÉS, et c'est le cœur du test. `+0,459 R` est une moyenne en R sur
des trades dont le risque varie de 8 à 65 €. Sommer des R sur des risques
incomparables sur-pondère les petits risques : le piège d'unité déjà payé par
le régulateur. Le gain en euros se calcule donc trade par trade,
`delta_R × risque_eur`, avec le `risk_eur.calculer` de la production.
"""

from __future__ import annotations

import math
import os
import sqlite3
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services import pair_pnl_regulator as reg  # noqa: E402
from backend.services.risk_eur import calculer  # noqa: E402

COUPURE = os.getenv("MAIN_COUPURE", "2026-09-08T18:00")
DEST = os.getenv("MAIN_DEST", "admin_live")
BARRE = float(os.getenv("MAIN_BARRE", "2.0"))


def _t_apparie(deltas: list[float]) -> float:
    """t de Student apparié. 0 si la dispersion est nulle — un t infini sur une
    dispersion nulle a l'air d'un résultat et n'en est pas."""
    n = len(deltas)
    if n < 3:
        return 0.0
    s = st.stdev(deltas)
    if s < 1e-9:
        return 0.0
    return st.mean(deltas) / (s / math.sqrt(n))


def charger(c, avant: bool):
    signe = "<" if avant else ">="
    rows = list(c.execute("""
      select f.trade_id, f.pair, f.direction, f.entry_price, f.sl,
             f.r_realise, f.r_contrefactuel, f.issue, f.closed_at,
             t.size_lot, t.pnl
      from contrefactuels_sortie f
      join personal_trades t on t.id = f.trade_id
      where f.destination_id = ? and f.close_reason = 'MANUAL'
        and f.r_realise is not null and f.r_contrefactuel is not null
        and f.closed_at %s ?
      order by f.closed_at""" % signe, (DEST, COUPURE)))
    out = []
    for r in rows:
        dR = float(r["r_realise"]) - float(r["r_contrefactuel"])
        risque_eur = None
        try:
            e, s, lot = r["entry_price"], r["sl"], r["size_lot"]
            if e and s and lot:
                m = calculer(r["pair"], float(e), float(s), 0.0, float(lot))
                if m and m.get("risque_eur", 0) > 0:
                    risque_eur = m["risque_eur"]
        except Exception:  # noqa: BLE001
            pass
        out.append({"dR": dR, "r_realise": float(r["r_realise"]),
                    "r_cf": float(r["r_contrefactuel"]), "issue": r["issue"],
                    "risque_eur": risque_eur, "pnl": r["pnl"],
                    "d_eur": dR * risque_eur if risque_eur else None})
    return out


def resume(nom, lot):
    if len(lot) < 3:
        print("  %-28s n=%d — trop peu pour conclure" % (nom, len(lot)))
        return None
    dR = [x["dR"] for x in lot]
    t = _t_apparie(dR)
    eur = [x["d_eur"] for x in lot if x["d_eur"] is not None]
    evites = sum(1 for x in lot if x["issue"] == "SL")
    manques = sum(1 for x in lot if x["issue"] == "TP")
    print("  %-28s n=%-4d  gain %+.3f R  t=%+.2f  mediane %+.3f R"
          % (nom, len(dR), st.mean(dR), t, st.median(dR)))
    print("      main %+.3f R  ·  contrefactuel %+.3f R  ·  %d/%d meilleurs"
          % (st.mean(x["r_realise"] for x in lot),
             st.mean(x["r_cf"] for x in lot),
             sum(1 for x in dR if x > 0), len(dR)))
    print("      %d stops evites · %d objectifs manques" % (evites, manques))
    if eur:
        print("      EN EUROS : gain moyen %+.2f EUR  mediane %+.2f  total %+.2f  (n=%d)"
              % (st.mean(eur), st.median(eur), sum(eur), len(eur)))
        rm = st.median(x["risque_eur"] for x in lot if x["risque_eur"])
        print("      risque median %.2f EUR -> le R laisse croire %+.2f EUR/trade"
              % (rm, st.mean(dR) * rm))
    return {"n": len(dR), "r": st.mean(dR), "t": t,
            "eur": st.mean(eur) if eur else None,
            "eur_attendu": st.mean(dR) * st.median(
                [x["risque_eur"] for x in lot if x["risque_eur"]] or [0])}


def main() -> int:
    print("LA MAIN, HORS ECHANTILLON — declaration accafd0")
    print("  coupure %s · destination %s · barre |t| > %.1f\n"
          % (COUPURE, DEST, BARRE))
    c = sqlite3.connect("file:" + reg._db_path() + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row

    print("=== P1 — L'APPAREIL, sur la fenetre DEJA mesuree (avant la coupure)")
    ref = resume("avant 08/09", charger(c, True))
    print("\n=== LE TEST — fenetre JAMAIS mesuree (apres la coupure)")
    oos = resume("APRES 08/09", charger(c, False))

    print("\n=== VERDICT contre les predictions de accafd0")
    if not ref or not oos:
        print("  ⛔ echantillon insuffisant — aucun verdict")
        return 1
    p1 = ref["r"] > 0.4 and ref["t"] > 3
    print("  P1 appareil (> +0,4 R et t > 3) : %s  [%+.3f R, t=%+.2f]"
          % ("VRAIE" if p1 else "FAUSSE", ref["r"], ref["t"]))
    if not p1:
        print("  ⛔ L'appareil ne reproduit pas la mesure du 08/09.")
        print("     Regle d'arret commitee : AUCUN VERDICT sur le hors echantillon.")
        return 1
    print("  P2 effondrement partiel (< +0,728 R) : %s  [%+.3f R]"
          % ("VRAIE" if oos["r"] < 0.728 else "FAUSSE", oos["r"]))
    survit = oos["r"] > 0.3 and abs(oos["t"]) > BARRE
    print("  P3 la main SURVIT (> +0,3 R et |t| > %.1f) : %s  [%+.3f R, t=%+.2f]"
          % (BARRE, "VRAIE" if survit else "FAUSSE", oos["r"], oos["t"]))
    if oos["eur"] is not None and oos["eur_attendu"]:
        ratio = oos["eur"] / oos["eur_attendu"] if oos["eur_attendu"] else 0
        print("  P4 l'euro dit MOINS que le R (< moitie) : %s  [%+.2f contre %+.2f attendu, ratio %.2f]"
              % ("VRAIE" if ratio < 0.5 else "FAUSSE",
                 oos["eur"], oos["eur_attendu"], ratio))
    print("\n  decision : %s" % (
        "✅ EFFET CONFIRME hors echantillon — le seul du projet"
        if survit and (oos["eur"] or 0) > 0 else
        "⚠️ EFFET D'UNITE : vrai en R, sans valeur en caisse"
        if survit else
        "⛔ EFFONDRE, comme la chaine et fvg_up"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
