import clsx from 'clsx';
import { motion } from 'motion/react';
import { usePerformance } from '@/hooks/usePerformance';
import { GlassCard } from '@/components/ui/GlassCard';
import { GradientText } from '@/components/ui/GradientText';
import { Skeleton } from '@/components/ui/Skeleton';
import { formatPct, formatPnl } from '@/lib/format';

/** Mini carte KPI pour le rail latéral du bento layout.
 *  3 chiffres clés (trades / win rate / PnL cumulé) en stack compact. */
export function PerformanceMiniKPI() {
  const { data, isLoading } = usePerformance();

  if (isLoading) {
    return <Skeleton className="h-44" />;
  }
  if (!data || data.total_trades === 0) {
    return (
      <GlassCard className="p-5 h-full">
        <h3 className="text-sm font-semibold tracking-tight mb-3">Perf cumulée</h3>
        <p className="text-xs text-white/40">
          Pas encore de trades clôturés.
        </p>
      </GlassCard>
    );
  }

  const pnlTone =
    (data.total_pnl ?? 0) > 0
      ? 'text-emerald-300'
      : (data.total_pnl ?? 0) < 0
      ? 'text-rose-300'
      : 'text-white/80';

  return (
    <GlassCard className="p-5 h-full">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold tracking-tight">Perf cumulée</h3>
        <span className="text-[9px] uppercase tracking-[0.2em] text-white/40 font-mono">
          Live
        </span>
      </div>

      <div className="space-y-4">
        <Metric
          label="Trades"
          value={
            <motion.span
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4 }}
              className="font-mono text-3xl font-bold tabular-nums"
            >
              {data.total_trades}
            </motion.span>
          }
        />

        <Metric
          label="Win rate"
          value={
            <motion.span
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: 0.08 }}
              className="font-mono text-3xl font-bold tabular-nums"
            >
              <GradientText>{formatPct(data.win_rate ?? 0)}</GradientText>
            </motion.span>
          }
        />

        <Metric
          label="PnL total"
          value={
            <motion.span
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: 0.16 }}
              className={clsx('font-mono text-3xl font-bold tabular-nums', pnlTone)}
            >
              {formatPnl(data.total_pnl ?? 0)}
            </motion.span>
          }
        />
      </div>
    </GlassCard>
  );
}

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="text-[9px] uppercase tracking-[0.2em] text-white/40 mb-1">{label}</div>
      <div className="leading-none">{value}</div>
    </div>
  );
}
