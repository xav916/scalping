import clsx from 'clsx';
import { motion } from 'motion/react';
import { GlassCard } from '@/components/ui/GlassCard';
import { Skeleton } from '@/components/ui/Skeleton';
import { Tooltip, LabelWithInfo } from '@/components/ui/Tooltip';
import { useMistakes } from '@/hooks/useCockpit';
import { formatPnl } from '@/lib/format';
import { TIPS } from '@/lib/metricTips';

/** Détecteur d'erreurs : 4 KPI cards comparant disciplinés vs négligés.
 *  Source : /api/stats/mistakes. Surface le coût concret de la négligence. */
export function MistakesCard() {
  const { data, isLoading } = useMistakes();

  if (isLoading) return <Skeleton className="h-48" />;
  if (!data) return null;

  const disciplineDelta = data.with_checklist_avg_pnl - data.without_checklist.avg_pnl;
  const deltaTone =
    disciplineDelta > 0 ? 'text-emerald-300' : disciplineDelta < 0 ? 'text-rose-300' : 'text-white/70';

  return (
    <GlassCard variant="elevated" className="p-5">
      <div className="flex items-center justify-between mb-4">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Discipline · détecteur d'erreurs</h3>}
          tip={TIPS.mistakes.titre}
        />
        <Tooltip content={TIPS.mistakes.totalTrades}>
          <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">
            {data.total_trades} trades analysés
          </span>
        </Tooltip>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <MistakeTile
          label="Sans checklist"
          tip={TIPS.mistakes.withoutChecklist}
          count={data.without_checklist.count}
          avgPnl={data.without_checklist.avg_pnl}
          severity={data.without_checklist.count > 0 && data.without_checklist.avg_pnl < 0 ? 'warning' : 'neutral'}
          index={0}
        />
        <MistakeTile
          label="Sans SL posé"
          tip={TIPS.mistakes.withoutSl}
          count={data.without_sl_set.count}
          avgPnl={data.without_sl_set.avg_pnl}
          severity={data.without_sl_set.count > 0 ? 'critical' : 'good'}
          index={1}
        />
        <MistakeTile
          label="Sans TP posé"
          tip={TIPS.mistakes.withoutTp}
          count={data.without_tp_set.count}
          avgPnl={data.without_tp_set.avg_pnl}
          severity={data.without_tp_set.count > 0 && data.without_tp_set.avg_pnl < 0 ? 'warning' : 'neutral'}
          index={2}
        />
        <motion.div
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 3 * 0.05 }}
          className="rounded-lg border border-emerald-400/30 bg-emerald-400/5 p-3"
        >
          <LabelWithInfo
            label={<span className="text-[9px] uppercase tracking-[0.2em] text-white/40">Disciplinés · avg PnL</span>}
            tip={TIPS.mistakes.withChecklist}
          />
          <div className={clsx('text-lg font-bold font-mono tabular-nums mt-1', data.with_checklist_avg_pnl >= 0 ? 'text-emerald-300' : 'text-rose-300')}>
            {formatPnl(data.with_checklist_avg_pnl)}
          </div>
          <Tooltip content={TIPS.mistakes.avgPnlImpact}>
            <div className={clsx('text-[10px] font-mono mt-1', deltaTone)}>
              {disciplineDelta >= 0 ? '+' : ''}
              {formatPnl(disciplineDelta)} vs négligés
            </div>
          </Tooltip>
        </motion.div>
      </div>
    </GlassCard>
  );
}

function MistakeTile({
  label,
  tip,
  count,
  avgPnl,
  severity,
  index,
}: {
  label: string;
  tip: React.ReactNode;
  count: number;
  avgPnl: number;
  severity: 'critical' | 'warning' | 'good' | 'neutral';
  index: number;
}) {
  const cardTone = {
    critical: 'border-rose-400/40 bg-rose-400/10',
    warning: 'border-amber-400/40 bg-amber-400/5',
    good: 'border-emerald-400/30 bg-emerald-400/5',
    neutral: 'border-glass-soft bg-white/[0.02]',
  }[severity];

  const pnlTone = avgPnl > 0 ? 'text-emerald-300' : avgPnl < 0 ? 'text-rose-300' : 'text-white/70';
  const countTone =
    severity === 'critical' && count > 0
      ? 'text-rose-300'
      : severity === 'warning' && count > 0
      ? 'text-amber-300'
      : count === 0
      ? 'text-emerald-300'
      : 'text-white/70';

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05 }}
      className={clsx('rounded-lg border p-3 transition-colors', cardTone)}
    >
      <LabelWithInfo
        label={<span className="text-[9px] uppercase tracking-[0.2em] text-white/40">{label}</span>}
        tip={tip}
      />
      <div className={clsx('text-lg font-bold font-mono tabular-nums mt-1', countTone)}>
        {count} <span className="text-[10px] text-white/40 font-normal">{count === 1 ? 'trade' : 'trades'}</span>
      </div>
      <div className={clsx('text-[10px] font-mono mt-1', pnlTone)}>
        avg {formatPnl(avgPnl)}
      </div>
    </motion.div>
  );
}
