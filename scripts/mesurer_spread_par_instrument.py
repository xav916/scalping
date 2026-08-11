#!/usr/bin/env python3
"""Combien coute le spread, par instrument et par heure ?

Sur ces comptes la **commission est nulle** et le **swap negligeable** (mesure
du 2026-08-11 sur 191 trades) : le spread EST le cout d'execution. Rien ne
l'exposait avant que `/rates` ne remonte le champ.

## Comment le rendre comparable a l'edge

Un spread en points ne dit rien. Ce qui compte, c'est sa taille **rapportee a
la distance au stop** : c'est la fraction de R payee a chaque trade.

    cout en R = spread / distance au stop

On l'affiche a deux distances :

- **au stop MINIMUM que le systeme autorise** (`MT5_BRIDGE_MIN_SL_DISTANCE_
  PCT_PER_CLASS`) : le pire cas admissible, et la borne qui decide si un
  instrument est tradable ;
- **a la distance MEDIANE reellement utilisee** sur cet instrument, quand il a
  ete trade.

⚠️ Le spread se paie **une fois** par aller-retour : on achete a l'offre et on
   vend a la demande. Ne pas le compter deux fois.

Usage :
    python3 scripts/mesurer_spread_par_instrument.py
"""
import os
import re
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

URL = os.getenv("MT5_BRIDGE_URL")
CLE = os.getenv("MT5_BRIDGE_API_KEY")

PAIRES = ["XAU/USD", "XAG/USD", "WTI/USD", "EUR/USD", "GBP/USD", "USD/JPY",
          "EUR/JPY", "GBP/JPY", "AUD/USD", "USD/CHF", "USD/CAD", "EUR/GBP"]

# Stop minimal autorise par classe, en % du prix (copie de la config).
MIN_SL_PCT = {"forex_major": 0.04, "forex_jpy": 0.02, "metal": 0.05,
              "equity_index": 0.03, "crypto": 0.08, "energy": 0.05}


def _classe(pair):
    base = pair.split("/")[0].upper()
    quote = pair.split("/")[1].upper() if "/" in pair else ""
    if base in {"XAU", "XAG"}:
        return "metal"
    if base in {"WTI", "BRENT"}:
        return "energy"
    if quote == "JPY":
        return "forex_jpy"
    return "forex_major"


def _stops_medians():
    """Distance au stop reellement utilisee, par paire, en % du prix."""
    t = sqlite3.connect("/app/data/trades.db")
    t.row_factory = sqlite3.Row
    par = defaultdict(list)
    for r in t.execute(
        "SELECT pair, entry_price, stop_loss FROM personal_trades "
        " WHERE entry_price > 0 AND stop_loss > 0"
    ):
        d = abs(r["entry_price"] - r["stop_loss"]) / r["entry_price"] * 100
        if 0 < d < 20:
            par[r["pair"]].append(d)
    return {k: statistics.median(v) for k, v in par.items() if len(v) >= 5}


def main() -> int:
    if not URL or not CLE:
        print("bridge demo non configure")
        return 1
    fin = datetime.now(timezone.utc)
    debut = fin - timedelta(hours=39)   # lundi + mardi, sous la limite de bougies
    print(f"fenetre : {debut:%Y-%m-%d %H:%M} -> {fin:%Y-%m-%d %H:%M} UTC")
    stops = _stops_medians()
    print()

    lignes = []
    par_heure = defaultdict(lambda: defaultdict(list))
    with httpx.Client() as client:
        for pair in PAIRES:
            try:
                d = client.get(f"{URL}/rates", params={
                    "pair": pair, "timeframe": "M1",
                    "from": debut.isoformat(), "to": fin.isoformat()},
                    headers={"X-API-Key": CLE}, timeout=90).json()
            except Exception as e:
                print(f"  {pair} : injoignable ({type(e).__name__})")
                continue
            if "error" in d:
                print(f"  {pair} : {d['error']}")
                continue
            point = d.get("point") or 0
            sp = [(b["s"], b["c"], b["t"]) for b in d.get("bougies", [])
                  if b.get("s") is not None and b.get("c")]
            if not sp or not point:
                print(f"  {pair} : pas de spread remonte")
                continue

            # ⚠️ MT5 stocke le spread en nombre ENTIER de points. Sur les
            # majors forex il est souvent inferieur a 1 point et se retrouve
            # tronque a zero : 96 % des bougies EUR/USD, 88 % GBP/USD, 61 %
            # USD/CAD — mais avec des valeurs 1-2 qui apparaissent par
            # centaines, donc ce ne sont PAS des mesures manquantes, c'est une
            # RESOLUTION insuffisante. On borne au lieu d'affirmer.
            part_zeros = sum(1 for x in sp if x[0] == 0) / len(sp)
            tronque = part_zeros > 0.25
            pts = statistics.median([x[0] for x in sp])
            if tronque:
                pts = 1.0   # borne HAUTE : le vrai spread est dans [0 ; 1[
            prix = statistics.median([x[1] for x in sp])
            spread_prix = pts * point
            spread_pct = spread_prix / prix * 100
            mini = MIN_SL_PCT[_classe(pair)]
            cout_mini = spread_pct / mini
            med = stops.get(pair)
            cout_med = (spread_pct / med) if med else None
            lignes.append((pair, pts, spread_prix, spread_pct, mini,
                           cout_mini, med, cout_med, len(sp), tronque))
            for s_, _, ts in sp:
                par_heure[pair][int(ts[11:13])].append(s_ * point / prix * 100)

    print("  %-9s %7s %11s %9s %10s %11s %10s %11s" % (
        "paire", "points", "spread", "% prix", "stop min", "cout au min",
        "stop med", "cout med"))
    for (p, pts, sprix, spct, mini, cmini, med, cmed, n, tronque) in sorted(
            lignes, key=lambda x: -x[5]):
        cm = f"{cmed:9.1%}" if cmed is not None else "        -"
        sm = f"{med:8.3f}%" if med is not None else "       -"
        marque = " <1pt" if tronque else "     "
        print("  %-9s %7.0f%s %10.5f %8.4f%% %9.2f%% %10.1f%% %s %s" % (
            p, pts, marque, sprix, spct, mini, cmini * 100, sm, cm))

    print()
    print("  « cout au min » = fraction de R mangee par le spread si le stop est")
    print("  place a la distance MINIMALE que le systeme autorise.")
    print("  « <1pt » = spread sous la resolution de stockage de MT5 (entier de")
    print("  points). Les chiffres affiches sont alors une BORNE HAUTE, pas une")
    print("  mesure : le vrai spread est quelque part dans [0 ; 1[ point.")
    print()
    print("=== variation par heure UTC (spread en % du prix, or et EUR/USD) ===")
    for pair in ("XAU/USD", "EUR/USD"):
        h = par_heure.get(pair)
        if not h:
            continue
        pires = sorted(h.items(), key=lambda kv: -statistics.median(kv[1]))[:3]
        best = sorted(h.items(), key=lambda kv: statistics.median(kv[1]))[:3]
        print(f"  {pair}")
        print("    plus cheres : " + " · ".join(
            f"{k:02d}h {statistics.median(v):.4f}%" for k, v in pires))
        print("    moins cheres: " + " · ".join(
            f"{k:02d}h {statistics.median(v):.4f}%" for k, v in best))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
