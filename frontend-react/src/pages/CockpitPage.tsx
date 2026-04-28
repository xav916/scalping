import { useCallback, useEffect, useState, type ReactNode } from 'react';
import clsx from 'clsx';
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  arrayMove,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { Header } from '@/components/layout/Header';
import { ReactiveMeshGradient } from '@/components/ui/ReactiveMeshGradient';
import { Skeleton } from '@/components/ui/Skeleton';
import { Tooltip } from '@/components/ui/Tooltip';
import { EquityCurveMini } from '@/components/performance/EquityCurveMini';
import { LiveChartsGrid } from '@/components/market/LiveChartsGrid';
import { LiveEquityCard } from '@/components/cockpit/LiveEquityCard';
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
import { SortableCard } from '@/components/cockpit/SortableCard';
import { useCockpit } from '@/hooks/useCockpit';
import { DateRangeProvider } from '@/hooks/useDateRange';
import { useCardOrder, resetAllCardOrders } from '@/hooks/useCardOrder';
import type { CockpitSnapshot } from '@/types/domain';

const SECTIONS = [
  { id: 'risk', label: 'Risque', accent: 'text-rose-300' },
  { id: 'performance', label: 'Performance', accent: 'text-emerald-300' },
  { id: 'analyse', label: 'Analyse', accent: 'text-cyan-300' },
  { id: 'systeme', label: 'Système', accent: 'text-amber-300' },
];

// IDs canoniques (persistés en localStorage). Ne jamais renommer sans
// migration, les users perdraient leur layout.
const DEFAULT_RISK_IDS = [
  'broker-margin',
  'today-stats',
  'exposure-timeline',
  'risk-row', // atomic grid : CapitalAtRisk + AssetClassBreakdown + FearGreed
  'active-trades',
] as const;
const DEFAULT_PERF_IDS = ['period-metrics', 'pnl-calendar'] as const;
const DEFAULT_ANALYSE_IDS = ['rejections', 'analyse-row'] as const; // atomic : Equity + Drift
const DEFAULT_SYSTEM_IDS = ['system-row', 'cot-extremes'] as const; // atomic : SystemHealth + NextEvents

/** Détecte si on est en viewport "desktop" (≥ md). Réactif au resize. */
function useIsDesktop() {
  const [is, setIs] = useState(() =>
    typeof window === 'undefined' ? true : window.matchMedia('(min-width: 768px)').matches
  );
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 768px)');
    const handler = (e: MediaQueryListEvent) => setIs(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);
  return is;
}

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
  const isDesktop = useIsDesktop();

  // Order per section
  const risk = useCardOrder('risk', DEFAULT_RISK_IDS);
  const perf = useCardOrder('performance', DEFAULT_PERF_IDS);
  const analyse = useCardOrder('analyse', DEFAULT_ANALYSE_IDS);
  const systeme = useCardOrder('systeme', DEFAULT_SYSTEM_IDS);

  // DnD sensors — distance 8 pour éviter les drags accidentels au clic
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));

  // IntersectionObserver pour highlight la section active
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (visible?.target.id) setActiveSection(visible.target.id);
      },
      { rootMargin: '-120px 0px -60% 0px', threshold: [0, 0.2, 0.5, 1] }
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

  const handleReset = useCallback(() => {
    resetAllCardOrders();
    // Force reset des 4 états locaux pour sync immédiat (sinon les hooks
    // ne relisent localStorage qu'au prochain mount)
    risk.reset();
    perf.reset();
    analyse.reset();
    systeme.reset();
  }, [risk, perf, analyse, systeme]);

  const makeDragHandler = useCallback(
    (order: string[], reorder: (o: string[]) => void) => (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;
      const oldIndex = order.indexOf(String(active.id));
      const newIndex = order.indexOf(String(over.id));
      if (oldIndex < 0 || newIndex < 0) return;
      reorder(arrayMove(order, oldIndex, newIndex));
    },
    []
  );

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

        {/* Courbes live par support — heartbeat marché toujours visible */}
        <LiveChartsGrid />

        {/* Capital MT5 live (admin only — endpoint gated, render no-op si 403) */}
        <LiveEquityCard />

        {/* Sticky section nav + reset layout */}
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
            {isDesktop && (
              <>
                <span className="flex-1" />
                <Tooltip content="Remet l'ordre des cartes par défaut dans chaque section." delay={300}>
                  <button
                    type="button"
                    onClick={handleReset}
                    className="text-[11px] px-2.5 py-1.5 rounded-lg border border-white/10 text-white/50 hover:text-rose-300 hover:border-rose-400/30 hover:bg-rose-400/5 transition-all whitespace-nowrap"
                  >
                    ↺ Reset layout
                  </button>
                </Tooltip>
              </>
            )}
          </div>
        </nav>

        {isLoading && <Skeleton className="h-32" />}
        {data && (
          <>
            {/* URGENT : kill switch + alerts (pinned, non-draggable) */}
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
                subtitle="L'argent en jeu — glisser-déposer sur desktop pour réordonner"
                accent="rose"
              />
              <DndContext
                sensors={sensors}
                collisionDetection={closestCenter}
                onDragEnd={makeDragHandler(risk.order, risk.reorder)}
              >
                <SortableContext items={risk.order} strategy={verticalListSortingStrategy}>
                  <div className="space-y-6">
                    {risk.order.map((id) => (
                      <SortableCard key={id} id={id} disabled={!isDesktop}>
                        {renderRiskCard(id, data)}
                      </SortableCard>
                    ))}
                  </div>
                </SortableContext>
              </DndContext>
            </section>

            {/* ═══════════ Performance ═══════════ */}
            <section id="performance" className="space-y-6 scroll-mt-24">
              <SectionHeader
                label="Performance"
                subtitle="Résultats — graph adaptive, drill-down, calendrier"
                accent="emerald"
              />
              <DndContext
                sensors={sensors}
                collisionDetection={closestCenter}
                onDragEnd={makeDragHandler(perf.order, perf.reorder)}
              >
                <SortableContext items={perf.order} strategy={verticalListSortingStrategy}>
                  <div className="space-y-6">
                    {perf.order.map((id) => (
                      <SortableCard key={id} id={id} disabled={!isDesktop}>
                        {renderPerfCard(id)}
                      </SortableCard>
                    ))}
                  </div>
                </SortableContext>
              </DndContext>
            </section>

            {/* ═══════════ Analyse ═══════════ */}
            <section id="analyse" className="space-y-6 scroll-mt-24">
              <SectionHeader
                label="Analyse"
                subtitle="Rejections, drift, equity cumul"
                accent="cyan"
              />
              <DndContext
                sensors={sensors}
                collisionDetection={closestCenter}
                onDragEnd={makeDragHandler(analyse.order, analyse.reorder)}
              >
                <SortableContext items={analyse.order} strategy={verticalListSortingStrategy}>
                  <div className="space-y-6">
                    {analyse.order.map((id) => (
                      <SortableCard key={id} id={id} disabled={!isDesktop}>
                        {renderAnalyseCard(id)}
                      </SortableCard>
                    ))}
                  </div>
                </SortableContext>
              </DndContext>
            </section>

            {/* ═══════════ Système ═══════════ */}
            <section id="systeme" className="space-y-6 scroll-mt-24">
              <SectionHeader
                label="Système"
                subtitle="Santé radar / bridge / events macro"
                accent="amber"
              />
              <DndContext
                sensors={sensors}
                collisionDetection={closestCenter}
                onDragEnd={makeDragHandler(systeme.order, systeme.reorder)}
              >
                <SortableContext items={systeme.order} strategy={verticalListSortingStrategy}>
                  <div className="space-y-6">
                    {systeme.order.map((id) => (
                      <SortableCard key={id} id={id} disabled={!isDesktop}>
                        {renderSystemCard(id, data)}
                      </SortableCard>
                    ))}
                  </div>
                </SortableContext>
              </DndContext>
            </section>
          </>
        )}
      </main>
    </>
  );
}

function renderRiskCard(id: string, data: CockpitSnapshot): ReactNode {
  switch (id) {
    case 'broker-margin':
      return <BrokerMarginCard />;
    case 'today-stats':
      return (
        <TodayStatsCard
          pnl={data.today_stats.pnl}
          pnlPct={data.today_stats.pnl_pct}
          nTrades={data.today_stats.n_trades}
          nOpen={data.today_stats.n_open}
          nClosed={data.today_stats.n_closed}
          capital={data.today_stats.capital}
          unrealizedPnl={data.active_trades.unrealized_pnl}
        />
      );
    case 'exposure-timeline':
      return <ExposureTimelineCard />;
    case 'risk-row':
      return (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <div className="lg:col-span-5 min-w-0">
            <CapitalAtRiskCard trades={data.active_trades.items} capital={data.today_stats.capital} />
          </div>
          <div className="lg:col-span-4 min-w-0">
            <AssetClassBreakdownCard trades={data.active_trades.items} />
          </div>
          <div className="lg:col-span-3 min-w-0">
            <FearGreedGauge snapshot={data.fear_greed} />
          </div>
        </div>
      );
    case 'active-trades':
      return <ActiveTradesPanel trades={data.active_trades.items} />;
    default:
      return null;
  }
}

function renderPerfCard(id: string): ReactNode {
  switch (id) {
    case 'period-metrics':
      return <PeriodMetricsCard />;
    case 'pnl-calendar':
      return <PnlCalendarCard />;
    default:
      return null;
  }
}

function renderAnalyseCard(id: string): ReactNode {
  switch (id) {
    case 'rejections':
      return <RejectionsCard />;
    case 'analyse-row':
      return (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <EquityCurveMini />
          <DriftCard />
        </div>
      );
    default:
      return null;
  }
}

function renderSystemCard(id: string, data: CockpitSnapshot): ReactNode {
  switch (id) {
    case 'system-row':
      return (
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
      );
    case 'cot-extremes':
      return <CotExtremesCard items={data.cot_extremes} />;
    default:
      return null;
  }
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
      <h2 className={clsx('text-base font-semibold tracking-tight', labelClass)}>{label}</h2>
      <span className="text-[11px] text-white/40 font-mono">{subtitle}</span>
    </div>
  );
}
