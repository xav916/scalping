"""Moteur de backtest V1 — replay du scoring sur historique OHLC.

Objectif : valider si le scoring a un vrai edge AVANT tout passage live.

Principe :
1. Charge 1h + 5min candles de la DB historique (backtest_candles.db).
2. À chaque bar 1h clos, reconstruit volatility (ATR ratio) + trend (EMA
   slope) à partir de l'historique disponible AU MOMENT T (pas de look-ahead).
3. Appelle `detect_patterns` + `calculate_trade_setup` — les fonctions live
   sont réutilisables, elles dépendent uniquement des candles.
4. Applique les mêmes filtres que le bridge (`_should_push` : SL distance
   par asset class, confidence threshold).
5. Simule l'évolution forward du trade avec les 5min candles : SL ou TP hit
   d'abord ? Timeout à 24h → close au prix courant = MANUAL.
6. Enregistre dans `backtest_trades` + agrège stats (win rate, Sharpe,
   equity curve, drawdown).

Limites V1 connues :
- Pas d'events macro historiques (ForexFactory) → liste vide.
- Pas de macro snapshot historique (VIX/SPX/DXY) → macro multiplier = 1.
- Intra-bar : si SL et TP touchés dans le même 5min bar, on prend SL
  (worst-case, conservateur).
- Spread + slippage modélisés par un coût fixe en pips au moment du fill.

V2+ : enrichir avec macro reconstitué, backtest walk-forward par trimestre,
comparaison scoring heuristique vs ML.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from backend.models.schemas import (
    Candle,
    MarketTrend,
    TradeDirection,
    TradeSetup,
    TrendDirection,
    VolatilityData,
    VolatilityLevel,
)
from backend.services.pattern_detector import (
    calculate_trade_setup,
    detect_patterns,
    _calculate_atr,
)

# ─── Config ─────────────────────────────────────────────────────────────────

DEFAULT_DB = Path("/opt/scalping/data/backtest_candles.db")

# Seuils et constantes (inspirés du live)
SCORING_THRESHOLD = 55.0  # MT5_BRIDGE_MIN_CONFIDENCE live
TIMEOUT_HOURS = 24

# Slippage + spread conservateur (1.5 pips équivalent sur forex 5dp)
SPREAD_SLIPPAGE_PCT = 0.0002  # 0.02% = ~2.3 pips sur EUR/USD


# ─── Résultat d'un trade simulé ─────────────────────────────────────────────


Outcome = Literal["TP1", "SL", "TIMEOUT"]


@dataclass
class SimulatedTrade:
    pair: str
    direction: str
    entry_at: str     # ISO UTC
    entry_price: float
    stop_loss: float
    take_profit: float
    exit_at: str
    exit_price: float
    outcome: Outcome
    pnl_pips: float
    pnl_pct: float    # en % du prix d'entrée
    confidence: float
    pattern: str


# ─── Chargement candles ─────────────────────────────────────────────────────


def load_candles(
    db_path: Path, pair: str, interval: str,
    start: datetime | None = None, end: datetime | None = None,
) -> list[Candle]:
    """Charge les candles de la DB historique. Tri ASC par timestamp.

    Les timestamps en DB viennent de Twelve Data au format 'YYYY-MM-DD HH:MM:SS'
    en UTC (paramètre timezone=UTC fourni à l'API dans fetch_historical_backtest).
    """
    query = (
        "SELECT timestamp, open, high, low, close, volume "
        "  FROM candles_historical "
        " WHERE pair = ? AND interval = ?"
    )
    params: list = [pair, interval]
    if start:
        query += " AND timestamp >= ?"
        params.append(start.strftime("%Y-%m-%d %H:%M:%S"))
    if end:
        query += " AND timestamp <= ?"
        params.append(end.strftime("%Y-%m-%d %H:%M:%S"))
    query += " ORDER BY timestamp ASC"
    with sqlite3.connect(db_path) as c:
        rows = c.execute(query, params).fetchall()
    return [
        Candle(
            timestamp=datetime.fromisoformat(r[0]).replace(tzinfo=timezone.utc),
            open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5] or 0,
        )
        for r in rows
    ]


# ─── Reconstruction volatility + trend à partir des candles ────────────────


def compute_volatility(candles_1h: list[Candle], pair: str) -> VolatilityData:
    """Volatility via ATR : current (14-bar) vs average (50-bar). Ratio
    classe en LOW/MEDIUM/HIGH."""
    if len(candles_1h) < 15:
        return VolatilityData(
            pair=pair,
            current_volatility=0.0, average_volatility=0.0,
            volatility_ratio=1.0, level=VolatilityLevel.MEDIUM,
            timeframe="1H", updated_at=candles_1h[-1].timestamp if candles_1h else datetime.now(timezone.utc),
        )
    recent = candles_1h[-15:]
    atr_current = _calculate_atr(recent, period=14)
    # Baseline : fenêtre plus large, EXCLUT la fenêtre récente pour que le
    # ratio reflète vraiment "spike vs calme d'avant" et pas "calme + spike
    # vs calme + spike" (même série des deux côtés).
    older = candles_1h[:-15]
    baseline = older[-50:] if len(older) >= 50 else older
    if len(baseline) >= 15:
        atr_baseline = _calculate_atr(baseline, period=14)
    else:
        atr_baseline = atr_current  # pas assez d'historique → ratio 1.0
    ratio = atr_current / atr_baseline if atr_baseline > 0 else 1.0
    if ratio >= 1.3:
        level = VolatilityLevel.HIGH
    elif ratio >= 0.7:
        level = VolatilityLevel.MEDIUM
    else:
        level = VolatilityLevel.LOW
    return VolatilityData(
        pair=pair,
        current_volatility=atr_current,
        average_volatility=atr_baseline,
        volatility_ratio=round(ratio, 3),
        level=level,
        timeframe="1H",
        updated_at=candles_1h[-1].timestamp,
    )


def _ema(values: list[float], period: int) -> float:
    """Dernier EMA d'une série."""
    if not values or period <= 0:
        return 0.0
    k = 2 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def compute_trend(candles_1h: list[Candle], pair: str) -> MarketTrend:
    """Trend via crossover EMA rapide (10) vs lente (30). Force = magnitude
    relative du spread. Seuils ±0.2% pour départager neutral."""
    if len(candles_1h) < 30:
        return MarketTrend(
            pair=pair, direction=TrendDirection.NEUTRAL, strength=0.0,
            description="insufficient data",
            updated_at=candles_1h[-1].timestamp if candles_1h else datetime.now(timezone.utc),
        )
    closes = [c.close for c in candles_1h]
    ema_fast = _ema(closes[-30:], 10)
    ema_slow = _ema(closes[-30:], 30)
    if ema_slow <= 0:
        direction, strength = TrendDirection.NEUTRAL, 0.0
    else:
        spread = (ema_fast - ema_slow) / ema_slow
        if spread > 0.002:
            direction = TrendDirection.BULLISH
        elif spread < -0.002:
            direction = TrendDirection.BEARISH
        else:
            direction = TrendDirection.NEUTRAL
        strength = min(1.0, abs(spread) * 100)
    return MarketTrend(
        pair=pair, direction=direction, strength=round(strength, 3),
        description=f"EMA10={ema_fast:.4f} vs EMA30={ema_slow:.4f}",
        updated_at=candles_1h[-1].timestamp,
    )


# ─── Scoring simplifié (pas de macro en V1) ────────────────────────────────


def score_setup(
    setup: TradeSetup,
    volatility: VolatilityData,
    trend: MarketTrend,
) -> float:
    """Score simplifié à partir du setup + volatility + trend.

    Replique l'esprit du scoring live mais sans macro/events. Le but n'est
    pas d'être identique mais d'être cohérent : si live dit score élevé,
    backtest aussi.

    - Base : 40 points pour un pattern haute confiance
    - + jusqu'à 25 points si trend alignée avec direction
    - + jusqu'à 20 points si volatility medium/high
    - + jusqu'à 15 points si R:R favorable (>= 2)
    """
    score = 0.0

    # Pattern confidence (40 max)
    score += min(40.0, setup.pattern.confidence * 50)

    # Trend alignement (25 max)
    is_buy = setup.direction == TradeDirection.BUY
    if trend.direction == TrendDirection.BULLISH and is_buy:
        score += trend.strength * 25
    elif trend.direction == TrendDirection.BEARISH and not is_buy:
        score += trend.strength * 25

    # Volatility (20 max)
    if volatility.level == VolatilityLevel.HIGH:
        score += 20
    elif volatility.level == VolatilityLevel.MEDIUM:
        score += 12
    else:
        score += 4

    # R:R (15 max)
    if setup.take_profit_1 and setup.stop_loss and setup.entry_price:
        risk = abs(setup.entry_price - setup.stop_loss)
        reward = abs(setup.take_profit_1 - setup.entry_price)
        if risk > 0:
            rr = reward / risk
            score += min(15.0, rr * 5)

    return round(min(100.0, score), 1)


# ─── Simulation d'un trade forward ─────────────────────────────────────────


def simulate_trade_forward(
    setup: TradeSetup,
    candles_5min: list[Candle],
    entry_time: datetime,
    timeout_hours: int = TIMEOUT_HOURS,
) -> tuple[Outcome, datetime, float]:
    """Forward simulation depuis entry_time. Retourne (outcome, exit_time,
    exit_price).

    Règle intra-bar : si SL et TP touchés dans le même 5min, on prend SL
    (worst-case conservateur).
    """
    end_time = entry_time + timedelta(hours=timeout_hours)
    is_buy = setup.direction == TradeDirection.BUY
    sl = setup.stop_loss
    tp = setup.take_profit_1

    last_candle: Candle | None = None
    for c in candles_5min:
        if c.timestamp <= entry_time:
            continue
        if c.timestamp > end_time:
            break
        last_candle = c

        # Détection hit intra-bar (high/low du 5min)
        sl_hit = c.low <= sl if is_buy else c.high >= sl
        tp_hit = c.high >= tp if is_buy else c.low <= tp

        if sl_hit and tp_hit:
            # Worst-case : on assume que SL a été touché d'abord
            return ("SL", c.timestamp, sl)
        if sl_hit:
            return ("SL", c.timestamp, sl)
        if tp_hit:
            return ("TP1", c.timestamp, tp)

    # Timeout : close au dernier prix connu
    if last_candle:
        return ("TIMEOUT", last_candle.timestamp, last_candle.close)
    # Pas de candle dans la fenêtre (weekend ?) → pas de trade
    return ("TIMEOUT", entry_time, setup.entry_price)


def compute_pnl(
    setup: TradeSetup, exit_price: float, spread_slippage_pct: float = SPREAD_SLIPPAGE_PCT
) -> tuple[float, float]:
    """PnL en (pips, pct). Applique un coût fixe spread+slippage en %."""
    is_buy = setup.direction == TradeDirection.BUY
    entry = setup.entry_price
    if is_buy:
        gross_pct = (exit_price - entry) / entry
    else:
        gross_pct = (entry - exit_price) / entry
    net_pct = gross_pct - spread_slippage_pct  # coûts fixes
    # Pips : pour forex 5dp = pct × 10000, pour JPY 3dp = pct × 100
    pair = setup.pair
    is_jpy = "JPY" in pair.upper()
    pip_factor = 100 if is_jpy else 10000
    # Approximation métaux / crypto / indices : on met pips = abs diff × 10
    base = pair.split("/")[0].upper() if "/" in pair else pair.upper()
    if base in {"XAU", "XAG"} or base in {"BTC", "ETH"} or base in {"SPX", "NDX"}:
        pip_factor = 10
    pips = (exit_price - entry) * pip_factor if is_buy else (entry - exit_price) * pip_factor
    return round(pips, 2), round(net_pct * 100, 4)


# ─── Schéma backtest_trades ────────────────────────────────────────────────


def ensure_schema(db_path: Path) -> None:
    with sqlite3.connect(db_path) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS backtest_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                pair TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_at TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                exit_at TEXT NOT NULL,
                exit_price REAL NOT NULL,
                outcome TEXT NOT NULL,
                pnl_pips REAL,
                pnl_pct REAL,
                confidence REAL,
                pattern TEXT
            )
        """)
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_bt_runid_entry "
            "ON backtest_trades(run_id, entry_at)"
        )


# ─── Boucle principale ─────────────────────────────────────────────────────


def run_backtest(
    db_path: Path,
    pair: str,
    start: datetime,
    end: datetime,
    threshold: float = SCORING_THRESHOLD,
    run_id: str | None = None,
    dedup_hours: float = 1.0,
) -> list[SimulatedTrade]:
    """Run un backtest complet sur une pair entre start et end.

    Retourne la liste des trades simulés et les enregistre en DB.
    `dedup_hours` : ne re-déclenche pas le même signal pour la même pair
    dans cette fenêtre (évite le spam).
    """
    ensure_schema(db_path)
    run_id = run_id or f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    candles_1h = load_candles(db_path, pair, "1h", start=start, end=end)
    candles_5min = load_candles(db_path, pair, "5min", start=start, end=end)

    if len(candles_1h) < 30:
        return []  # pas assez de data pour scorer

    trades: list[SimulatedTrade] = []
    last_trade_at: datetime | None = None
    dedup_delta = timedelta(hours=dedup_hours)

    # On commence après 30 bars (warm-up pour EMA/ATR)
    for i in range(30, len(candles_1h)):
        now = candles_1h[i].timestamp
        history = candles_1h[: i + 1]  # inclut la bar qui vient de clôturer

        # Dedup : pas 2 trades dans la même fenêtre
        if last_trade_at and (now - last_trade_at) < dedup_delta:
            continue

        volatility = compute_volatility(history, pair)
        trend = compute_trend(history, pair)
        patterns = detect_patterns(history, pair)
        if not patterns:
            continue

        # Meilleur pattern seulement
        best = patterns[0]
        setup = calculate_trade_setup(pair, best, history)
        if not setup:
            continue

        score = score_setup(setup, volatility, trend)
        if score < threshold:
            continue

        # Simule l'évolution
        outcome, exit_time, exit_price = simulate_trade_forward(
            setup, candles_5min, now
        )
        pips, pct = compute_pnl(setup, exit_price)

        trade = SimulatedTrade(
            pair=pair,
            direction=setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction),
            entry_at=now.isoformat(),
            entry_price=setup.entry_price,
            stop_loss=setup.stop_loss,
            take_profit=setup.take_profit_1,
            exit_at=exit_time.isoformat(),
            exit_price=exit_price,
            outcome=outcome,
            pnl_pips=pips,
            pnl_pct=pct,
            confidence=score,
            pattern=best.pattern.value if hasattr(best.pattern, "value") else str(best.pattern),
        )
        trades.append(trade)
        last_trade_at = now

    # Bulk insert
    with sqlite3.connect(db_path) as c:
        c.executemany(
            """
            INSERT INTO backtest_trades
                (run_id, pair, direction, entry_at, entry_price, stop_loss,
                 take_profit, exit_at, exit_price, outcome, pnl_pips, pnl_pct,
                 confidence, pattern)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (run_id, t.pair, t.direction, t.entry_at, t.entry_price,
                 t.stop_loss, t.take_profit, t.exit_at, t.exit_price,
                 t.outcome, t.pnl_pips, t.pnl_pct, t.confidence, t.pattern)
                for t in trades
            ],
        )

    return trades


def summarize(trades: list[SimulatedTrade]) -> dict:
    """Stats d'une run de backtest. Win rate, Sharpe, drawdown, PnL cumul."""
    if not trades:
        return {"n": 0, "message": "aucun trade"}
    n = len(trades)
    wins = sum(1 for t in trades if t.outcome == "TP1")
    losses = sum(1 for t in trades if t.outcome == "SL")
    timeouts = sum(1 for t in trades if t.outcome == "TIMEOUT")
    pnls = [t.pnl_pct for t in trades]
    cumul = [sum(pnls[: i + 1]) for i in range(n)]
    peak = 0.0
    max_dd = 0.0
    for c in cumul:
        peak = max(peak, c)
        dd = peak - c
        max_dd = max(max_dd, dd)
    # Sharpe approximatif (ratio mean / std, annualisé à la louche ×252)
    if n > 1:
        mean = sum(pnls) / n
        var = sum((p - mean) ** 2 for p in pnls) / (n - 1)
        std = var ** 0.5
        sharpe = (mean / std) * (252 ** 0.5) if std > 0 else 0.0
    else:
        sharpe = 0.0
    return {
        "n": n,
        "wins": wins,
        "losses": losses,
        "timeouts": timeouts,
        "win_rate_pct": round(100 * wins / n, 2),
        "pnl_total_pct": round(sum(pnls), 3),
        "avg_pnl_pct": round(sum(pnls) / n, 4),
        "max_drawdown_pct": round(max_dd, 3),
        "sharpe_approx": round(sharpe, 2),
        "by_outcome": {"TP1": wins, "SL": losses, "TIMEOUT": timeouts},
    }
