import clsx from 'clsx';
import { GlassCard } from '@/components/ui/GlassCard';
import { Tooltip, LabelWithInfo } from '@/components/ui/Tooltip';
import { TIPS } from '@/lib/metricTips';

interface MacroEvent {
  time: string;
  currency: string;
  impact: string;
  event_name: string;
}

/** Events macro imminents (≤ 4h) : NFP, CPI, FOMC, BCE, etc. Impact tone. */
export function NextEventsCard({ events }: { events: MacroEvent[] }) {
  return (
    <GlassCard className="p-5">
      <div className="flex items-center justify-between mb-3">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Events macro imminents</h3>}
          tip={TIPS.events.titre}
        />
        <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">≤ 4h</span>
      </div>
      {events.length === 0 ? (
        <p className="text-xs text-white/40">Aucun event imminent.</p>
      ) : (
        <div className="space-y-2">
          {events.map((e, i) => {
            const when = e.time?.includes('T')
              ? new Date(e.time).toLocaleTimeString('fr-FR', {
                  hour: '2-digit',
                  minute: '2-digit',
                })
              : e.time;
            const impact = (e.impact || '').toUpperCase();
            const impactTone =
              impact === 'HIGH'
                ? 'text-rose-300 border-rose-400/30 bg-rose-400/5'
                : 'text-amber-300 border-amber-400/30 bg-amber-400/5';
            const impactTip =
              impact === 'HIGH'
                ? TIPS.events.impactHigh
                : impact === 'MEDIUM'
                ? TIPS.events.impactMedium
                : TIPS.events.impactLow;
            return (
              <div key={i} className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="font-mono tabular-nums text-white/70 w-14 flex-shrink-0">
                    {when}
                  </span>
                  <Tooltip content={impactTip}>
                    <span
                      className={clsx(
                        'text-[9px] font-bold uppercase tracking-widest px-1.5 py-0.5 rounded border',
                        impactTone
                      )}
                    >
                      {e.impact || '—'}
                    </span>
                  </Tooltip>
                  <span className="font-mono text-white/60 text-[11px] flex-shrink-0">
                    {e.currency}
                  </span>
                </div>
                <span className="text-white/80 truncate ml-2 text-right">{e.event_name}</span>
              </div>
            );
          })}
        </div>
      )}
    </GlassCard>
  );
}
