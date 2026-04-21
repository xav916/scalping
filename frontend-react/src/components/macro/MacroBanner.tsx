import clsx from 'clsx';
import { motion } from 'motion/react';
import { useMacro } from '@/hooks/useMacro';
import { GlassCard } from '@/components/ui/GlassCard';
import { Skeleton } from '@/components/ui/Skeleton';
import type { MacroDirection, MacroSnapshot, VixLevel } from '@/types/domain';

function DirectionArrow({ d }: { d: MacroDirection }) {
  if (d === 'neutral') {
    return (
      <span className="inline-block w-3 text-center text-white/40 leading-none">—</span>
    );
  }
  return (
    <motion.span
      className="inline-block w-3 text-center leading-none font-bold"
      animate={{ y: d === 'up' ? [-1, 1, -1] : [1, -1, 1] }}
      transition={{ duration: 2.4, repeat: Infinity, ease: 'easeInOut' }}
    >
      {d === 'up' ? '↑' : '↓'}
    </motion.span>
  );
}

function Pill({
  label,
  children,
  tone,
  index = 0,
}: {
  label: string;
  children: React.ReactNode;
  tone: string;
  index?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: -6, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.35, delay: 0.05 * index, ease: 'easeOut' }}
      className={clsx(
        'flex items-center gap-2 px-3.5 py-2 rounded-xl border backdrop-blur-glass transition-colors',
        tone
      )}
    >
      <span className="text-[9px] uppercase tracking-[0.15em] font-medium opacity-60">{label}</span>
      <span className="flex items-center gap-1 text-sm font-mono font-semibold">{children}</span>
    </motion.div>
  );
}

function toneForRegime(regime: MacroSnapshot['risk_regime']): string {
  if (regime === 'risk_on') return 'bg-emerald-400/10 text-emerald-300 border-emerald-400/30 shadow-[0_0_20px_rgba(52,211,153,0.12)]';
  if (regime === 'risk_off') return 'bg-rose-400/10 text-rose-300 border-rose-400/30 shadow-[0_0_20px_rgba(244,63,94,0.12)]';
  return 'bg-white/5 text-white/70 border-glass-soft';
}

function toneForDirection(d: MacroDirection): string {
  if (d === 'up') return 'bg-cyan-400/10 text-cyan-300 border-cyan-400/30';
  if (d === 'down') return 'bg-pink-400/10 text-pink-300 border-pink-400/30';
  return 'bg-white/5 text-white/60 border-glass-soft';
}

function toneForVix(level: VixLevel): string {
  if (level === 'low') return 'bg-emerald-400/10 text-emerald-300 border-emerald-400/30';
  if (level === 'normal') return 'bg-white/5 text-white/80 border-glass-soft';
  if (level === 'elevated') return 'bg-amber-400/10 text-amber-300 border-amber-400/30';
  return 'bg-rose-400/10 text-rose-300 border-rose-400/30';
}

function regimeLabel(regime: MacroSnapshot['risk_regime']): string {
  if (regime === 'risk_on') return 'RISK·ON';
  if (regime === 'risk_off') return 'RISK·OFF';
  return 'NEUTRAL';
}

export function MacroBanner() {
  const { data, isLoading } = useMacro();

  if (isLoading) {
    return <Skeleton className="h-20 w-full" />;
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
      <GlassCard className="p-4">
        <div className="flex flex-wrap items-center gap-2.5">
          <Pill label="Régime" tone={toneForRegime(data.risk_regime)} index={0}>
            <span className="tracking-[0.15em] text-xs">{regimeLabel(data.risk_regime)}</span>
          </Pill>
          <Pill label="DXY" tone={toneForDirection(data.dxy)} index={1}>
            <DirectionArrow d={data.dxy} />
          </Pill>
          <Pill label="SPX" tone={toneForDirection(data.spx)} index={2}>
            <DirectionArrow d={data.spx} />
          </Pill>
          <Pill label="VIX" tone={toneForVix(data.vix_level)} index={3}>
            <span className="text-xs uppercase tracking-wider opacity-70">{data.vix_level}</span>
            <span className="tabular-nums">{data.vix_value.toFixed(1)}</span>
          </Pill>
          <Pill label="US10Y" tone={toneForDirection(data.us10y)} index={4}>
            <DirectionArrow d={data.us10y} />
          </Pill>
          <Pill label="Gold" tone={toneForDirection(data.gold)} index={5}>
            <DirectionArrow d={data.gold} />
          </Pill>
          <Pill label="Oil" tone={toneForDirection(data.oil)} index={6}>
            <DirectionArrow d={data.oil} />
          </Pill>
          <Pill label="Nikkei" tone={toneForDirection(data.nikkei)} index={7}>
            <DirectionArrow d={data.nikkei} />
          </Pill>
        </div>
      </GlassCard>
    </motion.div>
  );
}
