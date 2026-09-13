import { Link } from "@tanstack/react-router";
import { Calendar, History as HistoryIcon } from "lucide-react";
import { useEffect, useState } from "react";

import type { HistoryIndexPayload, RecommendationsPayload } from "@/types/recommendation";

import { Badge } from "@/components/ui/badge";
import { loadHistoryIndex, loadHistoryReport } from "@/data/loader";
import { formatDate, formatVnd } from "@/lib/format";

export function History() {
  const [indexData, setIndexData] = useState<HistoryIndexPayload | null>(null);
  const [selectedDate, setSelectedDate] = useState<string>("");
  const [reportData, setReportData] = useState<RecommendationsPayload | null>(null);
  const [loadingIndex, setLoadingIndex] = useState(true);
  const [loadingReport, setLoadingReport] = useState(false);

  useEffect(() => {
    async function initHistoryIndex() {
      setLoadingIndex(true);
      const data = await loadHistoryIndex();
      if (data && data.dates && data.dates.length > 0) {
        setIndexData(data);
        setSelectedDate(data.dates[0]);
      }
      setLoadingIndex(false);
    }

    initHistoryIndex();
  }, []);

  useEffect(() => {
    if (!selectedDate) return;

    async function loadDateReport() {
      setLoadingReport(true);
      const report = await loadHistoryReport(selectedDate);
      if (report) {
        setReportData(report);
      }
      setLoadingReport(false);
    }

    loadDateReport();
  }, [selectedDate]);

  if (loadingIndex) {
    return (
      <div className="flex h-64 items-center justify-center font-mono text-xs text-muted-foreground">
        Đang tải chỉ mục lịch sử báo cáo...
      </div>
    );
  }

  if (!indexData || indexData.dates.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center space-y-2 text-center font-mono">
        <p className="text-sm font-bold text-foreground">Không tìm thấy báo cáo lịch sử</p>
        <p className="text-xs text-muted-foreground">
          Vui lòng tạo báo cáo đầu tiên bằng command pipeline Python.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Date Picker Header */}
      <div className="flex flex-col gap-4 border-b border-border pb-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="flex items-center text-xl font-bold tracking-tight text-foreground">
            <HistoryIcon className="mr-2 h-5 w-5" /> Lịch Sử Khuyến Nghị VN Invest
          </h1>
          <p className="text-xs text-muted-foreground">
            Chọn ngày giao dịch để xem lại dữ liệu khuyến nghị và trạng thái thị trường quá khứ.
          </p>
        </div>

        <div className="flex items-center space-x-2">
          <Calendar className="h-4 w-4 text-muted-foreground" />
          <select
            value={selectedDate}
            onChange={(e) => setSelectedDate(e.target.value)}
            className="cursor-pointer rounded-sm border border-border bg-card px-3 py-1.5 font-mono text-xs text-foreground focus:outline-none"
          >
            {indexData.dates.map((d) => (
              <option key={d} value={d}>
                Phiên ngày {formatDate(d)}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Selected Report Content */}
      {loadingReport ? (
        <div className="flex h-48 items-center justify-center font-mono text-xs text-muted-foreground">
          Đang tải báo cáo ngày {formatDate(selectedDate)}...
        </div>
      ) : !reportData ? (
        <div className="p-8 text-center font-mono text-xs text-muted-foreground">
          Không tìm thấy file báo cáo ngày {formatDate(selectedDate)}.
        </div>
      ) : (
        <div className="space-y-6">
          {/* Summary Box */}
          <div className="flex flex-wrap items-center justify-between gap-4 rounded-sm border border-border bg-card p-4">
            <div>
              <span className="block font-mono text-[10px] text-muted-foreground uppercase">
                Báo cáo ngày {formatDate(reportData.source_date)}
              </span>
              <span className="text-sm font-bold text-foreground">
                Thị trường: {reportData.market.regime} (Điểm:{" "}
                {reportData.market.regime_score ?? "—"})
              </span>
            </div>
            <div className="flex items-center space-x-3 font-mono text-xs">
              <span className="text-trend-up-text">MUA: {reportData.summary.buy_count}</span>
              <span className="text-warning-text">Theo dõi: {reportData.summary.watch_count}</span>
              <span className="text-trend-down-text">BÁN: {reportData.summary.sell_count}</span>
            </div>
          </div>

          {/* Recommendations Table */}
          <div className="overflow-x-auto rounded-sm border border-border bg-card">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-border bg-muted/40 font-mono text-[10px] text-muted-foreground uppercase">
                  <th className="p-3">Mã CP</th>
                  <th className="p-3 text-center">Hành động</th>
                  <th className="p-3 text-right">Signal Score</th>
                  <th className="p-3 text-right">Giá hiện tại</th>
                  <th className="p-3 text-center">Vùng mua / TP / SL</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border text-xs">
                {reportData.recommendations.map((rec) => (
                  <tr key={rec.symbol} className="transition-colors hover:bg-muted/30">
                    <td className="p-3 font-bold text-foreground">
                      <Link
                        to="/stock/$symbol"
                        params={{ symbol: rec.symbol }}
                        className="hover:underline"
                      >
                        {rec.symbol}
                      </Link>{" "}
                      <span className="text-[10px] font-normal text-muted-foreground">
                        ({rec.sector})
                      </span>
                    </td>
                    <td className="p-3 text-center">
                      <Badge
                        variant={
                          rec.action === "BUY"
                            ? "success"
                            : rec.action === "WATCH"
                              ? "warning"
                              : "destructive"
                        }
                      >
                        {rec.action}
                      </Badge>
                    </td>
                    <td className="p-3 text-right font-mono font-bold">
                      {rec.signal_score != null ? rec.signal_score.toFixed(1) : "—"}
                    </td>
                    <td className="p-3 text-right font-bold">
                      {formatVnd(rec.trade_plan.current_price)}
                    </td>
                    <td className="p-3 text-center font-mono text-[11px]">
                      {rec.trade_plan.entry_low != null
                        ? `${formatVnd(rec.trade_plan.entry_low)} - ${formatVnd(rec.trade_plan.entry_high)}`
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
