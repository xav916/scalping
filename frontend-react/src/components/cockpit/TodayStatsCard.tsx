import clsx from 'clsx';
import { GlassCard } from '@/components/ui/GlassCard';
import { GradientText } from '@/components/ui/GradientText';
import { Tooltip, LabelWithInfo } from '@/components/ui/Tooltip';
import { formatPct, formatPnl } from '@/lib/format';
import { TIPS } from '@/lib/metricTips';

/** Stats condensées du jour : PnL réalisé, non réalisé, trades, ouverts. */
export function TodayStatsCard({
  pnl,
  pnlPct,
  nTrades,
  nOpen,
  nClosed,
  capital,
  unrealizedPnl,
}: {
  pnl: number;
  pnlPct: number;
  nTrades: number;
  nOpen: number;
  nClosed: number;
  capital: number;
  unrealizedPnl: number;
}) {
  const pnlTone = pnl > 0 ? 'text-emerald-300' : pnl < 0 ? 'text-rose-300' : 'text-white/80';
  const unrealTone =
    unrealizedPnl > 0 ? 'text-emerald-300' : unrealizedPnl < 0 ? 'text-rose-300' : 'text-white/60';

  return (
    <GlassCard variant="elevated" className="p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold tracking-tight">Aujourd'hui</h3>
        <Tooltip content={TIPS.today.capital}>
          <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">
            capital {formatPnl(capital)}
          </span>
        </Tooltip>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Kpi
          label="PnL jour"
          tip={TIPS.today.pnlJour}
          value={<span className={clsx('font-mono', pnlTone)}>{formatPnl(pnl)}</span>}
          sub={formatPct(pnlPct / 100)}
          subTip={TIPS.today.pnlPct}
        />
        <Kpi
          label="Non réalisé"
          tip={TIPS.today.nonRealise}
          value={<span className={clsx('font-mono', unrealTone)}>{formatPnl(unrealizedPnl)}</span>}
          sub="trades ouverts"
        />
        <Kpi
          label="Trades"
          tip={TIPS.today.trades}
          value={<GradientText>{String(nTrades)}</GradientText>}
          sub={`${nClosed} clôturés`}
          subTip={TIPS.today.closurés}
        />
        <Kpi
          label="Ouverts"
          tip={TIPS.today.ouverts}
          value={<span className="font-mono">{String(nOpen)}</span>}
          sub="en cours"
        />
      </div>
    </GlassCard>
  );
}

function Kpi({
  label,
  value,
  sub,
  tip,
  subTip,
}: {
  label: string;
  value: React.ReactNode;
  sub?: string;
  tip?: React.ReactNode;
  subTip?: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-1">
        {tip ? (
          <LabelWithInfo
            label={<span className="text-[9px] uppercase tracking-[0.2em] text-white/40">{label}</span>}
            tip={tip}
          />
        ) : (
          <span className="text-[9px] uppercase tracking-[0.2em] text-white/40">{label}</span>
        )}
      </div>
      <div className="text-xl font-bold leading-tight">{value}</div>
      {sub && (
        <div className="text-[10px] text-white/40 mt-1 font-mono">
          {subTip ? (
            <Tooltip content={subTip}>
              <span>{sub}</span>
            </Tooltip>
          ) : (
            sub
          )}
        </div>
      )}
    </div>
  );
}
