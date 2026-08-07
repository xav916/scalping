"""Phase 4 — Reconciliation des outcomes des shadow setups.

Pour chaque setup en `outcome IS NULL`, résout l'outcome en simulant le
forward sur les bougies 5min depuis bar_timestamp.

Depuis 2026-08-04, la tentative est **anticipée** : dès qu'un TP ou un SL a
été touché, l'outcome est enregistré, sans attendre la fin de la fenêtre.
Seule l'étiquette TIMEOUT exige que la fenêtre complète soit écoulée — c'est
la seule conclusion qu'on ne peut pas tirer par anticipation.

Motivation : l'outcome se calcule en rejouant l'historique, il est donc
connaissable bien avant l'échéance. Mesure sur 16802 setups H1 résolus,
p50 = 0.1h et p75 = 5.2h : la moitié des trades se dénouaient en 6 minutes
et attendaient pourtant 4 jours pour être enregistrés. Aucun outcome n'est
modifié par ce changement, seule la latence de feedback.

Source des 5min :
  - **Prod live** : refetch via Twelve Data au moment de la reconcile
    (price_service.fetch_candles ; ~96h × 12 = 1150 candles ≈ 1 req TD)
  - **Local / dev** : possible de fournir une DB SQLite alternative via
    `_macro_veto_analysis/backtest_candles.db` qui contient les 5min
    historiques jusqu'à 2026-04-22

Le job est conçu pour être appelé périodiquement (ex: toutes les 1h depuis
cockpit_broadcast_cycle) et est idempotent (UPDATE WHERE outcome IS NULL
seulement).

Spec : docs/superpowers/specs/2026-04-25-phase4-shadow-log-spec.md
"""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dataclasses import dataclass

from backend.models.schemas import Candle, TradeDirection
from backend.services.backtest_engine import (
    compute_pnl,
    excursions_pct,
    simulate_trade_forward,
)
from backend.services.shadow_v2_core_long import DB_PATH, ensure_schema


@dataclass
class _MinimalSetup:
    """Stub léger compatible avec simulate_trade_forward + compute_pnl.

    TradeSetup complet a ~30 champs requis (pattern, risk_pips, message,
    confidence_factors...) qu'on n'a pas besoin de reconstituer juste pour
    la simulation forward. Ces 5 champs suffisent.
    """
    pair: str
    direction: TradeDirection
    entry_price: float
    stop_loss: float
    take_profit_1: float

logger = logging.getLogger(__name__)


# Forward timeout par timeframe — proportionnel à la taille de bougie.
# H4 : 24 bars × 4h = 96h (4 jours)
# 1d : 10 bars × 24h = 240h (10 jours), couverture 5min OK depuis 2023-04
TIMEOUT_HOURS_BY_TF: dict[str, int] = {"1h": 96, "4h": 96, "1d": 240}
TIMEOUT_HOURS_DEFAULT = 96  # H4 fallback pour rows sans timeframe explicite

# "1h" est explicite depuis 2026-08-04 : il représente 98,6% des rows
# (20726/21012) et tombait silencieusement sur TIMEOUT_HOURS_DEFAULT. La
# valeur reste 96h — la changer reclasserait en TIMEOUT des milliers de TP/SL
# historiques et casserait la comparabilité. C'est la *latence* qui était le
# vrai problème, pas la durée de la fenêtre (cf. EARLY_RECONCILE_HOURS).

# Cutoff SQL = le plus court possible (pour pas exclure du SELECT des setups
# H4 prêts juste parce que les Daily n'ont pas encore atteint leur 240h).
# La logique par-TF est appliquée dans la boucle Python.
TIMEOUT_HOURS_MIN = min(TIMEOUT_HOURS_BY_TF.values())

# Réconciliation anticipée (2026-08-04).
#
# Avant : un setup n'était même pas *regardé* avant 96h, alors que l'outcome
# est calculé en rejouant les bougies — donc parfaitement connaissable bien
# plus tôt. Mesure sur 16802 setups H1 résolus : p50 = 0.1h, p75 = 5.2h. La
# moitié des trades se dénouaient en 6 minutes et attendaient 4 jours pour
# être enregistrés.
#
# Maintenant : on tente dès EARLY_RECONCILE_HOURS. Un TP/SL touché est
# enregistré immédiatement ; un setup encore ouvert reste pending et n'est
# étiqueté TIMEOUT qu'une fois sa fenêtre réellement écoulée. Aucun outcome
# n'est modifié — seule la latence de feedback change.
EARLY_RECONCILE_HOURS = float(os.getenv("SHADOW_EARLY_RECONCILE_HOURS", "2"))

# Fenêtre d'éligibilité du SELECT : la plus courte des deux.
SELECT_CUTOFF_HOURS = min(EARLY_RECONCILE_HOURS, TIMEOUT_HOURS_MIN)

SPREAD_SLIPPAGE_PCT = 0.0002  # 0.02%, identique au backtest


# ─── Récupération des candles 5min ──────────────────────────────────────────


async def fetch_5min_for_window(
    pair: str,
    start: datetime,
    end: datetime,
) -> list[Candle]:
    """Récupère les bougies 5min pour la fenêtre [start, end].

    Stratégie :
    1. Tente le price_service (live, via Twelve Data)
    2. Fallback sur la DB locale `_macro_veto_analysis/backtest_candles.db`
       si présente (utile pour test local / backfill historique)
    """
    # Stratégie 1 : live via price_service
    try:
        from backend.services.price_service import fetch_candles
        # outputsize approx : 96h × 12 candles/h = 1152 + marge
        candles, _is_simulated = await fetch_candles(pair, interval="5min", outputsize=1500)
        # Filter by window
        windowed = [c for c in candles if start <= c.timestamp <= end]
        if windowed:
            return windowed
    except Exception as e:
        logger.debug(f"reconcile fetch live 5min {pair}: {e}")

    # Stratégie 2 : fallback DB locale (dev / backfill)
    fallback_db = Path("_macro_veto_analysis/backtest_candles.db")
    if not fallback_db.exists():
        return []
    with sqlite3.connect(fallback_db) as c:
        rows = c.execute(
            """
            SELECT timestamp, open, high, low, close, volume
              FROM candles_historical
             WHERE pair = ? AND interval = '5min'
               AND timestamp >= ? AND timestamp <= ?
             ORDER BY timestamp
            """,
            (pair, start.strftime("%Y-%m-%d %H:%M:%S"),
             end.strftime("%Y-%m-%d %H:%M:%S")),
        ).fetchall()
    return [
        Candle(
            timestamp=datetime.fromisoformat(r[0]).replace(tzinfo=timezone.utc),
            open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5] or 0,
        )
        for r in rows
    ]


# ─── Reconstruction TradeSetup minimal pour simulate_trade_forward ──────────


def _setup_from_row(row: dict) -> _MinimalSetup:
    """Construit un stub léger pour simulate_trade_forward."""
    return _MinimalSetup(
        pair=row["pair"],
        direction=TradeDirection(row["direction"]),
        entry_price=row["entry_price"],
        stop_loss=row["stop_loss"],
        take_profit_1=row["take_profit_1"],
    )


# ─── Job principal ──────────────────────────────────────────────────────────


async def reconcile_pending_setups(
    max_per_run: int = 50,
    fetch_5min_fn=None,
) -> dict[str, int]:
    """Résout les setups en pending dont le timeout est dépassé.

    Args:
        max_per_run: cap pour éviter rate limit TD si beaucoup de pending
        fetch_5min_fn: injectable pour test (override fetch_5min_for_window)

    Returns:
        dict de stats : {resolved, skipped_no_data, errors}
    """
    ensure_schema()
    fetch_fn = fetch_5min_fn or fetch_5min_for_window

    now = datetime.now(timezone.utc)

    # Sélection en deux temps, pour garantir la progression de la file.
    #
    # Une tentative anticipée peut ne rien conclure (trade encore ouvert) et
    # sera rejouée au run suivant. Si on mélangeait les deux populations dans
    # une seule requête, un setup destiné au TIMEOUT monopoliserait un slot à
    # chaque run pendant ~94h. On sert donc d'abord les lignes échues — qui
    # aboutissent toujours, donc vident la file de façon monotone — et on
    # n'utilise pour l'anticipation que les slots restants.
    matured_cutoff = now - timedelta(hours=TIMEOUT_HOURS_MIN)
    early_cutoff = now - timedelta(hours=SELECT_CUTOFF_HOURS)

    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = list(c.execute(
            """
            SELECT * FROM shadow_setups
             WHERE outcome IS NULL
               AND bar_timestamp <= ?
             ORDER BY bar_timestamp ASC
             LIMIT ?
            """,
            (matured_cutoff.isoformat(), max_per_run),
        ).fetchall())

        spare = max_per_run - len(rows)
        if spare > 0:
            rows += list(c.execute(
                """
                SELECT * FROM shadow_setups
                 WHERE outcome IS NULL
                   AND bar_timestamp <= ?
                   AND bar_timestamp > ?
                 ORDER BY bar_timestamp ASC
                 LIMIT ?
                """,
                (early_cutoff.isoformat(), matured_cutoff.isoformat(), spare),
            ).fetchall())

    if not rows:
        # Pas de pending résolvable, mais peut-être des pending pas encore au timeout
        with sqlite3.connect(DB_PATH) as c:
            remaining = c.execute(
                "SELECT COUNT(*) FROM shadow_setups WHERE outcome IS NULL"
            ).fetchone()[0]
        return {
            "resolved": 0, "skipped_no_data": 0, "errors": 0,
            "still_open": 0, "pending_remaining": remaining,
        }

    stats = {"resolved": 0, "skipped_no_data": 0, "errors": 0, "still_open": 0}

    # Cache des bougies pour ce run. Clé exacte (pair, début, fin) : les
    # setups d'un même cycle sur une même paire partagent leur bar_timestamp
    # (typiquement le buy et le sell générés au même instant), donc la même
    # fenêtre. Évite de refetcher la même série deux fois.
    candle_cache: dict[tuple[str, str, str], list[Candle]] = {}

    for r in rows:
        setup_dict = dict(r)
        bar_ts = datetime.fromisoformat(setup_dict["bar_timestamp"]).replace(tzinfo=timezone.utc) \
            if "T" in setup_dict["bar_timestamp"] else \
            datetime.fromisoformat(setup_dict["bar_timestamp"]).replace(tzinfo=timezone.utc)

        # Timeout par TF (Daily plus long que H4)
        tf = setup_dict.get("timeframe", "4h")
        timeout_hours = TIMEOUT_HOURS_BY_TF.get(tf, TIMEOUT_HOURS_DEFAULT)

        # Le setup a-t-il atteint le bout de sa fenêtre ? Si non, on peut
        # quand même constater un TP/SL déjà touché — mais surtout pas
        # conclure à un TIMEOUT, le trade ayant encore le temps de se dénouer.
        matured = bar_ts <= now - timedelta(hours=timeout_hours)

        # On ne demande jamais de bougies au-delà de maintenant.
        end_ts = min(bar_ts + timedelta(hours=timeout_hours), now)

        cache_key = (setup_dict["pair"], bar_ts.isoformat(), end_ts.isoformat())
        try:
            if cache_key in candle_cache:
                candles_5min = candle_cache[cache_key]
            else:
                candles_5min = await fetch_fn(setup_dict["pair"], bar_ts, end_ts)
                candle_cache[cache_key] = candles_5min
        except Exception as e:
            logger.warning(f"reconcile fetch failed {setup_dict['pair']} {bar_ts}: {e}")
            stats["errors"] += 1
            continue

        if not candles_5min:
            stats["skipped_no_data"] += 1
            continue

        try:
            setup = _setup_from_row(setup_dict)
            outcome, exit_time, exit_price = simulate_trade_forward(
                setup, candles_5min, bar_ts, timeout_hours=timeout_hours,
            )
            # simulate_trade_forward renvoie TIMEOUT dès qu'il épuise les
            # bougies sans hit. Sur une fenêtre encore ouverte, ce TIMEOUT
            # signifie juste « pas encore dénoué » — l'enregistrer figerait un
            # faux verdict. On laisse pending, le prochain run réessaiera.
            if outcome == "TIMEOUT" and not matured:
                stats["still_open"] += 1
                continue

            pips, pct_net = compute_pnl(setup, exit_price, spread_slippage_pct=SPREAD_SLIPPAGE_PCT)
            position_eur = setup_dict["sizing_position_eur"]
            pnl_eur = position_eur * (pct_net / 100.0)

            # Excursions maximales sur la fenêtre RÉELLEMENT tenue (2026-08-07).
            # Calculées sur les mêmes bougies, donc sans requête ni coût
            # supplémentaire. Sans elles on savait qu'un take-profit n'était
            # jamais atteint, sans pouvoir dire de combien il manquait — donc
            # sans pouvoir le calibrer. Ne peuvent pas faire échouer la
            # réconciliation : en cas d'anomalie on enregistre NULL, qui veut
            # dire « non mesuré », pas « nul ».
            try:
                mfe_pct, mae_pct = excursions_pct(
                    setup, candles_5min, bar_ts, exit_time)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"reconcile: excursions {setup_dict['pair']}: {e}")
                mfe_pct = mae_pct = None

            with sqlite3.connect(DB_PATH) as c:
                c.execute(
                    """
                    UPDATE shadow_setups
                       SET outcome = ?, exit_at = ?, exit_price = ?,
                           pnl_pct_net = ?, pnl_eur = ?,
                           mfe_pct = ?, mae_pct = ?
                     WHERE id = ?
                    """,
                    (outcome, exit_time.isoformat(), exit_price,
                     pct_net, pnl_eur, mfe_pct, mae_pct, setup_dict["id"]),
                )
            stats["resolved"] += 1
            logger.info(
                f"reconcile {setup_dict['pair']} {bar_ts.date()} "
                f"→ {outcome} pnl={pct_net:+.2f}% ({pnl_eur:+.0f}€)"
            )
        except Exception as e:
            logger.warning(f"reconcile simulate failed {setup_dict['pair']} {bar_ts}: {e}")
            stats["errors"] += 1
            continue

    # Combien restent pending ?
    with sqlite3.connect(DB_PATH) as c:
        remaining = c.execute(
            "SELECT COUNT(*) FROM shadow_setups WHERE outcome IS NULL"
        ).fetchone()[0]
    stats["pending_remaining"] = remaining

    return stats


# ─── CLI standalone (test/backfill manuel) ──────────────────────────────────


async def _async_main(args):
    stats = await reconcile_pending_setups(max_per_run=args.max)
    print(f"Reconcile: {stats}")


def main():
    import argparse
    p = argparse.ArgumentParser(description="Phase 4 reconcile shadow setups")
    p.add_argument("--max", type=int, default=50, help="Max setups à résoudre par run")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
