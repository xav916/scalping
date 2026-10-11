#!/usr/bin/env python3
"""A quelle cadence resserrer le stop d'un trade NEGATIF ?

Question de Xavier le 2026-10-11 : « est-ce que sonder au bout de 5 minutes
est un point negatif ? Voir si le trade est negatif au bout de 30 secondes et
resserrer le stop a cet effet. Lancez l'algo toutes les 20 secondes. »

🔑 CE QUI SE JOUE N'EST PAS LA REACTIVITE, C'EST LA VITESSE DE CONVERGENCE.
Le point milieu `(stop + perte) / 2` divise l'ecart par deux A CHAQUE PASSAGE.
Depuis 13 EUR avec 3 EUR de perte : 8 -> 5,5 -> 4,25 -> 3,6 -> ... En 5 passages
on est au plancher. A 5 minutes cela prend 25 minutes ; a 20 secondes, 100
SECONDES. La regle n'est donc pas la meme regle.

⚠️ LIMITE DECLAREE : les bougies sont du M1. **Une cadence de 20 secondes n'est
pas simulable** — le plus fin que cette donnee permette est la MINUTE. On
encadre donc : si la minute fait deja pire que les 5 minutes, les 20 secondes
feront pire encore.
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
INFINI = 1e9
DECLENCHE = 0.5
TRAINAGE = 0.5
SL_DEPART = 13.0          # la vraie production : 0,35 % du prix
PLANCHER = 2.0
MARGE_FRANCHIE = 0.10

# nom, age mini (min), negativite mini (min), cadence (min), protection active
STRATEGIES = (
    ("P5 production  5 min", 5.0, 2.5, 5, True),
    ("P1 sa demande  1 min", 1.0, 0.5, 1, True),
    ("P2 intermediaire 2min", 2.0, 1.0, 2, True),
    ("P0 aucune protection", 0.0, 0.0, 1, False),
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


def parcourir(hi, lo, cl, i, achat, cout_eur):
    e = cl[i]
    k = 1.0 / EUR_USD
    etats = {}
    for (nom, age, neg, cad, act) in STRATEGIES:
        etats[nom] = {"stop": -SL_DEPART, "age": age, "neg_mini": neg,
                      "cad": cad, "act": act, "neg": 0, "fini": None,
                      "serrages": 0}
    fin = min(len(hi), i + 1 + CAP)
    for j in range(i + 1, fin):
        if achat:
            bas, haut, ferm = ((lo[j] - e) * k, (hi[j] - e) * k, (cl[j] - e) * k)
        else:
            bas, haut, ferm = ((e - hi[j]) * k, (e - lo[j]) * k, (e - cl[j]) * k)
        age_min = j - i
        reste = False
        for nom, s in etats.items():
            if s["fini"] is not None:
                continue
            reste = True
            if bas <= s["stop"] + 1e-12:
                issue = ("SUIVEUR" if s["stop"] > 1e-9 else
                         "POINT MORT" if abs(s["stop"]) < 1e-9 else
                         "SL DEPART" if s["stop"] <= -SL_DEPART + 1e-9 else
                         "PROTECTION")
                s["fini"] = (s["stop"] - cout_eur, issue, age_min)
                continue
            # cote gain : trainage continu, aucun objectif
            if ferm >= DECLENCHE - 1e-9:
                cible = ferm - TRAINAGE
                if cible > s["stop"] and cible < ferm - 1e-12:
                    s["stop"] = cible
            if ferm < 0:
                s["neg"] += 1
            else:
                s["neg"] = 0
            if not s["act"]:
                continue
            # 🔑 LA CADENCE : la protection ne passe qu'un tour sur `cad`
            if age_min % s["cad"] != 0:
                continue
            perte = -ferm
            if (age_min >= s["age"] and perte > 0
                    and s["neg"] >= s["neg_mini"]):
                distance = -s["stop"]
                plancher = max(PLANCHER, perte + MARGE_FRANCHIE)
                if distance > plancher:
                    vise = max((distance + perte) / 2.0, plancher)
                    if vise < distance:
                        s["stop"] = -vise
                        s["serrages"] += 1
        if not reste:
            break
    for nom, s in etats.items():
        if s["fini"] is None:
            d = (cl[fin - 1] - e) * k if achat else (e - cl[fin - 1]) * k
            s["fini"] = (d - cout_eur, "TEMPS", fin - 1 - i)
    return {n: (s["fini"], s["serrages"]) for n, s in etats.items()}


def main():
    ts, hi, lo, cl, sp = charger()
    entrees = list(range(0, len(ts) - 2, PAS_ENTREE))
    milieu = ts[len(ts) // 2]
    noms = [n[0] for n in STRATEGIES]
    print("%d bougies M1   %s -> %s" % (len(ts), ts[0], ts[-1]))
    print("entrees : %d toutes les %d min, deux sens  ⇒  %d trades"
          % (len(entrees), PAS_ENTREE, 2 * len(entrees)))
    print("depart %.0f EUR (la vraie production, 0,35 %%), trainage %.2f, "
          "aucun objectif, plancher %.0f EUR" % (SL_DEPART, TRAINAGE, PLANCHER))

    par_jour = {n: collections.defaultdict(list) for n in noms}
    tous = {n: [] for n in noms}
    issues = {n: collections.Counter() for n in noms}
    serrages = {n: 0 for n in noms}
    moities = {n: ([], []) for n in noms}
    for idx, i in enumerate(entrees):
        cout = sp[i] * POINT_USD / EUR_USD
        for achat in (True, False):
            for nom, ((pnl, issue, duree), ns) in parcourir(
                    hi, lo, cl, i, achat, cout).items():
                par_jour[nom][ts[i].date()].append(pnl)
                tous[nom].append(pnl)
                issues[nom][issue] += 1
                serrages[nom] += ns
                moities[nom][0 if ts[i] < milieu else 1].append(pnl)
        if (idx + 1) % 1000 == 0:
            print("   %d/%d..." % (idx + 1, len(entrees)), flush=True)

    print("\n%-24s%11s%10s%11s%9s%12s%11s"
          % ("cadence", "EUR/trade", "sd", "pire jour", "reussite",
             "resserrages", "max"))
    res = {}
    for nom in noms:
        v = tous[nom]
        jours = {d: st.fmean(x) for d, x in par_jour[nom].items()}
        res[nom] = {"jours": jours, "m1": st.fmean(moities[nom][0]),
                    "m2": st.fmean(moities[nom][1])}
        print("%-24s%+11.4f%10.4f%+11.4f%8.2f%%%12d%+11.2f"
              % (nom, st.fmean(v), st.stdev(v), min(jours.values()),
                 100 * sum(1 for x in v if x > 0) / len(v), serrages[nom],
                 max(v)))
        print("%-24s   issues : %s" % ("", dict(issues[nom])))

    base = "P5 production  5 min"
    print("\n=== CHAQUE CADENCE CONTRE LA PRODUCTION (|t| > 2,5) ===")
    print("%-24s%12s%9s%12s%12s%9s"
          % ("cadence", "ecart/jour", "t", "1re moitie", "2e moitie", "signe"))
    for nom in noms:
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
        print("%-24s%+12.4f%+9.2f%+12.4f%+12.4f%9s %s"
              % (nom, m, t, d1, d2,
                 "stable" if (d1 > 0) == (d2 > 0) else "INVERSE",
                 "***" if abs(t) > 2.5 else ""))
    print("\n*** = |t| > 2,5")
    print("\n⚠️ Une cadence de 20 s n'est PAS simulable sur du M1 : elle serait")
    print("   PLUS agressive encore que la ligne << 1 min >>.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
