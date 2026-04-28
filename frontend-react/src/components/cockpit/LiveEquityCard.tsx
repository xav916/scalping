import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { GlassCard } from '@/components/ui/GlassCard';
import { Skeleton } from '@/components/ui/Skeleton';
import { ApiError } from '@/lib/api';

interface LivePoint {
  ts: string;
  balance_eur: number | null;
  equity_eur: number | null;
  profit_eur: number | null;
  positions_count: number | null;
}

interface LiveEquityResponse {
  points: LivePoint[];
  count: number;
  source: string;
}

async function fetchLiveEquity(points: number): Promise<LiveEquityResponse> {
  const res = await fetch(`/api/admin/equity-live?points=${points}`, {
    credentials: 'include',
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new ApiError(res.status, body || res.statusText);
  }
  return res.json();
}

const POINTS = 200;
const W = 720;
const H = 160;
const PAD = 8;

/** Live equity curve depuis le bridge_monitor.log (1 point/min ≈ 200 = 3h20).
 *  Polling 30s. Trace la balance + equity (profit latent inclus). */
export function LiveEquityCard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['admin', 'equity-live', POINTS],
    queryFn: () => fetchLiveEquity(POINTS),
    refetchInterval: 30_000,
    staleTime: 15_000,
    retry: 1,
  });

  const view = useMemo(() => {
    const series = data?.points ?? [];
    if (series.length < 2) return null;
    const equities = series
      .map((p) => p.equity_eur)
      .filter((v): v is number => typeof v === 'number');
    const balances = series
      .map((p) => p.balance_eur)
      .filter((v): v is number => typeof v === 'number');
    if (equities.length < 2) return null;

    const min = Math.min(...equities, ...balances);
    const max = Math.max(...equities, ...balances);
    const range = Math.max(max - min, 1);

    const w = W - PAD * 2;
    const h = H - PAD * 2;
    const xStep = series.length > 1 ? w / (series.length - 1) : 0;

    const equityPath = series
      .map((p, i) => {
        if (typeof p.equity_eur !== 'number') return null;
        const x = PAD + i * xStep;
        const y = PAD + h - ((p.equity_eur - min) / range) * h;
        return { x, y };
      })
      .filter((v): v is { x: number; y: number } => v !== null)
      .map(({ x, y }, i) =>
        i === 0
          ? `M ${x.toFixed(1)} ${y.toFixed(1)}`
          : `L ${x.toFixed(1)} ${y.toFixed(1)}`
      )
      .join(' ');

    const balancePath = series
      .map((p, i) => {
        if (typeof p.balance_eur !== 'number') return null;
        const x = PAD + i * xStep;
        const y = PAD + h - ((p.balance_eur - min) / range) * h;
        return { x, y };
      })
      .filter((v): v is { x: number; y: number } => v !== null)
      .map(({ x, y }, i) =>
        i === 0
          ? `M ${x.toFixed(1)} ${y.toFixed(1)}`
          : `L ${x.toFixed(1)} ${y.toFixed(1)}`
      )
      .join(' ');

    const last = series[series.length - 1];
    const first = series[0];
    const lastEq = last.equity_eur ?? 0;
    const firstEq = first.equity_eur ?? lastEq;
    const sessionDelta = lastEq - firstEq;
    const sessionPct = firstEq > 0 ? (sessionDelta / firstEq) * 100 : 0;

    const isUp = sessionDelta >= 0;

    return {
      equityPath,
      balancePath,
      min,
      max,
      last,
      sessionDelta,
      sessionPct,
      isUp,
      firstTs: first.ts,
      lastTs: last.ts,
    };
  }, [data]);

  if (error instanceof ApiError && error.status === 403) {
    return null; // Pas admin : on n'affiche rien (la card est admin-only)
  }

  return (
    <GlassCard variant="elevated" className="p-5">
      <div className="flex items-baseline justify-between mb-3 gap-3 flex-wrap">
        <div>
          <h3 className="text-sm font-semibold tracking-tight uppercase tracking-[0.2em] text-white/70">
            Capital MT5 live
          </h3>
          <p className="text-[10px] text-white/40 mt-0.5">
            Balance · Equity (incl. PnL latent) — bridge VPS Pepperstone démo
          </p>
        </div>
        {view && (
          <div className="text-right">
            <div className="font-mono text-2xl tabular-nums text-white/90">
              {view.last.equity_eur?.toLocaleString('fr-FR', {
                maximumFractionDigits: 2,
              })}{' '}
              €
            </div>
            <div
              className={`text-xs font-mono ${
                view.isUp ? 'text-emerald-300' : 'text-rose-300'
              }`}
            >
              {view.isUp ? '+' : ''}
              {view.sessionDelta.toFixed(2)} €{' '}
              ({view.isUp ? '+' : ''}
              {view.sessionPct.toFixed(2)}%) sur la fenêtre
            </div>
          </div>
        )}
      </div>

      {isLoading && !view && <Skeleton className="h-40 w-full" />}

      {!isLoading && !view && (
        <p className="text-xs text-white/40 py-8 text-center">
          Pas encore assez de points pour tracer une courbe (besoin ≥ 2).
          Le bridge_monitor s'éveille à raison de 1 point/minute.
        </p>
      )}

      {view && (
        <>
          <svg
            width="100%"
            viewBox={`0 0 ${W} ${H}`}
            preserveAspectRatio="none"
            className="overflow-visible"
          >
            {/* Equity area fill */}
            <defs>
              <linearGradient id="liveEquityFill" x1="0" y1="0" x2="0" y2="1">
                <stop
                  offset="0%"
                  stopColor={view.isUp ? '#10b981' : '#f43f5e'}
                  stopOpacity="0.25"
                />
                <stop
                  offset="100%"
                  stopColor={view.isUp ? '#10b981' : '#f43f5e'}
                  stopOpacity="0"
                />
              </linearGradient>
            </defs>
            {/* Equity fill area */}
            <path
              d={`${view.equityPath} L ${W - PAD} ${H - PAD} L ${PAD} ${H - PAD} Z`}
              fill="url(#liveEquityFill)"
            />
            {/* Balance line (subtle, dashed) */}
            <path
              d={view.balancePath}
              fill="none"
              stroke="rgba(255,255,255,0.35)"
              strokeWidth="1"
              strokeDasharray="3,3"
            />
            {/* Equity line (main) */}
            <path
              d={view.equityPath}
              fill="none"
              stroke={view.isUp ? '#34d399' : '#fb7185'}
              strokeWidth="1.8"
            />
          </svg>

          <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <Stat
              label="Balance"
              value={`${view.last.balance_eur?.toFixed(2)} €`}
            />
            <Stat
              label="Equity"
              value={`${view.last.equity_eur?.toFixed(2)} €`}
            />
            <Stat
              label="PnL latent"
              value={`${(view.last.profit_eur ?? 0).toFixed(2)} €`}
              tone={
                (view.last.profit_eur ?? 0) > 0
                  ? 'pos'
                  : (view.last.profit_eur ?? 0) < 0
                  ? 'neg'
                  : 'neutral'
              }
            />
            <Stat
              label="Positions"
              value={String(view.last.positions_count ?? 0)}
            />
          </div>

          <div className="flex items-center justify-between text-[10px] text-white/40 font-mono mt-2 pt-2 border-t border-white/5">
            <span>
              de {view.firstTs.slice(11, 16)} à {view.lastTs.slice(11, 16)} UTC
            </span>
            <span>
              {data?.count} pts · poll 30s · min {view.min.toFixed(2)} / max{' '}
              {view.max.toFixed(2)}
            </span>
          </div>
        </>
      )}
    </GlassCard>
  );
}

function Stat({
  label,
  value,
  tone = 'neutral',
}: {
  label: string;
  value: string;
  tone?: 'pos' | 'neg' | 'neutral';
}) {
  const toneCls =
    tone === 'pos'
      ? 'text-emerald-300'
      : tone === 'neg'
      ? 'text-rose-300'
      : 'text-white/85';
  return (
    <div className="rounded-lg border border-glass-soft bg-white/[0.02] p-2">
      <div className="text-[9px] uppercase tracking-wider text-white/40">
        {label}
      </div>
      <div className={`font-mono tabular-nums text-sm ${toneCls}`}>{value}</div>
    </div>
  );
}
