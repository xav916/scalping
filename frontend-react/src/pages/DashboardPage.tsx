import { Header } from '@/components/layout/Header';
import { MacroBanner } from '@/components/macro/MacroBanner';
import { SetupsGrid } from '@/components/setups/SetupsGrid';
import { PerformancePanel } from '@/components/performance/PerformancePanel';
import { MeshGradient } from '@/components/ui/MeshGradient';

export function DashboardPage() {
  return (
    <>
      <MeshGradient />
      <Header />
      <main className="px-6 py-6 max-w-[1400px] mx-auto space-y-6">
        <MacroBanner />
        <section>
          <h2 className="text-sm uppercase tracking-wider text-white/50 mb-3">Setups en cours</h2>
          <SetupsGrid />
        </section>
        <PerformancePanel />
      </main>
    </>
  );
}
