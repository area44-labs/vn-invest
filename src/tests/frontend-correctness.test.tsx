import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vite-plus/test";

import { MarketSummary } from "@/components/market-summary";
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

  describe("Dashboard error, missing data, and retry behavior", () => {
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
            new Response(
              JSON.stringify({
                schema_version: "2.0",
                data_as_of: "2026-10-09",
                source_date: "2026-10-09",
                generated_at: "2026-10-09T16:00:00Z",
                market: {
                  regime: "PANIC",
                  regime_score: 7,
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
                recommendations: [
                  {
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
                  },
                ],
              }),
              { status: 200 },
            ),
          );
        }
        return Promise.resolve(
          new Response(
            JSON.stringify({
              schema_version: "2.0",
              data_as_of: "2026-10-09",
              source_date: "2026-10-09",
              generated_at: "2026-10-09T16:00:00Z",
              market: {
                regime: "PANIC",
                regime_score: 7,
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
  });

  describe("History page race conditions, missing index vs error, and retry behavior", () => {
    it("handles out-of-order date requests correctly without showing stale data", async () => {
      let resolveDate1: (val: Response) => void = () => {};
      let resolveDate2: (val: Response) => void = () => {};

      const promise1 = new Promise<Response>((res) => {
        resolveDate1 = res;
      });
      const promise2 = new Promise<Response>((res) => {
        resolveDate2 = res;
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
        if (urlStr.includes("history/2026-10-09.json")) return promise1;
        if (urlStr.includes("history/2026-10-08.json")) return promise2;
        return Promise.resolve(new Response(null, { status: 404 }));
      });

      act(() => {
        root.render(<History />);
      });
      await waitTicks();

      expect(container.textContent).toContain(
        `Đang tải báo cáo ngày ${formatDate("2026-10-09")}...`,
      );

      const select = container.querySelector("select");
      expect(select).not.toBeNull();

      act(() => {
        select!.value = "2026-10-08";
        select!.dispatchEvent(new Event("change", { bubbles: true }));
      });
      await waitTicks();

      expect(container.textContent).toContain(
        `Đang tải báo cáo ngày ${formatDate("2026-10-08")}...`,
      );

      const mockReport20261008 = {
        schema_version: "2.0",
        source_date: "2026-10-08",
        generated_at: "2026-10-08T16:00:00Z",
        market: {
          regime: "BULL",
          regime_score: 80,
          metrics: { vnindex_value: 1250, vnindex_change_pct: 0.5 },
        },
        summary: {
          total_scanned: 1,
          buy_count: 5,
          watch_count: 2,
          hold_count: 0,
          sell_count: 1,
          avoid_count: 0,
        },
        recommendations: [
          {
            symbol: "VCB",
            company_name: "Vietcombank",
            exchange: "HOSE",
            sector: "Ngân hàng",
            action: "BUY",
            signal_score: 80,
            risk_adjusted_score: 70,
            confidence: 0.8,
            risk_level: "LOW",
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
              current_price: 90000,
              entry_low: 88000,
              entry_high: 89000,
              stop_loss: 85000,
              tp1: 95000,
              tp2: 100000,
              risk_reward: 2,
              position_percent: 10,
            },
            reasons: [],
            warnings: [],
            invalidation: [],
          },
        ],
      };

      resolveDate2(new Response(JSON.stringify(mockReport20261008), { status: 200 }));
      await waitTicks();

      expect(container.textContent).toContain("VCB");
      expect(container.textContent).toContain(`Báo cáo ngày ${formatDate("2026-10-08")}`);

      const mockReport20261009 = {
        schema_version: "2.0",
        source_date: "2026-10-09",
        generated_at: "2026-10-09T16:00:00Z",
        market: {
          regime: "BEAR",
          regime_score: 20,
          metrics: { vnindex_value: 1200, vnindex_change_pct: -1.0 },
        },
        summary: {
          total_scanned: 1,
          buy_count: 0,
          watch_count: 0,
          hold_count: 0,
          sell_count: 10,
          avoid_count: 0,
        },
        recommendations: [
          {
            symbol: "FPT",
            company_name: "FPT Corp",
            exchange: "HOSE",
            sector: "Công nghệ",
            action: "SELL",
            signal_score: 20,
            risk_adjusted_score: 10,
            confidence: 0.5,
            risk_level: "HIGH",
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
              current_price: 130000,
              entry_low: null,
              entry_high: null,
              stop_loss: null,
              tp1: null,
              tp2: null,
              risk_reward: null,
              position_percent: 0,
            },
            reasons: [],
            warnings: [],
            invalidation: [],
          },
        ],
      };

      resolveDate1(new Response(JSON.stringify(mockReport20261009), { status: 200 }));
      await waitTicks();

      expect(container.textContent).toContain("VCB");
      expect(container.textContent).not.toContain("FPT");
    });

    it("displays distinct history index NOT_FOUND vs ERROR and recovers on retry", async () => {
      let callCount = 0;
      vi.spyOn(window, "fetch").mockImplementation((url: RequestInfo | URL) => {
        callCount++;
        const urlStr = String(url);
        if (callCount === 1) {
          return Promise.resolve(
            new Response("500 Internal Error", { status: 500, statusText: "Internal Error" }),
          );
        }
        if (urlStr.includes("history/index.json")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                last_updated: "2026-10-09",
                total_reports: 1,
                dates: ["2026-10-09"],
              }),
              { status: 200 },
            ),
          );
        }
        return Promise.resolve(new Response("Not Found", { status: 404 }));
      });

      act(() => {
        root.render(<History />);
      });
      await waitTicks();

      expect(container.textContent).toContain("Lỗi tải chỉ mục lịch sử báo cáo");
      const retryBtn = container.querySelector("button");
      expect(retryBtn).not.toBeNull();

      act(() => {
        retryBtn!.click();
      });
      await waitTicks();

      expect(container.textContent).toContain("Lịch Sử Khuyến Nghị VN Invest");
      expect(container.textContent).toContain("Phiên ngày 2026-10-09");
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
      const mockVCBData = {
        schema_version: "2.0",
        data_as_of: "2026-10-09",
        source_date: "2026-10-09",
        generated_at: "2026-10-09T16:00:00Z",
        market: { regime: "PANIC", regime_score: 7, confidence: 0.85, metrics: {} },
        summary: {
          total_scanned: 1,
          buy_count: 1,
          watch_count: 0,
          hold_count: 0,
          sell_count: 0,
          avoid_count: 0,
        },
        recommendations: [
          {
            symbol: "VCB",
            company_name: "Vietcombank",
            exchange: "HOSE",
            sector: "Ngân hàng",
            action: "BUY",
            signal_score: 85,
            risk_adjusted_score: 75,
            confidence: 0.9,
            risk_level: "LOW",
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
              current_price: 90000,
              entry_low: 88000,
              entry_high: 89000,
              stop_loss: 85000,
              tp1: 95000,
              tp2: 100000,
              risk_reward: 2,
              position_percent: 10,
            },
            reasons: ["Strong growth"],
            warnings: [],
            invalidation: [],
          },
        ],
      };

      resolveVCB(new Response(JSON.stringify(mockVCBData), { status: 200 }));
      await waitTicks();

      expect(container.textContent).toContain("VCB");
      expect(container.textContent).toContain("Vietcombank");

      // Resolve FPT LATER (out-of-order)
      const mockFPTData = {
        schema_version: "2.0",
        data_as_of: "2026-10-09",
        source_date: "2026-10-09",
        generated_at: "2026-10-09T16:00:00Z",
        market: { regime: "PANIC", regime_score: 7, confidence: 0.85, metrics: {} },
        summary: {
          total_scanned: 1,
          buy_count: 0,
          watch_count: 0,
          hold_count: 1,
          sell_count: 0,
          avoid_count: 0,
        },
        recommendations: [
          {
            symbol: "FPT",
            company_name: "FPT Corp",
            exchange: "HOSE",
            sector: "Technology",
            action: "HOLD",
            signal_score: 50,
            risk_adjusted_score: 40,
            confidence: 0.6,
            risk_level: "MEDIUM",
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
              current_price: 130000,
              entry_low: null,
              entry_high: null,
              stop_loss: null,
              tp1: null,
              tp2: null,
              risk_reward: null,
              position_percent: 0,
            },
            reasons: [],
            warnings: [],
            invalidation: [],
          },
        ],
      };

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
          new Response(
            JSON.stringify({
              schema_version: "2.0",
              data_as_of: "2026-10-09",
              source_date: "2026-10-09",
              generated_at: "2026-10-09T16:00:00Z",
              market: { regime: "PANIC", regime_score: 7, confidence: 0.85, metrics: {} },
              summary: {
                total_scanned: 1,
                buy_count: 1,
                watch_count: 0,
                hold_count: 0,
                sell_count: 0,
                avoid_count: 0,
              },
              recommendations: [
                {
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
                    current_price: 130000,
                    entry_low: 125000,
                    entry_high: 128000,
                    stop_loss: 120000,
                    tp1: 140000,
                    tp2: 150000,
                    risk_reward: 2,
                    position_percent: 10,
                  },
                  reasons: [],
                  warnings: [],
                  invalidation: [],
                },
              ],
            }),
            { status: 200 },
          ),
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
