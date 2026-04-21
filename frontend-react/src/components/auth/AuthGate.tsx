import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { Skeleton } from '@/components/ui/Skeleton';

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
  return <Outlet />;
}
