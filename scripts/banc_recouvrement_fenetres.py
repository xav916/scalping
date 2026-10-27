"""Banc : le RECOUVREMENT TEMPOREL des fenetres, et sa structure.

Pre-inscrit dans `docs/preinscriptions/2026-10-28-recouvrement-fenetres.md`.

CE QUE CE BANC REPOND, ET CE QU IL NE REPOND PAS. Les bancs d esperance du
`5min` rendent un `t` contre une distribution de 200 tirages. J ai ecrit dans
le verdict `c5c68dc` que ce `t` « surestime la certitude » parce que les
fenetres de 96 h se recouvrent -- SANS L AVOIR MESURE. Ce banc le mesure.

🔑 LA NUANCE QUI COMPTE. Le `t` de ces bancs n est pas un `t` de Student sur
`n` observations independantes : chaque tirage du placebo est une moyenne sur
LES MEMES `n` setups, avec LES MEMES fenetres qui se recouvrent. La dispersion
entre tirages absorbe donc deja la correlation que le recouvrement induit --
pour autant que le schema de tirage la PRESERVE. Et c est la que ca coince :
le placebo tire `uniform(min, max)` par paire, donc il DETRUIT le regroupement
temporel des entrees reelles.

⛔ LE RECOUVREMENT MOYEN NE PEUT PAS TRANCHER SEUL. La concurrence moyenne vaut
`n x fenetre / etendue` QUELLE QUE SOIT la disposition des instants : c est un
premier moment, invariant par rearrangement. Il faut une statistique de
PAIRES. `recouvrement_moyen` en est une : moyennee SUR LES SETUPS, elle pese
davantage les regions denses, donc elle MONTE avec l agglomeration.

⛔ LECTURE SEULE sur la base (`mode=ro`). Aucune bougie n est chargee : ce banc
ne travaille que sur des INSTANTS.

🔑 LA POPULATION VIENT DU BANC D ESPERANCE, PAS D UNE COPIE. `parse_population`
et `_sql_et_args` sont importes de `banc_esperance_horizon` : c est la seule
facon de garantir que ces statistiques portent sur EXACTEMENT les lignes
mesurees la-bas. Une reecriture, meme fidele le jour ou elle est ecrite, est
une seconde source de verite qui divergera.
"""
from __future__ import annotations

import argparse
import bisect
import json
import logging
import os
import random
import sqlite3
import statistics
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.banc_esperance_horizon import (  # noqa: E402
    GRAINE, _sql_et_args, parse_population)

#: Nombre de tirages de STRUCTURE. Vingt suffisent : la statistique mesuree
#: (un comptage sur des milliers de paires d instants) est tres concentree.
#: ⛔ C est aussi pourquoi son `t` n est PAS la variable de decision -- voir la
#: pre-inscription : sur une statistique aussi concentree, la significativite
#: est bon marche et ne dit rien de la MAGNITUDE.
TIRAGES_STRUCTURE = 20


def recouvrement_moyen(instants: list[float], fenetre_s: float) -> float:
    """Nombre moyen d AUTRES fenetres qui croisent celle d un setup.

    Deux fenetres `[t, t + W]` se croisent exactement quand
    `|t_i - t_j| < W`. Le comptage passe par une recherche dichotomique sur la
    liste triee : `O(n log n)` et non `O(n^2)`, faute de quoi les 18 668 lignes
    en echantillon demanderaient 348 millions de comparaisons.

    ⚠️ Moyennee SUR LES SETUPS : c est voulu. Cette ponderation fait monter la
    statistique quand les instants s agglomerent, alors que la concurrence
    moyennee sur le TEMPS est invariante par rearrangement.
    """
    if len(instants) < 2:
        return 0.0
    t = sorted(instants)
    total = 0
    for x in t:
        # ⛔ BORNES STRICTES. `bisect_right` a gauche et `bisect_left` a droite
        # excluent exactement `x +/- W` : deux fenetres qui se TOUCHENT en un
        # point ne se recouvrent pas. Avec les bisect inverses, `[0, W]` et
        # `[W, 2W]` comptaient comme un recouvrement.
        g = bisect.bisect_right(t, x - fenetre_s)
        d = bisect.bisect_left(t, x + fenetre_s)
        total += (d - g) - 1  # on se retire soi-meme
    return total / len(t)


#: Les origines de decoupage essayees, en fraction de fenetre. ⛔ Une seule
#: origine rendrait la statistique dependante d un choix arbitraire : un amas
#: a cheval sur une frontiere paraitrait etale. On moyenne sur quatre.
ORIGINES = (0.0, 0.25, 0.5, 0.75)


def blocs_effectifs(instants: list[float], fenetre_s: float) -> float:
    """Nombre EFFECTIF de blocs de largeur `fenetre_s` occupes (Herfindahl).

    🔑 POURQUOI CETTE STATISTIQUE PORTE LA DECISION, ET PAS LE RECOUVREMENT.
    Le rapport des recouvrements SATURE dans notre regime : a 611 setups sur
    336 h avec une fenetre de 96 h, le tirage uniforme donne deja ~299
    croisements par setup contre un plafond de 610, donc le rapport ne peut
    PAS depasser ~2,04. Un seuil engage a 2,00 y serait quasi infalsifiable --
    le quatrieme seuil impossible par construction, dans l autre sens.

    Le nombre effectif de blocs, lui, va de 1 (tout dans un bloc) a
    `etendue / fenetre` (~3,5 hors echantillon, ~17 en echantillon) : son
    amplitude est reelle, et il mesure directement ce qui compte -- combien
    d unites independantes la periode contient.

    `(somme n_b)^2 / somme n_b^2` : la mesure de Herfindahl inversee, qui vaut
    le nombre de blocs quand ils sont egaux et 1 quand un seul est peuple.
    """
    if not instants:
        return 0.0
    if len(instants) == 1:
        return 1.0
    origine0 = min(instants)
    valeurs = []
    for frac in ORIGINES:
        compte: dict[int, int] = {}
        for x in instants:
            b = int((x - origine0 + frac * fenetre_s) // fenetre_s)
            compte[b] = compte.get(b, 0) + 1
        n = sum(compte.values())
        valeurs.append((n * n) / sum(c * c for c in compte.values()))
    return statistics.fmean(valeurs)


def union_secondes(instants: list[float], fenetre_s: float) -> float:
    """Duree couverte par l UNION des fenetres, en secondes."""
    if not instants:
        return 0.0
    total = 0.0
    debut = fin = None
    for x in sorted(instants):
        if debut is None:
            debut, fin = x, x + fenetre_s
            continue
        if x <= fin:
            fin = max(fin, x + fenetre_s)
        else:
            total += fin - debut
            debut, fin = x, x + fenetre_s
    return total + (fin - debut)


def ecarts_consecutifs(par_paire: dict[str, list[float]]) -> list[float]:
    """Les ecarts entre entrees consecutives, toutes paires confondues."""
    out: list[float] = []
    for instants in par_paire.values():
        t = sorted(instants)
        out.extend(b - a for a, b in zip(t, t[1:]))
    return out


def statistiques(par_paire: dict[str, list[float]],
                 fenetre_s: float) -> dict:
    """Les statistiques de structure d un jeu d instants.

    `recouvrement_moyen` est agrege en ponderant chaque paire par son nombre
    de setups : c est la moyenne sur les SETUPS, pas sur les paires. Une paire
    a 5 setups ne doit pas peser autant qu une paire a 900.
    """
    n = sum(len(v) for v in par_paire.values())
    if n == 0:
        return {"n": 0, "paires": 0, "recouvrement_moyen": None,
                "blocs_effectifs": None,
                "somme_h": 0.0, "union_h": 0.0,
                "ratio_somme_sur_union": None, "n_eff_naif": None,
                "ecart_median_s": None, "etendue_h": None}
    pondere = sum(recouvrement_moyen(v, fenetre_s) * len(v)
                  for v in par_paire.values())
    union_s = sum(union_secondes(v, fenetre_s) for v in par_paire.values())
    somme_s = n * fenetre_s
    ecarts = ecarts_consecutifs(par_paire)
    etendues = [max(v) - min(v) for v in par_paire.values() if len(v) > 1]
    return {
        "n": n,
        "paires": len(par_paire),
        "recouvrement_moyen": pondere / n,
        # Somme sur les paires : le nombre total d unites independantes que
        # la periode offre, toutes paires confondues.
        "blocs_effectifs": sum(blocs_effectifs(v, fenetre_s)
                               for v in par_paire.values()),
        "somme_h": somme_s / 3600.0,
        "union_h": union_s / 3600.0,
        "ratio_somme_sur_union": (somme_s / union_s) if union_s > 0 else None,
        "n_eff_naif": union_s / fenetre_s,
        "ecart_median_s": statistics.median(ecarts) if ecarts else None,
        "etendue_h": (statistics.fmean(etendues) / 3600.0
                      if etendues else None),
    }


def tirage_placebo(par_paire: dict[str, list[float]],
                   alea: random.Random) -> dict[str, list[float]]:
    """Un tirage de structure, avec EXACTEMENT le schema du banc d esperance.

    `scripts/banc_esperance_horizon.py` fait, pour chaque setup :
        mn, mx = bornes[paire] ; t = alea.uniform(mn, mx)
    Les bornes sont le min et le max des barres REELLES de cette paire. On
    reproduit cela a l identique -- meme effectif par paire, memes bornes,
    meme loi -- pour que la seule difference mesuree soit le REGROUPEMENT.
    """
    out: dict[str, list[float]] = {}
    for paire, instants in par_paire.items():
        if not instants:
            out[paire] = []
            continue
        mn, mx = min(instants), max(instants)
        if mx <= mn:
            out[paire] = list(instants)
            continue
        out[paire] = [alea.uniform(mn, mx) for _ in instants]
    return out


def lire_instants(db: str, horizon: str, filtre: dict) -> dict[str, list[float]]:
    """Les instants des barres, par paire. Lecture seule, aucune bougie."""
    where, args = _sql_et_args(filtre, horizon)
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    lignes = c.execute(
        "SELECT pair, bar_timestamp FROM shadow_setups"
        " WHERE " + where + " ORDER BY pair, bar_timestamp", args).fetchall()
    c.close()
    out: dict[str, list[float]] = {}
    for paire, bt in lignes:
        d = datetime.fromisoformat(bt)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        out.setdefault(paire, []).append(d.timestamp())
    return out


def compare_a_la_structure_uniforme(par_paire: dict[str, list[float]],
                                    fenetre_s: float,
                                    tirages: int = TIRAGES_STRUCTURE,
                                    graine: int = GRAINE) -> dict:
    """Le reel contre `tirages` structures uniformes de meme effectif."""
    reel = statistiques(par_paire, fenetre_s)
    alea = random.Random(graine)
    recs: list[float] = []
    blocs: list[float] = []
    unions: list[float] = []
    for _ in range(tirages):
        s = statistiques(tirage_placebo(par_paire, alea), fenetre_s)
        if s["recouvrement_moyen"] is not None:
            recs.append(s["recouvrement_moyen"])
            blocs.append(s["blocs_effectifs"])
            unions.append(s["union_h"])
    moy = statistics.fmean(recs) if recs else None
    moy_b = statistics.fmean(blocs) if blocs else None
    sigma_b = statistics.stdev(blocs) if len(blocs) > 1 else None

    # ⛔ LE PLAFOND DE CHAQUE STATISTIQUE EST PUBLIE AVEC ELLE. Un rapport ne
    # veut rien dire sans l amplitude dans laquelle il vit : c est en l
    # ignorant que j ai engage un seuil a 2,00 sur une quantite plafonnee a
    # 2,04. Le plafond du recouvrement est `n/paire - 1` (tout agglomere) ;
    # celui des blocs effectifs est leur valeur sous le tirage UNIFORME, le
    # plancher etant 1 bloc par paire.
    plafond_rec = (reel["recouvrement_moyen"] / moy
                   if moy not in (None, 0) else None)
    n_par_paire = (reel["n"] / reel["paires"]) if reel["paires"] else 0
    return {
        **reel,
        "tirages_aboutis": len(recs),
        "recouvrement_moyen_placebo": moy,
        "blocs_effectifs_placebo": moy_b,
        "union_h_placebo": statistics.fmean(unions) if unions else None,
        # Descriptif : sature dans ce regime, donc jamais decisionnel.
        "ratio_recouvrement_reel_sur_placebo": plafond_rec,
        "ratio_recouvrement_MAXIMUM_ATTEIGNABLE": (
            (n_par_paire - 1) / moy if moy not in (None, 0) else None),
        # 🔑 LA VARIABLE DE DECISION : combien de fois MOINS d unites
        # independantes le reel occupe-t-il, par rapport a l uniforme.
        "ratio_blocs_placebo_sur_reel": (
            moy_b / reel["blocs_effectifs"]
            if reel.get("blocs_effectifs") not in (None, 0)
            and moy_b is not None else None),
        "ratio_blocs_MAXIMUM_ATTEIGNABLE": (
            moy_b / reel["paires"] if reel["paires"] and moy_b is not None
            else None),
        # ⛔ Publie comme DESCRIPTION, jamais comme decision : sur une
        # statistique aussi concentree, un ecart de 2 % rend un `t` enorme.
        "t_structure": (
            (reel["blocs_effectifs"] - moy_b) / sigma_b
            if sigma_b not in (None, 0.0) and moy_b is not None
            and reel.get("blocs_effectifs") is not None else None),
    }


#: Les predictions, lues par NOM dans le critere. Meme discipline que le banc
#: d esperance : un seuil engage sous un nom et mesure sous un autre n est pas
#: un seuil. Chaque entree est `(libelle, test)`.
PREDICTIONS = {
    "P1_recouvrement_moyen_min": (
        "recouvrement moyen AU-DESSUS du seuil sur les DEUX populations",
        lambda m, v: (m["recouvrement_moyen"] is not None
                      and m["recouvrement_moyen_secondaire"] is not None
                      and m["recouvrement_moyen"] >= v
                      and m["recouvrement_moyen_secondaire"] >= v)),
    "P2_ratio_somme_sur_union_min": (
        "redondance somme/union AU-DESSUS du seuil sur les DEUX populations",
        lambda m, v: (m["ratio_somme_sur_union"] is not None
                      and m["ratio_somme_sur_union_secondaire"] is not None
                      and m["ratio_somme_sur_union"] >= v
                      and m["ratio_somme_sur_union_secondaire"] >= v)),
    "P3_n_eff_naif_max": (
        "n_eff naif SOUS le seuil sur les DEUX populations",
        lambda m, v: (m["n_eff_naif"] is not None
                      and m["n_eff_naif_secondaire"] is not None
                      and m["n_eff_naif"] <= v
                      and m["n_eff_naif_secondaire"] <= v)),
    "P4_ratio_blocs_min": (
        "le reel occupe MOINS de blocs independants que l uniforme",
        lambda m, v: (m["ratio_blocs_placebo_sur_reel"] is not None
                      and m["ratio_blocs_placebo_sur_reel_secondaire"] is not None
                      and m["ratio_blocs_placebo_sur_reel"] > v
                      and m["ratio_blocs_placebo_sur_reel_secondaire"] > v)),
    "P5_ratio_blocs_max": (
        "perte de blocs BORNEE, sur les DEUX populations",
        lambda m, v: (m["ratio_blocs_placebo_sur_reel"] is not None
                      and m["ratio_blocs_placebo_sur_reel_secondaire"] is not None
                      and m["ratio_blocs_placebo_sur_reel"] < v
                      and m["ratio_blocs_placebo_sur_reel_secondaire"] < v)),
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
        self.source = chemin
        self.bloc = bloc
        self.horizon = bloc.get("horizon", "5min")
        self.fenetre_h = int(float(bloc.get("fenetre_heures", 96)))
        self.tirages = int(float(bloc.get("tirages_placebo",
                                          TIRAGES_STRUCTURE)))
        self.graine = int(float(bloc.get("graine", GRAINE)))
        # ⛔ LES DEUX POPULATIONS SONT EXIGEES. Les predictions portent sur les
        # DEUX ; en mesurer une seule puis lire les clauses rendrait un verdict
        # sur un critere PARTIEL.
        for cle in ("population", "population_secondaire"):
            if not bloc.get(cle):
                raise SystemExit(
                    f"ARRET : le critere n a pas de [{cle}]. Les predictions"
                    f" portent sur les DEUX populations : en mesurer une"
                    f" seule donnerait un verdict sur un critere partiel.")
        self.population = parse_population(bloc["population"])
        self.population_secondaire = parse_population(
            bloc["population_secondaire"])
        self.predictions = {c: float(bloc[c]) for c in PREDICTIONS
                            if c in bloc}


def mesure(db: str, cr: "Criteres") -> dict:
    j = logging.getLogger("recouvrement")
    fenetre_s = cr.fenetre_h * 3600.0

    j.info("=== population PRINCIPALE : %s", cr.bloc["population"])
    principale = lire_instants(db, cr.horizon, cr.population)
    j.info("=== population SECONDAIRE : %s", cr.bloc["population_secondaire"])
    secondaire = lire_instants(db, cr.horizon, cr.population_secondaire)

    if not principale or not secondaire:
        return {"erreur": "une population est VIDE -- principale %d lignes,"
                          " secondaire %d lignes"
                          % (sum(map(len, principale.values())),
                             sum(map(len, secondaire.values())))}

    a = compare_a_la_structure_uniforme(principale, fenetre_s,
                                        cr.tirages, cr.graine)
    b = compare_a_la_structure_uniforme(secondaire, fenetre_s,
                                        cr.tirages, cr.graine)

    m = dict(a)
    for k, v in b.items():
        m[k + "_secondaire"] = v
    m["n_secondaire"] = b["n"]

    m.update({
        "forme": "placebo",
        "preinscription": cr.source,
        "horizon": cr.horizon,
        "fenetre_heures": cr.fenetre_h,
        "graine": cr.graine,
        # ⛔ `t` est un champ REQUIS par `or-verdict` sur la forme placebo. On
        # y met le `t` de structure, et la pre-inscription dit en clair qu il
        # n est PAS la variable de decision.
        "t": a["t_structure"],
        "valide": True,
        "verdict": "RENDU_PAR_OR_VERDICT",
        "ecart_par_trade": None,
        "placebo": f"{cr.tirages}_TIRAGES_STRUCTURE_GRAINE_{cr.graine}",
    })

    m["predictions"] = {}
    for cle, seuil in cr.predictions.items():
        libelle, test = PREDICTIONS[cle]
        m["predictions"][cle] = {"seuil": seuil, "libelle": libelle,
                                 "passe": bool(test(m, seuil))}
    return m


def rapport(m: dict) -> str:
    if "erreur" in m:
        return "=== ARRET : " + m["erreur"]
    L = []
    for etiq, suf in (("HORS ECHANTILLON (principale)", ""),
                      ("EN ECHANTILLON (secondaire)", "_secondaire")):
        L.append("")
        L.append("--- " + etiq)
        L.append("  n = %d sur %d paires, etendue moyenne %.1f h"
                 % (m["n" + suf], m["paires" + suf], m["etendue_h" + suf]))
        L.append("  recouvrement moyen : %.1f autres fenetres par setup"
                 % m["recouvrement_moyen" + suf])
        L.append("  blocs independants : %.2f reel  contre %.2f uniforme"
                 "   (plancher %d = 1 par paire)"
                 % (m["blocs_effectifs" + suf],
                    m["blocs_effectifs_placebo" + suf], m["paires" + suf]))
        L.append("  somme %.0f h / union %.0f h  =>  redondance x%.1f"
                 % (m["somme_h" + suf], m["union_h" + suf],
                    m["ratio_somme_sur_union" + suf]))
        L.append("  n_eff naif (union / fenetre) : %.1f creneaux"
                 % m["n_eff_naif" + suf])
        L.append("  ecart median entre entrees : %.0f s (%.1f min)"
                 % (m["ecart_median_s" + suf],
                    m["ecart_median_s" + suf] / 60.0))
        L.append("  placebo uniforme : recouvrement %.1f, union %.0f h"
                 % (m["recouvrement_moyen_placebo" + suf],
                    m["union_h_placebo" + suf]))
        L.append("  recouvrement  reel/uniforme : x%.4f   (MAXIMUM"
                 " atteignable x%.3f -- sature, donc DESCRIPTIF)"
                 % (m["ratio_recouvrement_reel_sur_placebo" + suf],
                    m["ratio_recouvrement_MAXIMUM_ATTEIGNABLE" + suf]))
        L.append("  >>> DECISION  blocs uniforme/reel : x%.4f   (MAXIMUM"
                 " atteignable x%.3f)      (t de structure %s)"
                 % (m["ratio_blocs_placebo_sur_reel" + suf],
                    m["ratio_blocs_MAXIMUM_ATTEIGNABLE" + suf],
                    "%.2f" % m["t_structure" + suf]
                    if m["t_structure" + suf] is not None else "n/d"))
    L.append("")
    for cle, d in m.get("predictions", {}).items():
        L.append("  %-40s %-6s seuil %s   (%s)"
                 % (cle, "PASSE" if d["passe"] else "ECHEC",
                    d["seuil"], d["libelle"]))
    L.append("")
    L.append("  VERDICT : " + m.get("verdict", "?"))
    return "\n".join(L)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--preinscription", required=True)
    p.add_argument("--db", default=None)
    p.add_argument("--json")
    a = p.parse_args(argv)

    db = a.db
    if db is None:
        from backend.services.shadow_v2_core_long import DB_PATH
        db = str(DB_PATH)

    cr = Criteres(a.preinscription)
    m = mesure(db, cr)

    # ⛔ LE JSON D ABORD. Une mesure de douze minutes a deja ete perdue parce
    # que le RAPPORT levait sur une cle absente apres le calcul.
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=2, ensure_ascii=False)
    print(rapport(m))
    if a.json:
        print("\n  resultat machine : " + a.json)
    return 1 if "erreur" in m else 0


if __name__ == "__main__":
    raise SystemExit(main())
