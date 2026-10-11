#!/usr/bin/env python3
"""Le trainage rejoue TICK PAR TICK, et non sur des bougies.

Demande de Xavier le 2026-10-11. 608 293 ticks du courtier, 3 jours reels
(2026-10-07 00:00 -> 2026-10-09 20:56:34, la cloture du vendredi).

🔑 CE QUE LES TICKS APPORTENT, par rapport a mes bancs sur bougies :

1. **l'ordre des evenements est connu** : plus de convention « la bougie
   contient les deux bornes, on prend le stop », qui valait a elle seule un
   encadrement de 0,225 EUR/trade ;
2. **le spread est DANS la donnee** : un achat entre a l'`ask` et sort au
   `bid`, une vente l'inverse. Plus rien n'est modelise ;
3. **la cadence se simule vraiment** : on peut comparer un trainage evalue a
   CHAQUE tick, a la seconde, a 15 s, et a la minute.

⛔ CE QUE CE BANC NE FAIT PAS : valider une strategie. **Trois jours ne
valident rien** — l'unite statistique serait le jour, et il n'y en a que trois.
Il mesure UNE chose : **ce que l'approximation a la minute m'a fait dire de
faux**. Les strategies sont comparees APPARIEES, sur les memes entrees et les
memes ticks.
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
PAS_ENTREE_SEC = int(os.getenv("PAS_ENTREE_SEC", "300"))   # une entree / 5 min
CAP_SEC = int(os.getenv("CAP_SEC", "86400"))               # 24 h
SL_DEPART = 13.0          # la vraie production : 0,35 % du prix
TRAINAGE = 0.5
DECLENCHE = 0.5
PLANCHER = 2.0
MARGE_FRANCHIE = 0.10
PROT_AGE_SEC = 60
PROT_NEG_SEC = 30
INFINI = 1e9

# nom, cadence du trainage en secondes (0 = chaque tick), objectif, cadence
# de la protection en secondes, echelle de production ?
STRATEGIES = (
    ("TICK  chaque tick", 0, None, 60, False),
    ("1 s", 1, None, 60, False),
    ("15 s  (production)", 15, None, 60, False),
    ("60 s  (mes bancs)", 60, None, 60, False),
    ("PROD objectif 2 EUR", 15, 2.0, 300, True),
)
ECH_PROD = ((1.0, 0.75), (1.5, 1.25), (1.75, 1.5), (2.0, 1.75))


def charger():
    c = sqlite3.connect(MAGASIN)
    rows = c.execute("SELECT ts_utc, ms, bid, ask FROM ticks "
                     "WHERE pair = 'XAU/USD' ORDER BY ts_utc, ms").fetchall()
    ts, bid, ask = [], [], []
    for t, ms, b, a in rows:
        d = dt.datetime.fromisoformat(t).replace(tzinfo=dt.timezone.utc)
        # ⛔ DEFAUT ATTRAPE PAR UNE DATE ABSURDE (<< 2083 >> a l'affichage) :
        # le champ `ms` du pont est un horodatage epoch COMPLET en
        # millisecondes (`time_msc` de MT5), pas un reste de seconde. En
        # l'additionnant je DOUBLAIS le temps : toutes les durees valaient le
        # double, et chaque porte de cadence s'ouvrait deux fois trop souvent
        # (une cadence de 60 s se comportait comme 30 s).
        # 🔑 C'est l'invraisemblance de l'annee affichee qui l'a trahi, pas une
        # relecture du code.
        if ms and ms > 1e12:
            ts.append(ms / 1000.0)
        else:
            ts.append(d.timestamp() + (ms or 0) / 1000.0)
        bid.append(b)
        ask.append(a)
    return ts, bid, ask


def palier_prod(profit):
    cible = seuil = None
    for s, c in ECH_PROD:
        if profit >= s - 1e-9:
            cible, seuil = c, s
    return cible, seuil


def parcourir(ts, bid, ask, i, achat):
    """Rejoue UN instant d'entree pour toutes les strategies, tick par tick."""
    k = 1.0 / EUR_USD
    entree = ask[i] if achat else bid[i]
    t0 = ts[i]
    etats = {}
    for (nom, cad, obj, cad_prot, prod) in STRATEGIES:
        etats[nom] = {"stop": -SL_DEPART, "tp": obj if obj else INFINI,
                      "cad": cad, "prod": prod, "cad_prot": cad_prot,
                      "vu": -1e18, "vu_prot": -1e18, "neg_depuis": None,
                      "fini": None, "bouges": 0}
    n = len(ts)
    j = i + 1
    while j < n and ts[j] - t0 <= CAP_SEC:
        # 🔑 le prix de SORTIE : un achat sort au bid, une vente a l'ask.
        # Le spread est donc paye par la donnee elle-meme.
        sortie = bid[j] if achat else ask[j]
        pnl = (sortie - entree) * k if achat else (entree - sortie) * k
        age = ts[j] - t0
        reste = False
        for nom, s in etats.items():
            if s["fini"] is not None:
                continue
            reste = True
            if pnl <= s["stop"] + 1e-12:
                issue = ("SUIVEUR" if s["stop"] > 1e-9 else
                         "POINT MORT" if abs(s["stop"]) < 1e-9 else
                         "SL DEPART" if s["stop"] <= -SL_DEPART + 1e-9 else
                         "PROTECTION")
                s["fini"] = (s["stop"], issue, age)
                continue
            if pnl >= s["tp"] - 1e-12:
                s["fini"] = (s["tp"], "OBJECTIF", age)
                continue
            # --- cote gain, a la cadence de la strategie ---
            if s["cad"] == 0 or ts[j] - s["vu"] >= s["cad"]:
                s["vu"] = ts[j]
                if s["prod"]:
                    cible, seuil = palier_prod(pnl)
                    if cible is not None and cible > s["stop"] and cible < pnl:
                        s["stop"] = cible
                        s["bouges"] += 1
                        if seuil is not None and s["tp"] < INFINI:
                            s["tp"] = max(s["tp"], seuil + 2.0)
                elif pnl >= DECLENCHE - 1e-9:
                    cible = pnl - TRAINAGE
                    if cible > s["stop"] and cible < pnl:
                        s["stop"] = cible
                        s["bouges"] += 1
            # --- cote perte, a sa propre cadence ---
            if pnl < 0:
                if s["neg_depuis"] is None:
                    s["neg_depuis"] = ts[j]
            else:
                s["neg_depuis"] = None
            if ts[j] - s["vu_prot"] >= s["cad_prot"]:
                s["vu_prot"] = ts[j]
                perte = -pnl
                assez = (s["neg_depuis"] is not None
                         and ts[j] - s["neg_depuis"] >= PROT_NEG_SEC)
                if age >= PROT_AGE_SEC and perte > 0 and assez:
                    distance = -s["stop"]
                    plancher = max(PLANCHER, perte + MARGE_FRANCHIE)
                    if distance > plancher:
                        vise = max((distance + perte) / 2.0, plancher)
                        if vise < distance:
                            s["stop"] = -vise
                            s["bouges"] += 1
        if not reste:
            break
        j += 1
    for nom, s in etats.items():
        if s["fini"] is None:
            fin = min(j, n - 1)
            sortie = bid[fin] if achat else ask[fin]
            pnl = (sortie - entree) * k if achat else (entree - sortie) * k
            s["fini"] = (pnl, "TEMPS", ts[fin] - t0)
    return {nom: (s["fini"], s["bouges"]) for nom, s in etats.items()}


def main():
    ts, bid, ask = charger()
    def _lisible(x):
        return dt.datetime.fromtimestamp(x, dt.timezone.utc).isoformat(
            timespec="seconds")

    print("%d ticks   %s -> %s" % (len(ts), _lisible(ts[0]), _lisible(ts[-1])))
    ecarts = [ts[i + 1] - ts[i] for i in range(0, min(len(ts) - 1, 50000))]
    print("ecart median entre deux ticks : %.3f s   (soit %.1f ticks/s)"
          % (st.median(ecarts), 1.0 / max(st.median(ecarts), 1e-9)))
    spreads = [(ask[i] - bid[i]) for i in range(0, len(ts), 97)]
    print("spread median mesure : %.3f $ (p90 %.3f)"
          % (st.median(spreads), sorted(spreads)[int(0.9 * len(spreads))]))

    # instants d'entree : le premier tick de chaque tranche de PAS_ENTREE_SEC
    entrees = []
    prochain = ts[0]
    for i, t in enumerate(ts):
        if t >= prochain:
            entrees.append(i)
            prochain = t + PAS_ENTREE_SEC
    print("entrees : %d toutes les %d s, deux sens  ⇒  %d trades"
          % (len(entrees), PAS_ENTREE_SEC, 2 * len(entrees)))

    noms = [n[0] for n in STRATEGIES]
    tous = {n: [] for n in noms}
    issues = {n: collections.Counter() for n in noms}
    bouges = {n: 0 for n in noms}
    durees = {n: [] for n in noms}
    apparie = {n: [] for n in noms}
    for idx, i in enumerate(entrees):
        for achat in (True, False):
            r = parcourir(ts, bid, ask, i, achat)
            for nom, ((pnl, issue, duree), nb) in r.items():
                tous[nom].append(pnl)
                issues[nom][issue] += 1
                bouges[nom] += nb
                durees[nom].append(duree)
                apparie[nom].append(pnl)
        if (idx + 1) % 200 == 0:
            print("   %d/%d entrees..." % (idx + 1, len(entrees)), flush=True)

    print("\n%-22s%11s%10s%10s%9s%10s%12s"
          % ("cadence", "EUR/trade", "sd", "reussite", "duree s", "max",
             "deplacements"))
    for nom in noms:
        v = tous[nom]
        print("%-22s%+11.4f%10.4f%9.2f%%%9.0f%+10.2f%12d"
              % (nom, st.fmean(v), st.stdev(v),
                 100 * sum(1 for x in v if x > 0) / len(v),
                 st.fmean(durees[nom]), max(v), bouges[nom]))
        print("%-22s   issues : %s" % ("", dict(issues[nom])))

    base = "1 s"
    print("\n=== CHAQUE CADENCE CONTRE << %s >>, APPARIEE PAR TRADE ===" % base)
    print("%-22s%12s%9s%10s" % ("cadence", "ecart/trade", "t", "n"))
    for nom in noms:
        if nom == base:
            continue
        ec = [a - b for a, b in zip(apparie[nom], apparie[base])]
        m = st.fmean(ec)
        s = st.stdev(ec) if len(ec) > 2 else 0.0
        t = m / (s / math.sqrt(len(ec))) if s else 0.0
        print("%-22s%+12.4f%+9.2f%10d" % (nom, m, t, len(ec)))
    print("\n⛔ Trois jours ne valident AUCUNE strategie : l'unite serait le")
    print("   JOUR, et il n'y en a que trois. Ce banc mesure ce que")
    print("   l'approximation a la minute m'a fait dire de faux, rien d'autre.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
