#!/usr/bin/env python3
"""Redonne sa vraie cause a chaque refus du bridge range sous « cap positions ».

⛔ LE DEFAUT. `_categoriser_refus` rangeait tout `status 429` sous
`bridge_max_positions`. Or le bridge repond 429 pour TOUS ses garde-fous.
Releve du 2026-08-25 sur le compte reel :

    108 lignes etiquetees « places pleines »
     76  en realite : coupe-circuit de perte journaliere
     19  en realite : doublon (fenetre de dedup)
     10  vraiment  : max open positions
      3  en realite : plafond de risque engage

Le plafond de positions etait donc surestime **d'un facteur 10**, et trois
mecanismes distincts n'apparaissaient nulle part.

✅ **La cause exacte est deja en base** : `details.body` porte le message du
bridge, mot pour mot. Il n'y a rien a deviner — on relit, on reclasse.

## Trois regles

1. **Lecture seule par defaut.** `--ecrire` sauvegarde la base avant.
2. **On ne reclasse QUE depuis le message du bridge.** Une ligne dont le corps
   est illisible garde son etiquette : mieux vaut une etiquette qu'on sait
   douteuse qu'une reecriture qu'on croira mesuree.
3. **On ne touche qu'a `bridge_max_positions`.** Les autres codes n'ont pas ce
   defaut ; les rejouer risquerait d'en casser un qui va bien.

Usage :
    python3 scripts/rectifier_refus_bridge.py            # constat
    python3 scripts/rectifier_refus_bridge.py --ecrire   # applique

Cf. [[feedback_detection_par_absence]]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app")

DB = os.getenv("TRADES_DB", "/opt/scalping/data/trades.db")


def _cause(details: str | None) -> str | None:
    """Rend le corps de la reponse du bridge, ou None s'il est illisible."""
    try:
        corps = json.loads(details or "{}").get("body")
    except (ValueError, TypeError):
        return None
    return corps or None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ecrire", action="store_true")
    args = ap.parse_args()

    from backend.services.mt5_bridge import _categoriser_refus

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    lignes = conn.execute(
        "SELECT id, destination_id, details FROM signal_rejections "
        "WHERE reason_code = 'bridge_max_positions'").fetchall()

    plan: list[tuple[int, str]] = []
    illisibles = 0
    par_dest: dict = collections.defaultdict(collections.Counter)
    for r in lignes:
        corps = _cause(r["details"])
        if corps is None:
            illisibles += 1
            continue
        neuf = _categoriser_refus(429, corps)
        par_dest[r["destination_id"] or "?"][neuf] += 1
        if neuf != "bridge_max_positions":
            plan.append((r["id"], neuf))

    print(f"{len(lignes)} lignes etiquetees 'bridge_max_positions'")
    print(f"  {illisibles} au corps illisible — laissees telles quelles")
    print(f"  {len(plan)} a reclasser\n")
    for dest, cpt in sorted(par_dest.items()):
        print(f"  {dest} :")
        for code, n in cpt.most_common():
            marque = "  <- vraiment" if code == "bridge_max_positions" else ""
            print(f"     {n:>4}  {code}{marque}")
    print()

    if not args.ecrire:
        print("LECTURE SEULE — relancer avec --ecrire pour appliquer.")
        return 0
    if not plan:
        print("rien a reclasser.")
        return 0

    sauv = f"{DB}.avant-rectif-refus-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    shutil.copy2(DB, sauv)
    print(f"sauvegarde : {sauv}")
    # ⚠️ La condition d'origine est REPETEE dans l'UPDATE : entre le SELECT et
    # l'ecriture, une ligne a pu etre reclassee par ailleurs.
    n = 0
    for rid, neuf in plan:
        n += conn.execute(
            "UPDATE signal_rejections SET reason_code = ? "
            " WHERE id = ? AND reason_code = 'bridge_max_positions'",
            (neuf, rid)).rowcount
    conn.commit()
    reste = conn.execute(
        "SELECT COUNT(*) FROM signal_rejections "
        "WHERE reason_code='bridge_max_positions'").fetchone()[0]
    print(f"{n} lignes reclassees · il reste {reste} vrais 'cap positions'")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
