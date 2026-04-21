import clsx from 'clsx';
import { motion } from 'motion/react';
import type { TradeSetup } from '@/types/domain';
import { GlassCard } from '@/components/ui/GlassCard';
import { ConfidenceGauge } from '@/components/ui/ConfidenceGauge';
import { Sparkline } from '@/components/ui/Sparkline';
import { TiltWrapper } from '@/components/ui/TiltWrapper';
import { Tooltip } from '@/components/ui/Tooltip';
import { useAllCandles } from '@/hooks/useCandles';
import { formatPrice } from '@/lib/format';
import { TIPS } from '@/lib/metricTips';

interface Props {
  setup: TradeSetup;
  onClick?: () => void;
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

export function SetupCard({ setup, onClick }: Props) {
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
    >
      <TiltWrapper maxTilt={5}>
      <GlassCard
        variant="elevated"
        onClick={onClick}
        className={clsx(
          'relative p-5 overflow-hidden group transition-shadow duration-300',
          onClick && 'cursor-pointer',
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
            <Tooltip content={TIPS.trade.pair}>
              <div className="text-xl font-mono font-bold tracking-tight truncate cursor-help">{setup.pair}</div>
            </Tooltip>
            <div className="flex items-center gap-2 mt-1">
              <Tooltip content={TIPS.trade.direction}>
                <span
                  className={clsx(
                    'text-[10px] font-semibold uppercase tracking-widest px-2 py-0.5 rounded-md cursor-help',
                    isBuy ? 'bg-cyan-400/10 text-cyan-300 border border-cyan-400/20' : 'bg-pink-400/10 text-pink-300 border border-pink-400/20'
                  )}
                >
                  {setup.direction}
                </span>
              </Tooltip>
              {rr && (
                <Tooltip content={TIPS.setup.rr}>
                  <span className="text-[10px] text-white/40 font-mono uppercase tracking-wider cursor-help">
                    R:R {rr}
                  </span>
                </Tooltip>
              )}
            </div>
          </div>
          <Tooltip content={TIPS.setup.confidenceGauge}>
            <div className="cursor-help">
              <ConfidenceGauge score={setup.confidence_score} variant={isBuy ? 'buy' : 'sell'} size={56} />
            </div>
          </Tooltip>
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
            <PriceBox label="SL" value={formatPrice(setup.stop_loss)} tone="rose" tip={TIPS.trade.stopLoss} />
            <PriceBox label="Entry" value={formatPrice(setup.entry_price)} tone="neutral" highlight tip={TIPS.trade.entryPrice} />
            <PriceBox label="TP1" value={formatPrice(setup.take_profit_1)} tone="emerald" tip={TIPS.trade.takeProfit} />
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
            <Tooltip content={
              setup.verdict_action === 'TAKE' ? TIPS.setup.verdictTake
              : setup.verdict_action === 'WAIT' ? TIPS.setup.verdictWait
              : TIPS.setup.verdictSkip
            }>
              <span
                className={clsx(
                  'text-[9px] font-bold uppercase tracking-[0.2em] px-2 py-1 rounded border cursor-help',
                  setup.verdict_action === 'TAKE' && 'bg-emerald-400/10 text-emerald-300 border-emerald-400/30',
                  setup.verdict_action === 'WAIT' && 'bg-amber-400/10 text-amber-300 border-amber-400/30',
                  setup.verdict_action === 'SKIP' && 'bg-white/5 text-white/40 border-glass-soft'
                )}
              >
                {setup.verdict_action}
              </span>
            </Tooltip>
          </div>
        )}
      </GlassCard>
      </TiltWrapper>
    </motion.div>
  );
}

function PriceBox({
  label,
  value,
  tone,
  highlight = false,
  tip,
}: {
  label: string;
  value: string;
  tone: 'rose' | 'emerald' | 'neutral';
  highlight?: boolean;
  tip?: React.ReactNode;
}) {
  const toneCls =
    tone === 'rose' ? 'text-rose-300' : tone === 'emerald' ? 'text-emerald-300' : 'text-white/90';
  const content = (
    <div
      className={clsx(
        'rounded-lg p-2 text-center transition-colors',
        highlight
          ? 'bg-white/[0.04] border border-glass-soft'
          : 'bg-transparent',
        tip && 'cursor-help'
      )}
    >
      <div className="text-[9px] uppercase tracking-wider text-white/40 mb-1">{label}</div>
      <div className={clsx('font-mono text-sm font-semibold tabular-nums', toneCls)}>{value}</div>
    </div>
  );
  return tip ? <Tooltip content={tip}>{content}</Tooltip> : content;
}
