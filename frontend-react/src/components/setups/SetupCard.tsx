import clsx from 'clsx';
import { motion } from 'motion/react';
import type { TradeSetup } from '@/types/domain';
import { GlassCard } from '@/components/ui/GlassCard';
import { GradientText } from '@/components/ui/GradientText';
import { formatPrice } from '@/lib/format';

interface Props {
  setup: TradeSetup;
}

export function SetupCard({ setup }: Props) {
  const isBuy = setup.direction === 'buy';
  const accentBorder = isBuy ? 'before:bg-neon-buy' : 'before:bg-neon-sell';

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 20, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.96, transition: { duration: 0.2 } }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
    >
      <GlassCard
        variant="elevated"
        className={clsx(
          'relative p-5 overflow-hidden',
          'before:absolute before:inset-y-0 before:left-0 before:w-0.5',
          accentBorder
        )}
      >
        <div className="flex items-start justify-between mb-3">
          <div>
            <div className="text-lg font-mono font-bold tracking-tight">{setup.pair}</div>
            <div className={clsx('text-xs font-semibold uppercase tracking-wider', isBuy ? 'text-neon-buy' : 'text-neon-sell')}>
              {setup.direction}
            </div>
          </div>
          <GradientText variant={isBuy ? 'buy' : 'sell'} className="text-3xl leading-none">
            {setup.confidence_score.toFixed(0)}
          </GradientText>
        </div>
        <dl className="grid grid-cols-3 gap-2 text-xs">
          <div>
            <dt className="text-white/40 uppercase tracking-wider">Entry</dt>
            <dd className="font-mono tabular-nums text-white/90 mt-0.5">{formatPrice(setup.entry_price)}</dd>
          </div>
          <div>
            <dt className="text-white/40 uppercase tracking-wider">SL</dt>
            <dd className="font-mono tabular-nums text-rose-300 mt-0.5">{formatPrice(setup.stop_loss)}</dd>
          </div>
          <div>
            <dt className="text-white/40 uppercase tracking-wider">TP1</dt>
            <dd className="font-mono tabular-nums text-emerald-300 mt-0.5">{formatPrice(setup.take_profit_1)}</dd>
          </div>
        </dl>
        {setup.verdict_summary && (
          <p className="mt-3 text-xs text-white/60 line-clamp-2">{setup.verdict_summary}</p>
        )}
      </GlassCard>
    </motion.div>
  );
}
