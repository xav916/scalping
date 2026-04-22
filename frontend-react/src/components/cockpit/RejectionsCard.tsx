import { useMemo, useState } from 'react';
import clsx from 'clsx';
import { useQuery } from '@tanstack/react-query';
import { GlassCard } from '@/components/ui/GlassCard';
import { Skeleton } from '@/components/ui/Skeleton';
import { Tooltip, LabelWithInfo } from '@/components/ui/Tooltip';
import { api } from '@/lib/api';
import type { RejectionsReport } from '@/types/domain';

type WindowKey = '24h' | '7d' | '30d';
type ViewKey = 'reasons' | 'timeline';

const WINDOWS: Array<{ key: WindowKey; label: string; hours: number }> = [
  { key: '24h', label: '24h', hours: 24 },
  { key: '7d', label: '7 jours', hours: 24 * 7 },
  { key: '30d', label: '30 jours', hours: 24 * 30 },
];

/** Couleurs associées aux reason_code canoniques (cf. rejection_service.py). */
const REASON_COLORS: Record<string, string> = {
  kill_switch: '#f43f5e',
  event_blackout: '#fb923c',
  simulated_data: '#a78bfa',
  verdict_blocker: '#fbbf24',
  market_closed: '#64748b',
  sl_too_close: '#f87171',
  below_confidence: '#94a3b8',
  asset_class_blocked: '#22d3ee',
  bridge_max_positions: '#ec4899',
  bridge_invalid_stops: '#ef4444',
  bridge_error: '#dc2626',
  bridge_timeout: '#a855f7',
};

function hoursAgoIso(hoursBack: number): string {
  return new Date(Date.now() - hoursBack * 3_600_000).toISOString();
}

/** Carte visualisant les rejections d'auto-exec. Deux vues toggleables :
 *  par raison (bar chart) et timeline heatmap (raison × heure UTC). */
export function RejectionsCard() {
  const [windowKey, setWindowKey] = useState<WindowKey>('7d');
  const [view, setView] = useState<ViewKey>('reasons');

  const { since, until } = useMemo(() => {
    const w = WINDOWS.find((x) => x.key === windowKey)!;
    return { since: hoursAgoIso(w.hours), until: new Date().toISOString() };
  }, [windowKey]);

  const { data, isLoading } = useQuery({
    queryKey: ['rejections', since, until],
    queryFn: () => api.rejections(since, until),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  return (
    <GlassCard variant="elevated" className="p-5">
      <div className="flex items-start justify-between gap-4 flex-wrap mb-4">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Rejections auto-exec</h3>}
          tip="Chaque ligne = un signal auto-exec bloqué (cap bridge, marché fermé, SL trop serré, etc.). Permet de voir les ordres perdus et leur pattern horaire."
        />
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex items-center gap-1">
            {(['reasons', 'timeline'] as const).map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => setView(v)}
                className={clsx(
                  'text-xs px-2.5 py-1 rounded-md border transition-all font-semibold',
                  view === v
                    ? 'border-cyan-400/40 bg-cyan-400/10 text-cyan-300'
                    : 'border-glass-soft text-white/40 hover:text-white/80'
                )}
              >
                {v === 'reasons' ? 'Raisons' : 'Timeline'}
              </button>
            ))}
          </div>
          <span className="text-white/20">|</span>
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
      </div>

      {isLoading && !data ? (
        <Skeleton className="h-40" />
      ) : data ? (
        <>
          <div className="mb-3">
            <span className="text-2xl font-mono font-bold tabular-nums text-white/90">
              {data.total}
            </span>
            <span className="ml-2 text-xs text-white/40">
              ordre{data.total > 1 ? 's' : ''} perdu{data.total > 1 ? 's' : ''}
              {' sur '}
              {WINDOWS.find((w) => w.key === windowKey)?.label}
            </span>
          </div>

          {data.total === 0 ? (
            <div className="py-8 text-center text-sm text-emerald-300/70">
              ✓ Aucune rejection sur cette période
            </div>
          ) : view === 'reasons' ? (
            <ReasonsView data={data} />
          ) : (
            <TimelineView data={data} />
          )}
        </>
      ) : null}
    </GlassCard>
  );
}

function ReasonsView({ data }: { data: RejectionsReport }) {
  const maxCount = Math.max(...data.by_reason.map((r) => r.count), 1);

  return (
    <div className="space-y-2">
      {data.by_reason.map((r) => {
        const pct = (r.count / maxCount) * 100;
        const color = REASON_COLORS[r.reason_code] || 'rgba(255,255,255,0.4)';
        return (
          <Tooltip
            key={r.reason_code}
            content={
              <div>
                <div className="font-semibold">{r.label_fr}</div>
                <div className="text-white/60 text-[10px] mt-1">
                  {Object.entries(r.pairs)
                    .sort(([, a], [, b]) => b - a)
                    .slice(0, 5)
                    .map(([p, c]) => `${p}: ${c}`)
                    .join(' · ')}
                </div>
              </div>
            }
            delay={100}
          >
            <div className="grid grid-cols-[180px_1fr_60px] items-center gap-3 group cursor-default">
              <div className="text-xs text-white/70 font-mono truncate">
                {r.label_fr}
              </div>
              <div className="relative h-5 rounded bg-white/[0.02] overflow-hidden">
                <div
                  className="absolute inset-y-0 left-0 rounded transition-all group-hover:brightness-125"
                  style={{ width: `${pct}%`, background: color, opacity: 0.75 }}
                />
              </div>
              <div className="text-xs font-mono tabular-nums text-white/80 text-right">
                {r.count}
                {r.top_pair && (
                  <div className="text-[9px] text-white/40 truncate">{r.top_pair}</div>
                )}
              </div>
            </div>
          </Tooltip>
        );
      })}
    </div>
  );
}

function TimelineView({ data }: { data: RejectionsReport }) {
  // Matrice reason × hour
  const matrix = useMemo(() => {
    const m = new Map<string, Map<number, number>>();
    for (const cell of data.by_reason_hour) {
      if (!m.has(cell.reason_code)) m.set(cell.reason_code, new Map());
      m.get(cell.reason_code)!.set(cell.hour, cell.count);
    }
    return m;
  }, [data.by_reason_hour]);

  const reasons = data.by_reason.map((r) => r.reason_code);
  const maxCell = Math.max(
    ...data.by_reason_hour.map((c) => c.count),
    1
  );

  const CELL_W = 18;
  const CELL_H = 18;
  const LABEL_W = 180;

  return (
    <div className="overflow-x-auto">
      <svg
        width={LABEL_W + 24 * CELL_W + 10}
        height={reasons.length * CELL_H + 20 + 14}
        style={{ display: 'block', minWidth: LABEL_W + 24 * CELL_W + 10 }}
      >
        {/* Hour labels top */}
        {Array.from({ length: 24 }, (_, h) => (
          <text
            key={`h-${h}`}
            x={LABEL_W + h * CELL_W + CELL_W / 2}
            y={10}
            textAnchor="middle"
            fontSize={9}
            fontFamily="ui-monospace, monospace"
            fill="rgba(255,255,255,0.35)"
          >
            {h % 3 === 0 ? h : ''}
          </text>
        ))}

        {/* Rows par raison */}
        {reasons.map((reason, i) => {
          const y = 20 + i * CELL_H;
          const rowData = matrix.get(reason);
          const color = REASON_COLORS[reason] || 'rgba(255,255,255,0.4)';
          const reasonRow = data.by_reason.find((r) => r.reason_code === reason);
          return (
            <g key={reason}>
              {/* Label */}
              <text
                x={LABEL_W - 6}
                y={y + CELL_H * 0.7}
                textAnchor="end"
                fontSize={10}
                fontFamily="ui-monospace, monospace"
                fill="rgba(255,255,255,0.7)"
              >
                {reasonRow?.label_fr.slice(0, 22) || reason}
              </text>
              {/* Cells */}
              {Array.from({ length: 24 }, (_, h) => {
                const c = rowData?.get(h) || 0;
                const intensity = c > 0 ? 0.25 + (c / maxCell) * 0.75 : 0;
                return (
                  <rect
                    key={`${reason}-${h}`}
                    x={LABEL_W + h * CELL_W + 1}
                    y={y + 1}
                    width={CELL_W - 2}
                    height={CELL_H - 2}
                    rx={2}
                    fill={c > 0 ? color : 'rgba(255,255,255,0.03)'}
                    opacity={c > 0 ? intensity : 1}
                  >
                    <title>
                      {reasonRow?.label_fr} · {String(h).padStart(2, '0')}h UTC · {c}
                    </title>
                  </rect>
                );
              })}
            </g>
          );
        })}

        {/* X-axis bottom label */}
        <text
          x={LABEL_W + 12 * CELL_W}
          y={reasons.length * CELL_H + 20 + 12}
          textAnchor="middle"
          fontSize={9}
          fontFamily="ui-monospace, monospace"
          fill="rgba(255,255,255,0.35)"
        >
          heure UTC (0 à 23)
        </text>
      </svg>
    </div>
  );
}
