#!/usr/bin/env python3
"""Stop large + echelle, ou stop serre d'office ? -- la question de Xavier.

Pre-inscrit dans docs/predictions/2026-10-11_stop_large_et_echelle_contre_
stop_serre.md (commit e4f62b1) AVANT d'ecrire ce fichier.

Six strategies avancent EN PARALLELE sur un seul parcours par trade, chacune
avec son propre etat. Les regles ne sont pas supposees : l'echelle de gains et
la protection des pertes sont reimplementees d'apres le code de production et
ses variables d'environnement.

CONVENTIONS, declarees :
  - une bougie qui contient le stop ET l'objectif compte comme un STOP ;
  - l'echelle et la protection sont evaluees sur la bougie courante mais leur
    nouveau stop ne s'applique qu'a partir de la SUIVANTE -- sinon un stop
    cree par une bougie pourrait etre touche par cette meme bougie ;
  - 1 lot de 0,01 sur XAU : un dollar de mouvement vaut 1/1,1198 EUR.
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

# Lus dans l'environnement de production le 2026-10-11.
PALIERS = ((1.0, 0.75), (1.5, 1.25), (1.75, 1.5), (2.0, 1.75))
TP_ECART = 2.0          # l'objectif devient `seuil + 2 EUR`
PROT_AGE_MIN = 5        # 300 s
PROT_NEG_MIN = 2.5      # 150 s
PROT_MARGE = 2.0        # plancher : perte + 2 EUR

STRATEGIES = (
    ("T  temoin",      20.0, 2.0, False, False),
    ("A1 production",  20.0, 2.0, True,  False),
    ("A2 +protection", 20.0, 2.0, True,  True),
    ("B1 stop -1",      1.0, 2.0, False, False),
    ("B2 stop -2",      2.0, 2.0, False, False),
    ("B3 -2 +echelle",  2.0, 2.0, True,  False),
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


def palier_cible(profit_eur):
    """Cible du stop (en EUR de profit) pour le palier franchi, ou None."""
    cible = None
    for seuil, c in PALIERS:
        if profit_eur >= seuil - 1e-9:
            cible = c
    return cible


def seuil_franchi(profit_eur):
    retenu = None
    for seuil, _c in PALIERS:
        if profit_eur >= seuil - 1e-9:
            retenu = seuil
    return retenu


def parcourir(hi, lo, cl, i, achat, cout_eur):
    """Rend {nom: (pnl_eur, issue, duree_min)} pour les six strategies."""
    e = cl[i]
    k = 1.0 / EUR_USD                      # EUR par dollar de mouvement
    etats = {}
    for (nom, sl, tp, ech, prot) in STRATEGIES:
        etats[nom] = {"stop": -sl, "tp": tp, "ech": ech, "prot": prot,
                      "fini": None, "neg": 0}
    fin = min(len(hi), i + 1 + CAP)
    for j in range(i + 1, fin):
        if achat:
            bas = (lo[j] - e) * k
            haut = (hi[j] - e) * k
            fermeture = (cl[j] - e) * k
        else:
            bas = (e - hi[j]) * k
            haut = (e - lo[j]) * k
            fermeture = (e - cl[j]) * k
        tous_finis = True
        for nom, s in etats.items():
            if s["fini"] is not None:
                continue
            tous_finis = False
            # ⛔ le stop d'abord : convention declaree
            if bas <= s["stop"] + 1e-12:
                issue = "SL"
                if s["stop"] > -1e-9:
                    issue = "ECHELLE"
                elif s["stop"] > -20.0 + 1e-9 and s["prot"]:
                    issue = "PROTECTION"
                s["fini"] = (s["stop"] - cout_eur, issue, j - i)
                continue
            if haut >= s["tp"] - 1e-12:
                s["fini"] = (s["tp"] - cout_eur, "TP", j - i)
                continue
            # --- echelle de GAINS ---
            # ⛔ SUR LA CLOTURE, PAS SUR L'EXTREME. Mon premier jet armait le
            # palier sur le plus-haut de la bougie : si le prix touchait +1,00
            # puis revenait a +0,50, le stop etait pose a +0,75 -- c'est-a-dire
            # AU-DESSUS du cours -- et je creditais +0,75 pour une sortie qui
            # aurait eu lieu plus bas. La production refuse precisement cela
            # (<< poser un stop du mauvais cote du cours FERME la position >>).
            # Cette version n'arme un palier que si le stop reste SOUS le cours.
            if s["ech"]:
                cible = palier_cible(fermeture)
                if (cible is not None and cible > s["stop"]
                        and cible < fermeture - 1e-12):
                    s["stop"] = cible
                    seuil = seuil_franchi(fermeture)
                    if seuil is not None:
                        s["tp"] = max(s["tp"], seuil + TP_ECART)
            # --- protection des PERTES : sur la cloture ---
            if s["prot"]:
                if fermeture < 0:
                    s["neg"] += 1
                else:
                    s["neg"] = 0
                age = j - i
                perte = -fermeture
                if (age >= PROT_AGE_MIN and perte > 0
                        and s["neg"] >= PROT_NEG_MIN):
                    distance = -s["stop"]          # distance positive
                    plancher = perte + PROT_MARGE
                    if distance > plancher:
                        vise = (distance + perte) / 2.0
                        if vise < plancher:
                            vise = plancher
                        if vise < distance:
                            s["stop"] = -vise
        if tous_finis:
            break
    for nom, s in etats.items():
        if s["fini"] is None:
            if achat:
                d = (cl[fin - 1] - e) * k
            else:
                d = (e - cl[fin - 1]) * k
            s["fini"] = (d - cout_eur, "TEMPS", fin - 1 - i)
    return {nom: s["fini"] for nom, s in etats.items()}


def main():
    ts, hi, lo, cl, sp = charger()
    entrees = list(range(0, len(ts) - 2, PAS_ENTREE))
    milieu = ts[len(ts) // 2]
    print("magasin %s" % MAGASIN)
    print("%d bougies M1   %s -> %s" % (len(ts), ts[0], ts[-1]))
    print("entrees : %d toutes les %d min, deux sens  ⇒  %d trades"
          % (len(entrees), PAS_ENTREE, 2 * len(entrees)))
    print("paliers lus en production : %s   objectif = seuil + %.1f EUR"
          % (PALIERS, TP_ECART))
    print("coupure d'echantillon : %s" % milieu.date())

    par_jour = {n[0]: collections.defaultdict(list) for n in STRATEGIES}
    tous = {n[0]: [] for n in STRATEGIES}
    issues = {n[0]: collections.Counter() for n in STRATEGIES}
    durees = {n[0]: [] for n in STRATEGIES}
    moities = {n[0]: ([], []) for n in STRATEGIES}
    for idx, i in enumerate(entrees):
        cout_eur = sp[i] * POINT_USD / EUR_USD
        for achat in (True, False):
            r = parcourir(hi, lo, cl, i, achat, cout_eur)
            for nom, (pnl, issue, duree) in r.items():
                par_jour[nom][ts[i].date()].append(pnl)
                tous[nom].append(pnl)
                issues[nom][issue] += 1
                durees[nom].append(duree)
                moities[nom][0 if ts[i] < milieu else 1].append(pnl)
        if (idx + 1) % 1000 == 0:
            print("   %d/%d entrees..." % (idx + 1, len(entrees)), flush=True)

    print("\n%-16s%11s%11s%12s%11s%11s%10s"
          % ("strategie", "EUR/trade", "ecart-type", "pire jour",
             "reussite", "duree min", "n"))
    resume = {}
    for (nom, sl, tp, ech, prot) in STRATEGIES:
        v = tous[nom]
        jours = [st.fmean(x) for x in par_jour[nom].values()]
        pire = min(jours)
        gagnants = sum(1 for x in v if x > 0)
        resume[nom] = {
            "moy": st.fmean(v), "sd": st.stdev(v), "pire": pire,
            "jours": {d: st.fmean(x) for d, x in par_jour[nom].items()},
            "m1": st.fmean(moities[nom][0]), "m2": st.fmean(moities[nom][1]),
        }
        print("%-16s%+11.4f%11.4f%+12.4f%10.2f%%%11.1f%10d"
              % (nom, st.fmean(v), st.stdev(v), pire,
                 100 * gagnants / len(v), st.fmean(durees[nom]), len(v)))
        print("%-16s   issues : %s" % ("", dict(issues[nom])))

    print("\n=== LES PAIRES, ecart par JOUR et t (critere : |t| > 2,5) ===")
    noms = [n[0] for n in STRATEGIES]
    print("%-34s%12s%9s%12s%12s%9s"
          % ("paire", "ecart/jour", "t", "1re moitie", "2e moitie", "signe"))
    for a in range(len(noms)):
        for b in range(a + 1, len(noms)):
            na, nb = noms[a], noms[b]
            ja, jb = resume[na]["jours"], resume[nb]["jours"]
            communs = sorted(set(ja) & set(jb))
            ecarts = [ja[d] - jb[d] for d in communs]
            m = st.fmean(ecarts)
            s = st.stdev(ecarts) if len(ecarts) > 2 else 0.0
            t = m / (s / math.sqrt(len(ecarts))) if s else 0.0
            d1 = resume[na]["m1"] - resume[nb]["m1"]
            d2 = resume[na]["m2"] - resume[nb]["m2"]
            marque = "***" if abs(t) > 2.5 else ""
            print("%-34s%+12.4f%+9.2f%+12.4f%+12.4f%9s %s"
                  % ("%s  -  %s" % (na, nb), m, t, d1, d2,
                     "stable" if (d1 > 0) == (d2 > 0) else "INVERSE", marque))
    print("\n*** = |t| > 2,5, le critere pre-inscrit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
