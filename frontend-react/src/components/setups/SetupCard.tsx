import clsx from 'clsx';
import { motion } from 'motion/react';
import type { TradeSetup } from '@/types/domain';
import { GlassCard } from '@/components/ui/GlassCard';
import { ConfidenceGauge } from '@/components/ui/ConfidenceGauge';
import { Sparkline } from '@/components/ui/Sparkline';
import { useAllCandles } from '@/hooks/useCandles';
import { formatPrice } from '@/lib/format';

interface Props {
  setup: TradeSetup;
}

/** Calcule le ratio R:R affichable à partir du setup. */
function rrRatio(s: TradeSetup): string | null {
  if (s.risk_reward_1 !== undefined && Number.isFinite(s.risk_reward_1)) {
    return `1:${s.risk_reward_1.toFixed(1)}`;
  }
  const risk = Math.abs(s.entry_price - s.stop_loss);
  const reward = Math.abs(s.take_profit_1 - s.entry_price);
  if (risk <= 0) return null;
  return `1:${(reward / risk).toFixed(1)}`;
}

export function SetupCard({ setup }: Props) {
  const isBuy = setup.direction === 'buy';
  const rr = rrRatio(setup);
  const { data: allCandles } = useAllCandles();
  const pairCandles = allCandles?.[setup.pair];
  const closes = pairCandles ? pairCandles.slice(-30).map((c) => c.close) : [];

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 20, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.96, transition: { duration: 0.2 } }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
      whileHover={{ y: -2, transition: { duration: 0.2 } }}
    >
      <GlassCard
        variant="elevated"
        className={clsx(
          'relative p-5 overflow-hidden group transition-shadow duration-300',
          isBuy ? 'hover:shadow-[0_8px_40px_rgba(34,211,238,0.25)]' : 'hover:shadow-[0_8px_40px_rgba(236,72,153,0.25)]',
          'before:absolute before:inset-y-0 before:left-0 before:w-0.5',
          isBuy ? 'before:bg-neon-buy' : 'before:bg-neon-sell'
        )}
      >
        {/* Glow gradient en arrière-plan au hover */}
        <div
          aria-hidden
          className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none"
          style={{
            background: isBuy
              ? 'radial-gradient(ellipse 300px 150px at 0% 50%, rgba(34,211,238,0.08), transparent 70%)'
              : 'radial-gradient(ellipse 300px 150px at 0% 50%, rgba(236,72,153,0.08), transparent 70%)',
          }}
        />

        <div className="relative flex items-start justify-between mb-4 gap-4">
          <div className="min-w-0 flex-1">
            <div className="text-xl font-mono font-bold tracking-tight truncate">{setup.pair}</div>
            <div className="flex items-center gap-2 mt-1">
              <span
                className={clsx(
                  'text-[10px] font-semibold uppercase tracking-widest px-2 py-0.5 rounded-md',
                  isBuy ? 'bg-cyan-400/10 text-cyan-300 border border-cyan-400/20' : 'bg-pink-400/10 text-pink-300 border border-pink-400/20'
                )}
              >
                {setup.direction}
              </span>
              {rr && (
                <span className="text-[10px] text-white/40 font-mono uppercase tracking-wider">
                  R:R {rr}
                </span>
              )}
            </div>
          </div>
          <ConfidenceGauge score={setup.confidence_score} variant={isBuy ? 'buy' : 'sell'} size={56} />
        </div>

        {/* Sparkline sur les 30 dernières candles 5min, overlay SL/Entry/TP */}
        {closes.length >= 2 && (
          <div className="relative mt-3 px-1 -mx-1 rounded-md overflow-hidden">
            <Sparkline
              values={closes}
              width={260}
              height={44}
              variant={isBuy ? 'buy' : 'sell'}
              showEntry={setup.entry_price}
              showSL={setup.stop_loss}
              showTP={setup.take_profit_1}
            />
          </div>
        )}

        {/* Prix : entry centré, SL/TP flanquant */}
        <div className="relative mt-4">
          <div className="grid grid-cols-3 gap-2">
            <PriceBox label="SL" value={formatPrice(setup.stop_loss)} tone="rose" />
            <PriceBox label="Entry" value={formatPrice(setup.entry_price)} tone="neutral" highlight />
            <PriceBox label="TP1" value={formatPrice(setup.take_profit_1)} tone="emerald" />
          </div>
        </div>

        {setup.verdict_summary && (
          <p className="relative mt-4 text-xs text-white/55 line-clamp-2 leading-relaxed">
            {setup.verdict_summary}
          </p>
        )}

        {/* Badge TAKE/WAIT/SKIP si présent */}
        {setup.verdict_action && (
          <div className="relative mt-3 flex items-center gap-2">
            <span
              className={clsx(
                'text-[9px] font-bold uppercase tracking-[0.2em] px-2 py-1 rounded border',
                setup.verdict_action === 'TAKE' && 'bg-emerald-400/10 text-emerald-300 border-emerald-400/30',
                setup.verdict_action === 'WAIT' && 'bg-amber-400/10 text-amber-300 border-amber-400/30',
                setup.verdict_action === 'SKIP' && 'bg-white/5 text-white/40 border-glass-soft'
              )}
            >
              {setup.verdict_action}
            </span>
          </div>
        )}
      </GlassCard>
    </motion.div>
  );
}

function PriceBox({
  label,
  value,
  tone,
  highlight = false,
}: {
  label: string;
  value: string;
  tone: 'rose' | 'emerald' | 'neutral';
  highlight?: boolean;
}) {
  const toneCls =
    tone === 'rose' ? 'text-rose-300' : tone === 'emerald' ? 'text-emerald-300' : 'text-white/90';
  return (
    <div
      className={clsx(
        'rounded-lg p-2 text-center transition-colors',
        highlight
          ? 'bg-white/[0.04] border border-glass-soft'
          : 'bg-transparent'
      )}
    >
      <div className="text-[9px] uppercase tracking-wider text-white/40 mb-1">{label}</div>
      <div className={clsx('font-mono text-sm font-semibold tabular-nums', toneCls)}>{value}</div>
    </div>
  );
}
