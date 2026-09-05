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
