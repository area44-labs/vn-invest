import type {
  ActionType,
  ExchangeType,
  HistoryIndexPayload,
  MarketInfo,
  MarketMetrics,
  MarketPayload,
  MarketRegime,
  Recommendation,
  RecommendationsPayload,
  RiskLevel,
  SummaryInfo,
  TradePlan,
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

function isNullableNumber(val: any): boolean {
  return val === null || val === undefined || typeof val === "number";
}

function isStringArray(arr: any): boolean {
  return Array.isArray(arr) && arr.every((x) => typeof x === "string");
}

function isMarketMetrics(obj: any): obj is MarketMetrics {
  if (!obj || typeof obj !== "object") return false;
  if (!isNullableNumber(obj.vnindex_value)) return false;
  if (!isNullableNumber(obj.vnindex_change_pct)) return false;
  if (!isNullableNumber(obj.vn30_change_pct)) return false;
  if (!isNullableNumber(obj.market_breadth_ratio)) return false;
  if (!isNullableNumber(obj.volatility)) return false;
  if (
    obj.volume_20d_ratio !== undefined &&
    obj.volume_20d_ratio !== null &&
    typeof obj.volume_20d_ratio !== "number" &&
    typeof obj.volume_20d_ratio !== "string"
  ) {
    return false;
  }
  return true;
}

function isMarketInfo(obj: any): obj is MarketInfo {
  if (!obj || typeof obj !== "object") return false;
  if (typeof obj.regime !== "string" || !VALID_MARKET_REGIMES.has(obj.regime)) return false;
  if (!isNullableNumber(obj.confidence)) return false;
  if (!isNullableNumber(obj.regime_score)) return false;
  if (!isMarketMetrics(obj.metrics)) return false;
  return true;
}

function isSummaryInfo(obj: any): obj is SummaryInfo {
  if (!obj || typeof obj !== "object") return false;
  if (typeof obj.total_scanned !== "number") return false;
  if (typeof obj.buy_count !== "number") return false;
  if (typeof obj.watch_count !== "number") return false;
  if (typeof obj.hold_count !== "number") return false;
  if (typeof obj.sell_count !== "number") return false;
  if (typeof obj.avoid_count !== "number") return false;
  return true;
}

function isTradePlan(obj: any): obj is TradePlan {
  if (!obj || typeof obj !== "object") return false;
  if (!isNullableNumber(obj.current_price)) return false;
  if (!isNullableNumber(obj.entry_low)) return false;
  if (!isNullableNumber(obj.entry_high)) return false;
  if (!isNullableNumber(obj.stop_loss)) return false;
  if (!isNullableNumber(obj.tp1)) return false;
  if (!isNullableNumber(obj.tp2)) return false;
  if (!isNullableNumber(obj.risk_reward)) return false;
  if (!isNullableNumber(obj.position_percent)) return false;
  return true;
}

function isRecommendation(obj: any): obj is Recommendation {
  if (!obj || typeof obj !== "object") return false;
  if (typeof obj.symbol !== "string" || obj.symbol.trim().length === 0) return false;
  if (typeof obj.company_name !== "string") return false;
  if (typeof obj.exchange !== "string" || !VALID_EXCHANGES.has(obj.exchange)) return false;
  if (typeof obj.sector !== "string") return false;
  if (typeof obj.action !== "string" || !VALID_ACTIONS.has(obj.action)) return false;
  if (!isNullableNumber(obj.signal_score)) return false;
  if (!isNullableNumber(obj.risk_adjusted_score)) return false;
  if (!isNullableNumber(obj.confidence)) return false;
  if (obj.risk_level !== undefined && !VALID_RISK_LEVELS.has(obj.risk_level)) return false;
  if (obj.trade_plan !== undefined && !isTradePlan(obj.trade_plan)) return false;
  if (obj.reasons !== undefined && !isStringArray(obj.reasons)) return false;
  if (obj.warnings !== undefined && !isStringArray(obj.warnings)) return false;
  if (obj.invalidation !== undefined && !isStringArray(obj.invalidation)) return false;
  return true;
}

export function isRecommendationsPayload(obj: any): obj is RecommendationsPayload {
  if (!obj || typeof obj !== "object") return false;
  if (obj.schema_version !== undefined && typeof obj.schema_version !== "string") return false;
  if (obj.generated_at !== undefined && typeof obj.generated_at !== "string") return false;
  if (
    obj.source_date !== undefined &&
    obj.source_date !== null &&
    typeof obj.source_date !== "string"
  )
    return false;
  if (!isMarketInfo(obj.market)) return false;
  if (obj.summary !== undefined && !isSummaryInfo(obj.summary)) return false;
  if (!Array.isArray(obj.recommendations)) return false;
  for (const rec of obj.recommendations) {
    if (!isRecommendation(rec)) return false;
  }
  return true;
}

export function isMarketPayload(obj: any): obj is MarketPayload {
  if (!obj || typeof obj !== "object") return false;
  if (obj.generated_at !== undefined && typeof obj.generated_at !== "string") return false;
  if (
    obj.source_date !== undefined &&
    obj.source_date !== null &&
    typeof obj.source_date !== "string"
  )
    return false;
  if (!isMarketInfo(obj.market)) return false;
  if (obj.summary !== undefined && !isSummaryInfo(obj.summary)) return false;
  return true;
}

export function isHistoryIndexPayload(obj: any): obj is HistoryIndexPayload {
  if (!obj || typeof obj !== "object") return false;
  if (obj.last_updated !== undefined && typeof obj.last_updated !== "string") return false;
  if (obj.total_reports !== undefined && typeof obj.total_reports !== "number") return false;
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
