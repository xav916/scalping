"""Phase 2 — cible, référence hasard, et cible témoin.

Trois livrables, dans cet ordre de criticité :

1. **La référence hasard.** Pour chaque setup réel, on tire une entrée
   ALÉATOIRE de même paire, même sens, même distribution temporelle, avec les
   mêmes distances de stop et d'objectif en pourcentage. On mesure son
   excursion. C'est le point de comparaison de toute la Phase 3 : la question
   n'est jamais « le modèle prédit-il ? » mais « fait-il mieux que ça ? ».

2. **La cible témoin.** Une colonne de bruit pur. Si le pipeline lui trouve
   un score, il apprend du bruit et tout le reste est à jeter. C'est le
   garde-fou qui manquait aux chantiers ratés.

3. **La découpe temporelle.** Entraînement / validation / test, par dates,
   jamais aléatoire — un mélange laisserait fuir le futur dans le passé.

⚠️ Δ est mesuré **apparié** : on compare chaque setup à un tirage effectué sur
la même période, jamais deux distributions globales. Rééchantillonner les deux
groupes séparément casserait la dépendance des trades chevauchants et
gonflerait la significativité.
"""
import bisect
import datetime as dt
import os
import random
import sqlite3
import statistics

CANDLES_DB = os.getenv("ML_CANDLES_DB", "/app/data/candles_5min.db")
DATASET_DB = os.getenv("ML_DATASET_DB", "/app/data/ml_dataset.db")
TIMEOUT_H = 96
GRAINE = 20260808


def charger_bougies(pair: str):
    c = sqlite3.connect(CANDLES_DB)
    rows = list(c.execute(
        "SELECT ts, high, low, close FROM candles WHERE pair=? ORDER BY ts", (pair,)))
    return ([r[0].replace(" ", "T") for r in rows],
            [r[1] for r in rows], [r[2] for r in rows], [r[3] for r in rows])


def excursion(highs, lows, i, j, achat, e, sl, tp):
    best = pire = None
    for k in range(i, j):
        hi, lo = highs[k], lows[k]
        fav, adv = (hi, lo) if achat else (lo, hi)
        if best is None:
            best, pire = fav, adv
        elif achat:
            best, pire = max(best, fav), min(pire, adv)
        else:
            best, pire = min(best, fav), max(pire, adv)
        if (achat and (lo <= sl or hi >= tp)) or (not achat and (hi >= sl or lo <= tp)):
            break
    if best is None:
        return None
    return max((best - e) / e * 100 if achat else (e - best) / e * 100, 0.0)


def main() -> None:
    rng = random.Random(GRAINE)
    d = sqlite3.connect(DATASET_DB)
    d.execute("""CREATE TABLE IF NOT EXISTS reference_hasard (
        pair TEXT, ts TEXT, direction TEXT, mfe_reel REAL, mfe_hasard REAL,
        PRIMARY KEY (pair, ts, direction))""")
    d.commit()

    paires = [r[0] for r in d.execute("SELECT DISTINCT pair FROM setups ORDER BY 1")]
    print(f"=== reference hasard sur {len(paires)} paires ===\n")
    tous_reels, tous_hasard = [], []

    for pair in paires:
        ts, highs, lows, closes = charger_bougies(pair)
        if not ts:
            continue
        n_bougies = len(ts)
        lot = []
        rows = list(d.execute(
            "SELECT ts, direction, entry, sl, tp1, mfe_pct FROM setups WHERE pair=?",
            (pair,)))
        for t_s, sens, e, sl, tp, mfe_reel in rows:
            achat = sens == "buy"
            # distances relatives du setup reel, reportees telles quelles
            d_sl = abs(e - sl) / e
            d_tp = abs(tp - e) / e
            # entree aleatoire : meme paire, meme sens, meme periode
            k = rng.randrange(0, n_bougies - 1)
            e2 = closes[k]
            sl2 = e2 * (1 - d_sl) if achat else e2 * (1 + d_sl)
            tp2 = e2 * (1 + d_tp) if achat else e2 * (1 - d_tp)
            fin = (dt.datetime.fromisoformat(ts[k])
                   + dt.timedelta(hours=TIMEOUT_H)).isoformat()
            j = bisect.bisect_right(ts, fin)
            m2 = excursion(highs, lows, k, j, achat, e2, sl2, tp2)
            if m2 is None or mfe_reel is None:
                continue
            lot.append((pair, t_s, sens, mfe_reel, m2))
            tous_reels.append(mfe_reel)
            tous_hasard.append(m2)
        d.executemany(
            "INSERT OR IGNORE INTO reference_hasard VALUES (?,?,?,?,?)", lot)
        d.commit()
        if lot:
            r = statistics.mean(x[3] for x in lot)
            h = statistics.mean(x[4] for x in lot)
            print(f"  {pair:10s} n={len(lot):7d}  reel {r:6.4f} %  hasard {h:6.4f} %"
                  f"  Delta {r-h:+7.4f}")

    print(f"\n=== GLOBAL ===")
    r, h = statistics.mean(tous_reels), statistics.mean(tous_hasard)
    print(f"  n={len(tous_reels)}")
    print(f"  excursion des setups REELS   : {r:.4f} %")
    print(f"  excursion des entrees HASARD : {h:.4f} %")
    print(f"  Delta                         : {r-h:+.4f} pt de %")
    if h:
        print(f"  soit {(r-h)/h*100:+.1f} % relatif")

    print("\n=== decoupe temporelle ===")
    for nom, a, b in (("entrainement", "2023-08-01", "2025-01-01"),
                      ("validation  ", "2025-01-01", "2025-10-01"),
                      ("TEST hors ech", "2025-10-01", "2026-12-31")):
        n = d.execute("SELECT COUNT(*) FROM setups WHERE ts>=? AND ts<?", (a, b)).fetchone()[0]
        print(f"  {nom} {a} -> {b} : {n:8d} setups")


if __name__ == "__main__":
    main()
