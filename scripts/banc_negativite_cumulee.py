#!/usr/bin/env python3
"""Negativite CUMULEE contre CONSECUTIVE, sur les ticks du courtier.

Pre-inscrit dans docs/predictions/2026-10-12_negativite_cumulee.md AVANT
d'ecrire ce fichier (commit b3481b2).

⚠️ POURQUOI LES TICKS ET PAS LES BOUGIES M1 : la regle raisonne en SECONDES.
Un OHLC par minute ne dit rien du chemin intra-minute, donc il est INCAPABLE
de departager 30 s continues d'un cumul de 30 s. Mesurer sur M1 serait
inventer la reponse.
"""
from __future__ import annotations

import collections
import datetime as dt
import math
import os
import sqlite3
import statistics as st
import sys

MAGASIN = os.getenv("TICKS", "/app/data/ticks_courtier.db")
EUR_USD = 1.1198

# La production, a l'identique.
SL_DEPART_EUR = 13.0
TRAINAGE = 0.50
DECLENCHE = 0.50
PAS_MINI = 0.10
PLANCHER_EUR = 2.0
PLAFOND_EUR = 9.0
MARGE_MIN_EUR = 2.0
AGE_MINI_SEC = 60
CADENCE_SEC = 60
NEG_REQUIS_SEC = 30
CAP_SEC = 14400          # 4 h : au-dela on clot sur le dernier tick
REPOS_SEC = 300          # entre deux entrees, pour ne pas compter 100 fois
                         # le meme mouvement

# Les quatre regles. `fenetre` = None -> serie CONSECUTIVE.
REGLES = (
    ("A consecutive", None),
    ("B cumulee 60s", 60),
    ("B cumulee 120s", 120),
    ("B cumulee 180s", 180),
    ("C sans condition", 0),      # 0 -> aucune condition de negativite
)


def charger():
    c = sqlite3.connect(MAGASIN)
    rows = c.execute("SELECT ts_utc, ms, bid, ask FROM ticks "
                     "WHERE pair = 'XAU/USD' ORDER BY ts_utc, ms").fetchall()
    ts, bid, ask = [], [], []
    for t, ms, b, a in rows:
        if ms and ms > 1e12:
            ts.append(ms / 1000.0)
        else:
            d = dt.datetime.fromisoformat(t).replace(tzinfo=dt.timezone.utc)
            ts.append(d.timestamp() + (ms or 0) / 1000.0)
        bid.append(b)
        ask.append(a)
    return ts, bid, ask


def rejouer(ts, bid, ask, i, achat, fenetre):
    """Rend le P&L en euros d'une position ouverte au tick `i`.

    `fenetre` : None = negatif CONSECUTIF ; un entier > 0 = cumul sur cette
    fenetre glissante ; 0 = aucune condition de negativite.
    """
    k = 1.0 / EUR_USD
    entree = ask[i] if achat else bid[i]
    t0 = ts[i]
    stop = -SL_DEPART_EUR
    neg_depuis = None                 # debut de la serie negative en cours
    negatifs = collections.deque()    # (instant, duree) pour le cumul
    dernier_vu = None
    vu_trainage = -1e18
    vu_prot = -1e18
    n = len(ts)
    j = i + 1

    while j < n and ts[j] - t0 <= CAP_SEC:
        sortie = bid[j] if achat else ask[j]
        pnl = (sortie - entree) * k if achat else (entree - sortie) * k
        if pnl <= stop + 1e-12:
            return stop

        # ── le temps passe en negatif, compte des DEUX facons ─────────────
        if dernier_vu is not None and pnl < 0:
            negatifs.append((ts[j], ts[j] - dernier_vu))
        dernier_vu = ts[j]
        if pnl < 0:
            if neg_depuis is None:
                neg_depuis = ts[j]
        else:
            neg_depuis = None         # ⛔ LE DEFAUT : un retour en positif
                                      # remet la serie CONSECUTIVE a zero
        if fenetre:
            while negatifs and ts[j] - negatifs[0][0] > fenetre:
                negatifs.popleft()

        # ── cote GAIN : le trainage, a la seconde ────────────────────────
        if ts[j] - vu_trainage >= 1:
            vu_trainage = ts[j]
            if pnl >= DECLENCHE - 1e-9:
                cible = pnl - TRAINAGE
                if cible > stop + PAS_MINI - 1e-9 and cible < pnl:
                    stop = cible

        # ── cote PERTE : la protection, a la cadence ─────────────────────
        if ts[j] - vu_prot >= CADENCE_SEC:
            vu_prot = ts[j]
            perte = -pnl
            if ts[j] - t0 >= AGE_MINI_SEC and perte > 0:
                if fenetre is None:
                    assez = (neg_depuis is not None
                             and ts[j] - neg_depuis >= NEG_REQUIS_SEC)
                elif fenetre == 0:
                    assez = True
                else:
                    assez = sum(d for _, d in negatifs) >= NEG_REQUIS_SEC
                if assez:
                    largeur = -stop
                    plancher = PLANCHER_EUR
                    if largeur > plancher:
                        vise = (largeur + perte) / 2.0
                        if vise < plancher:
                            vise = plancher
                        vise = min(vise, max(PLAFOND_EUR,
                                             perte + MARGE_MIN_EUR))
                        if vise < largeur:
                            stop = -vise
        j += 1

    fin = min(j, n - 1)
    sortie = bid[fin] if achat else ask[fin]
    return (sortie - entree) * k if achat else (entree - sortie) * k


def main() -> int:
    ts, bid, ask = charger()
    jours = [dt.datetime.fromtimestamp(t, dt.timezone.utc).date() for t in ts]
    print("%d ticks   %d jours   du %s au %s"
          % (len(ts), len(set(jours)), min(jours), max(jours)))

    # ── Les instants d'entree : un toutes les REPOS_SEC, sens alterne ────
    # 🔑 Le SENS alterne plutot qu'aleatoire : les sept zeros disent que la
    # direction n'a pas d'information, donc alterner donne un echantillon
    # EQUILIBRE sans introduire de graine a justifier.
    entrees = []
    dernier = -1e18
    for i in range(1, len(ts) - 1):
        if ts[i] - dernier < REPOS_SEC:
            continue
        entrees.append((i, len(entrees) % 2 == 0))
        dernier = ts[i]
    print("%d positions rejouees par regle, soit %d au total"
          % (len(entrees), len(entrees) * len(REGLES)))
    print()

    resultats = {}
    for nom, fenetre in REGLES:
        par_jour = collections.defaultdict(list)
        for i, achat in entrees:
            par_jour[jours[i]].append(rejouer(ts, bid, ask, i, achat, fenetre))
        tous = [x for v in par_jour.values() for x in v]
        moyennes = [st.fmean(v) for _, v in sorted(par_jour.items())]
        resultats[nom] = {
            "par_jour": par_jour, "tous": tous, "moyennes": moyennes,
            "moyenne": st.fmean(tous),
            "pire_jour": min(moyennes),
            "reussite": 100.0 * sum(1 for x in tous if x > 0) / len(tous),
            "stop_depart": sum(1 for x in tous if x <= -SL_DEPART_EUR + 0.01),
        }
        r = resultats[nom]
        print("  %-18s moyenne %+7.4f EUR   pire jour %+7.3f   "
              "reussite %5.1f %%   stop de depart touche %4d"
              % (nom, r["moyenne"], r["pire_jour"], r["reussite"],
                 r["stop_depart"]))

    # ── L'ecart APPARIE contre A, jour par jour ──────────────────────────
    print()
    print("  ECART CONTRE A, apparie sur le JOUR")
    print("  %-18s %10s %8s %10s %10s" % ("regle", "ecart", "t", "1re moitie",
                                          "2e moitie"))
    a = resultats["A consecutive"]["moyennes"]
    for nom, _ in REGLES:
        if nom == "A consecutive":
            continue
        b = resultats[nom]["moyennes"]
        ec = [x - y for x, y in zip(b, a)]
        m = st.fmean(ec)
        s = st.stdev(ec) if len(ec) > 1 else 0.0
        t = m / (s / math.sqrt(len(ec))) if s else 0.0
        mi = len(ec) // 2
        print("  %-18s %+10.4f %+8.2f %+10.4f %+10.4f"
              % (nom, m, t, st.fmean(ec[:mi]), st.fmean(ec[mi:])))

    # ── LE CRITERE PRE-INSCRIT ───────────────────────────────────────────
    print()
    print("  === LE CRITERE PRE-INSCRIT ===")
    for nom, _ in REGLES:
        if nom == "A consecutive":
            continue
        b = resultats[nom]
        ec = [x - y for x, y in zip(b["moyennes"], a)]
        m = st.fmean(ec)
        s = st.stdev(ec) if len(ec) > 1 else 0.0
        t = m / (s / math.sqrt(len(ec))) if s else 0.0
        mi = len(ec) // 2
        c1 = b["pire_jour"] > resultats["A consecutive"]["pire_jour"]
        c2 = t > -2.0
        c3 = (st.fmean(ec[:mi]) > 0) == (st.fmean(ec[mi:]) > 0)
        print("  %-18s pire jour meilleur %-5s   t > -2 %-5s   "
              "signe stable %-5s   => %s"
              % (nom, c1, c2, c3, "RETENU" if (c1 and c2 and c3) else "rejete"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
