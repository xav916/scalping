import { useState } from 'react';
import clsx from 'clsx';
import { usePerformance } from '@/hooks/usePerformance';
import { GlassCard } from '@/components/ui/GlassCard';
import { GradientText } from '@/components/ui/GradientText';
import { Skeleton } from '@/components/ui/Skeleton';
import { formatPct, formatPnl } from '@/lib/format';
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

function BucketRow({ b }: { b: InsightsBucket }) {
  const winPct = b.win_rate;
  const winTone =
    winPct >= 0.6 ? 'text-emerald-300' : winPct >= 0.45 ? 'text-amber-300' : 'text-rose-300';
  return (
    <div className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-4 py-2 border-b border-glass-soft last:border-none text-sm">
      <div className="font-mono text-white/80">{b.bucket}</div>
      <div className="text-xs text-white/50 tabular-nums">{b.count} trades</div>
      <div className={clsx('text-xs font-semibold tabular-nums', winTone)}>{formatPct(winPct)}</div>
      <div className="text-xs font-mono tabular-nums text-white/80 w-24 text-right">{formatPnl(b.total_pnl)}</div>
    </div>
  );
}

export function PerformancePanel() {
  const [tab, setTab] = useState<TabKey>('by_score_bucket');
  const { data, isLoading } = usePerformance();

  if (isLoading) {
    return <Skeleton className="h-64" />;
  }
  if (!data || data.total_trades === 0) {
    return (
      <GlassCard className="p-6 text-sm text-white/50">
        {data?.message ?? 'Pas de trades clôturés à analyser (attend quelques cycles).'}
      </GlassCard>
    );
  }

  const buckets = data[tab] ?? [];

  return (
    <GlassCard variant="elevated" className="p-6">
      <div className="flex items-end justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold">Performance</h2>
          <p className="text-xs text-white/50 mt-1">
            {data.total_trades} trades ·{' '}
            <GradientText>{formatPct(data.win_rate ?? 0)}</GradientText> win rate · {formatPnl(data.total_pnl ?? 0)}
          </p>
        </div>
        <div className="flex flex-wrap gap-1">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={clsx(
                'text-xs px-3 py-1.5 rounded-lg border transition-colors',
                tab === t.key
                  ? 'border-glass-strong bg-white/10 text-white'
                  : 'border-glass-soft text-white/60 hover:text-white/90'
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>
      <div>
        {buckets.length === 0 ? (
          <p className="text-sm text-white/40 py-6 text-center">Pas de données pour cette dimension.</p>
        ) : (
          buckets.map((b) => <BucketRow key={b.bucket} b={b} />)
        )}
      </div>
    </GlassCard>
  );
}
