import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { SWRConfig } from "swr";
import { swrFetcher } from "@/api/client";
import { Layout } from "@/components/Layout";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AnalyticsPage } from "@/pages/AnalyticsPage";
import { CockpitPage } from "@/pages/CockpitPage";
import { LoginPage } from "@/pages/LoginPage";
import { TradesPage } from "@/pages/TradesPage";

export default function App() {
  return (
    <SWRConfig
      value={{
        fetcher: swrFetcher,
        revalidateOnFocus: false,
        shouldRetryOnError: (err) => {
          // Pas de retry auto sur 401 (on redirige vers /login).
          return (err as { status?: number }).status !== 401;
        },
      }}
    >
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }
          >
            <Route path="/" element={<CockpitPage />} />
            <Route path="/analytics" element={<AnalyticsPage />} />
            <Route path="/trades" element={<TradesPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </SWRConfig>
  );
}
