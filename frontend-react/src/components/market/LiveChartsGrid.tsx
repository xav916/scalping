import clsx from 'clsx';
import { motion } from 'motion/react';
import { GlassCard } from '@/components/ui/GlassCard';
import { Sparkline } from '@/components/ui/Sparkline';
import { Skeleton } from '@/components/ui/Skeleton';
import { Tooltip, LabelWithInfo } from '@/components/ui/Tooltip';
import { useAllCandles } from '@/hooks/useCandles';
import { formatPrice } from '@/lib/format';

/** Paires principales affichées dans la grille live (ordre = visibilité).
 *  Limité à 8 pour ne pas surcharger le dashboard mobile. */
const MAIN_PAIRS = [
  'EUR/USD',
  'GBP/USD',
  'USD/JPY',
  'XAU/USD',
  'BTC/USD',
  'ETH/USD',
  'SPX',
  'NDX',
];

/** Grille de 8 mini-sparklines montrant les paires principales en temps réel.
 *  "Heartbeat" du marché — un coup d'œil pour sentir la vitalité globale,
 *  indépendamment des setups en cours. */
export function LiveChartsGrid() {
  const { data: allCandles, isLoading } = useAllCandles();

  if (isLoading) {
    return (
      <GlassCard className="p-5">
        <Skeleton className="h-40" />
      </GlassCard>
    );
  }

  return (
    <GlassCard className="p-5">
      <div className="flex items-center justify-between mb-4">
        <LabelWithInfo
          label={<h2 className="text-sm font-semibold tracking-tight uppercase tracking-[0.2em] text-white/70">Prix live</h2>}
          tip="Prix des paires principales en temps réel. Sparkline = 30 dernières bougies 5 minutes. Variation = delta entre la première et la dernière close sur la fenêtre. Utile comme heartbeat du marché, indépendamment des setups actifs."
        />
        <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">
          5m · 30 bougies
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {MAIN_PAIRS.map((pair, i) => (
          <LiveChartTile
            key={pair}
            pair={pair}
            candles={allCandles?.[pair]}
            index={i}
          />
        ))}
      </div>
    </GlassCard>
  );
}

function LiveChartTile({
  pair,
  candles,
  index,
}: {
  pair: string;
  candles: Array<{ open: number; high: number; low: number; close: number }> | undefined;
  index: number;
}) {
  if (!candles || candles.length < 2) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: index * 0.04 }}
        className="rounded-lg border border-glass-soft bg-white/[0.02] p-3 min-h-[96px]"
      >
        <div className="font-mono text-sm font-semibold truncate">{pair}</div>
        <div className="text-[10px] text-white/40 mt-2">Pas de données</div>
      </motion.div>
    );
  }
  const closes = candles.slice(-30).map((c) => c.close);
  const first = closes[0];
  const last = closes[closes.length - 1];
  const delta = last - first;
  const deltaPct = first > 0 ? (delta / first) * 100 : 0;
  const variant: 'buy' | 'sell' | 'neutral' =
    delta > 0 ? 'buy' : delta < 0 ? 'sell' : 'neutral';
  const tone =
    delta > 0 ? 'text-emerald-300' : delta < 0 ? 'text-rose-300' : 'text-white/70';

  return (
    <Tooltip content={
      <>
        <div><span className="font-mono font-semibold">{pair}</span> · last {formatPrice(last)}</div>
        <div className="text-white/60 mt-1">
          {delta >= 0 ? '+' : ''}{deltaPct.toFixed(2)}% sur les 30 dernières bougies 5m
        </div>
      </>
    }>
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: index * 0.04 }}
        className="rounded-lg border border-glass-soft bg-white/[0.02] p-3 hover:bg-white/[0.04] transition-colors w-full"
      >
        <div className="flex items-baseline justify-between mb-2 gap-2">
          <span className="font-mono text-xs font-semibold truncate">{pair}</span>
          <span className={clsx('font-mono text-[10px] tabular-nums', tone)}>
            {delta >= 0 ? '+' : ''}{deltaPct.toFixed(2)}%
          </span>
        </div>
        <Sparkline values={closes} width={260} height={36} variant={variant} />
        <div className="mt-1 text-[10px] font-mono tabular-nums text-white/50">
          {formatPrice(last)}
        </div>
      </motion.div>
    </Tooltip>
  );
}
