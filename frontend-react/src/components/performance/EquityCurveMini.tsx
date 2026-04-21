import clsx from 'clsx';
import { useEquityCurve } from '@/hooks/useEquityCurve';
import { GlassCard } from '@/components/ui/GlassCard';
import { Sparkline } from '@/components/ui/Sparkline';
import { Skeleton } from '@/components/ui/Skeleton';
import { formatPnl } from '@/lib/format';

/** Mini courbe d'équité (PnL cumulé trade par trade) pour le rail droit. */
export function EquityCurveMini() {
  const { data, isLoading } = useEquityCurve();

  if (isLoading) {
    return <Skeleton className="h-40" />;
  }
  if (!data || data.points.length === 0) {
    return (
      <GlassCard className="p-5 h-full">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold tracking-tight">Équité cumulée</h3>
        </div>
        <p className="text-xs text-white/40">Pas encore de points à tracer.</p>
      </GlassCard>
    );
  }

  const values = data.points.map((p) => p.cumulative_pnl);
  const variant: 'buy' | 'sell' | 'neutral' =
    data.final_pnl > 0 ? 'buy' : data.final_pnl < 0 ? 'sell' : 'neutral';
  const finalTone =
    data.final_pnl > 0 ? 'text-emerald-300' : data.final_pnl < 0 ? 'text-rose-300' : 'text-white/70';

  return (
    <GlassCard className="p-5 h-full">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold tracking-tight">Équité cumulée</h3>
        <span className="text-[9px] uppercase tracking-[0.2em] text-white/40 font-mono">
          {data.total_trades} {data.total_trades === 1 ? 'trade' : 'trades'}
        </span>
      </div>

      <div className="mb-2">
        <Sparkline
          values={values}
          width={260}
          height={72}
          variant={variant}
          showEntry={0}
        />
      </div>

      <div className="pt-3 border-t border-glass-soft flex items-baseline justify-between">
        <span className="text-[9px] uppercase tracking-[0.2em] text-white/40">Final</span>
        <span className={clsx('text-xl font-mono font-bold tabular-nums', finalTone)}>
          {formatPnl(data.final_pnl)}
        </span>
      </div>
    </GlassCard>
  );
}
