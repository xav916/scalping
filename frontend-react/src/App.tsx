import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from '@/lib/queryClient';
import { AuthGate } from '@/components/auth/AuthGate';
import { ToastProvider } from '@/components/ui/Toast';
import { DashboardPage } from '@/pages/DashboardPage';
import { LoginPage } from '@/pages/LoginPage';
import { TradesPage } from '@/pages/TradesPage';
import { CockpitPage } from '@/pages/CockpitPage';
import { AnalyticsPage } from '@/pages/AnalyticsPage';

/** Les transitions de page (fade/slide) sont gérées désormais à l'intérieur
 *  de AuthGate sur l'Outlet uniquement — pour que la bottom nav mobile et
 *  la CommandPalette restent montées en permanence (sinon le pill indicator
 *  layoutId se rebuild à chaque click et perd son animation fluide). */
export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter basename="/v2">
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<AuthGate />}>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/cockpit" element={<CockpitPage />} />
              <Route path="/analytics" element={<AnalyticsPage />} />
              <Route path="/trades" element={<TradesPage />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}
