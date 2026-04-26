import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { motion } from 'motion/react';
import { api } from '@/lib/api';
import { GlassCard } from '@/components/ui/GlassCard';
import { AnimatedMeshGradient } from '@/components/ui/AnimatedMeshGradient';
import { GradientText } from '@/components/ui/GradientText';
import { RadarPulse } from '@/components/ui/RadarPulse';
import type { ShadowSetup } from '@/types/domain';

/**
 * Page publique /v2/live — affiche les KPIs et setups récents du shadow log
 * en temps réel, sans login. Utilise les endpoints publics
 * /api/public/shadow/{summary,setups} ouverts en lecture seule.
 *
 * Refresh auto toutes les 60s.
 */

function formatDateTime(iso: string): string {
  try {
    return new Intl.DateTimeFormat('fr-FR', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'Europe/Paris',
    }).format(new Date(iso));
  } catch {
    return iso.slice(0, 16);
  }
}

function outcomeColor(o: string | null): string {
  if (o === 'TP1') return 'text-emerald-400';
  if (o === 'SL') return 'text-rose-400';
  if (o === 'TIMEOUT') return 'text-amber-400';
  return 'text-white/40';
}

function outcomeLabel(o: string | null): string {
  if (o === null) return 'pending';
  if (o === 'TP1') return 'TP1 ✓';
  if (o === 'SL') return 'SL ✗';
  if (o === 'TIMEOUT') return 'timeout';
  return o;
}

function pnlColor(pnl: number | null): string {
  if (pnl === null) return 'text-white/40';
  return pnl >= 0 ? 'text-emerald-400' : 'text-rose-400';
}

export function LivePage() {
  const summaryQuery = useQuery({
    queryKey: ['public', 'shadow', 'summary'],
    queryFn: () => api.publicShadowSummary(),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const setupsQuery = useQuery({
    queryKey: ['public', 'shadow', 'setups', 'recent'],
    queryFn: () => api.publicShadowSetups({ limit: 30 }),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const totals = useMemo(() => {
    const sys = summaryQuery.data?.systems ?? [];
    const n_total = sys.reduce((s, x) => s + x.n_total, 0);
    const n_resolved = sys.reduce((s, x) => s + x.n_tp1 + x.n_sl + x.n_timeout, 0);
    const n_pending = sys.reduce((s, x) => s + x.n_pending, 0);
    const net_pnl_eur = sys.reduce((s, x) => s + (x.net_pnl_eur ?? 0), 0);
    const gross_win = sys.reduce((s, x) => s + (x.gross_win_eur ?? 0), 0);
    const gross_loss = sys.reduce((s, x) => s + (x.gross_loss_eur ?? 0), 0);
    const pf = gross_loss > 0 ? gross_win / gross_loss : null;
    const wr = n_resolved > 0
      ? (sys.reduce((s, x) => s + x.n_tp1, 0) / Math.max(sys.reduce((s, x) => s + x.n_tp1 + x.n_sl, 0), 1)) * 100
      : null;
    return { n_total, n_resolved, n_pending, net_pnl_eur, pf, wr };
  }, [summaryQuery.data]);

  const setups = setupsQuery.data ?? [];

  return (
    <div className="min-h-screen">
      <AnimatedMeshGradient />

      {/* Header */}
      <header className="relative z-10 px-6 py-4 flex items-center justify-between max-w-6xl mx-auto">
        <Link to="/" className="flex items-center gap-2">
          <RadarPulse size={32} />
          <span className="font-semibold tracking-tight">Scalping Radar</span>
        </Link>
        <nav className="flex items-center gap-5">
          <Link to="/track-record" className="text-sm text-white/60 hover:text-white transition-colors">Track record</Link>
          <Link to="/pricing" className="text-sm text-white/60 hover:text-white transition-colors">Tarifs</Link>
          <Link to="/login" className="text-sm text-white/60 hover:text-white transition-colors">Connexion</Link>
        </nav>
      </header>

      {/* Hero */}
      <section className="relative z-10 max-w-6xl mx-auto px-6 py-12">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="text-center mb-10"
        >
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-400/10 border border-emerald-400/30 mb-4">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-xs uppercase tracking-wider text-emerald-300">
              Live · refresh auto 60s
            </span>
          </div>
          <h1 className="text-4xl md:text-5xl font-bold tracking-tight mb-3">
            <GradientText>Shadow log en direct</GradientText>
          </h1>
          <p className="text-white/60 text-sm max-w-2xl mx-auto">
            Les 6 stars (XAU H4, XAG H4, WTI H4, ETH 1d, XLI 1d, XLK 1d) en temps réel.
            Aucun login requis — c'est notre track record public.
          </p>
        </motion.div>

        {/* KPIs globaux */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-10">
          {[
            { label: 'Setups totaux', value: totals.n_total.toString(), color: 'text-cyan-300' },
            { label: 'Résolus', value: totals.n_resolved.toString(), color: 'text-white/80' },
            { label: 'Pending', value: totals.n_pending.toString(), color: 'text-amber-300' },
            { label: 'Win rate', value: totals.wr !== null ? `${totals.wr.toFixed(1)}%` : '—', color: 'text-emerald-400' },
            { label: 'Profit Factor', value: totals.pf !== null ? totals.pf.toFixed(2) : '—', color: 'text-emerald-400' },
            { label: 'Net PnL', value: `${totals.net_pnl_eur >= 0 ? '+' : ''}${totals.net_pnl_eur.toFixed(0)}€`, color: pnlColor(totals.net_pnl_eur) },
          ].map((kpi) => (
            <GlassCard key={kpi.label} className="p-4">
              <div className="text-[10px] uppercase tracking-wider text-white/40 mb-1">{kpi.label}</div>
              <div className={`text-2xl font-bold font-mono ${kpi.color}`}>{kpi.value}</div>
            </GlassCard>
          ))}
        </div>

        {/* Per-system breakdown */}
        <h2 className="text-xl font-semibold mb-4">
          <GradientText>Par système</GradientText>
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 mb-10">
          {(summaryQuery.data?.systems ?? []).map((s) => (
            <GlassCard key={s.system_id} className="p-4">
              <div className="text-xs font-mono text-cyan-300 mb-2">{s.system_id}</div>
              <div className="grid grid-cols-3 gap-2 text-xs">
                <div>
                  <div className="text-white/40">n</div>
                  <div className="text-white/90 font-mono">{s.n_total}</div>
                </div>
                <div>
                  <div className="text-white/40">PF</div>
                  <div className="text-emerald-400 font-mono">{s.pf?.toFixed(2) ?? '—'}</div>
                </div>
                <div>
                  <div className="text-white/40">WR</div>
                  <div className="text-emerald-400 font-mono">{s.wr_pct?.toFixed(0) ?? '—'}%</div>
                </div>
              </div>
              <div className="mt-2 text-xs">
                <span className="text-white/40">PnL :</span>{' '}
                <span className={`font-mono ${pnlColor(s.net_pnl_eur)}`}>
                  {s.net_pnl_eur >= 0 ? '+' : ''}{s.net_pnl_eur.toFixed(0)}€
                </span>
                {s.advanced?.sharpe !== null && s.advanced?.sharpe !== undefined && (
                  <span className="ml-3 text-white/40">
                    Sharpe :{' '}
                    <span className="text-cyan-300 font-mono">{s.advanced.sharpe.toFixed(2)}</span>
                  </span>
                )}
              </div>
            </GlassCard>
          ))}
          {(summaryQuery.data?.systems ?? []).length === 0 && !summaryQuery.isLoading && (
            <div className="col-span-full text-center text-white/50 text-sm py-8">
              Aucun setup encore enregistré. Le système vient juste d'être déployé — les premiers setups arrivent dès l'ouverture des marchés.
            </div>
          )}
        </div>

        {/* Setups récents */}
        <h2 className="text-xl font-semibold mb-4">
          <GradientText>Setups récents (30 derniers)</GradientText>
        </h2>
        <GlassCard className="p-0 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs sm:text-sm">
              <thead>
                <tr className="text-white/50 border-b border-white/5">
                  <th className="text-left px-3 py-2 font-medium">Bar</th>
                  <th className="text-left px-3 py-2 font-medium">Pair</th>
                  <th className="text-left px-3 py-2 font-medium hidden sm:table-cell">TF</th>
                  <th className="text-left px-3 py-2 font-medium">Pattern</th>
                  <th className="text-right px-3 py-2 font-medium hidden md:table-cell">Entry</th>
                  <th className="text-center px-3 py-2 font-medium">Outcome</th>
                  <th className="text-right px-3 py-2 font-medium">PnL</th>
                </tr>
              </thead>
              <tbody>
                {setups.map((s: ShadowSetup) => (
                  <tr key={s.id} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
                    <td className="px-3 py-2 text-white/60 font-mono whitespace-nowrap">
                      {formatDateTime(s.bar_timestamp)}
                    </td>
                    <td className="px-3 py-2 text-cyan-300 font-mono font-semibold">{s.pair}</td>
                    <td className="px-3 py-2 text-white/50 hidden sm:table-cell uppercase">{s.timeframe}</td>
                    <td className="px-3 py-2 text-white/70 font-mono">{s.pattern}</td>
                    <td className="px-3 py-2 text-right text-white/60 font-mono hidden md:table-cell">
                      {s.entry_price.toFixed(s.entry_price > 100 ? 2 : 4)}
                    </td>
                    <td className={`px-3 py-2 text-center font-medium ${outcomeColor(s.outcome)}`}>
                      {outcomeLabel(s.outcome)}
                    </td>
                    <td className={`px-3 py-2 text-right font-mono ${pnlColor(s.pnl_eur)}`}>
                      {s.pnl_eur !== null ? `${s.pnl_eur >= 0 ? '+' : ''}${s.pnl_eur.toFixed(0)}€` : '—'}
                    </td>
                  </tr>
                ))}
                {setups.length === 0 && !setupsQuery.isLoading && (
                  <tr>
                    <td colSpan={7} className="px-3 py-8 text-center text-white/50">
                      Aucun setup récent. Vérifiez plus tard ou consultez le track record complet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </GlassCard>

        <div className="mt-6 text-center">
          <Link
            to="/track-record"
            className="text-sm text-cyan-300 hover:text-cyan-200 font-medium"
          >
            Voir le track record complet →
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="relative z-10 max-w-6xl mx-auto px-6 py-10 text-center text-xs text-white/40">
        <p>Données live shadow log V2_CORE_LONG · Performances passées ≠ performances futures · Pas un conseil d'investissement</p>
      </footer>
    </div>
  );
}
