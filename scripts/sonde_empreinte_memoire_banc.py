#!/usr/bin/env python3
"""Combien de memoire coute UNE paire ? Mesure, avant de relancer quoi que ce soit.

⛔ POURQUOI. Le 2026-10-08 mon banc a fait tomber la production 56 minutes : il
gardait 14 paires en memoire a la fois. J'ai corrige pour n'en garder qu'UNE —
mais je n'avais pas mesure ce qu'UNE coute. Le radar occupe deja 1,83 Gio sur
3,75 : il reste moins de 2 Gio.

Supposer que ca tient serait refaire l'erreur d'hier sous une autre forme.
"""
from __future__ import annotations

import gc
import resource
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/bancs")

from backend.services import laboratoire_or as labo   # noqa: E402


def mo() -> float:
    """Pic de memoire resident du processus, en Mo."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def main() -> int:
    paire = sys.argv[1] if len(sys.argv) > 1 else "XAG/USD"
    import banc_risque_replication as rep

    print(f"  depart                      {mo():7.0f} Mo")
    bgs = rep.bougies(paire)
    print(f"  apres {len(bgs):6d} bougies     {mo():7.0f} Mo")
    releve = labo.detections(bgs)
    n = sum(len(v) for v in releve.values())
    print(f"  apres {n:6d} detections   {mo():7.0f} Mo   <- LE PIC")
    del releve
    gc.collect()
    print(f"  apres liberation            {mo():7.0f} Mo")
    print()
    print(f"  => une paire coute ~{mo():.0f} Mo au pic.")
    print("     Le radar en prend 1 830 sur 3 750 : il reste ~1 900 Mo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
