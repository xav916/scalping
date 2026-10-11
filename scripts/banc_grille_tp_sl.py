#!/usr/bin/env python3
"""La GRILLE COMPLETE des couples TP/SL sur l'or.

Pre-inscrit dans docs/predictions/2026-10-11_grille_tp_sl_exhaustive.md
(commit ca8bd92) AVANT d'ecrire ce fichier. Demande de Xavier : "je veux que tu
trouves le juste couple TP/SL qui soit au max gagnant sur l'or".

120 couples, bougies M5 DU COURTIER, entrees aveugles une par heure dans les
DEUX sens, deux panneaux (neutre et directionnel), designation sur la premiere
moitie et jugement sur la seconde.

## Le seul parametre que la pre-inscription ne fixait pas, declare ici

Une borne peut n'etre jamais touchee. Plutot que d'ECARTER ces trades -- ce qui
retirerait les plus lents, donc selectionnerait l'issue -- on les ferme AU PRIX
du marche apres 288 bougies (24 h). Aucun trade n'est perdu, et la part fermee
par le TEMPS est publiee.
"""
from __future__ import annotations

import bisect
import collections
import datetime as dt
import math
import os
import sqlite3
import statistics as st
import sys

MAGASIN = os.getenv("MAGASIN", "/app/data/candles_courtier.db")
PAIRE = os.getenv("PAIRE", "XAU/USD")
EUR_USD = float(os.getenv("EUR_USD", "1.1198"))   # taux du courtier
POINT_USD = 0.01                                   # 1 point XAU/USD
PAS_ENTREE = int(os.getenv("PAS_ENTREE", "12"))    # une entree par heure
MAX_BOUGIES = int(os.getenv("MAX_BOUGIES", "288"))  # 24 h, puis sortie au prix
PLAFOND_T = 2.80                                   # pre-inscrit, 120 cellules
MIN_N = 500                                        # pre-inscrit
# Convention quand UNE bougie M5 contient l'objectif ET le stop. "sl" est celle
# de la pre-inscription (la plus defavorable) ; "tp" sert d'ENCADREMENT, pour
# mesurer ce que la convention pese elle-meme.
EGALITE = os.getenv("EGALITE", "sl")

TPS = (1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0, 15.0, 20.0)
SLS = (1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0, 15.0, 20.0, 30.0, 40.0)


def charger():
    c = sqlite3.connect(MAGASIN)
    rows = c.execute(
        "SELECT ts_utc, high, low, close, spread_pts FROM candles "
        "WHERE pair = ? ORDER BY ts_utc", (PAIRE,)).fetchall()
    ts, hi, lo, cl, sp = [], [], [], [], []
    for t, h, l, c2, s in rows:
        d = dt.datetime.fromisoformat(t)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        ts.append(d.astimezone(dt.timezone.utc))
        hi.append(h)
        lo.append(l)
        cl.append(c2)
        sp.append(s if s is not None else 5.0)
    return ts, hi, lo, cl, sp


def chemins(hi, lo, i):
    """Les deux escaliers d'extremes du chemin qui suit l'entree i.

    🔑 Les niveaux sont pre-extraits en listes separees : les 120 couples
    appellent la recherche des millions de fois, et reconstruire la liste a
    chaque appel coutait 80 millions d'operations inutiles.

    j_monte / n_monte : indices et plus-hauts cumules, niveaux CROISSANTS
    j_baisse / n_baisse : indices et plus-bas cumules, niveaux DECROISSANTS
    """
    fin = min(len(hi), i + 1 + MAX_BOUGIES)
    j_monte, n_monte, j_baisse, n_baisse = [], [], [], []
    hmax, lmin = -1e18, 1e18
    for j in range(i + 1, fin):
        if hi[j] > hmax:
            hmax = hi[j]
            j_monte.append(j)
            n_monte.append(hmax)
        if lo[j] < lmin:
            lmin = lo[j]
            j_baisse.append(j)
            n_baisse.append(-lmin)      # opposes : CROISSANTS, pour bisect
    return (j_monte, n_monte), (j_baisse, n_baisse), fin - 1


def _premier_au_dessus(monte, cible):
    """Premier j ou le plus-haut cumule atteint `cible` (None sinon)."""
    js, niveaux = monte
    k = bisect.bisect_left(niveaux, cible)
    return js[k] if k < len(js) else None


def _premier_en_dessous(baisse, cible):
    """Premier j ou le plus-bas cumule descend a `cible` (None sinon).

    Niveaux DECROISSANTS : `bisect` travaille sur leurs opposes.
    """
    js, niveaux = baisse            # `niveaux` contient deja les OPPOSES
    k = bisect.bisect_left(niveaux, -cible)
    return js[k] if k < len(js) else None


def issue(entree, monte, baisse, close_fin, tp_usd, sl_usd, achat):
    """P&L brut en USD, et True si la sortie est due au TEMPS."""
    if achat:
        t_tp = _premier_au_dessus(monte, entree + tp_usd)
        t_sl = _premier_en_dessous(baisse, entree - sl_usd)
    else:
        t_tp = _premier_en_dessous(baisse, entree - tp_usd)
        t_sl = _premier_au_dessus(monte, entree + sl_usd)
    if EGALITE == "sl":
        # ⛔ egalite = la bougie contient les DEUX : on prend le stop.
        perd = t_sl is not None and (t_tp is None or t_sl <= t_tp)
    else:
        perd = t_sl is not None and (t_tp is None or t_sl < t_tp)
    if perd:
        return -sl_usd, False
    if t_tp is not None:
        return tp_usd, False
    d = close_fin - entree
    return (d if achat else -d), True


def main():
    ts, hi, lo, cl, sp = charger()
    print("magasin %s   %d bougies M5   %s -> %s"
          % (MAGASIN, len(ts), ts[0].date(), ts[-1].date()))
    entrees = list(range(0, len(ts) - 1, PAS_ENTREE))
    milieu = ts[len(ts) // 2]
    print("entrees : %d (une toutes les %d bougies), coupure echantillon %s"
          % (len(entrees), PAS_ENTREE, milieu.date()))
    print("taux EUR/USD %.4f  ⇒  TP 2 EUR = %.3f USD" % (EUR_USD, 2 * EUR_USD))

    # Pre-calcul des chemins : fait UNE fois, servira aux 120 couples.
    paquets = []
    for i in entrees:
        monte, baisse, dernier = chemins(hi, lo, i)
        if not monte[0] and not baisse[0]:
            continue
        paquets.append((i, cl[i], monte, baisse, cl[dernier], sp[i],
                        ts[i].date(), ts[i] < milieu))
    print("chemins pre-calcules : %d" % len(paquets))

    res = {}
    for tp_e in TPS:
        for sl_e in SLS:
            tp_u, sl_u = tp_e * EUR_USD, sl_e * EUR_USD
            # jour -> listes de P&L par panneau
            neutre = collections.defaultdict(list)
            direct = collections.defaultdict(list)
            n_dans = n_hors = 0
            temps = 0
            for (i, e, monte, baisse, cfin, spread, jour, dedans) in paquets:
                cout = spread * POINT_USD
                pa, t1 = issue(e, monte, baisse, cfin, tp_u, sl_u, True)
                pv, t2 = issue(e, monte, baisse, cfin, tp_u, sl_u, False)
                temps += int(t1) + int(t2)
                a, v = pa - cout, pv - cout
                cle = (dedans, jour)
                neutre[cle].append((a + v) / 2.0)
                direct[cle].extend((a, v))
                if dedans:
                    n_dans += 2
                else:
                    n_hors += 2

            def agrege(seaux, dedans):
                jours = [st.fmean(v) for (d, j), v in seaux.items() if d == dedans]
                n = sum(len(v) for (d, j), v in seaux.items() if d == dedans)
                if len(jours) < 3:
                    return 0.0, 0.0, n, 0
                m = st.fmean(jours)
                s = st.stdev(jours)
                t = m / (s / math.sqrt(len(jours))) if s else 0.0
                return m, t, n, len(jours)

            res[(tp_e, sl_e)] = {
                "neutre_dans": agrege(neutre, True),
                "neutre_hors": agrege(neutre, False),
                "direct_dans": agrege(direct, True),
                "direct_hors": agrege(direct, False),
                "part_temps": temps / max(1, 2 * len(paquets)),
            }
        print("   TP %.1f EUR fait" % tp_e, flush=True)

    print("\n" + "=" * 78)
    print("PANNEAU NEUTRE — P&L moyen par trade, en CENTIMES de dollar")
    print("(achat ET vente au meme instant : l'exposition est nulle, "
          "il ne reste que le COUT)")
    print("=" * 78)
    print("TP\\SL  " + "".join("%7.1f" % s for s in SLS))
    for tp_e in TPS:
        ligne = "%5.1f  " % tp_e
        for sl_e in SLS:
            m = res[(tp_e, sl_e)]["neutre_hors"][0]
            ligne += "%7.2f" % (100 * m)
        print(ligne)
    tous = [100 * res[k]["neutre_hors"][0] for k in res]
    sp_med = st.median([x[5] for x in paquets]) * POINT_USD
    print("\nmediane des 120 : %.2f centimes   min %.2f   max %.2f"
          % (st.median(tous), min(tous), max(tous)))
    print("spread median paye : %.2f centimes par trade" % (100 * sp_med))
    print("couples neutres positifs : %d / 120" % sum(1 for x in tous if x > 0))

    print("\n" + "=" * 78)
    print("PANNEAU DIRECTIONNEL — designation sur la 1re moitie, "
          "jugement sur la 2e")
    print("=" * 78)
    classement = sorted(res.items(), key=lambda kv: -kv[1]["direct_dans"][0])
    print("%-12s%12s%9s%12s%9s%8s%8s" % ("couple", "dans $/tr", "t dans",
                                         "hors $/tr", "t hors", "n hors",
                                         "jours"))
    for (tp_e, sl_e), v in classement[:12]:
        md, td, nd, jd = v["direct_dans"]
        mh, th, nh, jh = v["direct_hors"]
        print("%-12s%12.4f%9.2f%12.4f%9.2f%8d%8d"
              % ("TP%g/SL%g" % (tp_e, sl_e), md, td, mh, th, nh, jh))

    (tp_e, sl_e), v = classement[0]
    md, td, nd, jd = v["direct_dans"]
    mh, th, nh, jh = v["direct_hors"]
    print("\nLE COUPLE DESIGNE (meilleur en echantillon) : TP %g / SL %g EUR"
          % (tp_e, sl_e))
    crit = [
        ("1. P&L hors echantillon > 0", mh > 0, "%.4f $/trade" % mh),
        ("2. |t| hors echantillon > %.2f" % PLAFOND_T, abs(th) > PLAFOND_T,
         "t = %+.2f sur %d jours" % (th, jh)),
        ("3. n hors echantillon >= %d" % MIN_N, nh >= MIN_N, "n = %d" % nh),
        ("4. meme SIGNE dedans et dehors",
         (md > 0) == (mh > 0), "dedans %+.4f, dehors %+.4f" % (md, mh)),
    ]
    for nom, ok, detail in crit:
        print("   %s %-38s %s" % ("✅" if ok else "⛔", nom, detail))
    print("\n⇒ COUPLE RETENU" if all(c[1] for c in crit)
          else "\n⇒ AUCUN COUPLE RETENU sur ce critere")

    retenus = []
    for k, v in res.items():
        mh, th, nh, jh = v["direct_hors"]
        md = v["direct_dans"][0]
        if mh > 0 and abs(th) > PLAFOND_T and nh >= MIN_N and (md > 0) == (mh > 0):
            retenus.append((k, md, mh, th, nh))
    print("\nET SI ON TESTAIT LES 120 (ce que la pre-inscription INTERDIT de "
          "faire pour conclure, publie pour l'honnetete) :")
    print("couples passant les 4 criteres hors echantillon : %d / 120"
          % len(retenus))
    for k, md, mh, th, nh in sorted(retenus, key=lambda x: -x[3])[:8]:
        print("   TP%g/SL%g  dedans %+.4f  dehors %+.4f  t %+.2f  n %d"
              % (k[0], k[1], md, mh, th, nh))
    print("\npart des trades fermes par le TEMPS (24 h) : %.1f %% a %.1f %%"
          % (100 * min(v["part_temps"] for v in res.values()),
             100 * max(v["part_temps"] for v in res.values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
