#!/usr/bin/env python3
"""Rend leur prix d'entree aux trades ou IC Markets avait renvoye zero.

⛔ LE DEFAUT D'ORIGINE. `result.price` vaut **0** dans la reponse d'IC Markets :
le prix obtenu se lit sur le deal, pas sur le retour d'ordre. La cause est
reparee depuis le 2026-08-24 (`9cb89e3`) — mais **prospectivement**. Les lignes
deja ecrites portaient toujours `entry_price = 0`, et le chantier de rattrapage
etait bloque faute de source : `bridge_audit.db` porte le meme zero.

✅ **`broker_close_snapshots` EST cette source.** Le courtier rend le prix du
deal d'ouverture par ticket. 221 des 224 lignes concernees y figurent.

## Pourquoi un zero n'est pas anodin

`entry_price = 0` ne se lit pas comme « inconnu » : il se calcule. Un R vaut
`(sortie - entree)/risque` — avec une entree a zero, le gain mesure devient le
prix de sortie ENTIER (-1790 sur un ETH a 1790, deja vu le 2026-08-10). La
valeur par defaut ne se contente pas de manquer, elle **ment**.

## Trois verrous

1. **Lecture seule par defaut.** `--ecrire` est explicite, et sauvegarde avant.
2. **On ne touche QUE les zeros.** Une entree deja renseignee fait autorite :
   `entry_price = 0` est la seule marque de l'absence, et elle est sans
   ambiguite (aucun instrument ne s'echange a zero).
3. **On ne pose que ce que le courtier a dit.** Pas de reconstruction depuis le
   pnl et le prix de sortie : ce serait une deduction, pas une mesure.

Usage :
    python3 scripts/rattraper_entry_price_depuis_snapshot.py            # constat
    python3 scripts/rattraper_entry_price_depuis_snapshot.py --ecrire   # repare

Cf. [[project_rattrapage_entry_price_2026_08_24]] ·
    [[project_entry_price_absent_reel_2026_08_24]] ·
    [[project_analyse_clotures_main_2026_08_24]]
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
from datetime import datetime, timezone

DB = os.getenv("TRADES_DB", "/opt/scalping/data/trades.db")

CANDIDATS = """
SELECT p.id, p.mt5_ticket, p.pair, p.direction, p.exit_price, p.pnl,
       s.entry_price, s.bridge, s.reason
  FROM personal_trades p
  JOIN broker_close_snapshots s ON s.ticket = p.mt5_ticket
 WHERE p.status = 'CLOSED'
   AND (p.entry_price IS NULL OR p.entry_price = 0)
   AND s.entry_price IS NOT NULL
   AND s.entry_price <> 0
 ORDER BY p.id
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ecrire", action="store_true",
                    help="ecrit reellement (sauvegarde la base avant)")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    lignes = conn.execute(CANDIDATS).fetchall()

    restants = conn.execute(
        "SELECT COUNT(*) FROM personal_trades WHERE status='CLOSED' "
        "AND (entry_price IS NULL OR entry_price = 0)").fetchone()[0]

    print(f"{restants} lignes CLOSED sans prix d'entree · "
          f"{len(lignes)} retrouvees chez le courtier · "
          f"{restants - len(lignes)} INVERIFIABLES (historique purge)")
    print()
    for r in lignes[:12]:
        print(f"  #{r['id']:<5} {r['mt5_ticket']:<12} {r['pair']:<9} "
              f"{r['direction']:<5} entree 0 -> {r['entry_price']:<10.6g} "
              f"(sortie {r['exit_price']}, {r['reason']}, {r['bridge']})")
    if len(lignes) > 12:
        print(f"  ... et {len(lignes) - 12} autres")
    print()

    if not args.ecrire:
        print("LECTURE SEULE — relancer avec --ecrire pour appliquer.")
        return 0

    if lignes:
        sauv = f"{DB}.avant-rattrapage-entry-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
        shutil.copy2(DB, sauv)
        print(f"sauvegarde : {sauv}")

    # ⚠️ La condition `entry_price = 0` est REPETEE dans l'UPDATE, pas seulement
    # dans le SELECT. Entre les deux, le sync a pu renseigner la ligne : sans
    # elle, on ecraserait une valeur fraiche par une lecture perimee.
    n = 0
    for r in lignes:
        n += conn.execute(
            "UPDATE personal_trades SET entry_price = ? "
            " WHERE id = ? AND (entry_price IS NULL OR entry_price = 0)",
            (r["entry_price"], r["id"]),
        ).rowcount
    conn.commit()

    reste = conn.execute(
        "SELECT COUNT(*) FROM personal_trades WHERE status='CLOSED' "
        "AND (entry_price IS NULL OR entry_price = 0)").fetchone()[0]
    print(f"{n} lignes reparees · il reste {reste} sans prix d'entree "
          f"(inverifiables)")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
