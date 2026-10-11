#!/usr/bin/env python3
"""A quelle DISTANCE du cours resserrer le stop ? -- la question de Xavier.

Question du 2026-10-11 : << si on commence a -20 EUR et qu'au bout d'une minute
le cours est a -5, qu'est-ce qui se passe si la regle resserre le stop a -1 ?
Est-ce que le trade est cloture ? Ou peut-on mettre une regle qui met le stop a
l'entier inferieur ? >>

La reponse mecanique est dans le code de production : un stop pose du MAUVAIS
COTE du cours ferme la position, et la production refuse de l'envoyer
(`MARGE_FRANCHIE_EUR = 0.10` dans equiper_trades_main, plancher
`perte + 2 EUR` dans protection_perte_or).

Ce banc chiffre l'autre moitie de la question : **quelle marge choisir**.
Quatre variantes de la protection des pertes, sur les memes trades :

    P2      plancher perte + 2 EUR   (la regle d'aujourd'hui)
    P1      plancher perte + 1 EUR
    PENT    stop a l'ENTIER INFERIEUR : -(floor(perte) + 1)   <- sa proposition
    P05     plancher perte + 0,50 EUR

Toutes partent de SL -20 EUR / TP 2 EUR avec l'echelle de gains armee, le
palier etant arme sur la CLOTURE (la version defendable, cf. le verdict
precedent).
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
PALIERS = ((1.0, 0.75), (1.5, 1.25), (1.75, 1.5), (2.0, 1.75))
TP_ECART = 2.0
PROT_AGE_MIN = 5
PROT_NEG_MIN = 2.5

# nom, marge en EUR ou "entier"
VARIANTES = (("P2  marge 2 EUR", 2.0),
             ("P1  marge 1 EUR", 1.0),
             ("PENT entier inf", "entier"),
             ("P05 marge 0,5", 0.5),
             ("SANS protection", None))


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


def palier_cible(p):
    c = None
    for seuil, cible in PALIERS:
        if p >= seuil - 1e-9:
            c = cible
    return c


def seuil_franchi(p):
    r = None
    for seuil, _c in PALIERS:
        if p >= seuil - 1e-9:
            r = seuil
    return r


def parcourir(hi, lo, cl, i, achat, cout_eur):
    e = cl[i]
    k = 1.0 / EUR_USD
    etats = {nom: {"stop": -20.0, "tp": 2.0, "marge": marge, "neg": 0,
                   "fini": None, "serrages": 0}
             for nom, marge in VARIANTES}
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
                issue = "ECHELLE" if s["stop"] > -1e-9 else (
                    "SL" if s["stop"] <= -20.0 + 1e-9 else "PROTECTION")
                s["fini"] = (s["stop"] - cout_eur, issue, j - i)
                continue
            if haut >= s["tp"] - 1e-12:
                s["fini"] = (s["tp"] - cout_eur, "TP", j - i)
                continue
            cible = palier_cible(ferm)
            if cible is not None and cible > s["stop"] and cible < ferm - 1e-12:
                s["stop"] = cible
                seuil = seuil_franchi(ferm)
                if seuil is not None:
                    s["tp"] = max(s["tp"], seuil + TP_ECART)
            if s["marge"] is None:
                continue
            if ferm < 0:
                s["neg"] += 1
            else:
                s["neg"] = 0
            perte = -ferm
            if (j - i) >= PROT_AGE_MIN and perte > 0 and s["neg"] >= PROT_NEG_MIN:
                distance = -s["stop"]
                if s["marge"] == "entier":
                    # 🔑 la proposition de Xavier : l'entier au-dessous de la
                    # perte courante, donc une marge qui vaut entre 0 et 1 EUR
                    plancher = math.floor(perte) + 1.0
                else:
                    plancher = perte + s["marge"]
                if distance > plancher:
                    vise = (distance + perte) / 2.0
                    if vise < plancher:
                        vise = plancher
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
    print("%d bougies M1   %s -> %s" % (len(ts), ts[0], ts[-1]))
    print("entrees : %d toutes les %d min, deux sens  ⇒  %d trades"
          % (len(entrees), PAS_ENTREE, 2 * len(entrees)))
    print("depart SL -20 EUR / TP 2 EUR, echelle de gains armee sur la CLOTURE")

    par_jour = {n: collections.defaultdict(list) for n, _ in VARIANTES}
    tous = {n: [] for n, _ in VARIANTES}
    issues = {n: collections.Counter() for n, _ in VARIANTES}
    serrages = {n: 0 for n, _ in VARIANTES}
    moities = {n: ([], []) for n, _ in VARIANTES}
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

    print("\n%-18s%11s%11s%12s%10s%12s"
          % ("variante", "EUR/trade", "ecart-type", "pire jour", "reussite",
             "resserrages"))
    res = {}
    for nom, _m in VARIANTES:
        v = tous[nom]
        jours = {d: st.fmean(x) for d, x in par_jour[nom].items()}
        res[nom] = {"jours": jours, "m1": st.fmean(moities[nom][0]),
                    "m2": st.fmean(moities[nom][1])}
        print("%-18s%+11.4f%11.4f%+12.4f%9.2f%%%12d"
              % (nom, st.fmean(v), st.stdev(v), min(jours.values()),
                 100 * sum(1 for x in v if x > 0) / len(v), serrages[nom]))
        print("%-18s   issues : %s" % ("", dict(issues[nom])))

    print("\n=== CHAQUE VARIANTE CONTRE LA REGLE D'AUJOURD'HUI (marge 2 EUR) ===")
    base = "P2  marge 2 EUR"
    print("%-18s%12s%9s%12s%12s%9s"
          % ("variante", "ecart/jour", "t", "1re moitie", "2e moitie", "signe"))
    for nom, _m in VARIANTES:
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
        print("%-18s%+12.4f%+9.2f%+12.4f%+12.4f%9s %s"
              % (nom, m, t, d1, d2,
                 "stable" if (d1 > 0) == (d2 > 0) else "INVERSE",
                 "***" if abs(t) > 2.5 else ""))
    print("\n*** = |t| > 2,5")
    return 0


if __name__ == "__main__":
    sys.exit(main())
