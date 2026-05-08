import { useQuery } from '@tanstack/react-query';
import { motion } from 'motion/react';
import clsx from 'clsx';
import { api, ApiError } from '@/lib/api';
import { GlassCard } from '@/components/ui/GlassCard';
import { Skeleton } from '@/components/ui/Skeleton';

const RULE_LABELS: Record<string, string> = {
  iran_hormuz: 'Iran / Hormuz',
  fed_dovish: 'Fed dovish',
  recession: 'Recession',
  gdelt_stress: 'GDELT stress',
  unknown: 'Inconnue',
};

const RULE_COLORS: Record<string, string> = {
  iran_hormuz: 'from-amber-500 to-orange-400',
  fed_dovish: 'from-cyan-500 to-blue-400',
  recession: 'from-rose-500 to-pink-400',
  gdelt_stress: 'from-violet-500 to-purple-400',
  unknown: 'from-white/30 to-white/10',
};

/**
 * Card admin Geopolitical Veto Activity : compte les setups skip par les
 * 4 règles veto sur les N derniers jours, ventilation par règle / par pair /
 * par jour. Permet de juger en 5s si les seuils mordent trop ou pas assez.
 *
 * Source : `/api/admin/geopolitical-veto-stats?days=7`. Refresh 60s.
 */
export function GeopoliticalVetoActivityCard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['admin', 'geopolitical-veto-stats'],
    queryFn: () => api.adminGeopoliticalVetoStats(7),
    retry: 0,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  if (isLoading) return <Skeleton className="w-full h-48" />;
  if (error || !data) {
    const msg = error instanceof ApiError ? error.message : 'Indisponible';
    return (
      <GlassCard className="p-4">
        <h3 className="text-sm font-semibold text-rose-300 mb-1">Geopolitical Veto</h3>
        <p className="text-xs text-white/60">{msg}</p>
      </GlassCard>
    );
  }

  const totalByRule = Object.entries(data.by_rule)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1]);
  const maxRuleCount = Math.max(1, ...totalByRule.map(([, c]) => c));
  const maxDayCount = Math.max(1, ...data.by_day.map((d) => d.count));

  return (
    <GlassCard className="p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold tracking-tight">Geopolitical Veto activity</h3>
          <p className="text-[11px] text-white/50">
            Setups skip par les 4 règles veto sur les 7 derniers jours · refresh 60s
          </p>
        </div>
        <div className="text-right">
          <div className="text-2xl font-bold tabular-nums">{data.total}</div>
          <div className="text-[10px] text-white/40 uppercase tracking-wider">vetos 7j</div>
        </div>
      </div>

      {data.total === 0 ? (
        <div className="text-xs text-white/50 py-4 text-center border border-dashed border-white/10 rounded">
          Aucun veto déclenché. Soit le contexte géopolitique est calme, soit les
          seuils sont trop hauts. Voir <code>config/settings.py</code> pour ajuster.
        </div>
      ) : (
        <>
          {/* Ventilation par règle */}
          <div className="space-y-2">
            <div className="text-[10px] uppercase tracking-wider text-white/40">Par règle</div>
            {totalByRule.map(([rule, count]) => (
              <div key={rule} className="flex items-center gap-2">
                <span className="w-28 text-[11px] text-white/70 shrink-0">
                  {RULE_LABELS[rule] ?? rule}
                </span>
                <div className="flex-1 h-2 rounded-full bg-white/5 overflow-hidden">
                  <motion.div
                    className={clsx(
                      'h-full rounded-full bg-gradient-to-r',
                      RULE_COLORS[rule] ?? RULE_COLORS.unknown,
                    )}
                    initial={{ width: 0 }}
                    animate={{ width: `${(count / maxRuleCount) * 100}%` }}
                    transition={{ duration: 0.5, ease: 'easeOut' }}
                  />
                </div>
                <span className="w-10 text-right text-[11px] font-mono tabular-nums">
                  {count}
                </span>
              </div>
            ))}
          </div>

          {/* Top pairs touchés */}
          {data.by_pair.length > 0 && (
            <div className="space-y-2 pt-2 border-t border-white/5">
              <div className="text-[10px] uppercase tracking-wider text-white/40">
                Top paires bloquées
              </div>
              <div className="flex flex-wrap gap-1.5">
                {data.by_pair.slice(0, 8).map((p) => (
                  <span
                    key={p.pair}
                    className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-white/5 border border-white/10"
                  >
                    {p.pair} · {p.count}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Mini chart par jour */}
          {data.by_day.length > 0 && (
            <div className="space-y-2 pt-2 border-t border-white/5">
              <div className="text-[10px] uppercase tracking-wider text-white/40">
                Par jour ({data.by_day.length} actifs)
              </div>
              <div className="flex items-end gap-1 h-12">
                {data.by_day.map((d) => (
                  <div
                    key={d.date}
                    className="flex-1 flex flex-col justify-end"
                    title={`${d.date} : ${d.count} vetos`}
                  >
                    <motion.div
                      className="w-full rounded-t-sm bg-gradient-to-t from-cyan-500/40 to-cyan-300/60"
                      initial={{ height: 0 }}
                      animate={{ height: `${(d.count / maxDayCount) * 100}%` }}
                      transition={{ duration: 0.5, ease: 'easeOut' }}
                    />
                    <div className="text-[8px] text-white/30 text-center mt-0.5 tabular-nums">
                      {d.date.slice(5)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Liste des 20 derniers vetos */}
          {data.recent.length > 0 && (
            <details className="pt-2 border-t border-white/5">
              <summary className="text-[10px] uppercase tracking-wider text-white/40 cursor-pointer hover:text-white/60">
                Derniers vetos ({data.recent.length})
              </summary>
              <div className="mt-2 space-y-1 max-h-64 overflow-y-auto pr-1">
                {data.recent.map((r, i) => (
                  <div
                    key={`${r.created_at}-${i}`}
                    className="text-[10px] py-1.5 px-2 rounded bg-white/[0.02] border-l-2"
                    style={{ borderLeftColor: 'rgba(34, 211, 238, 0.5)' }}
                  >
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="font-mono text-white/70">{r.pair}</span>
                      <span className="text-white/30 text-[9px]">
                        {r.direction ?? '?'}
                      </span>
                      <span className="text-cyan-300 text-[9px] font-medium">
                        {RULE_LABELS[r.rule] ?? r.rule}
                      </span>
                      <span className="ml-auto text-white/30 text-[9px] tabular-nums">
                        {r.created_at.slice(11, 16)} {r.created_at.slice(0, 10)}
                      </span>
                    </div>
                    <div className="text-white/50 line-clamp-1">{r.reason}</div>
                  </div>
                ))}
              </div>
            </details>
          )}
        </>
      )}
    </GlassCard>
  );
}
