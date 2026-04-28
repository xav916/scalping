import { Link, Navigate } from 'react-router-dom';
import { motion } from 'motion/react';
import { Header } from '@/components/layout/Header';
import { ReactiveMeshGradient } from '@/components/ui/ReactiveMeshGradient';
import { GlassCard } from '@/components/ui/GlassCard';
import { Skeleton } from '@/components/ui/Skeleton';
import { LiveChartsGrid } from '@/components/market/LiveChartsGrid';
import { useAuth } from '@/hooks/useAuth';
import { V1_LEGACY_PAIRS } from '@/lib/constants';

interface HubLink {
  to: string;
  title: string;
  description: string;
  badge?: string;
}

const V1_TOOLS: HubLink[] = [
  {
    to: '/analytics',
    title: 'Analytics',
    description:
      'Breakdowns win rate par feature : heure, paire, pattern, asset_class, régime macro. Sert pour V1 audit et calibration.',
  },
  {
    to: '/trades',
    title: 'Trades',
    description:
      "Table PnL complète + filtres status/auto + KPIs. Inclut les trades historiques V1 (forex + indices avant pivot 2026-04-26).",
  },
  {
    to: '/shadow-log',
    title: 'Shadow log V2',
    description:
      "Setups V2_CORE_LONG live observés sur les 6 stars + candidats. Source de vérité pour le rapport hebdomadaire (samedi 09:00 Paris).",
    badge: 'V2',
  },
  {
    to: '/supports',
    title: 'Supports',
    description:
      'Support technique, FAQ, contact, statut subscription. Pour les beta users et résolution de problèmes.',
  },
];

/**
 * /v2/v1 — Hub central pour les outils legacy V1 et les pages secondaires.
 * Le menu principal est désormais réduit à : Cockpit · Candidats · Infra · V1.
 * Cette page sert de rangement pour ne pas perdre les outils existants
 * tout en gardant un menu top-level propre.
 *
 * Inclut aussi à la fin la grille live des 12 anciens supports V1
 * (forex/BTC/SPX/NDX) coupés du portefeuille actif depuis le 2026-04-26.
 */
export function V1HubPage() {
  const { whoami } = useAuth();

  // Page entière admin only (depuis 2026-04-28). Les non-admins sont
  // redirigés vers le cockpit. Les routes individuelles
  // (/v2/analytics, /v2/trades, /v2/shadow-log, /v2/supports) restent
  // accessibles directement par URL pour les non-admins.
  if (whoami.isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Skeleton className="w-48 h-8" />
      </div>
    );
  }
  if (!whoami.data?.is_admin) {
    return <Navigate to="/cockpit" replace />;
  }
  const isAdmin = true;

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
          <h1 className="text-2xl font-semibold tracking-tight">V1</h1>
          <p className="text-sm text-white/50 mt-1">
            Hub des outils legacy + analyses détaillées. Le menu top-level
            est réservé au flux principal (Cockpit, Candidats, Infra) ;
            tout le reste est rangé ici.
          </p>
        </motion.div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {V1_TOOLS.map((tool) => (
            <Link key={tool.to} to={tool.to} className="block group">
              <GlassCard
                variant="elevated"
                className="p-5 hover:border-cyan-400/30 hover:bg-white/[0.05] transition-colors h-full"
              >
                <div className="flex items-baseline justify-between gap-3 mb-2">
                  <h2 className="text-base font-semibold tracking-tight group-hover:text-cyan-200 transition-colors">
                    {tool.title}
                  </h2>
                  {tool.badge && (
                    <span className="text-[10px] font-mono font-semibold text-cyan-300/80 px-2 py-0.5 rounded-md bg-cyan-400/10 border border-cyan-400/20">
                      {tool.badge}
                    </span>
                  )}
                </div>
                <p className="text-xs text-white/55 leading-relaxed">
                  {tool.description}
                </p>
                <div className="mt-3 text-xs text-white/40 group-hover:text-cyan-300 inline-flex items-center gap-1 transition-colors">
                  Ouvrir →
                </div>
              </GlassCard>
            </Link>
          ))}
        </div>

        {/* Section "anciens supports" — admin only.
            Pour les non-admin, on cache simplement (le menu n'a plus
            de lien dédié à /v1-legacy de toutes manières). */}
        {isAdmin && (
          <>
            <div className="pt-2">
              <h2 className="text-base font-semibold tracking-tight">
                Anciens supports V1
                <span className="text-white/40 text-xs font-normal ml-2">
                  admin only · musée live
                </span>
              </h2>
              <p className="text-sm text-white/50 mt-1">
                Forex (10 paires) + BTC + indices SPX/NDX. Coupés de
                l'auto-exec et des notifs Telegram depuis le pivot
                stars-only du 2026-04-26. Verdict V1 ferme :{' '}
                <span className="font-mono">39 689 trades</span> backtestés
                sans edge.
              </p>
            </div>

            <LiveChartsGrid pairs={V1_LEGACY_PAIRS} title="Prix live V1" />
          </>
        )}
      </main>
    </>
  );
}
