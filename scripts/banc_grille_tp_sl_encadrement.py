#!/usr/bin/env python3
"""La grille TP/SL refaite en M1, pour RETRECIR l'encadrement de convention.

Suite du verdict `7c29d0f` : sur des bougies M5, changer la seule regle
« une bougie contient les deux bornes » deplacait une case de **86 centimes**,
plus que la plupart des effets que ce projet mesure. Le banc etait donc
INDECIDABLE aux bornes serrees, et pas seulement negatif.

Ici on compare **la meme periode, aux memes instants d'entree, au meme horizon
de 24 h**, en ne changeant QUE la granularite :

    M5  bougies de 5 min,  horizon 288 bougies
    M1  bougies de 1 min,  horizon 1440 bougies

et pour chaque granularite on calcule les DEUX conventions d'egalite dans le
MEME passage. L'ecart entre les deux est l'encadrement : c'est lui qui dit si
un verdict est decidable a cette echelle.

⚠️ La fenetre commune est courte (le magasin M1 ne couvre que 2026-08-30 ->
2026-10-08) : ce banc ne REFAIT pas le verdict de 17 mois, il mesure la
PRECISION disponible.
"""
from __future__ import annotations

import collections
import datetime as dt
import math
import os
import sqlite3
import statistics as st
import sys

sys.path.insert(0, "/app/scripts")

from banc_grille_tp_sl import (  # noqa: E402
    MIN_N, PLAFOND_T, SLS, TPS, _premier_au_dessus, _premier_en_dessous)

EUR_USD = 1.1198
POINT_USD = 0.01
DEBUT = dt.datetime.fromisoformat(
    os.getenv("FEN_DEBUT", "2026-08-30")).replace(tzinfo=dt.timezone.utc)
FIN = dt.datetime.fromisoformat(
    os.getenv("FEN_FIN", "2026-10-09")).replace(tzinfo=dt.timezone.utc)

ECHELLES = (
    ("M5", "/app/data/candles_courtier.db", 5, 12, 288),
    ("M1", "/app/data/candles_courtier_m1.db", 1, 60, 1440),
)


def charger(chemin):
    c = sqlite3.connect(chemin)
    rows = c.execute(
        "SELECT ts_utc, high, low, close, spread_pts FROM candles "
        "WHERE pair = 'XAU/USD' AND ts_utc >= ? AND ts_utc < ? ORDER BY ts_utc",
        (DEBUT.isoformat(), FIN.isoformat())).fetchall()
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


def chemins(hi, lo, i, horizon):
    fin = min(len(hi), i + 1 + horizon)
    j_m, n_m, j_b, n_b = [], [], [], []
    hmax, lmin = -1e18, 1e18
    for j in range(i + 1, fin):
        if hi[j] > hmax:
            hmax = hi[j]
            j_m.append(j)
            n_m.append(hmax)
        if lo[j] < lmin:
            lmin = lo[j]
            j_b.append(j)
            n_b.append(-lmin)
    return (j_m, n_m), (j_b, n_b), fin - 1


def issue(e, monte, baisse, cfin, tp_u, sl_u, achat, egalite_sl):
    if achat:
        t_tp = _premier_au_dessus(monte, e + tp_u)
        t_sl = _premier_en_dessous(baisse, e - sl_u)
    else:
        t_tp = _premier_en_dessous(baisse, e - tp_u)
        t_sl = _premier_au_dessus(monte, e + sl_u)
    if egalite_sl:
        perd = t_sl is not None and (t_tp is None or t_sl <= t_tp)
    else:
        perd = t_sl is not None and (t_tp is None or t_sl < t_tp)
    if perd:
        return -sl_u
    if t_tp is not None:
        return tp_u
    d = cfin - e
    return d if achat else -d


def t_par_jour(seaux, dedans):
    jours = [st.fmean(v) for (d, j), v in seaux.items() if d == dedans]
    n = sum(len(v) for (d, j), v in seaux.items() if d == dedans)
    if len(jours) < 3:
        return 0.0, 0.0, n, 0
    m = st.fmean(jours)
    s = st.stdev(jours)
    return m, (m / (s / math.sqrt(len(jours))) if s else 0.0), n, len(jours)


def passer(chemin, pas, horizon, nom):
    ts, hi, lo, cl, sp = charger(chemin)
    if not ts:
        print("%s : magasin VIDE sur la fenetre" % nom)
        return None
    milieu = ts[len(ts) // 2]
    # 🔑 Les entrees sont aux MEMES instants dans les deux echelles : on prend
    # une bougie par heure, donc l'heure pile.
    entrees = [i for i in range(0, len(ts) - 1, pas)]
    paquets = []
    for i in entrees:
        monte, baisse, dernier = chemins(hi, lo, i, horizon)
        if not monte[0] and not baisse[0]:
            continue
        paquets.append((cl[i], monte, baisse, cl[dernier], sp[i],
                        ts[i].date(), ts[i] < milieu))
    print("%s : %d bougies, %d entrees, coupure %s, horizon %d bougies"
          % (nom, len(ts), len(paquets), milieu.date(), horizon))
    out = {}
    for tp_e in TPS:
        for sl_e in SLS:
            tp_u, sl_u = tp_e * EUR_USD, sl_e * EUR_USD
            v = {}
            for eg, nom_eg in ((True, "sl"), (False, "tp")):
                neutre = collections.defaultdict(list)
                direct = collections.defaultdict(list)
                for (e, monte, baisse, cfin, spread, jour, dedans) in paquets:
                    cout = spread * POINT_USD
                    a = issue(e, monte, baisse, cfin, tp_u, sl_u, True, eg) - cout
                    d2 = issue(e, monte, baisse, cfin, tp_u, sl_u, False, eg) - cout
                    cle = (dedans, jour)
                    neutre[cle].append((a + d2) / 2.0)
                    direct[cle].extend((a, d2))
                v[nom_eg] = {
                    "neutre_hors": t_par_jour(neutre, False),
                    "direct_dans": t_par_jour(direct, True),
                    "direct_hors": t_par_jour(direct, False),
                }
            out[(tp_e, sl_e)] = v
    return out


def main():
    print("fenetre commune : %s -> %s" % (DEBUT.date(), FIN.date()))
    res = {}
    for nom, chemin, _pas_min, pas, horizon in ECHELLES:
        res[nom] = passer(chemin, pas, horizon, nom)

    print("\n" + "=" * 78)
    print("ENCADREMENT DE CONVENTION — |panneau neutre 'objectif' moins")
    print("'stop'|, en CENTIMES de dollar par trade. Plus petit = plus decidable.")
    print("=" * 78)
    for nom in ("M5", "M1"):
        if not res[nom]:
            continue
        print("\n%s" % nom)
        print("TP\\SL  " + "".join("%7.1f" % s for s in SLS))
        for tp_e in TPS:
            ligne = "%5.1f  " % tp_e
            for sl_e in SLS:
                v = res[nom][(tp_e, sl_e)]
                ligne += "%7.2f" % (100 * abs(v["tp"]["neutre_hors"][0]
                                              - v["sl"]["neutre_hors"][0]))
            print(ligne)

    if res["M5"] and res["M1"]:
        print("\n" + "=" * 78)
        print("CE QUE LE M1 FAIT GAGNER — rapport M5 / M1 de l'encadrement")
        print("=" * 78)
        gains = []
        for k in res["M5"]:
            e5 = abs(res["M5"][k]["tp"]["neutre_hors"][0]
                     - res["M5"][k]["sl"]["neutre_hors"][0])
            e1 = abs(res["M1"][k]["tp"]["neutre_hors"][0]
                     - res["M1"][k]["sl"]["neutre_hors"][0])
            gains.append((k, 100 * e5, 100 * e1, (e5 / e1) if e1 else float("inf")))
        for k, e5, e1, r in sorted(gains, key=lambda x: -x[1])[:6]:
            print("   TP%g/SL%g   M5 %7.2f c   M1 %7.2f c   ÷ %.2f"
                  % (k[0], k[1], e5, e1, r))
        med5 = st.median([g[1] for g in gains])
        med1 = st.median([g[2] for g in gains])
        print("   mediane des 120 : M5 %.2f c   M1 %.2f c   ÷ %.2f"
              % (med5, med1, med5 / med1 if med1 else float("inf")))
        print("   couples dont l'encadrement M1 < 10 centimes : %d / 120"
              % sum(1 for g in gains if g[2] < 10))
        prod = next(g for g in gains if g[0] == (2.0, 20.0))
        print("   geometrie de production TP2/SL20 : M5 %.2f c  ->  M1 %.2f c"
              % (prod[1], prod[2]))

    # La question de Xavier : faut-il un SL INFERIEUR au TP ?
    print()
    print("=" * 78)
    print("SL PLUS PETIT OU PLUS GRAND QUE LE TP ? -- l'arithmetique d'abord")
    print("=" * 78)
    print("Le spread est paye UNE fois par trade, quelles que soient les bornes.")
    print("Ce qu'il coute se lit donc en POINTS de taux de reussite :")
    print("   taxe = spread / (TP + SL)")
    print("%-14s%12s%12s%12s" % ("couple", "equitable", "requis", "taxe (pts)"))
    sp_usd = 0.05
    for tp_e, sl_e in ((5, 1), (5, 2), (5, 5), (5, 10), (5, 20),
                       (2, 20), (20, 2), (1, 1), (20, 20)):
        tp_u, sl_u = tp_e * EUR_USD, sl_e * EUR_USD
        eq = sl_u / (tp_u + sl_u)
        req = (sl_u + sp_usd) / (tp_u + sl_u)
        print("%-14s%11.2f%%%11.2f%%%12.3f"
              % ("TP%g/SL%g" % (tp_e, sl_e), 100 * eq, 100 * req,
                 100 * (req - eq)))

    for nom in ("M5", "M1"):
        if not res[nom]:
            continue
        print()
        print("=" * 78)
        print("%s -- DIRECTIONNEL hors echantillon, $/trade (convention stop)"
              % nom)
        print("=" * 78)
        print("TP/SL  " + "".join("%7.1f" % s for s in SLS))
        for tp_e in TPS:
            ligne = "%5.1f  " % tp_e
            for sl_e in SLS:
                ligne += "%7.3f" % res[nom][(tp_e, sl_e)]["sl"]["direct_hors"][0]
            print(ligne)
        sous = [res[nom][(tp, sl)]["sl"]["direct_hors"][0]
                for tp in TPS for sl in SLS if sl < tp]
        egal = [res[nom][(tp, sl)]["sl"]["direct_hors"][0]
                for tp in TPS for sl in SLS if sl == tp]
        sur = [res[nom][(tp, sl)]["sl"]["direct_hors"][0]
               for tp in TPS for sl in SLS if sl > tp]
        print("   SL < TP : %d couples, moyenne %+.4f $/trade, %d positifs"
              % (len(sous), st.fmean(sous), sum(1 for x in sous if x > 0)))
        print("   SL = TP : %d couples, moyenne %+.4f $/trade, %d positifs"
              % (len(egal), st.fmean(egal), sum(1 for x in egal if x > 0)))
        print("   SL > TP : %d couples, moyenne %+.4f $/trade, %d positifs"
              % (len(sur), st.fmean(sur), sum(1 for x in sur if x > 0)))

    for nom in ("M5", "M1"):
        if not res[nom]:
            continue
        print("\n" + "=" * 78)
        print("%s — LES 4 CRITERES PRE-INSCRITS, convention 'stop' puis 'tp'" % nom)
        print("=" * 78)
        for eg in ("sl", "tp"):
            classement = sorted(res[nom].items(),
                                key=lambda kv: -kv[1][eg]["direct_dans"][0])
            (tp_e, sl_e), v = classement[0]
            md = v[eg]["direct_dans"][0]
            mh, th, nh, jh = v[eg]["direct_hors"]
            crit = (mh > 0, abs(th) > PLAFOND_T, nh >= MIN_N, (md > 0) == (mh > 0))
            print("   convention %-3s  designe TP%g/SL%g : dedans %+.4f, "
                  "dehors %+.4f (t %+.2f, n %d, %d jours)  ⇒ %s"
                  % (eg, tp_e, sl_e, md, mh, th, nh, jh,
                     "RETENU" if all(crit) else "REJETE"))
            tous = 0
            for k, v2 in res[nom].items():
                m2 = v2[eg]["direct_dans"][0]
                mh2, th2, nh2, _ = v2[eg]["direct_hors"]
                if mh2 > 0 and abs(th2) > PLAFOND_T and nh2 >= MIN_N \
                        and (m2 > 0) == (mh2 > 0):
                    tous += 1
            print("        route interdite (les 120) : %d couples passent" % tous)
    return 0


if __name__ == "__main__":
    sys.exit(main())
