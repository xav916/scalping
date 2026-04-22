#!/usr/bin/env python3
"""One-shot script : parse les docker logs existants pour récupérer les
rejections bridge historiques, et les insérer dans `signal_rejections`.

Utilisation (sur EC2) :
    sudo docker logs --since=72h scalping-radar 2>&1 | \\
        python3 /home/ec2-user/scalping/scripts/backfill_rejections.py --dry-run
    # Puis, si le dry-run est satisfaisant :
    sudo docker logs --since=72h scalping-radar 2>&1 | \\
        python3 /home/ec2-user/scalping/scripts/backfill_rejections.py

Dédoublonnage : n'insère pas une ligne si (created_at, pair, reason_code)
existe déjà dans la table. Safe à rerunner.
"""
import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone

DB_PATH = "/opt/scalping/data/trades.db"

# Log format observé :
#   2026-04-22 05:27:16,557 [WARNING] backend.services.mt5_bridge: \
#     MT5 bridge a répondu 429 pour GBP/USD: {"blocked":true,...}
LOG_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+.*?"
    r"MT5 bridge a répondu (?P<status>\d+) pour (?P<pair>[A-Z0-9/]+):\s*(?P<body>.+)$"
)

# Autres patterns intéressants
TIMEOUT_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+.*?"
    r"MT5 bridge timeout.*? skip (?P<pair>[A-Z0-9/]+)"
)
EXCEPTION_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+.*?"
    r"MT5 bridge exception pour (?P<pair>[A-Z0-9/]+): (?P<err>.+)$"
)


def classify_bridge_response(status: int, body: str) -> str:
    if status == 429 or "Max open positions" in body:
        return "bridge_max_positions"
    if "10016" in body or "INVALID_STOPS" in body:
        return "bridge_invalid_stops"
    return "bridge_error"


def parse_ts(ts_raw: str) -> str:
    """Docker log timestamp en UTC (TZ=UTC dans le container). ISO 8601."""
    return ts_raw.replace(" ", "T") + "+00:00"


def parse_stream(stream) -> list[dict]:
    rejections: list[dict] = []
    for line in stream:
        m = LOG_RE.match(line)
        if m:
            rejections.append({
                "created_at": parse_ts(m.group("ts")),
                "pair": m.group("pair"),
                "reason_code": classify_bridge_response(int(m.group("status")), m.group("body")),
                "details": json.dumps({
                    "status": int(m.group("status")),
                    "body": m.group("body")[:200].strip(),
                    "backfilled": True,
                }),
            })
            continue
        m = TIMEOUT_RE.match(line)
        if m:
            rejections.append({
                "created_at": parse_ts(m.group("ts")),
                "pair": m.group("pair"),
                "reason_code": "bridge_timeout",
                "details": json.dumps({"backfilled": True}),
            })
            continue
        m = EXCEPTION_RE.match(line)
        if m:
            rejections.append({
                "created_at": parse_ts(m.group("ts")),
                "pair": m.group("pair"),
                "reason_code": "bridge_error",
                "details": json.dumps({"exception": m.group("err")[:200], "backfilled": True}),
            })
    return rejections


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_rejections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            pair TEXT,
            direction TEXT,
            confidence REAL,
            reason_code TEXT NOT NULL,
            details TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sr_created ON signal_rejections(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sr_reason ON signal_rejections(reason_code)")


def insert_with_dedup(conn: sqlite3.Connection, rejections: list[dict]) -> int:
    inserted = 0
    for r in rejections:
        # Dédup sur (created_at, pair, reason_code) : signature unique
        existing = conn.execute(
            """
            SELECT 1 FROM signal_rejections
             WHERE created_at = ? AND pair = ? AND reason_code = ?
            """,
            (r["created_at"], r["pair"], r["reason_code"]),
        ).fetchone()
        if existing:
            continue
        conn.execute(
            """
            INSERT INTO signal_rejections (created_at, pair, reason_code, details)
            VALUES (?, ?, ?, ?)
            """,
            (r["created_at"], r["pair"], r["reason_code"], r["details"]),
        )
        inserted += 1
    return inserted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="parse mais n'écrit pas en DB")
    ap.add_argument("--db", default=DB_PATH, help=f"chemin DB (défaut {DB_PATH})")
    args = ap.parse_args()

    rejections = parse_stream(sys.stdin)
    print(f"Parsed {len(rejections)} rejection candidates from stdin", file=sys.stderr)

    # Stats préview
    by_reason: dict[str, int] = {}
    for r in rejections:
        by_reason[r["reason_code"]] = by_reason.get(r["reason_code"], 0) + 1
    for code, count in sorted(by_reason.items(), key=lambda kv: -kv[1]):
        print(f"  {code}: {count}", file=sys.stderr)

    if args.dry_run:
        print("DRY RUN — no writes.", file=sys.stderr)
        if rejections:
            print("\nFirst 3 entries:", file=sys.stderr)
            for r in rejections[:3]:
                print(f"  {r}", file=sys.stderr)
        return

    with sqlite3.connect(args.db) as conn:
        ensure_schema(conn)
        inserted = insert_with_dedup(conn, rejections)
    print(f"Inserted {inserted} new rows ({len(rejections) - inserted} dedupéd)", file=sys.stderr)


if __name__ == "__main__":
    main()
