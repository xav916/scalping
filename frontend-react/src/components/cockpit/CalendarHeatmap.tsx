import { useMemo, useState } from 'react';
import clsx from 'clsx';
import type { PnlBucket } from '@/types/domain';
import { formatPnl } from '@/lib/format';

interface Props {
  /** Buckets granularité `day`, tri chronologique ascendant. */
  buckets: PnlBucket[];
  /** Clic sur une case → reçoit le ISO start du jour. */
  onDayClick?: (iso: string, label: string) => void;
}

const CELL = 13;   // largeur/hauteur d'une case (px en coord SVG)
const GAP = 2;     // gap entre cases
const LEFT_AXIS_W = 18;
const TOP_AXIS_H = 14;

// Shades du plus foncé au plus clair (vert win, rose loss). Niveau 0 = vide.
const GREEN_SHADES = [
  'rgba(255,255,255,0.04)',          // 0 — vide
  'rgba(52,211,153,0.20)',           // 1
  'rgba(52,211,153,0.40)',           // 2
  'rgba(52,211,153,0.65)',           // 3
  '#34d399',                          // 4 — emerald-400
];
const RED_SHADES = [
  'rgba(255,255,255,0.04)',          // 0 — vide
  'rgba(248,113,113,0.20)',
  'rgba(248,113,113,0.40)',
  'rgba(248,113,113,0.65)',
  '#f87171',                          // 4 — rose-400
];

function dayOfWeekMondayFirst(d: Date): number {
  // JS: 0 dim ... 6 sam. On veut 0 lun ... 6 dim.
  return (d.getUTCDay() + 6) % 7;
}

function startOfMondayWeek(d: Date): Date {
  const dow = dayOfWeekMondayFirst(d);
  const anchor = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  anchor.setUTCDate(anchor.getUTCDate() - dow);
  return anchor;
}

function addDays(d: Date, n: number): Date {
  const r = new Date(d);
  r.setUTCDate(r.getUTCDate() + n);
  return r;
}

function formatDayLabel(iso: string): string {
  return new Date(iso).toLocaleDateString('fr-FR', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

/** Heatmap style GitHub contributions : grille 7 (jours) × N (semaines).
 *  Case coloree par intensité |pnl_day|. Axe X = mois. */
export function CalendarHeatmap({ buckets, onDayClick }: Props) {
  const [hover, setHover] = useState<{ idx: number; x: number; y: number } | null>(null);

  const { cells, totalWidth, height, monthLabels, maxAbs } = useMemo(() => {
    if (buckets.length === 0) {
      return {
        cells: [],
        totalWidth: 0,
        height: TOP_AXIS_H + 7 * (CELL + GAP),
        monthLabels: [],
        maxAbs: 0,
      };
    }
    const first = new Date(buckets[0].bucket_start);
    const last = new Date(buckets[buckets.length - 1].bucket_start);
    const firstMonday = startOfMondayWeek(first);
    const totalDays = Math.floor((last.getTime() - firstMonday.getTime()) / 86_400_000) + 1;
    const weeks = Math.ceil(totalDays / 7);
    const w = LEFT_AXIS_W + weeks * (CELL + GAP);
    const h = TOP_AXIS_H + 7 * (CELL + GAP);

    const absList = buckets.map((b) => Math.abs(b.pnl));
    const maxAbs = Math.max(1, ...absList);

    // Index buckets par date ISO (YYYY-MM-DD)
    const byDate = new Map<string, PnlBucket>();
    for (const b of buckets) {
      const d = new Date(b.bucket_start);
      const key = d.toISOString().slice(0, 10);
      byDate.set(key, b);
    }

    // Génère toutes les cellules (y compris avant le 1er bucket, dans la
    // grille de la semaine : ces cases sont dimmées)
    type Cell = {
      iso: string;
      x: number;
      y: number;
      bucket: PnlBucket | null;
      inRange: boolean;
      isFirstOfMonth: boolean;
    };
    const cells: Cell[] = [];
    for (let i = 0; i < weeks * 7; i++) {
      const d = addDays(firstMonday, i);
      const key = d.toISOString().slice(0, 10);
      const week = Math.floor(i / 7);
      const dow = i % 7;
      const b = byDate.get(key) || null;
      const inRange =
        d.getTime() >= new Date(buckets[0].bucket_start).getTime() &&
        d.getTime() <= new Date(buckets[buckets.length - 1].bucket_start).getTime();
      cells.push({
        iso: d.toISOString(),
        x: LEFT_AXIS_W + week * (CELL + GAP),
        y: TOP_AXIS_H + dow * (CELL + GAP),
        bucket: b,
        inRange,
        isFirstOfMonth: d.getUTCDate() === 1,
      });
    }

    // Labels mois : un par bloc de 4+ cases consecutives du même mois en
    // ligne top (Lundi).
    const monthLabels: Array<{ x: number; label: string }> = [];
    let currentMonth = -1;
    for (let wk = 0; wk < weeks; wk++) {
      const d = addDays(firstMonday, wk * 7);
      const m = d.getUTCMonth();
      if (m !== currentMonth) {
        currentMonth = m;
        monthLabels.push({
          x: LEFT_AXIS_W + wk * (CELL + GAP),
          label: d.toLocaleDateString('fr-FR', { month: 'short', timeZone: 'UTC' }),
        });
      }
    }

    return { cells, totalWidth: w, height: h, monthLabels, maxAbs };
  }, [buckets]);

  if (buckets.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-xs text-white/30 rounded-lg border border-white/5"
        style={{ height: TOP_AXIS_H + 7 * (CELL + GAP) }}
      >
        Pas de données
      </div>
    );
  }

  const hoverCell = hover ? cells[hover.idx] : null;

  return (
    <div className="relative overflow-x-auto">
      <svg
        width={totalWidth}
        height={height}
        style={{ display: 'block', minWidth: totalWidth }}
      >
        {/* Month labels */}
        {monthLabels.map((ml) => (
          <text
            key={`m-${ml.x}`}
            x={ml.x}
            y={10}
            fontSize={9}
            fontFamily="ui-monospace, monospace"
            fill="rgba(255,255,255,0.4)"
          >
            {ml.label}
          </text>
        ))}

        {/* Day-of-week labels (une sur deux pour la densité) */}
        {['L', '', 'M', '', 'V', '', 'D'].map((lbl, i) =>
          lbl ? (
            <text
              key={`dow-${i}`}
              x={0}
              y={TOP_AXIS_H + i * (CELL + GAP) + CELL * 0.75}
              fontSize={9}
              fontFamily="ui-monospace, monospace"
              fill="rgba(255,255,255,0.3)"
            >
              {lbl}
            </text>
          ) : null
        )}

        {/* Cells */}
        {cells.map((c, idx) => {
          const b = c.bucket;
          let fill: string;
          if (!c.inRange || !b) {
            fill = 'rgba(255,255,255,0.03)';
          } else if (b.pnl === 0) {
            fill = 'rgba(255,255,255,0.08)';
          } else {
            const intensity = Math.min(1, Math.abs(b.pnl) / maxAbs);
            const level = Math.max(1, Math.ceil(intensity * 4));
            fill = (b.pnl > 0 ? GREEN_SHADES : RED_SHADES)[level];
          }
          return (
            <g key={idx}>
              <rect
                x={c.x}
                y={c.y}
                width={CELL}
                height={CELL}
                rx={2}
                fill={fill}
                stroke={c.isFirstOfMonth ? 'rgba(255,255,255,0.12)' : 'transparent'}
                strokeWidth={0.5}
                style={{ cursor: onDayClick && b ? 'pointer' : 'default' }}
                onMouseEnter={() => setHover({ idx, x: c.x + CELL / 2, y: c.y })}
                onMouseLeave={() => setHover(null)}
                onClick={() => {
                  if (!onDayClick || !b) return;
                  onDayClick(b.bucket_start, formatDayLabel(b.bucket_start));
                }}
              />
            </g>
          );
        })}
      </svg>

      {/* Tooltip */}
      {hover && hoverCell && (
        <div
          className="pointer-events-none absolute rounded-lg border border-cyan-400/30 bg-[#0d111a] px-2.5 py-1.5 text-[11px] shadow-[0_8px_24px_rgba(0,0,0,0.6)]"
          style={{
            left: Math.min(hover.x, totalWidth - 180),
            top: hover.y + CELL + 4,
            zIndex: 10,
            whiteSpace: 'nowrap',
          }}
        >
          <div className="font-semibold text-cyan-300">{formatDayLabel(hoverCell.iso)}</div>
          {hoverCell.bucket ? (
            <>
              <div className="text-white/70 font-mono tabular-nums">
                {hoverCell.bucket.n_trades} trade{hoverCell.bucket.n_trades > 1 ? 's' : ''}
                {' · '}
                <span
                  className={clsx(
                    hoverCell.bucket.pnl > 0
                      ? 'text-emerald-300'
                      : hoverCell.bucket.pnl < 0
                      ? 'text-rose-300'
                      : 'text-white/60'
                  )}
                >
                  {formatPnl(hoverCell.bucket.pnl)}
                </span>
              </div>
              <div className="text-white/40 font-mono text-[10px]">
                cumul {formatPnl(hoverCell.bucket.cumulative_pnl)}
              </div>
              {onDayClick && hoverCell.bucket.n_trades > 0 && (
                <div className="text-cyan-400/60 text-[9px] mt-0.5">Clic pour zoomer</div>
              )}
            </>
          ) : (
            <div className="text-white/40 font-mono text-[10px]">Pas de trade</div>
          )}
        </div>
      )}

      {/* Legend */}
      <div className="flex items-center gap-2 mt-2 text-[9px] font-mono text-white/40">
        <span>Moins</span>
        {RED_SHADES.slice(1).reverse().map((c, i) => (
          <span
            key={`ln-${i}`}
            className="inline-block rounded-sm"
            style={{ width: 10, height: 10, background: c }}
          />
        ))}
        <span className="inline-block rounded-sm" style={{ width: 10, height: 10, background: 'rgba(255,255,255,0.08)' }} />
        {GREEN_SHADES.slice(1).map((c, i) => (
          <span
            key={`lp-${i}`}
            className="inline-block rounded-sm"
            style={{ width: 10, height: 10, background: c }}
          />
        ))}
        <span>Plus</span>
      </div>
    </div>
  );
}
