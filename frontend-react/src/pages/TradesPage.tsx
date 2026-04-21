import { useState, useMemo } from 'react';
import clsx from 'clsx';
import { Link } from 'react-router-dom';
import { motion } from 'motion/react';
import { Header } from '@/components/layout/Header';
import { MeshGradient } from '@/components/ui/MeshGradient';
import { GlassCard } from '@/components/ui/GlassCard';
import { Skeleton } from '@/components/ui/Skeleton';
import { useTrades } from '@/hooks/useTrades';
import { formatPrice, formatPnl } from '@/lib/format';
import type { PersonalTrade } from '@/types/domain';

type StatusFilter = 'all' | 'OPEN' | 'CLOSED';

function formatDuration(from: string, to?: string | null): string {
  if (!to) return '—';
  const d = (new Date(to).getTime() - new Date(from).getTime()) / 1000;
  if (d < 60) return `${Math.round(d)}s`;
  if (d < 3600) return `${Math.round(d / 60)}m`;
  if (d < 86400) return `${(d / 3600).toFixed(1)}h`;
  return `${(d / 86400).toFixed(1)}j`;
}

function formatDate(iso: string): string {
  try {
    return new Intl.DateTimeFormat('fr-FR', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'Europe/Paris',
    }).format(new Date(iso));
  } catch {
    return iso.slice(0, 16);
  }
}

export function TradesPage() {
  const [status, setStatus] = useState<StatusFilter>('all');
  const [autoOnly, setAutoOnly] = useState(true);
  const { data, isLoading } = useTrades({
    status: status === 'all' ? undefined : status,
    limit: 200,
  });

  const trades = useMemo(() => {
    const list = data ?? [];
    return autoOnly ? list.filter((t) => t.is_auto === 1) : list;
  }, [data, autoOnly]);

  const stats = useMemo(() => {
    const closed = trades.filter((t) => t.status === 'CLOSED' && t.pnl !== null && t.pnl !== undefined);
    const wins = closed.filter((t) => (t.pnl ?? 0) > 0).length;
    const total_pnl = closed.reduce((s, t) => s + (t.pnl ?? 0), 0);
    return {
      total: trades.length,
      open: trades.filter((t) => t.status === 'OPEN').length,
      closed: closed.length,
      wins,
      win_rate: closed.length ? wins / closed.length : 0,
      pnl: total_pnl,
    };
  }, [trades]);

  return (
    <>
      <MeshGradient />
      <Header />
      <main className="px-4 sm:px-6 py-6 max-w-[1500px] mx-auto space-y-4">
        {/* Header avec retour + titre */}
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <Link
              to="/"
              className="text-xs text-white/40 hover:text-white/70 transition-colors inline-flex items-center gap-1 mb-1"
            >
              ← Dashboard
            </Link>
            <h1 className="text-2xl font-semibold tracking-tight">Trades</h1>
          </div>
          <div className="flex items-center gap-4 text-xs">
            <KpiInline label="Total" value={stats.total.toString()} />
            <KpiInline label="Open" value={stats.open.toString()} tone="amber" />
            <KpiInline label="Closed" value={stats.closed.toString()} tone="cyan" />
            <KpiInline
              label="Win rate"
              value={`${(stats.win_rate * 100).toFixed(1)}%`}
              tone={stats.win_rate >= 0.5 ? 'emerald' : 'rose'}
            />
            <KpiInline
              label="PnL"
              value={formatPnl(stats.pnl)}
              tone={stats.pnl > 0 ? 'emerald' : stats.pnl < 0 ? 'rose' : 'neutral'}
            />
          </div>
        </div>

        {/* Filtres */}
        <GlassCard className="p-3 flex items-center gap-3 flex-wrap">
          <span className="text-[10px] uppercase tracking-[0.2em] text-white/40 mr-2">Statut</span>
          {(['all', 'OPEN', 'CLOSED'] as StatusFilter[]).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStatus(s)}
              className={clsx(
                'text-xs px-3 py-1 rounded-md border transition-all',
                status === s
                  ? 'border-glass-strong bg-white/10 text-white'
                  : 'border-glass-soft text-white/50 hover:text-white/90'
              )}
            >
              {s === 'all' ? 'Tous' : s === 'OPEN' ? 'Ouverts' : 'Fermés'}
            </button>
          ))}
          <span className="mx-3 text-white/20">|</span>
          <label className="flex items-center gap-2 text-xs text-white/70 cursor-pointer">
            <input
              type="checkbox"
              checked={autoOnly}
              onChange={(e) => setAutoOnly(e.target.checked)}
              className="accent-cyan-400"
            />
            Auto seulement
          </label>
        </GlassCard>

        {/* Tableau */}
        {isLoading ? (
          <Skeleton className="h-96" />
        ) : trades.length === 0 ? (
          <GlassCard className="p-12 text-center text-white/40 text-sm">
            Aucun trade à afficher pour ces filtres.
          </GlassCard>
        ) : (
          <GlassCard variant="elevated" className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-xs min-w-[760px]">
                <thead>
                  <tr className="text-[9px] uppercase tracking-[0.15em] text-white/40 border-b border-glass-soft">
                    <th className="px-3 py-3 text-left">Date</th>
                    <th className="px-3 py-3 text-left">Pair</th>
                    <th className="px-3 py-3 text-left">Dir</th>
                    <th className="px-3 py-3 text-right">Conf.</th>
                    <th className="px-3 py-3 text-right">Entry</th>
                    <th className="px-3 py-3 text-right">Exit</th>
                    <th className="px-3 py-3 text-right">SL</th>
                    <th className="px-3 py-3 text-right">TP</th>
                    <th className="px-3 py-3 text-right">Lot</th>
                    <th className="px-3 py-3 text-right">Durée</th>
                    <th className="px-3 py-3 text-right">PnL</th>
                    <th className="px-3 py-3 text-left">Statut</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.map((t, i) => (
                    <TradeRow key={t.id} t={t} index={i} />
                  ))}
                </tbody>
              </table>
            </div>
          </GlassCard>
        )}
      </main>
    </>
  );
}

function KpiInline({
  label,
  value,
  tone = 'neutral',
}: {
  label: string;
  value: string;
  tone?: 'emerald' | 'rose' | 'amber' | 'cyan' | 'neutral';
}) {
  const toneCls =
    tone === 'emerald'
      ? 'text-emerald-300'
      : tone === 'rose'
      ? 'text-rose-300'
      : tone === 'amber'
      ? 'text-amber-300'
      : tone === 'cyan'
      ? 'text-cyan-300'
      : 'text-white';
  return (
    <div className="flex flex-col items-end">
      <span className="text-[9px] uppercase tracking-[0.15em] text-white/40">{label}</span>
      <span className={clsx('text-sm font-mono font-semibold tabular-nums', toneCls)}>{value}</span>
    </div>
  );
}

function TradeRow({ t, index }: { t: PersonalTrade; index: number }) {
  const isBuy = t.direction === 'buy';
  const pnl = t.pnl;
  const pnlTone =
    pnl === null || pnl === undefined
      ? 'text-white/40'
      : pnl > 0
      ? 'text-emerald-300'
      : pnl < 0
      ? 'text-rose-300'
      : 'text-white/70';
  return (
    <motion.tr
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2, delay: Math.min(index, 20) * 0.015 }}
      className="border-b border-glass-soft last:border-none hover:bg-white/[0.02] transition-colors"
    >
      <td className="px-3 py-2.5 font-mono text-white/70 whitespace-nowrap">
        {formatDate(t.created_at)}
      </td>
      <td className="px-3 py-2.5 font-mono font-semibold">{t.pair}</td>
      <td className="px-3 py-2.5">
        <span
          className={clsx(
            'text-[9px] uppercase tracking-widest px-1.5 py-0.5 rounded',
            isBuy
              ? 'bg-cyan-400/10 text-cyan-300 border border-cyan-400/20'
              : 'bg-pink-400/10 text-pink-300 border border-pink-400/20'
          )}
        >
          {t.direction}
        </span>
      </td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-white/70">
        {t.signal_confidence ? t.signal_confidence.toFixed(0) : '—'}
      </td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums">{formatPrice(t.entry_price)}</td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-white/70">
        {t.exit_price !== null && t.exit_price !== undefined ? formatPrice(t.exit_price) : '—'}
      </td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-rose-300/70">
        {formatPrice(t.stop_loss)}
      </td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-emerald-300/70">
        {formatPrice(t.take_profit)}
      </td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-white/60">
        {t.size_lot.toFixed(2)}
      </td>
      <td className="px-3 py-2.5 text-right font-mono text-white/50">
        {formatDuration(t.created_at, t.closed_at)}
      </td>
      <td className={clsx('px-3 py-2.5 text-right font-mono font-semibold tabular-nums', pnlTone)}>
        {pnl !== null && pnl !== undefined ? formatPnl(pnl) : '—'}
      </td>
      <td className="px-3 py-2.5">
        <span
          className={clsx(
            'text-[9px] uppercase tracking-widest px-1.5 py-0.5 rounded',
            t.status === 'OPEN'
              ? 'bg-amber-400/10 text-amber-300 border border-amber-400/20'
              : 'bg-white/5 text-white/50 border border-glass-soft'
          )}
        >
          {t.status}
        </span>
      </td>
    </motion.tr>
  );
}
