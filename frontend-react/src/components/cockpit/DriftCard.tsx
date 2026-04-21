import { GlassCard } from '@/components/ui/GlassCard';
import { Skeleton } from '@/components/ui/Skeleton';
import { Tooltip, LabelWithInfo } from '@/components/ui/Tooltip';
import { useDrift } from '@/hooks/useCockpit';
import { TIPS } from '@/lib/metricTips';
import type { DriftFinding } from '@/types/domain';

/** Détection de drift : top 3 pairs/patterns en régression (delta win rate). */
export function DriftCard() {
  const { data, isLoading } = useDrift();
  if (isLoading) return <Skeleton className="h-40" />;
  const byPair = data?.by_pair ?? [];
  const byPattern = data?.by_pattern ?? [];
  const top3 = [...byPair, ...byPattern].sort((a, b) => a.delta_pct - b.delta_pct).slice(0, 3);

  return (
    <GlassCard className="p-5 h-full">
      <div className="flex items-center justify-between mb-3">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Drift détection</h3>}
          tip={TIPS.drift.titre}
        />
        <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">
          {data?.window_days ?? 7}j vs baseline
        </span>
      </div>
      {data?.error ? (
        <p className="text-xs text-rose-300/80">{data.error}</p>
      ) : top3.length === 0 ? (
        <Tooltip content={TIPS.drift.action}>
          <p className="text-xs text-white/40">Aucune régression détectée.</p>
        </Tooltip>
      ) : (
        <div className="space-y-2">
          {top3.map((f: DriftFinding) => (
            <Tooltip key={f.key} content={`${TIPS.drift.delta} ${TIPS.drift.action}`}>
              <div className="w-full flex items-center justify-between text-xs">
                <span className="font-mono text-white/85 truncate">{f.key}</span>
                <div className="flex items-center gap-2">
                  <span className="font-mono tabular-nums text-white/50">
                    {f.recent_win_rate_pct}% ← {f.baseline_win_rate_pct}%
                  </span>
                  <span className="font-mono font-semibold tabular-nums text-rose-300">
                    {f.delta_pct}pts
                  </span>
                </div>
              </div>
            </Tooltip>
          ))}
        </div>
      )}
    </GlassCard>
  );
}
