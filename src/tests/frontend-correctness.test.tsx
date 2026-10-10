import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vite-plus/test";

import { MarketSummary } from "@/components/market-summary";
import {
  isRecommendationsPayload,
  loadHistoryIndexResult,
  loadHistoryReportResult,
  loadMarketResult,
} from "@/data/loader";
import { formatDate } from "@/lib/format";
import { Dashboard } from "@/pages/dashboard";
import { History } from "@/pages/history";
import { StockDetail } from "@/pages/stock-detail";

// Mock TanStack Router
vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, to, params, className }: any) => (
    <a href={to} data-params={JSON.stringify(params)} className={className}>
      {children}
    </a>
  ),
  useNavigate: () => vi.fn<() => void>(),
}));

async function waitTicks() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 50));
  });
}

function getValidRecommendationSample(overrides: Record<string, any> = {}) {
  return {
    symbol: "FPT",
    company_name: "FPT Corp",
    exchange: "HOSE",
    sector: "Technology",
    action: "BUY",
    signal_score: 90,
    risk_adjusted_score: 80,
    confidence: 0.9,
    risk_level: "LOW",
    expected_return: {
      expected_return_5d: 0.05,
      expected_return_10d: 0.1,
      expected_return_20d: 0.15,
    },
    risk_metrics: {
      var_t25: -0.04,
      es_t25: -0.06,
      volatility_60d: 0.2,
      max_drawdown: -0.15,
      liquidity_score: 85,
    },
    trade_plan: {
      current_price: 130000,
      entry_low: 125000,
      entry_high: 128000,
      stop_loss: 120000,
      tp1: 140000,
      tp2: 150000,
      risk_reward: 2,
      position_percent: 10,
    },
    reasons: ["Strong growth"],
    warnings: [],
    invalidation: [],
    ...overrides,
  };
}

function getValidRecommendationsPayloadSample(overrides: Record<string, any> = {}) {
  return {
    schema_version: "2.0",
    generated_at: "2026-10-09T16:00:00Z",
    data_as_of: "2026-10-09",
    source_date: "2026-10-09",
    market: {
      regime: "PANIC",
      confidence: 0.85,
      metrics: { vnindex_value: 1250, vnindex_change_pct: -0.5 },
    },
    summary: {
      total_scanned: 1,
      buy_count: 1,
      watch_count: 0,
      hold_count: 0,
      sell_count: 0,
      avoid_count: 0,
    },
    recommendations: [getValidRecommendationSample()],
    ...overrides,
  };
}

describe("Frontend Data Correctness & Market Metrics", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    vi.restoreAllMocks();
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
  });

  describe("MarketSummary correctness", () => {
    it("never presents confidence and breadth as price changes", () => {
      const sampleMarketData = {
        vnIndex: {
          name: "VN-INDEX",
          value: 1250.5,
          changePercent: -0.5,
          volumeRatio: "1.2x MA20",
        },
        regimeStatus: {
          name: "TRẠNG THÁI THỊ TRƯỜNG",
          regime: "PANIC",
          regimeScore: 7.0,
          confidence: 0.85,
        },
        breadth: {
          name: "BREADTH (>MA20)",
          breadthRatio: 0.24,
          description: "Tỉ lệ mã CP > MA20",
        },
        totalStocks: {
          name: "TỔNG SỐ MÃ SCANNED",
          totalScanned: 42,
          summaryText: "0 MUA / 42 BÁN",
        },
      };

      act(() => {
        root.render(<MarketSummary marketData={sampleMarketData} />);
      });

      const text = container.textContent || "";
      expect(text).toContain("-0.50%");
      expect(text).toContain("Độ tin cậy 85%");
      expect(text).not.toContain("+85.00%");
      expect(text).toContain("24.0%");
      expect(text).not.toContain("+24.00%");
    });
  });

  describe("Dashboard error, missing data, market.json fallback, and retry behavior", () => {
    it("displays distinct NOT_FOUND vs ERROR states and recovers on retry", async () => {
      let callCount = 0;
      vi.spyOn(window, "fetch").mockImplementation((url: RequestInfo | URL) => {
        callCount++;
        const urlStr = String(url);
        if (callCount === 1) {
          // First attempt: return 500 error for recommendations
          return Promise.resolve(
            new Response("Internal Error", { status: 500, statusText: "Internal Error" }),
          );
        }
        // Second attempt (retry): return valid recommendations and market payloads
        if (urlStr.includes("recommendations.json")) {
          return Promise.resolve(
            new Response(JSON.stringify(getValidRecommendationsPayloadSample()), { status: 200 }),
          );
        }
        return Promise.resolve(
          new Response(
            JSON.stringify({
              generated_at: "2026-10-09T16:00:00Z",
              source_date: "2026-10-09",
              market: {
                regime: "PANIC",
                confidence: 0.85,
                metrics: { vnindex_value: 1250, vnindex_change_pct: -0.5 },
              },
              summary: {
                total_scanned: 1,
                buy_count: 1,
                watch_count: 0,
                hold_count: 0,
                sell_count: 0,
                avoid_count: 0,
              },
            }),
            { status: 200 },
          ),
        );
      });

      // Render initially without initialRecsResult to trigger fetch
      act(() => {
        root.render(<Dashboard />);
      });
      await waitTicks();

      // Should display ERROR state with retry button
      expect(container.textContent).toContain("Lỗi tải dữ liệu khuyến nghị");
      const retryBtn = container.querySelector("button");
      expect(retryBtn).not.toBeNull();
      expect(retryBtn!.textContent).toContain("Thử lại");

      // Click retry
      act(() => {
        retryBtn!.click();
      });
      await waitTicks();

      // Should recover and display FPT recommendation
      expect(container.textContent).toContain("FPT");
      expect(container.textContent).toContain("FPT Corp");
    });

    it("displays error state when recommendations payload is malformed schema", async () => {
      vi.spyOn(window, "fetch").mockImplementation(() =>
        Promise.resolve(
          new Response(JSON.stringify({ invalid_key: true }), {
            status: 200,
          }),
        ),
      );

      act(() => {
        root.render(<Dashboard />);
      });
      await waitTicks();

      expect(container.textContent).toContain("Lỗi tải dữ liệu khuyến nghị");
      expect(container.textContent).toContain("Malformed payload: invalid recommendations schema");
    });

    it("displays clean NOT_FOUND state when recommendation file is 404", async () => {
      vi.spyOn(window, "fetch").mockImplementation(() =>
        Promise.resolve(new Response("Not Found", { status: 404 })),
      );

      act(() => {
        root.render(<Dashboard />);
      });
      await waitTicks();

      expect(container.textContent).toContain("Không tìm thấy dữ liệu khuyến nghị");
    });

    it("displays fallback market banner when recommendations succeeds but market.json returns 404 or fails", async () => {
      vi.spyOn(window, "fetch").mockImplementation((url: RequestInfo | URL) => {
        const urlStr = String(url);
        if (urlStr.includes("recommendations.json")) {
          return Promise.resolve(
            new Response(
              JSON.stringify(getValidRecommendationsPayloadSample({ recommendations: [] })),
              { status: 200 },
            ),
          );
        }
        if (urlStr.includes("market.json")) {
          return Promise.resolve(new Response("Not Found", { status: 404 }));
        }
        return Promise.resolve(new Response("Not Found", { status: 404 }));
      });

      act(() => {
        root.render(<Dashboard />);
      });
      await waitTicks();

      expect(container.textContent).toContain(
        "Dữ liệu tổng quan thị trường đang hiển thị từ báo cáo đợt ngày",
      );
      expect(container.textContent).toContain("market.json không khả dụng");
    });
  });

  describe("Typed Loader Schema Validation - Strict Checks", () => {
    it("rejects recommendations payload missing required field 'summary'", () => {
      const payload = getValidRecommendationsPayloadSample();
      delete (payload as any).summary;
      expect(isRecommendationsPayload(payload)).toBe(false);
    });

    it("rejects recommendation missing required field 'expected_return'", () => {
      const payload = getValidRecommendationsPayloadSample();
      delete payload.recommendations[0].expected_return;
      expect(isRecommendationsPayload(payload)).toBe(false);
    });

    it("rejects recommendation with invalid enum action 'SUPER_BUY'", () => {
      const payload = getValidRecommendationsPayloadSample();
      (payload.recommendations[0] as any).action = "SUPER_BUY";
      expect(isRecommendationsPayload(payload)).toBe(false);
    });

    it("rejects recommendation with invalid exchange 'NASDAQ'", () => {
      const payload = getValidRecommendationsPayloadSample();
      (payload.recommendations[0] as any).exchange = "NASDAQ";
      expect(isRecommendationsPayload(payload)).toBe(false);
    });

    it("rejects market info with invalid regime 'SUPER_BULL'", () => {
      const payload = getValidRecommendationsPayloadSample();
      (payload.market as any).regime = "SUPER_BULL";
      expect(isRecommendationsPayload(payload)).toBe(false);
    });

    it("rejects recommendation with non-string array element in reasons", () => {
      const payload = getValidRecommendationsPayloadSample();
      (payload.recommendations[0] as any).reasons = ["Good", 12345];
      expect(isRecommendationsPayload(payload)).toBe(false);
    });

    it("accepts valid recommendations payload with legitimate null values", () => {
      const validPayload = getValidRecommendationsPayloadSample({
        data_as_of: null,
        source_date: null,
        market: {
          regime: "PANIC",
          confidence: null,
          regime_score: null,
          metrics: { vnindex_value: null, vnindex_change_pct: null },
        },
        recommendations: [
          getValidRecommendationSample({
            signal_score: null,
            risk_adjusted_score: null,
            confidence: null,
            risk_level: null,
            expected_return: {
              expected_return_5d: null,
              expected_return_10d: null,
              expected_return_20d: null,
            },
            risk_metrics: {
              var_t25: null,
              es_t25: null,
              volatility_60d: null,
              max_drawdown: null,
              liquidity_score: null,
            },
            trade_plan: {
              current_price: null,
              entry_low: null,
              entry_high: null,
              stop_loss: null,
              tp1: null,
              tp2: null,
              risk_reward: null,
              position_percent: null,
            },
          }),
        ],
      });

      expect(isRecommendationsPayload(validPayload)).toBe(true);
    });

    it("rejects malformed market payload schema with ERROR", async () => {
      vi.spyOn(window, "fetch").mockImplementation(() =>
        Promise.resolve(
          new Response(JSON.stringify({ market: { regime: "INVALID_REGIME" } }), { status: 200 }),
        ),
      );

      const res = await loadMarketResult();
      expect(res).toEqual({
        status: "ERROR",
        error: "Malformed payload: invalid market schema",
      });
    });

    it("rejects malformed history index schema with ERROR", async () => {
      vi.spyOn(window, "fetch").mockImplementation(() =>
        Promise.resolve(new Response(JSON.stringify({ dates: [123, 456] }), { status: 200 })),
      );

      const res = await loadHistoryIndexResult();
      expect(res).toEqual({
        status: "ERROR",
        error: "Malformed payload: invalid history index schema",
      });
    });

    it("rejects malformed history report schema with ERROR", async () => {
      vi.spyOn(window, "fetch").mockImplementation(() =>
        Promise.resolve(
          new Response(JSON.stringify({ recommendations: "not_an_array" }), { status: 200 }),
        ),
      );

      const res = await loadHistoryReportResult("2026-10-09");
      expect(res).toEqual({
        status: "ERROR",
        error: "Malformed payload: invalid history report schema",
      });
    });
  });

  describe("History page race conditions and retry request isolation", () => {
    it("prevents stale retry error or data from overwriting newer active report request", async () => {
      let resolveReport1: (val: Response) => void = () => {};
      let resolveReport2: (val: Response) => void = () => {};

      const promiseReport1 = new Promise<Response>((res) => {
        resolveReport1 = res;
      });
      const promiseReport2 = new Promise<Response>((res) => {
        resolveReport2 = res;
      });

      vi.spyOn(window, "fetch").mockImplementation((url: RequestInfo | URL) => {
        const urlStr = String(url);
        if (urlStr.includes("history/index.json")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                last_updated: "2026-10-09",
                total_reports: 2,
                dates: ["2026-10-09", "2026-10-08"],
              }),
              { status: 200 },
            ),
          );
        }
        if (urlStr.includes("history/2026-10-09.json")) return promiseReport1;
        if (urlStr.includes("history/2026-10-08.json")) return promiseReport2;
        return Promise.resolve(new Response(null, { status: 404 }));
      });

      act(() => {
        root.render(<History />);
      });
      await waitTicks();

      // Change date to 2026-10-08
      const select = container.querySelector("select");
      act(() => {
        select!.value = "2026-10-08";
        select!.dispatchEvent(new Event("change", { bubbles: true }));
      });
      await waitTicks();

      // Resolve Date 1 (2026-10-09) WITH AN ERROR after user already switched to Date 2 (2026-10-08)
      resolveReport1(new Response("Internal Server Error", { status: 500 }));
      await waitTicks();

      // Stale error from Date 1 MUST NOT set error view for Date 2
      expect(container.textContent).not.toContain("Lỗi tải báo cáo ngày 2026-10-09");
      expect(container.textContent).toContain(
        `Đang tải báo cáo ngày ${formatDate("2026-10-08")}...`,
      );

      // Resolve Date 2 (2026-10-08) WITH SUCCESS
      resolveReport2(
        new Response(
          JSON.stringify(
            getValidRecommendationsPayloadSample({
              source_date: "2026-10-08",
              recommendations: [
                getValidRecommendationSample({
                  symbol: "VCB",
                  company_name: "Vietcombank",
                }),
              ],
            }),
          ),
          { status: 200 },
        ),
      );
      await waitTicks();

      expect(container.textContent).toContain("VCB");
      expect(container.textContent).toContain(`Báo cáo ngày ${formatDate("2026-10-08")}`);
    });
  });

  describe("StockDetail page race conditions, error states, and retry behavior", () => {
    it("handles controlled out-of-order symbol requests correctly without showing stale stock data", async () => {
      let resolveFPT: (val: Response) => void = () => {};
      let resolveVCB: (val: Response) => void = () => {};

      const promiseFPT = new Promise<Response>((res) => {
        resolveFPT = res;
      });
      const promiseVCB = new Promise<Response>((res) => {
        resolveVCB = res;
      });

      let fptFetchCount = 0;
      let vcbFetchCount = 0;

      vi.spyOn(window, "fetch").mockImplementation((url: RequestInfo | URL) => {
        const urlStr = String(url);
        if (urlStr.includes("recommendations.json")) {
          if (fptFetchCount > 0 && vcbFetchCount === 0) {
            return promiseFPT;
          }
          return promiseVCB;
        }
        return Promise.resolve(new Response("Not Found", { status: 404 }));
      });

      // Render FPT
      fptFetchCount++;
      act(() => {
        root.render(<StockDetail symbol="FPT" />);
      });
      await waitTicks();

      expect(container.textContent).toContain("Đang tải phân tích định lượng cổ phiếu FPT...");

      // Render VCB before FPT finishes
      vcbFetchCount++;
      act(() => {
        root.render(<StockDetail symbol="VCB" />);
      });
      await waitTicks();

      expect(container.textContent).toContain("Đang tải phân tích định lượng cổ phiếu VCB...");

      // Resolve VCB FIRST
      const mockVCBData = getValidRecommendationsPayloadSample({
        recommendations: [
          getValidRecommendationSample({
            symbol: "VCB",
            company_name: "Vietcombank",
          }),
        ],
      });

      resolveVCB(new Response(JSON.stringify(mockVCBData), { status: 200 }));
      await waitTicks();

      expect(container.textContent).toContain("VCB");
      expect(container.textContent).toContain("Vietcombank");

      // Resolve FPT LATER (out-of-order)
      const mockFPTData = getValidRecommendationsPayloadSample({
        recommendations: [
          getValidRecommendationSample({
            symbol: "FPT",
            company_name: "FPT Corp",
          }),
        ],
      });

      resolveFPT(new Response(JSON.stringify(mockFPTData), { status: 200 }));
      await waitTicks();

      expect(container.textContent).toContain("VCB");
      expect(container.textContent).not.toContain("FPT Corp");
    });

    it("displays error state when fetch fails and recovers on retry", async () => {
      let callCount = 0;
      vi.spyOn(window, "fetch").mockImplementation(() => {
        callCount++;
        if (callCount === 1) {
          return Promise.reject(new TypeError("NetworkError: Failed to fetch"));
        }
        return Promise.resolve(
          new Response(JSON.stringify(getValidRecommendationsPayloadSample()), { status: 200 }),
        );
      });

      act(() => {
        root.render(<StockDetail symbol="FPT" />);
      });
      await waitTicks();

      expect(container.textContent).toContain("NetworkError: Failed to fetch");
      const retryBtn = container.querySelector("button");
      expect(retryBtn).not.toBeNull();

      act(() => {
        retryBtn!.click();
      });
      await waitTicks();

      expect(container.textContent).toContain("FPT");
      expect(container.textContent).toContain("FPT Corp");
    });
  });
});
