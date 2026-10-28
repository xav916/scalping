"""Banc : l artefact de PRIX D ENTREE touche-t-il aussi le `1d` et le `4h` ?

Pre-inscrit dans `docs/preinscriptions/2026-10-28-decomposition-1d-4h.md`.

⛔ CE QUI EST TESTE. Le verdict `644fded` a retire le signal `5min` : son ecart
venait d un `entry_price` non executable (un niveau de motif, hors de sa bougie
dans 50,2 % des cas). J y ai annonce une echelle `decalage / risk_pct`
monotone, SANS LA TESTER -- et les chiffres publies la contredisent deja, le
`4h` ayant un stop plus serre que le `5min` en echantillon pour un ecart plus
negatif. Ce banc mesure donc le DECALAGE REEL par horizon, pas son substitut.

🔑 LA QUANTITE DECISIVE NE CONTIENT PAS DE PLACEBO :

    artefact = ecart(STOCKE) - ecart(FILL) = esp_reel_STOCKE - esp_reel_FILL

Le placebo se simplifie. Verifie sur le `5min` : -0,059336 - (-0,197829) =
+0,138493 contre +0,091961 - (-0,046533) = +0,138494. ⇒ L artefact est donc
IMMUNE a la derive du placebo, ce qui compte ici car les criteres `1d` et `4h`
n ont pas de `fin_chargement`.

⛔ LECTURE SEULE sur la base. Rien n est ecrit nulle part.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import statistics
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.banc_esperance_horizon import (  # noqa: E402
    GRAINE, charge, lire_reels, parse_population, t_contre_placebo)
from scripts.banc_placebo_structure import instants_tires  # noqa: E402
from scripts.banc_anticorrelation_jambes import (  # noqa: E402
    r_par_setup, r_reel_par_setup)
from scripts.banc_placebo_fidele import ratios_d_entree  # noqa: E402
from scripts.banc_fill_realisable import (  # noqa: E402
    part_entree_hors_bougie_pct, taux_premiere_bougie)

REPRODUCTION_DEFAUT_PCT = 2.0


def _esp(rs) -> float | None:
    v = [x[1] for x in rs if x is not None]
    return statistics.fmean(v) if v else None


def une_cellule(nom: str, db: str, cr: "Criteres", j) -> dict:
    """Un horizon : les deux bras reels, le placebo, et l artefact."""
    import asyncio
    conf = cr.cellules[nom]
    j.info("=== cellule %s : %s", nom, conf["population_brute"])
    reels = lire_reels(db, conf["horizon"], conf["population"])
    if not reels:
        return {"erreur": f"aucun setup pour la cellule {nom}"}

    bornes: dict[str, tuple] = {}
    for d in reels:
        mn, mx = bornes.get(d["pair"], (d["bar"], d["bar"]))
        bornes[d["pair"]] = (min(mn, d["bar"]), max(mx, d["bar"]))
    j.info("    chargement des bougies (%d paires)", len(bornes))
    series = asyncio.run(charge(bornes, cr.fin_chargement))
    couverts = [d for d in reels if d["pair"] in series]
    if not couverts:
        return {"erreur": f"aucune serie chargee pour {nom}"}
    couverture = 100.0 * len(couverts) / len(reels)
    fh = conf["fenetre_h"]
    instants_reels = [d["bar"].timestamp() for d in couverts]

    # ─── les deux bras reels ───
    esp_stocke = _esp(r_reel_par_setup(couverts, series, fh))
    esp_fill = _esp(r_par_setup(couverts, series, instants_reels, fh))
    if esp_stocke is None or esp_fill is None:
        return {"erreur": f"un bras reel ne rend aucune issue pour {nom}"}

    # ─── le placebo, schema des bancs publies ───
    j.info("    placebo %s : %d tirages", cr.schema, cr.tirages)
    alea = random.Random(cr.graine)
    esperances: list[float] = []
    for k in range(cr.tirages):
        inst = instants_tires(cr.schema, couverts, bornes, alea)
        e = _esp(r_par_setup(couverts, series, inst, fh))
        if e is not None:
            esperances.append(e)
        if (k + 1) % 50 == 0:
            j.info("      tirage %d / %d", k + 1, cr.tirages)
    esp_pl = statistics.fmean(esperances) if esperances else None
    sd = statistics.stdev(esperances) if len(esperances) > 1 else None

    # ─── la cause, mesuree ───
    ratios = ratios_d_entree(couverts, series)
    dec = [abs(r - 1.0) * 100.0 / d["risk_pct"]
           for r, d in zip(ratios, couverts) if d["risk_pct"] > 0]
    sl_st, tp_st = taux_premiere_bougie(couverts, series, instants_reels, True)
    sl_fi, tp_fi = taux_premiere_bougie(couverts, series, instants_reels, False)
    inst0 = instants_tires(cr.schema, couverts, bornes,
                           random.Random(cr.graine))
    sl_pl, tp_pl = taux_premiere_bougie(couverts, series, inst0, False)

    ecart_st = (esp_stocke - esp_pl) if esp_pl is not None else None
    ecart_fi = (esp_fill - esp_pl) if esp_pl is not None else None
    return {
        "n_reel": len(couverts),
        "couverture_bougies_pct": couverture,
        "fenetre_heures": fh,
        "risk_pct_median": statistics.median([d["risk_pct"] for d in couverts]),
        "esperance_reel_stocke": esp_stocke,
        "esperance_reel_fill": esp_fill,
        # 🔑 LA QUANTITE DECISIVE, sans placebo.
        "artefact": esp_stocke - esp_fill,
        "esperance_placebo": esp_pl,
        "sd_nul": sd,
        "tirages_aboutis": len(esperances),
        "ecart_stocke": ecart_st,
        "ecart_fill": ecart_fi,
        "t_stocke": (ecart_st / sd) if sd else None,
        "t_fill": (ecart_fi / sd) if sd else None,
        "part_entree_hors_bougie_stocke_pct":
            part_entree_hors_bougie_pct(couverts, series, True),
        "part_entree_hors_bougie_fill_pct":
            part_entree_hors_bougie_pct(couverts, series, False),
        "mediane_decalage_sur_risque": statistics.median(dec) if dec else None,
        "premiere_bougie_stocke": [sl_st, tp_st],
        "premiere_bougie_fill": [sl_fi, tp_fi],
        "premiere_bougie_placebo": [sl_pl, tp_pl],
        "reproduction_esperance_pct":
            100.0 * abs(esp_stocke - conf["ref_esp"]) / abs(conf["ref_esp"]),
        "reproduction_ecart_pct":
            (100.0 * abs(ecart_st - conf["ref_ecart"]) / abs(conf["ref_ecart"])
             if ecart_st is not None else float("inf")),
    }


PREDICTIONS = {
    "P1_artefact_1d_max": (
        "artefact NEGLIGEABLE sur le 1d",
        lambda m, v: m["artefact_1d"] is not None and m["artefact_1d"] < v),
    "P2_artefact_4h_max": (
        "artefact du 4h INFERIEUR a celui du 5min",
        lambda m, v: m["artefact_4h"] is not None and m["artefact_4h"] < v),
    "P3_artefact_4h_plancher": (
        "mais POSITIF : la specification stockee favorise le reel",
        lambda m, v: m["artefact_4h"] is not None and m["artefact_4h"] > v),
    "P4_decalage_sur_risque_1d_max": (
        "la CAUSE, mesuree : decalage petit devant le stop du 1d",
        lambda m, v: m["mediane_decalage_sur_risque_1d"] is not None
        and m["mediane_decalage_sur_risque_1d"] < v),
    "P5_artefact_1d_plancher": (
        "et pas negatif",
        lambda m, v: m["artefact_1d"] is not None and m["artefact_1d"] > v),
}


class Criteres:
    def __init__(self, chemin: str):
        import pathlib
        sys.path.insert(0, ".claude/skills")
        from or_commun import sections

        bloc = sections.bloc_machine(
            pathlib.Path(chemin).read_text(encoding="utf-8"))
        if not bloc:
            raise SystemExit(f"ARRET : aucun bloc CRITERE-MACHINE dans {chemin}")
        self.source, self.bloc = chemin, bloc
        self.tirages = int(float(bloc.get("tirages_placebo", 200)))
        self.graine = int(float(bloc.get("graine", GRAINE)))
        self.schema = bloc.get("placebo_schema", "")
        if not self.schema:
            raise SystemExit("ARRET : le critere n a pas de [placebo_schema]."
                             " Les bancs publies ont utilise UNIFORME : le"
                             " deviner reproduirait le mauvais chiffre.")
        self.tolerance = float(bloc.get("tolerance_reproduction_pct",
                                        REPRODUCTION_DEFAUT_PCT))
        noms = [c.strip() for c in bloc.get("cellules_horizon", "").split(",")
                if c.strip()]
        if not noms:
            raise SystemExit("ARRET : le critere n a pas de [cellules_horizon]")
        self.cellules = {}
        for nom in noms:
            # ⛔ CHAQUE CELLULE EXIGE SES CINQ CHAMPS. En deviner un -- surtout
            # la fenetre -- mesurerait un autre horizon que celui annonce,
            # exactement la faute d etiquette du 27/10.
            manque = [c for c in ("horizon", "population", "fenetre_heures",
                                  "reference_esperance_reel",
                                  "reference_ecart")
                      if bloc.get(f"{c}_{nom}") is None]
            if manque:
                raise SystemExit(
                    "ARRET : cellule [%s] incomplete, champs absents : %s"
                    % (nom, ", ".join(f"{c}_{nom}" for c in manque)))
            self.cellules[nom] = {
                "horizon": bloc[f"horizon_{nom}"],
                "population_brute": bloc[f"population_{nom}"],
                "population": parse_population(bloc[f"population_{nom}"]),
                "fenetre_h": int(float(bloc[f"fenetre_heures_{nom}"])),
                "ref_esp": float(bloc[f"reference_esperance_reel_{nom}"]),
                "ref_ecart": float(bloc[f"reference_ecart_{nom}"]),
            }
        fin = bloc.get("fin_chargement")
        self.fin_chargement = datetime.fromisoformat(fin) if fin else None
        self.artefact_5min = float(bloc.get("artefact_5min_mesure", 0.0) or 0.0)
        self.decalage_5min = float(bloc.get("decalage_sur_risque_5min_mesure",
                                            0.0) or 0.0)
        self.predictions = {c: float(bloc[c]) for c in PREDICTIONS if c in bloc}


def mesure(db: str, cr: "Criteres") -> dict:
    j = logging.getLogger("banc")
    cellules = {}
    for nom in cr.cellules:
        r = une_cellule(nom, db, cr, j)
        if "erreur" in r:
            return r
        cellules[nom] = r

    m = {
        "forme": "placebo",
        "preinscription": cr.source,
        "graine": cr.graine,
        "placebo_schema": cr.schema,
        "artefact_5min_mesure": cr.artefact_5min,
        "decalage_sur_risque_5min_mesure": cr.decalage_5min,
        "cellules": list(cr.cellules),
        "ecart_par_trade": None,
        "placebo": f"{cr.tirages}_TIRAGES_GRAINE_{cr.graine}",
        "verdict": "RENDU_PAR_OR_VERDICT",
    }
    for nom, r in cellules.items():
        for k, v in r.items():
            m[f"{k}_{nom}"] = v

    m["n_reel"] = min(r["n_reel"] for r in cellules.values())
    m["couverture_min_pct"] = min(r["couverture_bougies_pct"]
                                  for r in cellules.values())
    m["tirages_aboutis_min"] = min(r["tirages_aboutis"]
                                   for r in cellules.values())
    m["part_entree_hors_bougie_fill_max_pct"] = max(
        r["part_entree_hors_bougie_fill_pct"] for r in cellules.values())
    m["ecart_reproduction_max_pct"] = max(
        max(r["reproduction_esperance_pct"], r["reproduction_ecart_pct"])
        for r in cellules.values())
    # `n` et `t` : les champs REQUIS par `or-verdict`. Le `t` publie est celui
    # de la cellule la plus large, et le critere ne branche pas dessus.
    m["n"] = m["n_reel"]
    m["t"] = cellules[list(cr.cellules)[-1]]["t_fill"]
    m["t_contre_placebo"] = m["t"]
    m["valide"] = True

    if m["ecart_reproduction_max_pct"] > cr.tolerance:
        return {**m, "erreur":
                "UNE CELLULE NE REPRODUIT PAS SON CHIFFRE PUBLIE : ecart"
                " maximum %.3f %% (tolerance %.1f %%)."
                % (m["ecart_reproduction_max_pct"], cr.tolerance)}

    m["predictions"] = {}
    for cle, seuil in cr.predictions.items():
        libelle, test = PREDICTIONS[cle]
        m["predictions"][cle] = {"seuil": seuil, "libelle": libelle,
                                 "passe": bool(test(m, seuil))}
    return m


def rapport(m: dict) -> str:
    if "erreur" in m:
        return "=== ARRET : " + str(m["erreur"])
    L = ["",
         "  placebo %s   reproduction maximale %.3f %%"
         % (m["placebo_schema"], m["ecart_reproduction_max_pct"]),
         "",
         "  %-6s %7s %9s %11s %11s %11s %9s %9s"
         % ("CELL.", "n", "risk%", "reel STOCKE", "reel FILL", "ARTEFACT",
            "ecart fi", "t fill"),
         ]
    for nom in m["cellules"]:
        g = lambda k: m[f"{k}_{nom}"]
        L.append("  %-6s %7d %9.4f %+11.6f %+11.6f %+11.6f %+9.4f %+9.3f"
                 % (nom, g("n_reel"), g("risk_pct_median"),
                    g("esperance_reel_stocke"), g("esperance_reel_fill"),
                    g("artefact"), g("ecart_fill"), g("t_fill")))
    L += ["",
          "  pour memoire, 5min hors echantillon : artefact %+.6f,"
          " decalage/risque %.3f"
          % (m["artefact_5min_mesure"], m["decalage_sur_risque_5min_mesure"]),
          ""]
    for nom in m["cellules"]:
        g = lambda k: m[f"{k}_{nom}"]
        L.append("  --- %s : decalage/risque median %.4f   entrees hors"
                 " bougie %.1f %% (stocke) / %.1f %% (fill)"
                 % (nom, g("mediane_decalage_sur_risque"),
                    g("part_entree_hors_bougie_stocke_pct"),
                    g("part_entree_hors_bougie_fill_pct")))
        for etiq, cle in (("stocke", "premiere_bougie_stocke"),
                          ("fill  ", "premiere_bougie_fill"),
                          ("placebo", "premiere_bougie_placebo")):
            sl, tp = g(cle)
            L.append("      1re bougie %-7s SL %5.1f %%  TP1 %5.1f %%"
                     "   =>  %+.4f R" % (etiq, sl, tp, (tp * 1.8 - sl) / 100))
    L.append("")
    for cle, d in m.get("predictions", {}).items():
        L.append("  %-34s %-6s seuil %s   (%s)"
                 % (cle, "PASSE" if d["passe"] else "ECHEC", d["seuil"],
                    d["libelle"]))
    L += ["", "  VERDICT : " + m.get("verdict", "?")]
    return "\n".join(L)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--preinscription", required=True)
    p.add_argument("--db", default=None)
    p.add_argument("--json")
    p.add_argument("--tirages", type=int, default=None)
    a = p.parse_args(argv)

    db = a.db
    if db is None:
        from backend.services.shadow_v2_core_long import DB_PATH
        db = str(DB_PATH)

    cr = Criteres(a.preinscription)
    if a.tirages:
        cr.tirages = a.tirages
    m = mesure(db, cr)

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=2, ensure_ascii=False, default=str)
    print(rapport(m))
    if a.json:
        print("\n  resultat machine : " + a.json)
    return 1 if "erreur" in m else 0


if __name__ == "__main__":
    raise SystemExit(main())
