import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { motion } from 'motion/react';
import { Header } from '@/components/layout/Header';
import { ReactiveMeshGradient } from '@/components/ui/ReactiveMeshGradient';
import { GlassCard } from '@/components/ui/GlassCard';
import { LiveChartsGrid } from '@/components/market/LiveChartsGrid';
import { api, ApiError } from '@/lib/api';
import { V1_LEGACY_PAIRS } from '@/lib/constants';

/**
 * /v2/v1-legacy — Page admin pour les anciens supports V1 (avant pivot
 * stars-only du 2026-04-26). Visible uniquement par les admins
 * (ADMIN_EMAILS côté backend). Le cockpit (home) affiche désormais
 * uniquement les stars (XAU/XAG/WTI/ETH).
 *
 * Vue sur :
 *  - Live charts des 12 anciennes paires (forex, BTC, indices SPX/NDX)
 *  - Stats trades V1 historiques (gardé pour audit / verdict V1)
 *
 * Si l'admin endpoint répond 403, on redirige vers /cockpit.
 */
export function V1LegacyPage() {
  // L'auth admin est gardée côté backend par require_admin sur les routes
  // /api/admin/*. On utilise l'endpoint adminUsers (rapide) comme test
  // d'autorisation : si 403, on bloque l'affichage.
  const { error } = useQuery({
    queryKey: ['admin', 'gate-check', 'v1-legacy'],
    queryFn: api.adminUsers,
    retry: 0,
    staleTime: 60_000,
  });

  if (error instanceof ApiError && error.status === 403) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <GlassCard className="p-8 max-w-sm text-center">
          <p className="text-white/80 mb-4">Accès admin requis.</p>
          <Link to="/cockpit" className="text-cyan-400 hover:text-cyan-300 text-sm">
            ← Retour au cockpit
          </Link>
        </GlassCard>
      </div>
    );
  }

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
            V1 — anciens supports{' '}
            <span className="text-white/40 text-sm font-normal ml-1">
              (admin only)
            </span>
          </h1>
          <p className="text-sm text-white/50 mt-1">
            Forex (10 paires) + BTC + indices SPX/NDX. Coupés de l'auto-exec et
            des notifs Telegram depuis le pivot stars-only du 2026-04-26.
            Conservés ici pour audit, comparaison V1 vs V2 et verdict
            historique.
          </p>
        </motion.div>

        <GlassCard className="p-4 text-xs text-amber-200/80 border-amber-400/20 bg-amber-500/[0.04]">
          ⚠️ Le verdict V1 est ferme :{' '}
          <span className="font-mono">39 689 trades</span> backtestés sans edge
          structurel. Cette page est un musée live, pas un terrain
          d'optimisation. Toute modification devrait passer par les processus
          recherche (track A/B/C, gate 2026-06-06).
        </GlassCard>

        <LiveChartsGrid pairs={V1_LEGACY_PAIRS} title="Prix live V1" />

        <GlassCard className="p-5 space-y-2">
          <h2 className="text-sm font-semibold tracking-tight">
            Comportement live de l'auto-exec V1
          </h2>
          <p className="text-xs text-white/60">
            Le bridge MT5 et les notifs Telegram filtrent ces paires :{' '}
            <span className="font-mono text-white/80">_not_a_star</span> dans{' '}
            <code className="text-white/70">mt5_bridge.py</code> et{' '}
            <code className="text-white/70">telegram_service.py</code>. Le radar
            continue de générer des setups dessus (pour stats), ils sont
            simplement non exécutés.
          </p>
          <p className="text-xs text-white/50">
            Pour voir les rejections détaillées, ouvrir{' '}
            <Link to="/trades" className="text-cyan-400 hover:text-cyan-300">
              /trades
            </Link>{' '}
            (filtre pair) ou{' '}
            <Link to="/analytics" className="text-cyan-400 hover:text-cyan-300">
              /analytics
            </Link>
            .
          </p>
        </GlassCard>
      </main>
    </>
  );
}
