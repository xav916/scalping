import { useQuery } from '@tanstack/react-query';
import { motion } from 'motion/react';
import clsx from 'clsx';
import { Link } from 'react-router-dom';
import { api, ApiError } from '@/lib/api';
import { GlassCard } from '@/components/ui/GlassCard';
import { Skeleton } from '@/components/ui/Skeleton';
import { LabelWithInfo } from '@/components/ui/Tooltip';
import type { ShadowSetup, ShadowSystemSummary } from '@/types/domain';

const SYSTEM_LABELS: Record<string, string> = {
  V2_CORE_LONG_XAUUSD_4H: 'XAU H4',
  V2_CORE_LONG_XAGUSD_4H: 'XAG H4',
  V2_WTI_OPTIMAL_WTIUSD_4H: 'WTI H4',
  V2_CORE_LONG_ETHUSD_1D: 'ETH 1D',
  V2_TIGHT_LONG_XLI_1D: 'XLI 1D',
  V2_WTI_OPTIMAL_XLK_1D: 'XLK 1D',
};

function formatPnl(eur: number): string {
  const sign = eur >= 0 ? '+' : '';
  if (Math.abs(eur) >= 1000) return `${sign}${(eur / 1000).toFixed(1)}k€`;
  return `${sign}${eur.toFixed(0)}€`;
}

function formatAge(ts: string): string {
  const diffMs = Date.now() - new Date(ts).getTime();
  const hours = diffMs / 3600_000;
  if (hours < 1) return `${Math.round(diffMs / 60_000)}m`;
  if (hours < 24) return `${Math.round(hours)}h`;
  return `${Math.round(hours / 24)}j`;
}

function outcomePill(outcome: ShadowSetup['outcome']): { label: string; cls: string } {
  if (outcome === 'TP1') return { label: 'TP', cls: 'bg-emerald-400/15 text-emerald-300 border-emerald-400/30' };
  if (outcome === 'SL') return { label: 'SL', cls: 'bg-rose-400/15 text-rose-300 border-rose-400/30' };
  if (outcome === 'TIMEOUT') return { label: 'TIMEOUT', cls: 'bg-amber-400/15 text-amber-300 border-amber-400/30' };
  return { label: 'PENDING', cls: 'bg-white/5 text-white/40 border-white/10' };
}

function SystemRow({ s }: { s: ShadowSystemSummary }) {
  const label = SYSTEM_LABELS[s.system_id] ?? s.system_id;
  const recon = s.n_total - s.n_pending;
  const pfText = s.pf !== null ? s.pf.toFixed(2) : '—';
  const wrText = s.wr_pct !== null ? `${Math.round(s.wr_pct)}%` : '—';
  const pnlText = s.net_pnl_eur !== null ? formatPnl(s.net_pnl_eur) : '—';
  const pnlCls = s.net_pnl_eur === null
    ? 'text-white/40'
    : s.net_pnl_eur > 0
      ? 'text-emerald-300'
      : s.net_pnl_eur < 0
        ? 'text-rose-300'
        : 'text-white/40';

  return (
    <div className="flex items-center gap-2 py-1.5 border-b border-white/5 last:border-b-0">
      <span className="w-16 text-[11px] font-mono text-white/80 shrink-0">{label}</span>
      <span className="text-[10px] text-white/40 tabular-nums shrink-0 w-16" title="loggés / réconciliés">
        {s.n_total}/{recon}
      </span>
      <span className="text-[10px] font-mono text-white/60 tabular-nums shrink-0 w-12" title="profit factor">
        PF {pfText}
      </span>
      <span className="text-[10px] font-mono text-white/60 tabular-nums shrink-0 w-12" title="win rate">
        {wrText}
      </span>
      <span className={clsx('text-[10px] font-mono tabular-nums ml-auto shrink-0', pnlCls)}>
        {pnlText}
      </span>
    </div>
  );
}

function SetupRow({ s }: { s: ShadowSetup }) {
  const { label: outcomeLabel, cls: outcomeCls } = outcomePill(s.outcome);
  const sysLabel = SYSTEM_LABELS[s.system_id] ?? s.pair;
  const dirCls = s.direction === 'buy' ? 'text-emerald-300' : 'text-rose-300';
  return (
    <div className="flex items-center gap-2 py-1 text-[10px]">
      <span className="font-mono text-white/70 shrink-0 w-14">{sysLabel}</span>
      <span className={clsx('uppercase font-bold tracking-wider shrink-0 w-8', dirCls)}>
        {s.direction}
      </span>
      <span
        className={clsx(
          'uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded border text-[9px] shrink-0',
          outcomeCls,
        )}
      >
        {outcomeLabel}
      </span>
      <span className="text-white/30 tabular-nums shrink-0">{formatAge(s.bar_timestamp)}</span>
      {s.pnl_eur !== null && (
        <span
          className={clsx(
            'font-mono tabular-nums ml-auto shrink-0',
            s.pnl_eur > 0 ? 'text-emerald-300' : 'text-rose-300',
          )}
        >
          {formatPnl(s.pnl_eur)}
        </span>
      )}
    </div>
  );
}

/**
 * Card Cockpit "Track A — Shadow log live".
 *
 * Vue compacte des 6 systèmes Phase 4 (XAU/XAG H4, WTI H4, ETH 1D, XLI 1D,
 * XLK 1D) avec n_total/recon, PF, WR, net PnL. Plus 5 derniers setups
 * détectés. Lien vers `/v2/shadow-log` pour le détail.
 *
 * Refresh 60s.
 */
export function TrackAShadowCard() {
  const summaryQ = useQuery({
    queryKey: ['shadow', 'summary'],
    queryFn: api.shadowSummary,
    retry: 0,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
  const setupsQ = useQuery({
    queryKey: ['shadow', 'setups', 'recent'],
    queryFn: () => api.shadowSetups({ limit: 5 }),
    retry: 0,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  if (summaryQ.isLoading || setupsQ.isLoading) {
    return <Skeleton className="w-full h-48" />;
  }

  const apiError = summaryQ.error ?? setupsQ.error;
  if (apiError) {
    const msg = apiError instanceof ApiError ? apiError.message : 'Indisponible';
    return (
      <GlassCard className="p-5">
        <h3 className="text-sm font-semibold text-rose-300 mb-1">Track A shadow</h3>
        <p className="text-xs text-white/60">{msg}</p>
      </GlassCard>
    );
  }

  const summary = summaryQ.data;
  const setups = setupsQ.data ?? [];

  // Trier les systèmes dans l'ordre du portefeuille (XAU en premier, puis dans l'ordre déclaré).
  const order = Object.keys(SYSTEM_LABELS);
  const systems = (summary?.systems ?? []).slice().sort(
    (a, b) => order.indexOf(a.system_id) - order.indexOf(b.system_id),
  );

  const totalSetups = systems.reduce((acc, s) => acc + s.n_total, 0);
  const totalRecon = systems.reduce((acc, s) => acc + (s.n_total - s.n_pending), 0);
  const totalPnl = systems.reduce(
    (acc, s) => acc + (s.net_pnl_eur ?? 0),
    0,
  );

  return (
    <GlassCard className="p-5">
      <div className="flex items-start justify-between mb-3 gap-3">
        <LabelWithInfo
          label={
            <h3 className="text-sm font-semibold tracking-tight">
              Track A — Shadow log live
            </h3>
          }
          tip="Phase 4 : observation live des 6 systèmes du portefeuille recherche (V2_CORE_LONG XAU/XAG H4, V2_WTI_OPTIMAL WTI H4 + XLK 1D, V2_CORE_LONG ETH 1D, V2_TIGHT_LONG XLI 1D). Lecture seule, pas branché au scoring V1. Gate de décision : 2026-06-06."
        />
        <Link
          to="/v2/shadow-log"
          className="text-[10px] uppercase tracking-wider text-cyan-400 hover:text-cyan-300 shrink-0 mt-0.5"
        >
          détail →
        </Link>
      </div>

      {/* Totaux */}
      <div className="flex items-center gap-3 mb-3 text-[10px] uppercase tracking-wider text-white/40">
        <span>
          <span className="text-white/70 font-mono tabular-nums">{totalSetups}</span> setups
        </span>
        <span>·</span>
        <span>
          <span className="text-white/70 font-mono tabular-nums">{totalRecon}</span> recon
        </span>
        <span>·</span>
        <span
          className={clsx(
            'font-mono tabular-nums',
            totalPnl > 0 ? 'text-emerald-300' : totalPnl < 0 ? 'text-rose-300' : 'text-white/40',
          )}
        >
          {formatPnl(totalPnl)}
        </span>
      </div>

      {/* Systèmes */}
      {systems.length > 0 ? (
        <motion.div
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          className="mb-3"
        >
          <div className="text-[9px] uppercase tracking-wider text-white/30 mb-1">Par système</div>
          {systems.map((s) => (
            <SystemRow key={s.system_id} s={s} />
          ))}
        </motion.div>
      ) : (
        <p className="text-[11px] text-white/40 mb-3">Aucun setup loggé.</p>
      )}

      {/* Derniers setups */}
      {setups.length > 0 && (
        <div className="pt-2 border-t border-white/5">
          <div className="text-[9px] uppercase tracking-wider text-white/30 mb-1">
            Derniers setups
          </div>
          {setups.slice(0, 5).map((s) => (
            <SetupRow key={s.id} s={s} />
          ))}
        </div>
      )}
    </GlassCard>
  );
}
