import type {
  TradeSetup,
  MacroSnapshot,
  InsightsPerformance,
  User,
} from '@/types/domain';
import { POST_FIX_CUTOFF } from '@/lib/constants';

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    let body = '';
    try {
      body = await res.text();
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, body || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  whoami: () => request<User>('/api/me'),
  login: (username: string, password: string) =>
    request<{ ok: true }>('/api/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<void>('/api/logout', { method: 'POST' }),

  macro: async () => {
    const raw = await request<{ status: string; snapshot: MacroSnapshot | null }>(
      '/api/macro'
    );
    return raw.snapshot;
  },

  setups: async (): Promise<TradeSetup[]> => {
    const raw = await request<{ trade_setups?: TradeSetup[] }>('/api/overview');
    return raw.trade_setups ?? [];
  },

  performance: (since: string = POST_FIX_CUTOFF) =>
    request<InsightsPerformance>(
      `/api/insights/performance?since=${encodeURIComponent(since)}`
    ),
};

export { ApiError };
