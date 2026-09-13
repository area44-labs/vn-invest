import type {
  HistoryIndexPayload,
  MarketPayload,
  Recommendation,
  RecommendationsPayload,
} from "@/types/recommendation";

function getBaseUrl(): string {
  const base = import.meta.env.BASE_URL || "/";
  return base.endsWith("/") ? base : `${base}/`;
}

/**
 * Reads local static JSON artifact from disk during SSG build,
 * or fetches via HTTP in browser runtime.
 */
async function loadArtifact<T>(relativePath: string): Promise<T | null> {
  if (import.meta.env.SSR) {
    try {
      const fsModule = "node:fs/promises";
      const pathModule = "node:path";
      const fs = await import(/* @vite-ignore */ fsModule);
      const path = await import(/* @vite-ignore */ pathModule);

      const filePath = path.join(process.cwd(), "public", relativePath);
      const content = await fs.readFile(filePath, "utf-8");
      return JSON.parse(content) as T;
    } catch (err) {
      console.error(
        `[SSG Fatal Error] Failed to read static artifact public/${relativePath}:`,
        err,
      );
      throw new Error(
        `[SSG Build Error] Required static artifact public/${relativePath} is missing or invalid: ${(err as Error).message}`,
      );
    }
  }

  const baseUrl = getBaseUrl();
  const url = `${baseUrl}${relativePath}`;

  try {
    const res = await fetch(url);
    if (res.ok) {
      return (await res.json()) as T;
    }
  } catch (err) {
    console.error(`Failed to fetch artifact ${url}:`, err);
  }
  return null;
}

/**
 * Fetches canonical recommendations JSON artifact.
 */
export async function loadRecommendations(): Promise<RecommendationsPayload | null> {
  const data = await loadArtifact<RecommendationsPayload>("generated/recommendations.json");
  if (data && data.recommendations) {
    return data;
  }
  return null;
}

/**
 * Fetches canonical market summary JSON artifact.
 */
export async function loadMarket(): Promise<MarketPayload | null> {
  const data = await loadArtifact<MarketPayload>("generated/market.json");
  if (data && data.market) {
    return data;
  }
  return null;
}

/**
 * Fetches history index JSON artifact.
 */
export async function loadHistoryIndex(): Promise<HistoryIndexPayload | null> {
  const data = await loadArtifact<HistoryIndexPayload>("generated/history/index.json");
  if (data && data.dates) {
    return data;
  }
  return null;
}

/**
 * Fetches historical recommendation report JSON artifact for a given date (YYYY-MM-DD).
 */
export async function loadHistoryReport(date: string): Promise<RecommendationsPayload | null> {
  if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return null;
  }
  const data = await loadArtifact<RecommendationsPayload>(`generated/history/${date}.json`);
  if (data && data.recommendations) {
    return data;
  }
  return null;
}

/**
 * Finds a single stock recommendation by symbol from canonical recommendations.
 */
export async function loadStock(symbol: string): Promise<Recommendation | null> {
  if (!symbol) return null;
  const payload = await loadRecommendations();
  if (!payload || !payload.recommendations) return null;

  const target = symbol.toUpperCase();
  return payload.recommendations.find((r) => r.symbol.toUpperCase() === target) || null;
}
