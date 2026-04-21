import { useState } from 'react';
import clsx from 'clsx';
import { motion } from 'motion/react';
import { usePerformance } from '@/hooks/usePerformance';
import { GlassCard } from '@/components/ui/GlassCard';
import { GradientText } from '@/components/ui/GradientText';
import { Skeleton } from '@/components/ui/Skeleton';
import { Tooltip, LabelWithInfo } from '@/components/ui/Tooltip';
import { formatPct, formatPnl } from '@/lib/format';
import { TIPS } from '@/lib/metricTips';
import type { InsightsBucket } from '@/types/domain';

type TabKey =
  | 'by_score_bucket'
  | 'by_asset_class'
  | 'by_direction'
  | 'by_risk_regime'
  | 'by_session'
  | 'by_pair';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'by_score_bucket', label: 'Score' },
  { key: 'by_asset_class', label: 'Classe' },
  { key: 'by_direction', label: 'Sens' },
  { key: 'by_risk_regime', label: 'Régime macro' },
  { key: 'by_session', label: 'Session' },
  { key: 'by_pair', label: 'Pair' },
];

function WinRateBar({ pct }: { pct: number }) {
  const clamped = Math.max(0, Math.min(1, pct));
  const color =
    clamped >= 0.6
      ? 'from-emerald-400 to-cyan-400'
      : clamped >= 0.45
      ? 'from-amber-400 to-cyan-400'
      : 'from-rose-400 to-pink-400';
  return (
    <div className="w-full h-1.5 rounded-full bg-white/5 overflow-hidden relative">
      <motion.div
        className={clsx('h-full rounded-full bg-gradient-to-r', color)}
        initial={{ width: 0 }}
        animate={{ width: `${clamped * 100}%` }}
        transition={{ duration: 0.7, ease: 'easeOut' }}
      />
    </div>
  );
}

function BucketRow({ b, index }: { b: InsightsBucket; index: number }) {
  const winPct = b.win_rate;
  const winTone =
    winPct >= 0.6 ? 'text-emerald-300' : winPct >= 0.45 ? 'text-amber-300' : 'text-rose-300';
  const pnlTone =
    b.total_pnl > 0 ? 'text-emerald-300' : b.total_pnl < 0 ? 'text-rose-300' : 'text-white/70';
  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.3, delay: index * 0.04 }}
      className="grid grid-cols-[minmax(80px,140px)_auto_1fr_48px_80px] sm:grid-cols-[140px_auto_1fr_56px_96px] items-center gap-2 sm:gap-4 py-3 border-b border-glass-soft last:border-none"
    >
      <Tooltip content={TIPS.perf.bucketName}>
        <div className="font-mono text-sm text-white/85 truncate cursor-help">{b.bucket}</div>
      </Tooltip>
      <Tooltip content={TIPS.perf.bucketCount}>
        <div className="text-[10px] text-white/40 tabular-nums uppercase tracking-wider cursor-help">
          {b.count} {b.count === 1 ? 'trade' : 'trades'}
        </div>
      </Tooltip>
      <Tooltip content={TIPS.perf.bucketWinrate}>
        <div className="cursor-help">
          <WinRateBar pct={winPct} />
        </div>
      </Tooltip>
      <Tooltip content={TIPS.perf.bucketWinrate}>
        <div className={clsx('text-xs font-semibold font-mono tabular-nums text-right cursor-help', winTone)}>
          {formatPct(winPct)}
        </div>
      </Tooltip>
      <Tooltip content={TIPS.perf.bucketPnl}>
        <div className={clsx('text-xs font-mono font-semibold tabular-nums text-right cursor-help', pnlTone)}>
          {formatPnl(b.total_pnl)}
        </div>
      </Tooltip>
    </motion.div>
  );
}

function Kpi({ label, value, tip }: { label: string; value: React.ReactNode; tip?: React.ReactNode }) {
  return (
    <div className="text-right">
      <div className="text-[9px] uppercase tracking-[0.2em] text-white/40 mb-0.5 flex items-center justify-end gap-1.5">
        {tip ? (
          <LabelWithInfo label={<span>{label}</span>} tip={tip} />
        ) : (
          <span>{label}</span>
        )}
      </div>
      <div className="text-lg font-bold tabular-nums leading-none">{value}</div>
    </div>
  );
}

export function PerformancePanel() {
  const [tab, setTab] = useState<TabKey>('by_score_bucket');
  const { data, isLoading } = usePerformance();

  if (isLoading) {
    return <Skeleton className="h-72" />;
  }
  if (!data || data.total_trades === 0) {
    return (
      <GlassCard className="p-6 text-sm text-white/50">
        {data?.message ?? 'Pas de trades clôturés à analyser (attend quelques cycles).'}
      </GlassCard>
    );
  }

  const buckets = data[tab] ?? [];
  const pnlTone =
    (data.total_pnl ?? 0) > 0
      ? 'text-emerald-300'
      : (data.total_pnl ?? 0) < 0
      ? 'text-rose-300'
      : 'text-white/80';

  return (
    <GlassCard variant="elevated" className="p-6">
      <div className="flex items-start justify-between mb-5 gap-4 flex-wrap">
        <div>
          <LabelWithInfo
            label={<h2 className="text-lg font-semibold tracking-tight">Performance</h2>}
            tip={TIPS.perf.titreBucket}
          />
          <p className="text-[10px] text-white/40 mt-1 uppercase tracking-[0.2em]">
            Depuis le post-fix · données agrégées
          </p>
        </div>
        <div className="flex items-center gap-4 sm:gap-6">
          <Kpi label="Trades" tip={TIPS.perf.tradesTotal} value={<span className="font-mono">{data.total_trades}</span>} />
          <Kpi label="Win rate" tip={TIPS.perf.winRateGlobal} value={<GradientText>{formatPct(data.win_rate ?? 0)}</GradientText>} />
          <Kpi
            label="PnL"
            tip={TIPS.perf.pnlTotal}
            value={<span className={clsx('font-mono', pnlTone)}>{formatPnl(data.total_pnl ?? 0)}</span>}
          />
        </div>
      </div>

      <div className="flex flex-nowrap overflow-x-auto scrollbar-hide gap-1.5 mb-4 pb-4 border-b border-glass-soft -mx-1 px-1">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={clsx(
              'text-xs px-3 py-1.5 rounded-lg border transition-all whitespace-nowrap flex-shrink-0',
              tab === t.key
                ? 'border-glass-strong bg-white/10 text-white shadow-sm'
                : 'border-glass-soft text-white/50 hover:text-white/90 hover:bg-white/[0.03]'
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div>
        {buckets.length === 0 ? (
          <p className="text-sm text-white/40 py-8 text-center">
            Pas de données pour cette dimension.
          </p>
        ) : (
          buckets.map((b, i) => <BucketRow key={b.bucket} b={b} index={i} />)
        )}
      </div>
    </GlassCard>
  );
}
