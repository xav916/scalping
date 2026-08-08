"""Rejoue le détecteur de motifs sur l'historique et étiquette chaque setup.

Posé le 2026-08-08 pour la Phase 1 du chantier ML. Les trades réels ne
remontent qu'au 2026-05-18 (82 jours) — trop court pour une découpe
temporelle qui tranche. Le détecteur étant une fonction pure, on le rejoue sur
l'historique de bougies pour produire un jeu pluriannuel.

⚠️ **Déduplication horaire identique à `record_setups`** : sans elle, 39,5 %
des bougies produisent un setup, soit cinq fois le taux réel de production, et
surtout des setups **chevauchants** qui violeraient l'indépendance des
observations — exactement le biais que le contrôle aléatoire du 2026-08-05
cherchait à éviter.

⚠️ L'excursion est calculée **intra-bougie** (hauts/bas), fenêtre bornée au
premier stop ou objectif touché, timeout 96 h. C'est la cible retenue par la
spec : contrairement à la sélection, elle n'est pas invariante par bougie.
"""
import bisect
import datetime as dt
import os
import sqlite3
import sys
import time

from backend.models.schemas import Candle
from backend.services.pattern_detector import calculate_trade_setup, detect_patterns
from config.settings import CANDLE_COUNT

CANDLES_DB = os.getenv("ML_CANDLES_DB", "/app/data/candles_5min.db")
OUT_DB = os.getenv("ML_DATASET_DB", "/app/data/ml_dataset.db")
TIMEOUT_H = 96
DEDUP_SEC = 3600            # meme fenetre que `backtest_service.record_setups`


def _schema(c: sqlite3.Connection) -> None:
    c.execute("""CREATE TABLE IF NOT EXISTS setups (
        pair TEXT, ts TEXT, direction TEXT, pattern TEXT,
        entry REAL, sl REAL, tp1 REAL,
        pattern_confidence REAL, risk_pct REAL,
        mfe_pct REAL, mae_pct REAL, outcome TEXT,
        PRIMARY KEY (pair, ts, direction))""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_setups_ts ON setups(ts)")
    c.commit()


def _excursion(highs, lows, i, j, achat, e, sl, tp):
    """Excursions exactes + issue, fenetre bornee au premier stop/objectif."""
    best = pire = None
    issue = "TIMEOUT"
    for k in range(i, j):
        hi, lo = highs[k], lows[k]
        fav, adv = (hi, lo) if achat else (lo, hi)
        if best is None:
            best, pire = fav, adv
        elif achat:
            best, pire = max(best, fav), min(pire, adv)
        else:
            best, pire = min(best, fav), max(pire, adv)
        touche_sl = lo <= sl if achat else hi >= sl
        touche_tp = hi >= tp if achat else lo <= tp
        if touche_sl and touche_tp:
            issue = "SL"; break          # pire cas, comme simulate_trade_forward
        if touche_sl:
            issue = "SL"; break
        if touche_tp:
            issue = "TP"; break
    if best is None:
        return None
    mfe = (best - e) / e * 100 if achat else (e - best) / e * 100
    mae = (e - pire) / e * 100 if achat else (pire - e) / e * 100
    return max(mfe, 0.0), max(mae, 0.0), issue


def main(paires: list[str]) -> None:
    cd = sqlite3.connect(CANDLES_DB)
    out = sqlite3.connect(OUT_DB)
    _schema(out)

    for pair in paires:
        t0 = time.time()
        rows = list(cd.execute(
            "SELECT ts, open, high, low, close FROM candles WHERE pair=? ORDER BY ts",
            (pair,)))
        if len(rows) < CANDLE_COUNT + 10:
            print(f"  {pair:10s} trop peu de bougies ({len(rows)})")
            continue
        ts = [r[0].replace(" ", "T") for r in rows]
        highs = [r[2] for r in rows]
        lows = [r[3] for r in rows]
        bougies = [Candle(
            timestamp=dt.datetime.fromisoformat(t + "+00:00"),
            open=r[1], high=r[2], low=r[3], close=r[4], volume=0.0)
            for t, r in zip(ts, rows)]

        vus: dict[tuple, float] = {}
        lot = []
        for i in range(CANDLE_COUNT, len(bougies)):
            fen = bougies[i - CANDLE_COUNT:i]
            pats = detect_patterns(fen, pair)
            if not pats:
                continue
            s = calculate_trade_setup(pair, pats[0], fen)
            if not s or not s.entry_price or not s.stop_loss:
                continue
            sens = s.direction.value
            t_s = dt.datetime.fromisoformat(ts[i] + "+00:00").timestamp()
            cle = (sens, round(s.entry_price, 5))
            if cle in vus and t_s - vus[cle] < DEDUP_SEC:
                continue
            vus[cle] = t_s
            fin = (dt.datetime.fromisoformat(ts[i])
                   + dt.timedelta(hours=TIMEOUT_H)).isoformat()
            j = bisect.bisect_right(ts, fin)
            ex = _excursion(highs, lows, i, j, sens == "buy",
                            s.entry_price, s.stop_loss, s.take_profit_1)
            if ex is None:
                continue
            risque = abs(s.entry_price - s.stop_loss) / s.entry_price * 100
            lot.append((pair, ts[i], sens, pats[0].pattern.value,
                        s.entry_price, s.stop_loss, s.take_profit_1,
                        pats[0].confidence, risque, ex[0], ex[1], ex[2]))
        out.executemany(
            "INSERT OR IGNORE INTO setups VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", lot)
        out.commit()
        print(f"  {pair:10s} {len(rows):7d} bougies -> {len(lot):6d} setups "
              f"({time.time()-t0:.0f} s)")

    n = out.execute("SELECT COUNT(*) FROM setups").fetchone()[0]
    print(f"\n  TOTAL : {n} setups -> {OUT_DB}")


if __name__ == "__main__":
    p = os.getenv("ML_FETCH_PAIRS", "").strip()
    main([x.strip() for x in p.split(",") if x.strip()] or sys.argv[1:])
