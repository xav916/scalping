import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { AnimatePresence, motion } from 'motion/react';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '@/hooks/useAuth';
import { api } from '@/lib/api';
import { Skeleton } from '@/components/ui/Skeleton';
import { MobileBottomNav } from '@/components/layout/MobileBottomNav';
import { CommandPalette } from '@/components/ui/CommandPalette';

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

export function AuthGate({ requireOnboarded = false }: { requireOnboarded?: boolean } = {}) {
  const { whoami } = useAuth();
  const authed = !whoami.isLoading && whoami.isSuccess && !!whoami.data;

  // Status d'onboarding — requêté uniquement pour les routes protégées qui
  // l'exigent, et seulement une fois le user authentifié.
  const onboarding = useQuery({
    queryKey: ['user', 'onboarding'],
    queryFn: api.onboardingStatus,
    enabled: authed && requireOnboarded,
    staleTime: 60_000,
    retry: 0,
  });

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

  if (requireOnboarded) {
    if (onboarding.isLoading) {
      return (
        <div className="min-h-screen flex items-center justify-center">
          <Skeleton className="w-48 h-8" />
        </div>
      );
    }
    // Si l'appel échoue (legacy env 400, ou 500), on laisse passer — pas de
    // blocage sur une feature optionnelle.
    if (onboarding.data?.needs_onboarding) {
      return <Navigate to="/onboarding" replace />;
    }
  }

  return (
    <>
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
