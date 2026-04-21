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

export type WSMessage =
  | { type: 'setups_update'; payload: TradeSetup[] }
  | { type: 'signal'; payload: unknown }
  | { type: 'ping' | 'pong' };
