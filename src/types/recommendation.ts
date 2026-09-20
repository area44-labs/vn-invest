export type MarketRegime = "STRONG_BULL" | "BULL" | "NEUTRAL" | "DEFENSIVE" | "BEAR" | "PANIC";

export type ActionType = "BUY" | "WATCH" | "HOLD" | "SELL" | "AVOID";

export type ExchangeType = "HOSE" | "HNX" | "UPCOM";

export type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | null;

export type DataQuality = "SUFFICIENT" | "PARTIAL" | "INSUFFICIENT";

export type DivergenceSignal = "BULLISH" | "BEARISH" | "NONE";

export interface MarketMetrics {
  vnindex_value: number | null;
  vnindex_change_pct: number | null;
  vn30_change_pct?: number | null;
  market_breadth_ratio?: number | null;
  volatility?: number | null;
  volume_20d_ratio?: number | null;
}

export interface MarketInfo {
  regime: MarketRegime;
  confidence: number | null;
  regime_score?: number | null;
  metrics: MarketMetrics;
}

export interface SummaryInfo {
  total_scanned: number;
  buy_count: number;
  watch_count: number;
  hold_count: number;
  sell_count: number;
  avoid_count: number;
}

export interface ExpectedReturn {
  expected_return_5d: number | null;
  expected_return_10d: number | null;
  expected_return_20d: number | null;
}

export interface RiskMetrics {
  var_t25: number | null;
  es_t25: number | null;
  volatility_60d: number | null;
  max_drawdown: number | null;
  liquidity_score: number | null;
  avg_value_20d?: number | null;
}

export interface TradePlan {
  current_price: number | null;
  entry_low: number | null;
  entry_high: number | null;
  stop_loss: number | null;
  tp1: number | null;
  tp2: number | null;
  risk_reward: number | null;
  position_percent: number | null;
}

export interface ScoreComponents {
  trend: number | null;
  momentum: number | null;
  volume: number | null;
  relative_strength: number | null;
  divergence: number | null;
}

export interface DivergenceDetails {
  "1H"?: DivergenceSignal;
  "1D"?: DivergenceSignal;
  "1W"?: DivergenceSignal;
  "1M"?: DivergenceSignal;
}

export interface Recommendation {
  symbol: string;
  company_name: string;
  exchange: ExchangeType;
  sector: string;
  action: ActionType;
  model_version?: string;
  data_quality?: DataQuality;
  data_as_of?: string | null;
  data_source?: string | null;
  signal_score: number | null;
  risk_adjusted_score: number | null;
  score_components?: ScoreComponents | null;
  confidence: number | null;
  risk_level: RiskLevel;
  expected_return: ExpectedReturn;
  risk_metrics: RiskMetrics;
  trade_plan: TradePlan;
  reasons: string[];
  warnings: string[];
  invalidation: string[];
  divergence?: DivergenceDetails | null;
}

export interface UniverseInfo {
  universe_type?: string;
  universe_size?: number;
}

export interface RecommendationsPayload {
  schema_version: "2.0";
  signal_model_version?: string;
  generated_at: string;
  data_as_of?: string | null;
  source_date: string | null;
  data_source?: string | null;
  universe_info?: UniverseInfo;
  market: MarketInfo;
  summary: SummaryInfo;
  recommendations: Recommendation[];
}

export interface MarketPayload {
  data_as_of?: string | null;
  source_date: string | null;
  generated_at: string;
  data_source?: string | null;
  universe_info?: UniverseInfo;
  market: MarketInfo;
  summary: SummaryInfo;
}

export interface HistoryIndexPayload {
  last_updated: string;
  total_reports: number;
  dates: string[];
}
