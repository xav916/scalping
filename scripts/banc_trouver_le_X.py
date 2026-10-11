#!/usr/bin/env python3
"""Trouver le X : oscillation dans une bande de 2 EUR, stop a 2 EUR du cours,
objectif a +X.

Pre-inscrit dans docs/predictions/2026-10-11_trouver_le_X.md AVANT d'ecrire ce
fichier. Demande de Xavier : << trouve-moi le X >>.

Condition : plage des 10 dernieres clotures <= 2,00 EUR.
Quand elle se declenche : stop -> cours - 2,00 (cliquet seul, jamais du mauvais
cote du cours) et objectif -> cours + X.
Hors condition : depart -9 EUR, point milieu cote perte, plancher -2 EUR.

⛔ 11 valeurs de X balayees : choisir le maximum d'un balayage est la facon
standard de fabriquer un faux positif, d'ou la barre relevee a |t| > 3,0.
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
FENETRE = 10
BANDE = 2.00               # sa bande d'oscillation
STOP_OSC = 2.00            # son stop a 2 EUR du cours
PLAFOND_T = 3.0            # barre relevee : 11 valeurs de X

XS = (1.0, 2.0, 3.0, 5.0, 7.0, 9.0, 10.0, 12.0, 15.0, 20.0, None)

# references, les meilleures connues
REFS = (("REF trainage 0,50", 0.00),
        ("REF trainage +0,10/min", 0.10))


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


def nom_x(x):
    return "X = aucun objectif" if x is None else "X = %g EUR" % x


def parcourir(hi, lo, cl, i, achat, cout_eur):
    e = cl[i]
    k = 1.0 / EUR_USD
    etats = {}
    for x in XS:
        etats[nom_x(x)] = {"stop": -9.0, "tp": 2.0, "genre": "osc", "x": x,
                           "neg": 0, "fini": None, "morsures": 0}
    for nom, pente in REFS:
        etats[nom] = {"stop": -9.0, "tp": INFINI, "genre": "ref",
                      "pente": pente, "neg": 0, "pos": 0, "fini": None,
                      "morsures": 0}
    fin = min(len(hi), i + 1 + CAP)
    fen = collections.deque(maxlen=FENETRE)
    for j in range(i + 1, fin):
        if achat:
            bas, haut, ferm = ((lo[j] - e) * k, (hi[j] - e) * k, (cl[j] - e) * k)
        else:
            bas, haut, ferm = ((e - hi[j]) * k, (e - lo[j]) * k, (e - cl[j]) * k)
        fen.append(ferm)
        plage = (max(fen) - min(fen)) if len(fen) == FENETRE else None
        oscille = plage is not None and plage <= BANDE
        reste = False
        for nom, s in etats.items():
            if s["fini"] is not None:
                continue
            reste = True
            if bas <= s["stop"] + 1e-12:
                issue = ("SUIVEUR" if s["stop"] > 1e-9 else
                         "POINT MORT" if abs(s["stop"]) < 1e-9 else
                         "SL DEPART" if s["stop"] <= -9.0 + 1e-9 else
                         "PROTECTION")
                s["fini"] = (s["stop"] - cout_eur, issue, j - i)
                continue
            if haut >= s["tp"] - 1e-12:
                s["fini"] = (s["tp"] - cout_eur, "OBJECTIF", j - i)
                continue
            if ferm < 0:
                s["neg"] += 1
            else:
                s["neg"] = 0
            if s["genre"] == "osc":
                # 🔑 SA REGLE : quand ca oscille, stop a 2 EUR du cours et
                # objectif a +X. Cliquet : on ne desserre jamais.
                if oscille:
                    cible = ferm - STOP_OSC
                    if cible > s["stop"] and cible < ferm - 1e-12:
                        s["stop"] = cible
                        s["morsures"] += 1
                    if s["x"] is None:
                        s["tp"] = INFINI
                    else:
                        s["tp"] = max(s["tp"], ferm + s["x"])
            else:
                if ferm > 0:
                    s["pos"] += 1
                w = min(0.5 + s["pente"] * s["pos"], 2.0) if s["pente"] > 0 \
                    else 0.5
                if ferm >= 0.5 - 1e-9:
                    cible = ferm - w
                    if cible > s["stop"] and cible < ferm - 1e-12:
                        s["stop"] = cible
            perte = -ferm
            if (j - i) >= PROT_AGE_MIN and perte > 0 and s["neg"] >= PROT_NEG_MIN:
                distance = -s["stop"]
                plancher = max(2.0, perte + MARGE_FRANCHIE)
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
    return {n: (s["fini"], s["morsures"]) for n, s in etats.items()}


def main():
    ts, hi, lo, cl, sp = charger()
    entrees = list(range(0, len(ts) - 2, PAS_ENTREE))
    milieu = ts[len(ts) // 2]
    noms = [nom_x(x) for x in XS] + [n for n, _p in REFS]
    print("%d bougies M1   %s -> %s" % (len(ts), ts[0], ts[-1]))
    print("entrees : %d toutes les %d min, deux sens  ⇒  %d trades"
          % (len(entrees), PAS_ENTREE, 2 * len(entrees)))
    print("oscillation : plage des %d dernieres clotures <= %.2f EUR ; "
          "stop a %.2f EUR du cours" % (FENETRE, BANDE, STOP_OSC))

    par_jour = {n: collections.defaultdict(list) for n in noms}
    tous = {n: [] for n in noms}
    issues = {n: collections.Counter() for n in noms}
    morsures = {n: 0 for n in noms}
    moities = {n: ([], []) for n in noms}
    for idx, i in enumerate(entrees):
        cout = sp[i] * POINT_USD / EUR_USD
        for achat in (True, False):
            for nom, ((pnl, issue, duree), ns) in parcourir(
                    hi, lo, cl, i, achat, cout).items():
                par_jour[nom][ts[i].date()].append(pnl)
                tous[nom].append(pnl)
                issues[nom][issue] += 1
                morsures[nom] += ns
                moities[nom][0 if ts[i] < milieu else 1].append(pnl)
        if (idx + 1) % 1000 == 0:
            print("   %d/%d..." % (idx + 1, len(entrees)), flush=True)

    print("\n%-24s%11s%10s%11s%9s%10s%12s"
          % ("variante", "EUR/trade", "sd", "pire jour", "reussite", "max",
             "resserrages"))
    res = {}
    for nom in noms:
        v = tous[nom]
        jours = {d: st.fmean(x) for d, x in par_jour[nom].items()}
        res[nom] = {"jours": jours, "moy": st.fmean(v),
                    "m1": st.fmean(moities[nom][0]),
                    "m2": st.fmean(moities[nom][1])}
        print("%-24s%+11.4f%10.4f%+11.4f%8.2f%%%+10.2f%12d"
              % (nom, st.fmean(v), st.stdev(v), min(jours.values()),
                 100 * sum(1 for x in v if x > 0) / len(v), max(v),
                 morsures[nom]))

    meilleure_ref = max((n for n, _p in REFS), key=lambda n: res[n]["moy"])
    print("\nmeilleure reference : %s (%+.4f EUR/trade)"
          % (meilleure_ref, res[meilleure_ref]["moy"]))

    print("\n=== CHAQUE X CONTRE LA MEILLEURE REFERENCE (|t| > %.1f) ==="
          % PLAFOND_T)
    print("%-24s%12s%9s%12s%12s%9s"
          % ("variante", "ecart/jour", "t", "1re moitie", "2e moitie", "signe"))
    retenus = []
    for x in XS:
        nom = nom_x(x)
        ja, jb = res[nom]["jours"], res[meilleure_ref]["jours"]
        communs = sorted(set(ja) & set(jb))
        ec = [ja[d] - jb[d] for d in communs]
        m = st.fmean(ec)
        s = st.stdev(ec) if len(ec) > 2 else 0.0
        t = m / (s / math.sqrt(len(ec))) if s else 0.0
        d1 = res[nom]["m1"] - res[meilleure_ref]["m1"]
        d2 = res[nom]["m2"] - res[meilleure_ref]["m2"]
        ok = m > 0 and abs(t) > PLAFOND_T and (d1 > 0) == (d2 > 0)
        print("%-24s%+12.4f%+9.2f%+12.4f%+12.4f%9s %s"
              % (nom, m, t, d1, d2,
                 "stable" if (d1 > 0) == (d2 > 0) else "INVERSE",
                 "***" if ok else ""))
        if ok:
            retenus.append(nom)
    meilleur_x = max(XS, key=lambda x: res[nom_x(x)]["moy"])
    print("\nLE MEILLEUR X du balayage : %s (%+.4f EUR/trade)"
          % (nom_x(meilleur_x), res[nom_x(meilleur_x)]["moy"]))
    print("X qui franchissent la barre de %.1f : %d / %d"
          % (PLAFOND_T, len(retenus), len(XS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
