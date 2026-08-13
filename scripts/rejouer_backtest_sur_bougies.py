"""Rejoue les issues de `backtest.db` sur les bougies 5 min.

POURQUOI
--------
`backtest_service.check_open_trades()` interroge le prix COURANT toutes les
~3 min et tranche avec `_evaluate(row, price)`. Il ne rejoue aucun chemin. Une
pointe qui perce le stop puis revient entre deux sondes est invisible : le
trade reste ouvert et peut ensuite atteindre son objectif.

Mesure du 2026-08-13 : 55 a 65 % des GAGNANTS enregistres avaient deja touche
leur stop. Le biais ne va que dans un sens — il gonfle.

CE QUE FAIT CE SCRIPT
---------------------
Pour chaque trade resolu, il rejoue les bougies depuis `emitted_at` et decide
l'issue sur le PREMIER niveau touche, comme le ferait un ordre reellement pose.

⚠️ NON DESTRUCTIF : ecrit dans une base separee (`rejeu_bougies.db`).
`backtest.db` n'est jamais modifiee — l'original garde sa valeur, il decrit
ce que le sondeur a vu.

CHOIX DE METHODE, ET POURQUOI
-----------------------------
1. ANCRE = bougie a t0, PAS `entry_price`. Les deux series ne coincident pas
   (ecart median 0,15 % du prix, jusqu'a +-10 R sur les stops serres). Seules
   les DISTANCES viennent du backtest ; tout le reste vit dans le referentiel
   des bougies. Melanger les deux fabriquerait du bruit de la taille du signal.

2. DEUX BORNES. Quand stop ET objectif tombent dans la meme bougie, l'ordre
   reel est inconnu (4 a 17 % des bougies selon la paire). On rend les deux
   lectures — pessimiste (stop d'abord) et optimiste (objectif d'abord) —
   plutot que d'en choisir une. Une conclusion ne vaut que si elle tient sous
   les deux.

3. TP2 N'EST PAS UNE SORTIE DISTINCTE. `take_profit_2` est plus loin que
   `take_profit_1` dans le meme sens : y arriver suppose d'avoir traverse TP1,
   ou un ordre est pose. Le sondeur enregistre `WIN_TP2` quand un prix
   echantillonne est deja au-dela — c'est l'artefact meme qu'on mesure. Le
   rejeu sort donc a TP1. Seul un GAP d'ouverture au-dela de TP2 justifie
   mieux, et il est compte a part.

Usage : python3 scripts/rejouer_backtest_sur_bougies.py [paire,paire] [--limite N]
"""
import bisect
import os
import sqlite3
import sys
from datetime import datetime, timedelta

BT = os.getenv("BACKTEST_DB", "/opt/scalping/data/backtest.db")
CA = os.getenv("CANDLES_DB", "/opt/scalping/data/candles_5min.db")
OUT = os.getenv("REJEU_DB", "/opt/scalping/data/rejeu_bougies.db")
HORIZON_H = 168                      # 7 jours : au-dela on marque NON_RESOLU
RESOLUS = ("LOSS", "WIN_TP1", "WIN_TP2")


def ouvrir_sortie():
    c = sqlite3.connect(OUT)
    c.executescript("""
        CREATE TABLE IF NOT EXISTS rejeu (
            trade_id INTEGER PRIMARY KEY,
            pair TEXT, direction TEXT, emitted_at TEXT,
            outcome_sonde TEXT, rr_sonde REAL,
            outcome_pess TEXT, rr_pess REAL,
            outcome_opt  TEXT, rr_opt  REAL,
            ambigu INTEGER,          -- stop ET objectif dans la meme bougie
            gap_au_dela_tp2 INTEGER, -- seul cas ou WIN_TP2 se justifie
            bougies INTEGER,         -- bougies parcourues avant sortie
            tronque INTEGER          -- serie de bougies epuisee avant l horizon
        );
        CREATE INDEX IF NOT EXISTS idx_rejeu_pair ON rejeu(pair);
    """)
    return c


def rejouer(hi, lo, op, i0, sl, tp1, tp2, sens, nbar, n):
    """Rend (issue_pess, r_pess, issue_opt, r_opt, ambigu, gap_tp2, bougies, tronque).

    R exprime en unites de risque : le stop vaut -1, l'objectif vaut sa
    distance rapportee au risque. Coherent avec `rr_realized`.
    """
    fin = min(i0 + nbar, n)
    tronque = 1 if i0 + nbar > n else 0
    d_sl = abs(sl)
    for i in range(i0, fin):
        # Gap d'ouverture : le prix ouvre deja au-dela d'un niveau.
        o = op[i]
        if sens > 0:
            gap_tp2 = o >= tp2
            gap_sl = o <= sl
        else:
            gap_tp2 = o <= tp2
            gap_sl = o >= sl
        if gap_sl:
            return ("LOSS", -1.0, "LOSS", -1.0, 0, 0, i - i0 + 1, tronque)
        if gap_tp2:
            r = abs(tp2) / d_sl if d_sl else 0.0
            return ("WIN_TP2", r, "WIN_TP2", r, 0, 1, i - i0 + 1, tronque)

        t_sl = lo[i] <= sl if sens > 0 else hi[i] >= sl
        t_tp = hi[i] >= tp1 if sens > 0 else lo[i] <= tp1
        r_tp = abs(tp1) / d_sl if d_sl else 0.0
        if t_sl and t_tp:
            return ("LOSS", -1.0, "WIN_TP1", r_tp, 1, 0, i - i0 + 1, tronque)
        if t_sl:
            return ("LOSS", -1.0, "LOSS", -1.0, 0, 0, i - i0 + 1, tronque)
        if t_tp:
            return ("WIN_TP1", r_tp, "WIN_TP1", r_tp, 0, 0, i - i0 + 1, tronque)
    return ("NON_RESOLU", 0.0, "NON_RESOLU", 0.0, 0, 0, fin - i0, tronque)


def main():
    paires_arg = None
    limite = None
    for a in sys.argv[1:]:
        if a.startswith("--limite"):
            limite = int(a.split("=")[1]) if "=" in a else None
        elif not a.startswith("--"):
            paires_arg = a.split(",")

    bt = sqlite3.connect(BT)
    ca = sqlite3.connect(CA)
    out = ouvrir_sortie()

    paires = paires_arg or [r[0] for r in bt.execute(
        "SELECT DISTINCT pair FROM trades WHERE outcome IN (?,?,?)", RESOLUS)]
    nbar = HORIZON_H * 12
    total = 0

    for p in sorted(paires):
        rows = ca.execute(
            "SELECT ts, open, high, low FROM candles WHERE pair=? ORDER BY ts",
            (p,)).fetchall()
        if not rows:
            print("  %-9s aucune bougie, ignore" % p)
            continue
        ts = [r[0] for r in rows]
        op = [r[1] for r in rows]
        hi = [r[2] for r in rows]
        lo = [r[3] for r in rows]
        n = len(ts)

        q = ("SELECT id, direction, entry_price, stop_loss, take_profit_1, "
             "       take_profit_2, outcome, rr_realized, emitted_at "
             "  FROM trades WHERE pair=? AND outcome IN (?,?,?) "
             "   AND ABS(entry_price-stop_loss) > 0")
        params = [p, *RESOLUS]
        if limite:
            q += " LIMIT ?"
            params.append(limite)

        lot, k = [], 0
        for (tid, d, e, sl, tp1, tp2, oc, rr, em) in bt.execute(q, params):
            t0 = datetime.fromisoformat(em).replace(tzinfo=None)
            i0 = bisect.bisect_left(ts, t0.strftime("%Y-%m-%d %H:%M:%S"))
            if i0 >= n - 1:
                continue
            sens = 1 if str(d).lower().startswith("b") else -1
            ancre = (hi[i0] + lo[i0]) / 2.0
            risque = abs(e - sl)
            # niveaux replaces dans le referentiel des bougies
            n_sl = ancre - sens * risque
            n_tp1 = ancre + sens * abs(tp1 - e)
            n_tp2 = ancre + sens * abs(tp2 - e)
            (op_, rp, oo, ro, amb, gap, nb, tr) = rejouer(
                hi, lo, op, i0 + 1,
                n_sl, n_tp1, n_tp2, sens, nbar, n)
            # les R sont rendus en unites de risque : on renormalise
            rp = -1.0 if op_ == "LOSS" else (0.0 if op_ == "NON_RESOLU" else
                                             abs(n_tp1 - ancre) / risque if op_ == "WIN_TP1"
                                             else abs(n_tp2 - ancre) / risque)
            ro = -1.0 if oo == "LOSS" else (0.0 if oo == "NON_RESOLU" else
                                            abs(n_tp1 - ancre) / risque if oo == "WIN_TP1"
                                            else abs(n_tp2 - ancre) / risque)
            lot.append((tid, p, d, em, oc, rr, op_, rp, oo, ro, amb, gap, nb, tr))
            k += 1
            if len(lot) >= 5000:
                out.executemany("INSERT OR REPLACE INTO rejeu VALUES "
                                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", lot)
                out.commit(); lot = []
        if lot:
            out.executemany("INSERT OR REPLACE INTO rejeu VALUES "
                            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", lot)
            out.commit()
        total += k
        print("  %-9s %6d trades rejoues" % (p, k), flush=True)

    print("TERMINE : %d trades ecrits dans %s" % (total, OUT))


if __name__ == "__main__":
    main()
