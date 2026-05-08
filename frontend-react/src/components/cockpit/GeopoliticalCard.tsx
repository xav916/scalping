import clsx from 'clsx';
import { motion } from 'motion/react';
import { GlassCard } from '@/components/ui/GlassCard';
import { Tooltip, LabelWithInfo } from '@/components/ui/Tooltip';
import type { GeopoliticalSnapshot, GeopoliticalStress } from '@/types/domain';

const THEME_LABELS: Record<string, string> = {
  monetary: 'Monétaire',
  geopolitical: 'Géopolitique',
  energy: 'Énergie',
  trade: 'Commerce',
};

const THEME_TIPS: Record<string, string> = {
  monetary: 'Couverture news Fed / BCE / BoE / taux directeurs / inflation',
  geopolitical: 'Couverture news Ukraine / Iran / Taïwan / sanctions / conflits',
  energy: 'Couverture news OPEC / pétrole / gaz / sanctions énergie',
  trade: 'Couverture news Chine / tariffs / semiconducteurs / guerre commerciale',
};

const STRESS_CFG: Record<GeopoliticalStress, { label: string; color: string; barTone: string }> = {
  calm: {
    label: 'CALME',
    color: 'text-emerald-400 border-emerald-400/30',
    barTone: 'from-emerald-400 to-cyan-300',
  },
  elevated: {
    label: 'TENDU',
    color: 'text-amber-300 border-amber-300/30',
    barTone: 'from-amber-300 to-orange-400',
  },
  high: {
    label: 'STRESS',
    color: 'text-rose-400 border-rose-400/30',
    barTone: 'from-rose-500 to-pink-400',
  },
};

/** Map tone GDELT [-10..+5] vers % visuel [0..100]. tone=0 → 67%. */
function toneToPercent(tone: number): number {
  const clamped = Math.max(-10, Math.min(5, tone));
  return ((clamped + 10) / 15) * 100;
}

/** Snapshot GDELT : tone moyen 24h sur 4 thèmes (shadow only). */
export function GeopoliticalCard({ snapshot }: { snapshot: GeopoliticalSnapshot | null }) {
  if (!snapshot) {
    return (
      <GlassCard className="p-5 h-full">
        <h3 className="text-sm font-semibold tracking-tight mb-2">Tension géopolitique</h3>
        <p className="text-xs text-white/40">Pas de données — refresh horaire GDELT.</p>
      </GlassCard>
    );
  }

  const overallCfg = STRESS_CFG[snapshot.overall_stress];
  const themes = Object.entries(snapshot.themes);

  return (
    <GlassCard className="p-5 h-full">
      <div className="flex items-center justify-between mb-3">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Tension géopolitique</h3>}
          tip="Tonalité moyenne des news mondiales sur 24h via GDELT 2.0. Range pratique -10..+5 (le tone moyen mondial habituel ≈ -2). Plus c'est négatif, plus la couverture est anxiogène. Shadow only — pas branché au scoring."
        />
        <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">GDELT</span>
      </div>

      <div className="flex items-baseline gap-3 mb-1">
        <span className="text-3xl font-bold font-mono tabular-nums">{snapshot.overall_tone}</span>
        <span className="text-[10px] text-white/40 uppercase tracking-widest">tone 24h</span>
      </div>

      <div className="mb-3">
        <Tooltip content={`Stress global = max des stress par thème. ${themes.length} thèmes lus.`}>
          <span
            className={clsx(
              'inline-block text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md border',
              overallCfg.color
            )}
          >
            {overallCfg.label}
          </span>
        </Tooltip>
      </div>

      <div className="space-y-2 mt-3 pt-3 border-t border-white/5">
        {themes.map(([key, reading]) => {
          const cfg = STRESS_CFG[reading.stress_level];
          const pct = toneToPercent(reading.avg_tone);
          const tip = THEME_TIPS[key] ?? key;
          return (
            <div key={key}>
              <div className="flex items-baseline justify-between text-[11px] mb-1">
                <Tooltip content={tip}>
                  <span className="text-white/70">{THEME_LABELS[key] ?? key}</span>
                </Tooltip>
                <span className={clsx('font-mono tabular-nums text-[10px]', cfg.color)}>
                  {reading.avg_tone}
                </span>
              </div>
              <div className="w-full h-1 rounded-full bg-white/5 overflow-hidden">
                <motion.div
                  className={clsx('h-full rounded-full bg-gradient-to-r', cfg.barTone)}
                  initial={{ width: 0 }}
                  animate={{ width: `${pct}%` }}
                  transition={{ duration: 0.6, ease: 'easeOut' }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </GlassCard>
  );
}
