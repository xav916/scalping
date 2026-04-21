import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { AnimatePresence, motion } from 'motion/react';
import { queryClient } from '@/lib/queryClient';
import { AuthGate } from '@/components/auth/AuthGate';
import { DashboardPage } from '@/pages/DashboardPage';
import { LoginPage } from '@/pages/LoginPage';
import { TradesPage } from '@/pages/TradesPage';
import { CockpitPage } from '@/pages/CockpitPage';

function AnimatedRoutes() {
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
        <Routes location={location}>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<AuthGate />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/cockpit" element={<CockpitPage />} />
            <Route path="/trades" element={<TradesPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </motion.div>
    </AnimatePresence>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename="/v2">
        <AnimatedRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
