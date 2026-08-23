#!/usr/bin/env python3
"""Mesure les corrélations horaires du forex et des métaux, chez le courtier.

Pourquoi ce script existe
-------------------------
``correlation_guard.CORRELATIONS`` ne couvre que **5 couples** forex/métaux,
mesurés le 2026-08-04 sur les prix d'entrée de ``backtest.db.signals``. Pour
tous les autres, ``correlation()`` rend ``None`` — donc le garde **ne compte
rien**.

⚠️ Le trou que ça laissait, mesuré le 2026-08-23 sur le compte réel : les
quatre positions ouvertes étaient GBP/USD ×2, EUR/GBP et GBP/JPY. Le couple
``GBP/USD × GBP/JPY`` **n'est pas dans la table**, donc invisible au garde —
alors que l'intuition dit « deux fois de la livre » et voudrait le bloquer.

La mesure dit le contraire, et c'est tout l'intérêt de mesurer :

    GBP/JPY vs USD/JPY   +0,79        volatilité H1 :  USD/JPY  0,151 %
    GBP/JPY vs GBP/USD   +0,19                         GBP/JPY  0,131 %
    GBP/USD vs USD/JPY   −0,50                         GBP/USD  0,067 %

``log(GBP/JPY) = log(GBP/USD) + log(USD/JPY)``. Le yen étant **2,3× plus
volatil** que la livre et USD/JPY anti-corrélé à GBP/USD, le facteur livre
partagé s'annule presque. **GBP/JPY est bien plus un pari sur le yen que sur
la livre.** Un garde-fou posé à l'intuition aurait bloqué ce couple pour la
mauvaise raison — et laissé passer les vrais doublons.

⚠️ **La valeur dépend de la fenêtre**, et il faut le savoir avant de s'en
servir comme d'une porte : ``GBP/USD × GBP/JPY`` vaut **−0,06 sur 30 jours**
et **+0,19 sur 44**. Les deux restent très en dessous du seuil de 0,6, donc
la décision ne change pas — mais un couple qui vivrait *près* du seuil
basculerait d'un côté ou de l'autre selon la fenêtre choisie. C'est une
raison de garder ``n`` en regard de chaque chiffre, et de remesurer.

Source
------
``GET <bridge>/rates?pair=…&timeframe=H1`` — le **courtier lui-même**, donc les
instruments réellement tradés et hors quota Twelve Data. Par défaut le bridge
LIVE : c'est là que se joue l'argent réel.

⚠️ **Le piège d'alignement.** Les horodatages rendus diffèrent d'**une
seconde** d'un symbole à l'autre (décalage serveur appliqué par paire) :
GBP/USD à ``21:00:46``, GBP/JPY à ``21:00:47``. Joindre à l'égalité rend
**zéro** ligne — même piège que ``substr(emitted_at,1,16)`` sur
``backtest.db``. On tronque donc à l'heure.

Méthode
-------
Rendements log horaires, Pearson sur l'intersection des heures communes à
chaque couple. Le nombre d'observations est conservé en regard : une
corrélation sur 200 points ne vaut pas celle sur 1 500.

Usage
-----
    python scripts/mesurer_correlations_forex.py
    HEURES=1500 python scripts/mesurer_correlations_forex.py
    BRIDGE_ENV=MT5_BRIDGE_URL python scripts/mesurer_correlations_forex.py
"""
from __future__ import annotations

import itertools
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

PAIRES = [
    "EUR/USD", "GBP/USD", "USD/JPY", "EUR/GBP", "USD/CHF",
    "AUD/USD", "USD/CAD", "EUR/JPY", "GBP/JPY", "XAU/USD", "XAG/USD",
]

HEURES = int(os.environ.get("HEURES", "1500"))
MIN_OBS = int(os.environ.get("MIN_OBS", "300"))
DELAI = 45

BRIDGE_ENV = os.environ.get("BRIDGE_ENV", "MT5_BRIDGE_LIVE_URL")
CLE_ENV = os.environ.get("CLE_ENV", "MT5_BRIDGE_LIVE_API_KEY")

SORTIE = (Path(__file__).resolve().parents[1] / "backend" / "services"
          / "correlations_forex_1h.json")


def _bougies(base: str, cle: str, paire: str) -> dict[str, float]:
    """``{heure_tronquee: cloture}``. Dict vide si la lecture échoue.

    ⚠️ La clé est tronquée à l'HEURE (13 caractères) : les secondes diffèrent
    entre symboles et une jointure exacte rendrait zéro ligne.
    """
    fin = datetime.now(timezone.utc)
    debut = fin - timedelta(hours=HEURES)
    q = urllib.parse.urlencode({
        "pair": paire, "timeframe": "H1",
        "from": debut.strftime("%Y-%m-%dT%H:%M:%S"),
        "to": fin.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    rq = urllib.request.Request(f"{base.rstrip('/')}/rates?{q}",
                                headers={"X-API-Key": cle} if cle else {})
    try:
        with urllib.request.urlopen(rq, timeout=DELAI) as r:
            charge = json.load(r)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        print(f"  {paire:<9} illisible ({type(e).__name__}: {e})")
        return {}
    out = {}
    for b in charge.get("bougies") or []:
        t, c = b.get("t"), b.get("c")
        if t and c:
            out[str(t)[:13]] = float(c)
    return out


def _rendements(series: dict[str, float], heures: list[str]) -> list[float]:
    return [math.log(series[heures[i]] / series[heures[i - 1]])
            for i in range(1, len(heures))]


def _pearson(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    if n < 2:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def main() -> int:
    base = os.environ.get(BRIDGE_ENV, "")
    if not base:
        print(f"{BRIDGE_ENV} absent de l'environnement — rien à mesurer")
        return 1
    cle = os.environ.get(CLE_ENV, "")

    print(f"source : {BRIDGE_ENV}   {HEURES} h demandées   min_obs={MIN_OBS}")
    series: dict[str, dict[str, float]] = {}
    for p in PAIRES:
        s = _bougies(base, cle, p)
        if s:
            series[p] = s
            print(f"  {p:<9} {len(s)} bougies")
    if len(series) < 2:
        print("moins de deux séries lisibles — abandon")
        return 1

    couples, ignores = [], []
    for a, b in itertools.combinations(sorted(series), 2):
        communs = sorted(set(series[a]) & set(series[b]))
        if len(communs) - 1 < MIN_OBS:
            ignores.append((a, b, len(communs) - 1))
            continue
        r = _pearson(_rendements(series[a], communs),
                     _rendements(series[b], communs))
        if r is None:
            ignores.append((a, b, 0))
            continue
        couples.append({"a": a, "b": b, "r": round(r, 3), "n": len(communs) - 1})

    couples.sort(key=lambda c: -abs(c["r"]))
    SORTIE.write_text(json.dumps({
        "source": f"{BRIDGE_ENV}/rates?timeframe=H1 (courtier MT5)",
        "methode": "rendements log horaires, Pearson sur l'intersection, "
                   "horodatages tronqués à l'heure",
        "heures_demandees": HEURES,
        "min_obs": MIN_OBS,
        "instruments": sorted(series),
        "couples": couples,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n{len(couples)} couples écrits dans {SORTIE.name}"
          f"   ({len(ignores)} ignorés faute d'observations)")
    print("\nles 12 plus fortes, en valeur absolue :")
    for c in couples[:12]:
        print(f"  {c['a']:<9} {c['b']:<9} {c['r']:+.2f}   n={c['n']}")
    if ignores:
        # Un couple ignore reste a None dans le garde : il ne compte RIEN.
        # Le taire ferait passer un trou pour une absence de correlation.
        print("\nignorés (le garde ne les comptera pas) :")
        for a, b, n in ignores:
            print(f"  {a:<9} {b:<9} n={n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
