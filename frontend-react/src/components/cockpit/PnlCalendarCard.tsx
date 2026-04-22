import { useMemo, useState } from 'react';
import clsx from 'clsx';
import { useQuery } from '@tanstack/react-query';
import { GlassCard } from '@/components/ui/GlassCard';
import { Skeleton } from '@/components/ui/Skeleton';
import { Tooltip, LabelWithInfo } from '@/components/ui/Tooltip';
import { api } from '@/lib/api';
import { CalendarHeatmap } from './CalendarHeatmap';

type RangeKey = '3m' | '6m' | 'year';

const TABS: Array<{ key: RangeKey; label: string; months: number }> = [
  { key: '3m', label: '3 mois', months: 3 },
  { key: '6m', label: '6 mois', months: 6 },
  { key: 'year', label: 'Année', months: 12 },
];

function monthsAgoIso(monthsBack: number): string {
  const d = new Date();
  d.setUTCMonth(d.getUTCMonth() - monthsBack);
  // Aligner au lundi pour une grille propre
  const dow = (d.getUTCDay() + 6) % 7;
  d.setUTCDate(d.getUTCDate() - dow);
  d.setUTCHours(0, 0, 0, 0);
  return d.toISOString();
}

/** Heatmap PnL calendaire, style GitHub. Révèle les patterns jour-de-semaine /
 *  session / clusters de drawdown sur 3 à 12 mois. */
export function PnlCalendarCard() {
  const [rangeKey, setRangeKey] = useState<RangeKey>('3m');
  const { since, until } = useMemo(() => {
    const tab = TABS.find((t) => t.key === rangeKey)!;
    return {
      since: monthsAgoIso(tab.months),
      until: new Date().toISOString(),
    };
  }, [rangeKey]);

  const { data, isLoading } = useQuery({
    queryKey: ['pnl-buckets', since, until, 'day'],
    queryFn: () => api.pnlBuckets(since, until, 'day'),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const summary = useMemo(() => {
    if (!data) return null;
    const { buckets, total_trades, final_pnl } = data;
    const tradedDays = buckets.filter((b) => b.n_trades > 0).length;
    const greenDays = buckets.filter((b) => b.pnl > 0).length;
    const redDays = buckets.filter((b) => b.pnl < 0).length;
    return { total_trades, final_pnl, tradedDays, greenDays, redDays };
  }, [data]);

  return (
    <GlassCard variant="elevated" className="p-5">
      <div className="flex items-start justify-between gap-4 flex-wrap mb-4">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Calendrier PnL</h3>}
          tip="Carte calendaire inspirée des contributions GitHub : chaque case = 1 jour, couleur = intensité du PnL. Révèle les patterns jour-de-semaine et clusters de drawdown."
        />
        <div className="flex items-center gap-1">
          {TABS.map((t) => (
            <Tooltip key={t.key} content={`${t.months} derniers mois`} delay={400}>
              <button
                type="button"
                onClick={() => setRangeKey(t.key)}
                className={clsx(
                  'text-xs px-3 py-1.5 rounded-lg border transition-all font-semibold',
                  rangeKey === t.key
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
        <Skeleton className="h-32" />
      ) : data ? (
        <>
          <CalendarHeatmap buckets={data.buckets} />

          {summary && (
            <div className="mt-4 pt-3 border-t border-glass-soft grid grid-cols-4 gap-4">
              <Kpi label="Trades" value={summary.total_trades} />
              <Kpi
                label="Jours tradés"
                value={summary.tradedDays}
                sub={`${data.buckets.length} total`}
              />
              <Kpi
                label="Verts / Rouges"
                value={
                  <span className="font-mono">
                    <span className="text-emerald-300">{summary.greenDays}</span>
                    <span className="text-white/30"> / </span>
                    <span className="text-rose-300">{summary.redDays}</span>
                  </span>
                }
              />
              <Kpi
                label="PnL cumul"
                value={
                  <span
                    className={clsx(
                      'font-mono',
                      summary.final_pnl > 0
                        ? 'text-emerald-300'
                        : summary.final_pnl < 0
                        ? 'text-rose-300'
                        : 'text-white/70'
                    )}
                  >
                    {summary.final_pnl > 0 ? '+' : ''}
                    {summary.final_pnl.toFixed(2)} €
                  </span>
                }
              />
            </div>
          )}
        </>
      ) : null}
    </GlassCard>
  );
}

function Kpi({
  label,
  value,
  sub,
}: {
  label: string;
  value: React.ReactNode;
  sub?: string;
}) {
  return (
    <div>
      <div className="text-[9px] uppercase tracking-[0.2em] text-white/40">{label}</div>
      <div className="text-lg font-bold leading-tight tabular-nums">{value}</div>
      {sub && <div className="text-[10px] text-white/40 mt-0.5 font-mono">{sub}</div>}
    </div>
  );
}
