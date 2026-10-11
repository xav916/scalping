#!/usr/bin/env python3
"""L'objectif qui FUIT : TP = 2 x profit + 1, contre un objectif atteignable.

Pre-inscrit dans docs/predictions/2026-10-11_objectif_qui_fuit.md AVANT
d'ecrire ce fichier.

Six strategies en parallele sur un seul parcours par trade. Palier arme sur la
CLOTURE ; une bougie qui contient le stop ET l'objectif compte comme un STOP.
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

# L'echelle de Xavier, prolongee : SL = profit - 0,50, par pas de 0,50.
ECH_XAVIER = tuple((round(0.5 * n, 2), round(0.5 * n - 0.5, 2))
                   for n in range(1, 201))
ECH_PROD = ((1.0, 0.75), (1.5, 1.25), (1.75, 1.5), (2.0, 1.75))

# nom, sl_depart, echelle, mode_tp, protection
#   mode_tp : ("fuyant",) = 2*p+1 ; ("atteignable",) = p+1 ;
#             ("palier",) = palier + 2 ; ("aucun",) ; ("fixe", v)
STRATEGIES = (
    ("Y  objectif fuyant", 9.0, ECH_XAVIER, ("fuyant",), ("fixe_plancher", 2.0)),
    ("Y0 sans objectif",   9.0, ECH_XAVIER, ("aucun",),  ("fixe_plancher", 2.0)),
    ("Y2 objectif p+1",    9.0, ECH_XAVIER, ("atteignable",), ("fixe_plancher", 2.0)),
    ("X+ palier + 2",      9.0, ECH_XAVIER, ("palier",), ("fixe_plancher", 2.0)),
    ("A2 prod+protection", 20.0, ECH_PROD,  ("palier",), ("marge", 2.0)),
    ("B2 stop -2 sec",     2.0, None,       ("fixe", 2.0), None),
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


def palier(echelle, profit):
    cible = seuil = None
    for s, c in echelle:
        if profit >= s - 1e-9:
            cible, seuil = c, s
        else:
            break
    return cible, seuil


def tp_vise(mode, seuil, profit, actuel):
    genre = mode[0]
    if genre == "aucun":
        return INFINI
    if genre == "fixe":
        return mode[1]
    if seuil is None:
        return actuel
    if genre == "fuyant":
        # 🔑 la regle de Xavier : 1 EUR -> 3, 1,5 -> 4, 2 -> 5, soit 2p + 1.
        # Elle ne s'applique qu'a partir de 1 EUR de profit.
        return max(actuel, 2.0 * seuil + 1.0) if seuil >= 1.0 else actuel
    if genre == "atteignable":
        return max(actuel, seuil + 1.0) if seuil >= 1.0 else actuel
    if genre == "palier":
        return max(actuel, seuil + 2.0)
    return actuel


def parcourir(hi, lo, cl, i, achat, cout_eur):
    e = cl[i]
    k = 1.0 / EUR_USD
    etats = {}
    for (nom, sl, ech, mode, prot) in STRATEGIES:
        etats[nom] = {"stop": -sl, "tp": 2.0, "ech": ech, "mode": mode,
                      "prot": prot, "neg": 0, "fini": None, "sl0": sl}
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
            if s["ech"] is not None:
                cible, seuil = palier(s["ech"], ferm)
                if (cible is not None and cible > s["stop"]
                        and cible < ferm - 1e-12):
                    s["stop"] = cible
                    s["tp"] = tp_vise(s["mode"], seuil, ferm, s["tp"])
            if s["prot"] is None:
                continue
            if ferm < 0:
                s["neg"] += 1
            else:
                s["neg"] = 0
            perte = -ferm
            if (j - i) >= PROT_AGE_MIN and perte > 0 and s["neg"] >= PROT_NEG_MIN:
                distance = -s["stop"]
                genre, v = s["prot"]
                plancher = (max(v, perte + MARGE_FRANCHIE)
                            if genre == "fixe_plancher" else perte + v)
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
    print("echelle de Xavier prolongee : SL = profit - 0,50, pas de 0,50")

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

    print("\n%-20s%10s%10s%11s%9s%9s%10s%10s"
          % ("strategie", "EUR/tr", "sd", "pire jour", "reussite", "duree",
             "gain moy", "max"))
    res = {}
    for (nom, *_r) in STRATEGIES:
        v = tous[nom]
        gagnants = [x for x in v if x > 0]
        jours = {d: st.fmean(x) for d, x in par_jour[nom].items()}
        res[nom] = {"jours": jours, "m1": st.fmean(moities[nom][0]),
                    "m2": st.fmean(moities[nom][1])}
        print("%-20s%+10.4f%10.4f%+11.4f%8.2f%%%9.1f%+10.3f%+10.2f"
              % (nom, st.fmean(v), st.stdev(v), min(jours.values()),
                 100 * len(gagnants) / len(v), st.fmean(durees[nom]),
                 st.fmean(gagnants) if gagnants else 0.0, max(v)))
        print("%-20s   issues : %s" % ("", dict(issues[nom])))

    print("\n=== SA NOUVELLE REGLE CONTRE CHAQUE AUTRE (|t| > 2,5) ===")
    base = "Y  objectif fuyant"
    print("%-20s%12s%9s%12s%12s%9s"
          % ("contre", "ecart/jour", "t", "1re moitie", "2e moitie", "signe"))
    for (nom, *_r) in STRATEGIES:
        if nom == base:
            continue
        ja, jb = res[base]["jours"], res[nom]["jours"]
        communs = sorted(set(ja) & set(jb))
        ec = [ja[d] - jb[d] for d in communs]
        m = st.fmean(ec)
        s = st.stdev(ec) if len(ec) > 2 else 0.0
        t = m / (s / math.sqrt(len(ec))) if s else 0.0
        d1 = res[base]["m1"] - res[nom]["m1"]
        d2 = res[base]["m2"] - res[nom]["m2"]
        print("%-20s%+12.4f%+9.2f%+12.4f%+12.4f%9s %s"
              % (nom, m, t, d1, d2,
                 "stable" if (d1 > 0) == (d2 > 0) else "INVERSE",
                 "***" if abs(t) > 2.5 else ""))
    print("\n*** = |t| > 2,5, le critere pre-inscrit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
