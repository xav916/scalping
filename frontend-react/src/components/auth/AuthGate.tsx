import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { Skeleton } from '@/components/ui/Skeleton';
import { MobileBottomNav } from '@/components/layout/MobileBottomNav';

export function AuthGate() {
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
      {/* Padding bottom sur mobile pour que le contenu ne soit pas masqué
          par la bottom nav fixée (env safe-area pour iPhone X+). */}
      <div className="pb-[72px] sm:pb-0">
        <Outlet />
      </div>
      <MobileBottomNav />
    </>
  );
}
