import { Header } from '@/components/layout/Header';
import { MacroBanner } from '@/components/macro/MacroBanner';
import { SetupsGrid } from '@/components/setups/SetupsGrid';
import { PerformancePanel } from '@/components/performance/PerformancePanel';
import { PerformanceMiniKPI } from '@/components/performance/PerformanceMiniKPI';
import { SessionClock } from '@/components/sessions/SessionClock';
import { MeshGradient } from '@/components/ui/MeshGradient';

export function DashboardPage() {
  return (
    <>
      <MeshGradient />
      <Header />
      <main className="px-6 py-6 max-w-[1500px] mx-auto space-y-6">
        {/* Row 1 : bandeau macro pleine largeur */}
        <MacroBanner />

        {/* Row 2 : bento — setups (gauche large) + rail droit (SessionClock + MiniKPIs) */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <section className="lg:col-span-8">
            <div className="flex items-baseline justify-between mb-3">
              <h2 className="text-sm uppercase tracking-[0.2em] text-white/50">Setups en cours</h2>
              <span className="text-[10px] text-white/30 font-mono uppercase tracking-wider">
                live · filtrés ≥ 50
              </span>
            </div>
            <SetupsGrid />
          </section>

          <aside className="lg:col-span-4 space-y-6">
            <SessionClock />
            <PerformanceMiniKPI />
          </aside>
        </div>

        {/* Row 3 : performance détaillée pleine largeur */}
        <PerformancePanel />
      </main>
    </>
  );
}
