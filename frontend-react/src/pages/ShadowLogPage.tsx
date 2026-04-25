import { useState, useMemo } from 'react';
import clsx from 'clsx';
import { Link } from 'react-router-dom';
import { Header } from '@/components/layout/Header';
import { MeshGradient } from '@/components/ui/MeshGradient';
import { GlassCard } from '@/components/ui/GlassCard';
import { Skeleton } from '@/components/ui/Skeleton';
import { useShadowSetups, useShadowSummary } from '@/hooks/useShadowLog';
import { EquityCurveChart } from '@/components/shadow/EquityCurveChart';
import { MonthlyReturnsChart } from '@/components/shadow/MonthlyReturnsChart';
import type { ShadowSetup } from '@/types/domain';

type OutcomeFilter = 'all' | 'pending' | 'TP1' | 'SL' | 'TIMEOUT';
type SystemFilter = 'all' | 'V2_CORE_LONG_XAUUSD_4H' | 'V2_CORE_LONG_XAGUSD_4H';

function formatDate(iso: string): string {
  try {
    return new Intl.DateTimeFormat('fr-FR', {
      day: '2-digit',
      month: '2-digit',
      year: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'Europe/Paris',
    }).format(new Date(iso));
  } catch {
    return iso.slice(0, 16);
  }
}

function outcomeColor(outcome: string | null): string {
  if (outcome === 'TP1') return 'text-emerald-400';
  if (outcome === 'SL') return 'text-rose-400';
  if (outcome === 'TIMEOUT') return 'text-amber-400';
  return 'text-white/40';
}

function pnlColor(pnl: number | null): string {
  if (pnl === null) return 'text-white/40';
  return pnl >= 0 ? 'text-emerald-400' : 'text-rose-400';
}

export function ShadowLogPage() {
  const [system, setSystem] = useState<SystemFilter>('all');
  const [outcome, setOutcome] = useState<OutcomeFilter>('all');

  const { data: setups, isLoading } = useShadowSetups({
    system_id: system === 'all' ? undefined : system,
    outcome: outcome === 'all' ? undefined : outcome,
    limit: 200,
  });
  const { data: summary } = useShadowSummary();

  const totals = useMemo(() => {
    const sys = summary?.systems ?? [];
    const n_total = sys.reduce((s, x) => s + x.n_total, 0);
    const n_resolved = sys.reduce((s, x) => s + x.n_tp1 + x.n_sl + x.n_timeout, 0);
    const n_pending = sys.reduce((s, x) => s + x.n_pending, 0);
    const net_pnl_eur = sys.reduce((s, x) => s + (x.net_pnl_eur ?? 0), 0);
    const gross_win = sys.reduce((s, x) => s + (x.gross_win_eur ?? 0), 0);
    const gross_loss = sys.reduce((s, x) => s + (x.gross_loss_eur ?? 0), 0);
    const pf = gross_loss > 0 ? gross_win / gross_loss : null;
    return { n_total, n_resolved, n_pending, net_pnl_eur, pf };
  }, [summary]);

  return (
    <>
      <MeshGradient />
      <Header />
      <main className="px-4 sm:px-6 py-6 max-w-[1500px] mx-auto space-y-4">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <Link
              to="/dashboard"
              className="text-xs text-white/40 hover:text-white/70 transition-colors inline-flex items-center gap-1 mb-1"
            >
              ← Dashboard
            </Link>
            <h1 className="text-2xl font-semibold tracking-tight">Shadow Log V2_CORE_LONG</h1>
            <p className="text-sm text-white/50 mt-1">
              Observation live — Track A V2_CORE_LONG sur XAU H4 + XAG H4 — Sharpe backtest 1.59
            </p>
          </div>
        </div>

        {/* KPIs synthèse */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <GlassCard className="p-4">
            <div className="text-xs text-white/50 uppercase tracking-wide">Setups</div>
            <div className="text-2xl font-semibold mt-1">{totals.n_total}</div>
            <div className="text-xs text-white/40">{totals.n_resolved} résolus / {totals.n_pending} pending</div>
          </GlassCard>
          <GlassCard className="p-4">
            <div className="text-xs text-white/50 uppercase tracking-wide">PF observé</div>
            <div className={clsx('text-2xl font-semibold mt-1', totals.pf !== null && totals.pf >= 1.3 ? 'text-emerald-400' : totals.pf !== null && totals.pf >= 1.0 ? 'text-amber-400' : 'text-rose-400')}>
              {totals.pf !== null ? totals.pf.toFixed(2) : '—'}
            </div>
            <div className="text-xs text-white/40">cible backtest 1.59</div>
          </GlassCard>
          <GlassCard className="p-4">
            <div className="text-xs text-white/50 uppercase tracking-wide">PnL net</div>
            <div className={clsx('text-2xl font-semibold mt-1', pnlColor(totals.net_pnl_eur))}>
              {totals.net_pnl_eur >= 0 ? '+' : ''}{totals.net_pnl_eur.toFixed(0)} €
            </div>
            <div className="text-xs text-white/40">capital virtuel 10k€</div>
          </GlassCard>
          {summary?.systems?.map((s) => (
            <GlassCard className="p-4" key={s.system_id}>
              <div className="text-xs text-white/50 uppercase tracking-wide">
                {s.system_id.includes('XAU') ? 'XAU/USD' : 'XAG/USD'}
              </div>
              <div className="text-lg font-semibold mt-1">
                {s.n_total} setups
              </div>
              <div className="text-xs text-white/40">
                Sharpe {s.advanced?.sharpe?.toFixed(2) ?? '—'} · maxDD {s.advanced?.max_dd_pct?.toFixed(1) ?? '—'}%
              </div>
            </GlassCard>
          ))}
        </div>

        {/* Equity curves par système */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {summary?.systems?.map((s) => (
            <GlassCard className="p-4" key={`curve-${s.system_id}`}>
              <div className="flex items-center justify-between mb-2">
                <div>
                  <div className="text-xs text-white/50 uppercase tracking-wide">
                    Equity curve {s.system_id.includes('XAU') ? 'XAU/USD' : 'XAG/USD'}
                  </div>
                  <div className="text-xs text-white/40 mt-1">
                    {s.advanced?.n_months ?? 0} mois · {s.advanced?.equity_curve.length ?? 0} setups résolus
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-xs text-white/50">Calmar</div>
                  <div className="text-sm font-semibold">{s.advanced?.calmar?.toFixed(2) ?? '—'}</div>
                </div>
              </div>
              <EquityCurveChart curve={s.advanced?.equity_curve ?? []} />
              <div className="mt-3 pt-3 border-t border-white/5">
                <div className="text-xs text-white/50 uppercase tracking-wide mb-2">Returns mensuels</div>
                <MonthlyReturnsChart monthly={s.advanced?.monthly_returns ?? []} />
              </div>
            </GlassCard>
          ))}
        </div>

        {/* Filtres */}
        <div className="flex flex-wrap gap-2">
          <select
            value={system}
            onChange={(e) => setSystem(e.target.value as SystemFilter)}
            className="bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-sm"
          >
            <option value="all">Toutes paires</option>
            <option value="V2_CORE_LONG_XAUUSD_4H">XAU/USD H4</option>
            <option value="V2_CORE_LONG_XAGUSD_4H">XAG/USD H4</option>
          </select>
          <select
            value={outcome}
            onChange={(e) => setOutcome(e.target.value as OutcomeFilter)}
            className="bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-sm"
          >
            <option value="all">Tous outcomes</option>
            <option value="pending">Pending</option>
            <option value="TP1">TP1</option>
            <option value="SL">SL</option>
            <option value="TIMEOUT">TIMEOUT</option>
          </select>
        </div>

        {/* Tableau */}
        <GlassCard className="p-0 overflow-hidden">
          {isLoading && <div className="p-6"><Skeleton className="h-40" /></div>}
          {!isLoading && setups && setups.length === 0 && (
            <div className="p-6 text-center text-white/50 text-sm">Aucun setup pour ces filtres</div>
          )}
          {!isLoading && setups && setups.length > 0 && (
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="bg-white/5 text-white/60 uppercase text-xs">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Bar</th>
                    <th className="px-3 py-2 text-left font-medium">Pair</th>
                    <th className="px-3 py-2 text-left font-medium">Pattern</th>
                    <th className="px-3 py-2 text-right font-medium">Entry</th>
                    <th className="px-3 py-2 text-right font-medium">SL</th>
                    <th className="px-3 py-2 text-right font-medium">TP1</th>
                    <th className="px-3 py-2 text-right font-medium">RR</th>
                    <th className="px-3 py-2 text-right font-medium">Position €</th>
                    <th className="px-3 py-2 text-center font-medium">Outcome</th>
                    <th className="px-3 py-2 text-right font-medium">PnL €</th>
                  </tr>
                </thead>
                <tbody>
                  {setups.map((s: ShadowSetup) => (
                    <tr key={s.id} className="border-t border-white/5 hover:bg-white/5">
                      <td className="px-3 py-2 text-white/70 whitespace-nowrap">{formatDate(s.bar_timestamp)}</td>
                      <td className="px-3 py-2">{s.pair}</td>
                      <td className="px-3 py-2 text-white/60">{s.pattern}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{s.entry_price.toFixed(4)}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-rose-400/80">{s.stop_loss.toFixed(4)}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-emerald-400/80">{s.take_profit_1.toFixed(4)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{s.rr.toFixed(2)}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-white/50">{s.sizing_position_eur.toFixed(0)}</td>
                      <td className={clsx('px-3 py-2 text-center font-medium', outcomeColor(s.outcome))}>
                        {s.outcome ?? '…'}
                      </td>
                      <td className={clsx('px-3 py-2 text-right tabular-nums', pnlColor(s.pnl_eur))}>
                        {s.pnl_eur !== null ? `${s.pnl_eur >= 0 ? '+' : ''}${s.pnl_eur.toFixed(0)}` : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassCard>
      </main>
    </>
  );
}
