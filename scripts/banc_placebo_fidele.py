"""Banc : un placebo FIDELE a la dissymetrie des deux jambes.

Pre-inscrit dans `docs/preinscriptions/2026-10-28-placebo-fidele-decalage.md`.

⛔ CE QU IL REMPLACE. En `8935497` j ai corrige le `t` de +5,602 a ~ +4,58 en
injectant le `rho` reel dans une FORMULE qui suppose la variance par jambe
identique entre schemas -- hypothese non verifiee, donc chiffre APPROCHE.

🔑 PLUTOT QUE DE VERIFIER LA FORMULE, ON LA REND INUTILE. Le placebo apparie
donne LA MEME entree aux deux jambes (l ouverture de la bougie tiree) : elles
sont donc en miroir, et leur anti-correlation (-0,443) depasse de loin celle du
reel (-0,127). Le barreau `RESEAU_PAIRES_DECALAGE` donne a chaque jambe son
PROPRE ratio d aout -- `entry_stocke / open(bougie apres sa barre)` -- applique
a la bougie tiree. Les deux jambes restent ouvertes au MEME instant, mais a des
niveaux dissymetriques dans la MEME proportion qu au reel.

⚠️ Et ce decalage est minuscule en prix mais ENORME en unites de risque : les
quartiles valent +/- 0,067 % quand le `risk_pct` median vaut 0,2106 %, soit
~ un tiers de la distance au stop. Verifie AVANT d ecrire ce fichier.

🔑 LES DEUX BARREAUX APPARIES PARTAGENT LEURS INSTANTS. `instants_tires` est
appele avec le meme schema et la meme graine pour les deux : la suite tiree est
donc IDENTIQUE, et la difference de `rho` est attribuable aux seuls decalages
d entree. C est un controle que je n avais pas prevu et qui vient gratuitement.

⛔ Le moteur, le tirage et les outils de correlation sont IMPORTES
(`banc_esperance_horizon`, `banc_placebo_structure`,
`banc_anticorrelation_jambes`) : aucun des bancs publies n est modifie.

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
    GRAINE, RR, Serie, charge, lire_reels, parse_population, pnl_pct)
from scripts.banc_placebo_structure import instants_tires  # noqa: E402
from scripts.banc_anticorrelation_jambes import (  # noqa: E402
    Accumulateur, duos, r_reel_par_setup)

#: Le schema de tirage d INSTANTS utilise par les deux barreaux apparies.
#: ⛔ Le barreau `DECALAGE` ne change PAS le tirage, seulement l entree.
SCHEMA_INSTANTS = {
    "RESEAU": "RESEAU",
    "RESEAU_ET_PAIRES": "RESEAU_ET_PAIRES",
    "RESEAU_PAIRES_DECALAGE": "RESEAU_ET_PAIRES",
}
#: Les barreaux qui appliquent les ratios d entree d aout.
AVEC_DECALAGE = ("RESEAU_PAIRES_DECALAGE",)

REPRODUCTION_MAX_PCT = 1.0


def ratios_d_entree(couverts: list[dict],
                    series: dict[str, Serie]) -> list[float]:
    """Pour chaque setup, `entry_stocke / open(bougie apres sa barre)`.

    🔑 C est le decalage que la production a introduit : chaque motif calcule
    son propre niveau d entree sur la MEME barre. Le reproduire est tout ce qui
    distingue ce banc du precedent.

    Rend `1.0` quand la bougie manque : neutre, et compte dans
    `part_ratio_non_unitaire_pct` comme un ratio unitaire -- donc la garde
    devient PLUS exigeante, jamais plus permissive.
    """
    out = []
    for d in couverts:
        s = series[d["pair"]]
        i0 = s.index_apres(d["bar"].timestamp())
        o = float(s.open[i0]) if i0 < len(s) else 0.0
        out.append((d["entry"] / o) if o > 0 and d["entry"] > 0 else 1.0)
    return out


def r_par_setup_avec_ratios(couverts: list[dict], series: dict[str, Serie],
                            instants: list[float], fenetre_h: int,
                            ratios: list[float] | None = None
                            ) -> list[tuple[int, float, str] | None]:
    """Le `R` et l issue de chaque setup, entree eventuellement DECALEE.

    ⚠️ A `ratios=None` cette fonction doit etre IDENTIQUE a
    `banc_anticorrelation_jambes.r_par_setup` -- un test le verifie. Sans cela
    les barreaux `RESEAU` et `RESEAU_ET_PAIRES` d ici ne seraient pas
    comparables a ceux de `2613282`.
    """
    out: list[tuple[int, float, str] | None] = []
    for i, (d, t) in enumerate(zip(couverts, instants)):
        s = series[d["pair"]]
        i0 = s.index_apres(t)
        if i0 >= len(s):
            out.append(None)
            continue
        entry = float(s.open[i0]) * (ratios[i] if ratios else 1.0)
        if entry <= 0 or d["risk_pct"] <= 0:
            out.append(None)
            continue
        dist = entry * d["risk_pct"] / 100.0
        signe = 1 if d["achat"] else -1
        r = s.simule(i0, t + fenetre_h * 3600, d["achat"],
                     entry - signe * dist, entry + signe * dist * RR)
        if r is None:
            out.append(None)
            continue
        out.append((i, pnl_pct(entry, r[1], d["achat"]) / d["risk_pct"],
                    r[0]))
    return out


class VarianceParJambe:
    """Les sommes de la variance des `R`, toutes jambes et tirages confondus."""

    def __init__(self) -> None:
        self.n = 0
        self.s = self.ss = 0.0

    def ajoute(self, x: float) -> None:
        self.n += 1
        self.s += x
        self.ss += x * x

    def variance(self) -> float | None:
        if self.n < 2:
            return None
        m = self.s / self.n
        return self.ss / self.n - m * m


def un_barreau(nom: str, couverts: list[dict], series: dict[str, Serie],
               bornes: dict, ratios: list[float], fenetre_h: int,
               tirages: int, graine: int, esp_reel: float,
               paires_duos: list[tuple[int, int]]) -> dict:
    """Un barreau : son esperance, son ecart-type nul, son `rho`, sa variance."""
    j = logging.getLogger("banc")
    alea = random.Random(graine)
    acc = Accumulateur()
    var = VarianceParJambe()
    esperances: list[float] = []
    rs_utilises = ratios if nom in AVEC_DECALAGE else None
    for k in range(tirages):
        instants = instants_tires(SCHEMA_INSTANTS[nom], couverts, bornes, alea)
        rs = r_par_setup_avec_ratios(couverts, series, instants, fenetre_h,
                                     rs_utilises)
        vals = []
        for x in rs:
            if x is not None:
                vals.append(x[1])
                var.ajoute(x[1])
        if vals:
            esperances.append(statistics.fmean(vals))
        for ia, ib in paires_duos:
            a, b = rs[ia], rs[ib]
            if a is not None and b is not None:
                acc.ajoute(a[1], b[1], a[2], b[2])
        if (k + 1) % 50 == 0:
            j.info("    %s : tirage %d / %d", nom, k + 1, tirages)

    esp = statistics.fmean(esperances) if esperances else None
    sigma = statistics.stdev(esperances) if len(esperances) > 1 else None
    return {
        "tirages_aboutis": len(esperances),
        "esperance_R_placebo": esp,
        "ecart_signal": (esp_reel - esp) if esp is not None else None,
        "sd_nul": sigma,
        "t_contre_placebo": ((esp_reel - esp) / sigma
                             if sigma not in (None, 0.0) and esp is not None
                             else None),
        "rho_duos": acc.rho(),
        "part_un_tp_un_sl_pct": acc.part_un_tp_un_sl_pct(),
        "variance_par_jambe": var.variance(),
        "observations_rho": acc.n,
    }


PREDICTIONS = {
    "P1_ecart_rho_decalage_reel_max": (
        "le barreau FIDELE retrouve le rho REEL",
        lambda m, v: m["ecart_rho_decalage_reel"] is not None
        and m["ecart_rho_decalage_reel"] < v),
    "P2_rapport_variance_par_jambe_plancher": (
        "variance par jambe stable entre schemas (plancher)",
        lambda m, v: m["rapport_variance_par_jambe"] is not None
        and m["rapport_variance_par_jambe"] >= v),
    "P3_rapport_variance_par_jambe_plafond": (
        "variance par jambe stable entre schemas (plafond)",
        lambda m, v: m["rapport_variance_par_jambe"] is not None
        and m["rapport_variance_par_jambe"] <= v),
    "P4_rho_reseau_abs_max": (
        "controle NEGATIF : sans appariement, pas de correlation intra-duo",
        lambda m, v: m["rho_duos_reseau"] is not None
        and abs(m["rho_duos_reseau"]) < v),
    "P5_mediane_decalage_sur_risque_min": (
        "le decalage est grand devant la distance au stop",
        lambda m, v: m["mediane_decalage_sur_risque"] is not None
        and m["mediane_decalage_sur_risque"] > v),
}

BARREAUX = ("RESEAU", "RESEAU_ET_PAIRES", "RESEAU_PAIRES_DECALAGE")


class Criteres:
    """Les seuils ENGAGES, lus une fois et jamais devines."""

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
        schemas = [s.strip() for s in bloc.get("placebo_schemas", "").split(",")
                   if s.strip()]
        if schemas != list(BARREAUX):
            raise SystemExit(
                "ARRET : ce banc exige EXACTEMENT les barreaux %s dans cet"
                " ordre -- le 1er est le controle negatif, le 2e celui de"
                " `2613282`, le 3e le barreau FIDELE. Lu : %s"
                % (list(BARREAUX), schemas))
        if bloc.get("placebo_decisif") != "RESEAU_PAIRES_DECALAGE":
            raise SystemExit(
                "ARRET : le barreau decisif doit etre RESEAU_PAIRES_DECALAGE")
        for cle in ("reference_ecart_reseau", "reference_ecart_reseau_et_paires",
                    "reference_rho_reel"):
            if bloc.get(cle) is None:
                raise SystemExit(f"ARRET : le critere n a pas de [{cle}]")
        self.ref_reseau = float(bloc["reference_ecart_reseau"])
        self.ref_apparie = float(bloc["reference_ecart_reseau_et_paires"])
        self.ref_rho_reel = float(bloc["reference_rho_reel"])
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
    paires_duos = duos(couverts)
    ratios = ratios_d_entree(couverts, series)

    # ─── bras REEL, geometrie d aout, recalcule en memoire ───
    reel_rs = r_reel_par_setup(couverts, series, cr.fenetre_h)
    acc_reel = Accumulateur()
    for ia, ib in paires_duos:
        a, b = reel_rs[ia], reel_rs[ib]
        if a is not None and b is not None:
            acc_reel.ajoute(a[1], b[1], a[2], b[2])
    vals_reel = [x[1] for x in reel_rs if x is not None]
    if not vals_reel:
        return {"erreur": "le bras reel ne rend aucune issue"}
    esp_reel = statistics.fmean(vals_reel)

    barreaux = {}
    for nom in BARREAUX:
        j.info("=== barreau %s : %d tirages", nom, cr.tirages)
        barreaux[nom] = un_barreau(nom, couverts, series, bornes, ratios,
                                   cr.fenetre_h, cr.tirages, cr.graine,
                                   esp_reel, paires_duos)

    base = barreaux["RESEAU"]
    app = barreaux["RESEAU_ET_PAIRES"]
    dec = barreaux["RESEAU_PAIRES_DECALAGE"]

    # ⛔ CONTROLE DE REPRODUCTION contre `2613282`, sur les deux barreaux qui
    # y figuraient. Le troisieme est neuf, donc sans reference.
    repro = max(100.0 * abs(b["ecart_signal"] - ref) / abs(ref)
                if b["ecart_signal"] is not None else float("inf")
                for b, ref in ((base, cr.ref_reseau), (app, cr.ref_apparie)))

    rho_reel = acc_reel.rho()
    decalages = [abs(r - 1.0) * 100.0 / d["risk_pct"]
                 for r, d in zip(ratios, couverts) if d["risk_pct"] > 0]

    m = {
        "forme": "placebo",
        "preinscription": cr.source,
        "graine": cr.graine,
        "horizon": cr.horizon,
        "fenetre_heures": cr.fenetre_h,
        "n": len(couverts), "n_reel": len(couverts),
        "couverture_bougies_pct": couverture,
        "source_bras_reel": "RECALCULE",
        "esperance_R_reel": esp_reel,
        "duos": len(paires_duos),
        "ecart_reproduction_max_pct": repro,
        "rho_duos_reel": rho_reel,
        "rho_duos_reel_reference": cr.ref_rho_reel,
        "rho_duos_reseau": base["rho_duos"],
        "rho_duos_apparie": app["rho_duos"],
        "rho_duos_decalage": dec["rho_duos"],
        "ecart_rho_decalage_reel": (abs(dec["rho_duos"] - rho_reel)
                                    if dec["rho_duos"] is not None
                                    and rho_reel is not None else None),
        "ecart_rho_apparie_reel": (abs(app["rho_duos"] - rho_reel)
                                   if app["rho_duos"] is not None
                                   and rho_reel is not None else None),
        "rapport_variance_par_jambe": (
            dec["variance_par_jambe"] / base["variance_par_jambe"]
            if base["variance_par_jambe"] else None),
        "part_ratio_non_unitaire_pct": (
            100.0 * sum(1 for r in ratios if r != 1.0) / len(ratios)
            if ratios else 0.0),
        "mediane_decalage_sur_risque": (statistics.median(decalages)
                                        if decalages else None),
        "tirages_aboutis": dec["tirages_aboutis"],
        "placebo": f"{cr.tirages}_TIRAGES_GRAINE_{cr.graine}",
        "ecart_par_trade": None,
        "t": dec["t_contre_placebo"],
        "t_contre_placebo": dec["t_contre_placebo"],
        "ecart_signal": dec["ecart_signal"],
        "valide": True,
        "verdict": "RENDU_PAR_OR_VERDICT",
    }
    for nom, b in barreaux.items():
        for k, v in b.items():
            m[k + "_" + nom.lower().replace("reseau_paires_decalage",
                                            "decalage")] = v

    if repro > REPRODUCTION_MAX_PCT:
        return {**m, "erreur":
                "LES BARREAUX NE REPRODUISENT PAS `2613282` : ecart maximum"
                " %.3f %% (tolerance %.1f %%)." % (repro, REPRODUCTION_MAX_PCT)}

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
         "  n = %d   couverture %.2f %%   duos = %d"
         % (m["n_reel"], m["couverture_bougies_pct"], m["duos"]),
         "  reproduction de 2613282 : ecart maximum %.3f %%"
         % m["ecart_reproduction_max_pct"],
         "  ratios non unitaires : %.1f %%   mediane |decalage| / risque :"
         " %.3f"
         % (m["part_ratio_non_unitaire_pct"],
            m["mediane_decalage_sur_risque"]),
         "",
         "  %-24s %10s %9s %9s %9s %12s"
         % ("BARREAU", "ECART", "sd nul", "t", "rho", "var/jambe"),
         ]
    for nom in ("reseau", "reseau_et_paires", "decalage"):
        L.append("  %-24s %+10.6f %9.6f %+9.3f %+9.4f %12.5f"
                 % (nom.upper(), m["ecart_signal_" + nom], m["sd_nul_" + nom],
                    m["t_contre_placebo_" + nom], m["rho_duos_" + nom],
                    m["variance_par_jambe_" + nom]))
    L += ["",
          "  rho REEL : %+.4f   (reference %+.4f)"
          % (m["rho_duos_reel"], m["rho_duos_reel_reference"]),
          "  ecart au reel : DECALAGE %.4f   contre APPARIE %.4f"
          % (m["ecart_rho_decalage_reel"], m["ecart_rho_apparie_reel"]),
          "  rapport des variances par jambe (decalage / reseau) : %.4f"
          % m["rapport_variance_par_jambe"],
          ""]
    for cle, d in m.get("predictions", {}).items():
        L.append("  %-42s %-6s seuil %s   (%s)"
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

    # ⛔ LE JSON D ABORD.
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=2, ensure_ascii=False, default=str)
    print(rapport(m))
    if a.json:
        print("\n  resultat machine : " + a.json)
    return 1 if "erreur" in m else 0


if __name__ == "__main__":
    raise SystemExit(main())
