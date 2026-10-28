"""Banc : TROIS BRAS nommes, et un controle de reproduction qui TIENT.

Pre-inscrit dans `docs/preinscriptions/2026-10-28-trois-bras-1d.md`.
⛔ DIVULGATION : ce banc est CONFIRMATOIRE. La quasi-totalite de ses valeurs
est deja mesuree (voir la pre-inscription) ; seules `P3` et `P5` sont aveugles.

⛔ POURQUOI IL EXISTE. Le banc precedent nommait « STOCKE » un bras qui gardait
la GEOMETRIE d aout mais RECALCULAIT l issue, et je l ai compare a une
reference faite d issues STOCKEES. Son garde-fou a eu raison de s arreter, mais
j ai publie une cause fausse (corrigee en `f36faed`). Ici les trois bras sont
nommes sans ambiguite :

    ISSUE_STOCKEE          : `pnl_pct_net` de la base      -> REPRODUCTION
    GEOMETRIE_RECALCULEE   : entry d aout, issue rejouee   -> COMPARABLE au placebo
    FILL_OUVERTURE         : entree a l ouverture, rejouee -> specification REALISABLE

🔴 ET CE QUE LA CORRECTION A REVELE. Les criteres `1d`, `4h` et `5min` en
echantillon n ont pas de `source_bras_reel`, donc leur bras reel vient des
issues de la BASE tandis que leur placebo est SIMULE : c est l asymetrie de
provenance du 27/10, presente dans les TROIS verdicts publies et jamais
corrigee pour eux. Seul `GEOMETRIE_RECALCULEE` partage la provenance du
placebo.

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
    GRAINE, charge, esperance_R, lire_reels, parse_population)
from scripts.banc_placebo_structure import instants_tires  # noqa: E402
from scripts.banc_anticorrelation_jambes import (  # noqa: E402
    r_par_setup, r_reel_par_setup)
from scripts.banc_fill_realisable import (  # noqa: E402
    part_entree_hors_bougie_pct, taux_premiere_bougie)

BRAS = ("ISSUE_STOCKEE", "GEOMETRIE_RECALCULEE", "FILL_OUVERTURE")


def _esp(rs) -> float | None:
    v = [x[1] for x in rs if x is not None]
    return statistics.fmean(v) if v else None


def esperance_issue_stockee(couverts: list[dict]) -> float | None:
    """L esperance telle que les bancs PUBLIES la calculent : `pnl_pct_net`.

    🔑 C est le bras de REPRODUCTION, et le seul qui ne touche pas aux bougies.
    `esperance_R` divise `pnl` par `risk_pct`, exactement comme
    `banc_esperance_horizon` le fait sur sa branche `STOCKE`.
    """
    return esperance_R([(d["pnl"], d["risk_pct"]) for d in couverts
                        if d["pnl"] is not None and d["risk_pct"] > 0])


def une_cellule(nom: str, db: str, cr: "Criteres", j) -> dict:
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
    fh = conf["fenetre_h"]
    instants_reels = [d["bar"].timestamp() for d in couverts]

    # ⛔ L ORDRE COMPTE : `r_reel_par_setup` ECRASE `d["issue"]` ? Non -- il ne
    # modifie rien, il rend une liste. Mais `esperance_issue_stockee` lit
    # `d["pnl"]`, donc elle est appelee AVANT toute chose par prudence.
    esp_stockee = esperance_issue_stockee(couverts)
    rs_rec = r_reel_par_setup(couverts, series, fh)
    esp_rec = _esp(rs_rec)
    esp_fill = _esp(r_par_setup(couverts, series, instants_reels, fh))
    if None in (esp_stockee, esp_rec, esp_fill):
        return {"erreur": f"un bras ne rend aucune issue pour {nom}"}

    # desaccord d issue entre la base et le recalcul
    dif = cmp_ = 0
    for d, x in zip(couverts, rs_rec):
        if x is None:
            continue
        cmp_ += 1
        if x[2] != d["issue"]:
            dif += 1

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
    if esp_pl is None or not sd:
        return {"erreur": f"le placebo ne rend pas de distribution pour {nom}"}

    sl_rec, tp_rec = taux_premiere_bougie(couverts, series, instants_reels,
                                          True)
    sl_fi, tp_fi = taux_premiere_bougie(couverts, series, instants_reels, False)
    inst0 = instants_tires(cr.schema, couverts, bornes,
                           random.Random(cr.graine))
    sl_pl, tp_pl = taux_premiere_bougie(couverts, series, inst0, False)

    return {
        "n_reel": len(couverts),
        "couverture_bougies_pct": 100.0 * len(couverts) / len(reels),
        "fenetre_heures": fh,
        "risk_pct_median": statistics.median([d["risk_pct"] for d in couverts]),
        "esperance_issue_stockee": esp_stockee,
        "esperance_geometrie_recalculee": esp_rec,
        "esperance_fill": esp_fill,
        "esperance_placebo": esp_pl,
        "sd_nul": sd,
        "tirages_aboutis": len(esperances),
        # ⛔ Les ecarts du bras STOCKE sont publies pour MEMOIRE, en sachant
        # qu ils melangent les provenances -- c est le defaut des bancs publies.
        "ecart_issue_stockee": esp_stockee - esp_pl,
        "ecart_geometrie_recalculee": esp_rec - esp_pl,
        "ecart_fill": esp_fill - esp_pl,
        "t_issue_stockee": (esp_stockee - esp_pl) / sd,
        "t_geometrie_recalculee": (esp_rec - esp_pl) / sd,
        "t_fill": (esp_fill - esp_pl) / sd,
        "artefact": esp_rec - esp_fill,
        "desaccord_pct": (100.0 * dif / cmp_) if cmp_ else None,
        "desaccord_n": dif,
        "part_entree_hors_bougie_stocke_pct":
            part_entree_hors_bougie_pct(couverts, series, True),
        "part_entree_hors_bougie_fill_pct":
            part_entree_hors_bougie_pct(couverts, series, False),
        "premiere_bougie_recalculee": [sl_rec, tp_rec],
        "premiere_bougie_fill": [sl_fi, tp_fi],
        "premiere_bougie_placebo": [sl_pl, tp_pl],
        "reproduction_issue_stockee_pct":
            100.0 * abs(esp_stockee - conf["ref_stockee"])
            / abs(conf["ref_stockee"]),
        "reproduction_placebo_pct":
            100.0 * abs(esp_pl - conf["ref_placebo"]) / abs(conf["ref_placebo"]),
    }


PREDICTIONS = {
    "P1_reproduction_issue_stockee_max_pct": (
        "le bras ISSUE_STOCKEE reproduit les chiffres publies",
        lambda m, v: m["reproduction_issue_stockee_max_pct"] is not None
        and m["reproduction_issue_stockee_max_pct"] < v),
    "P2_desaccord_1d_pct_plafond": (
        "desaccord stocke/recalcule du 1d sous le plafond",
        lambda m, v: m["desaccord_pct_1d"] is not None
        and m["desaccord_pct_1d"] <= v),
    "P3_desaccord_4h_pct_plafond": (
        "desaccord du 4h sous le plafond (AVEUGLE)",
        lambda m, v: m["desaccord_pct_4h"] is not None
        and m["desaccord_pct_4h"] <= v),
    "P4_t_fill_1d_min": (
        "sous une execution realisable, le 1d est significativement POSITIF",
        lambda m, v: m["t_fill_1d"] is not None and m["t_fill_1d"] > v),
    "P5_reproduction_placebo_max_pct": (
        "le placebo des bancs publies n a pas derive (AVEUGLE)",
        lambda m, v: m["reproduction_placebo_max_pct"] is not None
        and m["reproduction_placebo_max_pct"] < v),
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
            raise SystemExit("ARRET : le critere n a pas de [placebo_schema]")
        bras = [b.strip() for b in bloc.get("bras", "").split(",") if b.strip()]
        if bras != list(BRAS):
            raise SystemExit(
                "ARRET : ce banc exige EXACTEMENT les bras %s dans cet ordre."
                " Lu : %s" % (list(BRAS), bras))
        if bloc.get("bras_reproduction") != "ISSUE_STOCKEE":
            raise SystemExit(
                "ARRET : le bras de reproduction doit etre ISSUE_STOCKEE --"
                " c est le seul qui lit les memes lignes que les bancs"
                " publies. C est la porte qui manquait au banc precedent.")
        if bloc.get("bras_comparable") != "GEOMETRIE_RECALCULEE":
            raise SystemExit(
                "ARRET : le bras comparable au placebo doit etre"
                " GEOMETRIE_RECALCULEE -- le placebo est SIMULE, donc seul un"
                " bras recalcule partage sa provenance.")
        self.tolerance = float(bloc.get("tolerance_reproduction_pct", 0.5))
        noms = [c.strip() for c in bloc.get("cellules_horizon", "").split(",")
                if c.strip()]
        if not noms:
            raise SystemExit("ARRET : le critere n a pas de [cellules_horizon]")
        self.cellules = {}
        for nom in noms:
            manque = [c for c in ("horizon", "population", "fenetre_heures",
                                  "reference_issue_stockee",
                                  "reference_placebo")
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
                "ref_stockee": float(bloc[f"reference_issue_stockee_{nom}"]),
                "ref_placebo": float(bloc[f"reference_placebo_{nom}"]),
            }
        fin = bloc.get("fin_chargement")
        self.fin_chargement = datetime.fromisoformat(fin) if fin else None
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
        "divulgation": cr.bloc.get("divulgation"),
        "graine": cr.graine,
        "placebo_schema": cr.schema,
        "bras": list(BRAS),
        "cellules": list(cr.cellules),
        "ecart_par_trade": None,
        "placebo": f"{cr.tirages}_TIRAGES_GRAINE_{cr.graine}",
        "verdict": "RENDU_PAR_OR_VERDICT",
    }
    for nom, r in cellules.items():
        for k, v in r.items():
            m[f"{k}_{nom}"] = v

    m["n_reel"] = min(r["n_reel"] for r in cellules.values())
    m["n"] = m["n_reel"]
    m["couverture_min_pct"] = min(r["couverture_bougies_pct"]
                                  for r in cellules.values())
    m["tirages_aboutis_min"] = min(r["tirages_aboutis"]
                                   for r in cellules.values())
    m["part_entree_hors_bougie_fill_max_pct"] = max(
        r["part_entree_hors_bougie_fill_pct"] for r in cellules.values())
    m["reproduction_issue_stockee_max_pct"] = max(
        r["reproduction_issue_stockee_pct"] for r in cellules.values())
    m["reproduction_placebo_max_pct"] = max(
        r["reproduction_placebo_pct"] for r in cellules.values())
    m["t"] = cellules["1d"]["t_fill"] if "1d" in cellules else None
    m["t_contre_placebo"] = m["t"]
    m["valide"] = True

    # ⛔ LA PORTE QUI MANQUAIT AU BANC PRECEDENT : elle prouve que je lis les
    # MEMES LIGNES que les bancs publies, et elle porte sur le seul bras qui
    # partage leur provenance.
    if m["reproduction_issue_stockee_max_pct"] > cr.tolerance:
        return {**m, "erreur":
                "LE BRAS ISSUE_STOCKEE NE REPRODUIT PAS LES CHIFFRES PUBLIES :"
                " ecart maximum %.4f %% (tolerance %.1f %%). Je ne lis donc pas"
                " les memes lignes, et RIEN de ce banc n est interpretable."
                % (m["reproduction_issue_stockee_max_pct"], cr.tolerance)}

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
         "  placebo %s   reproduction ISSUE_STOCKEE %.4f %%   placebo %.3f %%"
         % (m["placebo_schema"], m["reproduction_issue_stockee_max_pct"],
            m["reproduction_placebo_max_pct"]),
         ""]
    for nom in m["cellules"]:
        g = lambda k: m[f"{k}_{nom}"]
        L += ["  --- cellule %s : n = %d, risk median %.4f %%, fenetre %d h"
              % (nom, g("n_reel"), g("risk_pct_median"), g("fenetre_heures")),
              "      %-22s %12s %12s %9s" % ("BRAS", "esperance", "ECART", "t"),
              "      %-22s %+12.6f %+12.6f %+9.3f"
              % ("ISSUE_STOCKEE", g("esperance_issue_stockee"),
                 g("ecart_issue_stockee"), g("t_issue_stockee")),
              "      %-22s %+12.6f %+12.6f %+9.3f"
              % ("GEOMETRIE_RECALCULEE", g("esperance_geometrie_recalculee"),
                 g("ecart_geometrie_recalculee"), g("t_geometrie_recalculee")),
              "      %-22s %+12.6f %+12.6f %+9.3f"
              % ("FILL_OUVERTURE", g("esperance_fill"), g("ecart_fill"),
                 g("t_fill")),
              "      placebo %+.6f   sd nul %.6f   artefact %+.6f"
              % (g("esperance_placebo"), g("sd_nul"), g("artefact")),
              "      desaccord stocke/recalcule : %d (%.2f %%)   entrees hors"
              " bougie %.1f %% / %.1f %%"
              % (g("desaccord_n"), g("desaccord_pct"),
                 g("part_entree_hors_bougie_stocke_pct"),
                 g("part_entree_hors_bougie_fill_pct"))]
        for etiq, cle in (("recalculee", "premiere_bougie_recalculee"),
                          ("fill      ", "premiere_bougie_fill"),
                          ("placebo   ", "premiere_bougie_placebo")):
            sl, tp = g(cle)
            L.append("      1re bougie %s SL %5.1f %%  TP1 %5.1f %%  => %+.4f R"
                     % (etiq, sl, tp, (tp * 1.8 - sl) / 100))
        L.append("")
    for cle, d in m.get("predictions", {}).items():
        L.append("  %-40s %-6s seuil %s   (%s)"
                 % (cle, "PASSE" if d["passe"] else "ECHEC", d["seuil"],
                    d["libelle"]))
    L += ["", "  VERDICT : " + m.get("verdict", "?"),
          "  ⛔ DIVULGATION : " + str(m.get("divulgation"))]
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
