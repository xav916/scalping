import clsx from 'clsx';
import type { Preset, PeriodKey } from '@/types/domain';
import { DateRangePopover } from '@/components/ui/DateRangePopover';
import { Tooltip } from '@/components/ui/Tooltip';

interface Props {
  preset: Preset;
  start: string;
  end: string;
  onSetPreset(p: Exclude<Preset, 'custom'>): void;
  onSetCustomRange(start: string, end: string): void;
  onShift(dir: -1 | 1): void;
  onReset(): void;
}

const TABS: Array<{ key: PeriodKey; label: string }> = [
  { key: 'day', label: 'Jour' },
  { key: 'week', label: 'Semaine' },
  { key: 'month', label: 'Mois' },
  { key: 'year', label: 'Année' },
  { key: 'all', label: 'Tout' },
];

function formatRange(startIso: string, endIso: string): string {
  const s = new Date(startIso);
  const e = new Date(endIso);
  const sameYear = s.getUTCFullYear() === e.getUTCFullYear();
  const fmtStart = s.toLocaleDateString('fr-FR', {
    day: '2-digit',
    month: 'short',
    year: sameYear ? undefined : 'numeric',
    timeZone: 'UTC',
  });
  const fmtEnd = e.toLocaleDateString('fr-FR', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  });
  return `${fmtStart} → ${fmtEnd}`;
}

export function RangeToolbar({
  preset,
  start,
  end,
  onSetPreset,
  onSetCustomRange,
  onShift,
  onReset,
}: Props) {
  const shiftDisabled = preset === 'all' || preset === 'custom';

  return (
    <div className="space-y-2.5">
      {/* Tabs */}
      <div className="flex items-center gap-1 flex-wrap">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => onSetPreset(t.key)}
            className={clsx(
              'text-xs px-3 py-1.5 rounded-lg border transition-all font-semibold',
              preset === t.key
                ? 'border-cyan-400/40 bg-cyan-400/10 text-cyan-300 shadow-[0_0_12px_rgba(34,211,238,0.15)]'
                : 'border-glass-soft text-white/50 hover:text-white/90 hover:bg-white/[0.03]'
            )}
          >
            {t.label}
          </button>
        ))}
        {preset === 'custom' && (
          <span className="text-[10px] uppercase tracking-[0.2em] text-cyan-300/80 font-mono px-2 py-1 border border-cyan-400/30 rounded-lg">
            custom
          </span>
        )}
      </div>

      {/* Range contrôle */}
      <div className="flex items-center gap-2 flex-wrap">
        <Tooltip content="Période précédente" delay={400}>
          <button
            type="button"
            onClick={() => onShift(-1)}
            disabled={shiftDisabled}
            className={clsx(
              'w-7 h-7 flex items-center justify-center rounded-lg border transition-colors',
              shiftDisabled
                ? 'border-white/5 text-white/20 cursor-not-allowed'
                : 'border-white/10 text-white/60 hover:text-cyan-300 hover:border-cyan-400/30 hover:bg-cyan-400/5'
            )}
            aria-label="Période précédente"
          >
            ←
          </button>
        </Tooltip>

        <DateRangePopover startIso={start} endIso={end} onApply={onSetCustomRange}>
          <button
            type="button"
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-white/10 bg-white/[0.02] text-xs font-mono hover:border-cyan-400/30 hover:bg-cyan-400/5 transition-colors"
          >
            <span className="text-white/40">Du</span>
            <span className="text-cyan-300 tabular-nums">{formatRange(start, end)}</span>
            <span className="text-white/30">▼</span>
          </button>
        </DateRangePopover>

        <Tooltip content="Période suivante" delay={400}>
          <button
            type="button"
            onClick={() => onShift(1)}
            disabled={shiftDisabled}
            className={clsx(
              'w-7 h-7 flex items-center justify-center rounded-lg border transition-colors',
              shiftDisabled
                ? 'border-white/5 text-white/20 cursor-not-allowed'
                : 'border-white/10 text-white/60 hover:text-cyan-300 hover:border-cyan-400/30 hover:bg-cyan-400/5'
            )}
            aria-label="Période suivante"
          >
            →
          </button>
        </Tooltip>

        {preset === 'custom' && (
          <Tooltip content="Retour à Semaine" delay={400}>
            <button
              type="button"
              onClick={onReset}
              className="text-[10px] uppercase tracking-wider px-2.5 py-1.5 rounded-lg border border-rose-400/20 text-rose-300/80 hover:text-rose-300 hover:bg-rose-400/10 transition-colors"
            >
              Reset
            </button>
          </Tooltip>
        )}
      </div>
    </div>
  );
}
