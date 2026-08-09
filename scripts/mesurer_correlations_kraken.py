"""Mesure les corrélations horaires des perpétuels Kraken Futures.

Pourquoi ce script existe
-------------------------
``correlation_guard.CORRELATIONS`` ne couvrait que **6 paires crypto sur les
24 surveillées** — table mesurée le 2026-08-04 sur ``backtest.db.signals``.
Pour les 18 autres, ``correlation()`` rendait ``None``, donc le garde ne les
comptait pas : ``max_correlated_positions=1`` était déclaré sur ``admin_kraken``
alors que trois positions crypto y étaient ouvertes en même temps.

⚠️ **L'erreur de raisonnement qu'il corrige.** J'avais annoncé qu'il faudrait
« attendre plusieurs semaines », en confondant **notre** historique avec celui
du **marché**. La corrélation des rendements est une propriété du marché :
ETHFI, SEI ou CRV cotent chez Kraken depuis des mois, même si notre système ne
les surveille que depuis le 2026-08-08. La donnée existait déjà.

Source
------
``GET https://futures.kraken.com/api/charts/v1/trade/<SYMBOLE>/1h`` — endpoint
**public**, donc **hors quota Twelve Data** (le régime tourne à ~24 req/min sur
55, il ne faut pas y toucher). Ce sont en outre les **instruments réellement
tradés** : le perpétuel ``PF_ETHFIUSD``, pas un proxy spot.

⚠️ L'API rend au maximum 2000 bougies **à partir de** ``from``. On demande donc
``from = maintenant − 2000 h`` pour obtenir les 2000 dernières, soit ~83 jours —
davantage que les 64 jours de la mesure d'origine.

Méthode
-------
Rendements **logarithmiques** des clôtures horaires, alignés par horodatage,
puis Pearson sur l'intersection. Le nombre d'observations est conservé pour
chaque couple : une corrélation sur 200 points ne vaut pas celle sur 2000.

Usage : ``python scripts/mesurer_correlations_kraken.py [--seuil 0.6]``
Sortie : JSON sur stdout, consommable par ``correlations_mesurees.json``.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time

import httpx

URL = "https://futures.kraken.com/api/charts/v1/trade/{sym}/1h"
HEURES = 2000


def symbole_pour(pair: str) -> str:
    """``BTC/USD`` → ``PF_XBTUSD``. Kraken nomme le bitcoin XBT."""
    base = pair.split("/")[0].upper()
    return f"PF_{'XBT' if base == 'BTC' else base}USD"


def closes(sym: str, client: httpx.Client) -> dict[int, float]:
    """``{horodatage_ms: clôture}``. Dict vide si l'instrument ne répond pas."""
    fin = int(time.time())
    debut = fin - HEURES * 3600
    try:
        r = client.get(URL.format(sym=sym), params={"from": debut, "to": fin},
                       timeout=30)
        if r.status_code != 200:
            print(f"  !! {sym}: HTTP {r.status_code}", file=sys.stderr)
            return {}
        return {int(c["time"]): float(c["close"])
                for c in (r.json().get("candles") or [])}
    except Exception as e:
        print(f"  !! {sym}: {type(e).__name__} {e}", file=sys.stderr)
        return {}


def rendements(series: dict[int, float]) -> dict[int, float]:
    """Rendements log entre bougies **consécutives**.

    Indexés sur l'horodatage d'arrivée. Un trou dans la série ne produit pas de
    rendement : sauter par-dessus fabriquerait un mouvement qui n'a pas eu lieu
    sur une heure.
    """
    ts = sorted(series)
    out: dict[int, float] = {}
    for prec, cour in zip(ts, ts[1:]):
        if cour - prec != 3_600_000:
            continue
        a, b = series[prec], series[cour]
        if a > 0 and b > 0:
            out[cour] = math.log(b / a)
    return out


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paires", default="",
                    help="CSV de paires ; défaut = les crypto surveillées")
    ap.add_argument("--min-obs", type=int, default=500,
                    help="couples sous ce nombre d'observations : écartés")
    args = ap.parse_args()

    if args.paires:
        paires = [p.strip() for p in args.paires.split(",") if p.strip()]
    else:
        from config.settings import WATCHED_PAIRS, asset_class_for
        paires = sorted(p.strip() for p in WATCHED_PAIRS
                        if asset_class_for(p.strip()) == "crypto")

    print(f"# {len(paires)} instruments, {HEURES} h demandées", file=sys.stderr)
    series: dict[str, dict[int, float]] = {}
    with httpx.Client() as client:
        for p in paires:
            sym = symbole_pour(p)
            c = closes(sym, client)
            if c:
                series[p] = rendements(c)
                print(f"  {p:11} {sym:13} {len(c):5} bougies "
                      f"{len(series[p]):5} rendements", file=sys.stderr)
            time.sleep(0.25)   # endpoint public : rester poli

    couples: list[dict] = []
    noms = sorted(series)
    for i, a in enumerate(noms):
        for b in noms[i + 1:]:
            communs = sorted(set(series[a]) & set(series[b]))
            if len(communs) < args.min_obs:
                continue
            r = pearson([series[a][t] for t in communs],
                        [series[b][t] for t in communs])
            if r is None:
                continue
            couples.append({"a": a, "b": b, "r": round(r, 3),
                            "n": len(communs)})

    couples.sort(key=lambda c: -abs(c["r"]))
    json.dump({
        "source": "futures.kraken.com/api/charts/v1/trade/<SYM>/1h",
        "methode": "rendements log horaires, Pearson sur l'intersection",
        "heures_demandees": HEURES,
        "min_obs": args.min_obs,
        "instruments": noms,
        "couples": couples,
    }, sys.stdout, ensure_ascii=False, indent=1)
    print(file=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
