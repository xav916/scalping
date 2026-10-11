#!/usr/bin/env python3
"""La bougie SUIVANTE va-t-elle dans le sens du motif ?

Question de Xavier (2026-10-11), dans ses mots : "si on observe les bougies
d'une minute et que la on detecte un des patterns, on peut ensuite donner le
sens de la bougie suivante qui va suivre le pattern, non ?"

Le banc repond exactement a ca, et sur N'IMPORTE QUELLE echelle : on detecte a
la cloture d'une bougie, puis on regarde le signe de `close - open` de la
bougie SUIVANTE.

    MAGASIN=/app/data/candles_courtier.db  (M5, defaut)
    MAGASIN=/app/data/candles_courtier_m1.db  ECHELLE=M1

## Le controle, et pourquoi il est indispensable

Un taux de reussite brut ne veut rien dire si le marche a derive : sur une
periode haussiere, tout motif "up" gagne sans rien prevoir. On publie donc :

1. le taux dans le sens du motif ;
2. le TAUX DE BASE des memes bougies (part des bougies suivantes qui montent) ;
3. un plafond par PERMUTATION, apparie sur l'heure UTC : on retire les
   detections au hasard parmi les bougies de la MEME heure, 200 fois, et on
   garde le 95e centile du max |z|. Une cellule ne compte que si elle le passe.
"""
from __future__ import annotations

import collections
import datetime as dt
import math
import os
import random
import sqlite3
import statistics as st
import sys

sys.path.insert(0, "/app")

from backend.models.schemas import Candle  # noqa: E402
from backend.services.pattern_detector import (  # noqa: E402
    _est_un_achat, detect_patterns)

MAGASIN = os.getenv("MAGASIN", "/app/data/candles_courtier.db")
ECHELLE = os.getenv("ECHELLE", "M5")
PAIRE = os.getenv("PAIRE", "XAU/USD")
FENETRE = int(os.getenv("FENETRE", "50"))     # CANDLE_COUNT de la production
MAX_BOUGIES = int(os.getenv("MAX_BOUGIES", "0"))   # 0 = tout le magasin
N_PLACEBO = int(os.getenv("N_PLACEBO", "200"))
MIN_N = int(os.getenv("MIN_N", "300"))
SEED = 20261011


def charger():
    c = sqlite3.connect(MAGASIN)
    rows = c.execute(
        "SELECT ts_utc, open, high, low, close, tick_volume FROM candles "
        "WHERE pair = ? ORDER BY ts_utc", (PAIRE,)).fetchall()
    if MAX_BOUGIES:
        rows = rows[-MAX_BOUGIES:]
    out = []
    for t, o, h, l, cl, tv in rows:
        d = dt.datetime.fromisoformat(t)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        out.append(Candle(timestamp=d.astimezone(dt.timezone.utc), open=o,
                          high=h, low=l, close=cl, volume=tv or 0))
    return out


def z_binomial(succes, n, p0):
    if n == 0 or p0 <= 0 or p0 >= 1:
        return 0.0
    return (succes / n - p0) / math.sqrt(p0 * (1 - p0) / n)


def main():
    rng = random.Random(SEED)
    cs = charger()
    print("magasin : %s   echelle %s   %d bougies   %s -> %s"
          % (MAGASIN, ECHELLE, len(cs), cs[0].timestamp, cs[-1].timestamp))
    print("fenetre de detection : %d bougies (CANDLE_COUNT de la production)"
          % FENETRE)

    # signe du mouvement de CHAQUE bougie : sert aux detections ET au placebo
    monte = [None] * len(cs)
    for i in range(1, len(cs)):
        monte[i] = cs[i].close > cs[i].open
    base_up = st.fmean([1.0 if m else 0.0 for m in monte[1:]])
    print("taux de base : %.2f %% des bougies montent (close > open)"
          % (100 * base_up))

    detections = collections.defaultdict(list)   # motif -> [(i_entree, achat)]
    for i in range(FENETRE - 1, len(cs) - 1):
        for p in detect_patterns(cs[i - FENETRE + 1:i + 1]):
            detections[p.pattern.value].append((i + 1, _est_un_achat(p.pattern)))
    n_tot = sum(len(v) for v in detections.values())
    print("detections : %d sur %d fenetres, %d motifs distincts"
          % (n_tot, len(cs) - FENETRE, len(detections)))

    def taux(items):
        ok = sum(1 for j, achat in items if monte[j] is (True if achat else False))
        return ok, len(items)

    globaux = taux([x for v in detections.values() for x in v])
    print("\n=== LA REPONSE ===")
    print("bougie suivante dans le sens du motif : %.2f %%  (n = %d)"
          % (100 * globaux[0] / max(1, globaux[1]), globaux[1]))

    lignes = []
    for m, v in detections.items():
        if len(v) < MIN_N:
            continue
        ok, n = taux(v)
        achats = sum(1 for _, a in v if a)
        p0 = (achats * base_up + (n - achats) * (1 - base_up)) / n
        lignes.append((m, n, 100 * ok / n, 100 * p0, z_binomial(ok, n, p0)))
    lignes.sort(key=lambda x: -x[2])
    print("\n%-22s%8s%10s%10s%9s" % ("motif", "n", "reussite", "base", "z"))
    for m, n, r, p0, z in lignes:
        print("%-22s%8d%9.2f%%%9.2f%%%+9.2f" % (m, n, r, p0, z))

    # --- plafond par permutation, apparie sur l'heure UTC ---
    par_heure = collections.defaultdict(list)
    for i in range(1, len(cs)):
        par_heure[cs[i].timestamp.hour].append(i)
    maxima = []
    for k in range(N_PLACEBO):
        mx = 0.0
        for m, v in detections.items():
            if len(v) < MIN_N:
                continue
            ok = 0
            achats = 0
            for j, achat in v:
                pool = par_heure[cs[j].timestamp.hour]
                jj = rng.choice(pool)
                achats += int(achat)
                if monte[jj] is (True if achat else False):
                    ok += 1
            n = len(v)
            p0 = (achats * base_up + (n - achats) * (1 - base_up)) / n
            mx = max(mx, abs(z_binomial(ok, n, p0)))
        maxima.append(mx)
        if (k + 1) % 50 == 0:
            print("  placebo %d/%d..." % (k + 1, N_PLACEBO), flush=True)
    maxima.sort()
    plafond = maxima[int(0.95 * len(maxima)) - 1]
    print("\nPLAFOND (95e centile du max|z| sur %d permutations appariees "
          "sur l'heure) : %.3f" % (N_PLACEBO, plafond))
    retenus = [x for x in lignes if abs(x[4]) > plafond]
    print("motifs qui le franchissent : %d / %d" % (len(retenus), len(lignes)))
    for m, n, r, p0, z in retenus:
        print("  %s : n=%d reussite=%.2f %% base=%.2f %% z=%+.2f"
              % (m, n, r, p0, z))
    return 0


if __name__ == "__main__":
    sys.exit(main())
