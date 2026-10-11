#!/usr/bin/env python3
"""Vendredi 09/10 : un trade qui COMMENCE en negatif finit-il au stop ?

Question de Xavier le 2026-10-11 : "est-ce qu'on peut refaire un backtest sur
la journee de vendredi, a savoir tester les trades qui ont ete lances et voir
si le trade lance qui a commence en negatif a fini par un SL".

## Pourquoi ce script ne fait PAS confiance au magasin

Les deux magasins batis le 10/10 s'arretent ~1 jour avant la fin reelle des
donnees, et le champ de decalage du pont a derive de 31 minutes entre ce matin
et maintenant. On ne corrige donc RIEN a l'aveugle : on demande les bougies
M1 BRUTES au pont du reel, puis on CHOISIT le decalage entier qui fait tomber
le plus de prix d'execution de la journee DANS leur bougie.

🔑 Les 82 trades de vendredi portent chacun un `fill_price` : ils sont leur
propre etalonnage. C'est plus solide qu'une formule, et ca se verifie.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import math
import os
import sqlite3
import statistics as st
import sys
import urllib.parse
import urllib.request

JOUR = os.getenv("JOUR", "2026-10-09")
OFFSETS_MIN = (1, 3, 5, 10)      # a quels instants on juge "commence negatif"
BASE = os.environ["MT5_BRIDGE_LIVE_URL"].rstrip("/")
CLE = os.environ["MT5_BRIDGE_LIVE_API_KEY"]


def bougies_brutes(debut, fin):
    q = urllib.parse.urlencode({"pair": "XAU/USD", "timeframe": "M1",
                                "from": debut, "to": fin})
    rq = urllib.request.Request(BASE + "/rates?" + q, headers={"X-API-Key": CLE})
    o = json.loads(urllib.request.urlopen(rq, timeout=120).read())
    ds = o.get("decalage_serveur_sec")
    # 🔑 LA FENETRE DU PONT EST EN ETIQUETTES BRUTES, pas en temps reel : c'est
    # pour ca que mes deux magasins s'arretaient un jour trop tot. On demande
    # donc large, on corrige avec le champ DE CETTE REPONSE, puis on filtre.
    if ds is None:
        dec = dt.timedelta(0)
    else:
        dec = dt.timedelta(minutes=int(round(-float(ds) / 60.0 + 180)))
    out = {}
    for b in o["bougies"]:
        # ⛔ Cles NAIVES : melanger un horodatage avec fuseau et un sans rend
        # toutes les recherches muettes, sans erreur. C'est ce qui a fait dire
        # a ce script << aucun decalage ne marche >> alors que la donnee etait
        # bonne.
        t = (dt.datetime.fromisoformat(b["t"]).replace(second=0, microsecond=0,
                                                       tzinfo=None) - dec)
        out[t] = (b["o"], b["h"], b["l"], b["c"])
    return out, ds, dec


def trades_du_jour():
    c = sqlite3.connect("/app/data/trades.db")
    rows = c.execute(
        "SELECT id, mt5_ticket, direction, fill_price, entry_price, stop_loss, "
        "take_profit, status, pnl, close_reason, created_at, closed_at, is_auto "
        "FROM personal_trades WHERE pair = 'XAU/USD' "
        "AND substr(created_at, 1, 10) = ? ORDER BY created_at", (JOUR,)
    ).fetchall()
    out = []
    for r in rows:
        t = dt.datetime.fromisoformat(r[10])
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        prix = r[3] or r[4]
        if not prix:
            continue
        out.append({
            "id": r[0], "ticket": r[1], "sens": r[2], "prix": prix,
            "sl": r[5], "tp": r[6], "statut": r[7], "pnl": r[8],
            "motif": r[9] or "", "ouvert": t.astimezone(dt.timezone.utc),
            "ferme": r[11], "auto": r[12],
        })
    return out


def main():
    trades = trades_du_jour()
    print("trades XAU du %s : %d  (auto %d, a la main %d)"
          % (JOUR, len(trades), sum(1 for t in trades if t["auto"]),
             sum(1 for t in trades if not t["auto"])))
    if not trades:
        return 1
    print("motifs de cloture :",
          dict(collections.Counter(t["motif"] for t in trades)))

    j0 = dt.datetime.fromisoformat(JOUR).replace(tzinfo=dt.timezone.utc)
    # fenetre BRUTE large : le decalage vaut ~+36 h, on couvre donc genereusement
    bg, champ, dec = bougies_brutes((j0 + dt.timedelta(hours=12)).isoformat(),
                                    (j0 + dt.timedelta(days=3)).isoformat())
    print("bougies M1 corrigees : %d   %s -> %s"
          % (len(bg), min(bg), max(bg)))
    print("champ de decalage = %s  ⇒  correction appliquee %+.0f min"
          % (champ, dec.total_seconds() / 60))

    # 🔑 ETALONNAGE : le decalage qui met le plus de fill_price dans sa bougie
    scores = {}
    for s in range(-3000, 3001):
        ok = 0
        for t in trades:
            b = bg.get(t["ouvert"].replace(tzinfo=None, second=0, microsecond=0)
                       + dt.timedelta(minutes=s))
            if b and b[2] <= t["prix"] <= b[1]:
                ok += 1
        if ok:
            scores[s] = ok
    if not scores:
        print("⛔ AUCUN decalage ne fait tomber un seul prix dans sa bougie")
        return 1
    meilleur = max(scores, key=lambda k: scores[k])
    print("decalage RETENU : %+d min  -> %d/%d prix d'execution dans leur "
          "bougie" % (meilleur, scores[meilleur], len(trades)))
    classement = sorted(scores.items(), key=lambda kv: -kv[1])[:4]
    print("   suivants : %s" % ", ".join("%+d (%d)" % kv for kv in classement[1:]))
    if abs(meilleur) > 2:
        print("   ⛔ le decalage residuel depasse 2 min : la correction du pont "
              "ne suffit pas, resultats a lire avec prudence")

    def prix_a(t, minutes):
        b = bg.get(t["ouvert"].replace(tzinfo=None, second=0, microsecond=0)
                   + dt.timedelta(minutes=meilleur + minutes))
        return b[3] if b else None

    print("\n=== LA QUESTION : commencer en negatif annonce-t-il le stop ? ===")
    for off in OFFSETS_MIN:
        table = collections.Counter()
        gains = {"negatif": [], "positif": []}
        for t in trades:
            p = prix_a(t, off)
            if p is None:
                continue
            ecart = (p - t["prix"]) if t["sens"] == "buy" else (t["prix"] - p)
            etat = "negatif" if ecart < 0 else "positif"
            stop = t["motif"].upper() == "SL"
            table[(etat, stop)] += 1
            if t["pnl"] is not None:
                gains[etat].append(t["pnl"])
        n_neg = table[("negatif", True)] + table[("negatif", False)]
        n_pos = table[("positif", True)] + table[("positif", False)]
        if not n_neg or not n_pos:
            print("+%2d min : donnees insuffisantes (neg %d, pos %d)"
                  % (off, n_neg, n_pos))
            continue
        p_neg = table[("negatif", True)] / n_neg
        p_pos = table[("positif", True)] / n_pos
        pool = (table[("negatif", True)] + table[("positif", True)]) / (n_neg + n_pos)
        se = math.sqrt(pool * (1 - pool) * (1 / n_neg + 1 / n_pos))
        z = (p_neg - p_pos) / se if se else 0.0
        print("+%2d min : negatif n=%-3d  %.1f %% finissent au SL   |   "
              "positif n=%-3d  %.1f %%   |   z = %+.2f"
              % (off, n_neg, 100 * p_neg, n_pos, 100 * p_pos, z))
        if gains["negatif"] and gains["positif"]:
            print("          P&L moyen : negatif %+.2f EUR (n=%d)   "
                  "positif %+.2f EUR (n=%d)"
                  % (st.fmean(gains["negatif"]), len(gains["negatif"]),
                     st.fmean(gains["positif"]), len(gains["positif"])))

    print("\n=== DETAIL DES TRADES FERMES AU STOP ===")
    for t in trades:
        if t["motif"].upper() != "SL":
            continue
        p1, p5 = prix_a(t, 1), prix_a(t, 5)
        def e(p):
            if p is None:
                return float("nan")
            return (p - t["prix"]) if t["sens"] == "buy" else (t["prix"] - p)
        print("   %s %-4s entree %.2f  a +1min %+.2f $  a +5min %+.2f $  "
              "pnl %+.2f EUR  %s"
              % (t["ouvert"].strftime("%H:%M"), t["sens"], t["prix"],
                 e(p1), e(p5), t["pnl"] or 0.0,
                 "auto" if t["auto"] else "a la main"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
