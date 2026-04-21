import clsx from 'clsx';
import { motion } from 'motion/react';
import { GlassCard } from '@/components/ui/GlassCard';
import { Tooltip, LabelWithInfo } from '@/components/ui/Tooltip';
import { TIPS } from '@/lib/metricTips';
import type { CockpitAlert } from '@/types/domain';

/** Stack d'alertes issues du cockpit (critical/warning/info). Cliquable sur
 *  chaque item pour avoir le détail via tooltip (tip mappé par code). */
export function AlertsStack({ alerts }: { alerts: CockpitAlert[] }) {
  if (alerts.length === 0) {
    return (
      <Tooltip content={TIPS.alerts.title}>
        <GlassCard className="w-full p-4 flex items-center justify-center text-sm text-white/40">
          Aucune alerte
        </GlassCard>
      </Tooltip>
    );
  }

  const toneFor = (lvl: CockpitAlert['level']) =>
    lvl === 'critical'
      ? 'border-rose-400/40 bg-rose-400/10 text-rose-300'
      : lvl === 'warning'
      ? 'border-amber-400/40 bg-amber-400/10 text-amber-300'
      : 'border-cyan-400/30 bg-cyan-400/5 text-cyan-300';

  const tipForCode = (code: string): string => {
    const map = TIPS.alerts as Record<string, string>;
    return map[code] ?? TIPS.alerts.title;
  };

  return (
    <GlassCard className="p-3">
      <div className="flex items-center justify-between mb-2 px-1">
        <LabelWithInfo
          label={<span className="text-[9px] uppercase tracking-[0.2em] text-white/40">Alertes</span>}
          tip={TIPS.alerts.title}
        />
        <span className="text-[9px] font-mono text-white/40">{alerts.length}</span>
      </div>
      <div className="flex flex-col gap-1.5 max-h-[140px] overflow-y-auto pr-1">
        {alerts.map((a, i) => (
          <Tooltip key={`${a.code}-${i}`} content={tipForCode(a.code)}>
            <motion.div
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.03 }}
              className={clsx(
                'w-full text-xs px-3 py-1.5 rounded-md border leading-snug',
                toneFor(a.level)
              )}
            >
              <span className="font-mono uppercase tracking-wider mr-2 opacity-60">{a.level}</span>
              {a.msg}
            </motion.div>
          </Tooltip>
        ))}
      </div>
    </GlassCard>
  );
}
