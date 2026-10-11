#!/usr/bin/env python3
"""BATIR un magasin de TICKS de l'or depuis le pont, en UTC vrai.

Demande de Xavier le 2026-10-11 : « je veux que tu analyses le cours reel du
trade a l'aide de MetaTrader 5 et non les bougies ».

🔑 CE QUE LES TICKS CHANGENT, et ce n'est pas un detail :

1. **l'ORDRE des evenements dans la minute est connu** — plus besoin de la
   convention « une bougie qui contient les deux bornes compte comme un stop »,
   qui valait a elle seule un encadrement de **0,225 EUR/trade** ;
2. **le SPREAD est dans la donnee** : un achat entre a l'`ask` et sort au
   `bid`. Plus besoin de le modeliser ;
3. **la cadence reelle est simulable** : 2,7 ticks par seconde sur l'or, donc
   un trainage sonde a la seconde se rejoue vraiment.

⚠️ La fenetre `from`/`to` du pont est en ETIQUETTES BRUTES, comme `/rates`. On
corrige avec `decalage_serveur_sec` DE LA MEME REPONSE, jamais memorise d'un
appel a l'autre : le champ derive de dizaines de minutes par heure.

Verification faite avant d'ecrire ce fichier : la fenetre corrigee tombe
exactement sur celle demandee, et le prix d'execution reel du 09/10 a 08h20
(4 200,22 a l'achat) tombe dans la plage des bids de cette minute.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

PAIRE = "XAU/USD"
CIBLE = os.getenv("TICKS_CIBLE", "/app/data/ticks_courtier.db")
DEBUT = dt.datetime.fromisoformat(os.getenv("TICKS_DEBUT", "2026-10-07T00:00:00"))
FIN = dt.datetime.fromisoformat(os.getenv("TICKS_FIN", "2026-10-09T21:00:00"))
PAS_MIN = int(os.getenv("TICKS_PAS_MIN", "30"))     # taille d'une tranche
PAUSE = 0.2

base = os.environ["MT5_BRIDGE_LIVE_URL"].rstrip("/")
cle = os.environ["MT5_BRIDGE_LIVE_API_KEY"]

db = sqlite3.connect(CIBLE)
db.execute("""CREATE TABLE IF NOT EXISTS ticks (
    pair TEXT NOT NULL, ts_utc TEXT NOT NULL, ms INTEGER,
    bid REAL, ask REAL,
    PRIMARY KEY (pair, ts_utc, ms))""")
db.execute("CREATE INDEX IF NOT EXISTS idx_t ON ticks(pair, ts_utc)")
db.execute("""CREATE TABLE IF NOT EXISTS provenance (
    cle TEXT PRIMARY KEY, valeur TEXT)""")
db.executemany("INSERT OR REPLACE INTO provenance VALUES (?,?)", [
    ("source", "pont MT5 IC Markets route /ticks, PAS Twelve Data"),
    ("fuseau", "UTC vrai, corrige par -decalage_serveur_sec/60 + 180"),
    ("ancre_verifiee", "fill 09/10 08:20:21 a 4200.22 dans la plage des bids"),
    ("bati_le", "2026-10-11"),
])
db.commit()


def tranche(debut_reel: dt.datetime, fin_reel: dt.datetime):
    """Rend les ticks d'une tranche REELLE, deja corriges."""
    # 1er appel : on apprend le decalage du moment
    q = urllib.parse.urlencode({"pair": PAIRE, "from": debut_reel.isoformat(),
                                "to": fin_reel.isoformat(), "resume": 1})
    rq = urllib.request.Request(base + "/ticks?" + q, headers={"X-API-Key": cle})
    o = json.loads(urllib.request.urlopen(rq, timeout=180).read())
    ds = o.get("decalage_serveur_sec")
    if ds is None:
        return [], None
    dec = dt.timedelta(minutes=int(round(-float(ds) / 60.0 + 180)))
    # 2e appel : la fenetre BRUTE qui correspond a la fenetre reelle voulue
    q2 = urllib.parse.urlencode({"pair": PAIRE,
                                 "from": (debut_reel + dec).isoformat(),
                                 "to": (fin_reel + dec).isoformat()})
    rq2 = urllib.request.Request(base + "/ticks?" + q2,
                                 headers={"X-API-Key": cle})
    o2 = json.loads(urllib.request.urlopen(rq2, timeout=180).read())
    ds2 = o2.get("decalage_serveur_sec")
    if ds2 is None:
        return [], None
    # 🔑 le decalage de CETTE reponse, pas celui du premier appel
    dec2 = dt.timedelta(minutes=int(round(-float(ds2) / 60.0 + 180)))
    lot = o2.get("ticks") or []
    rows = []
    for t in lot:
        brut = dt.datetime.fromisoformat(t["t"])
        if brut.tzinfo:
            brut = brut.replace(tzinfo=None)
        vrai = brut - dec2
        rows.append((PAIRE, vrai.isoformat(), int(t.get("ms") or 0),
                     float(t["bid"]), float(t["ask"])))
    return rows, dec2


def main():
    print("cible : %s" % CIBLE)
    print("fenetre REELLE demandee : %s -> %s" % (DEBUT, FIN))
    curseur = DEBUT
    total = 0
    t0 = time.time()
    tranches = 0
    while curseur < FIN:
        fin_t = min(curseur + dt.timedelta(minutes=PAS_MIN), FIN)
        try:
            rows, dec = tranche(curseur, fin_t)
        except Exception as e:  # noqa: BLE001
            print("   %s -> %s : %s %s — tranche sautee"
                  % (curseur, fin_t, type(e).__name__, e))
            curseur = fin_t
            continue
        if rows:
            db.executemany("INSERT OR REPLACE INTO ticks VALUES (?,?,?,?,?)",
                           rows)
            db.commit()
            total += len(rows)
        tranches += 1
        if tranches % 20 == 0:
            print("   %s : %d ticks cumules, decalage %+.0f min, %.0f s"
                  % (curseur.date(), total,
                     dec.total_seconds() / 60 if dec else 0, time.time() - t0),
                  flush=True)
        curseur = fin_t
        time.sleep(PAUSE)
    n, a, b = db.execute(
        "SELECT count(*), min(ts_utc), max(ts_utc) FROM ticks WHERE pair = ?",
        (PAIRE,)).fetchone()
    print("\n%d ticks ecrits en %.0f s   %s -> %s" % (n, time.time() - t0, a, b))
    # continuite : combien de secondes sans aucun tick, en heures de cotation
    print("tranches lues : %d" % tranches)
    return 0


if __name__ == "__main__":
    sys.exit(main())
