#!/usr/bin/env python3
"""Elargir le trainage quand le cours STAGNE en positif.

Pre-inscrit dans docs/predictions/2026-10-11_stagnation_en_positif.md AVANT
d'ecrire ce fichier.

Stagnation, definie d'avance : sur les 10 dernieres clotures, l'ecart entre la
plus haute et la plus basse vaut 0,50 EUR ou moins, ET le trade est en positif.
Le compteur est le nombre de minutes CONSECUTIVES ou c'est vrai.

🔑 S4 est le temoin qui decide : il elargit sous VOLATILITE au lieu de
stagnation. S'il marche aussi bien, c'est l'elargissement qui compte, pas la
condition.
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
DECLENCHE = 0.5
FENETRE = 10               # minutes regardees pour juger la stagnation
# ⛔ MES PREMIERS SEUILS NE SE DECLENCHAIENT JAMAIS. A 0,50 EUR, seules
# **0,021 %** des fenetres de 10 min qualifiaient : S1 et S2 rendaient un
# resultat IDENTIQUE a S0 au centieme pres, ce qui a trahi le defaut.
# Mesure de la distribution, 14 285 fenetres de 10 min sur le magasin M1 :
#     centile 10 : 1,741 EUR    centile 20 : 2,268    MEDIANE : 3,688
#     centile 75 : 5,447        centile 90 : 7,823
# Les seuils sont donc pris DANS LA DISTRIBUTION, pas choisis a la main, et
# surtout pas regles sur le resultat : stagnation = 1er quintile (20 %),
# volatilite = dernier quartile (75 %).
SEUIL_STAGNE = float(os.getenv("SEUIL_STAGNE", "2.268"))
SEUIL_VOLATIL = float(os.getenv("SEUIL_VOLATIL", "5.447"))

# nom, condition, pente, plafond, objectif
STRATEGIES = (
    ("S0 reference",      None,        0.00, 0.5, "aucun"),
    ("S1 stagnation",     "stagne",    0.10, 2.0, "aucun"),
    ("S2 stagnation x2",  "stagne",    0.20, 4.0, "aucun"),
    ("S3 objectif stagne", "stagne",   0.00, 0.5, "temps_stagne"),
    ("S4 temoin volatil", "volatil",   0.10, 2.0, "aucun"),
    ("Z2 temps positif",  "positif",   0.10, 2.0, "aucun"),
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
    for (nom, cond, pente, plafond, obj) in STRATEGIES:
        etats[nom] = {"stop": -9.0, "tp": 2.0, "cond": cond, "pente": pente,
                      "plafond": plafond, "obj": obj, "neg": 0, "cpt": 0,
                      "fini": None}
    fin = min(len(hi), i + 1 + CAP)
    fenetre = collections.deque(maxlen=FENETRE)
    for j in range(i + 1, fin):
        if achat:
            bas, haut, ferm = ((lo[j] - e) * k, (hi[j] - e) * k, (cl[j] - e) * k)
        else:
            bas, haut, ferm = ((e - hi[j]) * k, (e - lo[j]) * k, (e - cl[j]) * k)
        fenetre.append(ferm)
        plage = (max(fenetre) - min(fenetre)) if len(fenetre) == FENETRE else None
        stagne = plage is not None and plage <= SEUIL_STAGNE and ferm > 0
        volatil = plage is not None and plage > SEUIL_VOLATIL and ferm > 0
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
                elif s["stop"] <= -9.0 + 1e-9:
                    issue = "SL DEPART"
                else:
                    issue = "PROTECTION"
                s["fini"] = (s["stop"] - cout_eur, issue, j - i)
                continue
            if haut >= s["tp"] - 1e-12:
                s["fini"] = (s["tp"] - cout_eur, "OBJECTIF", j - i)
                continue
            if ferm < 0:
                s["neg"] += 1
            else:
                s["neg"] = 0
            # --- le compteur de la condition ---
            if s["cond"] == "stagne":
                s["cpt"] = s["cpt"] + 1 if stagne else 0
            elif s["cond"] == "volatil":
                s["cpt"] = s["cpt"] + 1 if volatil else 0
            elif s["cond"] == "positif":
                s["cpt"] = s["cpt"] + 1 if ferm > 0 else s["cpt"]
            # --- cote gain : trainage continu, elargi par la condition ---
            w = min(0.5 + s["pente"] * s["cpt"], s["plafond"]) \
                if s["pente"] > 0 else 0.5
            if ferm >= DECLENCHE - 1e-9:
                cible = ferm - w
                if cible > s["stop"] and cible < ferm - 1e-12:
                    s["stop"] = cible
            if s["obj"] == "aucun":
                s["tp"] = INFINI
            else:
                # 🔑 sa demande litterale, version stagnation
                s["tp"] = max(s["tp"], 2.0 + 1.0 * s["cpt"])
            # --- cote perte : inchange ---
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
    return {n: s["fini"] for n, s in etats.items()}


def main():
    ts, hi, lo, cl, sp = charger()
    entrees = list(range(0, len(ts) - 2, PAS_ENTREE))
    milieu = ts[len(ts) // 2]
    print("%d bougies M1   %s -> %s" % (len(ts), ts[0], ts[-1]))
    print("entrees : %d toutes les %d min, deux sens  ⇒  %d trades"
          % (len(entrees), PAS_ENTREE, 2 * len(entrees)))
    print("stagnation : plage des %d dernieres clotures <= %.2f EUR, en positif"
          % (FENETRE, SEUIL_STAGNE))

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

    def comparer(a, b):
        ja, jb = res[a]["jours"], res[b]["jours"]
        communs = sorted(set(ja) & set(jb))
        ec = [ja[d] - jb[d] for d in communs]
        m = st.fmean(ec)
        s = st.stdev(ec) if len(ec) > 2 else 0.0
        t = m / (s / math.sqrt(len(ec))) if s else 0.0
        d1 = res[a]["m1"] - res[b]["m1"]
        d2 = res[a]["m2"] - res[b]["m2"]
        return m, t, d1, d2

    for base in ("S0 reference", "Z2 temps positif"):
        print("\n=== CHAQUE VARIANTE CONTRE %s (|t| > 2,5) ===" % base)
        print("%-20s%12s%9s%12s%12s%9s"
              % ("variante", "ecart/jour", "t", "1re moitie", "2e moitie",
                 "signe"))
        for (nom, *_r) in STRATEGIES:
            if nom == base:
                continue
            m, t, d1, d2 = comparer(nom, base)
            print("%-20s%+12.4f%+9.2f%+12.4f%+12.4f%9s %s"
                  % (nom, m, t, d1, d2,
                     "stable" if (d1 > 0) == (d2 > 0) else "INVERSE",
                     "***" if abs(t) > 2.5 else ""))
    print("\n*** = |t| > 2,5, le critere pre-inscrit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
