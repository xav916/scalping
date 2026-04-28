import { Link } from 'react-router-dom';
import { motion } from 'motion/react';
import { Header } from '@/components/layout/Header';
import { ReactiveMeshGradient } from '@/components/ui/ReactiveMeshGradient';
import { GlassCard } from '@/components/ui/GlassCard';
import { Skeleton } from '@/components/ui/Skeleton';
import { useShadowSummary } from '@/hooks/useShadowLog';
import { CANDIDATE_SYSTEMS } from '@/lib/constants';

/**
 * /v2/candidates — Supports en observation shadow log (pas encore tradés
 * en live). Pendant les 4 stars actives (XAU/XAG/WTI/ETH visibles sur le
 * cockpit), ces candidats sont scorés en shadow uniquement et leurs
 * trades sont simulés. Promotion possible vers les stars actives si les
 * KPIs live convergent avec le backtest J1.
 */
export function CandidatesPage() {
  const { data: summary, isLoading } = useShadowSummary();

  const candidatesWithStats = CANDIDATE_SYSTEMS.map((c) => {
    const sysStat = summary?.systems.find((s) => s.system_id === c.system_id);
    return { ...c, stats: sysStat };
  });

  const totalCandidateSetups = candidatesWithStats.reduce(
    (acc, c) => acc + (c.stats?.n_total ?? 0),
    0
  );

  return (
    <>
      <ReactiveMeshGradient />
      <Header />
      <main className="px-4 sm:px-6 py-6 max-w-[1500px] mx-auto space-y-5">
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
        >
          <Link
            to="/cockpit"
            className="text-xs text-white/40 hover:text-white/70 transition-colors inline-flex items-center gap-1 mb-1"
          >
            ← Cockpit
          </Link>
          <h1 className="text-2xl font-semibold tracking-tight">
            Candidats{' '}
            <span className="text-white/40 text-sm font-normal ml-1">
              en observation shadow
            </span>
          </h1>
          <p className="text-sm text-white/50 mt-1">
            Supports validés par le scan systématique du portefeuille J1
            (2026-04-25), en cours d'observation live via shadow log avant
            promotion vers les stars actives. Pas de trades réels exécutés
            sur ces supports tant que les KPIs live ne convergent pas avec
            le backtest.
          </p>
        </motion.div>

        <GlassCard className="p-4 flex flex-wrap items-center gap-x-6 gap-y-2">
          <div className="text-sm">
            <span className="text-cyan-300 font-semibold">
              {candidatesWithStats.length}
            </span>{' '}
            <span className="text-white/50">candidats observés</span>
            <span className="text-white/40"> · </span>
            <span className="text-white/70 font-mono">
              {totalCandidateSetups}
            </span>{' '}
            <span className="text-white/50">setups loggés</span>
          </div>
          <div className="text-xs text-white/50">
            promotion auto vers stars =&gt;{' '}
            <span className="text-white/70">décision manuelle</span> sur
            convergence backtest/live
          </div>
        </GlassCard>

        {isLoading && !summary ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Skeleton className="h-64 rounded-2xl" />
            <Skeleton className="h-64 rounded-2xl" />
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {candidatesWithStats.map((c) => (
              <CandidateCard key={c.system_id} candidate={c} />
            ))}
          </div>
        )}

        <GlassCard className="p-5">
          <h2 className="text-sm font-semibold tracking-tight mb-2">
            Pour aller plus loin
          </h2>
          <p className="text-xs text-white/60">
            Les setups détaillés de chaque candidat sont dans le{' '}
            <Link to="/shadow-log" className="text-cyan-400 hover:text-cyan-300">
              shadow log
            </Link>{' '}
            — filtre par système pour voir l'historique complet (entry,
            SL/TP, durée, outcome). Le rapport hebdomadaire automatique
            (samedi matin Paris) compare les KPIs live aux cibles backtest
            (Sharpe ≥ 1.0, maxDD ≤ 25%, PF ≥ 1.5).
          </p>
        </GlassCard>
      </main>
    </>
  );
}

function CandidateCard({
  candidate,
}: {
  candidate: (typeof CANDIDATE_SYSTEMS)[number] & {
    stats?: {
      system_id: string;
      n_total: number;
      n_pending: number;
      n_tp1: number;
      n_sl: number;
      n_timeout: number;
      net_pnl_eur: number | null;
      pf: number | null;
      wr_pct: number | null;
    };
  };
}) {
  const stats = candidate.stats;
  const hasData = stats && stats.n_total > 0;

  return (
    <GlassCard variant="elevated" className="p-5 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-baseline gap-2">
            <h3 className="text-lg font-mono font-semibold tracking-tight">
              {candidate.pair}
            </h3>
            <span className="text-[10px] uppercase tracking-wider text-white/40">
              {candidate.tf} · {candidate.filter}
            </span>
          </div>
          <p className="text-xs text-white/50 mt-1.5 leading-relaxed">
            {candidate.rationale}
          </p>
        </div>
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-cyan-400/30 bg-cyan-400/10 text-cyan-300 text-[10px] font-semibold tracking-wider uppercase whitespace-nowrap">
          <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
          Shadow
        </span>
      </div>

      {!hasData ? (
        <div className="text-xs text-white/40 py-4 text-center border-t border-white/5 mt-1">
          Aucun setup loggé encore. Les candidats en TF Daily produisent
          ~1 setup/semaine en régime normal.
        </div>
      ) : (
        <>
          <div className="grid grid-cols-4 gap-2 pt-2 border-t border-white/5">
            <Mini label="Total" value={stats!.n_total} tone="neutral" />
            <Mini
              label="TP1"
              value={stats!.n_tp1}
              tone={stats!.n_tp1 > 0 ? 'pos' : 'neutral'}
            />
            <Mini
              label="SL"
              value={stats!.n_sl}
              tone={stats!.n_sl > 0 ? 'neg' : 'neutral'}
            />
            <Mini
              label="Pending"
              value={stats!.n_pending}
              tone="amber"
            />
          </div>
          <div className="grid grid-cols-3 gap-2">
            <Mini
              label="Net PnL"
              value={
                stats!.net_pnl_eur !== null
                  ? `${stats!.net_pnl_eur.toFixed(2)} €`
                  : '—'
              }
              tone={
                stats!.net_pnl_eur !== null && stats!.net_pnl_eur > 0
                  ? 'pos'
                  : stats!.net_pnl_eur !== null && stats!.net_pnl_eur < 0
                  ? 'neg'
                  : 'neutral'
              }
            />
            <Mini
              label="Win rate"
              value={stats!.wr_pct !== null ? `${stats!.wr_pct.toFixed(0)}%` : '—'}
              tone="neutral"
            />
            <Mini
              label="PF"
              value={stats!.pf !== null ? stats!.pf.toFixed(2) : '—'}
              tone={
                stats!.pf !== null && stats!.pf >= 1.2
                  ? 'pos'
                  : stats!.pf !== null && stats!.pf < 1
                  ? 'neg'
                  : 'neutral'
              }
            />
          </div>
        </>
      )}

      <Link
        to={`/shadow-log`}
        className="text-xs text-cyan-400 hover:text-cyan-300 inline-flex items-center gap-1 self-start"
      >
        Voir tous les setups dans le shadow log →
      </Link>
    </GlassCard>
  );
}

function Mini({
  label,
  value,
  tone,
}: {
  label: string;
  value: string | number;
  tone: 'pos' | 'neg' | 'neutral' | 'amber';
}) {
  const toneCls =
    tone === 'pos'
      ? 'text-emerald-300'
      : tone === 'neg'
      ? 'text-rose-300'
      : tone === 'amber'
      ? 'text-amber-300'
      : 'text-white/85';
  return (
    <div className="rounded-lg border border-glass-soft bg-white/[0.02] p-2">
      <div className="text-[9px] uppercase tracking-wider text-white/40">
        {label}
      </div>
      <div className={`font-mono tabular-nums text-sm ${toneCls}`}>{value}</div>
    </div>
  );
}
