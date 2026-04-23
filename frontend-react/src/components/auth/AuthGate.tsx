import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { AnimatePresence, motion } from 'motion/react';
import { useAuth } from '@/hooks/useAuth';
import { Skeleton } from '@/components/ui/Skeleton';
import { MobileBottomNav } from '@/components/layout/MobileBottomNav';
import { CommandPalette } from '@/components/ui/CommandPalette';
import { TrialBanner } from '@/components/TrialBanner';

/** Anime SEULEMENT le contenu de route (Outlet). La bottom nav et la
 *  command palette restent montées hors de l'AnimatePresence pour que
 *  leurs layoutIds (pill indicator, etc.) puissent transitionner en
 *  continu entre les tabs au lieu d'être rebuild à chaque navigation. */
function AnimatedOutlet() {
  const location = useLocation();
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={location.pathname}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
        transition={{ duration: 0.3, ease: 'easeOut' }}
      >
        <Outlet />
      </motion.div>
    </AnimatePresence>
  );
}

/**
 * Pivot zero-friction (2026-04-23) : on ne bloque plus les routes auth sur
 * un "needs_onboarding" — les paires sont pré-sélectionnées au signup côté
 * backend, donc l'user atterrit direct sur le dashboard. La prop
 * `requireOnboarded` reste acceptée pour compat mais n'a plus d'effet.
 */
export function AuthGate({
  requireOnboarded: _requireOnboarded = false,
}: { requireOnboarded?: boolean } = {}) {
  const { whoami } = useAuth();

  if (whoami.isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Skeleton className="w-48 h-8" />
      </div>
    );
  }
  if (whoami.isError || !whoami.data) {
    return <Navigate to="/login" replace />;
  }

  return (
    <>
      {/* Bannière trial globale (self-hides si trial inactif). */}
      <TrialBanner />
      {/* Padding bottom sur mobile pour que le contenu ne soit pas masqué
          par la bottom nav fixée (env safe-area pour iPhone X+). */}
      <div className="pb-[72px] sm:pb-0">
        <AnimatedOutlet />
      </div>
      {/* Hors AnimatePresence → montés en permanence, layoutId stable */}
      <MobileBottomNav />
      <CommandPalette />
    </>
  );
}
