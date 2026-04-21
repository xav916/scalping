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
  | { type: 'ping' | 'pong' };
