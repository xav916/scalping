import { lazy, Suspense } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { Skeleton } from '@/components/ui/Skeleton';

const LandingPage = lazy(() =>
  import('@/pages/LandingPage').then((m) => ({ default: m.LandingPage }))
);

/**
 * Route racine `/` :
 * - user authentifié → redirect vers /dashboard
 * - non authentifié → LandingPage (publique)
 *
 * On ne fait PAS la vérif onboarding ici ; /dashboard derrière AuthGate
 * l'effectue et redirige vers /onboarding si incomplet.
 */
export function HomeRoute() {
  const { whoami } = useAuth();

  if (whoami.isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Skeleton className="w-48 h-8" />
      </div>
    );
  }

  if (whoami.isSuccess && whoami.data) {
    return <Navigate to="/cockpit" replace />;
  }

  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center p-6">
          <Skeleton className="w-56 h-10" />
        </div>
      }
    >
      <LandingPage />
    </Suspense>
  );
}
