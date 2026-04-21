import { GlassCard } from '@/components/ui/GlassCard';
import { Tooltip, LabelWithInfo } from '@/components/ui/Tooltip';
import { TIPS } from '@/lib/metricTips';
import type { CotExtreme } from '@/types/domain';

/** Positionnements CFTC extrêmes (z-score ≥ 2σ sur 52 semaines). */
export function CotExtremesCard({ items }: { items: CotExtreme[] }) {
  return (
    <GlassCard className="p-5">
      <div className="flex items-center justify-between mb-3">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">COT extremes</h3>}
          tip={TIPS.cot.titre}
        />
        <Tooltip content={TIPS.cot.z}>
          <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">
            z ≥ 2σ / 52s
          </span>
        </Tooltip>
      </div>
      {items.length === 0 ? (
        <p className="text-xs text-white/40">Aucun extrême cette semaine.</p>
      ) : (
        <div className="space-y-2">
          {items.map((it) => (
            <div key={it.pair} className="border-l-2 border-cyan-400/30 pl-3">
              <div className="text-sm font-mono font-semibold">{it.pair}</div>
              {it.signals.map((s, i) => {
                const actorTip =
                  (TIPS.cot as Record<string, string>)[s.actor] ?? TIPS.cot.titre;
                return (
                  <Tooltip key={i} content={actorTip}>
                    <div className="text-[11px] text-white/60 leading-snug">
                      <span className="font-mono tabular-nums text-cyan-300 mr-1.5">
                        z={s.z}
                      </span>
                      {s.interpretation}
                    </div>
                  </Tooltip>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  );
}
