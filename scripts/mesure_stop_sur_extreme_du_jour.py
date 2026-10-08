#!/usr/bin/env python3
"""Un stop posé au-delà de l'extrême du JOUR : combien coûterait-il ?

Question de Xavier, 2026-10-08 : *« garder en mémoire le max et le min d'une
journée de trading sur l'or, les faire évoluer, et calculer un stop loss à
+5 du max ou du min selon buy ou sell. »*

## 🔑 LE PIÈGE DE MÉTHODE, avant tout chiffre

L'extrême utilisable est celui **atteint jusqu'à cet instant**, jamais celui de
la journée entière : un stop posé sous le plus bas du jour *complet* lirait le
futur, et toute mesure bâtie dessus serait fausse dans le sens flatteur. Ce
script accumule donc le haut et le bas **au fil des bougies**, et les remet à
zéro à chaque changement de date UTC.

## Ce qu'on mesure, et pourquoi ça suffit à décider

Pas une performance : la **TAILLE** du stop. Si la distance à l'extrême du jour
dépasse ce que les portes acceptent, la règle est injouable avant même de
parler de rendement. Et si elle varie de 5 à 80 $ selon l'heure, alors le
risque par trade n'est plus maîtrisé — ce qui est une décision en soi.

Trois bornes la jugent :

```
porte des frais        stop >= prix / 300          (13,74 $ a 4 123 $)
risque par trade       <= 5 % du solde             (33,37 EUR a 667,40)
plafond journalier     59,68 EUR, donc N pertes
```
"""
from __future__ import annotations

import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

PAIRE = "XAU/USD"
ARCHIVE = "/app/data/candles_5min.db"
DEBUT, FIN = "2025-08-08", "2026-08-08"      # la fenêtre figée des bancs

MARGE_USD = 5.0 * 1.1197        # « +5 » lu en EUROS, converti
TAUX = 1.1197
SOLDE = 667.40
PLAFOND_JOUR_EUR = 59.68
PLAFOND_PAR_TRADE_PCT = 5.0


def bougies():
    with sqlite3.connect(f"file:{Path(ARCHIVE)}?mode=ro", uri=True) as c:
        return c.execute(
            "SELECT ts, high, low, close FROM candles "
            "WHERE pair = ? AND ts >= ? AND ts < ? ORDER BY ts",
            (PAIRE, DEBUT, FIN)).fetchall()


def main() -> int:
    lignes = bougies()
    print("=== STOP AU-DELA DE L'EXTREME DU JOUR — ce que ca coute ===")
    print(f"    {PAIRE}, bougies du COURTIER, {DEBUT} -> {FIN}")
    print(f"    {len(lignes)} bougies 5 min")
    print(f"    marge « +5 » lue en EUROS : {MARGE_USD:.2f} $")
    if len(lignes) < 1000:
        print("    pas assez de bougies")
        return 1

    # 🔑 Extremes ACCUMULES au fil de la journee, remis a zero par date UTC.
    jour = None
    haut = bas = None
    d_buy, d_sell = [], []
    par_heure = defaultdict(list)
    for ts, h, lo, cl in lignes:
        s = str(ts)
        date, heure = s[:10], int(s[11:13])
        if date != jour:
            jour, haut, bas = date, float(h), float(lo)
        else:
            haut = max(haut, float(h))
            bas = min(bas, float(lo))
        prix = float(cl)
        # ACHAT : stop sous le bas du jour, moins la marge.
        db = prix - (bas - MARGE_USD)
        # VENTE : stop au-dessus du haut du jour, plus la marge.
        ds = (haut + MARGE_USD) - prix
        if db > 0:
            d_buy.append(db)
            par_heure[heure].append(db)
        if ds > 0:
            d_sell.append(ds)

    def bilan(nom, v):
        v = sorted(v)
        n = len(v)
        def q(p):
            return v[min(n - 1, int(p * n))]
        print("")
        print(f"    --- {nom} ({n} cas) ---")
        print(f"      distance du stop, en $ :")
        print(f"        p10 {q(0.10):6.2f}   p25 {q(0.25):6.2f}   "
              f"mediane {q(0.50):6.2f}   p75 {q(0.75):6.2f}   p90 {q(0.90):6.2f}")
        print(f"        moyenne {statistics.fmean(v):6.2f}   max {v[-1]:6.2f}")
        print(f"      le MEME, en euros :")
        print(f"        p10 {q(0.10)/TAUX:6.2f}   mediane {q(0.50)/TAUX:6.2f}   "
              f"p90 {q(0.90)/TAUX:6.2f}   max {v[-1]/TAUX:6.2f}")
        # ─── Les trois bornes ────────────────────────────────────────────
        plancher = 4123.0 / 300.0
        trop_serre = sum(1 for x in v if x < plancher) * 100.0 / n
        plafond_eur = SOLDE * PLAFOND_PAR_TRADE_PCT / 100.0
        trop_large = sum(1 for x in v if x / TAUX > plafond_eur) * 100.0 / n
        print(f"      porte des FRAIS (stop >= {plancher:.2f} $) : "
              f"{trop_serre:.1f} % REFUSES (trop serre)")
        print(f"      porte du RISQUE (<= {plafond_eur:.2f} EUR)  : "
              f"{trop_large:.1f} % REFUSES (trop large)")
        passe = 100.0 - trop_serre - trop_large
        print(f"      => environ {passe:.1f} % des cas passeraient les deux")
        med_eur = q(0.50) / TAUX
        print(f"      pertes avant le plafond journalier, au stop MEDIAN : "
              f"{PLAFOND_JOUR_EUR/med_eur:.1f}")
        print(f"      au stop p90                                      : "
              f"{PLAFOND_JOUR_EUR/(q(0.90)/TAUX):.1f}")
        # 🔑 Le rapport a la cible de 2 EUR : le seuil de rentabilite.
        for nom_q, val in (("mediane", q(0.50)), ("p90", q(0.90))):
            sl_eur = val / TAUX
            requis = sl_eur / (sl_eur + 2.0) * 100
            print(f"      cible de 2 EUR contre un stop {nom_q} de "
                  f"{sl_eur:.2f} EUR -> il faudrait {requis:.2f} % de reussite")

    bilan("ACHAT : stop sous le bas du jour", d_buy)
    bilan("VENTE : stop au-dessus du haut du jour", d_sell)

    print("")
    print("    --- variation selon l'HEURE (achat) ---")
    print("      🔑 C'est le point qui decide : un stop qui vaut 5 $ a"
          " l'ouverture")
    print("         et 60 $ en fin de journee n'est pas un risque maitrise.")
    print(f"      {'h UTC':>6s} {'n':>7s} {'mediane $':>10s} {'mediane EUR':>12s}")
    for h in sorted(par_heure):
        v = sorted(par_heure[h])
        if len(v) < 50:
            continue
        med = v[len(v) // 2]
        print(f"      {h:4d} h {len(v):7d} {med:10.2f} {med/TAUX:12.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
