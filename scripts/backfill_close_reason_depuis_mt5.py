#!/usr/bin/env python3
"""Remplace les causes de clôture DEVINÉES par celles que MT5 rapporte.

Le bridge remonte désormais `deal.reason` (déployé sur le VPS le 2026-08-10).
Tout l'historique redevient donc vérifiable : MT5 garde les deals, il suffit de
les lui demander ticket par ticket.

⚠️ Pourquoi ça change tout. L'heuristique comparait le prix de sortie aux SL/TP
   stockés en base — or le bridge DÉPLACE ces niveaux en cours de vie (mise à
   zéro du risque, stop suiveur, passage à TP2). La base garde ceux d'origine.
   Vérifié sur le ticket 82840896 : l'heuristique concluait TRAILING_SL, MT5
   répond **TP**. La conjecture était fausse, et elle l'était systématiquement
   pour tout trade dont un niveau avait bougé.

⚠️ La destination n'est PAS devinée d'après le format du ticket. On interroge
   le bridge du démo puis, s'il ne connaît pas le ticket, celui du réel. Le
   courtier a le deal ou ne l'a pas — il n'y a rien à interpréter.

⚠️ Lecture seule par défaut. Écrit uniquement avec --apply.

Usage :
    python3 scripts/backfill_close_reason_depuis_mt5.py
    python3 scripts/backfill_close_reason_depuis_mt5.py --apply
"""
import argparse
import os
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services import mt5_sync  # noqa: E402

BRIDGES = [
    ("demo", os.getenv("MT5_BRIDGE_URL"), os.getenv("MT5_BRIDGE_API_KEY")),
    ("reel", os.getenv("MT5_BRIDGE_LIVE_URL"), os.getenv("MT5_BRIDGE_LIVE_API_KEY")),
]


def _demander_la_cause(client, ticket: int) -> tuple[str | None, str | None]:
    """Retourne (cause_brute, bridge) ou (None, None) si aucun bridge ne connaît
    ce ticket. Un bridge injoignable lève — on ne veut PAS confondre
    « injoignable » avec « inconnu »."""
    for nom, url, cle in BRIDGES:
        if not url or not cle:
            continue
        r = client.get(f"{url}/deals", params={"ticket": ticket},
                       headers={"X-API-Key": cle}, timeout=20)
        r.raise_for_status()
        data = r.json()
        if data.get("closed") and data.get("reason"):
            return data["reason"], nom
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limite", type=int, default=0,
                    help="s'arrêter après N tickets (0 = tous)")
    args = ap.parse_args()

    for nom, url, cle in BRIDGES:
        print(f"bridge {nom:5s} : {'configure' if url and cle else 'ABSENT'}")
    print("mode : ÉCRITURE" if args.apply else "mode : simulation (lecture seule)")
    print()

    conn = sqlite3.connect(str(mt5_sync._db_path()))
    conn.row_factory = sqlite3.Row
    lignes = conn.execute(
        "SELECT mt5_ticket, close_reason, pnl FROM personal_trades "
        " WHERE status = 'CLOSED' AND mt5_ticket IS NOT NULL"
        " ORDER BY id DESC"  # les plus recents d'abord : les anciens tickets
                             # viennent d'un autre courtier et n'existent plus
    ).fetchall()

    transitions: Counter = Counter()
    par_bridge: Counter = Counter()
    a_ecrire: list[tuple[str, int]] = []
    inconnus = non_mt5 = erreurs = 0

    with httpx.Client() as client:
        for i, ligne in enumerate(lignes):
            if args.limite and i >= args.limite:
                break
            try:
                ticket = int(ligne["mt5_ticket"])
            except (TypeError, ValueError):
                non_mt5 += 1
                continue

            try:
                brut, bridge = _demander_la_cause(client, ticket)
            except Exception as e:
                erreurs += 1
                if erreurs <= 3:
                    print(f"  ⚠️ ticket {ticket} : {type(e).__name__} {e}")
                continue

            if brut is None:
                inconnus += 1
                continue

            par_bridge[bridge] += 1
            cause = mt5_sync._normalize_close_reason(brut)
            cause = mt5_sync._affiner_cause_du_courtier(ticket, cause, ligne["pnl"])
            if cause and cause != ligne["close_reason"]:
                transitions[f"{ligne['close_reason'] or '(NULL)'} -> {cause}"] += 1
                a_ecrire.append((cause, ticket))

            if (i + 1) % 200 == 0:
                print(f"  ... {i + 1}/{len(lignes)} tickets interrogés")
                time.sleep(0.5)

    print()
    print("=== ce que MT5 repond, contre ce que la base croyait ===")
    for k, n in transitions.most_common():
        print(f"  {k:34s} {n:5d}")
    if not transitions:
        print("  aucune divergence")
    print()
    print(f"tickets retrouves : {sum(par_bridge.values())} "
          f"({dict(par_bridge)})")
    print(f"inconnus des deux bridges (historique purge) : {inconnus}")
    print(f"tickets non-MT5 (UUID Kraken) : {non_mt5}")
    if erreurs:
        print(f"⚠️ erreurs reseau : {erreurs} — ces tickets n'ont PAS ete traites")

    if not a_ecrire:
        print("\nrien a ecrire.")
        return 0
    if not args.apply:
        print(f"\n{len(a_ecrire)} ligne(s) seraient corrigees. Relancer avec --apply.")
        return 0

    with conn:
        conn.executemany(
            "UPDATE personal_trades SET close_reason = ? WHERE mt5_ticket = ?",
            a_ecrire,
        )
    print(f"\n✅ {len(a_ecrire)} ligne(s) corrigees d'apres MT5.")
    print("\n=== distribution finale ===")
    for r in conn.execute(
        "SELECT COALESCE(close_reason,'(NULL)') r, COUNT(*) n, ROUND(AVG(pnl),2) m "
        "  FROM personal_trades WHERE status='CLOSED' GROUP BY 1 ORDER BY n DESC"
    ):
        print(f"  {r['r']:14s} {r['n']:5d}  pnl moyen {r['m']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
