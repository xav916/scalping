import { useCockpit } from "@/hooks/useCockpit";
import { ActiveTradesPanel } from "@/components/cockpit/ActiveTradesPanel";
import { AlertsStack } from "@/components/cockpit/AlertsStack";
import { MacroBanner } from "@/components/cockpit/MacroBanner";
import { PendingSetupsPanel } from "@/components/cockpit/PendingSetupsPanel";
import { SystemHealthFooter } from "@/components/cockpit/SystemHealthFooter";
import { TodayStatsBar } from "@/components/cockpit/TodayStatsBar";

export function CockpitPage() {
  const { cockpit, loading, error, wsConnected } = useCockpit();

  if (loading && !cockpit) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500">
        Chargement du cockpit…
      </div>
    );
  }
  if (error && !cockpit) {
    return (
      <div className="flex items-center justify-center h-full text-danger">
        Erreur : {(error as Error).message}
      </div>
    );
  }
  if (!cockpit) return null;

  return (
    <div className="space-y-4">
      <MacroBanner
        macro={cockpit.macro}
        session={cockpit.session}
        fearGreed={cockpit.fear_greed}
      />
      <AlertsStack alerts={cockpit.alerts} />
      <div className="grid gap-4 lg:grid-cols-2">
        <ActiveTradesPanel data={cockpit.active_trades} />
        <PendingSetupsPanel data={cockpit.pending_setups} />
      </div>
      <TodayStatsBar today={cockpit.today_stats} />
      <SystemHealthFooter health={cockpit.system_health} wsConnected={wsConnected} />
    </div>
  );
}
