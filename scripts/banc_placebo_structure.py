"""Banc : une ECHELLE de placebos, chacun respectant une piece de plus de la
structure du bras reel.

Pre-inscrit dans `docs/preinscriptions/2026-10-28-placebo-reseau-et-paires-v2.md`
(v1 `2fb952b` remplacee : sa clause de validite etait impossible par
construction, voir la v2).

⛔ POURQUOI CE BANC EXISTE. Le placebo publie tire `uniform(min, max)` par
setup. Il conserve les paires, leur nombre, la periode, le `risk_pct`, le sens
et la fenetre -- et il differe du reel sur TROIS axes que personne n avait
isoles :

1. le reel est a la minute `:00` **cent fois sur cent**, le placebo se repartit
   sur les douze creneaux de l heure ;
2. le reel ouvre un achat ET une vente sur la MEME barre (1 877 duos de sens
   opposes sur 1 877), le placebo disperse les deux jambes ;
3. donc le `n` reel vaut 2 403 INSTANTS, pas 4 280 observations.

Chacun de ces axes peut a lui seul produire l ecart publie de +0,0874 R.

🔑 LE MOTEUR EST IMPORTE, PAS RECOPIE. `charge`, `Serie`, `controle_moteur`,
`lire_reels`, `esperance_R`, `pnl_pct` viennent de `banc_esperance_horizon` :
c est la seule facon de garantir que ces trois barreaux sont calcules par le
meme code que le resultat qu ils remettent en question. Le banc partage n est
PAS modifie -- quatre criteres publies en dependent.

⛔ ET LE BARREAU `UNIFORME` EST UN CONTROLE DE REPRODUCTION. Il doit rendre
l ecart publie (+0,0874 R) a 0,0005 pres. S il ne le rend pas, c est que ma
re-implementation du placebo diverge, et le banc S ARRETE : comparer les
barreaux entre eux n aurait alors aucun sens.

⛔ LECTURE SEULE sur la base (`mode=ro`). Rien n est ecrit nulle part.
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
    GRAINE, RR, SPREAD_PCT, Serie, charge, controle_moteur, esperance_R,
    lire_reels, parse_population, part_battus_pct, pnl_pct, t_contre_placebo)

#: Les schemas de tirage connus, du moins au plus fidele a la structure reelle.
#: ⛔ Un schema inconnu est un ARRET : se tromper doit rendre bavard.
SCHEMAS = ("UNIFORME", "RESEAU", "RESEAU_ET_PAIRES")

#: Tolerance du controle de reproduction du barreau `UNIFORME`.
TOLERANCE_REPRODUCTION = 0.0005


def _bornes_s(bornes: dict, paire: str) -> tuple[float, float]:
    mn, mx = bornes[paire]
    return mn.timestamp(), mx.timestamp()


def instants_tires(schema: str, couverts: list[dict], bornes: dict,
                   alea: random.Random) -> list[float]:
    """Un instant d entree par setup, selon le schema.

    `UNIFORME` reproduit **exactement** le tirage du banc d esperance :
    `alea.uniform(t0, t1)`, un appel par setup, dans l ordre de `couverts`.
    A graine egale et ordre egal, la suite tiree est donc identique.

    `RESEAU` tire une **heure pleine** : `t0 + 3600 k`. Comme `t0` est une barre
    reelle, donc deja a `:00`, tout le reseau l est. L entree retenue par
    `index_apres` tombe alors sur le MEME creneau intra-horaire que le reel.

    `RESEAU_ET_PAIRES` tire **un seul instant par groupe `(paire, barre)`** et
    le donne a tous les setups du groupe : les deux jambes opposees restent
    ouvertes au meme moment, comme au reel.
    """
    if schema == "UNIFORME":
        return [alea.uniform(*_bornes_s(bornes, d["pair"])) for d in couverts]

    if schema == "RESEAU":
        out = []
        for d in couverts:
            t0, t1 = _bornes_s(bornes, d["pair"])
            out.append(t0 + 3600.0 * alea.randint(0, max(0, int((t1 - t0) // 3600))))
        return out

    if schema == "RESEAU_ET_PAIRES":
        choisi: dict[tuple, float] = {}
        out = []
        for d in couverts:
            g = (d["pair"], d["bar"])
            if g not in choisi:
                t0, t1 = _bornes_s(bornes, d["pair"])
                choisi[g] = t0 + 3600.0 * alea.randint(
                    0, max(0, int((t1 - t0) // 3600)))
            out.append(choisi[g])
        return out

    raise SystemExit(
        f"ARRET : schema de tirage INCONNU [{schema}] -- connus : {SCHEMAS}."
        f" Le banc refuse de deviner.")


def part_sur_le_reseau_pct(instants: list[float]) -> float:
    """Part des instants tombant exactement sur une heure pleine."""
    if not instants:
        return 0.0
    return 100.0 * sum(1 for t in instants if t % 3600.0 == 0.0) / len(instants)


def groupes_respectes_pct(couverts: list[dict],
                          instants: list[float]) -> float:
    """Part des groupes `(paire, barre)` dont TOUS les setups partagent l instant.

    🔑 L INSTRUMENT QUI VERIFIE QUE LE REGROUPEMENT A AGI, et le bon : la v1 de
    la pre-inscription exigeait « autant d instants distincts qu au reel », ce
    que les COLLISIONS rendent impossible (343 groupes tires parmi 351 heures
    => ~1 533 distincts contre 2 403). J avais confondu la propriete avec une
    consequence qui n en est pas une.
    """
    par_groupe: dict[tuple, set] = {}
    for d, t in zip(couverts, instants):
        par_groupe.setdefault((d["pair"], d["bar"]), set()).add(t)
    if not par_groupe:
        return 0.0
    return 100.0 * sum(1 for v in par_groupe.values() if len(v) == 1) \
        / len(par_groupe)


def _esperance_d_un_tirage(couverts: list[dict], series: dict[str, Serie],
                           instants: list[float],
                           fenetre_h: int) -> tuple[float | None, list[float]]:
    """L esperance en R d un tirage, geometrie du setup reel conservee."""
    pts: list[tuple[float, float]] = []
    risks: list[float] = []
    for d, t in zip(couverts, instants):
        s = series[d["pair"]]
        i0 = s.index_apres(t)
        if i0 >= len(s):
            continue
        entry = float(s.open[i0])
        if entry <= 0:
            continue
        dist = entry * d["risk_pct"] / 100.0
        signe = 1 if d["achat"] else -1
        sl = entry - signe * dist
        tp = entry + signe * dist * RR
        r = s.simule(i0, t + fenetre_h * 3600, d["achat"], sl, tp)
        if r is None:
            continue
        pts.append((pnl_pct(entry, r[1], d["achat"]), d["risk_pct"]))
        risks.append(d["risk_pct"])
    return esperance_R(pts), risks


def un_barreau(schema: str, couverts: list[dict], series: dict[str, Serie],
               bornes: dict, fenetre_h: int, tirages: int,
               graine: int, esp_reel: float) -> dict:
    """Un barreau de l echelle : `tirages` tirages du schema donne.

    ⛔ Une graine NEUVE par schema : chaque barreau est ainsi reproductible
    seul, et l ordre des barreaux n influe sur aucun resultat.
    """
    j = logging.getLogger("banc")
    alea = random.Random(graine)
    esperances: list[float] = []
    risks_tous: list[float] = []
    instr = {}
    for k in range(tirages):
        instants = instants_tires(schema, couverts, bornes, alea)
        if k == 0:
            # Les instruments sont mesures sur le PREMIER tirage : ils portent
            # sur le SCHEMA, pas sur le hasard d un tirage particulier.
            instr = {
                "part_reseau_pct": part_sur_le_reseau_pct(instants),
                "groupes_respectes_pct": groupes_respectes_pct(couverts,
                                                               instants),
                "instants_distincts": len({(d["pair"], t) for d, t
                                           in zip(couverts, instants)}),
            }
        e, risks = _esperance_d_un_tirage(couverts, series, instants, fenetre_h)
        risks_tous.extend(risks)
        if e is not None:
            esperances.append(e)
        if (k + 1) % 50 == 0:
            j.info("    %s : tirage %d / %d", schema, k + 1, tirages)

    esp = statistics.fmean(esperances) if esperances else None
    return {
        **instr,
        "tirages_aboutis": len(esperances),
        "esperance_R_placebo": esp,
        "risk_pct_median_placebo": (statistics.median(risks_tous)
                                    if risks_tous else None),
        "ecart_signal": (esp_reel - esp) if esp is not None else None,
        "t_contre_placebo": t_contre_placebo(esp_reel, esperances),
        "tirages_battus_pct": part_battus_pct(esp_reel, esperances),
    }


#: Les predictions, lues par NOM dans le critere.
PREDICTIONS = {
    "P1_ecart_reseau_max": (
        "ecart du barreau RESEAU sous l ecart publie",
        lambda m, v: (m["ecart_signal_reseau"] is not None
                      and m["ecart_signal_reseau"] < v)),
    "P2_ecart_reseau_et_paires_max": (
        "ecart du barreau RESEAU_ET_PAIRES sous l ecart publie",
        lambda m, v: (m["ecart_signal_reseau_et_paires"] is not None
                      and m["ecart_signal_reseau_et_paires"] < v)),
    "P3_ecart_reseau_et_paires_min": (
        "ecart du barreau decisif AU-DESSUS du seuil",
        lambda m, v: (m["ecart_signal_reseau_et_paires"] is not None
                      and m["ecart_signal_reseau_et_paires"] > v)),
    "P4_t_reseau_et_paires_min": (
        "t du barreau decisif AU-DESSUS du seuil",
        lambda m, v: (m["t_contre_placebo_reseau_et_paires"] is not None
                      and m["t_contre_placebo_reseau_et_paires"] > v)),
    "P5_ecart_reseau_et_paires_plancher": (
        "au moins un tiers de l ecart publie survit",
        lambda m, v: (m["ecart_signal_reseau_et_paires"] is not None
                      and m["ecart_signal_reseau_et_paires"] > v)),
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
        self.source_bras_reel = bloc.get("source_bras_reel", "STOCKE")
        if self.source_bras_reel != "RECALCULE":
            raise SystemExit(
                f"ARRET : ce banc exige source_bras_reel RECALCULE (lu :"
                f" [{self.source_bras_reel}]) -- sans quoi le bras reel et les"
                f" placebos ne partagent pas leur source, defaut du 27/10.")
        self.schemas = [s.strip() for s
                        in bloc.get("placebo_schemas", "").split(",") if s.strip()]
        if not self.schemas:
            raise SystemExit("ARRET : le critere n a pas de [placebo_schemas]")
        for s in self.schemas:
            if s not in SCHEMAS:
                raise SystemExit(
                    f"ARRET : schema INCONNU [{s}] dans placebo_schemas --"
                    f" connus : {SCHEMAS}")
        self.decisif = bloc.get("placebo_decisif", "")
        if self.decisif not in self.schemas:
            raise SystemExit(
                f"ARRET : placebo_decisif [{self.decisif}] n est pas dans"
                f" placebo_schemas {self.schemas}")
        ref = bloc.get("reference_ecart_uniforme_publie")
        if ref is None:
            raise SystemExit(
                "ARRET : le critere n a pas de"
                " [reference_ecart_uniforme_publie] -- sans elle le barreau"
                " UNIFORME ne peut pas servir de controle de reproduction.")
        self.ref_uniforme = float(ref)
        fin = bloc.get("fin_chargement")
        self.fin_chargement = datetime.fromisoformat(fin) if fin else None
        self.predictions = {c: float(bloc[c]) for c in PREDICTIONS if c in bloc}


def mesure(db: str, cr: "Criteres", controle: bool = True) -> dict:
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

    j.info("=== chargement des bougies (peut prendre ~10 min)")
    series = asyncio.run(charge(bornes, cr.fin_chargement))
    couverts = [d for d in reels if d["pair"] in series]
    couverture = 100.0 * len(couverts) / len(reels)

    accord = essais = -1
    if controle:
        j.info("=== controle du moteur vectorise contre la production")
        accord, essais = controle_moteur(couverts, series, cr.fenetre_h)
        if essais and accord != essais:
            return {"erreur": "LE MOTEUR VECTORISE DIVERGE DE LA PRODUCTION",
                    "accord": accord, "essais": essais}

    # ─── le bras REEL, RECALCULE sur les bougies chargees ───
    # ⛔ RIEN N EST ECRIT EN BASE : le recalcul vit en memoire, comme en
    # `d591d42`. La GEOMETRIE d aout est conservee, seule l ISSUE est rejouee.
    n_dif = n_cmp = 0
    for d in couverts:
        s = series[d["pair"]]
        r = s.simule(s.index_apres(d["bar"].timestamp()),
                     d["bar"].timestamp() + cr.fenetre_h * 3600,
                     d["achat"], d["sl"], d["tp"])
        if r is None:
            d["pnl"] = None
            continue
        n_cmp += 1
        if r[0] != d["issue"]:
            n_dif += 1
        d["issue"] = r[0]
        d["pnl"] = pnl_pct(d["entry"], r[1], d["achat"])
    desaccord = (100.0 * n_dif / n_cmp) if n_cmp else None
    j.info("    bras reel RECALCULE : %.1f %% de desaccord (%d / %d)",
           desaccord or 0.0, n_dif, n_cmp)

    reel_pts = [(d["pnl"], d["risk_pct"]) for d in couverts
                if d["pnl"] is not None and d["risk_pct"] > 0]
    esp_reel = esperance_R(reel_pts)
    risk_med_reel = statistics.median([d["risk_pct"] for d in couverts])
    cout_R = (100.0 * SPREAD_PCT) / risk_med_reel

    m = {
        "forme": "placebo",
        "preinscription": cr.source,
        "graine": cr.graine,
        "horizon": cr.horizon,
        "fenetre_heures": cr.fenetre_h,
        "n": len(couverts),
        "n_reel": len(couverts),
        "couverture_bougies_pct": couverture,
        "controle_moteur_accord": accord,
        "controle_moteur_essais": essais,
        "source_bras_reel": "RECALCULE",
        "desaccord_avec_stocke_pct": desaccord,
        "esperance_R_reel": esp_reel,
        "risk_pct_median_reel": risk_med_reel,
        "cout_R_median": cout_R,
        "part_entrees_reseau_pct": part_sur_le_reseau_pct(
            [d["bar"].timestamp() for d in couverts]),
        "instants_distincts_reel": len({(d["pair"], d["bar"])
                                        for d in couverts}),
        "schemas": cr.schemas,
        "placebo_decisif": cr.decisif,
        "placebo": f"{cr.tirages}_TIRAGES_GRAINE_{cr.graine}",
        "ecart_par_trade": None,
        "verdict": "RENDU_PAR_OR_VERDICT",
    }

    for schema in cr.schemas:
        j.info("=== barreau %s : %d tirages", schema, cr.tirages)
        b = un_barreau(schema, couverts, series, bornes, cr.fenetre_h,
                       cr.tirages, cr.graine, esp_reel)
        suf = "_" + schema.lower()
        for k, v in b.items():
            m[k + suf] = v

    # ⛔ CONTROLE DE REPRODUCTION. Le barreau UNIFORME doit rendre l ecart
    # publie. Sinon ma re-implementation du placebo diverge et comparer les
    # barreaux entre eux n a aucun sens -- ce serait une mesure sur un
    # instrument non verifie, la faute du 27/10 transposee.
    eu = m.get("ecart_signal_uniforme")
    if eu is None or abs(eu - cr.ref_uniforme) > TOLERANCE_REPRODUCTION:
        return {**m, "erreur":
                "LE BARREAU UNIFORME NE REPRODUIT PAS L ECART PUBLIE :"
                " %s contre %s attendu (tolerance %s). Ma re-implementation"
                " du placebo diverge du banc d esperance : comparer les"
                " barreaux n aurait aucun sens."
                % (eu, cr.ref_uniforme, TOLERANCE_REPRODUCTION)}

    dec = "_" + cr.decisif.lower()
    m["part_placebo_reseau_pct"] = m["part_reseau_pct" + dec]
    m["groupes_respectes_pct"] = m["groupes_respectes_pct" + dec]
    m["instants_distincts_placebo_apparie"] = m["instants_distincts" + dec]
    m["tirages_aboutis"] = m["tirages_aboutis" + dec]
    m["ecart_signal"] = m["ecart_signal" + dec]
    m["t"] = m["t_contre_placebo" + dec]
    m["t_contre_placebo"] = m["t_contre_placebo" + dec]
    m["risk_pct_median_placebo"] = m["risk_pct_median_placebo" + dec]
    m["valide"] = True

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
         "  n = %d / %d   couverture %.2f %%   moteur %s / %s"
         % (m["n_reel"], m["n_reel"], m["couverture_bougies_pct"],
            m["controle_moteur_accord"], m["controle_moteur_essais"]),
         "  bras reel RECALCULE : %.1f %% de desaccord   esperance %+.4f R"
         % (m["desaccord_avec_stocke_pct"], m["esperance_R_reel"]),
         "  cout median %+.4f R   entrees sur le reseau horaire : %.1f %%"
         % (m["cout_R_median"], m["part_entrees_reseau_pct"]),
         "  instants distincts du reel : %d  (pour %d setups)"
         % (m["instants_distincts_reel"], m["n_reel"]),
         "",
         "  %-18s %10s %10s %9s %9s %10s %10s"
         % ("BARREAU", "placebo", "ECART", "t", "battus%", "reseau%",
            "groupes%"),
         ]
    for schema in m["schemas"]:
        s = "_" + schema.lower()
        L.append("  %-18s %+10.4f %+10.4f %+9.3f %9.1f %10.1f %10.1f"
                 % (schema, m["esperance_R_placebo" + s], m["ecart_signal" + s],
                    m["t_contre_placebo" + s], m["tirages_battus_pct" + s],
                    m["part_reseau_pct" + s], m["groupes_respectes_pct" + s]))
    L += ["",
          "  decisif : %s" % m["placebo_decisif"],
          "  instants distincts du placebo apparie : %d  (reel %d --"
          " l ecart est du aux COLLISIONS, pas a un defaut)"
          % (m["instants_distincts_placebo_apparie"],
             m["instants_distincts_reel"]),
          ""]
    for cle, d in m.get("predictions", {}).items():
        L.append("  %-38s %-6s seuil %s   (%s)"
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
    p.add_argument("--sans-controle-moteur", action="store_true")
    a = p.parse_args(argv)

    db = a.db
    if db is None:
        from backend.services.shadow_v2_core_long import DB_PATH
        db = str(DB_PATH)

    cr = Criteres(a.preinscription)
    if a.tirages:
        cr.tirages = a.tirages
    m = mesure(db, cr, controle=not a.sans_controle_moteur)

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
