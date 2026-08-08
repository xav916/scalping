"""Récupère l'historique 5 min de Twelve Data et le stocke localement.

Posé le 2026-08-08 pour la Phase 1 du chantier ML, après avoir découvert que
la limite d'historique que je croyais imposée par l'API venait en réalité du
`outputsize=1500` codé dans `shadow_reconciliation`. **Avec `start_date` /
`end_date`, l'historique 5 min remonte bien au-delà de 5 jours.**

Profondeur constatée le 2026-08-08 (plan Grow) :

    5min    accessible par fenêtres de dates, 5 000 bougies par requête
    1h      jusqu'à janvier 2026
    4h      jusqu'à août 2023
    1day    jusqu'à 2007

⚠️ Limite de 55 requêtes/minute : une pause de 1,2 s sépare les appels. Le
passage complet (20 paires × 82 jours) a coûté **150 requêtes** pour
**486 251 bougies** — négligeable contre le quota quotidien de 5 000.

Usage :
    python scripts/ml_fetch_candles_5min.py [debut] [fin]
"""
import datetime as dt
import os
import sqlite3
import sys
import time

import httpx

KEY = os.environ["TWELVEDATA_API_KEY"]
DB = os.getenv("ML_CANDLES_DB", "/app/data/candles_5min.db")
API = "https://api.twelvedata.com/time_series"


def fenetres(debut: str, fin: str, jours: int = 14):
    """Découpe en fenêtres : 14 jours de 5 min ≈ 4 000 bougies, sous la limite."""
    d, f = dt.date.fromisoformat(debut), dt.date.fromisoformat(fin)
    while d < f:
        e = min(d + dt.timedelta(days=jours), f)
        yield d.isoformat(), e.isoformat()
        d = e


def paires_a_couvrir(backtest_db: str = "/app/data/backtest.db") -> list[str]:
    """Les paires réellement tradées, les plus fournies d'abord."""
    c = sqlite3.connect(backtest_db)
    return [r[0] for r in c.execute(
        "SELECT pair, COUNT(*) n FROM trades WHERE outcome IS NOT NULL "
        "GROUP BY 1 ORDER BY n DESC")]


def main(debut: str, fin: str) -> None:
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS candles (
        pair TEXT, ts TEXT, open REAL, high REAL, low REAL, close REAL,
        PRIMARY KEY (pair, ts))""")
    c.commit()

    total = req = 0
    for p in paires_a_couvrir():
        n_p = 0
        for d1, d2 in fenetres(debut, fin):
            for essai in range(3):
                try:
                    r = httpx.get(API, timeout=45, params={
                        "symbol": p, "interval": "5min",
                        "start_date": d1, "end_date": d2,
                        "outputsize": 5000, "apikey": KEY})
                    j = r.json()
                    req += 1
                    if j.get("status") == "error":
                        print(f"  {p} {d1} : {j.get('message', '')[:70]}")
                        break
                    rows = [(p, v["datetime"], float(v["open"]), float(v["high"]),
                             float(v["low"]), float(v["close"]))
                            for v in (j.get("values") or [])]
                    c.executemany(
                        "INSERT OR IGNORE INTO candles VALUES (?,?,?,?,?,?)", rows)
                    c.commit()
                    n_p += len(rows)
                    break
                except Exception as e:  # noqa: BLE001
                    if essai == 2:
                        print(f"  {p} {d1} : {type(e).__name__}")
                    time.sleep(3)
            time.sleep(1.2)  # 55 req/min
        total += n_p
        print(f"  {p:10s} {n_p:7d} bougies")
    print(f"\n{total} bougies, {req} requetes -> {DB}")


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "2026-05-18"
    b = sys.argv[2] if len(sys.argv) > 2 else dt.date.today().isoformat()
    main(a, b)
