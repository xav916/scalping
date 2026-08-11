"""Journal des rejections de signaux auto-exec.

Chaque fois qu'un setup éligible (score ≥ seuil, etc.) est bloqué avant
l'exécution MT5 — que ce soit par un garde-fou local (market hours, SL
trop serré, kill-switch...) ou par le bridge (rc=10016, 429 max positions,
timeout...) — on enregistre une ligne.

Sert à la carte RejectionsCard du cockpit pour visualiser d'où viennent
les ordres perdus.
"""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


# Codes de raison canoniques. Un seul par rejection pour simplifier la viz.
# - kill_switch : coupure manuelle ou par perte journalière atteinte
# - event_blackout : fenêtre +/-15min autour d'un event high-impact
# - simulated_data : fallback price_service (bug historique, fix 69df7f1)
# - verdict_blocker : blockers durs du verdict (VIX, holiday, etc.)
# - market_closed : pair fermée (weekends, daily break métal, etc.)
# - sl_too_close : distance SL inférieure au seuil MIN_SL_DISTANCE_PCT
# - below_confidence : score < MT5_BRIDGE_MIN_CONFIDENCE
# - asset_class_blocked : broker actuel ne supporte pas cette classe
# - bridge_max_positions : bridge renvoie 429 (max_open_positions)
# - bridge_invalid_stops : bridge renvoie erreur rc=10016
# - bridge_error : autre erreur bridge (status ≠ 200)
# - bridge_timeout : bridge injoignable (PC éteint, Tailscale down)

REASON_LABELS_FR = {
    "kill_switch": "Kill switch actif",
    "kill_switch_pair_paused": "Pair en pause rafale SL",
    "event_blackout": "Blackout event macro",
    "simulated_data": "Données simulées",
    "verdict_blocker": "Verdict bloqué",
    "market_closed": "Marché fermé",
    "sl_too_close": "SL trop serré",
    "heure_spread_defavorable": "Heure où le spread coûte le double",
    "below_confidence": "Confiance < seuil",
    "pattern_not_allowed": "Pattern hors whitelist",
    "asset_class_blocked": "Classe d'actif bloquée",
    "max_positions_per_pair": "Cap positions par pair",
    "bridge_max_positions": "Cap positions bridge",
    "bridge_invalid_stops": "Bridge : stops invalides",
    "bridge_error": "Bridge : erreur autre",
    "bridge_timeout": "Bridge injoignable",
    "fees_exceed_edge": "frais supérieurs à 30 % de l'edge",
    "horizon_not_allowed": "horizon non servi par cette route",
    "earnings_blackout": "résultats publiés pendant la détention",
    "weekend_hold_blocked": "détention à travers le week-end",
}


def _db_path() -> str:
    from backend.services.trade_log_service import _DB_PATH
    return str(_DB_PATH)


def _ensure_schema() -> None:
    with sqlite3.connect(_db_path()) as c:
        c.execute("""
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
        # Chantier 3D SaaS : ajoute user_id (nullable tant que la migration
        # du bridge pour propager le contexte user n'est pas faite).
        cols = [r[1] for r in c.execute("PRAGMA table_info(signal_rejections)").fetchall()]
        if "user_id" not in cols:
            c.execute("ALTER TABLE signal_rejections ADD COLUMN user_id INTEGER")
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_sr_user_id ON signal_rejections(user_id)"
            )
        # destination_id (2026-08-04) : `user_id` vaut None pour TOUTES les
        # destinations admin, donc rien ne distinguait admin_live d'admin_kraken
        # dans le log. Deux destinations ont passé des semaines à ne rien
        # exécuter sans que rien ne l'indique — les Voies A/B, puis Kraken, dont
        # 34 des 40 derniers signaux crypto tombaient en `_not_admitted` sans
        # que ce soit attribuable. Diagnostiquer a exigé de reconstruire la
        # config à la main et de rejouer le filtre.
        if "destination_id" not in cols:
            c.execute("ALTER TABLE signal_rejections ADD COLUMN destination_id TEXT")
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_sr_destination "
                "ON signal_rejections(destination_id)"
            )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_sr_created ON signal_rejections(created_at)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_sr_reason ON signal_rejections(reason_code)"
        )


def record_rejection(
    pair: str | None,
    direction: str | None,
    confidence: float | None,
    reason_code: str,
    details: dict[str, Any] | None = None,
    user_id: int | None = None,
    destination_id: str | None = None,
) -> None:
    """Enregistre une ligne dans `signal_rejections`. Best-effort : toute
    erreur DB est silencieusement avalée pour ne pas planter le pipeline.

    `user_id` (Chantier 3D) : id du user auquel imputer la rejection.
    Laisser None tant que le bridge MT5 ne propage pas encore l'identité
    du user (mono-tenant actuel). Les rows NULL sont rattrapées par le
    script de backfill (scripts/backfill_rejections_user_id.py).

    `destination_id` (2026-08-04) : 'admin_live', 'admin_kraken', 'user:2'…
    **Indispensable pour savoir QUI rejette.** `user_id` est None sur toutes
    les destinations admin, donc sans ce champ un rejet `admin_kraken` est
    indiscernable d'un rejet `admin_legacy`. None = appel legacy mono-tenant
    (``_should_push`` sans destination).
    """
    try:
        _ensure_schema()
        with sqlite3.connect(_db_path()) as c:
            c.execute(
                """
                INSERT INTO signal_rejections
                    (created_at, pair, direction, confidence, reason_code,
                     details, user_id, destination_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    pair,
                    direction,
                    confidence,
                    reason_code,
                    json.dumps(details) if details else None,
                    user_id,
                    destination_id,
                ),
            )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("record_rejection failed (silencé)")


def get_rejections(
    since: str,
    until: str,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Agrège les rejections pour la RejectionsCard.

    Retourne :
        {
          "total": int,
          "by_reason": [{reason_code, label_fr, count, top_pair}, ...],
          "by_hour_utc": [{hour: 0..23, count}, ...],  # 24 entrées exactes
          "by_reason_hour": [[reason_code, hour, count], ...],  # pour heatmap
          "by_destination": [{destination_id, count, top_reason}, ...],
          "since": str,
          "until": str,
        }

    ``by_destination`` (2026-08-04) répond à « quelle destination rejette
    quoi ». Sans lui, une destination peut ne rien exécuter pendant des
    semaines sans que rien ne l'indique : c'est arrivé aux Voies A/B, puis à
    Kraken, dont 34 des 40 derniers signaux crypto tombaient en
    ``_not_admitted`` sans que ce soit attribuable. Les lignes antérieures au
    2026-08-04 portent ``None`` — elles apparaissent sous ``"(inconnu)"``.
    """
    _ensure_schema()
    scope_sql = ""
    scope_params: tuple = ()
    if user_id is not None:
        # Chantier 3D : un user ne voit QUE ses propres rejections. Les rows
        # NULL (legacy avant backfill) sont ignorées côté user — les opérateurs
        # peuvent lancer scripts/backfill_rejections_user_id.py pour les
        # attribuer.
        scope_sql = " AND user_id = ?"
        scope_params = (user_id,)

    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            f"""
            SELECT created_at, pair, reason_code, destination_id
              FROM signal_rejections
             WHERE created_at >= ? AND created_at <= ?
               {scope_sql}
            """,
            (since, until, *scope_params),
        ).fetchall()

    by_reason: dict[str, dict[str, Any]] = {}
    by_hour_count: dict[int, int] = {h: 0 for h in range(24)}
    by_reason_hour: dict[tuple[str, int], int] = {}
    by_dest: dict[str, dict[str, Any]] = {}

    for r in rows:
        reason = r["reason_code"]
        pair = r["pair"] or "UNKNOWN"
        try:
            hour = int(r["created_at"][11:13])
        except (ValueError, IndexError):
            hour = 0

        entry = by_reason.setdefault(reason, {"count": 0, "pairs": {}})
        entry["count"] += 1
        entry["pairs"][pair] = entry["pairs"].get(pair, 0) + 1

        by_hour_count[hour] = by_hour_count.get(hour, 0) + 1
        key = (reason, hour)
        by_reason_hour[key] = by_reason_hour.get(key, 0) + 1

        dest = r["destination_id"] or "(inconnu)"
        d_entry = by_dest.setdefault(dest, {"count": 0, "reasons": {}})
        d_entry["count"] += 1
        d_entry["reasons"][reason] = d_entry["reasons"].get(reason, 0) + 1

    by_reason_list = []
    for reason, v in sorted(by_reason.items(), key=lambda kv: -kv[1]["count"]):
        top_pair = max(v["pairs"].items(), key=lambda kv: kv[1])[0] if v["pairs"] else None
        by_reason_list.append({
            "reason_code": reason,
            "label_fr": REASON_LABELS_FR.get(reason, reason),
            "count": v["count"],
            "pairs": v["pairs"],
            "top_pair": top_pair,
        })

    by_destination_list = []
    for dest, v in sorted(by_dest.items(), key=lambda kv: -kv[1]["count"]):
        top_reason = max(v["reasons"].items(), key=lambda kv: kv[1])[0]
        by_destination_list.append({
            "destination_id": dest,
            "count": v["count"],
            "top_reason": top_reason,
            "top_reason_label_fr": REASON_LABELS_FR.get(top_reason, top_reason),
            "reasons": v["reasons"],
        })

    return {
        "total": len(rows),
        "by_reason": by_reason_list,
        "by_destination": by_destination_list,
        "by_hour_utc": [{"hour": h, "count": c} for h, c in sorted(by_hour_count.items())],
        "by_reason_hour": [
            {"reason_code": r, "hour": h, "count": c}
            for (r, h), c in by_reason_hour.items()
        ],
        "since": since,
        "until": until,
    }


# ── Drops silencieux : les reason codes privés (2026-08-04) ────────────────
#
# Les codes commençant par "_" ne produisaient AUCUNE trace. Or c'est
# `_not_admitted` qui bloquait 85 % des signaux Kraken, et `_not_a_star` qui
# a empêché les Voies A/B de trader une seule action pendant leurs premiers
# jours. Dans les deux cas : pas de push, pas de rejet, rien à voir dans les
# logs. Une destination pouvait rester morte des semaines en silence.
#
# ⚠️ On ne les enregistre PAS ligne par ligne. Ces codes se déclenchent sur la
# grande majorité des tentatives de dispatch (~30 000/jour, toutes
# destinations confondues) et noieraient la table. Une ligne individuelle
# n'apporte d'ailleurs rien de plus que le tuple lui-même : on agrège par
# jour dans un compteur, ce qui répond exactement à la question posée —
# « cette destination est-elle silencieusement morte ? ».

SILENT_REASON_LABELS_FR = {
    "_not_configured": "Bridge non configuré",
    "_user_excluded_pair": "Paire exclue pour ce user",
    "_not_admitted": "Paire non admise à l'auto-exec",
    "_not_a_star": "Hors portefeuille stars (fallback legacy)",
}


def _ensure_silent_schema() -> None:
    with sqlite3.connect(_db_path()) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS silent_drop_counters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                destination_id TEXT,
                pair TEXT,
                direction TEXT,
                reason_code TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                first_at TEXT,
                last_at TEXT,
                UNIQUE (day, destination_id, pair, direction, reason_code)
            )
        """)
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_sdc_day ON silent_drop_counters(day)"
        )


def record_silent_drop(
    pair: str | None,
    direction: str | None,
    reason_code: str,
    destination_id: str | None = None,
) -> None:
    """Incrémente le compteur du jour pour ce drop silencieux.

    ⚠️ Le compteur mesure des **tentatives de dispatch**, pas des idées de
    trade distinctes. Le radar réémet le même setup à chaque cycle (~6 min)
    tant que le bar n'a pas changé, donc un même signal compte plusieurs
    dizaines de fois. À lire comme un signal de vie, pas comme un volume.

    Best-effort : toute erreur est avalée, comme `record_rejection`.
    """
    try:
        _ensure_silent_schema()
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(_db_path()) as c:
            c.execute(
                """
                INSERT INTO silent_drop_counters
                    (day, destination_id, pair, direction, reason_code,
                     count, first_at, last_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT (day, destination_id, pair, direction, reason_code)
                DO UPDATE SET count = count + 1, last_at = excluded.last_at
                """,
                (now[:10], destination_id, pair, direction, reason_code, now, now),
            )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("record_silent_drop failed (silencé)")


def get_silent_drops(since_day: str, until_day: str) -> dict[str, Any]:
    """Agrège les drops silencieux sur une plage de jours (bornes incluses).

    Retourne ``{"total", "by_destination", "by_reason", "since", "until"}``
    où ``by_destination`` porte, par destination, le volume et le motif
    dominant — de quoi repérer d'un coup d'œil une destination qui ne laisse
    rien passer.
    """
    _ensure_silent_schema()
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT destination_id, pair, reason_code, count, last_at "
            "  FROM silent_drop_counters WHERE day >= ? AND day <= ?",
            (since_day, until_day),
        ).fetchall()

    by_dest: dict[str, dict[str, Any]] = {}
    by_reason: dict[str, int] = {}
    total = 0
    for r in rows:
        n = r["count"] or 0
        total += n
        dest = r["destination_id"] or "(inconnu)"
        e = by_dest.setdefault(dest, {"count": 0, "reasons": {}, "pairs": {}, "last_at": None})
        e["count"] += n
        e["reasons"][r["reason_code"]] = e["reasons"].get(r["reason_code"], 0) + n
        if r["pair"]:
            e["pairs"][r["pair"]] = e["pairs"].get(r["pair"], 0) + n
        if r["last_at"] and (e["last_at"] is None or r["last_at"] > e["last_at"]):
            e["last_at"] = r["last_at"]
        by_reason[r["reason_code"]] = by_reason.get(r["reason_code"], 0) + n

    by_destination = []
    for dest, v in sorted(by_dest.items(), key=lambda kv: -kv[1]["count"]):
        top = max(v["reasons"].items(), key=lambda kv: kv[1])[0]
        by_destination.append({
            "destination_id": dest,
            "count": v["count"],
            "top_reason": top,
            "top_reason_label_fr": SILENT_REASON_LABELS_FR.get(top, top),
            "reasons": v["reasons"],
            "pairs": v["pairs"],
            "last_at": v["last_at"],
        })

    return {
        "total": total,
        "by_destination": by_destination,
        "by_reason": [
            {
                "reason_code": k,
                "label_fr": SILENT_REASON_LABELS_FR.get(k, k),
                "count": v,
            }
            for k, v in sorted(by_reason.items(), key=lambda kv: -kv[1])
        ],
        "since": since_day,
        "until": until_day,
    }
