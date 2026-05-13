"""Auto-régulateur PnL par pair sur fenêtre glissante.

Complément de `stop_loss_alerts` qui détecte les rafales courtes (≥ 3 SL
en 1h). Ce module-ci capture le **saignement chronique diffus** invisible
au watchdog rafale : ex XAG/USD = 53 SL sur 6 semaines (~1.3 SL/jour)
qui n'a jamais déclenché 3 SL en 1h mais a accumulé -783€ (cf audit
2026-05-13).

## Mécanisme

Sur fenêtre glissante de N derniers trades (default 30) :
- Si `sum_pnl / capital < pause_threshold_pct` (default -3%) → pause 14j
- Si pair pausée et expires_at < now → resume (laisse re-trader, ré-évaluera)
- Sample minimum requis : MIN_SAMPLE trades (default 10) pour éviter
  faux positifs sur sample bias

Auto-resume : pas de smart resume basé sur V1 quiet (cf stop_loss_alerts)
parce que le saignement chronique n'a pas de "rafale qui s'arrête" — on
laisse le pair re-trader après 14j et on observe.

## Hystérésis vs flapping

Pas de logique anti-flapping spéciale : sur 14 jours de cool-off,
même si le pair re-trade et perd 1-2 trades juste après resume,
il faut atteindre le seuil cumul -3% pour re-pause. Donc le cycle naturel
pause → 14j → resume → drift jusqu'à -3% → re-pause limite l'oscillation.

## Auto-pause vs MT5_BRIDGE_BLOCKED_PAIRS

Les deux co-existent. `MT5_BRIDGE_BLOCKED_PAIRS` = override manuel
permanent (env var). `auto_paused_pairs` = décisions auto révisées
toutes les heures. Le bridge check les deux en cascade ; n'importe lequel
qui bloque → "pair_blocked" ou "pair_auto_paused".
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _db_path() -> str:
    from backend.services.trade_log_service import _DB_PATH

    return str(_DB_PATH)


# ─── Schema ─────────────────────────────────────────────────────────────


_SCHEMA_ENSURED = False


def _ensure_schema() -> None:
    """Crée la table auto_paused_pairs si pas déjà là.

    Idempotent. Appelé au premier accès dans le process.
    """
    global _SCHEMA_ENSURED
    if _SCHEMA_ENSURED:
        return
    with sqlite3.connect(_db_path()) as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS auto_paused_pairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT NOT NULL,
                paused_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                reason TEXT NOT NULL,
                pnl_pct REAL,
                trades_in_window INTEGER,
                resumed_at TEXT,
                resumed_reason TEXT
            )
            """
        )
        c.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_app_pair_active
              ON auto_paused_pairs(pair) WHERE resumed_at IS NULL
            """
        )
    _SCHEMA_ENSURED = True


# ─── Configuration ──────────────────────────────────────────────────────


def _config() -> dict[str, Any]:
    """Lit la config depuis settings (env vars overrides possibles)."""
    from config.settings import (
        PAIR_PNL_REGULATOR_ENABLED,
        PAIR_PNL_REGULATOR_WINDOW_TRADES,
        PAIR_PNL_REGULATOR_MIN_SAMPLE,
        PAIR_PNL_REGULATOR_PAUSE_THRESHOLD_PCT,
        PAIR_PNL_REGULATOR_PAUSE_DURATION_DAYS,
        TRADING_CAPITAL,
    )
    return {
        "enabled": PAIR_PNL_REGULATOR_ENABLED,
        "window_trades": PAIR_PNL_REGULATOR_WINDOW_TRADES,
        "min_sample": PAIR_PNL_REGULATOR_MIN_SAMPLE,
        "pause_threshold_pct": PAIR_PNL_REGULATOR_PAUSE_THRESHOLD_PCT,
        "pause_duration_days": PAIR_PNL_REGULATOR_PAUSE_DURATION_DAYS,
        "capital": TRADING_CAPITAL,
    }


# ─── Core metrics ───────────────────────────────────────────────────────


def compute_window_metrics(pair: str, window_trades: int) -> dict[str, Any]:
    """Retourne PnL agrégé sur les N derniers trades auto-exec fermés du pair.

    Si moins de N trades existent, retourne ce qu'il y a (sample peut être < N).
    """
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            """
            SELECT pnl, closed_at
              FROM personal_trades
             WHERE pair = ? AND status = 'CLOSED'
               AND is_auto = 1 AND pnl IS NOT NULL
             ORDER BY closed_at DESC LIMIT ?
            """,
            (pair, window_trades),
        ).fetchall()
    n = len(rows)
    if n == 0:
        return {"n": 0, "sum_pnl": 0.0, "wins": 0, "wr": 0.0, "oldest_at": None, "newest_at": None}
    sum_pnl = sum(r["pnl"] for r in rows)
    wins = sum(1 for r in rows if r["pnl"] > 0)
    return {
        "n": n,
        "sum_pnl": round(sum_pnl, 2),
        "wins": wins,
        "wr": round(100.0 * wins / n, 1),
        "oldest_at": rows[-1]["closed_at"],
        "newest_at": rows[0]["closed_at"],
    }


# ─── Pause state ────────────────────────────────────────────────────────


def get_active_pause(pair: str) -> dict[str, Any] | None:
    """Retourne la pause active (resumed_at IS NULL) ou None."""
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            """
            SELECT * FROM auto_paused_pairs
             WHERE pair = ? AND resumed_at IS NULL
             ORDER BY id DESC LIMIT 1
            """,
            (pair,),
        ).fetchone()
    return dict(row) if row else None


def is_paused(pair: str) -> bool:
    """True si pair a une pause active non expirée."""
    pause = get_active_pause(pair)
    if not pause:
        return False
    try:
        expires = datetime.fromisoformat(pause["expires_at"].replace("Z", "+00:00"))
        return expires > datetime.now(timezone.utc)
    except (ValueError, AttributeError, KeyError):
        return True  # safe default : si parsing foire, on garde paused


def list_active_pauses() -> list[dict[str, Any]]:
    """Liste les pauses actives pour le dashboard admin."""
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT * FROM auto_paused_pairs WHERE resumed_at IS NULL ORDER BY paused_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def apply_pause(pair: str, reason: str, pnl_pct: float, trades_count: int) -> int:
    """INSERT row pause. Idempotent : si déjà active, retourne l'id existant."""
    _ensure_schema()
    existing = get_active_pause(pair)
    if existing:
        logger.debug(f"pair_pnl_regulator: {pair} already paused (id={existing['id']})")
        return existing["id"]
    cfg = _config()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=cfg["pause_duration_days"])
    with sqlite3.connect(_db_path()) as c:
        cur = c.execute(
            """
            INSERT INTO auto_paused_pairs
                (pair, paused_at, expires_at, reason, pnl_pct, trades_in_window)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (pair, now.isoformat(), expires.isoformat(), reason, pnl_pct, trades_count),
        )
        new_id = cur.lastrowid
    logger.warning(
        f"pair_pnl_regulator: PAUSED {pair} pnl_pct={pnl_pct:.2f}% "
        f"n={trades_count} until={expires.isoformat()}"
    )
    return new_id


def apply_resume(pair: str, reason: str) -> bool:
    """UPDATE row active : resumed_at + resumed_reason. Retourne True si effectif."""
    _ensure_schema()
    existing = get_active_pause(pair)
    if not existing:
        return False
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(_db_path()) as c:
        c.execute(
            """
            UPDATE auto_paused_pairs
               SET resumed_at = ?, resumed_reason = ?
             WHERE id = ?
            """,
            (now, reason, existing["id"]),
        )
    logger.warning(
        f"pair_pnl_regulator: RESUMED {pair} reason={reason} (was paused at {existing['paused_at']})"
    )
    return True


# ─── Decision logic ─────────────────────────────────────────────────────


def evaluate_pair(pair: str) -> dict[str, Any]:
    """Décide pour un pair : pause, resume, keep_paused, keep_active.

    Retourne {action, metrics, reason}.
    """
    cfg = _config()
    if not cfg["enabled"]:
        return {"action": "disabled", "metrics": {}, "reason": "regulator off"}

    metrics = compute_window_metrics(pair, cfg["window_trades"])
    pnl_pct = 100.0 * metrics["sum_pnl"] / cfg["capital"] if metrics["n"] > 0 else 0.0
    metrics["pnl_pct"] = round(pnl_pct, 2)

    # Pause active prioritaire sur tout autre check : un pair pausé sans
    # nouveaux trades doit rester pausé (cas froid). Le check no_data ne
    # s'applique que si pas de pause en cours.
    pause = get_active_pause(pair)
    now = datetime.now(timezone.utc)

    if pause:
        try:
            expires = datetime.fromisoformat(pause["expires_at"].replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            expires = now  # parse fail → consider expired

        if expires <= now:
            apply_resume(pair, "expired_re_evaluate")
            return {
                "action": "resume",
                "metrics": metrics,
                "reason": "pause expired, re-evaluate next cycle",
            }
        return {
            "action": "keep_paused",
            "metrics": metrics,
            "reason": f"paused until {pause['expires_at']}",
        }

    if metrics["n"] == 0:
        return {"action": "no_data", "metrics": metrics, "reason": "no trades"}

    # Pas paused : check si on devrait pause
    if metrics["n"] < cfg["min_sample"]:
        return {
            "action": "keep_active",
            "metrics": metrics,
            "reason": f"sample too small (n={metrics['n']} < {cfg['min_sample']})",
        }

    if pnl_pct < cfg["pause_threshold_pct"]:
        apply_pause(pair, "ev_negative", pnl_pct, metrics["n"])
        return {
            "action": "pause",
            "metrics": metrics,
            "reason": f"pnl_pct {pnl_pct:.2f}% < threshold {cfg['pause_threshold_pct']:.2f}%",
        }

    return {"action": "keep_active", "metrics": metrics, "reason": "healthy"}


def check_and_regulate() -> dict[str, Any]:
    """Job scheduler + startup : évalue tous les pairs stars, applique.

    Retourne summary pour debug/tests.
    """
    cfg = _config()
    if not cfg["enabled"]:
        return {"enabled": False, "decisions": []}

    # On évalue les stars auto-exec + tous les pairs qui ont déjà été tradés
    # (pour gérer le cas où un pair est désactivé des stars mais a une pause
    # active à libérer après expiration).
    from backend.services.shadow_v2_core_long import SHADOW_PAIRS as _STAR_PAIRS

    pairs_to_check = set(_STAR_PAIRS)
    # Ajouter les pairs qui ont une pause active (au cas où retirés des stars)
    for p in list_active_pauses():
        pairs_to_check.add(p["pair"])

    decisions = []
    for pair in sorted(pairs_to_check):
        try:
            d = evaluate_pair(pair)
            d["pair"] = pair
            decisions.append(d)
        except Exception:
            logger.exception(f"pair_pnl_regulator: evaluate {pair} failed")

    summary = {
        "enabled": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "n_checked": len(decisions),
        "n_paused": sum(1 for d in decisions if d["action"] == "pause"),
        "n_resumed": sum(1 for d in decisions if d["action"] == "resume"),
        "n_keep_paused": sum(1 for d in decisions if d["action"] == "keep_paused"),
        "n_keep_active": sum(1 for d in decisions if d["action"] == "keep_active"),
        "decisions": decisions,
    }
    logger.info(
        f"pair_pnl_regulator: check_and_regulate n_checked={summary['n_checked']} "
        f"paused={summary['n_paused']} resumed={summary['n_resumed']} "
        f"keep_paused={summary['n_keep_paused']}"
    )
    return summary
