import clsx from 'clsx';
import { motion } from 'motion/react';
import { useMacro } from '@/hooks/useMacro';
import { GlassCard } from '@/components/ui/GlassCard';
import { Skeleton } from '@/components/ui/Skeleton';
import type { MacroDirection, MacroSnapshot } from '@/types/domain';

function arrow(d: MacroDirection): string {
  if (d === 'up') return '↑';
  if (d === 'down') return '↓';
  return '→';
}

function Pill({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div
      className={clsx(
        'flex items-baseline gap-1.5 px-3 py-1.5 rounded-xl border backdrop-blur-glass',
        tone
      )}
    >
      <span className="text-[10px] uppercase tracking-wider font-medium opacity-70">{label}</span>
      <span className="text-sm font-mono font-semibold">{value}</span>
    </div>
  );
}

function toneForRegime(regime: MacroSnapshot['risk_regime']): string {
  if (regime === 'risk_on') return 'bg-emerald-400/10 text-emerald-300 border-emerald-400/30';
  if (regime === 'risk_off') return 'bg-rose-400/10 text-rose-300 border-rose-400/30';
  return 'bg-white/5 text-white/70 border-glass-soft';
}

function toneForDirection(d: MacroDirection): string {
  if (d === 'up') return 'bg-cyan-400/10 text-cyan-300 border-cyan-400/30';
  if (d === 'down') return 'bg-pink-400/10 text-pink-300 border-pink-400/30';
  return 'bg-white/5 text-white/60 border-glass-soft';
}

export function MacroBanner() {
  const { data, isLoading } = useMacro();

  if (isLoading) {
    return <Skeleton className="h-16 w-full" />;
  }
  if (!data) {
    return (
      <GlassCard className="p-4 text-sm text-white/50">
        Aucun snapshot macro disponible.
      </GlassCard>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
    >
      <GlassCard className="p-4 flex flex-wrap items-center gap-3">
        <Pill label="Régime" value={data.risk_regime.replace('_', '-').toUpperCase()} tone={toneForRegime(data.risk_regime)} />
        <Pill label="DXY" value={arrow(data.dxy)} tone={toneForDirection(data.dxy)} />
        <Pill label="SPX" value={arrow(data.spx)} tone={toneForDirection(data.spx)} />
        <Pill label="VIX" value={`${data.vix_level} · ${data.vix_value.toFixed(1)}`} tone={toneForDirection(data.vix_level === 'low' ? 'down' : data.vix_level === 'high' ? 'up' : 'neutral')} />
        <Pill label="US10Y" value={arrow(data.us10y)} tone={toneForDirection(data.us10y)} />
        <Pill label="Gold" value={arrow(data.gold)} tone={toneForDirection(data.gold)} />
        <Pill label="Oil" value={arrow(data.oil)} tone={toneForDirection(data.oil)} />
      </GlassCard>
    </motion.div>
  );
}
