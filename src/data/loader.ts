import type {
  HistoryIndexPayload,
  MarketPayload,
  Recommendation,
  RecommendationsPayload,
} from "@/types/recommendation";

export type LoadResult<T> =
  | { status: "SUCCESS"; data: T }
  | { status: "NOT_FOUND" }
  | { status: "ERROR"; error: string };

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
  const result = await loadArtifactResult<RecommendationsPayload>("generated/recommendations.json");
  if (result.status === "SUCCESS" && (!result.data || !result.data.recommendations)) {
    return { status: "ERROR", error: "Malformed recommendations payload" };
  }
  return result;
}

/**
 * Fetches canonical market summary JSON artifact as LoadResult.
 */
export async function loadMarketResult(): Promise<LoadResult<MarketPayload>> {
  const result = await loadArtifactResult<MarketPayload>("generated/market.json");
  if (result.status === "SUCCESS" && (!result.data || !result.data.market)) {
    return { status: "ERROR", error: "Malformed market payload" };
  }
  return result;
}

/**
 * Fetches history index JSON artifact as LoadResult.
 */
export async function loadHistoryIndexResult(): Promise<LoadResult<HistoryIndexPayload>> {
  const result = await loadArtifactResult<HistoryIndexPayload>("generated/history/index.json");
  if (result.status === "SUCCESS" && (!result.data || !result.data.dates)) {
    return { status: "ERROR", error: "Malformed history index payload" };
  }
  return result;
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
  const result = await loadArtifactResult<RecommendationsPayload>(`generated/history/${date}.json`);
  if (result.status === "SUCCESS" && (!result.data || !result.data.recommendations)) {
    return { status: "ERROR", error: "Malformed history report payload" };
  }
  return result;
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
