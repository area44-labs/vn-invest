// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MarketSummary } from "@/components/market-summary";
import * as loader from "@/data/loader";
import { formatDate } from "@/lib/format";
import { History } from "@/pages/History";
import { StockDetail } from "@/pages/StockDetail";

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
      vi.spyOn(loader, "loadHistoryIndex").mockResolvedValue({
        last_updated: "2026-10-09",
        total_reports: 2,
        dates: ["2026-10-09", "2026-10-08"],
      });

      let resolveDate1: (val: any) => void = () => {};
      let resolveDate2: (val: any) => void = () => {};

      const promise1 = new Promise((res) => {
        resolveDate1 = res;
      });
      const promise2 = new Promise((res) => {
        resolveDate2 = res;
      });

      const mockLoadReport = vi.spyOn(loader, "loadHistoryReport");
      mockLoadReport.mockImplementation((date: string) => {
        if (date === "2026-10-09") return promise1 as any;
        if (date === "2026-10-08") return promise2 as any;
        return Promise.resolve(null);
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
        schema_version: "2.0",
        source_date: "2026-10-08",
        generated_at: "2026-10-08T16:00:00Z",
        market: { regime: "BULL", regime_score: 80, metrics: {} },
        summary: { buy_count: 5, watch_count: 2, sell_count: 1 },
        recommendations: [
          {
            symbol: "VCB",
            sector: "Ngân hàng",
            action: "BUY",
            trade_plan: { current_price: 90000, entry_low: 88000, entry_high: 89000 },
          },
        ],
      };

      await act(async () => {
        resolveDate2(mockReport20261008);
      });

      expect(container.textContent).toContain("VCB");
      expect(container.textContent).toContain(`Báo cáo ngày ${formatDate("2026-10-08")}`);

      // Resolve 2026-10-09 LATER (out-of-order response)
      const mockReport20261009 = {
        schema_version: "2.0",
        source_date: "2026-10-09",
        generated_at: "2026-10-09T16:00:00Z",
        market: { regime: "BEAR", regime_score: 20, metrics: {} },
        summary: { buy_count: 0, watch_count: 0, sell_count: 10 },
        recommendations: [
          {
            symbol: "FPT",
            sector: "Công nghệ",
            action: "SELL",
            trade_plan: { current_price: 130000 },
          },
        ],
      };

      await act(async () => {
        resolveDate1(mockReport20261009);
      });

      // Selected date is 2026-10-08, so late response for 2026-10-09 MUST BE IGNORED
      expect(container.textContent).toContain("VCB");
      expect(container.textContent).not.toContain("FPT");
    });

    it("handles missing historical reports cleanly", async () => {
      vi.spyOn(loader, "loadHistoryIndex").mockResolvedValue({
        last_updated: "2026-10-09",
        total_reports: 1,
        dates: ["2026-10-09"],
      });
      vi.spyOn(loader, "loadHistoryReport").mockResolvedValue(null);

      await act(async () => {
        root.render(<History />);
      });

      expect(container.textContent).toContain(
        `Không tìm thấy file báo cáo ngày ${formatDate("2026-10-09")}.`,
      );
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

      const mockLoadStock = vi.spyOn(loader, "loadStock");
      mockLoadStock.mockImplementation((sym: string) => {
        if (sym.toUpperCase() === "FPT") return promiseFPT as any;
        if (sym.toUpperCase() === "VCB") return promiseVCB as any;
        return Promise.resolve(null);
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
        exchange: "HOSE",
        sector: "Ngân hàng",
        action: "BUY",
        signal_score: 85,
        risk_adjusted_score: 75,
        confidence: 0.9,
        risk_level: "LOW",
        trade_plan: { current_price: 90000, entry_low: 88000, entry_high: 89000 },
        risk_metrics: {},
        reasons: ["Strong growth"],
        warnings: [],
        invalidation: [],
      };

      await act(async () => {
        resolveVCB(mockVCBData);
      });

      expect(container.textContent).toContain("VCB");
      expect(container.textContent).toContain("Vietcombank");

      // Resolve FPT LATER
      const mockFPTData = {
        symbol: "FPT",
        company_name: "FPT Corp",
        exchange: "HOSE",
        sector: "Technology",
        action: "HOLD",
        signal_score: 50,
        risk_adjusted_score: 40,
        confidence: 0.6,
        risk_level: "MEDIUM",
        trade_plan: { current_price: 130000 },
        risk_metrics: {},
        reasons: [],
        warnings: [],
        invalidation: [],
      };

      await act(async () => {
        resolveFPT(mockFPTData);
      });

      // Active symbol is VCB, late response for FPT must NOT overwrite VCB
      expect(container.textContent).toContain("VCB");
      expect(container.textContent).not.toContain("FPT Corp");
    });

    it("displays not-found state when stock data is missing", async () => {
      vi.spyOn(loader, "loadStock").mockResolvedValue(null);

      await act(async () => {
        root.render(<StockDetail symbol="UNKNOWN" />);
      });

      expect(container.textContent).toContain('Không tìm thấy dữ liệu phân tích cho mã "UNKNOWN"');
    });
  });
});
