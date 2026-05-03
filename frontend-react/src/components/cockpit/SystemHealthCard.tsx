import clsx from 'clsx';
import { GlassCard } from '@/components/ui/GlassCard';
import { LabelWithInfo } from '@/components/ui/Tooltip';
import { StatusDot } from '@/components/cockpit/StatusDot';
import { TIPS } from '@/lib/metricTips';

/** Santé infrastructure : cycle d'analyse, bridge MT5, clients WS, session active. */
export function SystemHealthCard({
  healthy,
  bridgeReachable,
  bridgeConfigured,
  secondsSince,
  wsClients,
  sessionLabel,
  marketsOpen,
}: {
  healthy: boolean;
  bridgeReachable: boolean;
  bridgeConfigured: boolean;
  secondsSince: number | null;
  wsClients: number;
  sessionLabel?: string;
  marketsOpen?: Record<string, boolean>;
}) {
  const marketEntries = marketsOpen ? Object.entries(marketsOpen) : [];

  return (
    <GlassCard className="p-5 h-full">
      <div className="flex items-center justify-between mb-3">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Santé système</h3>}
          tip={TIPS.sante.titre}
        />
        <StatusDot active={!healthy} />
      </div>
      <ul className="space-y-1.5 text-xs text-white/70">
        <li className="flex justify-between">
          <LabelWithInfo label="Cycle d'analyse" tip={TIPS.sante.cycle} />
          <span className={clsx('font-mono', healthy ? 'text-emerald-300' : 'text-rose-300')}>
            {secondsSince !== null ? `${Math.round(secondsSince)}s` : '—'}
          </span>
        </li>
        <li className="flex justify-between">
          <LabelWithInfo label="Bridge MT5" tip={TIPS.sante.bridge} />
          <span
            className={clsx(
              'font-mono',
              bridgeReachable ? 'text-emerald-300' : bridgeConfigured ? 'text-rose-300' : 'text-white/30'
            )}
          >
            {bridgeConfigured ? (bridgeReachable ? 'UP' : 'DOWN') : 'N/A'}
          </span>
        </li>
        <li className="flex justify-between">
          <LabelWithInfo label="Clients WS" tip={TIPS.sante.clientsWs} />
          <span className="font-mono">{wsClients}</span>
        </li>
        {sessionLabel && (
          <li className="flex justify-between">
            <LabelWithInfo label="Session" tip={TIPS.sante.session} />
            <span className="font-mono text-cyan-300">{sessionLabel}</span>
          </li>
        )}
        {marketEntries.length > 0 && (
          <li className="flex justify-between items-center pt-1.5 mt-1 border-t border-white/5">
            <LabelWithInfo label="Marchés stars" tip={TIPS.sante.marches} />
            <span className="flex gap-2 font-mono">
              {marketEntries.map(([pair, isOpen]) => (
                <span
                  key={pair}
                  className={clsx(
                    'inline-flex items-center gap-1',
                    isOpen ? 'text-emerald-300' : 'text-white/40'
                  )}
                  title={isOpen ? `${pair} — marché ouvert` : `${pair} — marché fermé`}
                >
                  <span>{isOpen ? '🟢' : '⚪'}</span>
                  <span>{pair.split('/')[0]}</span>
                </span>
              ))}
            </span>
          </li>
        )}
      </ul>
    </GlassCard>
  );
}
