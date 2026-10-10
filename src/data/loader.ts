import type {
  ActionType,
  DataQuality,
  DivergenceDetails,
  DivergenceSignal,
  ExchangeType,
  ExpectedReturn,
  HistoryIndexPayload,
  MarketInfo,
  MarketMetrics,
  MarketPayload,
  MarketRegime,
  Recommendation,
  RecommendationsPayload,
  RiskLevel,
  RiskMetrics,
  ScoreComponents,
  SummaryInfo,
  TradePlan,
  UniverseInfo,
} from "@/types/recommendation";

export type LoadResult<T> =
  | { status: "SUCCESS"; data: T }
  | { status: "NOT_FOUND" }
  | { status: "ERROR"; error: string };

const VALID_MARKET_REGIMES: Set<string> = new Set<MarketRegime>([
  "STRONG_BULL",
  "BULL",
  "DEFENSIVE",
  "BEAR",
  "PANIC",
]);

const VALID_ACTIONS: Set<string> = new Set<ActionType>(["BUY", "WATCH", "HOLD", "SELL", "AVOID"]);

const VALID_EXCHANGES: Set<string> = new Set<ExchangeType>(["HOSE", "HNX", "UPCOM"]);

const VALID_RISK_LEVELS: Set<string | null> = new Set<RiskLevel>(["LOW", "MEDIUM", "HIGH", null]);

const VALID_DATA_QUALITY: Set<string> = new Set<DataQuality>([
  "SUFFICIENT",
  "PARTIAL",
  "INSUFFICIENT",
]);

const VALID_DIVERGENCE_SIGNALS: Set<string> = new Set<DivergenceSignal>([
  "BULLISH",
  "BEARISH",
  "NONE",
]);

const ALLOWED_RECOMMENDATIONS_PAYLOAD_KEYS = new Set([
  "schema_version",
  "signal_model_version",
  "quant_version",
  "config_hash",
  "generated_at",
  "data_as_of",
  "source_date",
  "data_source",
  "universe_info",
  "market",
  "summary",
  "recommendations",
]);

const ALLOWED_MARKET_PAYLOAD_KEYS = new Set([
  "data_as_of",
  "source_date",
  "generated_at",
  "data_source",
  "universe_info",
  "market",
  "summary",
]);

const ALLOWED_MARKET_INFO_KEYS = new Set(["regime", "confidence", "regime_score", "metrics"]);

const ALLOWED_MARKET_METRICS_KEYS = new Set([
  "vnindex_value",
  "vnindex_change_pct",
  "vn30_change_pct",
  "market_breadth_ratio",
  "volatility",
  "volume_20d_ratio",
]);

const ALLOWED_SUMMARY_INFO_KEYS = new Set([
  "total_scanned",
  "buy_count",
  "watch_count",
  "hold_count",
  "sell_count",
  "avoid_count",
]);

const ALLOWED_RECOMMENDATION_KEYS = new Set([
  "symbol",
  "company_name",
  "exchange",
  "sector",
  "action",
  "model_version",
  "quant_version",
  "config_hash",
  "data_quality",
  "data_quality_issues",
  "data_as_of",
  "data_source",
  "signal_score",
  "risk_adjusted_score",
  "score_components",
  "confidence",
  "risk_level",
  "expected_return",
  "risk_metrics",
  "trade_plan",
  "reasons",
  "warnings",
  "invalidation",
  "divergence",
]);

const ALLOWED_EXPECTED_RETURN_KEYS = new Set([
  "expected_return_5d",
  "expected_return_10d",
  "expected_return_20d",
]);

const ALLOWED_RISK_METRICS_KEYS = new Set([
  "var_t25",
  "es_t25",
  "volatility_60d",
  "max_drawdown",
  "liquidity_score",
  "avg_value_20d",
]);

const ALLOWED_TRADE_PLAN_KEYS = new Set([
  "current_price",
  "entry_low",
  "entry_high",
  "stop_loss",
  "tp1",
  "tp2",
  "risk_reward",
  "position_percent",
]);

const ALLOWED_SCORE_COMPONENTS_KEYS = new Set([
  "trend",
  "momentum",
  "volume",
  "relative_strength",
  "divergence",
]);

const ALLOWED_DIVERGENCE_KEYS = new Set(["1H", "1D", "1W", "1M"]);

const ALLOWED_UNIVERSE_INFO_KEYS = new Set(["universe_type", "universe_size"]);

const ALLOWED_HISTORY_INDEX_KEYS = new Set(["last_updated", "total_reports", "dates"]);

function hasOnlyAllowedKeys(obj: object, allowedKeys: Set<string>): boolean {
  for (const key of Object.keys(obj)) {
    if (!allowedKeys.has(key)) return false;
  }
  return true;
}

function isFiniteNumber(val: any): boolean {
  return typeof val === "number" && Number.isFinite(val) && !Number.isNaN(val);
}

function isNonNegativeInteger(val: any): boolean {
  return typeof val === "number" && Number.isInteger(val) && val >= 0;
}

function isRequiredNullableFiniteNumber(val: any, min?: number, max?: number): boolean {
  if (val === undefined) return false;
  if (val === null) return true;
  if (!isFiniteNumber(val)) return false;
  if (min !== undefined && val < min) return false;
  if (max !== undefined && val > max) return false;
  return true;
}

function isOptionalNullableFiniteNumber(val: any, min?: number, max?: number): boolean {
  if (val === undefined || val === null) return true;
  if (!isFiniteNumber(val)) return false;
  if (min !== undefined && val < min) return false;
  if (max !== undefined && val > max) return false;
  return true;
}

function isRequiredNullableString(val: any): boolean {
  return val !== undefined && (val === null || typeof val === "string");
}

function isOptionalNullableString(val: any): boolean {
  return val === undefined || val === null || typeof val === "string";
}

function isStringArray(arr: any): boolean {
  return Array.isArray(arr) && arr.every((x) => typeof x === "string");
}

function isMarketMetrics(obj: any): obj is MarketMetrics {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return false;
  if (!hasOnlyAllowedKeys(obj, ALLOWED_MARKET_METRICS_KEYS)) return false;
  if (!isRequiredNullableFiniteNumber(obj.vnindex_value)) return false;
  if (!isRequiredNullableFiniteNumber(obj.vnindex_change_pct)) return false;
  if (!isOptionalNullableFiniteNumber(obj.vn30_change_pct)) return false;
  if (!isOptionalNullableFiniteNumber(obj.market_breadth_ratio, 0.0, 1.0)) return false;
  if (!isOptionalNullableFiniteNumber(obj.volatility)) return false;
  if (!isOptionalNullableFiniteNumber(obj.volume_20d_ratio)) return false;
  return true;
}

function isMarketInfo(obj: any): obj is MarketInfo {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return false;
  if (!hasOnlyAllowedKeys(obj, ALLOWED_MARKET_INFO_KEYS)) return false;
  if (typeof obj.regime !== "string" || !VALID_MARKET_REGIMES.has(obj.regime)) return false;
  if (!isRequiredNullableFiniteNumber(obj.confidence, 0.0, 1.0)) return false;
  if (!isOptionalNullableFiniteNumber(obj.regime_score, 0.0, 100.0)) return false;
  if (!isMarketMetrics(obj.metrics)) return false;
  return true;
}

function isSummaryInfo(obj: any): obj is SummaryInfo {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return false;
  if (!hasOnlyAllowedKeys(obj, ALLOWED_SUMMARY_INFO_KEYS)) return false;
  if (!isNonNegativeInteger(obj.total_scanned)) return false;
  if (!isNonNegativeInteger(obj.buy_count)) return false;
  if (!isNonNegativeInteger(obj.watch_count)) return false;
  if (!isNonNegativeInteger(obj.hold_count)) return false;
  if (!isNonNegativeInteger(obj.sell_count)) return false;
  if (!isNonNegativeInteger(obj.avoid_count)) return false;
  return true;
}

function isExpectedReturn(obj: any): obj is ExpectedReturn {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return false;
  if (!hasOnlyAllowedKeys(obj, ALLOWED_EXPECTED_RETURN_KEYS)) return false;
  if (!isRequiredNullableFiniteNumber(obj.expected_return_5d)) return false;
  if (!isRequiredNullableFiniteNumber(obj.expected_return_10d)) return false;
  if (!isRequiredNullableFiniteNumber(obj.expected_return_20d)) return false;
  return true;
}

function isRiskMetrics(obj: any): obj is RiskMetrics {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return false;
  if (!hasOnlyAllowedKeys(obj, ALLOWED_RISK_METRICS_KEYS)) return false;
  if (!isRequiredNullableFiniteNumber(obj.var_t25)) return false;
  if (!isRequiredNullableFiniteNumber(obj.es_t25)) return false;
  if (!isRequiredNullableFiniteNumber(obj.volatility_60d)) return false;
  if (!isRequiredNullableFiniteNumber(obj.max_drawdown)) return false;
  if (!isRequiredNullableFiniteNumber(obj.liquidity_score, 0.0, 100.0)) return false;
  if (!isOptionalNullableFiniteNumber(obj.avg_value_20d)) return false;
  return true;
}

function isTradePlan(obj: any): obj is TradePlan {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return false;
  if (!hasOnlyAllowedKeys(obj, ALLOWED_TRADE_PLAN_KEYS)) return false;
  if (!isRequiredNullableFiniteNumber(obj.current_price)) return false;
  if (!isRequiredNullableFiniteNumber(obj.entry_low)) return false;
  if (!isRequiredNullableFiniteNumber(obj.entry_high)) return false;
  if (!isRequiredNullableFiniteNumber(obj.stop_loss)) return false;
  if (!isRequiredNullableFiniteNumber(obj.tp1)) return false;
  if (!isRequiredNullableFiniteNumber(obj.tp2)) return false;
  if (!isRequiredNullableFiniteNumber(obj.risk_reward)) return false;
  if (!isRequiredNullableFiniteNumber(obj.position_percent, 0.0, 100.0)) return false;
  return true;
}

function isScoreComponents(obj: any): obj is ScoreComponents {
  if (obj === null || obj === undefined) return true;
  if (typeof obj !== "object" || Array.isArray(obj)) return false;
  if (!hasOnlyAllowedKeys(obj, ALLOWED_SCORE_COMPONENTS_KEYS)) return false;
  if (!isOptionalNullableFiniteNumber(obj.trend)) return false;
  if (!isOptionalNullableFiniteNumber(obj.momentum)) return false;
  if (!isOptionalNullableFiniteNumber(obj.volume)) return false;
  if (!isOptionalNullableFiniteNumber(obj.relative_strength)) return false;
  if (!isOptionalNullableFiniteNumber(obj.divergence)) return false;
  return true;
}

function isDivergenceDetails(obj: any): obj is DivergenceDetails {
  if (obj === null || obj === undefined) return true;
  if (typeof obj !== "object" || Array.isArray(obj)) return false;
  if (!hasOnlyAllowedKeys(obj, ALLOWED_DIVERGENCE_KEYS)) return false;
  for (const k of ["1H", "1D", "1W", "1M"]) {
    if (
      obj[k] !== undefined &&
      (typeof obj[k] !== "string" || !VALID_DIVERGENCE_SIGNALS.has(obj[k]))
    ) {
      return false;
    }
  }
  return true;
}

function isUniverseInfo(obj: any): obj is UniverseInfo {
  if (obj === undefined) return true;
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return false;
  if (!hasOnlyAllowedKeys(obj, ALLOWED_UNIVERSE_INFO_KEYS)) return false;
  if (obj.universe_type !== undefined && typeof obj.universe_type !== "string") return false;
  if (obj.universe_size !== undefined && !isNonNegativeInteger(obj.universe_size)) return false;
  return true;
}

function isRecommendation(obj: any): obj is Recommendation {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return false;
  if (!hasOnlyAllowedKeys(obj, ALLOWED_RECOMMENDATION_KEYS)) return false;

  if (typeof obj.symbol !== "string" || obj.symbol.trim().length === 0) return false;
  if (typeof obj.company_name !== "string") return false;
  if (typeof obj.exchange !== "string" || !VALID_EXCHANGES.has(obj.exchange)) return false;
  if (typeof obj.sector !== "string") return false;
  if (typeof obj.action !== "string" || !VALID_ACTIONS.has(obj.action)) return false;

  if (obj.model_version !== undefined && typeof obj.model_version !== "string") return false;
  if (obj.quant_version !== undefined && typeof obj.quant_version !== "string") return false;
  if (obj.config_hash !== undefined && typeof obj.config_hash !== "string") return false;
  if (
    obj.data_quality !== undefined &&
    (typeof obj.data_quality !== "string" || !VALID_DATA_QUALITY.has(obj.data_quality))
  ) {
    return false;
  }
  if (obj.data_quality_issues !== undefined && !isStringArray(obj.data_quality_issues)) {
    return false;
  }

  if (!isOptionalNullableString(obj.data_as_of)) return false;
  if (!isOptionalNullableString(obj.data_source)) return false;

  if (!isRequiredNullableFiniteNumber(obj.signal_score, 0.0, 100.0)) return false;
  if (!isRequiredNullableFiniteNumber(obj.risk_adjusted_score, 0.0, 100.0)) return false;
  if (!isScoreComponents(obj.score_components)) return false;
  if (!isRequiredNullableFiniteNumber(obj.confidence, 0.0, 1.0)) return false;

  if (obj.risk_level === undefined || !VALID_RISK_LEVELS.has(obj.risk_level)) return false;

  if (!isExpectedReturn(obj.expected_return)) return false;
  if (!isRiskMetrics(obj.risk_metrics)) return false;
  if (!isTradePlan(obj.trade_plan)) return false;

  if (!isStringArray(obj.reasons)) return false;
  if (!isStringArray(obj.warnings)) return false;
  if (!isStringArray(obj.invalidation)) return false;
  if (!isDivergenceDetails(obj.divergence)) return false;

  return true;
}

export function isRecommendationsPayload(obj: any): obj is RecommendationsPayload {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return false;
  if (!hasOnlyAllowedKeys(obj, ALLOWED_RECOMMENDATIONS_PAYLOAD_KEYS)) return false;

  if (typeof obj.schema_version !== "string" || obj.schema_version !== "2.0") return false;
  if (typeof obj.signal_model_version !== "string") return false;
  if (obj.quant_version !== undefined && typeof obj.quant_version !== "string") return false;
  if (obj.config_hash !== undefined && typeof obj.config_hash !== "string") return false;

  if (typeof obj.generated_at !== "string") return false;
  if (!isRequiredNullableString(obj.data_as_of)) return false;
  if (!isRequiredNullableString(obj.source_date)) return false;
  if (!isOptionalNullableString(obj.data_source)) return false;

  if (!isUniverseInfo(obj.universe_info)) return false;
  if (!isMarketInfo(obj.market)) return false;
  if (!isSummaryInfo(obj.summary)) return false;

  if (!Array.isArray(obj.recommendations)) return false;
  for (const rec of obj.recommendations) {
    if (!isRecommendation(rec)) return false;
  }
  return true;
}

export function isMarketPayload(obj: any): obj is MarketPayload {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return false;
  if (!hasOnlyAllowedKeys(obj, ALLOWED_MARKET_PAYLOAD_KEYS)) return false;

  if (!isOptionalNullableString(obj.data_as_of)) return false;
  if (!isRequiredNullableString(obj.source_date)) return false;
  if (typeof obj.generated_at !== "string") return false;
  if (!isOptionalNullableString(obj.data_source)) return false;

  if (!isUniverseInfo(obj.universe_info)) return false;
  if (!isMarketInfo(obj.market)) return false;
  if (!isSummaryInfo(obj.summary)) return false;

  return true;
}

export function isHistoryIndexPayload(obj: any): obj is HistoryIndexPayload {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return false;
  if (!hasOnlyAllowedKeys(obj, ALLOWED_HISTORY_INDEX_KEYS)) return false;

  if (typeof obj.last_updated !== "string") return false;
  if (!isNonNegativeInteger(obj.total_reports)) return false;
  if (!Array.isArray(obj.dates)) return false;
  for (const d of obj.dates) {
    if (typeof d !== "string" || d.trim().length === 0) return false;
  }
  return true;
}

function getBaseUrl(): string {
  const base = import.meta.env.BASE_URL || "/";
  return base.endsWith("/") ? base : `${base}/`;
}

/**
 * Reads local static JSON artifact from disk during SSG build,
 * or fetches via HTTP in browser runtime, returning a typed LoadResult.
 */
async function loadArtifactResult<T>(relativePath: string): Promise<LoadResult<T>> {
  if (import.meta.env.SSR) {
    try {
      const fsModule = "node:fs/promises";
      const pathModule = "node:path";
      const fs = await import(/* @vite-ignore */ fsModule);
      const path = await import(/* @vite-ignore */ pathModule);

      const filePath = path.join(process.cwd(), relativePath);
      try {
        const content = await fs.readFile(filePath, "utf-8");
        const data = JSON.parse(content) as T;
        return { status: "SUCCESS", data };
      } catch (err: any) {
        if (err?.code === "ENOENT") {
          return { status: "NOT_FOUND" };
        }
        console.error(`[SSG Fatal Error] Failed to read static artifact ${relativePath}:`, err);
        throw new Error(
          `[SSG Build Error] Required static artifact ${relativePath} is invalid: ${(err as Error).message}`,
        );
      }
    } catch (err: any) {
      if (err.message?.startsWith("[SSG Build Error]")) {
        throw err;
      }
      return { status: "ERROR", error: (err as Error).message || "SSG artifact read error" };
    }
  }

  const baseUrl = getBaseUrl();
  const url = `${baseUrl}${relativePath}`;

  try {
    const res = await fetch(url);
    if (res.status === 404) {
      return { status: "NOT_FOUND" };
    }
    if (!res.ok) {
      return {
        status: "ERROR",
        error: `HTTP ${res.status}: ${res.statusText || "Request failed"}`,
      };
    }
    try {
      const data = (await res.json()) as T;
      return { status: "SUCCESS", data };
    } catch (err) {
      return {
        status: "ERROR",
        error: `Failed to parse JSON response: ${(err as Error).message}`,
      };
    }
  } catch (err) {
    return {
      status: "ERROR",
      error: `Network or fetch error: ${(err as Error).message}`,
    };
  }
}

/**
 * Fetches canonical recommendations JSON artifact as LoadResult.
 */
export async function loadRecommendationsResult(): Promise<LoadResult<RecommendationsPayload>> {
  const result = await loadArtifactResult<unknown>("generated/recommendations.json");
  if (result.status !== "SUCCESS") return result;
  if (!isRecommendationsPayload(result.data)) {
    return { status: "ERROR", error: "Malformed payload: invalid recommendations schema" };
  }
  return { status: "SUCCESS", data: result.data };
}

/**
 * Fetches canonical market summary JSON artifact as LoadResult.
 */
export async function loadMarketResult(): Promise<LoadResult<MarketPayload>> {
  const result = await loadArtifactResult<unknown>("generated/market.json");
  if (result.status !== "SUCCESS") return result;
  if (!isMarketPayload(result.data)) {
    return { status: "ERROR", error: "Malformed payload: invalid market schema" };
  }
  return { status: "SUCCESS", data: result.data };
}

/**
 * Fetches history index JSON artifact as LoadResult.
 */
export async function loadHistoryIndexResult(): Promise<LoadResult<HistoryIndexPayload>> {
  const result = await loadArtifactResult<unknown>("generated/history/index.json");
  if (result.status !== "SUCCESS") return result;
  if (!isHistoryIndexPayload(result.data)) {
    return { status: "ERROR", error: "Malformed payload: invalid history index schema" };
  }
  return { status: "SUCCESS", data: result.data };
}

/**
 * Fetches historical recommendation report JSON artifact for a given date (YYYY-MM-DD) as LoadResult.
 */
export async function loadHistoryReportResult(
  date: string,
): Promise<LoadResult<RecommendationsPayload>> {
  if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return { status: "NOT_FOUND" };
  }
  const result = await loadArtifactResult<unknown>(`generated/history/${date}.json`);
  if (result.status !== "SUCCESS") return result;
  if (!isRecommendationsPayload(result.data)) {
    return { status: "ERROR", error: "Malformed payload: invalid history report schema" };
  }
  return { status: "SUCCESS", data: result.data };
}

/**
 * Finds a single stock recommendation by symbol as LoadResult.
 */
export async function loadStockResult(symbol: string): Promise<LoadResult<Recommendation>> {
  if (!symbol) {
    return { status: "NOT_FOUND" };
  }
  const recsResult = await loadRecommendationsResult();
  if (recsResult.status === "NOT_FOUND") {
    return { status: "NOT_FOUND" };
  }
  if (recsResult.status === "ERROR") {
    return { status: "ERROR", error: recsResult.error };
  }

  const target = symbol.toUpperCase();
  const stock = recsResult.data.recommendations.find((r) => r.symbol.toUpperCase() === target);
  if (!stock) {
    return { status: "NOT_FOUND" };
  }
  return { status: "SUCCESS", data: stock };
}

// Backward-compatibility wrappers returning T | null
export async function loadRecommendations(): Promise<RecommendationsPayload | null> {
  const res = await loadRecommendationsResult();
  return res.status === "SUCCESS" ? res.data : null;
}

export async function loadMarket(): Promise<MarketPayload | null> {
  const res = await loadMarketResult();
  return res.status === "SUCCESS" ? res.data : null;
}

export async function loadHistoryIndex(): Promise<HistoryIndexPayload | null> {
  const res = await loadHistoryIndexResult();
  return res.status === "SUCCESS" ? res.data : null;
}

export async function loadHistoryReport(date: string): Promise<RecommendationsPayload | null> {
  const res = await loadHistoryReportResult(date);
  return res.status === "SUCCESS" ? res.data : null;
}

export async function loadStock(symbol: string): Promise<Recommendation | null> {
  const res = await loadStockResult(symbol);
  return res.status === "SUCCESS" ? res.data : null;
}
