#!/usr/bin/env python3
"""Ou passent les 0,163 R qui separent la simulation du resultat reel ?

Mesure du 2026-08-11, en multiples du risque engage :

    simulation sur bougies, sans frais, avec gestion   +0,278 R
    resultat reellement encaisse                       +0,115 R
    ecart inexplique                                    0,163 R   <- 5x le cout
                                                                     de la gestion

Ce script ventile cet ecart poste par poste, en interrogeant le courtier plutot
qu'en modelisant :

  commission   somme des `commission` de tous les deals de la position
  swap         somme des `swap` (financement des nuits)
  glissement   ecart entre le prix demande et le prix obtenu a l'entree,
               deja mesure dans `slippage_pips`
  residu       ce qui reste : spread de sortie, glissement de sortie, et les
               ecarts entre mes hypotheses de rejeu et la realite

⚠️ Le residu n'est PAS un poste de cout : c'est ce que la mesure n'explique
   pas. Le nommer honnetement evite de le repartir arbitrairement sur les
   autres.

⚠️ Tout est rapporte a `risk_money` (le risque engage en euros, ecrit par le
   bridge a l'execution), donc en R. Comparer des euros entre des trades de
   tailles differentes n'aurait aucun sens.

Usage :
    python3 scripts/decomposer_les_frais.py
"""
import os
import re
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.telegram_service import destination_for_ticket  # noqa: E402

BRIDGES = {
    "admin_legacy": (os.getenv("MT5_BRIDGE_URL"), os.getenv("MT5_BRIDGE_API_KEY")),
    "admin_live": (os.getenv("MT5_BRIDGE_LIVE_URL"), os.getenv("MT5_BRIDGE_LIVE_API_KEY")),
}


def _pip(pair: str) -> float:
    base = pair.split("/")[0].upper()
    quote = pair.split("/")[1].upper() if "/" in pair else ""
    if base in {"XAU", "XAG", "XPT", "XPD"}:
        return 0.01
    if quote == "JPY":
        return 0.01
    return 0.0001


def main() -> int:
    t = sqlite3.connect("/app/data/trades.db")
    t.row_factory = sqlite3.Row
    lignes = t.execute(
        "SELECT mt5_ticket, pair, direction, entry_price, stop_loss, pnl, notes, "
        "       slippage_pips, size_lot "
        "  FROM personal_trades WHERE status='CLOSED' AND pnl IS NOT NULL "
        " ORDER BY created_at DESC"
    ).fetchall()

    postes = defaultdict(list)
    glissements = []
    n = sans_detail = 0

    with httpx.Client() as client:
        for r in lignes:
            if not str(r["mt5_ticket"]).isdigit():
                continue
            dest = destination_for_ticket(int(r["mt5_ticket"]))
            url, cle = BRIDGES.get(dest, (None, None))
            if not url or not cle:
                continue
            m = re.search(r"risk_money=([0-9.]+)", r["notes"] or "")
            if not m or float(m.group(1)) <= 0:
                continue
            risk = float(m.group(1))
            e, sl = r["entry_price"], r["stop_loss"]
            if not e or not sl or abs(e - sl) <= 0:
                continue

            try:
                rep = client.get(f"{url}/deals", params={"ticket": int(r["mt5_ticket"])},
                                 headers={"X-API-Key": cle}, timeout=25).json()
            except Exception:
                continue
            if not rep.get("closed") or "commission" not in rep:
                sans_detail += 1
                continue

            n += 1
            postes["commission"].append(rep["commission"] / risk)
            postes["swap"].append(rep["swap"] / risk)
            postes["fee"].append(rep.get("fee", 0) / risk)
            postes["profit brut (prix)"].append(rep["profit_brut"] / risk)
            postes["resultat net encaisse"].append(rep["pnl_net"] / risk)

            # Glissement d'entree : `slippage_pips` est SIGNE (positif = en
            # notre faveur). On le convertit en R via la valeur du pip.
            sp = r["slippage_pips"]
            if sp is not None and r["size_lot"]:
                pip = _pip(r["pair"])
                # Cout en unites de prix, rapporte a la distance au stop.
                glissements.append(-(sp * pip) / abs(e - sl))

    print(f"trades avec detail des couts : {n}")
    print(f"  sans detail (bridge ancien) : {sans_detail}")
    if not n:
        return 1

    print()
    print("  %-26s %10s %10s %12s" % ("poste", "R moyen", "R median", "part"))
    net = statistics.mean(postes["resultat net encaisse"])
    brut = statistics.mean(postes["profit brut (prix)"])
    for nom in ("profit brut (prix)", "commission", "swap", "fee",
                "resultat net encaisse"):
        v = postes.get(nom)
        if not v:
            continue
        mo = statistics.mean(v)
        part = "" if nom.startswith(("profit", "resultat")) else \
            "%9.1f %%" % (100 * abs(mo) / abs(brut)) if brut else ""
        print("  %-26s %+9.4f %+10.4f %12s" % (nom, mo, statistics.median(v), part))

    print()
    print("  %-26s %+9.4f" % ("brut - net (couts explicites)", brut - net))
    if glissements:
        g = statistics.mean(glissements)
        print("  %-26s %+9.4f   (mediane %+.4f, n=%d)" % (
            "glissement a l'entree", g, statistics.median(glissements), len(glissements)))
    print()
    print("⚠️ Le glissement d'entree n'est PAS soustrait du brut : il est deja")
    print("   dans le prix d'execution, donc deja dans `profit_brut`. Il est")
    print("   affiche pour savoir combien l'execution coute en plus du spread.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
