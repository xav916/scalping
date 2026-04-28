import clsx from 'clsx';
import { motion } from 'motion/react';
import { GlassCard } from '@/components/ui/GlassCard';
import { Tooltip, LabelWithInfo } from '@/components/ui/Tooltip';
import { formatPnl, formatPrice } from '@/lib/format';
import { TIPS } from '@/lib/metricTips';
import type { ActiveTrade } from '@/types/domain';

/** Leverage retail Pepperstone par classe — pour estimer la margin
 *  bloquée à partir du notional. Valeurs réglementaires UE/UK 2024-26. */
const LEVERAGE_BY_CLASS: Record<string, number> = {
  forex: 30,
  metal: 20,
  equity_index: 20,
  index: 20,
  energy: 10,
  crypto: 2,
};

function estimateMarginEur(notional: number, assetClass: string): number {
  const lev = LEVERAGE_BY_CLASS[assetClass.toLowerCase()] ?? 30;
  return notional / lev;
}

/** Tableau des trades actifs avec PnL latent, distance SL, exposition,
 *  margin bloquée + risk money. Responsive : stack 2-col en mobile,
 *  grid 8-col en sm+. */
export function ActiveTradesPanel({
  trades,
  capital,
}: {
  trades: ActiveTrade[];
  capital?: number;
}) {
  if (trades.length === 0) {
    return (
      <GlassCard className="p-6 text-sm text-white/50 text-center">
        Aucun trade ouvert en ce moment.
      </GlassCard>
    );
  }
  return (
    <GlassCard variant="elevated" className="p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold tracking-tight">Trades actifs</h3>
        <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">
          {trades.length} ouvert{trades.length > 1 ? 's' : ''}
        </span>
      </div>
      {/* Légende colonnes — uniquement desktop */}
      <div className="hidden sm:grid grid-cols-[100px_56px_1fr_90px_90px_70px_70px_80px] items-center gap-3 pb-2 mb-2 px-3 text-[9px] uppercase tracking-[0.2em] text-white/30 font-mono">
        <LabelWithInfo label="Paire" tip={TIPS.trade.pair} />
        <LabelWithInfo label="Sens" tip={TIPS.trade.direction} />
        <LabelWithInfo
          label="Entry → Now"
          tip={`${TIPS.trade.entryPrice} · ${TIPS.trade.currentPrice}`}
        />
        <span className="text-right">
          <LabelWithInfo label="Exposition" tip={TIPS.trade.notional} />
        </span>
        <span className="text-right">
          <LabelWithInfo label="Bloqué" tip={TIPS.trade.margin} />
        </span>
        <span className="text-right">
          <LabelWithInfo label="Dist. SL" tip={TIPS.trade.distanceSl} />
        </span>
        <span className="text-right">
          <LabelWithInfo label="Risque" tip={TIPS.trade.riskMoney} />
        </span>
        <span className="text-right">
          <LabelWithInfo label="PnL latent" tip={TIPS.trade.pnlUnrealized} />
        </span>
      </div>
      <div className="space-y-2">
        {trades.map((t) => (
          <ActiveTradeRow key={t.id} trade={t} capital={capital} />
        ))}
      </div>
    </GlassCard>
  );
}

function ActiveTradeRow({
  trade,
  capital,
}: {
  trade: ActiveTrade;
  capital?: number;
}) {
  const isBuy = trade.direction === 'buy';
  const pnl = trade.pnl_unrealized ?? 0;
  const pnlTone = pnl > 0 ? 'text-emerald-300' : pnl < 0 ? 'text-rose-300' : 'text-white/70';
  const marginEur =
    trade.notional !== null && trade.notional !== undefined
      ? estimateMarginEur(trade.notional, trade.asset_class)
      : null;
  const marginPct =
    marginEur !== null && capital && capital > 0 ? (marginEur / capital) * 100 : null;
  return (
    <motion.div
      layout
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className={clsx(
        'rounded-lg border p-3 transition-colors',
        trade.near_sl ? 'border-rose-400/30 bg-rose-400/5' : 'border-glass-soft bg-white/[0.02]'
      )}
    >
      <div className="grid grid-cols-2 sm:grid-cols-[100px_56px_1fr_90px_90px_70px_70px_80px] items-center gap-2 sm:gap-3">
        <div className="flex items-center gap-2 min-w-0 col-span-2 sm:col-span-1">
          <Tooltip content={TIPS.trade.pair}>
            <span className="font-mono text-sm font-semibold truncate">{trade.pair}</span>
          </Tooltip>
          <Tooltip content={TIPS.trade.assetClass}>
            <span className="text-[9px] text-white/30 font-mono hidden sm:inline">
              {trade.asset_class}
            </span>
          </Tooltip>
        </div>
        <Tooltip content={TIPS.trade.direction}>
          <span
            className={clsx(
              'text-[9px] font-semibold uppercase tracking-widest px-1.5 py-0.5 rounded text-center w-fit',
              isBuy ? 'bg-cyan-400/10 text-cyan-300' : 'bg-pink-400/10 text-pink-300'
            )}
          >
            {trade.direction}
          </span>
        </Tooltip>
        <Tooltip content={`${TIPS.trade.entryPrice} · ${TIPS.trade.currentPrice}`}>
          <div className="text-xs text-white/60 font-mono tabular-nums truncate">
            {formatPrice(trade.entry_price)}
            {trade.current_price !== null && (
              <>
                <span className="mx-1 opacity-40">→</span>
                <span className="text-white/80">{formatPrice(trade.current_price)}</span>
              </>
            )}
          </div>
        </Tooltip>
        <Tooltip content={TIPS.trade.notional}>
          <div className="text-xs font-mono tabular-nums text-right text-white/70">
            {trade.notional !== null && trade.notional !== undefined
              ? `${trade.notional.toLocaleString('fr-FR', { maximumFractionDigits: 0 })} €`
              : '—'}
          </div>
        </Tooltip>
        <Tooltip content={TIPS.trade.margin}>
          <div className="text-xs font-mono tabular-nums text-right text-cyan-300/80">
            {marginEur !== null
              ? `${marginEur.toLocaleString('fr-FR', { maximumFractionDigits: 0 })} €${
                  marginPct !== null ? ` (${marginPct.toFixed(2)}%)` : ''
                }`
              : '—'}
          </div>
        </Tooltip>
        <Tooltip content={trade.near_sl ? TIPS.trade.nearSl : TIPS.trade.distanceSl}>
          <div className="text-xs font-mono tabular-nums text-right text-white/50">
            {trade.distance_to_sl_pct !== null ? `SL ${trade.distance_to_sl_pct}%` : '—'}
          </div>
        </Tooltip>
        <Tooltip content={TIPS.trade.riskMoney}>
          <div className="text-xs font-mono tabular-nums text-right text-rose-300/80">
            {trade.risk_money !== null
              ? `-${formatPnl(trade.risk_money).replace('-', '')}`
              : '—'}
          </div>
        </Tooltip>
        <Tooltip
          content={`${TIPS.trade.pnlUnrealized}${
            trade.pnl_pips !== null ? ` · ${trade.pnl_pips} pips` : ''
          }`}
        >
          <div
            className={clsx(
              'text-sm font-mono font-semibold tabular-nums text-right',
              pnlTone
            )}
          >
            {trade.pnl_unrealized !== null ? formatPnl(trade.pnl_unrealized) : '—'}
          </div>
        </Tooltip>
      </div>
    </motion.div>
  );
}
