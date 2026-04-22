import { useMemo, useState } from 'react';
import clsx from 'clsx';
import { useQuery } from '@tanstack/react-query';
import { GlassCard } from '@/components/ui/GlassCard';
import { Skeleton } from '@/components/ui/Skeleton';
import { LabelWithInfo } from '@/components/ui/Tooltip';
import { api } from '@/lib/api';
import { formatPnl } from '@/lib/format';
import type { ExposureTimeseries, Granularity } from '@/types/domain';

type WindowKey = '24h' | '7d' | '30d';

const WINDOWS: Array<{ key: WindowKey; label: string; hours: number; gran: Granularity }> = [
  { key: '24h', label: '24h', hours: 24, gran: 'hour' },
  { key: '7d', label: '7 jours', hours: 24 * 7, gran: 'hour' },
  { key: '30d', label: '30 jours', hours: 24 * 30, gran: 'day' },
];

function hoursAgoIso(hoursBack: number): string {
  return new Date(Date.now() - hoursBack * 3_600_000).toISOString();
}

function formatBucketLabel(iso: string, granularity: Granularity): string {
  const d = new Date(iso);
  if (granularity === 'month') return d.toLocaleDateString('fr-FR', { month: 'long', year: 'numeric', timeZone: 'UTC' });
  if (granularity === 'day') return d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', timeZone: 'UTC' });
  return `${d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', timeZone: 'UTC' })} ${String(d.getUTCHours()).padStart(2, '0')}h`;
}

/** Timeline du capital à risque engagé dans les trades au cours du temps.
 *  Dérivée des trades fermés/ouverts : utile pour repérer les pics
 *  d'exposition (ex : 14h UTC quand les signaux macro déclenchent en chaîne). */
export function ExposureTimelineCard() {
  const [windowKey, setWindowKey] = useState<WindowKey>('7d');
  const { since, until, granularity } = useMemo(() => {
    const w = WINDOWS.find((x) => x.key === windowKey)!;
    return {
      since: hoursAgoIso(w.hours),
      until: new Date().toISOString(),
      granularity: w.gran,
    };
  }, [windowKey]);

  const { data, isLoading } = useQuery({
    queryKey: ['exposure-timeseries', since, until, granularity],
    queryFn: () => api.exposureTimeseries(since, until, granularity),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  return (
    <GlassCard variant="elevated" className="p-5">
      <div className="flex items-start justify-between gap-4 flex-wrap mb-4">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Exposition dans le temps</h3>}
          tip="Capital à risque (Σ |entry-SL| × size × units) à chaque instant, dérivé des trades OPEN à ce moment. Révèle les pics d'exposition simultanée — utile pour ajuster la taille de position ou la fenêtre d'auto-exec."
        />
        <div className="flex items-center gap-1">
          {WINDOWS.map((w) => (
            <button
              key={w.key}
              type="button"
              onClick={() => setWindowKey(w.key)}
              className={clsx(
                'text-xs px-2.5 py-1 rounded-md border transition-all font-semibold',
                windowKey === w.key
                  ? 'border-cyan-400/40 bg-cyan-400/10 text-cyan-300'
                  : 'border-glass-soft text-white/40 hover:text-white/80'
              )}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>

      {/* Reservation ~240px : chart 180 + KPIs row 50 + gap */}
      <div style={{ minHeight: 240 }}>
        {isLoading && !data ? (
          <Skeleton className="h-[220px] w-full" />
        ) : data ? (
          <>
            <ExposureChart data={data} />

            <div className="mt-3 pt-3 border-t border-glass-soft grid grid-cols-3 gap-4">
              <Kpi
                label="Pic exposure"
                tip="Capital max engagé à un instant sur la période."
                value={
                  <span className="text-rose-300 font-mono">
                    {formatPnl(data.peak_at_risk)}
                  </span>
                }
              />
              <Kpi
                label="Moyenne"
                tip="Moyenne du capital à risque sur tous les buckets."
                value={
                  <span className="text-amber-300 font-mono">
                    {formatPnl(data.avg_at_risk)}
                  </span>
                }
              />
              <Kpi
                label="Max positions"
                tip="Nombre max de trades simultanés observé sur la période."
                value={
                  <span className="text-cyan-300 font-mono">{data.max_open}</span>
                }
                sub={`granularité ${data.granularity_used}`}
              />
            </div>
          </>
        ) : null}
      </div>
    </GlassCard>
  );
}

function ExposureChart({ data }: { data: ExposureTimeseries }) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const { points } = data;

  const { maxAtRisk, maxOpen, pathD, areaD } = useMemo(() => {
    const maxAtRisk = Math.max(1, ...points.map((p) => p.capital_at_risk));
    const maxOpen = Math.max(1, ...points.map((p) => p.n_open));
    const W = points.length * 40;
    const H = 180;
    const padY = 10;
    const scaleX = (i: number) => (points.length > 1 ? (i / (points.length - 1)) * W : W / 2);
    const scaleY = (v: number) => padY + ((maxAtRisk - v) / maxAtRisk) * (H - 2 * padY);

    const pathD = points
      .map((p, i) => `${i === 0 ? 'M' : 'L'} ${scaleX(i).toFixed(1)} ${scaleY(p.capital_at_risk).toFixed(1)}`)
      .join(' ');
    const areaD =
      points.length > 0
        ? `${pathD} L ${scaleX(points.length - 1).toFixed(1)} ${H} L 0 ${H} Z`
        : '';

    return { maxAtRisk, maxOpen, pathD, areaD };
  }, [points]);

  if (points.length === 0) {
    return (
      <div className="flex items-center justify-center h-[180px] text-xs text-white/30 rounded-lg border border-white/5">
        Pas de données sur cette période
      </div>
    );
  }

  const W = points.length * 40;
  const H = 180;

  return (
    <div className="relative" onMouseLeave={() => setHoverIdx(null)}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        style={{ width: '100%', height: H, display: 'block' }}
      >
        <defs>
          <linearGradient id="expo-gradient" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#f87171" stopOpacity="0.28" />
            <stop offset="100%" stopColor="#f87171" stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Grille horizontale */}
        {[0.25, 0.5, 0.75].map((frac) => (
          <line
            key={`g-${frac}`}
            x1={0}
            x2={W}
            y1={10 + (H - 20) * frac}
            y2={10 + (H - 20) * frac}
            stroke="rgba(255,255,255,0.05)"
            strokeDasharray="2 3"
            vectorEffect="non-scaling-stroke"
          />
        ))}

        {/* Area fill */}
        <path d={areaD} fill="url(#expo-gradient)" />

        {/* Ligne capital à risque (rose) */}
        <path
          d={pathD}
          fill="none"
          stroke="#f87171"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />

        {/* Hover zones + points */}
        {points.map((p, i) => {
          const cx = points.length > 1 ? (i / (points.length - 1)) * W : W / 2;
          const cy = 10 + ((maxAtRisk - p.capital_at_risk) / maxAtRisk) * (H - 20);
          return (
            <g key={p.bucket_time}>
              <rect
                x={Math.max(0, cx - 20)}
                y={0}
                width={40}
                height={H}
                fill="transparent"
                onMouseEnter={() => setHoverIdx(i)}
                style={{ cursor: 'default' }}
              />
              {hoverIdx === i && (
                <circle cx={cx} cy={cy} r={4} fill="#f87171" vectorEffect="non-scaling-stroke" />
              )}
            </g>
          );
        })}
      </svg>

      {/* Tooltip hover */}
      {hoverIdx !== null && points[hoverIdx] && (
        <div
          className="pointer-events-none absolute top-0 rounded-lg border border-rose-400/30 bg-[#0d111a] px-3 py-1.5 text-[11px] shadow-[0_8px_24px_rgba(0,0,0,0.6)]"
          style={{
            left: `${((hoverIdx + 0.5) / points.length) * 100}%`,
            transform: 'translate(-50%, -4px)',
            zIndex: 10,
            whiteSpace: 'nowrap',
          }}
        >
          <div className="font-semibold text-rose-300">
            {formatBucketLabel(points[hoverIdx].bucket_time, data.granularity_used)}
          </div>
          <div className="text-white/70 font-mono tabular-nums">
            {formatPnl(points[hoverIdx].capital_at_risk)} à risque
          </div>
          <div className="text-white/40 font-mono text-[10px]">
            {points[hoverIdx].n_open} position{points[hoverIdx].n_open > 1 ? 's' : ''} ouverte
            {points[hoverIdx].n_open > 1 ? 's' : ''}
          </div>
        </div>
      )}

      {/* Axis scale hints */}
      <div className="flex justify-between text-[9px] font-mono text-white/30 mt-1">
        <span>{formatBucketLabel(points[0].bucket_time, data.granularity_used)}</span>
        <span className="text-white/50">
          max {formatPnl(maxAtRisk)} · {maxOpen} pos
        </span>
        <span>
          {formatBucketLabel(points[points.length - 1].bucket_time, data.granularity_used)}
        </span>
      </div>
    </div>
  );
}

function Kpi({
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
