#!/usr/bin/env python3
"""Rectifie les causes de clôture affirmées sans preuve.

Jusqu'au 2026-08-10, `_derive_close_reason_from_exit` renvoyait "MANUAL" dans sa
branche par défaut : toute sortie qu'elle ne savait pas reconnaître était
déclarée « fermée à la main ». Mesuré ce jour-là : 215 trades étiquetés MANUAL,
dont 215 (100 %) avec `post_entry_sl=1` — donc aucun fermé à la main. C'étaient
les sorties du stop suiveur et de la mise à zéro du risque.

Ce script rejoue le classifieur corrigé sur les lignes concernées.

⚠️ Ne touche QUE `close_reason='MANUAL'` et `close_reason IS NULL`.
   - 'EXTERNE' et 'NET' viennent de l'attribution par unicité (08-09) : ce sont
     des déterminations positives, on n'y touche pas.
   - 'SL' et 'TP1' venaient déjà de branches positives : on se contente de
     signaler les divergences, sans écrire.

⚠️ Lecture seule par défaut. Écrit uniquement avec --apply.

Usage :
    python3 scripts/rectifier_close_reason_manual.py            # simulation
    python3 scripts/rectifier_close_reason_manual.py --apply    # écrit
"""
import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services import mt5_sync  # noqa: E402

# Causes établies par une autre voie que l'heuristique : intouchables.
CAUSES_AUTORITAIRES = {"EXTERNE", "NET", "STOP_OUT"}
# Causes que l'heuristique posait déjà positivement : on signale, on n'écrit pas.
CAUSES_A_SIGNALER_SEULEMENT = {"SL", "TP1", "TP2", "TIMEOUT"}


def _ticket_entier(valeur) -> int | None:
    """Les tickets Kraken sont des UUID ; seuls les tickets MT5 sont entiers.
    Rejouer le classifieur MT5 sur une ligne Kraken n'aurait aucun sens."""
    try:
        return int(valeur)
    except (TypeError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="écrit en base (sinon simulation)")
    ap.add_argument("--db", default=None, help="chemin de trades.db")
    args = ap.parse_args()

    db_path = args.db or str(mt5_sync._db_path())
    print(f"base : {db_path}")
    print("mode : ÉCRITURE" if args.apply else "mode : simulation (lecture seule)")
    print()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT mt5_ticket, close_reason, exit_price, pnl, pair "
        "  FROM personal_trades "
        " WHERE status = 'CLOSED' AND mt5_ticket IS NOT NULL"
    ).fetchall()

    transitions: Counter = Counter()
    divergences: Counter = Counter()
    a_ecrire: list[tuple[str, int]] = []
    ignores = 0

    for r in rows:
        ancienne = r["close_reason"]
        if ancienne in CAUSES_AUTORITAIRES:
            continue
        ticket = _ticket_entier(r["mt5_ticket"])
        if ticket is None:
            ignores += 1
            continue

        nouvelle = mt5_sync._derive_close_reason_from_exit(ticket, r["exit_price"])
        if nouvelle is None or nouvelle == ancienne:
            continue

        if ancienne in CAUSES_A_SIGNALER_SEULEMENT:
            divergences[f"{ancienne} -> {nouvelle}"] += 1
            continue

        transitions[f"{ancienne or '(NULL)'} -> {nouvelle}"] += 1
        a_ecrire.append((nouvelle, ticket))

    print("=== rectifications (MANUAL / NULL uniquement) ===")
    if not transitions:
        print("  aucune")
    for k, n in transitions.most_common():
        print(f"  {k:34s} {n:5d}")

    if divergences:
        print()
        print("=== divergences SIGNALÉES, non écrites ===")
        print("  (le classifieur voit autre chose que la cause déjà posée)")
        for k, n in divergences.most_common():
            print(f"  {k:34s} {n:5d}")

    if ignores:
        print()
        print(f"tickets non-MT5 ignorés (UUID Kraken) : {ignores}")

    if not a_ecrire:
        print("\nrien à écrire.")
        return 0

    if not args.apply:
        print(f"\n{len(a_ecrire)} ligne(s) seraient rectifiées. Relancer avec --apply.")
        return 0

    with conn:
        conn.executemany(
            "UPDATE personal_trades SET close_reason = ? WHERE mt5_ticket = ?",
            a_ecrire,
        )
    print(f"\n✅ {len(a_ecrire)} ligne(s) rectifiées.")

    print("\n=== distribution après rectification ===")
    for row in conn.execute(
        "SELECT COALESCE(close_reason,'(NULL)') r, COUNT(*) n, ROUND(AVG(pnl),2) m "
        "  FROM personal_trades WHERE status='CLOSED' GROUP BY 1 ORDER BY n DESC"
    ):
        print(f"  {row['r']:14s} {row['n']:5d}  pnl moyen {row['m']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
