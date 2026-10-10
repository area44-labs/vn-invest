// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vite-plus/test";

import { MarketSummary } from "@/components/market-summary";
import * as loader from "@/data/loader";
import { formatDate } from "@/lib/format";
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
      // VN-INDEX price change should show -0.50%
      expect(text).toContain("-0.50%");

      // Confidence should be displayed as 85%, NOT as +85.00%
      expect(text).toContain("Độ tin cậy 85%");
      expect(text).not.toContain("+85.00%");

      // Breadth should be displayed as 24.0%, NOT as +24.00%
      expect(text).toContain("24.0%");
      expect(text).not.toContain("+24.00%");
    });
  });

  describe("History page race conditions and states", () => {
    it("handles out-of-order date requests correctly without showing stale data", async () => {
      vi.spyOn(loader, "loadHistoryIndexResult").mockResolvedValue({
        status: "SUCCESS",
        data: {
          last_updated: "2026-10-09",
          total_reports: 2,
          dates: ["2026-10-09", "2026-10-08"],
        },
      });

      let resolveDate1: (val: any) => void = () => {};
      let resolveDate2: (val: any) => void = () => {};

      const promise1 = new Promise((res) => {
        resolveDate1 = res;
      });
      const promise2 = new Promise((res) => {
        resolveDate2 = res;
      });

      const mockLoadReportResult = vi.spyOn(loader, "loadHistoryReportResult");
      mockLoadReportResult.mockImplementation((date: string) => {
        if (date === "2026-10-09") return promise1 as any;
        if (date === "2026-10-08") return promise2 as any;
        return Promise.resolve({ status: "NOT_FOUND" });
      });

      await act(async () => {
        root.render(<History />);
      });

      // Initial date selected: 2026-10-09
      expect(container.textContent).toContain(
        `Đang tải báo cáo ngày ${formatDate("2026-10-09")}...`,
      );

      // Simulate date selector change to 2026-10-08 while 2026-10-09 is still pending
      const select = container.querySelector("select");
      expect(select).not.toBeNull();

      await act(async () => {
        select!.value = "2026-10-08";
        select!.dispatchEvent(new Event("change", { bubbles: true }));
      });

      expect(container.textContent).toContain(
        `Đang tải báo cáo ngày ${formatDate("2026-10-08")}...`,
      );

      // Resolve 2026-10-08 FIRST
      const mockReport20261008 = {
        schema_version: "2.0" as const,
        source_date: "2026-10-08",
        generated_at: "2026-10-08T16:00:00Z",
        market: {
          regime: "BULL" as const,
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
            exchange: "HOSE" as const,
            sector: "Ngân hàng",
            action: "BUY" as const,
            signal_score: 80,
            risk_adjusted_score: 70,
            confidence: 0.8,
            risk_level: "LOW" as const,
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

      await act(async () => {
        resolveDate2({ status: "SUCCESS", data: mockReport20261008 });
      });

      expect(container.textContent).toContain("VCB");
      expect(container.textContent).toContain(`Báo cáo ngày ${formatDate("2026-10-08")}`);

      // Resolve 2026-10-09 LATER (out-of-order response)
      const mockReport20261009 = {
        schema_version: "2.0" as const,
        source_date: "2026-10-09",
        generated_at: "2026-10-09T16:00:00Z",
        market: {
          regime: "BEAR" as const,
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
            exchange: "HOSE" as const,
            sector: "Công nghệ",
            action: "SELL" as const,
            signal_score: 20,
            risk_adjusted_score: 10,
            confidence: 0.5,
            risk_level: "HIGH" as const,
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

      await act(async () => {
        resolveDate1({ status: "SUCCESS", data: mockReport20261009 });
      });

      // Selected date is 2026-10-08, so late response for 2026-10-09 MUST BE IGNORED
      expect(container.textContent).toContain("VCB");
      expect(container.textContent).not.toContain("FPT");
    });

    it("displays clean NOT_FOUND state when report file is missing", async () => {
      vi.spyOn(loader, "loadHistoryIndexResult").mockResolvedValue({
        status: "SUCCESS",
        data: {
          last_updated: "2026-10-09",
          total_reports: 1,
          dates: ["2026-10-09"],
        },
      });
      vi.spyOn(loader, "loadHistoryReportResult").mockResolvedValue({ status: "NOT_FOUND" });

      await act(async () => {
        root.render(<History />);
      });

      expect(container.textContent).toContain(
        `Không tìm thấy file báo cáo ngày ${formatDate("2026-10-09")}.`,
      );
    });

    it("displays error state when report fetch/parse fails", async () => {
      vi.spyOn(loader, "loadHistoryIndexResult").mockResolvedValue({
        status: "SUCCESS",
        data: {
          last_updated: "2026-10-09",
          total_reports: 1,
          dates: ["2026-10-09"],
        },
      });
      vi.spyOn(loader, "loadHistoryReportResult").mockResolvedValue({
        status: "ERROR",
        error: "HTTP 500: Internal Server Error",
      });

      await act(async () => {
        root.render(<History />);
      });

      expect(container.textContent).toContain("HTTP 500: Internal Server Error");
    });
  });

  describe("StockDetail page race conditions and missing data", () => {
    it("handles rapid symbol switching without displaying stale stock data", async () => {
      let resolveFPT: (val: any) => void = () => {};
      let resolveVCB: (val: any) => void = () => {};

      const promiseFPT = new Promise((res) => {
        resolveFPT = res;
      });
      const promiseVCB = new Promise((res) => {
        resolveVCB = res;
      });

      const mockLoadStockResult = vi.spyOn(loader, "loadStockResult");
      mockLoadStockResult.mockImplementation((sym: string) => {
        if (sym.toUpperCase() === "FPT") return promiseFPT as any;
        if (sym.toUpperCase() === "VCB") return promiseVCB as any;
        return Promise.resolve({ status: "NOT_FOUND" });
      });

      // Render initially with FPT
      await act(async () => {
        root.render(<StockDetail symbol="FPT" />);
      });

      expect(container.textContent).toContain("Đang tải phân tích định lượng cổ phiếu FPT...");

      // Switch to VCB while FPT is loading
      await act(async () => {
        root.render(<StockDetail symbol="VCB" />);
      });

      expect(container.textContent).toContain("Đang tải phân tích định lượng cổ phiếu VCB...");

      // Resolve VCB FIRST
      const mockVCBData = {
        symbol: "VCB",
        company_name: "Vietcombank",
        exchange: "HOSE" as const,
        sector: "Ngân hàng",
        action: "BUY" as const,
        signal_score: 85,
        risk_adjusted_score: 75,
        confidence: 0.9,
        risk_level: "LOW" as const,
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
      };

      await act(async () => {
        resolveVCB({ status: "SUCCESS", data: mockVCBData });
      });

      expect(container.textContent).toContain("VCB");
      expect(container.textContent).toContain("Vietcombank");

      // Resolve FPT LATER
      const mockFPTData = {
        symbol: "FPT",
        company_name: "FPT Corp",
        exchange: "HOSE" as const,
        sector: "Technology",
        action: "HOLD" as const,
        signal_score: 50,
        risk_adjusted_score: 40,
        confidence: 0.6,
        risk_level: "MEDIUM" as const,
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
      };

      await act(async () => {
        resolveFPT({ status: "SUCCESS", data: mockFPTData });
      });

      // Active symbol is VCB, late response for FPT must NOT overwrite VCB
      expect(container.textContent).toContain("VCB");
      expect(container.textContent).not.toContain("FPT Corp");
    });

    it("displays clean NOT_FOUND state when stock symbol is not found", async () => {
      vi.spyOn(loader, "loadStockResult").mockResolvedValue({ status: "NOT_FOUND" });

      await act(async () => {
        root.render(<StockDetail symbol="UNKNOWN" />);
      });

      expect(container.textContent).toContain('Không tìm thấy dữ liệu phân tích cho mã "UNKNOWN"');
    });

    it("displays error state when stock fetch/parse fails", async () => {
      vi.spyOn(loader, "loadStockResult").mockResolvedValue({
        status: "ERROR",
        error: "NetworkError: Failed to fetch",
      });

      await act(async () => {
        root.render(<StockDetail symbol="UNKNOWN" />);
      });

      expect(container.textContent).toContain("NetworkError: Failed to fetch");
    });
  });
});
