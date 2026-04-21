import clsx from 'clsx';
import { motion } from 'motion/react';
import { GlassCard } from '@/components/ui/GlassCard';
import { Tooltip, LabelWithInfo } from '@/components/ui/Tooltip';
import { formatPnl } from '@/lib/format';
import { TIPS } from '@/lib/metricTips';
import type { ActiveTrade } from '@/types/domain';

/** Capital en jeu : total à risque, notionnel, + top 5 positions par risque. */
export function CapitalAtRiskCard({
  trades,
  capital,
}: {
  trades: ActiveTrade[];
  capital: number;
}) {
  const totalRisk = trades.reduce((sum, t) => sum + (t.risk_money ?? 0), 0);
  const totalNotional = trades.reduce((sum, t) => sum + (t.notional ?? 0), 0);
  const riskPct = capital > 0 ? (totalRisk / capital) * 100 : 0;
  const maxRiskPerTrade = trades.length ? Math.max(...trades.map((t) => t.risk_money ?? 0)) : 0;
  const byPair = [...trades]
    .filter((t) => (t.risk_money ?? 0) > 0)
    .sort((a, b) => (b.risk_money ?? 0) - (a.risk_money ?? 0))
    .slice(0, 5);

  return (
    <GlassCard variant="elevated" className="p-5 h-full">
      <div className="flex items-center justify-between mb-3">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Capital en jeu</h3>}
          tip={TIPS.capital.titre}
        />
        <Tooltip content={TIPS.capital.aRisque}>
          <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">
            risque si tous SL touchés
          </span>
        </Tooltip>
      </div>
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div>
          <LabelWithInfo
            label={<span className="text-[9px] uppercase tracking-[0.2em] text-white/40">À risque</span>}
            tip={TIPS.capital.aRisque}
            className="mb-1"
          />
          <div className="text-2xl font-bold font-mono tabular-nums text-rose-300">
            {formatPnl(totalRisk)}
          </div>
          <Tooltip content={TIPS.capital.risquePct}>
            <div className="text-[10px] text-white/40 font-mono mt-0.5">
              {riskPct.toFixed(2)}% capital
            </div>
          </Tooltip>
        </div>
        <div>
          <LabelWithInfo
            label={<span className="text-[9px] uppercase tracking-[0.2em] text-white/40">Notionnel</span>}
            tip={TIPS.capital.notionnel}
            className="mb-1"
          />
          <div className="text-2xl font-bold font-mono tabular-nums text-white/80">
            {formatPnl(totalNotional)}
          </div>
          <Tooltip content={TIPS.capital.expositionTotale}>
            <div className="text-[10px] text-white/40 font-mono mt-0.5">exposition totale</div>
          </Tooltip>
        </div>
      </div>

      {byPair.length > 0 ? (
        <div className="space-y-2 pt-3 border-t border-glass-soft">
          <LabelWithInfo
            label={<span className="text-[9px] uppercase tracking-[0.2em] text-white/40">Top 5 par risque</span>}
            tip={TIPS.capital.top5}
          />
          {byPair.map((t) => {
            const pct = maxRiskPerTrade > 0 ? ((t.risk_money ?? 0) / maxRiskPerTrade) * 100 : 0;
            const isBuy = t.direction === 'buy';
            return (
              <div key={t.id} className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="font-mono font-semibold truncate">{t.pair}</span>
                    <span
                      className={clsx(
                        'text-[9px] font-semibold uppercase tracking-widest px-1 rounded',
                        isBuy ? 'bg-cyan-400/10 text-cyan-300' : 'bg-pink-400/10 text-pink-300'
                      )}
                    >
                      {t.direction}
                    </span>
                  </div>
                  <span className="font-mono tabular-nums text-rose-300/90">
                    {formatPnl(t.risk_money ?? 0)}
                  </span>
                </div>
                <div className="w-full h-1 rounded-full bg-white/5 overflow-hidden">
                  <motion.div
                    className="h-full rounded-full bg-gradient-to-r from-rose-400/40 to-pink-400/40"
                    initial={{ width: 0 }}
                    animate={{ width: `${pct}%` }}
                    transition={{ duration: 0.5, ease: 'easeOut' }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="text-xs text-white/40 pt-3 border-t border-glass-soft">Aucun trade ouvert.</p>
      )}
    </GlassCard>
  );
}
