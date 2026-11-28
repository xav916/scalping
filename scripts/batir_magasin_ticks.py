#!/usr/bin/env python3
"""BATIR un magasin de (pseudo-)TICKS de l'or depuis le pont, en UTC vrai.

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

⛔ BASCULE DU 2026-11-28 : la route `/ticks` a disparu du bridge Windows
(-> 404 Not Found, confirme sur `/ticks` ET `/tick` sur le SHA b85ec3b010cd).
Dernier vrai tick ecrit : 2026-11-13 20:57:26. On se rabat sur `/rates`
horizon=M1 et on genere UN pseudo-tick par bougie close :

    ts_utc = bougie.t
    bid    = c - s * point / 2
    ask    = c + s * point / 2

Les trois promesses ci-dessus RETOMBENT en partie : plus d'ordre intra-minute,
plus de cadence 2,7/s, seul le spread au close de la minute est connu. On
CODE cette perte dans la table `provenance` pour que les bancs qui lisent le
magasin apres cette date la trouvent sans relire ce fichier.

⚠️ L'ancien chemin `/ticks` lisait `from`/`to` en ETIQUETTES BRUTES et devait
corriger avec `decalage_serveur_sec`. `/rates` renvoie deja ses `t` corriges
cote serveur (observe : fenetre `from=20:00:00&to=20:05:00` rend des bougies
aux `t` 20:00:03, 20:01:03, ...). Pas de correction manuelle necessaire.
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
PAS_MIN = int(os.getenv("TICKS_PAS_MIN", "10"))     # taille d'une tranche
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
    # Marqueurs historiques : gardes pour les lignes ecrites jusqu'au
    # 2026-11-13 20:57:26, qui sont de VRAIS ticks /ticks.
    ("source", "pont MT5 IC Markets route /ticks, PAS Twelve Data"),
    ("fuseau", "UTC vrai, corrige par -decalage_serveur_sec/60 + 180"),
    ("ancre_verifiee", "fill 09/10 08:20:21 a 4200.22 dans la plage des bids"),
    ("bati_le", "2026-10-11"),
    # 🔑 Bascule du 2026-11-28 : /ticks disparu du bridge (SHA b85ec3b010cd).
    ("source_depuis_2026-11-28",
     "pont /rates horizon=M1, 1 pseudo-tick par bougie close, "
     "bid = c - s*point/2, ask = c + s*point/2"),
    ("bascule_motif",
     "route /ticks 404 Not Found depuis 2026-11-13 ~22:37 UTC, "
     "confirme le 2026-11-28 sur SHA b85ec3b010cd"),
    ("bascule_resolution_perdue",
     "de 2,7 ticks/s a 1 tick/min : ordre intra-minute perdu, "
     "la convention 'bougie qui contient les deux bornes = stop' "
     "revient par la petite porte sur les bancs qui lisent apres cette date"),
])
db.commit()


def tranche(debut_reel: dt.datetime, fin_reel: dt.datetime):
    """Rend les pseudo-ticks d'une tranche REELLE via `/rates` M1.

    Un seul appel suffit : `/rates` rend les `t` deja corriges serveur-side.
    Pas de pagination (une tranche de 10 min = 10 bougies M1 max, loin du
    plafond de la route).
    """
    q = urllib.parse.urlencode({
        "pair": PAIRE,
        "from": debut_reel.isoformat(),
        "to": fin_reel.isoformat(),
        "horizon": "M1",
    })
    rq = urllib.request.Request(base + "/rates?" + q,
                                headers={"X-API-Key": cle})
    o = json.loads(urllib.request.urlopen(rq, timeout=60).read())
    bougies = o.get("bougies") or []
    point = float(o.get("point") or 0.01)
    rows = []
    for b in bougies:
        brut = dt.datetime.fromisoformat(b["t"])
        if brut.tzinfo:
            brut = brut.replace(tzinfo=None)
        c = float(b["c"])
        s = float(b.get("s") or 0)
        half = s * point / 2.0
        rows.append((PAIRE, brut.isoformat(), 0, c - half, c + half))
    return rows


def main():
    print("cible : %s" % CIBLE)
    print("fenetre REELLE demandee : %s -> %s" % (DEBUT, FIN))
    print("source : /rates horizon=M1 (route /ticks disparue, cf. provenance)")
    curseur = DEBUT
    total = 0
    t0 = time.time()
    tranches = 0
    while curseur < FIN:
        fin_t = min(curseur + dt.timedelta(minutes=PAS_MIN), FIN)
        try:
            rows = tranche(curseur, fin_t)
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
            print("   %s : %d pseudo-ticks cumules, %.0f s"
                  % (curseur.date(), total, time.time() - t0), flush=True)
        curseur = fin_t
        time.sleep(PAUSE)
    n, a, b = db.execute(
        "SELECT count(*), min(ts_utc), max(ts_utc) FROM ticks WHERE pair = ?",
        (PAIRE,)).fetchone()
    print("\n%d ticks ecrits en %.0f s   %s -> %s" % (n, time.time() - t0, a, b))
    print("tranches lues : %d" % tranches)
    return 0


if __name__ == "__main__":
    sys.exit(main())
