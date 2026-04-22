import type {
  TradeSetup,
  MacroSnapshot,
  InsightsPerformance,
  User,
  Candle,
  EquityCurve,
  PersonalTrade,
  CockpitSnapshot,
  KillSwitchStatus,
  DriftReport,
  AnalyticsReport,
  PeriodStats,
  PeriodKey,
  Granularity,
  PnlBucketsResponse,
  BrokerAccount,
  ExposureTimeseries,
  RejectionsReport,
  MistakesReport,
  CombosReport,
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

  allCandles: () => request<Record<string, Candle[]>>('/api/candles'),

  equityCurve: (since: string = POST_FIX_CUTOFF) =>
    request<EquityCurve>(
      `/api/insights/equity-curve?since=${encodeURIComponent(since)}`
    ),

  trades: (params: { status?: string; limit?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.status) qs.set('status', params.status);
    if (params.limit) qs.set('limit', String(params.limit));
    const q = qs.toString();
    return request<PersonalTrade[]>(`/api/trades${q ? `?${q}` : ''}`);
  },

  cockpit: () => request<CockpitSnapshot>('/api/cockpit'),

  killSwitchStatus: () => request<KillSwitchStatus>('/api/kill-switch'),
  killSwitchSet: (enabled: boolean, reason?: string) =>
    request<KillSwitchStatus>('/api/kill-switch', {
      method: 'POST',
      body: JSON.stringify({ enabled, reason: reason ?? null }),
    }),

  drift: () => request<DriftReport>('/api/drift'),

  analytics: () => request<AnalyticsReport>('/api/analytics'),

  mistakes: () => request<MistakesReport>('/api/stats/mistakes'),

  combos: () => request<CombosReport>('/api/stats/combos'),

  periodStats: (arg: PeriodKey | { since: string; until: string }) => {
    if (typeof arg === 'string') {
      return request<PeriodStats>(`/api/insights/period-stats?period=${arg}`);
    }
    const qs = new URLSearchParams({ since: arg.since, until: arg.until });
    return request<PeriodStats>(`/api/insights/period-stats?${qs.toString()}`);
  },

  pnlBuckets: (since: string, until: string, granularity: Granularity | 'auto' = 'auto') => {
    const qs = new URLSearchParams({ since, until, granularity });
    return request<PnlBucketsResponse>(`/api/insights/pnl-buckets?${qs.toString()}`);
  },

  rejections: (since: string, until: string) => {
    const qs = new URLSearchParams({ since, until });
    return request<RejectionsReport>(`/api/insights/rejections?${qs.toString()}`);
  },

  brokerAccount: () => request<BrokerAccount>('/api/broker/account'),

  exposureTimeseries: (since: string, until: string, granularity: Granularity | 'auto' = 'auto') => {
    const qs = new URLSearchParams({ since, until, granularity });
    return request<ExposureTimeseries>(`/api/insights/exposure-timeseries?${qs.toString()}`);
  },

  health: () =>
    request<{
      healthy: boolean;
      last_cycle_at: string | null;
      seconds_since_last_cycle: number | null;
    }>('/api/health'),
};

export { ApiError };
