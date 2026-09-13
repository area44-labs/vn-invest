import { ArrowDownRight, Sparkles, AlertCircle } from "lucide-react";
import { useEffect, useState } from "react";

import type { MarketPayload, RecommendationsPayload } from "@/types/recommendation";

import { MarketSummary } from "@/components/market-summary";
import { RecommendationCard } from "@/components/recommendation-card";
import { StockTable } from "@/components/stock-table";
import { loadMarket, loadRecommendations } from "@/data/loader";
import { formatDate } from "@/lib/format";

interface DashboardProps {
  initialData?: RecommendationsPayload | null;
  initialMarketPayload?: MarketPayload | null;
}

export function Dashboard({ initialData = null, initialMarketPayload = null }: DashboardProps) {
  const [data, setData] = useState<RecommendationsPayload | null>(initialData);
  const [marketPayload, setMarketPayload] = useState<MarketPayload | null>(initialMarketPayload);
  const [activeTab, setActiveTab] = useState<string>("BUY");
  const [loading, setLoading] = useState(!initialData);

  useEffect(() => {
    if (initialData) {
      return;
    }

    async function initDashboardData() {
      setLoading(true);
      const [recs, mkt] = await Promise.all([loadRecommendations(), loadMarket()]);
      if (recs) setData(recs);
      if (mkt) setMarketPayload(mkt);
      setLoading(false);
    }
    initDashboardData();
  }, [initialData]);

  if (loading && !data) {
    return (
      <div className="flex h-64 items-center justify-center font-mono text-xs text-muted-foreground">
        Đang tải dữ liệu phân tích thị trường VN Invest...
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex h-64 flex-col items-center justify-center space-y-2 font-mono text-xs">
        <p className="font-bold text-foreground">Không tìm thấy dữ liệu khuyến nghị</p>
        <p className="text-muted-foreground">
          Vui lòng chạy pipeline định lượng Python để tạo dữ liệu ban đầu.
        </p>
      </div>
    );
  }

  const recommendations = data.recommendations || [];
  const buyList = recommendations.filter((r) => r.action === "BUY" || r.action === "WATCH");
  const sellList = recommendations.filter(
    (r) => r.action === "SELL" || r.action === "AVOID" || r.action === "HOLD",
  );

  // Deterministic ranking by risk_adjusted_score or signal_score DESC
  const sortedBuys = [...buyList].sort(
    (a, b) =>
      (b.risk_adjusted_score ?? b.signal_score ?? 0) -
      (a.risk_adjusted_score ?? a.signal_score ?? 0),
  );
  const sortedSells = [...sellList].sort(
    (a, b) =>
      (b.risk_adjusted_score ?? b.signal_score ?? 0) -
      (a.risk_adjusted_score ?? a.signal_score ?? 0),
  );

  const topBuys = sortedBuys.slice(0, 4);
  const topSells = sortedSells.slice(0, 4);

  const mktMetrics = marketPayload?.market?.metrics || data.market?.metrics;
  const vnVal = mktMetrics?.vnindex_value ?? null;
  const vnChgPct = mktMetrics?.vnindex_change_pct ?? null;
  const vnChgAbs = vnVal != null && vnChgPct != null ? (vnVal * vnChgPct) / 100 : null;

  const isStale = () => {
    if (!data.source_date) return false;
    const dataDate = new Date(data.source_date);
    const today = new Date();
    const diffDays = Math.floor((today.getTime() - dataDate.getTime()) / (1000 * 3600 * 24));
    return diffDays > 3;
  };

  const marketSummaryData = {
    vnIndex: {
      name: "VN-INDEX",
      value: vnVal,
      change: vnChgAbs,
      changePercent: vnChgPct,
      volume: mktMetrics?.volume_20d_ratio != null ? `${mktMetrics.volume_20d_ratio}x MA20` : "N/A",
    },
    regimeStatus: {
      name: "TRẠNG THÁI THỊ TRƯỜNG",
      value: data.market?.regime_score ?? null,
      change: null,
      changePercent: data.market?.confidence != null ? data.market.confidence * 100 : null,
      volume: data.market?.regime ?? "N/A",
    },
    breadth: {
      name: "BREADTH (>MA20)",
      value:
        mktMetrics?.market_breadth_ratio != null ? mktMetrics.market_breadth_ratio * 100 : null,
      change: null,
      changePercent:
        mktMetrics?.market_breadth_ratio != null ? mktMetrics.market_breadth_ratio * 100 : null,
      volume: "Tỉ lệ mã CP > MA20",
    },
    totalStocks: {
      name: "TỔNG SỐ MÃ SCANNED",
      value: data.summary?.total_scanned ?? recommendations.length,
      change: null,
      changePercent: null,
      volume: `${data.summary?.buy_count ?? buyList.length} MUA / ${data.summary?.sell_count ?? sellList.length} BÁN`,
    },
  };

  return (
    <div className="space-y-8">
      {/* Freshness Banner */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-sm border border-border bg-card px-4 py-3 font-mono text-xs">
        <div className="flex items-center space-x-2">
          <span className="font-bold text-foreground">Dữ liệu định lượng:</span>
          <span className="text-muted-foreground">{formatDate(data.source_date)}</span>
          <span className="text-subtle-foreground">({data.generated_at})</span>
        </div>
        {isStale() && (
          <div className="flex items-center space-x-1 font-bold text-trend-down-text">
            <AlertCircle className="h-4 w-4" />
            <span>⚠ Dữ liệu có thể đã cũ (batch generated)</span>
          </div>
        )}
      </div>

      {/* Real-time Market Overview Banner */}
      <MarketSummary
        marketData={marketSummaryData}
        buyCount={buyList.length}
        sellCount={sellList.length}
      />

      {/* Primary Product Question Banner */}
      <div className="rounded-sm border border-border bg-accent/30 p-4">
        <h2 className="text-lg font-bold text-foreground">Hôm nay nên chú ý cổ phiếu nào?</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Hệ thống xếp hạng định lượng ưu tiên các mã thỏa mãn bộ lọc Signal Score, rủi ro T+2.5 và
          quy tắc Market Regime ({data.market?.regime}).
        </p>
      </div>

      {/* Top Today Recommendations Cards */}
      <div className="space-y-4">
        <div className="flex items-center justify-between border-b border-border pb-2">
          <h3 className="flex items-center font-mono text-xs font-bold text-trend-up-text uppercase">
            <Sparkles className="mr-1.5 h-4 w-4" /> Top Khuyến Nghị Tiêu Biểu Hôm Nay
          </h3>
          <span className="font-mono text-[10px] text-muted-foreground">
            Sắp xếp theo Risk-Adjusted Score
          </span>
        </div>

        {topBuys.length === 0 ? (
          <div className="rounded-sm border border-dashed border-border p-6 text-center font-mono text-xs text-muted-foreground">
            Không có mã khuyến nghị MUA/THEO DÕI phù hợp trong chế độ thị trường{" "}
            {data.market?.regime}.
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {topBuys.map((rec, index) => (
              <RecommendationCard key={rec.symbol} recommendation={rec} rank={index + 1} />
            ))}
          </div>
        )}
      </div>

      {/* Sell / Avoid Warnings Section */}
      {topSells.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between border-b border-border pb-2">
            <h3 className="flex items-center font-mono text-xs font-bold text-trend-down-text uppercase">
              <ArrowDownRight className="mr-1.5 h-4 w-4" /> Cảnh Báo Khuyên Bán / Tránh Giao Dịch
            </h3>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {topSells.map((rec) => (
              <RecommendationCard key={rec.symbol} recommendation={rec} />
            ))}
          </div>
        </div>
      )}

      {/* Main Stock Table */}
      <div className="space-y-4">
        <div className="flex items-center space-x-2">
          <div className="h-1.5 w-1.5 bg-foreground" />
          <h2 className="font-mono text-[11px] tracking-wider text-muted-foreground uppercase">
            Toàn Bộ Danh Sách Khuyến Nghị Giao Dịch
          </h2>
        </div>

        <StockTable
          recommendations={recommendations}
          activeTab={activeTab}
          setActiveTab={setActiveTab}
        />
      </div>
    </div>
  );
}
