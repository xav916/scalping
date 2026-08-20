#!/usr/bin/env python3
"""Périme les ordres EA dont le TTL est dépassé (2026-08-21).

`purge_expired()` existe depuis la phase MQL.B et son docstring dit « à
appeler par cron ou job admin ». **Personne ne l'appelait.** Résultat au
21/08 : 2 912 ordres restés `PENDING` depuis le 08/06, deux mois et demi
d'accumulation dans la file d'un seul client.

⚠️ Ils n'étaient pas dangereux — `fetch_for_api_key` filtre déjà sur
`expires_at > now`, donc un EA qui revient ne les recevrait jamais. Le coût
était **de lisibilité** : la file affichait 2 912 ordres « en attente » alors
que zéro était servable, ce qui rend tout diagnostic faux.

> **Une fonction de maintenance que rien n'appelle n'est pas un garde-fou,
> c'est une intention.**

Ne SUPPRIME aucune ligne : `PENDING`/`SENT` → `EXPIRED`, l'historique reste
auditable (qui a expiré, quand, pourquoi).

Usage :
    python purge_file_ea.py
    DRY_RUN=1 python purge_file_ea.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app")


def main() -> int:
    from backend.services import mt5_pending_orders_service as q

    maintenant = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(q._db_path()) as c:
        avant = c.execute("SELECT COUNT(*) FROM mt5_pending_orders").fetchone()[0]
        a_perimer = c.execute(
            "SELECT COUNT(*) FROM mt5_pending_orders "
            " WHERE status IN ('PENDING','SENT') AND expires_at < ?",
            (maintenant,)).fetchone()[0]

    if os.environ.get("DRY_RUN") == "1":
        print(f"  [DRY_RUN] {a_perimer} ordre(s) à périmer")
        return 0

    n = q.purge_expired()

    with sqlite3.connect(q._db_path()) as c:
        apres = c.execute("SELECT COUNT(*) FROM mt5_pending_orders").fetchone()[0]

    # ⚠️ Le controle qui compte : purge_expired ne doit JAMAIS supprimer.
    # Une regression qui passerait a DELETE effacerait la preuve d'une panne
    # client — exactement ce qui a servi a etablir le cas de Cedric.
    if apres != avant:
        print(f"  ⛔ {avant - apres} ligne(s) ONT DISPARU — la purge doit "
              f"marquer EXPIRED, jamais supprimer")
        return 1

    if n:
        print(f"  {n} ordre(s) marqué(s) EXPIRED ({avant} lignes, intactes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
