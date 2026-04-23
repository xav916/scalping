import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from '@/lib/queryClient';
import { AuthGate } from '@/components/auth/AuthGate';
import { HomeRoute } from '@/components/HomeRoute';
import { ToastProvider } from '@/components/ui/Toast';
import { Skeleton } from '@/components/ui/Skeleton';

/** Code splitting par route : chaque page devient un chunk séparé chargé à
 *  la demande. Réduit le bundle initial (630 KB → ~350 KB) et améliore le
 *  TTI sur mobile / connexion lente. Les transitions AnimatePresence (fade
 *  + slide) de AuthGate servent aussi de "loader" naturel pendant le fetch
 *  du chunk — donc pas besoin de Skeleton visible en général. */
const DashboardPage = lazy(() =>
  import('@/pages/DashboardPage').then((m) => ({ default: m.DashboardPage }))
);
const LoginPage = lazy(() =>
  import('@/pages/LoginPage').then((m) => ({ default: m.LoginPage }))
);
const SignupPage = lazy(() =>
  import('@/pages/SignupPage').then((m) => ({ default: m.SignupPage }))
);
const ForgotPasswordPage = lazy(() =>
  import('@/pages/ForgotPasswordPage').then((m) => ({ default: m.ForgotPasswordPage }))
);
const ResetPasswordPage = lazy(() =>
  import('@/pages/ResetPasswordPage').then((m) => ({ default: m.ResetPasswordPage }))
);
const VerifyEmailPage = lazy(() =>
  import('@/pages/VerifyEmailPage').then((m) => ({ default: m.VerifyEmailPage }))
);
const OnboardingPage = lazy(() =>
  import('@/pages/OnboardingPage').then((m) => ({ default: m.OnboardingPage }))
);
const PricingPage = lazy(() =>
  import('@/pages/PricingPage').then((m) => ({ default: m.PricingPage }))
);
const SettingsPage = lazy(() =>
  import('@/pages/SettingsPage').then((m) => ({ default: m.SettingsPage }))
);
const AdminPage = lazy(() =>
  import('@/pages/AdminPage').then((m) => ({ default: m.AdminPage }))
);
const TradesPage = lazy(() =>
  import('@/pages/TradesPage').then((m) => ({ default: m.TradesPage }))
);
const CockpitPage = lazy(() =>
  import('@/pages/CockpitPage').then((m) => ({ default: m.CockpitPage }))
);
const AnalyticsPage = lazy(() =>
  import('@/pages/AnalyticsPage').then((m) => ({ default: m.AnalyticsPage }))
);

function RouteLoader() {
  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <Skeleton className="w-56 h-10" />
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter basename="/v2">
          <Suspense fallback={<RouteLoader />}>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/signup" element={<SignupPage />} />
              <Route path="/forgot-password" element={<ForgotPasswordPage />} />
              <Route path="/reset-password" element={<ResetPasswordPage />} />
              <Route path="/verify-email" element={<VerifyEmailPage />} />
              <Route path="/pricing" element={<PricingPage />} />
              <Route element={<AuthGate />}>
                <Route path="/onboarding" element={<OnboardingPage />} />
              </Route>
              <Route path="/" element={<HomeRoute />} />
              <Route element={<AuthGate requireOnboarded />}>
                <Route path="/dashboard" element={<DashboardPage />} />
                <Route path="/cockpit" element={<CockpitPage />} />
                <Route path="/analytics" element={<AnalyticsPage />} />
                <Route path="/trades" element={<TradesPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="/admin" element={<AdminPage />} />
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}
