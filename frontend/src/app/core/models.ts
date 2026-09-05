export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface User {
  id: string;
  email: string;
  display_name: string | null;
  is_active: boolean;
  telegram_chat_id: string | null;
}

export interface HealthStatus {
  status: 'ok' | 'degraded' | 'down';
  version: string;
  checks: Record<string, string>;
}

export interface Instrument {
  id: string;
  symbol: string;
  name: string;
  sector: string | null;
  exchange: string;
  is_synthetic: boolean;
  is_tradable: boolean;
  beta: number | null;
  annual_vol: number | null;
  shares_outstanding: number | null;
  listed_on: string | null;
}

export interface Bar {
  ts: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: number;
}

export interface NewsItem {
  id: string;
  published_at: string;
  headline: string;
  category: string;
  sentiment: number;
  source: string;
}

export interface CorporateEvent {
  id: string;
  event_type: string;
  occurs_at: string;
  eps_estimate: string | null;
  eps_actual: string | null;
  amount: string | null;
  note: string | null;
}

export interface Mover {
  symbol: string;
  sector: string | null;
  close: number;
  change_pct: number;
  volume: number;
  relative_volume: number;
}

export interface SectorPerf {
  sector: string;
  constituents: number;
  return_pct: number;
  median_return_pct: number;
  advancers: number;
  decliners: number;
}

export interface MarketOverview {
  as_of: string;
  index: { value: number; change_pct: number; regime: string | null };
  breadth: {
    advancers: number;
    decliners: number;
    unchanged: number;
    new_highs: number;
    new_lows: number;
    pct_above_50dma: number;
  };
  total_volume: number;
  sectors: SectorPerf[];
  gainers: Mover[];
  losers: Mover[];
  most_active: Mover[];
}

export interface IndexPoint {
  ts: string;
  index_value: number;
  index_return_pct: number;
  advancers: number;
  decliners: number;
  new_highs: number;
  new_lows: number;
  pct_above_50dma: number;
  total_volume: number;
  regime: string | null;
}

export interface InstrumentStats {
  symbol: string;
  lookback_days: number;
  last: number;
  period_return_pct: number;
  annualised_return_pct: number;
  annualised_vol_pct: number;
  sharpe: number | null;
  max_drawdown_pct: number;
  current_drawdown_pct: number;
  best_day_pct: number;
  worst_day_pct: number;
  up_day_pct: number;
  avg_volume: number;
}

export interface TradingAccount {
  id: string;
  broker: string;
  currency: string;
  starting_cash: string;
  cash: string;
  equity: string;
  is_halted: boolean;
  halt_reason: string | null;
  total_return_pct: number | null;
  open_positions: number;
}

export interface PositionRow {
  id: string;
  symbol: string | null;
  quantity: number;
  avg_cost: string;
  realised_pnl: string;
  total_commission: string;
  opened_at: string | null;
  last_price: string | null;
  market_value: string | null;
  unrealised_pnl: string | null;
  unrealised_pct: number | null;
}

export interface OrderRow {
  id: string;
  client_order_id: string;
  symbol: string | null;
  side: string;
  order_type: string;
  quantity: number;
  status: string;
  filled_quantity: number;
  avg_fill_price: string | null;
  commission: string;
  reject_reason: string | null;
  note: string | null;
  created_at: string;
}

export interface AgentRunRow {
  id: string;
  trigger: string;
  status: string;
  started_at: string;
  duration_ms: number | null;
  symbols_examined: number;
  intents_formed: number;
  orders_placed: number;
  denials: number;
  error: string | null;
}

export interface DecisionRow {
  at?: string;
  symbol: string;
  direction: string;
  approved: boolean;
  quantity?: number;
  approved_quantity?: number;
  requested_quantity?: number;
  conviction: number;
  denial: string | null;
  rationale: string;
  risk_trace?: { verdict?: string; checks?: RiskCheck[] };
  context?: Record<string, unknown>;
  signals?: Record<string, unknown>;
}

export interface RiskCheck {
  check: string;
  passed: boolean;
  detail: string;
  denial: string | null;
  adjusted_quantity: number | null;
}

export interface Reconciliation {
  reconciled: boolean;
  cash_stored: string;
  cash_from_fills: string;
  cash_difference: string;
  position_mismatches: { symbol: string; stored_quantity: number; expected_quantity: number }[];
}

export interface NotificationRow {
  at: string;
  event: string;
  severity: string;
  channel: string;
  status: string;
  title: string;
  body: string;
  error: string | null;
}

export interface TelegramStatus {
  bot_configured: boolean;
  bot_username: string | null;
  linked: boolean;
}

export interface Policy {
  id: string;
  version: number;
  risk_profile: string;
  autonomy_level: string;
  max_position_pct: string;
  max_sector_pct: string;
  cash_floor_pct: string;
  stop_loss_pct: string;
  take_profit_pct: string;
  max_daily_loss_pct: string;
  max_drawdown_pct: string;
  max_trades_per_day: number;
  max_trades_per_symbol_per_day: number;
  auto_approve_below: string;
  avoid_earnings: boolean;
  allow_shorting: boolean;
}

export type PolicyUpdate = Partial<
  Omit<Policy, 'id' | 'version' | 'auto_approve_below'>
>;

export interface WatchlistRow {
  id: string;
  symbol: string | null;
  name: string | null;
  sector: string | null;
  conviction: number;
  is_favourite: boolean;
  last_price: string | null;
}
