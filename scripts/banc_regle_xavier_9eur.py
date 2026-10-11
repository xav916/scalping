#!/usr/bin/env python3
"""La regle de Xavier : depart -9 EUR, plancher -2 EUR, echelle qui traine 0,50.

Pre-inscrit dans docs/predictions/2026-10-11_regle_de_xavier_neuf_euros.md
AVANT d'ecrire ce fichier.

Six strategies avancent EN PARALLELE sur un seul parcours par trade.
Palier arme sur la CLOTURE (version defendable du verdict precedent) ; une
bougie qui contient le stop ET l'objectif compte comme un STOP.
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
MARGE_FRANCHIE = 0.10      # un stop ne se pose jamais du mauvais cote du cours

ECH_XAVIER = ((0.5, 0.0), (1.0, 0.5), (1.5, 1.0), (2.0, 1.5))
ECH_PROD = ((1.0, 0.75), (1.5, 1.25), (1.75, 1.5), (2.0, 1.75))

# nom, sl_depart, tp_depart, echelle, tp_mobile, protection:
#   None = pas de protection ; ("plancher_fixe", v) ; ("marge", v)
STRATEGIES = (
    ("X  sa regle",      9.0, 2.0, ECH_XAVIER, False, ("plancher_fixe", 2.0)),
    ("X+ TP mobile",     9.0, 2.0, ECH_XAVIER, True,  ("plancher_fixe", 2.0)),
    ("A1 production",   20.0, 2.0, ECH_PROD,   True,  None),
    ("A2 prod+protec",  20.0, 2.0, ECH_PROD,   True,  ("marge", 2.0)),
    ("B2 stop -2",       2.0, 2.0, None,       False, None),
    ("T  temoin",       20.0, 2.0, None,       False, None),
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
    return cible, seuil


def parcourir(hi, lo, cl, i, achat, cout_eur):
    e = cl[i]
    k = 1.0 / EUR_USD
    etats = {}
    for (nom, sl, tp, ech, tpm, prot) in STRATEGIES:
        etats[nom] = {"stop": -sl, "tp": tp, "ech": ech, "tpm": tpm,
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
                    issue = "ECHELLE"
                elif abs(s["stop"]) < 1e-9:
                    issue = "POINT MORT"
                elif s["stop"] <= -s["sl0"] + 1e-9:
                    issue = "SL DEPART"
                else:
                    issue = "PROTECTION"
                s["fini"] = (s["stop"] - cout_eur, issue, j - i)
                continue
            if haut >= s["tp"] - 1e-12:
                s["fini"] = (s["tp"] - cout_eur, "TP", j - i)
                continue
            # --- echelle de gains, sur la CLOTURE et jamais au-dessus du cours
            if s["ech"] is not None:
                cible, seuil = palier(s["ech"], ferm)
                if (cible is not None and cible > s["stop"]
                        and cible < ferm - 1e-12):
                    s["stop"] = cible
                    if s["tpm"] and seuil is not None:
                        s["tp"] = max(s["tp"], seuil + 2.0)
            # --- protection des pertes, point milieu
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
                if genre == "plancher_fixe":
                    # 🔑 la regle de Xavier : on ne resserre jamais sous -2 EUR,
                    # et jamais du mauvais cote du cours non plus.
                    plancher = max(v, perte + MARGE_FRANCHIE)
                else:
                    plancher = perte + v
                if distance > plancher:
                    vise = (distance + perte) / 2.0
                    if vise < plancher:
                        vise = plancher
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
    print("echelle de Xavier : %s   echelle de production : %s"
          % (ECH_XAVIER, ECH_PROD))

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

    print("\n%-17s%11s%11s%12s%10s%11s"
          % ("strategie", "EUR/trade", "ecart-type", "pire jour", "reussite",
             "duree min"))
    res = {}
    for (nom, *_r) in STRATEGIES:
        v = tous[nom]
        jours = {d: st.fmean(x) for d, x in par_jour[nom].items()}
        res[nom] = {"jours": jours, "m1": st.fmean(moities[nom][0]),
                    "m2": st.fmean(moities[nom][1]), "moy": st.fmean(v)}
        print("%-17s%+11.4f%11.4f%+12.4f%9.2f%%%11.1f"
              % (nom, st.fmean(v), st.stdev(v), min(jours.values()),
                 100 * sum(1 for x in v if x > 0) / len(v),
                 st.fmean(durees[nom])))
        print("%-17s   issues : %s" % ("", dict(issues[nom])))

    print("\n=== SA REGLE CONTRE CHAQUE AUTRE (critere : |t| > 2,5) ===")
    base = "X  sa regle"
    print("%-17s%12s%9s%12s%12s%9s"
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
        print("%-17s%+12.4f%+9.2f%+12.4f%+12.4f%9s %s"
              % (nom, m, t, d1, d2,
                 "stable" if (d1 > 0) == (d2 > 0) else "INVERSE",
                 "***" if abs(t) > 2.5 else ""))
    print("\n*** = |t| > 2,5, le critere pre-inscrit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
