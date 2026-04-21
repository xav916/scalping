import { useMemo } from 'react';
import clsx from 'clsx';
import { motion } from 'motion/react';
import { GlassCard } from '@/components/ui/GlassCard';
import { Skeleton } from '@/components/ui/Skeleton';
import { Tooltip, LabelWithInfo } from '@/components/ui/Tooltip';
import { useCombos } from '@/hooks/useCockpit';
import { formatPnl } from '@/lib/format';
import { TIPS } from '@/lib/metricTips';
import type { ComboRow } from '@/types/domain';

/** Heatmap pattern × pair : matrice croisée des win rates pour identifier
 *  les combos gagnants et toxiques. Source : /api/stats/combos. */
export function CombosHeatmap() {
  const { data, isLoading } = useCombos();

  const grid = useMemo(() => {
    if (!data?.combos) return { patterns: [], pairs: [], cells: new Map<string, ComboRow>() };
    const patterns = Array.from(new Set(data.combos.map((c) => c.pattern))).sort();
    const pairs = Array.from(new Set(data.combos.map((c) => c.pair))).sort();
    const cells = new Map<string, ComboRow>();
    for (const c of data.combos) {
      cells.set(`${c.pattern}|${c.pair}`, c);
    }
    return { patterns, pairs, cells };
  }, [data]);

  if (isLoading) return <Skeleton className="h-72" />;

  if (!data || data.combos.length === 0) {
    return (
      <GlassCard variant="elevated" className="p-5">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Combos pattern × paire</h3>}
          tip={TIPS.combos.titre}
        />
        <p className="text-xs text-white/40 mt-4">
          Pas encore assez de trades clôturés pour construire la matrice. Revenir après quelques dizaines de trades.
        </p>
      </GlassCard>
    );
  }

  const minSignif = data.min_trades_for_significance;

  return (
    <GlassCard variant="elevated" className="p-5">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Combos pattern × paire</h3>}
          tip={TIPS.combos.titre}
        />
        <Tooltip content={TIPS.combos.minSignif}>
          <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">
            significatif ≥ {minSignif} trades
          </span>
        </Tooltip>
      </div>

      <div className="overflow-x-auto -mx-1 px-1">
        <div className="inline-block min-w-full">
          {/* Header : pair columns */}
          <div
            className="grid gap-1 mb-1 items-end"
            style={{
              gridTemplateColumns: `minmax(140px, 180px) repeat(${grid.pairs.length}, minmax(72px, 1fr))`,
            }}
          >
            <div />
            {grid.pairs.map((pair) => (
              <div
                key={pair}
                className="text-[9px] font-mono uppercase tracking-wider text-white/50 text-center pb-1 truncate"
              >
                {pair}
              </div>
            ))}
          </div>

          {/* Lignes : pattern × pairs */}
          {grid.patterns.map((pattern, rowIdx) => (
            <div
              key={pattern}
              className="grid gap-1 mb-1"
              style={{
                gridTemplateColumns: `minmax(140px, 180px) repeat(${grid.pairs.length}, minmax(72px, 1fr))`,
              }}
            >
              <div className="font-mono text-xs text-white/85 truncate flex items-center pr-2">
                {pattern}
              </div>
              {grid.pairs.map((pair) => {
                const cell = grid.cells.get(`${pattern}|${pair}`);
                return (
                  <HeatmapCell
                    key={pair}
                    cell={cell}
                    minSignif={minSignif}
                    delay={rowIdx * 0.02}
                  />
                );
              })}
            </div>
          ))}
        </div>
      </div>

      {/* Légende */}
      <div className="mt-4 pt-3 border-t border-glass-soft flex items-center flex-wrap gap-3 text-[10px] font-mono text-white/50">
        <span>Win rate :</span>
        <LegendSwatch tone="bg-emerald-400/30 border-emerald-400/50" label="> 60%" />
        <LegendSwatch tone="bg-cyan-400/20 border-cyan-400/40" label="50-60%" />
        <LegendSwatch tone="bg-amber-400/20 border-amber-400/40" label="45-50%" />
        <LegendSwatch tone="bg-rose-400/20 border-rose-400/40" label="< 45%" />
        <LegendSwatch tone="bg-white/[0.04] border-glass-soft" label="< significatif" />
      </div>
    </GlassCard>
  );
}

function HeatmapCell({
  cell,
  minSignif,
  delay,
}: {
  cell: ComboRow | undefined;
  minSignif: number;
  delay: number;
}) {
  if (!cell) {
    return (
      <div className="aspect-[2/1] rounded border border-white/5 bg-white/[0.015]" />
    );
  }
  const significant = cell.total >= minSignif;
  const wr = cell.win_rate_pct;
  const tone = !significant
    ? 'bg-white/[0.04] border-glass-soft text-white/40'
    : wr > 60
    ? 'bg-emerald-400/20 border-emerald-400/50 text-emerald-200'
    : wr >= 50
    ? 'bg-cyan-400/15 border-cyan-400/40 text-cyan-200'
    : wr >= 45
    ? 'bg-amber-400/15 border-amber-400/40 text-amber-200'
    : 'bg-rose-400/15 border-rose-400/40 text-rose-200';
  const pnlTone =
    cell.total_pnl > 0 ? 'text-emerald-300/80' : cell.total_pnl < 0 ? 'text-rose-300/80' : 'text-white/40';

  return (
    <Tooltip content={
      <>
        <div className="font-mono font-semibold mb-1">
          {cell.pattern} · {cell.pair}
        </div>
        <div>Win rate : <span className="font-mono font-semibold">{wr}%</span></div>
        <div>Trades : {cell.wins} W · {cell.losses} L · {cell.total} total {!significant && '(insignificant)'}</div>
        <div>PnL cumulé : <span className={clsx('font-mono', pnlTone)}>{formatPnl(cell.total_pnl)}</span></div>
        <div className="mt-1 text-white/60 text-[10px]">{TIPS.combos.cell}</div>
      </>
    }>
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay, duration: 0.2 }}
        className={clsx(
          'aspect-[2/1] rounded border flex flex-col items-center justify-center text-[10px] font-mono tabular-nums px-1',
          tone
        )}
      >
        <span className="font-bold">{wr}%</span>
        <span className="text-[8px] opacity-60">n={cell.total}</span>
      </motion.div>
    </Tooltip>
  );
}

function LegendSwatch({ tone, label }: { tone: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={clsx('inline-block w-3 h-3 rounded border', tone)} />
      <span>{label}</span>
    </span>
  );
}
