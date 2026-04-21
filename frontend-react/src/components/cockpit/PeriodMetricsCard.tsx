import { useState } from 'react';
import clsx from 'clsx';
import { motion, AnimatePresence } from 'motion/react';
import { GlassCard } from '@/components/ui/GlassCard';
import { GradientText } from '@/components/ui/GradientText';
import { Skeleton } from '@/components/ui/Skeleton';
import { Tooltip, LabelWithInfo } from '@/components/ui/Tooltip';
import { usePeriodStats } from '@/hooks/useCockpit';
import { formatPnl, formatPct } from '@/lib/format';
import { TIPS } from '@/lib/metricTips';
import type { PeriodKey, PeriodStats } from '@/types/domain';

const TABS: Array<{ key: PeriodKey; label: string; tip: string }> = [
  { key: 'day', label: 'Jour', tip: TIPS.period.tabDay },
  { key: 'week', label: 'Semaine', tip: TIPS.period.tabWeek },
  { key: 'month', label: 'Mois', tip: TIPS.period.tabMonth },
  { key: 'year', label: 'Année', tip: TIPS.period.tabYear },
  { key: 'all', label: 'Tout', tip: TIPS.period.tabAll },
];

/** Carte KPI avec tabs Jour/Semaine/Mois/Année/Tout.
 *  Source : /api/insights/period-stats?period=X (backend calcule tout). */
export function PeriodMetricsCard() {
  const [period, setPeriod] = useState<PeriodKey>('day');
  const { data, isLoading } = usePeriodStats(period);

  return (
    <GlassCard variant="elevated" className="p-5">
      <div className="flex items-start justify-between gap-4 flex-wrap mb-4">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Performance par période</h3>}
          tip={TIPS.period.titre}
        />
        <div className="flex items-center gap-1 flex-wrap">
          {TABS.map((t) => (
            <Tooltip key={t.key} content={t.tip}>
              <button
                type="button"
                onClick={() => setPeriod(t.key)}
                className={clsx(
                  'text-xs px-3 py-1.5 rounded-lg border transition-all font-semibold',
                  period === t.key
                    ? 'border-cyan-400/40 bg-cyan-400/10 text-cyan-300 shadow-[0_0_12px_rgba(34,211,238,0.15)]'
                    : 'border-glass-soft text-white/50 hover:text-white/90 hover:bg-white/[0.03]'
                )}
              >
                {t.label}
              </button>
            </Tooltip>
          ))}
        </div>
      </div>

      {isLoading && !data ? (
        <Skeleton className="h-56" />
      ) : data ? (
        <AnimatePresence mode="wait">
          <motion.div
            key={period}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.2 }}
          >
            <StatsGrid stats={data} />
          </motion.div>
        </AnimatePresence>
      ) : null}
    </GlassCard>
  );
}

function StatsGrid({ stats }: { stats: PeriodStats }) {
  const pnlTone = stats.pnl > 0 ? 'text-emerald-300' : stats.pnl < 0 ? 'text-rose-300' : 'text-white/80';
  const pfTone =
    stats.profit_factor === null
      ? 'text-white/50'
      : stats.profit_factor >= 2
      ? 'text-emerald-300'
      : stats.profit_factor >= 1.5
      ? 'text-cyan-300'
      : stats.profit_factor >= 1
      ? 'text-amber-300'
      : 'text-rose-300';
  const expectancyTone =
    stats.expectancy > 0 ? 'text-emerald-300' : stats.expectancy < 0 ? 'text-rose-300' : 'text-white/70';
  const wrTone =
    stats.win_rate >= 0.6 ? 'text-emerald-300' : stats.win_rate >= 0.45 ? 'text-amber-300' : 'text-rose-300';

  if (stats.n_trades === 0) {
    return (
      <div className="py-8 text-center text-sm text-white/40">
        Aucun trade clôturé sur cette période.
        {stats.n_open > 0 && (
          <div className="text-xs mt-2 text-white/60">
            {stats.n_open} position{stats.n_open > 1 ? 's' : ''} ouverte{stats.n_open > 1 ? 's' : ''} ·{' '}
            <span className="font-mono text-rose-300/80">{formatPnl(stats.capital_at_risk_now)}</span> à risque
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Ligne 1 : PnL hero + capital à risque instantané */}
      <div className="grid grid-cols-2 gap-4 pb-4 border-b border-glass-soft">
        <div>
          <LabelWithInfo
            label={<span className="text-[9px] uppercase tracking-[0.2em] text-white/40">PnL période</span>}
            tip={TIPS.period.pnl}
          />
          <div className={clsx('text-3xl font-bold font-mono tabular-nums mt-1', pnlTone)}>
            {formatPnl(stats.pnl)}
          </div>
          <Tooltip content={TIPS.period.pnlPct}>
            <div className="text-[11px] text-white/40 font-mono mt-1">
              {formatPct(stats.pnl_pct / 100)} du capital
            </div>
          </Tooltip>
        </div>
        <div>
          <LabelWithInfo
            label={<span className="text-[9px] uppercase tracking-[0.2em] text-white/40">Capital à risque (now)</span>}
            tip={TIPS.period.capitalAtRiskNow}
          />
          <div className="text-3xl font-bold font-mono tabular-nums text-rose-300/90 mt-1">
            {formatPnl(stats.capital_at_risk_now)}
          </div>
          <div className="text-[11px] text-white/40 font-mono mt-1">
            {stats.n_open} position{stats.n_open > 1 ? 's' : ''} ouverte{stats.n_open > 1 ? 's' : ''}
          </div>
        </div>
      </div>

      {/* Ligne 2 : KPIs secondaires en grille */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <MiniKpi
          label="Trades"
          tip={TIPS.period.nTrades}
          value={<GradientText>{String(stats.n_trades)}</GradientText>}
          sub={`${stats.n_wins}W / ${stats.n_losses}L`}
        />
        <MiniKpi
          label="Win rate"
          tip={TIPS.period.winRate}
          value={<span className={clsx('font-mono', wrTone)}>{formatPct(stats.win_rate)}</span>}
        />
        <MiniKpi
          label="Profit factor"
          tip={TIPS.period.profitFactor}
          value={
            <span className={clsx('font-mono', pfTone)}>
              {stats.profit_factor === null ? '—' : stats.profit_factor.toFixed(2)}
            </span>
          }
        />
        <MiniKpi
          label="Expectancy"
          tip={TIPS.period.expectancy}
          value={<span className={clsx('font-mono', expectancyTone)}>{formatPnl(stats.expectancy)}</span>}
          sub="par trade"
        />
      </div>

      {/* Ligne 3 : drawdown + durée + best/worst */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-4 border-t border-glass-soft">
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <LabelWithInfo
              label={<span className="text-[9px] uppercase tracking-[0.2em] text-white/40">Max drawdown</span>}
              tip={TIPS.period.maxDrawdown}
            />
            <span className="font-mono font-semibold tabular-nums text-rose-300">
              {formatPnl(stats.max_drawdown)}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <LabelWithInfo
              label={<span className="text-[9px] uppercase tracking-[0.2em] text-white/40">Durée moyenne</span>}
              tip={TIPS.period.avgDuration}
            />
            <span className="font-mono tabular-nums text-white/70">
              {stats.avg_duration_min !== null ? `${stats.avg_duration_min} min` : '—'}
            </span>
          </div>
        </div>
        <div className="space-y-2">
          {stats.best_trade && (
            <TradeLine label="Meilleur trade" tip={TIPS.period.bestTrade} trade={stats.best_trade} />
          )}
          {stats.worst_trade && (
            <TradeLine label="Pire trade" tip={TIPS.period.worstTrade} trade={stats.worst_trade} />
          )}
        </div>
      </div>

      {/* Ligne 4 : distribution close_reason en barres horizontales */}
      {Object.keys(stats.close_reasons).length > 0 && (
        <div className="pt-4 border-t border-glass-soft">
          <LabelWithInfo
            label={<span className="text-[9px] uppercase tracking-[0.2em] text-white/40 mb-2 block">Raisons de fermeture</span>}
            tip={TIPS.period.closeReasons}
          />
          <div className="mt-2 flex items-center gap-2 flex-wrap">
            {Object.entries(stats.close_reasons)
              .sort((a, b) => b[1] - a[1])
              .map(([reason, count]) => {
                const pct = Math.round((count / stats.n_trades) * 100);
                const tone =
                  reason === 'TP1' || reason === 'TP2'
                    ? 'bg-emerald-400/10 text-emerald-300 border-emerald-400/30'
                    : reason === 'SL'
                    ? 'bg-rose-400/10 text-rose-300 border-rose-400/30'
                    : 'bg-white/5 text-white/60 border-glass-soft';
                return (
                  <div
                    key={reason}
                    className={clsx('text-[10px] font-mono px-2 py-1 rounded-md border', tone)}
                  >
                    <span className="font-semibold">{reason}</span>{' '}
                    <span className="opacity-60">{count} · {pct}%</span>
                  </div>
                );
              })}
          </div>
        </div>
      )}
    </div>
  );
}

function MiniKpi({
  label,
  tip,
  value,
  sub,
}: {
  label: string;
  tip: React.ReactNode;
  value: React.ReactNode;
  sub?: string;
}) {
  return (
    <div>
      <LabelWithInfo
        label={<span className="text-[9px] uppercase tracking-[0.2em] text-white/40">{label}</span>}
        tip={tip}
        className="mb-1"
      />
      <div className="text-xl font-bold leading-tight tabular-nums">{value}</div>
      {sub && <div className="text-[10px] text-white/40 mt-1 font-mono">{sub}</div>}
    </div>
  );
}

function TradeLine({
  label,
  tip,
  trade,
}: {
  label: string;
  tip: React.ReactNode;
  trade: { pair: string; direction: string; pnl: number; closed_at: string };
}) {
  const tone = trade.pnl > 0 ? 'text-emerald-300' : 'text-rose-300';
  return (
    <div className="flex items-center justify-between">
      <LabelWithInfo
        label={<span className="text-[9px] uppercase tracking-[0.2em] text-white/40">{label}</span>}
        tip={tip}
      />
      <div className="flex items-center gap-2">
        <span className="font-mono text-xs text-white/70 truncate">{trade.pair}</span>
        <span className="text-[9px] font-mono uppercase tracking-wider text-white/40">
          {trade.direction}
        </span>
        <span className={clsx('font-mono font-semibold tabular-nums', tone)}>
          {formatPnl(trade.pnl)}
        </span>
      </div>
    </div>
  );
}
