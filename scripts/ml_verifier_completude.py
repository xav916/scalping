"""Détecte et rebouche les trous de l'historique de bougies.

Posé le 2026-08-08 après avoir constaté que `ml_fetch_candles_5min.py` perdait
des fenêtres en silence. Deux causes successives, la seconde étant mon propre
correctif incomplet :

1. Sur `You have run out of API credits`, la version initiale faisait `break`
   et passait à la fenêtre suivante.
2. La version « corrigée » faisait `continue` — mais dans la boucle
   `for essai in range(3)`. Au **quatrième** épuisement, la fenêtre était
   perdue quand même.

⛔ **La leçon** : ne pas faire confiance au déroulement, **vérifier le
résultat**. Un jeu d'entraînement troué au hasard est pire qu'un jeu absent —
rien ne le signale ensuite, et le modèle apprend sur une histoire à trous.

Méthode : pour chaque (paire, mois), comparer le nombre de bougies au meilleur
observé ce mois-là toutes paires confondues. Sous 50 %, la cellule est
considérée trouée et re-téléchargée. On répète jusqu'à ce qu'un passage
n'apporte plus rien.

Usage :
    python scripts/ml_verifier_completude.py [--refill]
"""
import os
import sqlite3
import sys
import time

import httpx

KEY = os.environ["TWELVEDATA_API_KEY"]
DB = os.getenv("ML_CANDLES_DB", "/app/data/candles_5min.db")
API = "https://api.twelvedata.com/time_series"
PAUSE_SEC = float(os.getenv("ML_FETCH_PAUSE_SEC", "4.0"))
SEUIL = float(os.getenv("ML_GAP_RATIO", "0.5"))


def cellules_trouees(c: sqlite3.Connection) -> list[tuple[str, str]]:
    """(paire, mois) dont la couverture est sous SEUIL du meilleur du mois.

    La référence est le maximum observé ce mois-là, pas une constante : elle
    absorbe les jours fériés, les week-ends et les mois courts sans les
    signaler à tort.
    """
    import statistics

    par_paire: dict[str, dict[str, int]] = {}
    for pair, mois, n in c.execute(
        "SELECT pair, substr(ts,1,7), COUNT(*) FROM candles GROUP BY 1,2"
    ):
        par_paire.setdefault(pair, {})[mois] = n

    import datetime as _dt

    # Le mois COURANT est legitimement partiel : le signaler serait un faux
    # positif quotidien, et rebouché il reviendrait le lendemain.
    mois_courant = _dt.date.today().strftime("%Y-%m")
    filtre = [x.strip() for x in os.getenv("ML_FETCH_PAIRS", "").split(",") if x.strip()]
    tous_mois = sorted({m for d in par_paire.values() for m in d} - {mois_courant})
    trous = []
    for pair, d in par_paire.items():
        if len(d) < 3 or (filtre and pair not in filtre):
            continue
        # ⚠️ Reference = la MEDIANE DE LA PAIRE ELLE-MEME, jamais le meilleur
        # toutes paires confondues : une action cote 6 h 30 par jour, une paire
        # forex 24 h. Comparer entre elles signalait 306 faux trous, dont tous
        # les mois d'AAPL/MSFT/NVDA/TSLA. Chaque instrument est son propre etalon.
        ref = statistics.median(d.values())
        if ref <= 0:
            continue
        debut, fin = min(d), max(d)
        for m in tous_mois:
            if m < debut or m > fin:
                continue          # hors de la periode couverte : pas un trou
            if d.get(m, 0) < ref * SEUIL:
                trous.append((pair, m))
    return sorted(trous)


def recharge(c: sqlite3.Connection, pair: str, mois: str) -> int:
    """Re-télécharge un mois. Attente ILLIMITÉE sur quota — jamais d'abandon."""
    an, m = mois.split("-")
    d1 = f"{an}-{m}-01"
    d2 = f"{int(an)+1}-01-01" if m == "12" else f"{an}-{int(m)+1:02d}-01"
    attentes = 0
    while True:
        try:
            j = httpx.get(API, timeout=45, params={
                "symbol": pair, "interval": "5min", "start_date": d1,
                "end_date": d2, "outputsize": 5000, "apikey": KEY}).json()
        except Exception:  # noqa: BLE001
            time.sleep(5)
            continue
        msg = j.get("message", "") if j.get("status") == "error" else ""
        if "API credits" in msg:
            attentes += 1
            if attentes > 20:      # 20 min d'attente : le quota JOURNALIER est mort
                print(f"    {pair} {mois} : quota journalier probablement epuise")
                return -1
            time.sleep(62)
            continue
        if msg:
            return 0               # pas de donnee sur ces dates : legitime
        rows = [(pair, v["datetime"], float(v["open"]), float(v["high"]),
                 float(v["low"]), float(v["close"]))
                for v in (j.get("values") or [])]
        c.executemany("INSERT OR IGNORE INTO candles VALUES (?,?,?,?,?,?)", rows)
        c.commit()
        return len(rows)


def main(refill: bool) -> None:
    c = sqlite3.connect(DB)
    passage = 0
    while True:
        passage += 1
        trous = cellules_trouees(c)
        print(f"\n=== passage {passage} : {len(trous)} cellules trouees ===")
        if not trous:
            print("  historique complet")
            return
        for p, m in trous[:20]:
            print(f"    {p:10s} {m}")
        if len(trous) > 20:
            print(f"    ... et {len(trous)-20} autres")
        if not refill:
            print("\n  (lancer avec --refill pour reboucher)")
            return
        gagne = 0
        for pair, mois in trous:
            n = recharge(c, pair, mois)
            if n < 0:
                print("  arret : quota journalier epuise, relancer demain")
                return
            gagne += n
            time.sleep(PAUSE_SEC)
        print(f"  {gagne} bougies ajoutees")
        if gagne == 0:
            print("  aucun progres : ces cellules n'ont pas de donnee disponible")
            return


if __name__ == "__main__":
    main("--refill" in sys.argv)
