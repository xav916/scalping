#!/usr/bin/env python3
"""Fige ce que le courtier sait encore, avant qu'il ne l'oublie.

⛔ LE PROBLEME. MT5 purge l'historique des deals. Mesure du 2026-08-24 :
sur 1 082 tickets CLOSED interroges, **838 (79 %) ne rendent plus de cause**.
Le 08-10 c'etait 1 349 lignes non verifiables, le 08-17 807 tickets muets.
La fenetre se referme en continu, et rien ne la photographiait.

> **Ce n'est pas une base de donnees qu'on interroge, c'est une fenetre qui se
> ferme.** Chaque jour sans snapshot est de l'historique perdu pour toujours.

Ce script demande a chaque bridge ce qu'il sait de chaque ticket CLOSED et
l'ecrit dans `broker_close_snapshots` — une table qui, elle, ne se purge pas.

## Trois regles

1. **Le premier releve gagne** (`INSERT OR IGNORE`). Les reponses du courtier
   ne peuvent que se degrader avec le temps : une reponse tardive et vide ne
   doit jamais ecraser une reponse complete deja figee.
2. **Un bridge muet n'ecrit rien.** Ni erreur reseau, ni `no deals found` ne
   sont enregistres : une absence de reponse n'est pas une observation.
   Cf. [[feedback_detection_par_absence]].
3. **Lecture seule sur `personal_trades`.** Ce script ajoute une table, il ne
   corrige rien. Le rattrapage est un autre geste, qui se decide.

Usage :
    python3 scripts/snapshot_deals_courtier.py            # tous les CLOSED
    python3 scripts/snapshot_deals_courtier.py --manquants # seulement les non figes

Cf. [[project_analyse_clotures_main_2026_08_24]] ·
    [[project_reconciliation_cloture_2026_08_13]]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

DB = os.getenv("TRADES_DB", "/opt/scalping/data/trades.db")
ENV = os.getenv("SCALPING_ENV_FILE", "/opt/scalping/.env")

SCHEMA = """
CREATE TABLE IF NOT EXISTS broker_close_snapshots (
    ticket             INTEGER PRIMARY KEY,
    bridge             TEXT,
    reason             TEXT,
    entry_price        REAL,
    exit_price         REAL,
    volume             REAL,
    pnl                REAL,
    pnl_net            REAL,
    swap               REAL,
    commission         REAL,
    fee                REAL,
    closed_at          TEXT,
    niveau_declencheur REAL,
    niveaux_source     TEXT,
    n_deals            INTEGER,
    vu_le              TEXT NOT NULL,
    brut               TEXT
)
"""


def _env() -> dict[str, str]:
    out: dict[str, str] = {}
    with open(ENV, encoding="utf-8", errors="replace") as f:
        for ligne in f:
            ligne = ligne.strip()
            if "=" in ligne and not ligne.startswith("#"):
                cle, val = ligne.split("=", 1)
                # ⚠️ `--env-file` ne retire pas les guillemets, mais nous si :
                # sinon la cle d'API part avec ses quotes et le bridge repond
                # 401 en silence. Cf. [[feedback_env_file_guillemets]].
                out[cle] = val.strip().strip('"').strip("'")
    return out


def _bridges(env: dict[str, str]) -> list[tuple[str, str, str]]:
    """(nom, url, cle) — le reel d'abord : c'est lui qui porte l'argent."""
    paires = [
        ("live", "MT5_BRIDGE_LIVE_URL", "MT5_BRIDGE_LIVE_API_KEY"),
        ("demo", "MT5_BRIDGE_URL", "MT5_BRIDGE_API_KEY"),
    ]
    return [
        (nom, env[u].rstrip("/"), env[k])
        for nom, u, k in paires
        if env.get(u) and env.get(k)
    ]


def _demander(bridges, ticket: int) -> tuple[str, dict] | None:
    """Le premier bridge qui CONNAIT la cloture fait foi.

    ⚠️ Un `closed=None` n'est pas une information sur la fermeture : c'est
    « ce ticket n'est pas le mien » ou « mon historique est purge ». On
    poursuit sur le bridge suivant au lieu de conclure.
    """
    for nom, url, cle in bridges:
        try:
            req = urllib.request.Request(
                f"{url}/deals?ticket={ticket}", headers={"X-API-Key": cle}
            )
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.load(r)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("closed") is True:
            return nom, data
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manquants", action="store_true",
                    help="n'interroger que les tickets pas encore figes")
    ap.add_argument("--paralleles", type=int, default=12)
    args = ap.parse_args()

    env = _env()
    bridges = _bridges(env)
    if not bridges:
        print("aucun bridge configure", file=sys.stderr)
        return 2

    conn = sqlite3.connect(DB)
    conn.execute(SCHEMA)
    conn.commit()

    sql = ("SELECT DISTINCT mt5_ticket FROM personal_trades "
           "WHERE status='CLOSED' AND mt5_ticket IS NOT NULL")
    if args.manquants:
        sql += (" AND mt5_ticket NOT IN "
                "(SELECT ticket FROM broker_close_snapshots)")
    tickets = [r[0] for r in conn.execute(sql)]
    print(f"{len(tickets)} tickets a interroger sur {len(bridges)} bridge(s)")

    vu_le = datetime.now(timezone.utc).isoformat()
    figes = muets = 0
    with ThreadPoolExecutor(max_workers=args.paralleles) as ex:
        for ticket, rep in zip(tickets, ex.map(
                lambda t: _demander(bridges, t), tickets)):
            if rep is None:
                muets += 1
                continue
            nom, d = rep
            conn.execute(
                "INSERT OR IGNORE INTO broker_close_snapshots "
                "(ticket, bridge, reason, entry_price, exit_price, volume, pnl,"
                " pnl_net, swap, commission, fee, closed_at,"
                " niveau_declencheur, niveaux_source, n_deals, vu_le, brut) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ticket, nom, d.get("reason"), d.get("entry_price"),
                 d.get("exit_price"), d.get("volume"), d.get("pnl"),
                 d.get("pnl_net"), d.get("swap"), d.get("commission"),
                 d.get("fee"), d.get("closed_at"), d.get("niveau_declencheur"),
                 d.get("niveaux_source"), d.get("n_deals"), vu_le,
                 json.dumps(d, separators=(",", ":"))),
            )
            figes += 1
    conn.commit()

    total = conn.execute(
        "SELECT COUNT(*) FROM broker_close_snapshots").fetchone()[0]
    avec_cause = conn.execute(
        "SELECT COUNT(*) FROM broker_close_snapshots "
        "WHERE reason IS NOT NULL").fetchone()[0]
    # ⚠️ Compter ce qui a ETE MESURE, pas ce qui a ete demande : un run qui
    # n'aurait joint aucun bridge afficherait sinon « 0 muet, tout va bien ».
    print(f"repondus {figes} · muets {muets} · table {total} lignes "
          f"(dont {avec_cause} avec cause du courtier)")
    if figes == 0 and tickets:
        print("⛔ AUCUNE reponse : bridges injoignables ou cle invalide, "
              "ce n'est PAS 'historique purge'", file=sys.stderr)
        return 1
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
