import { useCallback, useEffect, useState } from 'react';
import clsx from 'clsx';
import { Header } from '@/components/layout/Header';
import { ReactiveMeshGradient } from '@/components/ui/ReactiveMeshGradient';
import { Skeleton } from '@/components/ui/Skeleton';
import { EquityCurveMini } from '@/components/performance/EquityCurveMini';
import { PeriodMetricsCard } from '@/components/cockpit/PeriodMetricsCard';
import { PnlCalendarCard } from '@/components/cockpit/PnlCalendarCard';
import { RejectionsCard } from '@/components/cockpit/RejectionsCard';
import { BrokerMarginCard } from '@/components/cockpit/BrokerMarginCard';
import { ExposureTimelineCard } from '@/components/cockpit/ExposureTimelineCard';
import { KillSwitchCard } from '@/components/cockpit/KillSwitchCard';
import { AlertsStack } from '@/components/cockpit/AlertsStack';
import { TodayStatsCard } from '@/components/cockpit/TodayStatsCard';
import { CapitalAtRiskCard } from '@/components/cockpit/CapitalAtRiskCard';
import { AssetClassBreakdownCard } from '@/components/cockpit/AssetClassBreakdownCard';
import { FearGreedGauge } from '@/components/cockpit/FearGreedGauge';
import { ActiveTradesPanel } from '@/components/cockpit/ActiveTradesPanel';
import { SystemHealthCard } from '@/components/cockpit/SystemHealthCard';
import { CotExtremesCard } from '@/components/cockpit/CotExtremesCard';
import { DriftCard } from '@/components/cockpit/DriftCard';
import { NextEventsCard } from '@/components/cockpit/NextEventsCard';
import { useCockpit } from '@/hooks/useCockpit';
import { DateRangeProvider } from '@/hooks/useDateRange';

const SECTIONS = [
  { id: 'risk', label: 'Risque', accent: 'text-rose-300' },
  { id: 'performance', label: 'Performance', accent: 'text-emerald-300' },
  { id: 'analyse', label: 'Analyse', accent: 'text-cyan-300' },
  { id: 'systeme', label: 'Système', accent: 'text-amber-300' },
];

/** Cockpit — tour de contrôle. Sticky nav + sections ancrées pour survoler
 *  15+ cartes sans scroll-fatigue. Chaque section a son ancre et son chip
 *  dans la nav du haut. */
/** Wrapper : fournit un DateRangeProvider au sous-arbre pour que la
 *  PnlCalendarCard et la PeriodMetricsCard partagent le même state de range
 *  (clic sur un jour du calendrier drill la Performance card). */
export function CockpitPage() {
  return (
    <DateRangeProvider>
      <CockpitPageInner />
    </DateRangeProvider>
  );
}

function CockpitPageInner() {
  const { data, isLoading } = useCockpit();
  const [activeSection, setActiveSection] = useState<string>('risk');

  // Suivi de la section visible via IntersectionObserver
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (visible?.target.id) setActiveSection(visible.target.id);
      },
      {
        // Décale la zone "active" vers le haut pour que ça corresponde à la
        // section qu'on voit vraiment sous la sticky nav
        rootMargin: '-120px 0px -60% 0px',
        threshold: [0, 0.2, 0.5, 1],
      }
    );
    SECTIONS.forEach((s) => {
      const el = document.getElementById(s.id);
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, [data]);

  const scrollTo = useCallback((id: string) => {
    const el = document.getElementById(id);
    if (!el) return;
    const top = el.getBoundingClientRect().top + window.pageYOffset - 110;
    window.scrollTo({ top, behavior: 'smooth' });
  }, []);

  return (
    <>
      <ReactiveMeshGradient />
      <Header />
      <main className="px-4 sm:px-6 py-6 max-w-[1500px] mx-auto space-y-6">
        <div className="flex items-baseline justify-between gap-4 flex-wrap">
          <h1 className="text-2xl font-semibold tracking-tight">
            Cockpit{' '}
            <span className="text-white/40 text-sm font-normal ml-2">
              tour de contrôle temps réel
            </span>
          </h1>
          {data && (
            <span className="text-[10px] text-white/40 font-mono uppercase tracking-wider">
              maj · {new Date(data.generated_at).toLocaleTimeString('fr-FR')}
            </span>
          )}
        </div>

        {/* Sticky section nav */}
        <nav className="sticky top-[56px] z-30 -mx-4 sm:-mx-6 px-4 sm:px-6 py-2 bg-[#050810]/80 backdrop-blur-md border-y border-white/5">
          <div className="flex items-center gap-2 overflow-x-auto">
            <span className="text-[9px] uppercase tracking-[0.2em] text-white/30 font-mono mr-1 hidden sm:inline">
              aller à
            </span>
            {SECTIONS.map((s) => {
              const active = activeSection === s.id;
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => scrollTo(s.id)}
                  className={clsx(
                    'text-xs px-3 py-1.5 rounded-lg border transition-all font-semibold whitespace-nowrap',
                    active
                      ? `border-cyan-400/40 bg-cyan-400/10 ${s.accent} shadow-[0_0_12px_rgba(34,211,238,0.15)]`
                      : 'border-white/10 text-white/50 hover:text-white/90 hover:bg-white/[0.03]'
                  )}
                >
                  {s.label}
                </button>
              );
            })}
          </div>
        </nav>

        {isLoading && <Skeleton className="h-32" />}
        {data && (
          <>
            {/* URGENT : kill switch + alerts (toujours en haut, hors sections) */}
            <div className="grid grid-cols-1 md:grid-cols-[auto_1fr] gap-4">
              <KillSwitchCard
                active={data.kill_switch.active}
                reason={data.kill_switch.reason}
              />
              <AlertsStack alerts={data.alerts} />
            </div>

            {/* ═══════════ Risque & capital ═══════════ */}
            <section id="risk" className="space-y-6 scroll-mt-24">
              <SectionHeader
                label="Risque & capital"
                subtitle="L'argent en jeu, à l'instant T et dans le temps"
                accent="rose"
              />

              <BrokerMarginCard />

              <TodayStatsCard
                pnl={data.today_stats.pnl}
                pnlPct={data.today_stats.pnl_pct}
                nTrades={data.today_stats.n_trades}
                nOpen={data.today_stats.n_open}
                nClosed={data.today_stats.n_closed}
                capital={data.today_stats.capital}
                unrealizedPnl={data.active_trades.unrealized_pnl}
              />

              <ExposureTimelineCard />

              <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
                <div className="lg:col-span-5 min-w-0">
                  <CapitalAtRiskCard
                    trades={data.active_trades.items}
                    capital={data.today_stats.capital}
                  />
                </div>
                <div className="lg:col-span-4 min-w-0">
                  <AssetClassBreakdownCard trades={data.active_trades.items} />
                </div>
                <div className="lg:col-span-3 min-w-0">
                  <FearGreedGauge snapshot={data.fear_greed} />
                </div>
              </div>

              <ActiveTradesPanel trades={data.active_trades.items} />
            </section>

            {/* ═══════════ Performance ═══════════ */}
            <section id="performance" className="space-y-6 scroll-mt-24">
              <SectionHeader
                label="Performance"
                subtitle="Résultats sur la période, graph adaptive + drill-down"
                accent="emerald"
              />

              <PeriodMetricsCard />

              <PnlCalendarCard />
            </section>

            {/* ═══════════ Analyse ═══════════ */}
            <section id="analyse" className="space-y-6 scroll-mt-24">
              <SectionHeader
                label="Analyse"
                subtitle="Rejections, drift, patterns en régression"
                accent="cyan"
              />

              <RejectionsCard />

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <EquityCurveMini />
                <DriftCard />
                <div />
              </div>
            </section>

            {/* ═══════════ Système ═══════════ */}
            <section id="systeme" className="space-y-6 scroll-mt-24">
              <SectionHeader
                label="Système"
                subtitle="Santé radar / bridge / events macro"
                accent="amber"
              />

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <SystemHealthCard
                  healthy={data.system_health.healthy}
                  bridgeReachable={data.system_health.bridge.reachable}
                  bridgeConfigured={data.system_health.bridge.configured}
                  secondsSince={data.system_health.seconds_since_last_cycle}
                  wsClients={data.system_health.ws_clients}
                  sessionLabel={data.session?.label}
                />
                <NextEventsCard events={data.next_events} />
              </div>

              <CotExtremesCard items={data.cot_extremes} />
            </section>
          </>
        )}
      </main>
    </>
  );
}

function SectionHeader({
  label,
  subtitle,
  accent,
}: {
  label: string;
  subtitle: string;
  accent: 'rose' | 'emerald' | 'cyan' | 'amber';
}) {
  const dotClass = {
    rose: 'bg-rose-400',
    emerald: 'bg-emerald-400',
    cyan: 'bg-cyan-400',
    amber: 'bg-amber-400',
  }[accent];
  const labelClass = {
    rose: 'text-rose-300',
    emerald: 'text-emerald-300',
    cyan: 'text-cyan-300',
    amber: 'text-amber-300',
  }[accent];
  return (
    <div className="flex items-baseline gap-3 pt-2">
      <span className={clsx('w-1.5 h-5 rounded-sm shadow-[0_0_12px_rgba(34,211,238,0.15)]', dotClass)} />
      <h2 className={clsx('text-base font-semibold tracking-tight', labelClass)}>
        {label}
      </h2>
      <span className="text-[11px] text-white/40 font-mono">{subtitle}</span>
    </div>
  );
}
