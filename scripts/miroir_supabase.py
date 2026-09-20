#!/usr/bin/env python3
"""Pousse une copie EN LECTURE des tables de production vers Postgres.

But : rendre les donnees de production interrogeables en SQL depuis
l'exterieur, sans ouvrir de porte vers l'EC2 et sans jamais transporter un
secret. Ne pousse QUE des resultats : trades, poussees, refus, cellules du
laboratoire. Jamais l'`.env`, jamais une cle, jamais un identifiant broker.

## Ce que ce script ne fait pas

Il n'ECRIT RIEN dans SQLite. Il ouvre la base en lecture seule (`mode=ro`),
donc il ne peut pas prendre de verrou d'ecriture sur le chemin chaud du
dispatch — la panne du 2026-08-31 (`mt5_pushes` a zero ligne pendant que des
ordres partaient) etait un verrou. Un miroir ne doit jamais pouvoir couter un
trade.

## ⛔ Les colonnes non miroitees CRIENT

Les colonnes sont l'INTERSECTION de la source et de la destination. Une
colonne ajoutee a la source n'est donc pas poussee — et c'est exactement le
defaut de la colonne `chaine` (2026-09-16) : une donnee qui existe et que
personne n'enregistre. Elle est donc INSCRITE dans `sync_log.note`, pour que
le manque se lise au lieu de se deviner.

## ⛔ Zero ligne n'est pas « rien a dire »

Chaque table ecrit sa ligne dans `radar.sync_log`, meme a zero. Un miroir qui
cesse de se remplir ressemblerait sinon a « aucun trade » — la meme forme de
silence que ce depot paie en boucle.

Usage :
    MIROIR_PG_DSN="postgresql://...:5432/postgres" python3 scripts/miroir_supabase.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

try:
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError:
    sys.exit("psycopg2 absent : pip install --user psycopg2-binary")

SQLITE = os.getenv("MIROIR_SQLITE", "/opt/scalping/data/trades.db")
DSN = os.getenv("MIROIR_PG_DSN", "").strip()
SCHEMA = "radar"

# Fenetre de re-poussee pour les tables dont les lignes CHANGENT apres
# creation : un trade ouvert voit son `status`, son `pnl` et son `closed_at`
# ecrits plus tard. Un incremental par `id` seul les manquerait pour toujours.
REPOUSSE_JOURS = 45

# ⛔ `signal_rejections` N'A PLUS DE FENETRE — corrige le 2026-09-20 APRES
# mesure, pas par principe. C'est un journal APPEND-ONLY : une ligne de refus
# n'est jamais modifiee apres coup. La fenetre de 45 jours la faisait pourtant
# reecrire en ENTIER a chaque execution — 1 007 088 lignes repoussees, et
# `n_tup_upd` = 1 640 026 cote Postgres — pour zero information nouvelle. Ce
# n'etait pas gratuit : des minutes par nuit, de la churn sur les index, et une
# base passee a 614 Mo pour un plan free plafonne a 500 Mo. Un miroir qui
# depasse son quota passe en lecture seule : il aurait cesse de se remplir en
# silence, ce que `sync_log` n'aurait meme pas pu ecrire.
#
# ⚠️ CE QU'ON PERD, et il faut le dire plutot que de le decouvrir : un backfill
# qui MODIFIE d'anciennes lignes (scripts/backfill_rejections_user_id.py) ne
# sera plus repousse tout seul. Apres un backfill, relancer le miroir UNE fois
# avec `MIROIR_REPOUSSE_REJETS=1` pour rattraper la fenetre.
#
# 🔑 Les deux autres tables gardent la leur, et pour une raison precise : un
# trade ouvert voit son `status`, son `pnl` et son `closed_at` ecrits plus tard.
# La fenetre n'est pas une precaution generale, c'est une reponse a la mutation.
REPOUSSE_REJETS = os.getenv("MIROIR_REPOUSSE_REJETS", "").strip() == "1"

# table -> (colonne d'horodatage pour la re-poussee, ou None)
TABLES = {
    "personal_trades": "created_at",
    "mt5_pushes": "pushed_at",
    "signal_rejections": "created_at" if REPOUSSE_REJETS else None,
    "labo_or_cellules": None,
    "labo_or_journal": None,
    "labo_or_sorties": None,
}
# Sans `id` a la source : cle naturelle, donc remplacement complet (table
# courte, et une fermeture peut etre reouverte).
TABLES_CLE_NATURELLE = {
    "labo_or_fermetures": ("destination", "pair", "horizon", "motif"),
}


def colonnes_sqlite(sq, table: str) -> list[str]:
    return [r[1] for r in sq.execute(f"PRAGMA table_info({table})")]


def colonnes_pg(pg, table: str) -> list[str]:
    with pg.cursor() as c:
        c.execute(
            "select column_name from information_schema.columns "
            "where table_schema=%s and table_name=%s", (SCHEMA, table))
        return [r[0] for r in c.fetchall()]


def journal(pg, table: str, lignes: int, max_id, note: str | None) -> None:
    with pg.cursor() as c:
        c.execute(
            f"insert into {SCHEMA}.sync_log "
            "(table_name, rows_upserted, max_source_id, source_db, note) "
            "values (%s,%s,%s,%s,%s)",
            (table, lignes, max_id, SQLITE, note))


def pousser(sq, pg, table: str, col_date: str | None) -> tuple[int, str | None]:
    src = colonnes_sqlite(sq, table)
    if not src:
        return 0, "table ABSENTE a la source"
    dst = colonnes_pg(pg, table)
    cols = [c for c in src if c in dst]
    if "id" not in cols:
        return 0, "pas de colonne `id` : table non poussee"
    manquantes = [c for c in src if c not in dst]
    note = ("colonnes a la source et PAS dans le miroir : "
            + ", ".join(manquantes)) if manquantes else None

    with pg.cursor() as c:
        c.execute(f"select coalesce(max(id),0) from {SCHEMA}.{table}")
        depuis = c.fetchone()[0]

    liste = ", ".join(f'"{c}"' for c in cols)
    where = f"id > {int(depuis)}"
    if col_date and col_date in src:
        borne = (datetime.now(timezone.utc)
                 - timedelta(days=REPOUSSE_JOURS)).isoformat()
        where += f" or {col_date} >= '{borne}'"
    rows = sq.execute(f"select {liste} from {table} where {where}").fetchall()
    if not rows:
        return 0, note

    maj = ", ".join(f'"{c}" = excluded."{c}"' for c in cols if c != "id")
    with pg.cursor() as c:
        execute_values(
            c,
            f'insert into {SCHEMA}.{table} ({liste}) values %s '
            f'on conflict (id) do update set {maj}',
            rows, page_size=500)
    return len(rows), note


def pousser_cle_naturelle(sq, pg, table: str, cle: tuple[str, ...]) -> tuple[int, str | None]:
    src = colonnes_sqlite(sq, table)
    if not src:
        return 0, "table ABSENTE a la source"
    dst = colonnes_pg(pg, table)
    cols = [c for c in src if c in dst]
    manquantes = [c for c in src if c not in dst]
    note = ("colonnes a la source et PAS dans le miroir : "
            + ", ".join(manquantes)) if manquantes else None
    liste = ", ".join(f'"{c}"' for c in cols)
    rows = sq.execute(f"select {liste} from {table}").fetchall()
    maj = ", ".join(f'"{c}" = excluded."{c}"' for c in cols if c not in cle)
    with pg.cursor() as c:
        if rows:
            execute_values(
                c,
                f'insert into {SCHEMA}.{table} ({liste}) values %s '
                f'on conflict ({", ".join(cle)}) do update set {maj}',
                rows, page_size=500)
    return len(rows), note


def main() -> int:
    if not DSN:
        sys.exit("MIROIR_PG_DSN absent")
    if not os.path.exists(SQLITE):
        sys.exit(f"base introuvable : {SQLITE}")

    # ⛔ Lecture seule, non negociable : voir l'en-tete.
    sq = sqlite3.connect(f"file:{SQLITE}?mode=ro", uri=True)
    pg = psycopg2.connect(DSN)
    total, echecs = 0, []
    try:
        for table, col_date in TABLES.items():
            try:
                n, note = pousser(sq, pg, table, col_date)
            except Exception as e:  # noqa: BLE001
                pg.rollback()
                n, note = 0, f"ECHEC : {e}"
                echecs.append(table)
            with pg.cursor() as c:
                c.execute(f"select coalesce(max(id),0) from {SCHEMA}.{table}")
                mx = c.fetchone()[0]
            journal(pg, table, n, mx, note)
            pg.commit()
            total += n
            print(f"{table}: {n} ligne(s)" + (f" — {note}" if note else ""))

        for table, cle in TABLES_CLE_NATURELLE.items():
            try:
                n, note = pousser_cle_naturelle(sq, pg, table, cle)
            except Exception as e:  # noqa: BLE001
                pg.rollback()
                n, note = 0, f"ECHEC : {e}"
                echecs.append(table)
            journal(pg, table, n, None, note)
            pg.commit()
            total += n
            print(f"{table}: {n} ligne(s)" + (f" — {note}" if note else ""))
    finally:
        sq.close()
        pg.close()

    print(f"total : {total} ligne(s)")
    # Sortie non nulle : un cron muet sur echec est un miroir qu'on croit a jour.
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
