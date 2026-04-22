export interface Candle {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface EquityPoint {
  closed_at: string;
  pnl: number;
  cumulative_pnl: number;
  trade_num: number;
  pair?: string;
  direction?: Direction;
}

export interface EquityCurve {
  points: EquityPoint[];
  total_trades: number;
  final_pnl: number;
  since?: string;
}

export type Direction = 'buy' | 'sell';
export type VerdictAction = 'TAKE' | 'WAIT' | 'SKIP';
export type RiskRegime = 'risk_on' | 'risk_off' | 'neutral';
export type MacroDirection = 'up' | 'down' | 'neutral';
export type VixLevel = 'low' | 'normal' | 'elevated' | 'high';

export interface ConfidenceFactor {
  name: string;
  score: number;
  detail: string;
  positive: boolean;
  source?: string;
}

export interface TradeSetup {
  pair: string;
  direction: Direction;
  entry_price: number;
  stop_loss: number;
  take_profit_1: number;
  take_profit_2?: number;
  confidence_score: number;
  confidence_factors?: ConfidenceFactor[];
  verdict_action?: VerdictAction;
  verdict_summary?: string;
  verdict_reasons?: string[];
  verdict_warnings?: string[];
  verdict_blockers?: string[];
  is_simulated?: boolean;
  risk_reward_1?: number;
}

export interface MacroSnapshot {
  fetched_at: string;
  dxy: MacroDirection;
  spx: MacroDirection;
  vix_level: VixLevel;
  vix_value: number;
  us10y: MacroDirection;
  de10y: MacroDirection;
  oil: MacroDirection;
  nikkei: MacroDirection;
  gold: MacroDirection;
  risk_regime: RiskRegime;
}

export interface InsightsBucket {
  bucket: string;
  count: number;
  wins: number;
  win_rate: number;
  total_pnl: number;
  avg_pnl: number;
}

export interface InsightsPerformance {
  total_trades: number;
  win_rate?: number;
  total_pnl?: number;
  avg_pnl?: number;
  total_losses?: number;
  since?: string;
  message?: string;
  by_score_bucket?: InsightsBucket[];
  by_asset_class?: InsightsBucket[];
  by_direction?: InsightsBucket[];
  by_risk_regime?: InsightsBucket[];
  by_session?: InsightsBucket[];
  by_pair?: InsightsBucket[];
}

export interface User {
  username: string;
  email?: string;
}

export interface PersonalTrade {
  id: number;
  user: string;
  pair: string;
  direction: Direction;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  size_lot: number;
  signal_pattern?: string | null;
  signal_confidence?: number | null;
  checklist_passed?: number;
  notes?: string | null;
  status: 'OPEN' | 'CLOSED';
  exit_price?: number | null;
  pnl?: number | null;
  created_at: string;
  closed_at?: string | null;
  mt5_ticket?: number | null;
  is_auto?: number;
  context_macro?: string | null;
}

export type WSMessage =
  | { type: 'setups_update'; payload: TradeSetup[] }
  | { type: 'signal'; payload: unknown }
  | { type: 'cockpit'; payload: CockpitSnapshot }
  | { type: 'ping' | 'pong' };

export interface KillSwitchStatus {
  active: boolean;
  reason: string | null;
  manual_enabled: boolean;
  manual_reason: string | null;
  manual_set_at: string | null;
  auto_triggered_by_daily_loss: boolean;
  daily_loss_limit_pct: number | null;
}

export type AssetClass = 'forex' | 'metal' | 'crypto' | 'equity_index' | 'energy' | 'unknown';

export interface ActiveTrade {
  id: number;
  pair: string;
  asset_class: AssetClass;
  direction: Direction;
  entry_price: number;
  current_price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  size_lot: number;
  risk_money: number | null;
  notional: number;
  pnl_unrealized: number | null;
  pnl_pips: number | null;
  distance_to_sl_pct: number | null;
  distance_to_tp_pct: number | null;
  near_sl: boolean;
  duration_min: number | null;
  is_auto: boolean;
  mt5_ticket: number | null;
}

export interface DriftFinding {
  key: string;
  recent_n: number;
  baseline_n: number;
  recent_win_rate_pct: number;
  baseline_win_rate_pct: number;
  delta_pct: number;
}

export interface DriftReport {
  window_days?: number;
  threshold_pct?: number;
  min_recent_trades?: number;
  by_pair?: DriftFinding[];
  by_pattern?: DriftFinding[];
  error?: string;
}

export interface AnalyticsBreakdownRow {
  key: string;
  wins: number;
  losses: number;
  total: number;
  win_rate_pct: number;
}

export interface SlippageByPair {
  pair: string;
  n: number;
  avg_pips: number;
  min_pips: number;
  max_pips: number;
}

export interface CloseReasonRow {
  reason: string;
  count: number;
  pct: number;
  avg_pnl: number;
}

export interface ExecutionQuality {
  total_closed_trades: number;
  slippage_by_pair: SlippageByPair[];
  close_reason_distribution: CloseReasonRow[];
}

export interface SignalVolume {
  total_signals: number;
  verdict_take: number;
  verdict_skip: number;
  take_ratio_pct: number;
  last_30_days: Array<{ day: string; count: number }>;
}

export type PeriodKey = 'day' | 'week' | 'month' | 'year' | 'all';
export type Preset = PeriodKey | 'custom';
export type Granularity = '5min' | 'hour' | 'day' | 'month';

export interface PeriodTradeRef {
  pair: string;
  direction: Direction;
  pnl: number;
  closed_at: string;
}

export interface PeriodStats {
  period: Preset;
  from: string;
  to: string;
  pnl: number;
  pnl_pct: number;
  capital: number;
  capital_at_risk_now: number;
  n_trades: number;
  n_wins: number;
  n_losses: number;
  win_rate: number;
  avg_pnl_per_trade: number;
  profit_factor: number | null;
  expectancy: number;
  max_drawdown: number;
  best_trade: PeriodTradeRef | null;
  worst_trade: PeriodTradeRef | null;
  avg_duration_min: number | null;
  close_reasons: Record<string, number>;
  n_open: number;
}

export interface PnlBucket {
  bucket_start: string;
  bucket_end: string;
  pnl: number;
  cumulative_pnl: number;
  n_trades: number;
}

export interface PnlBucketsResponse {
  buckets: PnlBucket[];
  granularity_used: Granularity;
  total_trades: number;
  final_pnl: number;
  since: string;
  until: string;
}

export interface DrillSegment {
  label: string;
  start: string;
  end: string;
  granularity: Granularity;
}

export interface RejectionByReason {
  reason_code: string;
  label_fr: string;
  count: number;
  pairs: Record<string, number>;
  top_pair: string | null;
}

export interface RejectionByHour {
  hour: number;
  count: number;
}

export interface RejectionByReasonHour {
  reason_code: string;
  hour: number;
  count: number;
}

export interface ExposurePoint {
  bucket_time: string;
  capital_at_risk: number;
  n_open: number;
}

export interface ExposureTimeseries {
  points: ExposurePoint[];
  granularity_used: Granularity;
  peak_at_risk: number;
  avg_at_risk: number;
  max_open: number;
  since: string;
  until: string;
}

export interface BrokerAccount {
  configured: boolean;
  reachable: boolean;
  /** Champs bas seulement si reachable=true */
  login?: number;
  currency?: string;
  balance?: number;
  equity?: number;
  margin?: number;
  margin_free?: number;
  margin_level_pct?: number | null;
  leverage?: number;
  positions_count?: number;
  profit?: number;
  status?: number;
  error?: string;
}

export interface RejectionsReport {
  total: number;
  by_reason: RejectionByReason[];
  by_hour_utc: RejectionByHour[];
  by_reason_hour: RejectionByReasonHour[];
  since: string;
  until: string;
}

export interface MistakesReport {
  total_trades: number;
  without_checklist: { count: number; avg_pnl: number };
  without_sl_set: { count: number; avg_pnl: number };
  without_tp_set: { count: number; avg_pnl: number };
  with_checklist_avg_pnl: number;
}

export interface ComboRow {
  pattern: string;
  pair: string;
  wins: number;
  losses: number;
  total: number;
  win_rate_pct: number;
  total_pnl: number;
}

export interface CombosReport {
  min_trades_for_significance: number;
  combos: ComboRow[];
}

export interface AnalyticsReport {
  by_pair?: AnalyticsBreakdownRow[];
  by_hour_utc?: AnalyticsBreakdownRow[];
  by_pattern?: AnalyticsBreakdownRow[];
  by_confidence_bucket?: AnalyticsBreakdownRow[];
  by_asset_class?: AnalyticsBreakdownRow[];
  by_risk_regime?: AnalyticsBreakdownRow[];
  execution_quality?: ExecutionQuality;
  signal_volume?: SignalVolume;
  error?: string;
}

export interface CockpitAlert {
  level: 'critical' | 'warning' | 'info';
  code: string;
  msg: string;
}

export interface FearGreedSnapshot {
  recorded_at: string;
  value: number;
  classification: 'extreme_fear' | 'fear' | 'neutral' | 'greed' | 'extreme_greed';
}

export interface CotExtreme {
  pair: string;
  report_date: string;
  signals: Array<{
    actor: 'leveraged_funds' | 'non_reportables';
    z: number;
    interpretation: string;
  }>;
}

export interface CockpitSnapshot {
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
    items: unknown[];
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
  macro: MacroSnapshot | null;
  kill_switch: KillSwitchStatus;
  session: { label?: string; activity_multiplier?: number; is_weekend?: boolean };
  blackouts: Array<{ pair: string; reason: string }>;
  cot_extremes: CotExtreme[];
  fear_greed: FearGreedSnapshot | null;
  next_events: Array<{ time: string; currency: string; impact: string; event_name: string }>;
  alerts: CockpitAlert[];
}
