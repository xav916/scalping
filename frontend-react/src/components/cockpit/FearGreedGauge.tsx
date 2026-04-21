import clsx from 'clsx';
import { motion } from 'motion/react';
import { GlassCard } from '@/components/ui/GlassCard';
import { Tooltip, LabelWithInfo } from '@/components/ui/Tooltip';
import { TIPS } from '@/lib/metricTips';
import type { FearGreedSnapshot } from '@/types/domain';

/** Jauge CNN Fear & Greed : 0-100 avec gradient 5 zones + label classifié. */
export function FearGreedGauge({ snapshot }: { snapshot: FearGreedSnapshot | null }) {
  if (!snapshot) {
    return (
      <GlassCard className="p-5 h-full">
        <h3 className="text-sm font-semibold tracking-tight mb-2">Fear &amp; Greed</h3>
        <p className="text-xs text-white/40">Pas de données — prochain fetch 22:30 UTC.</p>
      </GlassCard>
    );
  }

  const v = snapshot.value;
  const classif = snapshot.classification;
  const labelMap: Record<FearGreedSnapshot['classification'], { label: string; tone: string }> = {
    extreme_fear: { label: 'Extreme Fear', tone: 'from-rose-500 to-pink-400' },
    fear: { label: 'Fear', tone: 'from-pink-400 to-amber-300' },
    neutral: { label: 'Neutral', tone: 'from-amber-300 to-cyan-300' },
    greed: { label: 'Greed', tone: 'from-cyan-300 to-emerald-400' },
    extreme_greed: { label: 'Extreme Greed', tone: 'from-emerald-400 to-lime-300' },
  };
  const cfg = labelMap[classif];
  const classifTip = (TIPS.fearGreed as Record<string, string>)[classif] ?? TIPS.fearGreed.titre;

  return (
    <GlassCard className="p-5 h-full">
      <div className="flex items-center justify-between mb-3">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Fear &amp; Greed</h3>}
          tip={TIPS.fearGreed.titre}
        />
        <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">CNN</span>
      </div>
      <Tooltip content={TIPS.fearGreed.titre}>
        <div className="flex items-baseline gap-3 mb-2">
          <span className="text-4xl font-bold font-mono tabular-nums">{v}</span>
          <span className="text-[10px] text-white/40 uppercase tracking-widest">/100</span>
        </div>
      </Tooltip>
      <div className="w-full h-2 rounded-full bg-white/5 overflow-hidden relative">
        <motion.div
          className={clsx('h-full rounded-full bg-gradient-to-r', cfg.tone)}
          initial={{ width: 0 }}
          animate={{ width: `${Math.max(0, Math.min(100, v))}%` }}
          transition={{ duration: 0.7, ease: 'easeOut' }}
        />
      </div>
      <div className="mt-2 text-xs font-semibold uppercase tracking-wider">
        <Tooltip content={classifTip}>
          <span
            className={clsx(
              'px-2 py-0.5 rounded-md border',
              `bg-gradient-to-r ${cfg.tone} bg-clip-text text-transparent border-glass-soft`
            )}
          >
            {cfg.label}
          </span>
        </Tooltip>
      </div>
    </GlassCard>
  );
}
