// Types miroir des payloads backend. Source de verite : backend/services/*.
// A garder synchrone avec les changements d'API (pas de codegen pour
// l'instant — on reste simple).

export type RiskRegime = "risk_on" | "neutral" | "risk_off";

export type Alert = {
  level: "critical" | "warning" | "info";
  code: string;
  msg: string;
};

export type ActiveTrade = {
  id: number;
  pair: string;
  direction: "buy" | "sell";
  entry_price: number;
  current_price: number | null;
  stop_loss: number;
  take_profit: number;
  size_lot: number;
  pnl_unrealized: number | null;
  pnl_pips: number | null;
  distance_to_sl_pct: number | null;
  distance_to_tp_pct: number | null;
  near_sl: boolean;
  duration_min: number | null;
  is_auto: boolean;
  mt5_ticket: number | null;
};

export type PendingSetup = {
  pair: string;
  direction: "buy" | "sell";
  entry_price: number;
  stop_loss: number;
  take_profit_1: number;
  confidence_score: number;
  verdict_action: "TAKE" | "WAIT" | "SKIP";
  asset_class: string;
  pattern: string | null;
  message: string;
  timestamp: string;
};

export type KillSwitchStatus = {
  active: boolean;
  reason: string | null;
  manual_enabled: boolean;
  manual_reason: string | null;
  manual_set_at: string | null;
  auto_triggered_by_daily_loss: boolean;
  daily_loss_limit_pct: number | null;
};

export type Cockpit = {
  generated_at: string;
  active_trades: {
    count: number;
    total_exposure_lots: number;
    unrealized_pnl: number;
    items: ActiveTrade[];
  };
  pending_setups: {
    count: number;
    total_count: number;
    items: PendingSetup[];
  };
  today_stats: {
    date: string;
    pnl: number;
    pnl_pct: number;
    n_trades: number;
    n_open: number;
    n_closed: number;
    silent_mode: boolean;
    loss_alert: boolean;
    capital: number;
  };
  system_health: {
    healthy: boolean;
    last_cycle_at: string | null;
    seconds_since_last_cycle: number | null;
    bridge: { configured: boolean; reachable: boolean; mode: string | null };
    ws_clients: number;
    watched_pairs: number;
  };
  macro: null | {
    fresh: boolean;
    risk_regime: RiskRegime;
    dxy: string;
    spx: string;
    vix_level: string;
    vix_value: number;
    fetched_at: string;
  };
  kill_switch: KillSwitchStatus;
  session: {
    label: string;
    activity_multiplier: number;
    is_weekend: boolean;
  };
  blackouts: Array<{ pair: string; reason: string }>;
  cot_extremes: Array<{
    pair: string;
    report_date: string;
    signals: Array<{ actor: string; z: number; interpretation: string }>;
  }>;
  fear_greed: null | {
    recorded_at: string;
    value: number;
    classification:
      | "extreme_fear"
      | "fear"
      | "neutral"
      | "greed"
      | "extreme_greed";
  };
  next_events: Array<{
    time: string;
    currency: string;
    impact: string;
    event_name: string;
  }>;
  alerts: Alert[];
};

export type AnalyticsBucket = {
  key: string;
  wins: number;
  losses: number;
  total: number;
  win_rate_pct: number;
};

export type Analytics = {
  by_pair: AnalyticsBucket[];
  by_hour_utc: AnalyticsBucket[];
  by_pattern: AnalyticsBucket[];
  by_confidence_bucket: AnalyticsBucket[];
  by_asset_class: AnalyticsBucket[];
  by_risk_regime: AnalyticsBucket[];
  execution_quality: {
    total_closed_trades: number;
    slippage_by_pair: Array<{
      pair: string;
      n: number;
      avg_pips: number;
      min_pips: number;
      max_pips: number;
    }>;
    close_reason_distribution: Array<{
      reason: string;
      count: number;
      pct: number;
      avg_pnl: number;
    }>;
  };
  signal_volume: {
    total_signals: number;
    verdict_take: number;
    verdict_skip: number;
    take_ratio_pct: number;
    last_30_days: Array<{ day: string; count: number }>;
  };
};

export type DriftResult = {
  window_days: number;
  threshold_pct: number;
  min_recent_trades: number;
  by_pair: Array<{
    key: string;
    recent_n: number;
    baseline_n: number;
    recent_win_rate_pct: number;
    baseline_win_rate_pct: number;
    delta_pct: number;
  }>;
  by_pattern: DriftResult["by_pair"];
};

export type PersonalTrade = {
  id: number;
  user: string;
  pair: string;
  direction: "buy" | "sell";
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  size_lot: number;
  status: "OPEN" | "CLOSED";
  exit_price: number | null;
  pnl: number | null;
  created_at: string;
  closed_at: string | null;
  mt5_ticket: number | null;
  is_auto: number;
  signal_id: number | null;
  fill_price: number | null;
  slippage_pips: number | null;
  close_reason: string | null;
};

export type WSMessage =
  | { type: "cockpit"; data: Cockpit }
  | { type: "signal"; data: unknown }
  | { type: "tick"; data: { pair: string; price: number; bid: number | null; ask: number | null; timestamp: string } }
  | { type: "update"; data: unknown }
  | { type: "pong" };
