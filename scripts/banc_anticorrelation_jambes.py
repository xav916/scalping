"""Banc : l ANTI-CORRELATION des deux jambes d un duo explique-t-elle la
baisse de 20,2 % de l ecart-type nul ?

Pre-inscrit dans `docs/preinscriptions/2026-10-28-anticorrelation-des-jambes.md`.

⛔ CE QUE CE BANC DOIT TRANCHER. Le verdict `2613282` a montre qu apparier les
deux jambes au meme instant fait baisser l ecart-type nul de 20,2 %
(0,020967 -> 0,016153), ce qui porte le `t` de +4,386 a +5,602 a ecart quasi
constant. J ai avance un mecanisme -- les deux jambes opposees ont des issues
anti-correlees -- SANS LE MESURER. Un ecart-type nul qui bouge pour une raison
inconnue n est pas un ecart-type nul sur lequel appuyer un `t`.

🔑 ET LE TEST N EST PAS LE SIGNE DE `rho`, C EST QU IL REPRODUISE LA BAISSE.
Avec N = 4 280 setups, D = 1 877 duos et S = 526 singletons :

    Var(moyenne) = (v / N) [ 1 + (2D / N) rho ]

Le `rho` mesure doit donc reconstruire `sd_observe` a partir de
`sd_baseline`. Un `rho` negatif mais petit laisserait la baisse inexpliquee, et
le mecanisme serait FAUX meme avec le bon signe.

⛔ UNE BAISSE DE VARIANCE NE PEUT PAS VENIR DU NOMBRE DE TIRAGES. Apparier fait
passer de 4 280 instants tires a 2 403 : a issues independantes, moins de
tirages donnerait PLUS de variance. Le signe de l effet exclut cette
explication, et c est ce qui rend l anti-correlation la candidate naturelle.

🔑 LE MOTEUR ET LE TIRAGE SONT IMPORTES. `instants_tires` vient de
`banc_placebo_structure`, le moteur de `banc_esperance_horizon` : les deux
barreaux sont donc tires et simules par le MEME code que `2613282`. Et ils sont
REJOUES dans cette passe, jamais repris de la precedente -- comparer un `rho`
mesure ici a un ecart-type mesure la-bas serait la faute de source du 27/10.
D ou la clause `ecart_reproduction_max_pct`.

⛔ LECTURE SEULE sur la base. Rien n est ecrit nulle part.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import random
import statistics
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.banc_esperance_horizon import (  # noqa: E402
    GRAINE, RR, Serie, charge, esperance_R, lire_reels, parse_population,
    pnl_pct)
from scripts.banc_placebo_structure import SCHEMAS, instants_tires  # noqa: E402

#: Tolerance du controle de reproduction des deux barreaux, en pourcent.
REPRODUCTION_MAX_PCT = 1.0


def r_par_setup(couverts: list[dict], series: dict[str, Serie],
                instants: list[float],
                fenetre_h: int) -> list[tuple[int, float, str] | None]:
    """Le `R` et l issue de chaque setup, a l instant qui lui est donne.

    ⚠️ C est volontairement la MEME arithmetique que
    `banc_placebo_structure._esperance_d_un_tirage`, mais rendue setup par
    setup -- la moyenne ne suffit pas quand on veut la correlation INTRA-duo.
    🔑 Un test verifie que la moyenne des `R` rendus ici egale exactement
    l esperance rendue par la fonction importee : sans cela, j aurais deux
    sources de verite pour la meme quantite.
    """
    out: list[tuple[int, float, str] | None] = []
    for i, (d, t) in enumerate(zip(couverts, instants)):
        s = series[d["pair"]]
        i0 = s.index_apres(t)
        if i0 >= len(s):
            out.append(None)
            continue
        entry = float(s.open[i0])
        if entry <= 0:
            out.append(None)
            continue
        dist = entry * d["risk_pct"] / 100.0
        signe = 1 if d["achat"] else -1
        sl = entry - signe * dist
        tp = entry + signe * dist * RR
        r = s.simule(i0, t + fenetre_h * 3600, d["achat"], sl, tp)
        if r is None or d["risk_pct"] <= 0:
            out.append(None)
            continue
        out.append((i, pnl_pct(entry, r[1], d["achat"]) / d["risk_pct"],
                    r[0]))
    return out


class Accumulateur:
    """Les sommes d une correlation INTRA-CLASSE sur des groupes de deux.

    ⛔ L ORDRE DES DEUX JAMBES D UN DUO EST ARBITRAIRE (il vient de l ordre de
    lecture en base). Une correlation de Pearson sur `(a, b)` dependrait donc
    d un ordre invente. On accumule la forme SYMETRIQUE -- chaque duo compte
    dans les deux sens -- qui est le coefficient intra-classe.
    """

    def __init__(self) -> None:
        self.n = 0
        self.sa = self.sb = self.saa = self.sbb = self.sab = 0.0
        self.un_tp_un_sl = 0

    def ajoute(self, a: float, b: float, issue_a: str, issue_b: str) -> None:
        self.n += 1
        self.sa += a
        self.sb += b
        self.saa += a * a
        self.sbb += b * b
        self.sab += a * b
        if {issue_a, issue_b} == {"TP1", "SL"}:
            self.un_tp_un_sl += 1

    def rho(self) -> float | None:
        if self.n < 2:
            return None
        m = (self.sa + self.sb) / (2.0 * self.n)
        var = (self.saa + self.sbb) / (2.0 * self.n) - m * m
        if var <= 0:
            return None
        cov = self.sab / self.n - m * m
        return cov / var

    def part_un_tp_un_sl_pct(self) -> float | None:
        return (100.0 * self.un_tp_un_sl / self.n) if self.n else None


def r_reel_par_setup(couverts: list[dict], series: dict[str, Serie],
                     fenetre_h: int) -> list[tuple[int, float, str] | None]:
    """Le `R` et l issue de chaque setup REEL, avec la GEOMETRIE D AOUT.

    🔴 LE BUG QUE LE CONTROLE DE REPRODUCTION A ATTRAPE LE 28/10.
    J avais evalue le bras reel avec `r_par_setup`, qui RECALCULE
    `entry`/`sl`/`tp` depuis la bougie tiree -- c est-a-dire avec la geometrie
    du PLACEBO. L esperance reelle sortait a **-0,1978** au lieu de **-0,0593**
    publie, soit **153 %** d ecart, et le banc s est ARRETE.

    🔑 Le bras reel garde ses bornes d aout (`entry`, `sl`, `tp` stockes) et
    ne rejoue que l ISSUE sur les bougies chargees -- exactement ce que fait
    `banc_placebo_structure.mesure`. Les deux barreaux de placebo, eux,
    etaient deja exacts : seul le bras reel etait faux.
    """
    out: list[tuple[int, float, str] | None] = []
    for i, d in enumerate(couverts):
        s_ = series[d["pair"]]
        t = d["bar"].timestamp()
        r = s_.simule(s_.index_apres(t), t + fenetre_h * 3600,
                      d["achat"], d["sl"], d["tp"])
        if r is None or d["risk_pct"] <= 0:
            out.append(None)
            continue
        out.append((i, pnl_pct(d["entry"], r[1], d["achat"]) / d["risk_pct"],
                    r[0]))
    return out


def sd_predite(sd_baseline, rho, duos_n: int, n: int) -> float | None:
    """L ecart-type nul reconstruit depuis `rho`, par la formule PRE-INSCRITE.

        Var(moyenne) = (v / N) [ 1 + (2D / N) rho ]
    donc   sd_apparie = sd_base * sqrt(1 + (2D / N) rho)

    ⛔ EXTRAITE POUR ETRE TESTABLE. Inline dans `mesure`, elle n etait
    couverte par aucun test : remplacer `2D/N` par `D/N` ne faisait tomber
    AUCUN test -- prouve par mutation. Une formule qui porte la prediction
    decisive ne peut pas vivre sans son propre test.

    Rend `None` si le facteur est negatif : un `rho` trop negatif pour la
    structure rendrait une variance impossible, et c est un fait a signaler,
    pas a masquer.
    """
    if not n or sd_baseline is None or rho is None:
        return None
    facteur = 1.0 + (2.0 * duos_n / n) * rho
    return sd_baseline * math.sqrt(facteur) if facteur > 0 else None


def duos(couverts: list[dict]) -> list[tuple[int, int]]:
    """Les paires d indices partageant `(paire, barre)`. Groupes de 2 SEULEMENT.

    ⚠️ Un groupe de taille autre que 2 est ignore : la formule de variance
    pre-inscrite ne couvre que `2D + S = N`. Le banc publie le compte, et la
    clause `duos >= 1877` refuse si la structure a change.
    """
    par_groupe: dict[tuple, list[int]] = {}
    for i, d in enumerate(couverts):
        par_groupe.setdefault((d["pair"], d["bar"]), []).append(i)
    return [tuple(v) for v in par_groupe.values() if len(v) == 2]


def un_barreau(schema: str, couverts: list[dict], series: dict[str, Serie],
               bornes: dict, fenetre_h: int, tirages: int, graine: int,
               esp_reel: float, paires_duos: list[tuple[int, int]],
               acc: Accumulateur | None) -> dict:
    """`tirages` tirages du schema, et l accumulation intra-duo si demandee."""
    j = logging.getLogger("banc")
    alea = random.Random(graine)
    esperances: list[float] = []
    for k in range(tirages):
        instants = instants_tires(schema, couverts, bornes, alea)
        rs = r_par_setup(couverts, series, instants, fenetre_h)
        vals = [x[1] for x in rs if x is not None]
        if vals:
            esperances.append(statistics.fmean(vals))
        if acc is not None:
            for ia, ib in paires_duos:
                a, b = rs[ia], rs[ib]
                if a is not None and b is not None:
                    acc.ajoute(a[1], b[1], a[2], b[2])
        if (k + 1) % 50 == 0:
            j.info("    %s : tirage %d / %d", schema, k + 1, tirages)

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
    }


PREDICTIONS = {
    "P1_rho_placebo_max": (
        "anti-correlation FRANCHE du placebo apparie",
        lambda m, v: m["rho_duos_placebo"] is not None
        and m["rho_duos_placebo"] < v),
    "P2_rho_placebo_plancher": (
        "et PAS un miroir parfait",
        lambda m, v: m["rho_duos_placebo"] is not None
        and m["rho_duos_placebo"] > v),
    "P3_ecart_sd_predit_pct_max": (
        "le rho mesure RECONSTRUIT l ecart-type observe",
        lambda m, v: m["ecart_sd_predit_pct"] is not None
        and m["ecart_sd_predit_pct"] < v),
    "P4_rho_reel_max": (
        "les duos REELS d aout sont aussi anti-correles",
        lambda m, v: m["rho_duos_reel"] is not None
        and m["rho_duos_reel"] < v),
    "P5_part_duos_un_tp_un_sl_pct_min": (
        "le mecanisme concret : une jambe TP1, l autre SL",
        lambda m, v: m["part_duos_un_tp_un_sl_pct"] is not None
        and m["part_duos_un_tp_un_sl_pct"] > v),
}


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
            raise SystemExit(
                "ARRET : ce banc exige source_bras_reel RECALCULE -- sans quoi"
                " le bras reel et les placebos ne partagent pas leur source.")
        self.schemas = [s.strip() for s
                        in bloc.get("placebo_schemas", "").split(",")
                        if s.strip()]
        for s in self.schemas:
            if s not in SCHEMAS:
                raise SystemExit(f"ARRET : schema INCONNU [{s}]")
        if self.schemas != ["RESEAU", "RESEAU_ET_PAIRES"]:
            raise SystemExit(
                "ARRET : ce banc exige EXACTEMENT les schemas"
                " RESEAU,RESEAU_ET_PAIRES dans cet ordre -- le premier est la"
                " base de variance, le second celui dont on explique la"
                " baisse. Lu : %s" % self.schemas)
        # ⛔ Les references de reproduction sont EXIGEES : sans elles, les deux
        # barreaux rejoues ici ne peuvent pas etre rattaches a `2613282`.
        for cle in ("reference_ecart_reseau", "reference_ecart_reseau_et_paires"):
            if bloc.get(cle) is None:
                raise SystemExit(f"ARRET : le critere n a pas de [{cle}]")
        self.ref_reseau = float(bloc["reference_ecart_reseau"])
        self.ref_apparie = float(bloc["reference_ecart_reseau_et_paires"])
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

    # ─── bras REEL, RECALCULE en memoire ───
    reel_rs = r_reel_par_setup(couverts, series, cr.fenetre_h)
    acc_reel = Accumulateur()
    for ia, ib in paires_duos:
        a, b = reel_rs[ia], reel_rs[ib]
        if a is not None and b is not None:
            acc_reel.ajoute(a[1], b[1], a[2], b[2])
    vals_reel = [x[1] for x in reel_rs if x is not None]
    esp_reel = statistics.fmean(vals_reel) if vals_reel else None
    if esp_reel is None:
        return {"erreur": "le bras reel ne rend aucune issue"}

    N = len(couverts)
    D = len(paires_duos)
    acc = Accumulateur()
    barreaux = {}
    for schema in cr.schemas:
        j.info("=== barreau %s : %d tirages", schema, cr.tirages)
        barreaux[schema] = un_barreau(
            schema, couverts, series, bornes, cr.fenetre_h, cr.tirages,
            cr.graine, esp_reel, paires_duos,
            acc if schema == "RESEAU_ET_PAIRES" else None)

    base = barreaux["RESEAU"]
    app = barreaux["RESEAU_ET_PAIRES"]

    # ⛔ CONTROLE DE REPRODUCTION des deux barreaux contre `2613282`.
    ecarts_pct = []
    for b, ref in ((base, cr.ref_reseau), (app, cr.ref_apparie)):
        if b["ecart_signal"] is None:
            ecarts_pct.append(float("inf"))
        else:
            ecarts_pct.append(100.0 * abs(b["ecart_signal"] - ref) / abs(ref))
    repro = max(ecarts_pct)

    rho = acc.rho()
    sd_predit = sd_predite(base["sd_nul"], rho, D, N)
    ecart_sd_pct = (100.0 * abs(sd_predit - app["sd_nul"]) / app["sd_nul"]
                    if sd_predit is not None and app["sd_nul"] else None)
    m = {
        "forme": "placebo",
        "preinscription": cr.source,
        "graine": cr.graine,
        "horizon": cr.horizon,
        "fenetre_heures": cr.fenetre_h,
        "n": N, "n_reel": N,
        "couverture_bougies_pct": couverture,
        "source_bras_reel": "RECALCULE",
        "esperance_R_reel": esp_reel,
        "instants_distincts_reel": len({(d["pair"], d["bar"])
                                        for d in couverts}),
        "duos": D,
        "facteur_2D_sur_N": 2.0 * D / N,
        "ecart_reproduction_max_pct": repro,
        "observations_rho": acc.n,
        "rho_duos_placebo": rho,
        "rho_duos_reel": acc_reel.rho(),
        "observations_rho_reel": acc_reel.n,
        "part_duos_un_tp_un_sl_pct": acc.part_un_tp_un_sl_pct(),
        "part_duos_un_tp_un_sl_reel_pct": acc_reel.part_un_tp_un_sl_pct(),
        "sd_nul_baseline": base["sd_nul"],
        "sd_nul_observe": app["sd_nul"],
        "sd_nul_predit": sd_predit,
        "ecart_sd_predit_pct": ecart_sd_pct,
        "tirages_aboutis": app["tirages_aboutis"],
        "placebo": f"{cr.tirages}_TIRAGES_GRAINE_{cr.graine}",
        "ecart_par_trade": None,
        "t": app["t_contre_placebo"],
        "t_contre_placebo": app["t_contre_placebo"],
        "valide": True,
        "verdict": "RENDU_PAR_OR_VERDICT",
    }
    for schema, b in barreaux.items():
        for k, v in b.items():
            m[k + "_" + schema.lower()] = v

    if repro > REPRODUCTION_MAX_PCT:
        return {**m, "erreur":
                "LES BARREAUX NE REPRODUISENT PAS `2613282` : ecart maximum"
                " %.3f %% (tolerance %.1f %%). Les deux passes ne mesurent pas"
                " la meme chose, donc le rho d ici ne peut pas expliquer"
                " l ecart-type de la-bas." % (repro, REPRODUCTION_MAX_PCT)}

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
         "  n = %d   couverture %.2f %%   duos = %d   2D/N = %.5f"
         % (m["n_reel"], m["couverture_bougies_pct"], m["duos"],
            m["facteur_2D_sur_N"]),
         "  reproduction de 2613282 : ecart maximum %.3f %%"
         % m["ecart_reproduction_max_pct"],
         "",
         "  ecart RESEAU           %+.6f   (sd nul %.6f)"
         % (m["ecart_signal_reseau"], m["sd_nul_baseline"]),
         "  ecart RESEAU_ET_PAIRES %+.6f   (sd nul %.6f)   t %+.3f"
         % (m["ecart_signal_reseau_et_paires"], m["sd_nul_observe"],
            m["t_contre_placebo"]),
         "",
         "  rho intra-duo PLACEBO : %+.4f   (sur %d duos-tirages)"
         % (m["rho_duos_placebo"], m["observations_rho"]),
         "  rho intra-duo REEL    : %+.4f   (sur %d duos)"
         % (m["rho_duos_reel"], m["observations_rho_reel"]),
         "  une jambe TP1 / l autre SL : %.1f %% du placebo, %.1f %% du reel"
         % (m["part_duos_un_tp_un_sl_pct"],
            m["part_duos_un_tp_un_sl_reel_pct"]),
         "",
         "  sd nul PREDIT depuis rho : %.6f   contre %.6f observe"
         "   =>  ecart %.2f %%"
         % (m["sd_nul_predit"], m["sd_nul_observe"],
            m["ecart_sd_predit_pct"]),
         ""]
    for cle, d in m.get("predictions", {}).items():
        L.append("  %-36s %-6s seuil %s   (%s)"
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

    # ⛔ LE JSON D ABORD : une mesure de douze minutes a deja ete perdue parce
    # que le rapport levait sur une cle absente apres le calcul.
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=2, ensure_ascii=False, default=str)
    print(rapport(m))
    if a.json:
        print("\n  resultat machine : " + a.json)
    return 1 if "erreur" in m else 0


if __name__ == "__main__":
    raise SystemExit(main())
