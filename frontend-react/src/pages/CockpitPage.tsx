import { Header } from '@/components/layout/Header';
import { ReactiveMeshGradient } from '@/components/ui/ReactiveMeshGradient';
import { Skeleton } from '@/components/ui/Skeleton';
import { EquityCurveMini } from '@/components/performance/EquityCurveMini';
import { PeriodMetricsCard } from '@/components/cockpit/PeriodMetricsCard';
import { PnlCalendarCard } from '@/components/cockpit/PnlCalendarCard';
import { RejectionsCard } from '@/components/cockpit/RejectionsCard';
import { BrokerMarginCard } from '@/components/cockpit/BrokerMarginCard';
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

/** Cockpit — tour de contrôle. Orchestrator pur : chaque zone est un composant
 *  dédié dans `@/components/cockpit/*`. Le fetch `/api/cockpit` est centralisé
 *  ici et ses champs sont distribués aux sous-composants. */
export function CockpitPage() {
  const { data, isLoading } = useCockpit();

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

        {isLoading && <Skeleton className="h-32" />}
        {data && (
          <>
            <div className="grid grid-cols-1 md:grid-cols-[auto_1fr] gap-4">
              <KillSwitchCard
                active={data.kill_switch.active}
                reason={data.kill_switch.reason}
              />
              <AlertsStack alerts={data.alerts} />
            </div>

            <PeriodMetricsCard />

            <PnlCalendarCard />

            <RejectionsCard />

            <TodayStatsCard
              pnl={data.today_stats.pnl}
              pnlPct={data.today_stats.pnl_pct}
              nTrades={data.today_stats.n_trades}
              nOpen={data.today_stats.n_open}
              nClosed={data.today_stats.n_closed}
              capital={data.today_stats.capital}
              unrealizedPnl={data.active_trades.unrealized_pnl}
            />

            <BrokerMarginCard />

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

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <EquityCurveMini />
              <SystemHealthCard
                healthy={data.system_health.healthy}
                bridgeReachable={data.system_health.bridge.reachable}
                bridgeConfigured={data.system_health.bridge.configured}
                secondsSince={data.system_health.seconds_since_last_cycle}
                wsClients={data.system_health.ws_clients}
                sessionLabel={data.session?.label}
              />
              <DriftCard />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <CotExtremesCard items={data.cot_extremes} />
              <NextEventsCard events={data.next_events} />
            </div>
          </>
        )}
      </main>
    </>
  );
}
