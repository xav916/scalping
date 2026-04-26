import { useMemo, useState } from 'react';
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
 * Page publique /v2/track-record — affiche TOUT l'historique des setups
 * shadow log avec filtres et stats agrégées par star. Lecture seule, sans
 * login. Différenciant principal vs concurrents qui cachent leurs résultats.
 */

type SystemFilter = 'all' | string;
type OutcomeFilter = 'all' | 'pending' | 'TP1' | 'SL' | 'TIMEOUT';

function formatDate(iso: string): string {
  try {
    return new Intl.DateTimeFormat('fr-FR', {
      day: '2-digit',
      month: 'short',
      year: '2-digit',
      timeZone: 'Europe/Paris',
    }).format(new Date(iso));
  } catch {
    return iso.slice(0, 10);
  }
}

function outcomeColor(o: string | null): string {
  if (o === 'TP1') return 'text-emerald-400';
  if (o === 'SL') return 'text-rose-400';
  if (o === 'TIMEOUT') return 'text-amber-400';
  return 'text-white/40';
}

function pnlColor(pnl: number | null): string {
  if (pnl === null) return 'text-white/40';
  return pnl >= 0 ? 'text-emerald-400' : 'text-rose-400';
}

export function TrackRecordPage() {
  const [system, setSystem] = useState<SystemFilter>('all');
  const [outcome, setOutcome] = useState<OutcomeFilter>('all');

  const summaryQuery = useQuery({
    queryKey: ['public', 'shadow', 'summary'],
    queryFn: () => api.publicShadowSummary(),
    refetchInterval: 120_000,
    staleTime: 60_000,
  });

  const setupsQuery = useQuery({
    queryKey: ['public', 'shadow', 'setups', 'all', system, outcome],
    queryFn: () =>
      api.publicShadowSetups({
        system_id: system === 'all' ? undefined : system,
        outcome: outcome === 'all' ? undefined : outcome,
        limit: 200,
      }),
    refetchInterval: 120_000,
    staleTime: 60_000,
  });

  const systems = summaryQuery.data?.systems ?? [];
  const setups = setupsQuery.data ?? [];

  const totals = useMemo(() => {
    const n_total = systems.reduce((s, x) => s + x.n_total, 0);
    const n_resolved = systems.reduce((s, x) => s + x.n_tp1 + x.n_sl + x.n_timeout, 0);
    const n_pending = systems.reduce((s, x) => s + x.n_pending, 0);
    const n_tp1 = systems.reduce((s, x) => s + x.n_tp1, 0);
    const n_sl = systems.reduce((s, x) => s + x.n_sl, 0);
    const net_pnl_eur = systems.reduce((s, x) => s + (x.net_pnl_eur ?? 0), 0);
    const gross_win = systems.reduce((s, x) => s + (x.gross_win_eur ?? 0), 0);
    const gross_loss = systems.reduce((s, x) => s + (x.gross_loss_eur ?? 0), 0);
    const pf = gross_loss > 0 ? gross_win / gross_loss : null;
    const wr = (n_tp1 + n_sl) > 0 ? (n_tp1 / (n_tp1 + n_sl)) * 100 : null;
    return { n_total, n_resolved, n_pending, net_pnl_eur, pf, wr };
  }, [systems]);

  return (
    <div className="min-h-screen">
      <AnimatedMeshGradient />

      <header className="relative z-10 px-6 py-4 flex items-center justify-between max-w-6xl mx-auto">
        <Link to="/" className="flex items-center gap-2">
          <RadarPulse size={32} />
          <span className="font-semibold tracking-tight">Scalping Radar</span>
        </Link>
        <nav className="flex items-center gap-5">
          <Link to="/live" className="text-sm text-white/60 hover:text-white transition-colors">Live</Link>
          <Link to="/pricing" className="text-sm text-white/60 hover:text-white transition-colors">Tarifs</Link>
          <Link to="/login" className="text-sm text-white/60 hover:text-white transition-colors">Connexion</Link>
        </nav>
      </header>

      <section className="relative z-10 max-w-6xl mx-auto px-6 py-12">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="text-center mb-10"
        >
          <h1 className="text-4xl md:text-5xl font-bold tracking-tight mb-3">
            <GradientText>Track record public</GradientText>
          </h1>
          <p className="text-white/60 text-sm max-w-2xl mx-auto">
            Tous les setups détectés depuis le déploiement Phase 4. Aucune cherry-picking,
            aucune sélection. Tu vois tout — les wins, les losses, les pending, les timeouts.
          </p>
        </motion.div>

        {/* Totaux globaux */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-8">
          {[
            { label: 'Setups détectés', value: totals.n_total.toString(), color: 'text-cyan-300' },
            { label: 'Résolus', value: totals.n_resolved.toString(), color: 'text-white/80' },
            { label: 'TP1 ✓', value: systems.reduce((s, x) => s + x.n_tp1, 0).toString(), color: 'text-emerald-400' },
            { label: 'SL ✗', value: systems.reduce((s, x) => s + x.n_sl, 0).toString(), color: 'text-rose-400' },
            { label: 'Profit Factor', value: totals.pf !== null ? totals.pf.toFixed(2) : '—', color: totals.pf !== null && totals.pf >= 1 ? 'text-emerald-400' : 'text-rose-400' },
            { label: 'Net PnL cumul', value: `${totals.net_pnl_eur >= 0 ? '+' : ''}${totals.net_pnl_eur.toFixed(0)}€`, color: pnlColor(totals.net_pnl_eur) },
          ].map((kpi) => (
            <GlassCard key={kpi.label} className="p-4">
              <div className="text-[10px] uppercase tracking-wider text-white/40 mb-1">{kpi.label}</div>
              <div className={`text-2xl font-bold font-mono ${kpi.color}`}>{kpi.value}</div>
            </GlassCard>
          ))}
        </div>

        {/* Filtres */}
        <div className="flex flex-wrap items-center gap-3 mb-6">
          <span className="text-xs uppercase tracking-wider text-white/40">Filtrer :</span>
          <select
            value={system}
            onChange={(e) => setSystem(e.target.value)}
            className="px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-sm font-mono"
          >
            <option value="all">Tous systèmes</option>
            {systems.map((s) => (
              <option key={s.system_id} value={s.system_id}>{s.system_id}</option>
            ))}
          </select>
          <select
            value={outcome}
            onChange={(e) => setOutcome(e.target.value as OutcomeFilter)}
            className="px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-sm"
          >
            <option value="all">Tous outcomes</option>
            <option value="pending">Pending</option>
            <option value="TP1">TP1 (gagnant)</option>
            <option value="SL">SL (perdant)</option>
            <option value="TIMEOUT">Timeout</option>
          </select>
          <span className="text-xs text-white/40">{setups.length} setups affichés</span>
        </div>

        {/* Table complète */}
        <GlassCard className="p-0 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs sm:text-sm">
              <thead>
                <tr className="text-white/50 border-b border-white/5 bg-white/[0.02]">
                  <th className="text-left px-3 py-2 font-medium">Date</th>
                  <th className="text-left px-3 py-2 font-medium">Pair</th>
                  <th className="text-left px-3 py-2 font-medium hidden sm:table-cell">TF</th>
                  <th className="text-left px-3 py-2 font-medium">Pattern</th>
                  <th className="text-right px-3 py-2 font-medium hidden lg:table-cell">Entry</th>
                  <th className="text-right px-3 py-2 font-medium hidden lg:table-cell">SL</th>
                  <th className="text-right px-3 py-2 font-medium hidden lg:table-cell">TP1</th>
                  <th className="text-right px-3 py-2 font-medium hidden md:table-cell">R:R</th>
                  <th className="text-center px-3 py-2 font-medium">Outcome</th>
                  <th className="text-right px-3 py-2 font-medium">PnL %</th>
                  <th className="text-right px-3 py-2 font-medium">PnL €</th>
                </tr>
              </thead>
              <tbody>
                {setups.map((s: ShadowSetup) => (
                  <tr key={s.id} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
                    <td className="px-3 py-2 text-white/60 font-mono whitespace-nowrap">{formatDate(s.bar_timestamp)}</td>
                    <td className="px-3 py-2 text-cyan-300 font-mono font-semibold">{s.pair}</td>
                    <td className="px-3 py-2 text-white/50 hidden sm:table-cell uppercase">{s.timeframe}</td>
                    <td className="px-3 py-2 text-white/70 font-mono text-[11px]">{s.pattern}</td>
                    <td className="px-3 py-2 text-right text-white/60 font-mono hidden lg:table-cell">{s.entry_price.toFixed(s.entry_price > 100 ? 2 : 4)}</td>
                    <td className="px-3 py-2 text-right text-rose-300/60 font-mono hidden lg:table-cell">{s.stop_loss.toFixed(s.stop_loss > 100 ? 2 : 4)}</td>
                    <td className="px-3 py-2 text-right text-emerald-300/60 font-mono hidden lg:table-cell">{s.take_profit_1.toFixed(s.take_profit_1 > 100 ? 2 : 4)}</td>
                    <td className="px-3 py-2 text-right text-white/60 font-mono hidden md:table-cell">{s.rr.toFixed(2)}</td>
                    <td className={`px-3 py-2 text-center font-medium ${outcomeColor(s.outcome)}`}>
                      {s.outcome ?? 'pending'}
                    </td>
                    <td className={`px-3 py-2 text-right font-mono ${pnlColor(s.pnl_pct_net)}`}>
                      {s.pnl_pct_net !== null ? `${s.pnl_pct_net >= 0 ? '+' : ''}${s.pnl_pct_net.toFixed(2)}%` : '—'}
                    </td>
                    <td className={`px-3 py-2 text-right font-mono ${pnlColor(s.pnl_eur)}`}>
                      {s.pnl_eur !== null ? `${s.pnl_eur >= 0 ? '+' : ''}${s.pnl_eur.toFixed(0)}€` : '—'}
                    </td>
                  </tr>
                ))}
                {setups.length === 0 && !setupsQuery.isLoading && (
                  <tr>
                    <td colSpan={11} className="px-3 py-12 text-center text-white/50">
                      <div className="space-y-2">
                        <p>Aucun setup ne correspond aux filtres actuels.</p>
                        <p className="text-xs">
                          Le système vient juste d'être déployé — les premiers setups
                          apparaîtront dès l'ouverture des marchés (lundi 13:30 UTC pour les ETFs US).
                        </p>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </GlassCard>

        <div className="mt-8 grid grid-cols-1 md:grid-cols-2 gap-4">
          <GlassCard className="p-5">
            <h3 className="font-semibold mb-2">Comment lire ce track record</h3>
            <ul className="text-sm text-white/60 space-y-1.5">
              <li>• <span className="text-emerald-400">TP1 ✓</span> = setup atteint le take-profit 1</li>
              <li>• <span className="text-rose-400">SL ✗</span> = setup atteint le stop-loss</li>
              <li>• <span className="text-amber-400">TIMEOUT</span> = exit forcé après 96h (H4) ou 240h (Daily)</li>
              <li>• <span className="text-white/60">pending</span> = setup en cours, pas encore résolu</li>
              <li>• PnL en € = sizing virtuel 0.25-0.5% sur capital 10k€</li>
            </ul>
          </GlassCard>
          <GlassCard className="p-5">
            <h3 className="font-semibold mb-2">Méthodologie</h3>
            <p className="text-sm text-white/60 leading-relaxed">
              6 stars validées sur 20 ans de backtest cross-régime
              (XAU/XAG/WTI H4, ETH/XLI/XLK 1d).
              Filtres V2_CORE_LONG / V2_WTI_OPTIMAL / V2_TIGHT_LONG dérivés
              de 36 expériences publiées dans le journal de recherche.
              <Link to="/" className="text-cyan-300 hover:text-cyan-200 ml-1">En savoir plus →</Link>
            </p>
          </GlassCard>
        </div>
      </section>

      <footer className="relative z-10 max-w-6xl mx-auto px-6 py-10 text-center text-xs text-white/40">
        <p>Track record live shadow log V2_CORE_LONG · Performances passées ≠ performances futures · Pas un conseil d'investissement</p>
      </footer>
    </div>
  );
}
