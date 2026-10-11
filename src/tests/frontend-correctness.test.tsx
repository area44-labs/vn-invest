import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vite-plus/test";

import { MarketSummary } from "@/components/market-summary";
import {
  isHistoryIndexPayload,
  isMarketPayload,
  isRecommendationsPayload,
  loadHistoryIndexResult,
  loadHistoryReportResult,
  loadMarketResult,
  loadRecommendationsResult,
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
    signal_model_version: "v2.1",
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
          return Promise.resolve(
            new Response("Internal Error", { status: 500, statusText: "Internal Error" }),
          );
        }
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

      act(() => {
        root.render(<Dashboard />);
      });
      await waitTicks();

      expect(container.textContent).toContain("Lỗi tải dữ liệu khuyến nghị");
      const retryBtn = container.querySelector("button");
      expect(retryBtn).not.toBeNull();
      expect(retryBtn!.textContent).toContain("Thử lại");

      act(() => {
        retryBtn!.click();
      });
      await waitTicks();

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

  describe("Typed Loader Schema Validation - Strict Fail-Closed Checks", () => {
    it("rejects recommendations payload missing required field 'signal_model_version'", () => {
      const payload = getValidRecommendationsPayloadSample();
      delete (payload as any).signal_model_version;
      expect(isRecommendationsPayload(payload)).toBe(false);
    });

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

    it("validates 'risk_level' enum strictly: accepts LOW, MEDIUM, HIGH, null and rejects EXTREME, empty string, number, object", () => {
      const validLow = getValidRecommendationsPayloadSample();
      validLow.recommendations[0].risk_level = "LOW";
      expect(isRecommendationsPayload(validLow)).toBe(true);

      const validMed = getValidRecommendationsPayloadSample();
      validMed.recommendations[0].risk_level = "MEDIUM";
      expect(isRecommendationsPayload(validMed)).toBe(true);

      const validHigh = getValidRecommendationsPayloadSample();
      validHigh.recommendations[0].risk_level = "HIGH";
      expect(isRecommendationsPayload(validHigh)).toBe(true);

      const validNull = getValidRecommendationsPayloadSample();
      validNull.recommendations[0].risk_level = null;
      expect(isRecommendationsPayload(validNull)).toBe(true);

      // Rejections
      const invalidExtreme = getValidRecommendationsPayloadSample();
      (invalidExtreme.recommendations[0] as any).risk_level = "EXTREME";
      expect(isRecommendationsPayload(invalidExtreme)).toBe(false);

      const invalidEmpty = getValidRecommendationsPayloadSample();
      (invalidEmpty.recommendations[0] as any).risk_level = "";
      expect(isRecommendationsPayload(invalidEmpty)).toBe(false);

      const invalidNumber = getValidRecommendationsPayloadSample();
      (invalidNumber.recommendations[0] as any).risk_level = 1;
      expect(isRecommendationsPayload(invalidNumber)).toBe(false);

      const invalidObject = getValidRecommendationsPayloadSample();
      (invalidObject.recommendations[0] as any).risk_level = {};
      expect(isRecommendationsPayload(invalidObject)).toBe(false);
    });

    it("rejects numeric fields out of schema range or non-finite numbers", () => {
      // confidence > 1.0
      const invalidConf = getValidRecommendationsPayloadSample();
      invalidConf.market.confidence = 1.5;
      expect(isRecommendationsPayload(invalidConf)).toBe(false);

      // NaN or Infinity
      const invalidNaN = getValidRecommendationsPayloadSample();
      invalidNaN.recommendations[0].signal_score = NaN;
      expect(isRecommendationsPayload(invalidNaN)).toBe(false);

      const invalidInf = getValidRecommendationsPayloadSample();
      invalidInf.recommendations[0].signal_score = Infinity;
      expect(isRecommendationsPayload(invalidInf)).toBe(false);

      // position_percent > 100
      const invalidPos = getValidRecommendationsPayloadSample();
      invalidPos.recommendations[0].trade_plan.position_percent = 150;
      expect(isRecommendationsPayload(invalidPos)).toBe(false);
    });

    it("rejects non-integers in summary count fields", () => {
      const invalidSummary = getValidRecommendationsPayloadSample();
      invalidSummary.summary.buy_count = 1.5;
      expect(isRecommendationsPayload(invalidSummary)).toBe(false);
    });

    it("rejects payloads containing additional properties (additionalProperties: false)", () => {
      const extraPayloadProp = getValidRecommendationsPayloadSample({
        extra_field_disallowed: true,
      });
      expect(isRecommendationsPayload(extraPayloadProp)).toBe(false);

      const extraRecProp = getValidRecommendationsPayloadSample();
      (extraRecProp.recommendations[0] as any).extra_rec_field = "bad";
      expect(isRecommendationsPayload(extraRecProp)).toBe(false);

      const extraTradePlanProp = getValidRecommendationsPayloadSample();
      (extraTradePlanProp.recommendations[0].trade_plan as any).unknown_plan_key = 100;
      expect(isRecommendationsPayload(extraTradePlanProp)).toBe(false);
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

  describe("UI Retry Actions & Race Condition Isolation Tests", () => {
    it("handles UI Retry action then date change, ensuring stale retry completion (both error and success) is discarded", async () => {
      let resolveRetryReq: (val: Response) => void = () => {};
      let resolveDate2Req: (val: Response) => void = () => {};

      const retryPromise = new Promise<Response>((r) => {
        resolveRetryReq = r;
      });
      const date2Promise = new Promise<Response>((r) => {
        resolveDate2Req = r;
      });

      let callCount = 0;
      vi.spyOn(window, "fetch").mockImplementation((url: RequestInfo | URL) => {
        callCount++;
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
        if (urlStr.includes("history/2026-10-09.json")) {
          if (callCount === 2) {
            // Initial load fails with 500 error
            return Promise.resolve(new Response("500 Internal Error", { status: 500 }));
          }
          // Retry load for 2026-10-09
          return retryPromise;
        }
        if (urlStr.includes("history/2026-10-08.json")) {
          return date2Promise;
        }
        return Promise.resolve(new Response("Not Found", { status: 404 }));
      });

      // Render History page
      act(() => {
        root.render(<History />);
      });
      await waitTicks();

      // Initial Date 1 load fails -> displays error message & Thử lại button
      expect(container.textContent).toContain("Lỗi tải báo cáo ngày 2026-10-09");
      const retryBtn = container.querySelector("button");
      expect(retryBtn).not.toBeNull();

      // Step 2: User clicks Thử lại button
      act(() => {
        retryBtn!.click();
      });
      await waitTicks();

      expect(container.textContent).toContain(
        `Đang tải báo cáo ngày ${formatDate("2026-10-09")}...`,
      );

      // Step 3: User changes selected date to 2026-10-08 BEFORE retry finishes
      const select = container.querySelector("select");
      act(() => {
        select!.value = "2026-10-08";
        select!.dispatchEvent(new Event("change", { bubbles: true }));
      });
      await waitTicks();

      expect(container.textContent).toContain(
        `Đang tải báo cáo ngày ${formatDate("2026-10-08")}...`,
      );

      // Step 4: Allow Date 2 (2026-10-08) to complete FIRST with SUCCESS
      resolveDate2Req(
        new Response(
          JSON.stringify(
            getValidRecommendationsPayloadSample({
              source_date: "2026-10-08",
              recommendations: [
                getValidRecommendationSample({ symbol: "VCB", company_name: "Vietcombank" }),
              ],
            }),
          ),
          { status: 200 },
        ),
      );
      await waitTicks();

      expect(container.textContent).toContain("VCB");
      expect(container.textContent).toContain(`Báo cáo ngày ${formatDate("2026-10-08")}`);

      // Step 5: Allow old retry request for 2026-10-09 to complete LATER (testing stale retry completion)
      resolveRetryReq(
        new Response(
          JSON.stringify(
            getValidRecommendationsPayloadSample({
              source_date: "2026-10-09",
              recommendations: [
                getValidRecommendationSample({ symbol: "FPT", company_name: "FPT Corp" }),
              ],
            }),
          ),
          { status: 200 },
        ),
      );
      await waitTicks();

      // Step 6: Verify stale retry completion MUST NOT overwrite current view or clear Date 2 data
      expect(container.textContent).toContain("VCB");
      expect(container.textContent).not.toContain("FPT");
    });

    it("handles UI Retry action on StockDetail then symbol switch, discarding stale retry error response", async () => {
      let resolveRetryReq: (val: Response) => void = () => {};
      let resolveVCBReq: (val: Response) => void = () => {};

      const retryPromise = new Promise<Response>((r) => {
        resolveRetryReq = r;
      });
      const vcbPromise = new Promise<Response>((r) => {
        resolveVCBReq = r;
      });

      let recsFetchCount = 0;
      vi.spyOn(window, "fetch").mockImplementation((url: RequestInfo | URL) => {
        const urlStr = String(url);
        if (urlStr.includes("recommendations.json")) {
          recsFetchCount++;
          if (recsFetchCount === 1) {
            // First attempt for FPT fails
            return Promise.resolve(new Response("Internal Error", { status: 500 }));
          }
          if (recsFetchCount === 2) {
            // Retry for FPT
            return retryPromise;
          }
          // Request for VCB
          return vcbPromise;
        }
        return Promise.resolve(new Response("Not Found", { status: 404 }));
      });

      // Render StockDetail for FPT
      act(() => {
        root.render(<StockDetail symbol="FPT" />);
      });
      await waitTicks();

      expect(container.textContent).toContain('Lỗi tải phân tích định lượng cho mã "FPT"');
      const retryBtn = container.querySelector("button");
      expect(retryBtn).not.toBeNull();

      // Click Thử lại
      act(() => {
        retryBtn!.click();
      });
      await waitTicks();

      expect(container.textContent).toContain("Đang tải phân tích định lượng cổ phiếu FPT...");

      // Switch symbol to VCB before FPT retry finishes
      act(() => {
        root.render(<StockDetail symbol="VCB" />);
      });
      await waitTicks();

      expect(container.textContent).toContain("Đang tải phân tích định lượng cổ phiếu VCB...");

      // Resolve stale FPT retry with 500 ERROR
      resolveRetryReq(new Response("500 Internal Error", { status: 500 }));
      await waitTicks();

      // Ensure stale FPT error does NOT set error state for VCB
      expect(container.textContent).not.toContain('Lỗi tải phân tích định lượng cho mã "FPT"');
      expect(container.textContent).toContain("Đang tải phân tích định lượng cổ phiếu VCB...");

      // Resolve VCB request with SUCCESS
      resolveVCBReq(
        new Response(
          JSON.stringify(
            getValidRecommendationsPayloadSample({
              recommendations: [
                getValidRecommendationSample({ symbol: "VCB", company_name: "Vietcombank" }),
              ],
            }),
          ),
          { status: 200 },
        ),
      );
      await waitTicks();

      expect(container.textContent).toContain("VCB");
      expect(container.textContent).toContain("Vietcombank");
    });
  });
});
