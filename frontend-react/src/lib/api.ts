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
  ShadowSetup,
  ShadowSummary,
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
  publicConfig: () => request<{ signup_enabled: boolean }>('/api/config'),

  whoami: () => request<User>('/api/me'),
  login: (username: string, password: string) =>
    request<{ ok: true }>('/api/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  signup: (email: string, password: string, accepted_terms: boolean, referral_code?: string) =>
    request<{ ok: true; user_id: number }>('/api/auth/signup', {
      method: 'POST',
      body: JSON.stringify({ email, password, accepted_terms, referral_code }),
    }),
  forgotPassword: (email: string) =>
    request<{ ok: true }>('/api/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify({ email }),
    }),
  resetPassword: (token: string, new_password: string) =>
    request<{ ok: true }>('/api/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify({ token, new_password }),
    }),
  logout: () => request<void>('/api/logout', { method: 'POST' }),

  // ─── Onboarding (Chantier 4 SaaS) ─────────────────────────────
  onboardingStatus: () =>
    request<{ has_broker: boolean; has_pairs: boolean; needs_onboarding: boolean }>(
      '/api/user/onboarding-status'
    ),

  userBrokerGet: () =>
    request<{
      bridge_url: string;
      broker_name: string;
      api_key_set: boolean;
      auto_exec_enabled: boolean;
      last_ea_heartbeat: string | null;
      mode: 'ea' | 'bridge' | 'none';
    }>('/api/user/broker'),

  userBrokerAutoExec: (enabled: boolean, demo_confirmed?: boolean) =>
    request<{ auto_exec_enabled: boolean }>('/api/user/broker/auto-exec', {
      method: 'POST',
      body: JSON.stringify({ enabled, demo_confirmed }),
    }),

  userBrokerGenerateApiKey: () =>
    request<{ api_key: string; api_key_set: true }>(
      '/api/user/broker/generate-api-key',
      { method: 'POST' }
    ),

  userWatchedPairsGet: () =>
    request<{ pairs: string[]; cap: number; tier: string }>('/api/user/watched-pairs'),

  userWatchedPairsPut: (pairs: string[]) =>
    request<{ ok: true; pairs: string[] }>('/api/user/watched-pairs', {
      method: 'PUT',
      body: JSON.stringify({ pairs }),
    }),

  // ─── Billing (Chantier 5 SaaS) ────────────────────────────────
  userTier: () =>
    request<{
      tier: string;
      tier_stored?: string;
      stripe_customer_set: boolean;
      stripe_subscription_set?: boolean;
      billing_cycle?: 'monthly' | 'yearly' | null;
      trial_active?: boolean;
      trial_days_left?: number | null;
      trial_ends_at?: string | null;
      email_verified?: boolean;
      legacy_env?: boolean;
    }>('/api/user/tier'),

  verifyEmail: (token: string) =>
    request<{ ok: true; user_id: number }>('/api/auth/verify-email', {
      method: 'POST',
      body: JSON.stringify({ token }),
    }),
  resendVerification: () =>
    request<{ ok: true; already_verified?: boolean }>('/api/auth/resend-verification', {
      method: 'POST',
    }),

  changePassword: (current_password: string, new_password: string) =>
    request<{ ok: true }>('/api/user/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password, new_password }),
    }),

  deleteAccount: (current_password: string) =>
    request<{ ok: true; deleted: true }>('/api/user/account', {
      method: 'DELETE',
      body: JSON.stringify({ current_password }),
    }),

  stripeCheckout: (tier: 'pro' | 'premium', billing_cycle: 'monthly' | 'yearly' = 'monthly') =>
    request<{ url: string }>('/api/stripe/checkout', {
      method: 'POST',
      body: JSON.stringify({ tier, billing_cycle }),
    }),

  stripePortal: () =>
    request<{ url: string }>('/api/stripe/portal', { method: 'POST' }),

  // ─── Admin (Chantier 12 SaaS) ────────────────────────────────
  adminUsers: () =>
    request<{
      totals: {
        total_users: number;
        active_users: number;
        signups_7d: number;
        signups_30d: number;
        trials_active: number;
        trials_j3_or_less: number;
        by_tier: { free?: number; pro?: number; premium?: number };
        mrr_eur: number;
      };
      users: Array<{
        id: number;
        email: string;
        tier_stored: string;
        tier_effective: string;
        billing_cycle: string | null;
        trial_active: boolean;
        trial_days_left: number | null;
        trial_ends_at: string | null;
        stripe_customer_set: boolean;
        stripe_subscription_set: boolean;
        created_at: string;
        last_login_at: string | null;
        is_active: boolean;
      }>;
    }>('/api/admin/users'),

  adminDeleteUser: (userId: number) =>
    request<{ ok: boolean; deleted_user_id: number }>(`/api/admin/users/${userId}`, {
      method: 'DELETE',
    }),

  adminWatchdogState: () =>
    request<{
      now: string;
      global_rafale_pause_active: boolean;
      global_rafale_pause_info: {
        triggered_at: string;
        min_resume_at?: string;
        max_resume_at?: string;
        expires_at?: string;
        reason: string;
        trigger_type: string;
      } | null;
      paused_pairs: Record<string, {
        triggered_at: string;
        min_resume_at?: string;
        max_resume_at?: string;
        expires_at?: string;
        reason: string;
        failed_pattern?: string;
        failed_direction?: string;
      }>;
      paused_pairs_count: number;
      sl_breakdown_24h: Array<{
        pair: string;
        pattern: string | null;
        count: number;
        pnl_total: number | null;
      }>;
      total_sl_24h: number;
      last_sl_trades: Array<{
        id: number;
        pair: string;
        direction: string;
        pattern: string | null;
        pnl: number | null;
        closed_at: string;
      }>;
      rejected_attempts_24h: Array<{
        pair: string;
        pattern: string | null;
        count: number;
      }>;
    }>('/api/admin/watchdog/state'),

  adminWatchdogUnpause: (body: { pair?: string; global?: boolean; all?: boolean }) =>
    request<{
      ok: boolean;
      cleared: { pairs: string[]; global: boolean };
      state: Record<string, unknown>;
    }>('/api/admin/watchdog/unpause', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

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

  // Phase 4 — shadow log V2_CORE_LONG
  shadowSetups: (params: { since?: string; until?: string; system_id?: string; outcome?: string; limit?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.since) qs.set('since', params.since);
    if (params.until) qs.set('until', params.until);
    if (params.system_id) qs.set('system_id', params.system_id);
    if (params.outcome) qs.set('outcome', params.outcome);
    if (params.limit) qs.set('limit', String(params.limit));
    const q = qs.toString();
    return request<ShadowSetup[]>(`/api/shadow/v2_core_long/setups${q ? `?${q}` : ''}`);
  },

  shadowSummary: () => request<ShadowSummary>('/api/shadow/v2_core_long/summary'),

  // Endpoints publics shadow log (sans auth, pages /v2/live et /v2/track-record)
  publicShadowSummary: () => request<ShadowSummary>('/api/public/shadow/summary'),
  publicShadowSetups: (params: { system_id?: string; outcome?: string; limit?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.system_id) qs.set('system_id', params.system_id);
    if (params.outcome) qs.set('outcome', params.outcome);
    if (params.limit) qs.set('limit', String(params.limit));
    const q = qs.toString();
    return request<ShadowSetup[]>(`/api/public/shadow/setups${q ? `?${q}` : ''}`);
  },

  publicLeadSubscribe: (email: string, source: string) =>
    request<{ ok: boolean; message: string }>('/api/public/leads/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, source }),
    }),

  publicResearchExperiments: () =>
    request<{ experiments: Array<{
      num: string; date: string; track: string;
      title: string; link: string | null;
      status: string; verdict: string;
    }>; count: number }>('/api/public/research/experiments'),

  publicChangelog: () =>
    request<{ commits: Array<{
      hash: string; date: string; type: string;
      scope: string | null; subject: string;
    }>; count: number }>('/api/public/changelog'),

  // Programme parrainage
  referralsMe: () =>
    request<{
      code: string | null;
      share_url: string;
      n_signups: number;
      n_converted: number;
      commission_total_eur: number;
      commission_paid_eur: number;
      commission_pending_eur: number;
    }>('/api/referrals/me'),

  publicReferralsValidate: (code: string) =>
    request<{ valid: boolean; owner_email_initials?: string; n_signups?: number }>(
      `/api/public/referrals/validate?code=${encodeURIComponent(code)}`
    ),

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
