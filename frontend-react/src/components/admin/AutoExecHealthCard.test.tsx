import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/lib/api', () => ({
  api: {
    adminAutoExecHealth: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status = 500;
  },
}));

import { api } from '@/lib/api';
import { AutoExecHealthCard } from './AutoExecHealthCard';

function renderCard() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <AutoExecHealthCard />
    </QueryClientProvider>
  );
}

const baseResponse = {
  users: [],
  totals: {
    users_with_auto_exec: 0,
    users_live: 0,
    users_stale: 0,
    users_offline: 0,
    orders_24h: 0,
    executed_rate_24h: null,
    zombies_total: 0,
  },
  thresholds: {
    heartbeat_live_max_sec: 300,
    heartbeat_stale_max_sec: 1800,
    sent_stale_min_sec: 300,
    pending_overdue_pct: 0.8,
  },
};

describe('AutoExecHealthCard', () => {
  it('affiche le message empty quand aucun user auto-exec', async () => {
    vi.mocked(api.adminAutoExecHealth).mockResolvedValue(baseResponse);
    renderCard();
    await waitFor(() => {
      expect(screen.getByText(/Aucun user avec auto_exec_enabled/i)).toBeInTheDocument();
    });
  });

  it('affiche heartbeat LIVE + breakdown ordres + taux pour un user actif', async () => {
    vi.mocked(api.adminAutoExecHealth).mockResolvedValue({
      ...baseResponse,
      users: [{
        user_id: 1,
        email: 'admin@test.com',
        auto_exec_enabled: true,
        api_key_set: true,
        heartbeat: { last: '2026-05-02T08:00:00Z', age_seconds: 60, status: 'LIVE' as const },
        orders_24h: {
          total: 10,
          by_status: { EXECUTED: 8, FAILED: 1, EXPIRED: 1 },
          executed_rate: 0.8,
        },
        zombies: { sent_stale: 0, pending_overdue: 0, total: 0 },
        last_order: {
          id: 42, pair: 'XAU/USD', direction: 'buy', status: 'EXECUTED',
          mt5_ticket: 50012345, mt5_error: null,
          created_at: '2026-05-02T08:00:00Z', executed_at: '2026-05-02T08:00:05Z',
        },
      }],
      totals: { ...baseResponse.totals, users_with_auto_exec: 1, users_live: 1, orders_24h: 10 },
    });
    renderCard();
    await waitFor(() => {
      expect(screen.getByText('admin@test.com')).toBeInTheDocument();
    });
    expect(screen.getByText('LIVE')).toBeInTheDocument();
    expect(screen.getByText('80%')).toBeInTheDocument();
    expect(screen.getByText(/EXECUTED 8/)).toBeInTheDocument();
    expect(screen.getByText(/FAILED 1/)).toBeInTheDocument();
    expect(screen.getByText(/ticket 50012345/)).toBeInTheDocument();
  });

  it('met en avant les zombies en rouge', async () => {
    vi.mocked(api.adminAutoExecHealth).mockResolvedValue({
      ...baseResponse,
      users: [{
        user_id: 1,
        email: 'sus@test.com',
        auto_exec_enabled: true,
        api_key_set: true,
        heartbeat: { last: '2026-05-02T08:00:00Z', age_seconds: 100, status: 'LIVE' as const },
        orders_24h: { total: 1, by_status: { SENT: 1 }, executed_rate: null },
        zombies: { sent_stale: 1, pending_overdue: 0, total: 1 },
        last_order: null,
      }],
      totals: { ...baseResponse.totals, users_with_auto_exec: 1, users_live: 1, orders_24h: 1, zombies_total: 1 },
    });
    renderCard();
    await waitFor(() => {
      expect(screen.getByText(/1 SENT depuis > 5min/)).toBeInTheDocument();
    });
    expect(screen.getByText(/1 zombie/)).toBeInTheDocument();
  });
});
