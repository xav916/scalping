"""Backtest de la stratégie meanrev sur ticks historiques (ticks_courtier.db).

Utilise les MÊMES helpers que ``meanrev_trader`` en live (imports partagés)
pour garantir que le backtest mesure la vraie stratégie, pas une
approximation. Deux choses sont **recodées localement** et pas importées :

1. ``_compute_vwap_for_day`` : le live calcule le VWAP du jour UTC *courant*
   via ``date.today()``. Au backtest on veut le VWAP d'un jour simulé, donc
   on le paramétrise (même logique : moyenne des typicals (H+L+C)/3 des
   bougies 15min dont la date UTC == ``day``).

2. ``_simulate_exit`` : recode la politique de sortie (SL → TP → time stop
   4h → data_end) sur un flux de ticks, parce que le live ne l'implémente
   que via du polling à cadence 15min (pas tick-par-tick).

Agrège les ticks ``(pair, ts_utc, ms, bid, ask)`` en bougies OHLC 1h et
15min (mid = (bid+ask)/2), puis pour chaque bougie 15min terminée évalue
``_detect_regime`` + ``_detect_trigger`` ; si setup valide, simule l'exit
tick par tick et collecte le trade.
"""
from __future__ import annotations

import dataclasses
import logging
import math
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Iterator

from backend.models.schemas import Candle
from backend.services.meanrev_trader import (
    _compute_atr,
    _compute_atr_series,
    _compute_bbw_series,
    _contract_size,
    _detect_regime,
    _detect_trigger,
    _percentile_rank,
    _sl_from_trigger,
    _size_lots_from_risk,
    ATR_EXPANSION_MIN,
    BBW_PERCENTILE_MIN,
    EUR_USD_RATE,
    RISK_PCT,
    TIME_STOP_MINUTES,
    TRIGGER_CANDLE_MULT,
)

logger = logging.getLogger(__name__)


# ─── Modèles de résultat ────────────────────────────────────────────────

@dataclasses.dataclass
class Trade:
    """Une position virtuelle backtestée avec son résultat."""
    pair: str
    direction: str  # "buy" ou "sell"
    entry_time_utc: datetime
    entry_price: float
    sl: float
    tp: float  # VWAP du jour au moment de l'entrée
    exit_time_utc: datetime
    exit_price: float
    exit_reason: str  # "tp" | "sl" | "time_stop_4h" | "data_end"
    lots: float
    pnl_usd: float


@dataclasses.dataclass
class FunnelStats:
    """Diagnostic du pipeline de détection setup.

    Ne se peuple qu'en mode ``debug=True``. Les 3 critères (BBW percentile,
    ATR expansion, trigger amplitude+reversal) sont évalués **séparément**
    sur chaque bougie 15min pour mesurer le taux de pass de chacun et de
    leurs intersections — là où la boucle normale short-circuite dès qu'un
    critère rate.
    """
    n_candles_15m_evaluated: int
    # Compteurs par critère (chacun seul)
    n_pass_bbw: int
    n_pass_atr: int
    n_pass_trigger: int
    # Compteurs intersections 2 à 2
    n_pass_bbw_and_atr: int
    n_pass_bbw_and_trigger: int
    n_pass_atr_and_trigger: int
    # Triple AND = nombre de setups que la strat détecterait
    n_pass_all_three: int
    # Distributions observées (p10, p25, p50, p75, p90, p95, p99, max)
    bbw_percentile_quantiles: dict[int, float]
    atr_expansion_quantiles: dict[int, float]
    trigger_mult_quantiles: dict[int, float]
    # Seuils utilisés pour cette évaluation (actuellement les constantes live)
    bbw_threshold_used: float
    atr_threshold_used: float
    trigger_threshold_used: float
    # Suggestions de seuils (via _suggest_thresholds)
    suggested_thresholds: dict[int, dict]


@dataclasses.dataclass
class BacktestResults:
    pair: str
    from_dt: datetime
    to_dt: datetime
    n_ticks: int
    n_candles_1h: int
    n_candles_15m: int
    n_setups_detected: int
    trades: list[Trade]
    funnel: FunnelStats | None = None

    @property
    def pnl_total_usd(self) -> float:
        return sum(t.pnl_usd for t in self.trades)

    @property
    def winrate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.pnl_usd > 0)
        return wins / len(self.trades)

    @property
    def profit_factor(self) -> float:
        gains = sum(t.pnl_usd for t in self.trades if t.pnl_usd > 0)
        losses = -sum(t.pnl_usd for t in self.trades if t.pnl_usd < 0)
        if losses == 0:
            return float("inf") if gains > 0 else 0.0
        return gains / losses

    @property
    def max_drawdown_usd(self) -> float:
        """Max drawdown en USD sur la courbe d'equity cumulée."""
        if not self.trades:
            return 0.0
        trades_sorted = sorted(self.trades, key=lambda t: t.exit_time_utc)
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in trades_sorted:
            equity += t.pnl_usd
            if equity > peak:
                peak = equity
            dd = equity - peak  # <= 0
            if dd < max_dd:
                max_dd = dd
        return max_dd

    @property
    def sharpe_ratio(self) -> float:
        """Sharpe simple sur les PnL par trade (pas annualisé)."""
        if len(self.trades) < 2:
            return 0.0
        pnls = [t.pnl_usd for t in self.trades]
        mean = sum(pnls) / len(pnls)
        var = sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1)
        std = math.sqrt(var)
        if std == 0:
            return 0.0
        return mean / std

    @property
    def breakdown(self) -> dict[str, int]:
        out = {"tp": 0, "sl": 0, "time_stop_4h": 0, "data_end": 0}
        for t in self.trades:
            out[t.exit_reason] = out.get(t.exit_reason, 0) + 1
        return out


# ─── Chargement + agrégation ────────────────────────────────────────────

def _load_ticks(
    db_path: str, pair: str, from_dt: datetime, to_dt: datetime,
) -> Iterator[tuple[datetime, float, float]]:
    """Streaming lazy des ticks. Rend (ts_as_datetime, bid, ask)."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.execute(
            "SELECT ts_utc, ms, bid, ask FROM ticks "
            "WHERE pair = ? AND ts_utc BETWEEN ? AND ? "
            "ORDER BY ts_utc, ms",
            (pair, from_dt.isoformat(), to_dt.isoformat()),
        )
        for ts_utc_str, ms, bid, ask in cur:
            ts = datetime.fromisoformat(ts_utc_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ms:
                ts = ts + timedelta(microseconds=int(ms) * 1000)
            yield ts, float(bid), float(ask)
    finally:
        con.close()


def _aggregate_candles(
    ticks: Iterator[tuple[datetime, float, float]],
    timeframe_minutes: int,
) -> list[Candle]:
    """Agrège un stream de (ts, bid, ask) en bougies OHLC (mid).

    Bucket d'une bougie = minute arrondie au bas de la fenêtre
    (ex: 15min → minutes {0,15,30,45}).
    """
    candles: list[Candle] = []
    current_start: datetime | None = None
    o = h = l = c = 0.0

    for ts, bid, ask in ticks:
        mid = (bid + ask) / 2.0
        minute = ts.minute - (ts.minute % timeframe_minutes)
        bucket_start = ts.replace(minute=minute, second=0, microsecond=0)

        if current_start is None or bucket_start > current_start:
            if current_start is not None:
                candles.append(Candle(
                    timestamp=current_start, open=o, high=h, low=l, close=c,
                ))
            current_start = bucket_start
            o = h = l = c = mid
        else:
            if mid > h:
                h = mid
            if mid < l:
                l = mid
            c = mid

    if current_start is not None:
        candles.append(Candle(
            timestamp=current_start, open=o, high=h, low=l, close=c,
        ))
    return candles


def _compute_vwap_for_day(candles_15min: list[Candle], day: date) -> float | None:
    """Variante backtest de ``_compute_vwap_today`` : paramétrisée sur ``day``.

    La logique est identique au live (moyenne des typicals (H+L+C)/3 pour
    les bougies dont la date UTC == day), mais le live utilise
    ``date.today()`` qui n'a pas de sens en backtest.
    """
    today_candles = []
    for c in candles_15min:
        ts = c.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        if ts.date() == day:
            today_candles.append(c)
    if not today_candles:
        return None
    typicals = [(float(c.high) + float(c.low) + float(c.close)) / 3.0 for c in today_candles]
    return sum(typicals) / len(typicals)


# ─── Simulation exit ────────────────────────────────────────────────────

def _simulate_exit(
    entry_ts: datetime,
    direction: str,
    sl: float,
    tp: float,
    future_ticks: Iterator[tuple[datetime, float, float]],
    time_stop_minutes: int = TIME_STOP_MINUTES,
) -> tuple[datetime, float, str]:
    """Replay des ticks futurs. Retourne (exit_ts, exit_price, reason).

    Convention direction :
      - "buy"  : SL si bid <= sl (close au bid), TP si bid >= tp
      - "sell" : SL si ask >= sl (close à l'ask), TP si ask <= tp

    Priorité à chaque tick : SL check d'abord puis TP (pessimiste).
    Si aucun des 2 n'est touché dans la fenêtre time_stop → close au dernier
    tick connu avec reason="time_stop_4h". Si le flux s'épuise avant →
    "data_end" sur le dernier tick vu.
    """
    deadline = entry_ts + timedelta(minutes=time_stop_minutes)
    last_ts = entry_ts
    last_exit_price = (sl + tp) / 2.0  # fallback rarement utilisé

    for ts, bid, ask in future_ticks:
        if ts <= entry_ts:
            continue
        last_ts = ts
        if direction == "buy":
            last_exit_price = bid
            if bid <= sl:
                return ts, sl, "sl"
            if bid >= tp:
                return ts, tp, "tp"
        else:
            last_exit_price = ask
            if ask >= sl:
                return ts, sl, "sl"
            if ask <= tp:
                return ts, tp, "tp"
        if ts >= deadline:
            return ts, last_exit_price, "time_stop_4h"

    return last_ts, last_exit_price, "data_end"


# ─── Replay principal ───────────────────────────────────────────────────

def _pnl_usd(direction: str, entry: float, exit_price: float, lots: float, pair: str) -> float:
    """PnL en USD : (delta prix) × contract_size(pair) × lots.

    ⛔ Bug historique fixé 2026-11-12 : utilisait hardcoded 100000 (forex)
    pour toutes les classes d'asset, amplifiant le PnL XAU/USD d'un facteur
    1000× (100 oz × 1000 = 100000). Résultat du backtest : -46K USD pour un
    risque autorisé de 8 USD × 7 trades. Corrigé en utilisant _contract_size
    comme _size_lots_from_risk (même logique miroir).
    """
    cs = _contract_size(pair)
    if direction == "buy":
        return (exit_price - entry) * cs * lots
    return (entry - exit_price) * cs * lots


# ─── Quantiles + suggestion de seuils ───────────────────────────────────

def _quantile(values: list[float], percentile: float) -> float:
    """Retourne la valeur au ``percentile`` donné (0-100) par interpolation linéaire."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if percentile <= 0:
        return sorted_vals[0]
    if percentile >= 100:
        return sorted_vals[-1]
    idx = (percentile / 100.0) * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _compute_quantiles(values: list[float]) -> dict[int, float]:
    """Pack standard de quantiles (p10, p25, p50, p75, p90, p95, p99, 100)."""
    return {p: _quantile(values, p) for p in (10, 25, 50, 75, 90, 95, 99, 100)}


def _suggest_thresholds(
    bbw_vals: list[float],
    atr_vals: list[float],
    trigger_mult_vals: list[float],
    reversal_flags: list[bool],
    targets: list[int],
) -> dict[int, dict]:
    """Pour chaque N cible, suggère un triplet (bbw, atr, trigger) tel que
    leur intersection donne ~N setups.

    Hypothèse de travail (optimiste) : indépendance entre les 3 critères.
    Le trigger inclut une condition reversal, on estime empiriquement sa
    fréquence via les flags reçus.

    Approche : viser ``p_combined = N / total``, répartir équitablement en
    cube root sur les 3 critères, puis pour le trigger diviser par la
    fréquence observée du reversal pour obtenir le seuil d'amplitude
    attendu. On lit ensuite la valeur réelle au quantile correspondant.
    """
    total = len(bbw_vals)
    if total == 0 or not targets:
        return {}

    p_reversal = sum(reversal_flags) / total if reversal_flags else 0.25
    if p_reversal == 0:
        p_reversal = 0.25  # fallback pour éviter division par zéro

    out: dict[int, dict] = {}
    for n_target in targets:
        p_combined = n_target / total
        if p_combined <= 0:
            continue
        p_individual = p_combined ** (1 / 3)
        # Pour bbw et atr : seuil = quantile tel que (1 - p_individual) le dépasse
        bbw_threshold = _quantile(bbw_vals, (1 - p_individual) * 100)
        atr_threshold = _quantile(atr_vals, (1 - p_individual) * 100)
        # Trigger : le critère effectif est amplitude × reversal, donc on
        # ajuste pour isoler l'amplitude seule.
        p_amplitude = min(1.0, p_individual / p_reversal)
        trig_threshold = _quantile(trigger_mult_vals, (1 - p_amplitude) * 100)

        # Sanity : recompte sur les valeurs réelles pour donner une
        # estimation plus honnête (contre l'hypothèse d'indépendance).
        new_bbw_rate = sum(1 for v in bbw_vals if v > bbw_threshold) / total
        new_atr_rate = sum(1 for v in atr_vals if v > atr_threshold) / total
        new_amplitude_rate = sum(1 for v in trigger_mult_vals if v > trig_threshold) / total
        estim_setups = round(
            total * new_bbw_rate * new_atr_rate * new_amplitude_rate * p_reversal
        )

        out[n_target] = {
            "bbw_pct": round(bbw_threshold, 1),
            "atr_mult": round(atr_threshold, 2),
            "trigger_mult": round(trig_threshold, 2),
            "expected_setups": estim_setups,
        }
    return out


def _is_reversal_pair(trigger_candle: Candle, last_candle: Candle) -> bool:
    """La paire (trigger, last) forme-t-elle un pattern reversal ?

    Réplique la condition interne de ``_detect_trigger`` :
      - trigger baissière (close<open) suivie de last haussière (close>open) → reversal BUY
      - trigger haussière (close>open) suivie de last baissière (close<open) → reversal SELL
    """
    t_open, t_close = float(trigger_candle.open), float(trigger_candle.close)
    l_open, l_close = float(last_candle.open), float(last_candle.close)
    bullish_rev = (t_close < t_open) and (l_close > l_open)
    bearish_rev = (t_close > t_open) and (l_close < l_open)
    return bullish_rev or bearish_rev


def run_backtest(
    pair: str,
    from_dt: datetime,
    to_dt: datetime,
    db_path: str = "/app/data/ticks_courtier.db",
    capital_eur: float = 1600.0,
    risk_pct: float | None = None,
    debug: bool = False,
) -> BacktestResults:
    """Replay complet. Si risk_pct est None, utilise RISK_PCT du live (0.5%).

    Si ``debug=True``, collecte les stats du funnel de détection (combien de
    bougies passent chaque critère seul et en intersection) + les
    distributions observées + des suggestions de seuils pour atteindre des
    nombres cibles de setups.
    """
    # Note : _size_lots_from_risk lit la const RISK_PCT du module meanrev_trader.
    # Si le caller veut un risk_pct custom, on scale manuellement les lots après.
    risk_scale = 1.0
    if risk_pct is not None:
        risk_scale = (risk_pct / 100.0) / RISK_PCT

    # 1. Charger les ticks en mémoire une seule fois (lazy itérateur épuisable).
    # On a besoin de deux passes : agrégation candles + simulation exits.
    # Pour XAU/USD sur 2 mois on parle de ~14M ticks ≈ 500 MB en Python.
    # On accepte le coût mémoire plutôt que relire 2× depuis sqlite.
    ticks_list = list(_load_ticks(db_path, pair, from_dt, to_dt))
    n_ticks = len(ticks_list)
    if n_ticks == 0:
        return BacktestResults(
            pair=pair, from_dt=from_dt, to_dt=to_dt,
            n_ticks=0, n_candles_1h=0, n_candles_15m=0,
            n_setups_detected=0, trades=[],
        )

    # 2. Agréger en candles 1h et 15min
    candles_1h = _aggregate_candles(iter(ticks_list), 60)
    candles_15m = _aggregate_candles(iter(ticks_list), 15)

    # 3. Pour chaque bougie 15min terminée (sauf les 2 dernières = manque reversal),
    #    évaluer régime (fenêtre 100 bougies 1h) + trigger (15min).
    #    Pour éviter le lookahead : on utilise UNIQUEMENT les candles dont
    #    timestamp <= current_candle.timestamp.
    trades: list[Trade] = []
    n_setups = 0
    seen_entries: set[datetime] = set()

    # Collecteurs pour le funnel diagnostic (remplis si debug=True)
    n_evaluated = 0
    n_pass_bbw = 0
    n_pass_atr = 0
    n_pass_trigger = 0
    n_pass_bbw_and_atr = 0
    n_pass_bbw_and_trigger = 0
    n_pass_atr_and_trigger = 0
    n_pass_all_three = 0
    bbw_vals: list[float] = []
    atr_vals: list[float] = []
    trigger_mult_vals: list[float] = []
    reversal_flags: list[bool] = []

    for i in range(2, len(candles_15m)):
        current_candle = candles_15m[i]
        current_ts = current_candle.timestamp
        if current_ts.tzinfo is None:
            current_ts = current_ts.replace(tzinfo=timezone.utc)

        # Candles 1h visibles à current_ts (dernière qui finit avant current_ts)
        visible_1h = [c for c in candles_1h if c.timestamp <= current_ts]
        if len(visible_1h) < 50:
            continue
        # On utilise les 100 dernières pour match la logique live
        regime_candles = visible_1h[-100:]

        bbw_pct, atr_exp, regime_ok = _detect_regime(regime_candles)

        # Trigger : les 3 dernières 15m visibles (current + 2 précédentes)
        visible_15m = candles_15m[: i + 1]
        if len(visible_15m) < 3:
            # Pas de contexte suffisant → ne compte pas dans le funnel
            if regime_ok:
                # Early-skip path (jamais atteint vu i>=2 mais défensif)
                continue
            continue
        atr_15min = _compute_atr(visible_15m, period=14)
        if not atr_15min:
            continue

        # ─── Collecte pour le funnel ────────────────────────────────────
        # Chaque critère évalué séparément, SANS short-circuit, pour voir
        # la vraie distribution et l'intersection.
        if debug:
            trigger_candle = visible_15m[-2]
            last_candle = visible_15m[-1]
            amplitude = float(trigger_candle.high) - float(trigger_candle.low)
            trigger_mult = amplitude / atr_15min if atr_15min > 0 else 0.0
            reversal = _is_reversal_pair(trigger_candle, last_candle)

            n_evaluated += 1
            bbw_vals.append(bbw_pct)
            atr_vals.append(atr_exp)
            trigger_mult_vals.append(trigger_mult)
            reversal_flags.append(reversal)

            pass_bbw = bbw_pct > BBW_PERCENTILE_MIN
            pass_atr = atr_exp > ATR_EXPANSION_MIN
            pass_trigger = (trigger_mult > TRIGGER_CANDLE_MULT) and reversal

            if pass_bbw:
                n_pass_bbw += 1
            if pass_atr:
                n_pass_atr += 1
            if pass_trigger:
                n_pass_trigger += 1
            if pass_bbw and pass_atr:
                n_pass_bbw_and_atr += 1
            if pass_bbw and pass_trigger:
                n_pass_bbw_and_trigger += 1
            if pass_atr and pass_trigger:
                n_pass_atr_and_trigger += 1
            if pass_bbw and pass_atr and pass_trigger:
                n_pass_all_three += 1
        # ────────────────────────────────────────────────────────────────

        if not regime_ok:
            continue

        trigger = _detect_trigger(visible_15m, atr_15min)
        if trigger is None:
            continue

        n_setups += 1
        entry_ts = current_ts
        if entry_ts in seen_entries:
            continue
        seen_entries.add(entry_ts)

        entry = float(trigger["entry"])
        sl = _sl_from_trigger(trigger, atr_15min)

        # TP = VWAP du jour au moment de l'entrée
        vwap = _compute_vwap_for_day(visible_15m, entry_ts.date())
        if vwap is None:
            continue
        tp = vwap

        # Sanity : si direction buy mais tp < entry, ou sell mais tp > entry,
        # le VWAP est "derrière" (le prix s'est déjà réverté). Skip.
        if trigger["direction"] == "buy" and tp <= entry:
            continue
        if trigger["direction"] == "sell" and tp >= entry:
            continue

        lots = _size_lots_from_risk(capital_eur, entry, sl, pair) * risk_scale
        if lots <= 0:
            continue
        lots = round(lots, 2)

        # Simulate exit sur les ticks futurs
        future_ticks = (t for t in ticks_list if t[0] > entry_ts)
        exit_ts, exit_price, reason = _simulate_exit(
            entry_ts=entry_ts,
            direction=trigger["direction"],
            sl=sl,
            tp=tp,
            future_ticks=future_ticks,
            time_stop_minutes=TIME_STOP_MINUTES,
        )

        pnl = _pnl_usd(trigger["direction"], entry, exit_price, lots, pair)
        trades.append(Trade(
            pair=pair,
            direction=trigger["direction"],
            entry_time_utc=entry_ts,
            entry_price=entry,
            sl=sl,
            tp=tp,
            exit_time_utc=exit_ts,
            exit_price=exit_price,
            exit_reason=reason,
            lots=lots,
            pnl_usd=pnl,
        ))

    funnel: FunnelStats | None = None
    if debug:
        suggestions = _suggest_thresholds(
            bbw_vals=bbw_vals,
            atr_vals=atr_vals,
            trigger_mult_vals=trigger_mult_vals,
            reversal_flags=reversal_flags,
            targets=[5, 10, 20, 50],
        )
        funnel = FunnelStats(
            n_candles_15m_evaluated=n_evaluated,
            n_pass_bbw=n_pass_bbw,
            n_pass_atr=n_pass_atr,
            n_pass_trigger=n_pass_trigger,
            n_pass_bbw_and_atr=n_pass_bbw_and_atr,
            n_pass_bbw_and_trigger=n_pass_bbw_and_trigger,
            n_pass_atr_and_trigger=n_pass_atr_and_trigger,
            n_pass_all_three=n_pass_all_three,
            bbw_percentile_quantiles=_compute_quantiles(bbw_vals),
            atr_expansion_quantiles=_compute_quantiles(atr_vals),
            trigger_mult_quantiles=_compute_quantiles(trigger_mult_vals),
            bbw_threshold_used=BBW_PERCENTILE_MIN,
            atr_threshold_used=ATR_EXPANSION_MIN,
            trigger_threshold_used=TRIGGER_CANDLE_MULT,
            suggested_thresholds=suggestions,
        )

    return BacktestResults(
        pair=pair,
        from_dt=from_dt,
        to_dt=to_dt,
        n_ticks=n_ticks,
        n_candles_1h=len(candles_1h),
        n_candles_15m=len(candles_15m),
        n_setups_detected=n_setups,
        trades=trades,
        funnel=funnel,
    )
