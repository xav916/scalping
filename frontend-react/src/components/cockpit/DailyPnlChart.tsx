import { useMemo, useState } from 'react';
import clsx from 'clsx';
import { motion } from 'motion/react';
import type { PnlBucket, Granularity, DrillSegment } from '@/types/domain';
import { formatPnl } from '@/lib/format';

interface Props {
  buckets: PnlBucket[];
  granularity: Granularity;
  /** True si la dernière barre doit pulser (range inclut now). */
  live?: boolean;
  /** Clic sur une barre → drill-down. Null si la barre n'est pas drillable
   *  (granularity=5min = fond du ladder). */
  onBarClick?: (seg: DrillSegment) => void;
  /** Hauteur du svg (default 200). */
  height?: number;
}

const BAR_GAP = 2;
const Y_PADDING = 12;
const LABEL_PADDING = 18;

/** Granularité enfant dans le drill ladder (null = on est au fond). */
function childGranularity(g: Granularity): Granularity | null {
  if (g === 'month') return 'day';
  if (g === 'day') return 'hour';
  if (g === 'hour') return '5min';
  return null;
}

/** Label lisible pour une barre selon la granularité. */
function bucketLabel(b: PnlBucket, g: Granularity): string {
  const d = new Date(b.bucket_start);
  if (g === 'month') return d.toLocaleDateString('fr-FR', { month: 'long', year: 'numeric', timeZone: 'UTC' });
  if (g === 'day') return d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', timeZone: 'UTC' });
  if (g === 'hour') return `${String(d.getUTCHours()).padStart(2, '0')}h UTC`;
  // 5min
  return `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')} UTC`;
}

/** Label court pour l'axe X (pour éviter d'encombrer). */
function shortAxisLabel(b: PnlBucket, g: Granularity): string {
  const d = new Date(b.bucket_start);
  if (g === 'month') return d.toLocaleDateString('fr-FR', { month: 'short', timeZone: 'UTC' });
  if (g === 'day') return String(d.getUTCDate());
  if (g === 'hour') return String(d.getUTCHours());
  return `${d.getUTCHours()}:${String(d.getUTCMinutes()).padStart(2, '0')}`;
}

/** Choisit ~targetCount indices répartis uniformément sur n. */
function pickLabelIndices(n: number, targetCount = 7): Set<number> {
  if (n <= targetCount) {
    return new Set(Array.from({ length: n }, (_, i) => i));
  }
  const step = (n - 1) / (targetCount - 1);
  const set = new Set<number>();
  for (let i = 0; i < targetCount; i++) set.add(Math.round(i * step));
  return set;
}

export function DailyPnlChart({
  buckets,
  granularity,
  live = false,
  onBarClick,
  height = 200,
}: Props) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const { barYScale, yMax, yMin, lineYScale } = useMemo(() => {
    if (buckets.length === 0) {
      return { barYScale: () => 0, yMax: 0, yMin: 0, lineYScale: () => 0 };
    }
    // Y cap pour les barres : ±5 × médiane des |pnl|
    const abs = buckets.map((b) => Math.abs(b.pnl)).filter((v) => v > 0);
    abs.sort((a, b) => a - b);
    const median = abs.length ? abs[Math.floor(abs.length / 2)] : 0;
    const cap = Math.max(median * 5, 1);
    // Mais laisser l'axe englober aussi la cumul line (qui peut dépasser)
    const cumMax = Math.max(...buckets.map((b) => b.cumulative_pnl), 0);
    const cumMin = Math.min(...buckets.map((b) => b.cumulative_pnl), 0);
    const yMax = Math.max(cap, cumMax) * 1.08;
    const yMin = Math.min(-cap, cumMin) * 1.08;
    const yRange = yMax - yMin || 1;

    const chartHeight = height - Y_PADDING * 2 - LABEL_PADDING;
    const barYScale = (v: number) => {
      // Clip visuel à cap pour les barres — outlier reste visible avec un petit marker
      const clipped = Math.max(Math.min(v, yMax), yMin);
      return Y_PADDING + ((yMax - clipped) / yRange) * chartHeight;
    };
    const lineYScale = (v: number) => Y_PADDING + ((yMax - v) / yRange) * chartHeight;

    return { barYScale, yMax, yMin, lineYScale };
  }, [buckets, height]);

  if (buckets.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-xs text-white/30 rounded-lg border border-white/5"
        style={{ height }}
      >
        Aucun bucket à afficher
      </div>
    );
  }

  const n = buckets.length;
  // Largeur en viewBox : 100 unités par bucket, ajusté par le preserveAspectRatio
  const barWidth = 100;
  const totalWidth = n * barWidth;
  const zeroY = lineYScale(0);
  const labelIdx = pickLabelIndices(n);
  const child = childGranularity(granularity);
  const drillable = !!child && !!onBarClick;

  return (
    <div className="relative" onMouseLeave={() => setHoverIdx(null)}>
      <svg
        viewBox={`0 0 ${totalWidth} ${height}`}
        preserveAspectRatio="none"
        style={{ width: '100%', height, display: 'block' }}
      >
        {/* Axe zéro */}
        <line
          x1={0}
          y1={zeroY}
          x2={totalWidth}
          y2={zeroY}
          stroke="rgba(255,255,255,0.1)"
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
        />

        {/* Barres */}
        {buckets.map((b, i) => {
          const x = i * barWidth + BAR_GAP * 2;
          const w = barWidth - BAR_GAP * 4;
          const y = b.pnl >= 0 ? barYScale(b.pnl) : zeroY;
          const h = Math.max(1, Math.abs(barYScale(b.pnl) - zeroY));
          const positive = b.pnl > 0;
          const negative = b.pnl < 0;
          const isLast = i === n - 1;
          const isClipped =
            (b.pnl > yMax && yMax > 0) || (b.pnl < yMin && yMin < 0);
          const fill = positive
            ? 'rgba(52,211,153,0.6)'
            : negative
            ? 'rgba(248,113,113,0.6)'
            : 'rgba(255,255,255,0.15)';
          const stroke = isLast && live ? 'rgba(250,204,21,0.9)' : 'transparent';
          return (
            <g key={b.bucket_start}>
              <rect
                x={x}
                y={y}
                width={w}
                height={h}
                fill={fill}
                stroke={stroke}
                strokeWidth={isLast && live ? 2 : 0}
                vectorEffect="non-scaling-stroke"
                rx={1}
              />
              {/* Marker d'outlier (triangle) au top de la barre si clippé */}
              {isClipped && (
                <polygon
                  points={`${x + w / 2},${y - 3} ${x + w / 2 - 3},${y} ${x + w / 2 + 3},${y}`}
                  fill={positive ? '#34d399' : '#f87171'}
                  vectorEffect="non-scaling-stroke"
                />
              )}
              {/* Zone hover + click invisible (large pour UX mobile) */}
              <rect
                x={i * barWidth}
                y={0}
                width={barWidth}
                height={height - LABEL_PADDING}
                fill="transparent"
                style={{ cursor: drillable ? 'pointer' : 'default' }}
                onMouseEnter={() => setHoverIdx(i)}
                onClick={() => {
                  if (!drillable || !onBarClick || !child) return;
                  onBarClick({
                    label: bucketLabel(b, granularity),
                    start: b.bucket_start,
                    end: b.bucket_end,
                    granularity: child,
                  });
                }}
              />
            </g>
          );
        })}

        {/* Ligne cumul */}
        <path
          d={buckets
            .map((b, i) => `${i === 0 ? 'M' : 'L'} ${i * barWidth + barWidth / 2} ${lineYScale(b.cumulative_pnl)}`)
            .join(' ')}
          fill="none"
          stroke="#22d3ee"
          strokeWidth={2.5}
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />

        {/* Point sur chaque bucket de la ligne */}
        {buckets.map((b, i) => (
          <circle
            key={`pt-${b.bucket_start}`}
            cx={i * barWidth + barWidth / 2}
            cy={lineYScale(b.cumulative_pnl)}
            r={3}
            fill="#22d3ee"
            vectorEffect="non-scaling-stroke"
          />
        ))}

        {/* Pulse sur le dernier point si live */}
        {live && n > 0 && (
          <motion.circle
            cx={(n - 1) * barWidth + barWidth / 2}
            cy={lineYScale(buckets[n - 1].cumulative_pnl)}
            r={6}
            fill="#22d3ee"
            initial={{ scale: 0.4, opacity: 0.7 }}
            animate={{ scale: 1.6, opacity: 0 }}
            transition={{ duration: 1.6, repeat: Infinity, ease: 'easeOut' }}
            vectorEffect="non-scaling-stroke"
          />
        )}

        {/* Labels axe X */}
        {buckets.map((b, i) =>
          labelIdx.has(i) ? (
            <text
              key={`lbl-${b.bucket_start}`}
              x={i * barWidth + barWidth / 2}
              y={height - 4}
              textAnchor="middle"
              fontFamily="ui-monospace, monospace"
              fontSize={10}
              fill="rgba(255,255,255,0.4)"
            >
              {shortAxisLabel(b, granularity)}
            </text>
          ) : null
        )}
      </svg>

      {/* Tooltip */}
      {hoverIdx !== null && buckets[hoverIdx] && (
        <div
          className="pointer-events-none absolute top-0 rounded-lg border border-cyan-400/30 bg-[#0d111a] px-3 py-1.5 text-[11px] shadow-[0_8px_24px_rgba(0,0,0,0.6)]"
          style={{
            left: `${((hoverIdx + 0.5) / n) * 100}%`,
            transform: 'translate(-50%, -8px)',
            zIndex: 10,
            whiteSpace: 'nowrap',
          }}
        >
          <div className="font-semibold text-cyan-300">
            {bucketLabel(buckets[hoverIdx], granularity)}
          </div>
          <div className="text-white/70 font-mono tabular-nums">
            {buckets[hoverIdx].n_trades} trade{buckets[hoverIdx].n_trades > 1 ? 's' : ''}
            {' · '}
            <span
              className={clsx(
                buckets[hoverIdx].pnl > 0
                  ? 'text-emerald-300'
                  : buckets[hoverIdx].pnl < 0
                  ? 'text-rose-300'
                  : 'text-white/60'
              )}
            >
              {formatPnl(buckets[hoverIdx].pnl)}
            </span>
          </div>
          <div className="text-white/40 font-mono text-[10px]">
            cumul {formatPnl(buckets[hoverIdx].cumulative_pnl)}
          </div>
          {drillable && (
            <div className="text-cyan-400/60 text-[9px] mt-0.5">
              Clic pour zoom &rarr; {child}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
