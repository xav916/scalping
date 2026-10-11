#!/usr/bin/env python3
"""L'objectif, ou le TRAINAGE, qui s'elargit avec le temps passe en positif.

Pre-inscrit dans docs/predictions/2026-10-11_objectif_selon_le_temps_en_positif.md
AVANT d'ecrire ce fichier.

Base commune : SL de depart -9 EUR, point milieu cote perte avec plancher
-2 EUR, stop suiveur a 0,50 EUR derriere le profit des 0,50 EUR de profit.

Le << temps en positif >> est le nombre CUMULE de minutes dont la cloture est
au-dessus de l'entree.
"""
from __future__ import annotations

import collections
import datetime as dt
import math
import os
import sqlite3
import statistics as st
import sys

MAGASIN = os.getenv("MAGASIN", "/app/data/candles_courtier_m1_complet.db")
EUR_USD = 1.1198
POINT_USD = 0.01
PAS_ENTREE = 30
CAP = 1440
PROT_AGE_MIN = 5
PROT_NEG_MIN = 2.5
MARGE_FRANCHIE = 0.10
INFINI = 1e9
DECLENCHE = 0.5        # le suiveur s'arme a partir de 0,50 EUR de profit

ECH_PROD = ((1.0, 0.75), (1.5, 1.25), (1.75, 1.5), (2.0, 1.75))


def trainage(mode, minutes_positif):
    """Largeur du trainage, en EUR, selon le temps passe en positif."""
    if mode == "fixe":
        return 0.5
    if mode == "elargit":
        return min(0.5 + 0.10 * minutes_positif, 2.0)
    if mode == "double":
        return min(0.5 * (2.0 ** (minutes_positif / 5.0)), 4.0)
    if mode == "resserre":
        return max(0.5 - 0.02 * minutes_positif, 0.10)
    return 0.5


def objectif(mode, minutes_positif):
    if mode == "aucun":
        return INFINI
    if mode == "temps":
        # 🔑 sa demande littérale : 2 EUR plus 1 EUR par minute en positif
        return 2.0 + 1.0 * minutes_positif
    return INFINI


# nom, mode_objectif, mode_trainage, echelle_prod (A2 uniquement)
STRATEGIES = (
    ("Z0 reference",      "aucun", "fixe",     False),
    ("Z1 TP selon temps", "temps", "fixe",     False),
    ("Z2 trainage +0,10", "aucun", "elargit",  False),
    ("Z3 trainage double", "aucun", "double",  False),
    ("Z4 trainage serre", "aucun", "resserre", False),
    ("A2 la production",  "palier", "prod",    True),
)


def charger():
    c = sqlite3.connect(MAGASIN)
    rows = c.execute("SELECT ts_utc, high, low, close, spread_pts FROM candles "
                     "WHERE pair = 'XAU/USD' ORDER BY ts_utc").fetchall()
    ts, hi, lo, cl, sp = [], [], [], [], []
    for t, h, l, c2, s in rows:
        d = dt.datetime.fromisoformat(t)
        ts.append(d.replace(tzinfo=None) if d.tzinfo else d)
        hi.append(h)
        lo.append(l)
        cl.append(c2)
        sp.append(s if s is not None else 5.0)
    return ts, hi, lo, cl, sp


def palier_prod(profit):
    cible = seuil = None
    for s, c in ECH_PROD:
        if profit >= s - 1e-9:
            cible, seuil = c, s
    return cible, seuil


def parcourir(hi, lo, cl, i, achat, cout_eur):
    e = cl[i]
    k = 1.0 / EUR_USD
    etats = {}
    for (nom, mo, mt, prod) in STRATEGIES:
        etats[nom] = {"stop": -20.0 if prod else -9.0, "tp": 2.0, "mo": mo,
                      "mt": mt, "prod": prod, "neg": 0, "pos": 0,
                      "fini": None, "sl0": 20.0 if prod else 9.0}
    fin = min(len(hi), i + 1 + CAP)
    for j in range(i + 1, fin):
        if achat:
            bas, haut, ferm = ((lo[j] - e) * k, (hi[j] - e) * k, (cl[j] - e) * k)
        else:
            bas, haut, ferm = ((e - hi[j]) * k, (e - lo[j]) * k, (e - cl[j]) * k)
        reste = False
        for nom, s in etats.items():
            if s["fini"] is not None:
                continue
            reste = True
            if bas <= s["stop"] + 1e-12:
                if s["stop"] > 1e-9:
                    issue = "SUIVEUR"
                elif abs(s["stop"]) < 1e-9:
                    issue = "POINT MORT"
                elif s["stop"] <= -s["sl0"] + 1e-9:
                    issue = "SL DEPART"
                else:
                    issue = "PROTECTION"
                s["fini"] = (s["stop"] - cout_eur, issue, j - i)
                continue
            if haut >= s["tp"] - 1e-12:
                s["fini"] = (s["tp"] - cout_eur, "OBJECTIF", j - i)
                continue
            if ferm > 0:
                s["pos"] += 1
                s["neg"] = 0
            elif ferm < 0:
                s["neg"] += 1
            # --- cote gain ---
            if s["prod"]:
                cible, seuil = palier_prod(ferm)
                if (cible is not None and cible > s["stop"]
                        and cible < ferm - 1e-12):
                    s["stop"] = cible
                    if seuil is not None:
                        s["tp"] = max(s["tp"], seuil + 2.0)
            else:
                w = trainage(s["mt"], s["pos"])
                if ferm >= DECLENCHE - 1e-9:
                    cible = ferm - w
                    if cible > s["stop"] and cible < ferm - 1e-12:
                        s["stop"] = cible
                if s["mo"] == "aucun":
                    s["tp"] = INFINI
                else:
                    # l'objectif ne fait que s'eloigner, jamais revenir
                    s["tp"] = max(s["tp"], objectif(s["mo"], s["pos"]))
            # --- cote perte : point milieu, plancher -2 EUR (ou perte+2 pour A2)
            perte = -ferm
            if (j - i) >= PROT_AGE_MIN and perte > 0 and s["neg"] >= PROT_NEG_MIN:
                distance = -s["stop"]
                plancher = (perte + 2.0 if s["prod"]
                            else max(2.0, perte + MARGE_FRANCHIE))
                if distance > plancher:
                    vise = max((distance + perte) / 2.0, plancher)
                    if vise < distance:
                        s["stop"] = -vise
        if not reste:
            break
    for nom, s in etats.items():
        if s["fini"] is None:
            d = (cl[fin - 1] - e) * k if achat else (e - cl[fin - 1]) * k
            s["fini"] = (d - cout_eur, "TEMPS", fin - 1 - i)
    return {n: s["fini"] for n, s in etats.items()}


def main():
    ts, hi, lo, cl, sp = charger()
    entrees = list(range(0, len(ts) - 2, PAS_ENTREE))
    milieu = ts[len(ts) // 2]
    print("%d bougies M1   %s -> %s" % (len(ts), ts[0], ts[-1]))
    print("entrees : %d toutes les %d min, deux sens  ⇒  %d trades"
          % (len(entrees), PAS_ENTREE, 2 * len(entrees)))

    par_jour = {n[0]: collections.defaultdict(list) for n in STRATEGIES}
    tous = {n[0]: [] for n in STRATEGIES}
    issues = {n[0]: collections.Counter() for n in STRATEGIES}
    durees = {n[0]: [] for n in STRATEGIES}
    moities = {n[0]: ([], []) for n in STRATEGIES}
    for idx, i in enumerate(entrees):
        cout = sp[i] * POINT_USD / EUR_USD
        for achat in (True, False):
            for nom, (pnl, issue, duree) in parcourir(
                    hi, lo, cl, i, achat, cout).items():
                par_jour[nom][ts[i].date()].append(pnl)
                tous[nom].append(pnl)
                issues[nom][issue] += 1
                durees[nom].append(duree)
                moities[nom][0 if ts[i] < milieu else 1].append(pnl)
        if (idx + 1) % 1000 == 0:
            print("   %d/%d..." % (idx + 1, len(entrees)), flush=True)

    print("\n%-20s%10s%10s%11s%9s%8s%10s%10s"
          % ("strategie", "EUR/tr", "sd", "pire jour", "reussite", "duree",
             "gain moy", "max"))
    res = {}
    for (nom, *_r) in STRATEGIES:
        v = tous[nom]
        g = [x for x in v if x > 0]
        jours = {d: st.fmean(x) for d, x in par_jour[nom].items()}
        res[nom] = {"jours": jours, "m1": st.fmean(moities[nom][0]),
                    "m2": st.fmean(moities[nom][1])}
        print("%-20s%+10.4f%10.4f%+11.4f%8.2f%%%8.1f%+10.3f%+10.2f"
              % (nom, st.fmean(v), st.stdev(v), min(jours.values()),
                 100 * len(g) / len(v), st.fmean(durees[nom]),
                 st.fmean(g) if g else 0.0, max(v)))
        print("%-20s   issues : %s" % ("", dict(issues[nom])))

    print("\n=== CHAQUE VARIANTE CONTRE Z0 (critere : |t| > 2,5) ===")
    base = "Z0 reference"
    print("%-20s%12s%9s%12s%12s%9s"
          % ("variante", "ecart/jour", "t", "1re moitie", "2e moitie", "signe"))
    for (nom, *_r) in STRATEGIES:
        if nom == base:
            continue
        ja, jb = res[nom]["jours"], res[base]["jours"]
        communs = sorted(set(ja) & set(jb))
        ec = [ja[d] - jb[d] for d in communs]
        m = st.fmean(ec)
        s = st.stdev(ec) if len(ec) > 2 else 0.0
        t = m / (s / math.sqrt(len(ec))) if s else 0.0
        d1 = res[nom]["m1"] - res[base]["m1"]
        d2 = res[nom]["m2"] - res[base]["m2"]
        print("%-20s%+12.4f%+9.2f%+12.4f%+12.4f%9s %s"
              % (nom, m, t, d1, d2,
                 "stable" if (d1 > 0) == (d2 > 0) else "INVERSE",
                 "***" if abs(t) > 2.5 else ""))
    print("\n*** = |t| > 2,5, le critere pre-inscrit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
