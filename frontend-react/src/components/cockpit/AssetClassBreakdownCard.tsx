import clsx from 'clsx';
import { motion } from 'motion/react';
import { GlassCard } from '@/components/ui/GlassCard';
import { Tooltip, LabelWithInfo } from '@/components/ui/Tooltip';
import { formatPnl } from '@/lib/format';
import { TIPS } from '@/lib/metricTips';
import type { ActiveTrade, AssetClass } from '@/types/domain';

const ASSET_CLASS_LABELS: Record<AssetClass, string> = {
  forex: 'Forex',
  metal: 'Métaux',
  crypto: 'Crypto',
  equity_index: 'Indices',
  energy: 'Énergie',
  unknown: 'Autre',
};

const ASSET_CLASS_COLORS: Record<AssetClass, string> = {
  forex: 'from-cyan-400 to-cyan-300',
  metal: 'from-amber-400 to-yellow-300',
  crypto: 'from-purple-400 to-pink-400',
  equity_index: 'from-emerald-400 to-cyan-400',
  energy: 'from-orange-400 to-rose-400',
  unknown: 'from-white/30 to-white/50',
};

/** Répartition du risque par classe d'actif (forex/métaux/crypto/indices/énergie). */
export function AssetClassBreakdownCard({ trades }: { trades: ActiveTrade[] }) {
  const grouped = trades.reduce<Record<AssetClass, { risk: number; notional: number; n: number }>>(
    (acc, t) => {
      const cls = t.asset_class ?? 'unknown';
      if (!acc[cls]) acc[cls] = { risk: 0, notional: 0, n: 0 };
      acc[cls].risk += t.risk_money ?? 0;
      acc[cls].notional += t.notional ?? 0;
      acc[cls].n += 1;
      return acc;
    },
    {} as Record<AssetClass, { risk: number; notional: number; n: number }>
  );
  const entries = Object.entries(grouped).sort((a, b) => b[1].risk - a[1].risk);
  const totalRisk = entries.reduce((s, [, v]) => s + v.risk, 0);

  return (
    <GlassCard className="p-5 h-full">
      <div className="flex items-center justify-between mb-4">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Répartition</h3>}
          tip={TIPS.repartition.titre}
        />
        <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">
          par classe d'actif
        </span>
      </div>
      {entries.length === 0 ? (
        <p className="text-xs text-white/40">Aucune exposition.</p>
      ) : (
        <div className="space-y-3">
          {entries.map(([cls, v]) => {
            const ac = cls as AssetClass;
            const pct = totalRisk > 0 ? (v.risk / totalRisk) * 100 : 0;
            const classTip =
              (TIPS.repartition as Record<string, string>)[cls] ?? TIPS.repartition.unknown;
            return (
              <div key={cls} className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <Tooltip content={classTip}>
                    <span className="text-white/80">{ASSET_CLASS_LABELS[ac] ?? cls}</span>
                  </Tooltip>
                  <span className="font-mono tabular-nums text-white/50">
                    {v.n} trade{v.n > 1 ? 's' : ''} · {formatPnl(v.risk)}
                  </span>
                </div>
                <div className="w-full h-1.5 rounded-full bg-white/5 overflow-hidden">
                  <motion.div
                    className={clsx('h-full rounded-full bg-gradient-to-r', ASSET_CLASS_COLORS[ac])}
                    initial={{ width: 0 }}
                    animate={{ width: `${pct}%` }}
                    transition={{ duration: 0.6, ease: 'easeOut' }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </GlassCard>
  );
}
