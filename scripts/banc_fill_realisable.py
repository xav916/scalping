"""Banc : le signal `5min` survit-il a un prix d entree REALISABLE ?

Pre-inscrit dans `docs/preinscriptions/2026-10-28-fill-realisable.md`.
⛔ DIVULGATION obligatoire : `2026-10-28-fill-realisable-DIVULGATION.md` --
quatre des cinq reponses etaient deja connues avant l ecriture du critere, car
la passe ARRETEE de `a176cdf` portait precisement cette specification (c etait
son bug). Ce banc est donc CONFIRMATOIRE, pas predictif.

🔴 CE QUE LA MESURE PREALABLE A MONTRE. Toute la difference entre le bras reel
et le placebo vit dans la PREMIERE BOUGIE : resolution des la 1re bougie a
6,2 % SL / 7,0 % TP1 au reel contre 9,2 % / 2,7 % au placebo, soit +0,064 R
contre -0,043 R de contribution -- un ecart de +0,107 R pour un ecart TOTAL de
+0,092 R. Les 96 heures restantes ne contribuent rien.

🔴 ET LA CAUSE. `entry_price` n est ni une ouverture ni une cloture de bougie
dans 87,8 % des cas : c est un NIVEAU DE MOTIF, et il tombe HORS de la bougie
d entree dans 50,2 % des cas. Le banc accordait donc au bras reel un fill a un
prix souvent jamais traite, et net favorable (11,1 % d objectifs deja franchis
contre 2,0 % de stops). Le placebo, lui, entre toujours a l ouverture.

🔑 LA CORRECTION : une seule specification d execution pour LES DEUX BRAS --
entree a l ouverture de sa propre bougie d entree, barrieres a `± risk_pct`
autour. C est une RE-SPECIFICATION DU BRAS REEL, assumee, et c est pourquoi la
cellule `REF_STOCKE` doit reproduire les chiffres publies, sinon ARRET.

⚠️ UN SEUL PLACEBO POUR LES DEUX CELLULES. Le placebo entre deja a l ouverture
de sa bougie : il est donc INCHANGE par la re-specification. Seul le bras reel
change, et l ecart entre cellules est donc entierement attribuable a lui.

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
    GRAINE, RR, Serie, charge, lire_reels, parse_population,
    part_battus_pct, t_contre_placebo)
from scripts.banc_placebo_structure import instants_tires  # noqa: E402
from scripts.banc_anticorrelation_jambes import (  # noqa: E402
    r_par_setup, r_reel_par_setup)

REPRODUCTION_MAX_PCT = 1.0


def part_entree_hors_bougie_pct(couverts: list[dict],
                                series: dict[str, Serie],
                                stocke: bool) -> float:
    """Part des entrees situees HORS de l amplitude de leur bougie d entree.

    🔑 C est la garde qui prouve que la re-specification a AGI : elle doit
    valoir ~50 % sur l entree STOCKEE (un niveau de motif) et ZERO sur
    l ouverture, atteignable par construction.
    """
    hors = n = 0
    for d in couverts:
        s = series[d["pair"]]
        i = s.index_apres(d["bar"].timestamp())
        if i >= len(s):
            continue
        n += 1
        e = d["entry"] if stocke else float(s.open[i])
        if not (float(s.low[i]) <= e <= float(s.high[i])):
            hors += 1
    return (100.0 * hors / n) if n else 0.0


def taux_premiere_bougie(couverts: list[dict], series: dict[str, Serie],
                         instants: list[float],
                         stocke: bool) -> tuple[float, float]:
    """`(part SL, part TP1)` resolues DES la premiere bougie, en pourcent.

    ⛔ Reproduit la regle de `Serie.simule` : SL et TP touches dans la MEME
    bougie => SL. Sans cela, ces taux ne decriraient pas ce que le moteur fait.
    """
    sl0 = tp0 = n = 0
    for d, t in zip(couverts, instants):
        s = series[d["pair"]]
        i = s.index_apres(t)
        if i >= len(s) or d["risk_pct"] <= 0:
            continue
        if stocke:
            e, sl, tp = d["entry"], d["sl"], d["tp"]
        else:
            e = float(s.open[i])
            g = e * d["risk_pct"] / 100.0
            sg = 1 if d["achat"] else -1
            sl, tp = e - sg * g, e + sg * g * RR
        if e <= 0:
            continue
        n += 1
        t_sl = (float(s.low[i]) <= sl) if d["achat"] else (float(s.high[i]) >= sl)
        t_tp = (float(s.high[i]) >= tp) if d["achat"] else (float(s.low[i]) <= tp)
        if t_sl:
            sl0 += 1          # SL gagne les ex aequo, comme le moteur
        elif t_tp:
            tp0 += 1
    if not n:
        return 0.0, 0.0
    return 100.0 * sl0 / n, 100.0 * tp0 / n


PREDICTIONS = {
    "P1_ecart_signal_fill_max": (
        "l ecart s effondre depuis +0,092",
        lambda m, v: m["ecart_signal_fill"] is not None
        and m["ecart_signal_fill"] < v),
    "P2_t_fill_abs_max": (
        "le signal devient INDISCERNABLE du hasard",
        lambda m, v: m["t_fill"] is not None and abs(m["t_fill"]) < v),
    "P3_esperance_reel_fill_max": (
        "l esperance reelle chute nettement",
        lambda m, v: m["esperance_R_reel_fill"] is not None
        and m["esperance_R_reel_fill"] < v),
    "P4_asymetrie_premiere_bougie_pts_max": (
        "l asymetrie de premiere bougie DISPARAIT",
        lambda m, v: m["asymetrie_premiere_bougie_pts"] is not None
        and m["asymetrie_premiere_bougie_pts"] < v),
    "P5_ecart_signal_fill_plancher": (
        "et pas absurdement negatif",
        lambda m, v: m["ecart_signal_fill"] is not None
        and m["ecart_signal_fill"] > v),
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
        self.horizon = bloc.get("horizon", "5min")
        self.fenetre_h = int(float(bloc.get("fenetre_heures", 96)))
        self.tirages = int(float(bloc.get("tirages_placebo", 200)))
        self.graine = int(float(bloc.get("graine", GRAINE)))
        self.population = parse_population(bloc.get("population", ""))
        if bloc.get("source_bras_reel") != "RECALCULE":
            raise SystemExit("ARRET : ce banc exige source_bras_reel RECALCULE")
        cells = [c.strip() for c in bloc.get("cellules_fill", "").split(",")
                 if c.strip()]
        if cells != ["REF_STOCKE", "FILL_OUVERTURE"]:
            raise SystemExit(
                "ARRET : ce banc exige EXACTEMENT les cellules"
                " REF_STOCKE,FILL_OUVERTURE dans cet ordre -- la premiere est"
                " le controle de reproduction. Lu : %s" % cells)
        if bloc.get("cellule_decisive") != "FILL_OUVERTURE":
            raise SystemExit("ARRET : la cellule decisive doit etre"
                             " FILL_OUVERTURE")
        for cle in ("reference_esperance_reel_stocke", "reference_ecart_stocke"):
            if bloc.get(cle) is None:
                raise SystemExit(f"ARRET : le critere n a pas de [{cle}]")
        self.ref_esp = float(bloc["reference_esperance_reel_stocke"])
        self.ref_ecart = float(bloc["reference_ecart_stocke"])
        fin = bloc.get("fin_chargement")
        self.fin_chargement = datetime.fromisoformat(fin) if fin else None
        self.predictions = {c: float(bloc[c]) for c in PREDICTIONS if c in bloc}


def mesure(db: str, cr: "Criteres") -> dict:
    import asyncio
    j = logging.getLogger("banc")

    j.info("=== lecture de la population : %s", cr.bloc.get("population"))
    reels = lire_reels(db, cr.horizon, cr.population)
    if not reels:
        return {"erreur": "aucun setup dans la population pre-inscrite"}

    bornes: dict[str, tuple] = {}
    for d in reels:
        mn, mx = bornes.get(d["pair"], (d["bar"], d["bar"]))
        bornes[d["pair"]] = (min(mn, d["bar"]), max(mx, d["bar"]))

    j.info("=== chargement des bougies")
    series = asyncio.run(charge(bornes, cr.fin_chargement))
    couverts = [d for d in reels if d["pair"] in series]
    couverture = 100.0 * len(couverts) / len(reels)
    instants_reels = [d["bar"].timestamp() for d in couverts]

    # ─── les DEUX bras reels, sur les memes bougies ───
    # ⛔ `STOCKE` garde la geometrie d aout. `FILL` entre a l ouverture de sa
    # bougie d entree, avec le `risk_pct` stocke : c est EXACTEMENT ce que
    # `r_par_setup` calcule, donc la fonction est reutilisee telle quelle.
    def _esp(rs):
        v = [x[1] for x in rs if x is not None]
        return statistics.fmean(v) if v else None

    esp_stocke = _esp(r_reel_par_setup(couverts, series, cr.fenetre_h))
    esp_fill = _esp(r_par_setup(couverts, series, instants_reels,
                                cr.fenetre_h))
    if esp_stocke is None or esp_fill is None:
        return {"erreur": "un bras reel ne rend aucune issue"}

    # ─── le placebo, UNIQUE : il entre deja a l ouverture ───
    j.info("=== placebo RESEAU : %d tirages", cr.tirages)
    alea = random.Random(cr.graine)
    esperances: list[float] = []
    for k in range(cr.tirages):
        inst = instants_tires("RESEAU", couverts, bornes, alea)
        e = _esp(r_par_setup(couverts, series, inst, cr.fenetre_h))
        if e is not None:
            esperances.append(e)
        if (k + 1) % 50 == 0:
            j.info("    tirage %d / %d", k + 1, cr.tirages)
    esp_placebo = statistics.fmean(esperances) if esperances else None
    sd = statistics.stdev(esperances) if len(esperances) > 1 else None
    if esp_placebo is None or not sd:
        return {"erreur": "le placebo ne rend pas de distribution"}

    # ─── les taux de premiere bougie ───
    sl_st, tp_st = taux_premiere_bougie(couverts, series, instants_reels, True)
    sl_fi, tp_fi = taux_premiere_bougie(couverts, series, instants_reels, False)
    inst0 = instants_tires("RESEAU", couverts, bornes,
                           random.Random(cr.graine))
    sl_pl, tp_pl = taux_premiere_bougie(couverts, series, inst0, False)

    ecart_stocke = esp_stocke - esp_placebo
    ecart_fill = esp_fill - esp_placebo
    repro = max(100.0 * abs(esp_stocke - cr.ref_esp) / abs(cr.ref_esp),
                100.0 * abs(ecart_stocke - cr.ref_ecart) / abs(cr.ref_ecart))

    m = {
        "forme": "placebo",
        "preinscription": cr.source,
        "divulgation": "docs/preinscriptions/2026-10-28-fill-realisable-DIVULGATION.md",
        "graine": cr.graine,
        "horizon": cr.horizon,
        "fenetre_heures": cr.fenetre_h,
        "n": len(couverts), "n_reel": len(couverts),
        "couverture_bougies_pct": couverture,
        "source_bras_reel": "RECALCULE",
        "esperance_R_placebo": esp_placebo,
        "sd_nul": sd,
        "tirages_aboutis": len(esperances),
        "esperance_R_reel_stocke": esp_stocke,
        "esperance_R_reel_fill": esp_fill,
        "ecart_signal_stocke": ecart_stocke,
        "ecart_signal_fill": ecart_fill,
        "t_stocke": ecart_stocke / sd,
        "t_fill": ecart_fill / sd,
        "tirages_battus_pct_fill": part_battus_pct(esp_fill, esperances),
        "ecart_reproduction_max_pct": repro,
        "part_entree_hors_bougie_stocke_pct":
            part_entree_hors_bougie_pct(couverts, series, True),
        "part_entree_hors_bougie_fill_pct":
            part_entree_hors_bougie_pct(couverts, series, False),
        "premiere_bougie_sl_stocke_pct": sl_st,
        "premiere_bougie_tp_stocke_pct": tp_st,
        "premiere_bougie_sl_fill_pct": sl_fi,
        "premiere_bougie_tp_fill_pct": tp_fi,
        "premiere_bougie_sl_placebo_pct": sl_pl,
        "premiere_bougie_tp_placebo_pct": tp_pl,
        "asymetrie_premiere_bougie_pts":
            abs(tp_fi - tp_pl) + abs(sl_fi - sl_pl),
        "asymetrie_premiere_bougie_stocke_pts":
            abs(tp_st - tp_pl) + abs(sl_st - sl_pl),
        "placebo": f"{cr.tirages}_TIRAGES_GRAINE_{cr.graine}",
        "ecart_par_trade": None,
        "t": ecart_fill / sd,
        "t_contre_placebo": ecart_fill / sd,
        "ecart_signal": ecart_fill,
        "valide": True,
        "verdict": "RENDU_PAR_OR_VERDICT",
    }

    if repro > REPRODUCTION_MAX_PCT:
        return {**m, "erreur":
                "LA CELLULE REF_STOCKE NE REPRODUIT PAS LES CHIFFRES PUBLIES :"
                " ecart maximum %.3f %% (tolerance %.1f %%). Sans elle, la"
                " comparaison entre specifications n a aucun sens."
                % (repro, REPRODUCTION_MAX_PCT)}

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
         "  n = %d   couverture %.2f %%   reproduction %.3f %%"
         % (m["n_reel"], m["couverture_bougies_pct"],
            m["ecart_reproduction_max_pct"]),
         "  placebo (unique) %+.6f   sd nul %.6f   %d tirages"
         % (m["esperance_R_placebo"], m["sd_nul"], m["tirages_aboutis"]),
         "",
         "  %-16s %12s %12s %9s" % ("BRAS REEL", "esperance", "ECART", "t"),
         "  %-16s %+12.6f %+12.6f %+9.3f"
         % ("STOCKE", m["esperance_R_reel_stocke"], m["ecart_signal_stocke"],
            m["t_stocke"]),
         "  %-16s %+12.6f %+12.6f %+9.3f"
         % ("FILL OUVERTURE", m["esperance_R_reel_fill"],
            m["ecart_signal_fill"], m["t_fill"]),
         "",
         "  entrees HORS de leur bougie : stocke %.1f %%   fill %.1f %%"
         % (m["part_entree_hors_bougie_stocke_pct"],
            m["part_entree_hors_bougie_fill_pct"]),
         "  des la 1re bougie   SL / TP1 :",
         "     reel STOCKE  %.1f %% / %.1f %%   (asymetrie %.1f pts)"
         % (m["premiere_bougie_sl_stocke_pct"],
            m["premiere_bougie_tp_stocke_pct"],
            m["asymetrie_premiere_bougie_stocke_pts"]),
         "     reel FILL    %.1f %% / %.1f %%   (asymetrie %.1f pts)"
         % (m["premiere_bougie_sl_fill_pct"],
            m["premiere_bougie_tp_fill_pct"],
            m["asymetrie_premiere_bougie_pts"]),
         "     placebo      %.1f %% / %.1f %%"
         % (m["premiere_bougie_sl_placebo_pct"],
            m["premiere_bougie_tp_placebo_pct"]),
         ""]
    for cle, d in m.get("predictions", {}).items():
        L.append("  %-40s %-6s seuil %s   (%s)"
                 % (cle, "PASSE" if d["passe"] else "ECHEC", d["seuil"],
                    d["libelle"]))
    L += ["", "  VERDICT : " + m.get("verdict", "?"),
          "  ⛔ DIVULGATION : " + m["divulgation"]]
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
