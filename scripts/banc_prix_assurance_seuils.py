#!/usr/bin/env python3
"""PISTE 3 : le prix de l'assurance -- couper sur un SEUIL en euros.

Pre-inscrit dans docs/predictions/2026-10-11_prix_de_l_assurance.md
(commit 52c10d8) AVANT d'ecrire ce fichier.

⛔ Ce banc ne RETIENT rien : il affiche un prix. Couper est une assurance, pas
un rendement, et un banc qui pretendrait la << valider >> confondrait les deux.

Memes 6 666 trades aveugles que le banc du signe : une entree toutes les
30 minutes, deux sens, magasin M1 du courtier, bornes TP 2 EUR / SL 20 EUR.
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
TP_USD = 2.0 * EUR_USD
SL_USD = 20.0 * EUR_USD
POINT_USD = 0.01
PAS_ENTREE = 30
CAP = 1440
SEUILS_EUR = (-1.0, -2.0, -5.0, -10.0)


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


def simuler(hi, lo, cl, i, achat, seuil_usd):
    """Rend (pnl_tenir, pnl_couper, coupe, aurait_atteint_tp) en USD brut."""
    e = cl[i]
    tp = e + TP_USD if achat else e - TP_USD
    sl = e - SL_USD if achat else e + SL_USD
    niveau = (e - seuil_usd) if achat else (e + seuil_usd)
    fin = min(len(hi), i + 1 + CAP)
    pnl_couper = None
    coupe = False
    for j in range(i + 1, fin):
        if achat:
            touche_sl, touche_tp = lo[j] <= sl, hi[j] >= tp
            touche_seuil = lo[j] <= niveau
        else:
            touche_sl, touche_tp = hi[j] >= sl, lo[j] <= tp
            touche_seuil = hi[j] >= niveau
        if pnl_couper is None and touche_seuil and not touche_sl:
            # ⛔ SIGNE : `seuil_usd` est une valeur ABSOLUE. Couper a -2 EUR
            # encaisse une PERTE. Mon premier jet ecrivait `+seuil_usd` et
            # annoncait +1,43 $/trade -- une assurance qui RAPPORTE, ce qui est
            # impossible et ce qui a trahi le defaut.
            pnl_couper = -seuil_usd
            coupe = True
        if touche_sl:
            if pnl_couper is None:
                pnl_couper = -SL_USD
            return -SL_USD, pnl_couper, coupe, False
        if touche_tp:
            if pnl_couper is None:
                pnl_couper = TP_USD
            return TP_USD, pnl_couper, coupe, True
    d = cl[fin - 1] - e
    brut = d if achat else -d
    if pnl_couper is None:
        pnl_couper = brut
    return brut, pnl_couper, coupe, False


def main():
    ts, hi, lo, cl, sp = charger()
    entrees = list(range(0, len(ts) - 2, PAS_ENTREE))
    print("bougies M1 : %d   %s -> %s" % (len(ts), ts[0], ts[-1]))
    print("entrees : %d toutes les %d min, deux sens  ⇒  %d trades"
          % (len(entrees), PAS_ENTREE, 2 * len(entrees)))
    print("bornes TP %.3f $ / SL %.3f $,  seuils testes : %s EUR"
          % (TP_USD, SL_USD, ", ".join("%g" % s for s in SEUILS_EUR)))

    print("\n%-10s%12s%12s%11s%13s%13s%12s%14s"
          % ("seuil", "TENIR $", "COUPER $", "cout", "ecart-type",
             "pire jour", "part coupee", "coupes -> TP"))
    jours_tenir = collections.defaultdict(list)
    base_faite = False
    sd_tenir = pire_tenir = moy_tenir = 0.0
    milieu = ts[len(ts) // 2]
    ecarts = {}
    for seuil in SEUILS_EUR:
        seuil_usd = abs(seuil) * EUR_USD
        tenir, couper = [], []
        par_jour_c = collections.defaultdict(list)
        ecarts_jour = collections.defaultdict(list)
        dedans, dehors = [], []
        n_coupe = 0
        coupe_vers_tp = 0
        for i in entrees:
            cout = sp[i] * POINT_USD
            for achat in (True, False):
                a, b, coupe, vers_tp = simuler(hi, lo, cl, i, achat, seuil_usd)
                tenir.append(a - cout)
                couper.append(b - cout)
                if not base_faite:
                    jours_tenir[ts[i].date()].append(a - cout)
                par_jour_c[ts[i].date()].append(b - cout)
                ecarts_jour[ts[i].date()].append(b - a)
                (dedans if ts[i] < milieu else dehors).append(b - a)
                if coupe:
                    n_coupe += 1
                    if vers_tp:
                        coupe_vers_tp += 1
        if not base_faite:
            moy_tenir = st.fmean(tenir)
            sd_tenir = st.stdev(tenir)
            pire_tenir = min(st.fmean(v) for v in jours_tenir.values())
            base_faite = True
        pire_c = min(st.fmean(v) for v in par_jour_c.values())
        print("%-10s%12.4f%12.4f%11.4f%13.4f%13.4f%11.1f%%%13.1f%%"
              % ("%g EUR" % seuil, moy_tenir, st.fmean(couper),
                 st.fmean(couper) - moy_tenir, st.stdev(couper), pire_c,
                 100 * n_coupe / len(tenir),
                 100 * coupe_vers_tp / max(1, n_coupe)))
        ecarts[seuil] = (ecarts_jour, dedans, dehors)
    print("\nTENIR sans rien faire : %+.4f $/trade, ecart-type %.4f, "
          "pire journee %.4f" % (moy_tenir, sd_tenir, pire_tenir))

    # ⚠️ AJOUT NON PRE-INSCRIT, et la raison est dite : la pre-inscription
    # annonçait un COUT. La mesure donne un GAIN aux seuils serres. Un prix
    # negatif n'est plus une assurance, c'est une regle -- et une regle se
    # juge, donc on la juge : t par JOUR, puis moitie/moitie.
    print("\n=== LE PRIX EST NEGATIF : on le JUGE donc comme une regle ===")
    print("%-10s%12s%10s%9s%14s%14s%10s"
          % ("seuil", "ecart/jour", "t", "jours", "1re moitie", "2e moitie",
             "signe"))
    for seuil in SEUILS_EUR:
        ecarts_jour, dedans, dehors = ecarts[seuil]
        jours = [st.fmean(v) for v in ecarts_jour.values()]
        m = st.fmean(jours)
        s = st.stdev(jours) if len(jours) > 2 else 0.0
        t = m / (s / math.sqrt(len(jours))) if s else 0.0
        m1 = st.fmean(dedans) if dedans else 0.0
        m2 = st.fmean(dehors) if dehors else 0.0
        print("%-10s%12.4f%+10.2f%9d%14.4f%14.4f%10s"
              % ("%g EUR" % seuil, m, t, len(jours), m1, m2,
                 "stable" if (m1 > 0) == (m2 > 0) else "INVERSE"))
    print("\n🔑 Rappel du banc du SIGNE (meme jour) : couper a k=5 coute "
          "0,3165 $/trade, ecart-type 3,5993, pire journee -1,6752.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
