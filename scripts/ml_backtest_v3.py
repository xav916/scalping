#!/usr/bin/env python3
"""Backtest V3 — re-run du backtest V1 avec le modèle ML intégré comme
filtre / score additionnel.

Objectif : mesurer le **delta** entre :
- V1 : scoring heuristique seul (pattern + volatility + trend + R:R)
- V3 : scoring heuristique + filtre/boost ML (si proba TP >= threshold)

Calcule les mêmes stats que le V1 pour comparaison directe : WR, PnL cumul,
Sharpe, max DD. Sort un rapport JSON side-by-side.

Usage :
    sudo docker exec scalping-radar python3 /app/scripts/ml_backtest_v3.py \\
        --db /app/data/backtest_candles.db \\
        --model /app/data/ml_model.joblib \\
        --report /app/data/ml_backtest_v3_report.json \\
        --ml-threshold 0.55
"""
from __future__ import annotations
import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.models.schemas import Candle, TradeDirection
from backend.services.backtest_engine import (
    compute_volatility, compute_trend, score_setup,
    simulate_trade_forward, compute_pnl, load_candles,
    SCORING_THRESHOLD,
)
from backend.services.pattern_detector import detect_patterns, calculate_trade_setup

# Réutilise extraction features pour passer au modèle
from scripts.ml_extract_features import extract_features, pattern_value  # type: ignore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bt_v3")


DEFAULT_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD",
    "EUR/JPY", "GBP/JPY", "EUR/GBP",
    "XAU/USD", "XAG/USD",
    "BTC/USD", "ETH/USD",
]


def run_pair(
    db_path: Path, pair: str, start: datetime, end: datetime,
    model_bundle: dict | None, ml_threshold: float,
    scoring_threshold: float = SCORING_THRESHOLD,
) -> dict:
    """Run backtest V3 sur 1 pair. Retourne stats globales et séparées V1/V3."""
    candles_1h = load_candles(db_path, pair, "1h", start=start, end=end)
    candles_5min = load_candles(db_path, pair, "5min", start=start, end=end)
    if len(candles_1h) < 30:
        return {"pair": pair, "n_v1": 0, "n_v3": 0, "message": "insufficient candles"}

    # Flags par trade pour ML filter
    trades_v1 = []  # tous les setups qui passent le scoring heuristique
    trades_v3 = []  # sous-ensemble qui passe ALSO le ML filter

    model = model_bundle["model"] if model_bundle else None
    feature_cols = model_bundle["feature_cols"] if model_bundle else []

    import numpy as np
    dedup_delta = timedelta(hours=1)
    last_trade_at = None

    for i in range(30, len(candles_1h)):
        now = candles_1h[i].timestamp
        if last_trade_at and (now - last_trade_at) < dedup_delta:
            continue
        history = candles_1h[: i + 1]

        vol = compute_volatility(history, pair)
        trend = compute_trend(history, pair)
        patterns = detect_patterns(history, pair)
        if not patterns:
            continue
        best = patterns[0]
        setup = calculate_trade_setup(pair, best, history)
        if not setup:
            continue

        score = score_setup(setup, vol, trend)
        if score < scoring_threshold:
            continue

        # Forward simulation identique au V1
        direction_str = setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction)
        outcome, exit_time, exit_price = simulate_trade_forward(setup, candles_5min, now)
        pips, pct = compute_pnl(setup, exit_price)

        trade_record = {
            "entry_at": now.isoformat(),
            "outcome": outcome,
            "pnl_pct": pct,
            "score_heur": score,
        }
        trades_v1.append(trade_record)

        # V3 : ML filter
        if model is not None and feature_cols:
            feats = extract_features(
                history, pattern_value(best.pattern), direction_str,
                setup.entry_price, setup.stop_loss, setup.take_profit_1, pair,
            )
            if feats:
                row = [float(feats.get(c, 0) or 0) for c in feature_cols]
                try:
                    proba = float(model.predict_proba([row])[0][1])
                except Exception:
                    proba = 0.5
                trade_record["ml_proba"] = proba
                if proba >= ml_threshold:
                    trades_v3.append(trade_record)

        last_trade_at = now

    return {
        "pair": pair,
        "v1": summarize(trades_v1),
        "v3": summarize(trades_v3),
    }


def summarize(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0}
    n = len(trades)
    wins = sum(1 for t in trades if t["outcome"] == "TP1")
    pnls = [t["pnl_pct"] for t in trades]
    cumul_pnl = sum(pnls)
    peak = 0.0
    max_dd = 0.0
    running = 0.0
    for p in pnls:
        running += p
        peak = max(peak, running)
        max_dd = max(max_dd, peak - running)
    if n > 1:
        mean = cumul_pnl / n
        var = sum((p - mean) ** 2 for p in pnls) / (n - 1)
        std = var ** 0.5
        sharpe = (mean / std) * (252 ** 0.5) if std > 0 else 0.0
    else:
        sharpe = 0.0
    return {
        "n": n,
        "wins": wins,
        "win_rate_pct": round(100 * wins / n, 2),
        "pnl_cumul_pct": round(cumul_pnl, 3),
        "avg_pnl_pct": round(cumul_pnl / n, 4),
        "sharpe": round(sharpe, 2),
        "max_dd_pct": round(max_dd, 3),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/app/data/backtest_candles.db")
    ap.add_argument("--model", default="/app/data/ml_model.joblib")
    ap.add_argument("--report", default="/app/data/ml_backtest_v3_report.json")
    ap.add_argument("--days", type=int, default=1095)
    ap.add_argument("--ml-threshold", type=float, default=0.55)
    ap.add_argument("--pair")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        log.error(f"DB absente: {db_path}")
        sys.exit(1)

    model_bundle = None
    if Path(args.model).exists():
        import joblib
        model_bundle = joblib.load(args.model)
        log.info(f"Model chargé : {args.model} (auc={model_bundle.get('test_auc')})")
    else:
        log.warning(f"Pas de modèle à {args.model} — V3 = V1 (pas de filtre ML)")

    pairs = [args.pair] if args.pair else DEFAULT_PAIRS
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=args.days)

    log.info(f"Backtest V3 : {len(pairs)} pairs, {start.date()}→{end.date()}, ml_thr={args.ml_threshold}")

    results = []
    for pair in pairs:
        log.info(f"═══ {pair} ═══")
        r = run_pair(db_path, pair, start, end, model_bundle, args.ml_threshold)
        results.append(r)
        v1 = r.get("v1", {})
        v3 = r.get("v3", {})
        log.info(
            f"  V1: n={v1.get('n', 0)} wr={v1.get('win_rate_pct', 0)}% "
            f"pnl={v1.get('pnl_cumul_pct', 0)}% sharpe={v1.get('sharpe', 0)} | "
            f"V3: n={v3.get('n', 0)} wr={v3.get('win_rate_pct', 0)}% "
            f"pnl={v3.get('pnl_cumul_pct', 0)}% sharpe={v3.get('sharpe', 0)}"
        )

    # Agrégat global
    global_v1 = {"n": 0, "wins": 0, "pnl": 0.0}
    global_v3 = {"n": 0, "wins": 0, "pnl": 0.0}
    for r in results:
        v1 = r.get("v1", {})
        v3 = r.get("v3", {})
        global_v1["n"] += v1.get("n", 0)
        global_v1["wins"] += v1.get("wins", 0)
        global_v1["pnl"] += v1.get("pnl_cumul_pct", 0)
        global_v3["n"] += v3.get("n", 0)
        global_v3["wins"] += v3.get("wins", 0)
        global_v3["pnl"] += v3.get("pnl_cumul_pct", 0)

    def _wr(d):
        return round(100 * d["wins"] / d["n"], 2) if d["n"] else 0.0

    report = {
        "ml_threshold": args.ml_threshold,
        "model_path": str(args.model),
        "by_pair": results,
        "global_v1": {**global_v1, "win_rate_pct": _wr(global_v1)},
        "global_v3": {**global_v3, "win_rate_pct": _wr(global_v3)},
        "delta": {
            "pnl_pct": round(global_v3["pnl"] - global_v1["pnl"], 2),
            "wr_pct": round(_wr(global_v3) - _wr(global_v1), 2),
            "n_reduction_pct": round(
                100 * (1 - global_v3["n"] / global_v1["n"]), 2
            ) if global_v1["n"] else 0,
        },
    }

    Path(args.report).write_text(json.dumps(report, indent=2))
    log.info(f"Report → {args.report}")
    log.info(
        f"═══ GLOBAL ═══ V1: n={global_v1['n']} wr={_wr(global_v1)}% pnl={global_v1['pnl']:.1f}% | "
        f"V3: n={global_v3['n']} wr={_wr(global_v3)}% pnl={global_v3['pnl']:.1f}%"
    )


if __name__ == "__main__":
    main()
