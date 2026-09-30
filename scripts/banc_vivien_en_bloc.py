#!/usr/bin/env python3
"""La méthode Vivien éprouvée EN BLOC — prédictions déclarées dans `149d85e`.

22 chaînes + 22 motifs directionnels, mis en commun en UNE seule mesure, sur
une fenêtre que les nuits glissantes n'ont jamais vue.

⛔ POURQUOI EN BLOC. Chaque cellule est déjà mesurée chaque nuit : 4 570
`INSUFFISANT`, 0 `RETENU`. Un test par cellule n'a de puissance que sur 50-170
trades et le plafond de multiplicité pour 168 cellules est écrasant : un effet
faible mais réel, commun à la famille, serait invisible. La mise en commun est
la seule façon de le chercher.

⚠️ L'INDÉPENDANCE EST VIOLÉE, ET IL FAUT LE DIRE. La contrainte séquentielle
vaut PAR cellule : deux cellules peuvent tenir un trade au même instant. Le
`t` du bloc est donc **optimiste en magnitude**.
🔑 Ce biais joue CONTRE la prédiction d'échec : si le bloc échoue malgré un `t`
gonflé, la conclusion est plus solide, pas moins.

⛔ RÉUTILISÉ, JAMAIS RÉÉCRIT : `detections`, `rejouer_cellule`,
`controle_aleatoire`, `_welch`, `_stat`, `PLACEBO_PCT`, `_bougies_et_spread`.
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

PAIRE = "XAU/USD"
JOURS_TOTAL = int(os.getenv("VIV_JOURS_TOTAL", "365"))
JOURS_VUS = int(os.getenv("VIV_JOURS_VUS", "90"))
SPREAD = float(os.getenv("VIV_SPREAD", "0.20"))
GRAINES = int(os.getenv("VIV_GRAINES", "30"))
BARRE = float(os.getenv("VIV_BARRE", "2.0"))
N_MINIMUM = int(os.getenv("VIV_N_MIN", "3000"))
COUT_MAX_R = 0.25
R_MAX_PLAUSIBLE = 3.0

RACINES_VIVIEN = ("order_block", "liquidity_sweep", "poc_return",
                  "opening_range", "retest", "reintegration", "double_sweep",
                  "fvg", "fvg_inverse", "bos", "choch")


def est_vivien(motif: str) -> str | None:
    """Rend 'chaine', 'motif' ou None. ⛔ Les racines sont comparées sur le nom
    SANS le suffixe de sens : `fvg` ne doit pas attraper `fvg_inverse` par
    hasard, et `bos` ne doit pas attraper un motif qui contiendrait 'bos'."""
    if motif.startswith("chaine:"):
        return "chaine"
    base = motif
    for suf in ("_up", "_down"):
        if base.endswith(suf):
            base = base[: -len(suf)]
            break
    return "motif" if base in RACINES_VIVIEN else None


def _h(b):
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


def mesurer_bloc(nom, trades, bougies, spread):
    if len(trades) < 10:
        print("  %-22s n=%d — trop peu" % (nom, len(trades)))
        return None
    R = [t["R"] for t in trades]
    moyenne, t_brut = labo._stat(R)
    ecart = st.pstdev(R) if len(R) > 1 else 0.0
    risque_med = st.median(t["risque"] for t in trades)
    objectif_med = st.median(t["objectif_r"] for t in trades)
    cout = spread / risque_med if risque_med > 0 else float("inf")
    if cout > COUT_MAX_R or abs(moyenne) > R_MAX_PLAUSIBLE:
        print("  %-22s NON MESURABLE (cout %.3f R, R moyen %+.2f)"
              % (nom, cout, moyenne))
        return None

    n_sens = {"buy": 0, "sell": 0}
    for t in trades:
        n_sens[t["sens"]] = n_sens.get(t["sens"], 0) + 1
    Rc: list[float] = []
    for g in range(GRAINES):
        for sens, combien in n_sens.items():
            if combien <= 0:
                continue
            Rc.extend(x["R"] for x in labo.controle_aleatoire(
                bougies, spread, combien, risque_med, objectif_med,
                graine=g, sens=sens))
    if len(Rc) < 10:
        print("  %-22s controle vide" % nom)
        return None
    moy_c, ecart_c = st.mean(Rc), st.pstdev(Rc)
    t_vs = labo._welch(moyenne, ecart, len(R), moy_c, ecart_c, len(Rc))
    print("  %-22s n=%-6d R %+8.4f  cout %.4f  hasard %+8.4f  t_vs=%+7.3f"
          % (nom, len(R), moyenne, cout, moy_c, t_vs))
    return {"n": len(R), "r": moyenne, "t_vs": t_vs, "cout": cout,
            "hasard": moy_c, "t_brut": t_brut}


def main() -> int:
    print("LA METHODE VIVIEN, EN BLOC — declaration 149d85e")
    print("  spread epingle %.2f · %d graines · barre |t| > %.1f\n"
          % (SPREAD, GRAINES, BARRE))

    bougies, vivant = reg._bougies_et_spread(JOURS_TOTAL, PAIRE)
    print("  %d bougies · spread vivant ignore (%.4f)" % (len(bougies), vivant))
    coupure = datetime.now(timezone.utc) - timedelta(days=JOURS_VUS)
    vieilles = [b for b in bougies if _d(_h(b)) < coupure]
    recentes = [b for b in bougies if _d(_h(b)) >= coupure]
    if not vieilles or not recentes:
        print("  ⛔ decoupage impossible")
        return 1
    fin, deb = _d(_h(vieilles[-1])), _d(_h(recentes[0]))
    print("  DISJOINTE %s -> %s (%d bougies) · vue des %s"
          % (_d(_h(vieilles[0])).date(), fin.date(), len(vieilles), deb.date()))
    if fin >= deb:
        print("  ⛔ RECOUVREMENT NON NUL — test invalide")
        return 1
    print("  recouvrement NUL (%.1f h)\n" % ((deb - fin).total_seconds() / 3600))

    # ⛔ DEFAUT ATTRAPE PAR L'ESSAI A BLANC : `detections()` seule rend ZERO
    # chaine — elles viennent de `fusionner_chaines`, comme dans le cycle
    # nocturne (`laboratoire_or.py:1400`). Sans cette ligne, le test « en bloc »
    # ne mesurait que les 22 motifs et laissait de cote les 22 CHAINES, qui
    # sont precisement la methode Vivien. Le bloc aurait eu l'air complet.
    releve = labo.fusionner_chaines(labo.detections(vieilles, PAIRE), vieilles)
    cellules = sorted({(labo._nom_motif(s), labo._sens(s))
                       for lot in releve.values() for s in lot})
    par_famille: dict[str, list] = {"chaine": [], "motif": []}
    n_cell = {"chaine": 0, "motif": 0, "hors": 0}
    for motif, sens in cellules:
        fam = est_vivien(motif)
        if fam is None:
            n_cell["hors"] += 1
            continue
        n_cell[fam] += 1
        for t in labo.rejouer_cellule(vieilles, releve, motif, sens, SPREAD):
            t["sens"] = sens
            par_famille[fam].append(t)
    print("  cellules : %d chaines · %d motifs Vivien · %d hors perimetre\n"
          % (n_cell["chaine"], n_cell["motif"], n_cell["hors"]))

    print("=== LE BLOC (seul eligible au verdict)")
    bloc = mesurer_bloc("VIVIEN EN BLOC", par_famille["chaine"] + par_famille["motif"],
                        vieilles, SPREAD)
    print("\n=== decomposition, publiee mais NON eligible")
    mesurer_bloc("chaines seules", par_famille["chaine"], vieilles, SPREAD)
    mesurer_bloc("motifs seuls", par_famille["motif"], vieilles, SPREAD)

    print("\n=== VERDICT contre les predictions de 149d85e")
    if not bloc:
        print("  ⛔ bloc non mesurable — aucun verdict")
        return 1
    p1 = bloc["n"] > N_MINIMUM
    print("  P1 appareil (n > %d) : %s  [%d]"
          % (N_MINIMUM, "VRAIE" if p1 else "FAUSSE", bloc["n"]))
    if not p1:
        print("  ⛔ la mise en commun n'apporte pas la puissance attendue.")
        print("     Regle commitee : aucun verdict.")
        return 1
    echoue = abs(bloc["t_vs"]) < BARRE
    print("  P2 j'ai predit l'ECHEC (|t| < %.1f) : %s  [%+.3f]"
          % (BARRE, "VRAIE" if echoue else "FAUSSE", bloc["t_vs"]))
    print("  P3 signe negatif (-0,35 a -0,05 R) : %s  [%+.4f]"
          % ("VRAIE" if -0.35 <= bloc["r"] <= -0.05 else "FAUSSE", bloc["r"]))
    print("\n  decision : %s" % (
        "⛔ REFUTEE EN BLOC" if echoue else
        "⛔ mesurablement NUISIBLE" if bloc["r"] < 0 else
        "🔬 FAIT NEUF — a repliquer avant toute production"))
    print("\n  ⚠️ rappel : l'independance est violee entre cellules, donc ce |t|"
          "\n     est OPTIMISTE. Un echec malgre un t gonfle est plus solide.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
