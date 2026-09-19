import { Link } from "@tanstack/react-router";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  BarChart3,
  HelpCircle,
  ShieldAlert,
  Sparkles,
  Target,
} from "lucide-react";
import { useEffect, useState } from "react";

import type { Recommendation } from "@/types/recommendation";

import { Badge } from "@/components/ui/badge";
import { loadStock } from "@/data/loader";
import { formatRisk, formatScore, formatVnd } from "@/lib/format";
import { cn } from "@/lib/utils";

interface StockDetailProps {
  symbol?: string;
  initialStock?: Recommendation | null;
}

export function StockDetail({ symbol: propsSymbol, initialStock = null }: StockDetailProps) {
  const activeSymbol = propsSymbol || "FPT";
  const [stock, setStock] = useState<Recommendation | null>(initialStock);
  const [loading, setLoading] = useState(!initialStock);

  useEffect(() => {
    if (initialStock && initialStock.symbol.toUpperCase() === activeSymbol.toUpperCase()) {
      return;
    }

    async function fetchStock() {
      setLoading(true);
      const rec = await loadStock(activeSymbol);
      if (rec) {
        setStock(rec);
      }
      setLoading(false);
    }
    fetchStock();
  }, [activeSymbol, initialStock]);

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center font-mono text-xs text-muted-foreground">
        Đang tải phân tích định lượng cổ phiếu {activeSymbol}...
      </div>
    );
  }

  if (!stock) {
    return (
      <div className="flex h-64 flex-col items-center justify-center space-y-3 text-center">
        <p className="font-mono text-sm font-bold text-foreground">
          Không tìm thấy dữ liệu phân tích cho mã "{activeSymbol}"
        </p>
        <Link
          to="/"
          className="flex cursor-pointer items-center gap-1 font-mono text-xs text-muted-foreground underline hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Quay lại Dashboard
        </Link>
      </div>
    );
  }

  const getActionBadge = (action: string) => {
    switch (action) {
      case "BUY":
        return <Badge variant="success">Khuyến Nghị MUA (BUY)</Badge>;
      case "WATCH":
        return <Badge variant="warning">Theo Dõi (WATCH)</Badge>;
      case "HOLD":
        return <Badge variant="outline">Nắm Giữ (HOLD)</Badge>;
      case "SELL":
        return <Badge variant="destructive">Khuyến Nghị BÁN (SELL)</Badge>;
      case "AVOID":
        return <Badge variant="destructive">Tránh Giao Dịch (AVOID)</Badge>;
      default:
        return <Badge variant="outline">{action}</Badge>;
    }
  };

  const isBuy = stock.action === "BUY" || stock.action === "WATCH";
  const tfs: ("1H" | "1D" | "1W" | "1M")[] = ["1H", "1D", "1W", "1M"];

  return (
    <div className="space-y-6">
      {/* Top Header & Navigation */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
        <div className="flex items-center space-x-3">
          <Link
            to="/"
            className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-sm border border-border bg-card text-muted-foreground hover:bg-accent"
            title="Quay lại Dashboard"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div>
            <div className="flex items-center space-x-2">
              <h1 className="text-2xl font-extrabold text-foreground">{stock.symbol}</h1>
              {getActionBadge(stock.action)}
            </div>
            <p className="text-xs text-muted-foreground">
              {stock.company_name} • Sàn:{" "}
              <strong className="text-foreground">{stock.exchange}</strong> • Ngành:{" "}
              <strong className="text-foreground">{stock.sector}</strong>
            </p>
          </div>
        </div>

        <div className="text-right font-mono">
          <span className="block text-[10px] text-muted-foreground uppercase">
            Giá đóng cửa gần nhất
          </span>
          <span className="text-2xl font-bold text-foreground">
            {formatVnd(stock.trade_plan.current_price)}
          </span>
        </div>
      </div>

      {/* Grid Overview Metrics */}
      <div className="grid grid-cols-2 gap-3 font-mono sm:grid-cols-4">
        <div className="space-y-1 rounded-sm border border-border bg-card p-4 text-center">
          <span className="block text-[10px] text-muted-foreground uppercase">Signal Score</span>
          <span className="text-2xl font-extrabold text-foreground">
            {formatScore(stock.signal_score)}
          </span>
        </div>

        <div className="space-y-1 rounded-sm border border-border bg-card p-4 text-center">
          <span className="block text-[10px] text-muted-foreground uppercase">
            Risk-Adjusted Score
          </span>
          <span className="text-2xl font-extrabold text-trend-up-text">
            {formatScore(stock.risk_adjusted_score)}
          </span>
        </div>

        <div className="space-y-1 rounded-sm border border-border bg-card p-4 text-center">
          <span className="block text-[10px] text-muted-foreground uppercase">
            Độ Tin Cậy Model (Heuristic)
          </span>
          <span className="text-2xl font-extrabold text-foreground">
            {stock.confidence != null ? `${Math.round(stock.confidence * 100)}%` : "—"}
          </span>
        </div>

        <div className="space-y-1 rounded-sm border border-border bg-card p-4 text-center">
          <span className="block text-[10px] text-muted-foreground uppercase">Mức Độ Rủi Ro</span>
          <span className="text-base font-bold text-foreground">
            {formatRisk(stock.risk_level)}
          </span>
        </div>
      </div>

      {/* Action Plan (Trade Plan) */}
      <div className="space-y-3 rounded-sm border border-border bg-card p-4 font-mono">
        <h3 className="flex items-center text-xs font-bold text-foreground uppercase">
          <Target className="mr-1.5 h-4 w-4 text-trend-up-text" /> Kế Hoạch Giao Dịch & Quản Trị Vốn
          (Trade Plan)
        </h3>
        <div className="grid grid-cols-1 gap-3 text-xs sm:grid-cols-3 lg:grid-cols-6">
          <div className="rounded-sm border border-border bg-background p-3">
            <span className="block text-[9px] text-muted-foreground uppercase">Vùng Mua Thấp</span>
            <span className="font-bold text-foreground">
              {isBuy ? formatVnd(stock.trade_plan.entry_low) : "—"}
            </span>
          </div>
          <div className="rounded-sm border border-border bg-background p-3">
            <span className="block text-[9px] text-muted-foreground uppercase">Vùng Mua Cao</span>
            <span className="font-bold text-foreground">
              {isBuy ? formatVnd(stock.trade_plan.entry_high) : "—"}
            </span>
          </div>
          <div className="rounded-sm border border-border bg-background p-3">
            <span className="block text-[9px] text-muted-foreground uppercase">Mục Tiêu TP1</span>
            <span className="font-bold text-trend-up-text">{formatVnd(stock.trade_plan.tp1)}</span>
          </div>
          <div className="rounded-sm border border-border bg-background p-3">
            <span className="block text-[9px] text-muted-foreground uppercase">Mục Tiêu TP2</span>
            <span className="font-bold text-trend-up-text">{formatVnd(stock.trade_plan.tp2)}</span>
          </div>
          <div className="rounded-sm border border-border bg-background p-3">
            <span className="block text-[9px] text-muted-foreground uppercase">
              Dừng Lỗ Stop Loss
            </span>
            <span className="font-bold text-trend-down-text">
              {formatVnd(stock.trade_plan.stop_loss)}
            </span>
          </div>
          <div className="rounded-sm border border-border bg-background p-3">
            <span className="block text-[9px] text-muted-foreground uppercase">
              Tỷ Trọng Khuyến Nghị
            </span>
            <span className="font-bold text-foreground">
              {stock.trade_plan.position_percent != null
                ? `${stock.trade_plan.position_percent}%`
                : "0%"}
            </span>
          </div>
        </div>
      </div>

      {/* Technical Evidence & Divergence */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* Reasons / Investment Thesis */}
        <div className="space-y-3 rounded-sm border border-border bg-card p-4">
          <h4 className="flex items-center font-mono text-xs font-bold text-trend-up-text uppercase">
            <Sparkles className="mr-1.5 h-4 w-4" /> Luận Điểm Đầu Tư & Bằng Chứng Định Lượng
          </h4>
          {stock.reasons && stock.reasons.length > 0 ? (
            <ul className="list-disc space-y-2 pl-4 text-xs text-foreground">
              {stock.reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">
              Không có luận điểm dương nào được thỏa mãn.
            </p>
          )}
        </div>

        {/* Multi-timeframe Divergence Signals */}
        <div className="space-y-3 rounded-sm border border-border bg-card p-4">
          <h4 className="flex items-center font-mono text-xs font-bold text-foreground uppercase">
            <Activity className="mr-1.5 h-4 w-4 text-trend-up-text" /> Tín Hiệu Phân Kỳ Đa Khung
            Thời Gian (1H, 1D, 1W, 1M)
          </h4>
          <div className="grid grid-cols-2 gap-3 font-mono text-xs sm:grid-cols-4">
            {tfs.map((tf) => {
              const sig = stock.divergence?.[tf] || "NONE";
              return (
                <div
                  key={tf}
                  className="rounded-sm border border-border bg-background p-3 text-center"
                >
                  <span className="block text-[10px] text-muted-foreground uppercase">{tf}</span>
                  <span
                    className={cn(
                      "mt-1 inline-block font-bold",
                      sig === "BULLISH"
                        ? "text-trend-up-text"
                        : sig === "BEARISH"
                          ? "text-trend-down-text"
                          : "text-muted-foreground",
                    )}
                  >
                    {sig === "BULLISH"
                      ? "Phân kỳ Dương"
                      : sig === "BEARISH"
                        ? "Phân kỳ Âm"
                        : "Bình thường"}
                  </span>
                </div>
              );
            })}
          </div>
          <p className="text-[11px] text-muted-foreground">
            Phân kỳ dương (Bullish Divergence) cảnh báo tín hiệu tạo đáy/tăng trưởng; Phân kỳ âm
            (Bearish Divergence) báo hiệu đỉnh điều chỉnh.
          </p>
        </div>
      </div>

      {/* Risk Metrics T+2.5 & Invalidation */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* Risk Metrics */}
        <div className="space-y-3 rounded-sm border border-border bg-card p-4 font-mono">
          <h4 className="flex items-center text-xs font-bold text-trend-down-text uppercase">
            <BarChart3 className="mr-1.5 h-4 w-4" /> Chỉ Số Rủi Ro Định Lượng T+2.5
          </h4>
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="rounded-sm border border-border bg-background p-3">
              <span className="block text-[9px] text-muted-foreground uppercase">
                Historical VaR (95% T+2.5)
              </span>
              <span className="font-bold text-foreground">
                {stock.risk_metrics.var_t25 != null
                  ? `${(stock.risk_metrics.var_t25 * 100).toFixed(2)}%`
                  : "N/A"}
              </span>
            </div>
            <div className="rounded-sm border border-border bg-background p-3">
              <span className="block text-[9px] text-muted-foreground uppercase">
                Expected Shortfall (ES T+2.5)
              </span>
              <span className="font-bold text-foreground">
                {stock.risk_metrics.es_t25 != null
                  ? `${(stock.risk_metrics.es_t25 * 100).toFixed(2)}%`
                  : "N/A"}
              </span>
            </div>
            <div className="rounded-sm border border-border bg-background p-3">
              <span className="block text-[9px] text-muted-foreground uppercase">
                Biến Động 60 Ngày Volatility
              </span>
              <span className="font-bold text-foreground">
                {stock.risk_metrics.volatility_60d != null
                  ? `${(stock.risk_metrics.volatility_60d * 100).toFixed(1)}%`
                  : "N/A"}
              </span>
            </div>
            <div className="rounded-sm border border-border bg-background p-3">
              <span className="block text-[9px] text-muted-foreground uppercase">
                Sụt Giảm Tối Đa Max Drawdown
              </span>
              <span className="font-bold text-foreground">
                {stock.risk_metrics.max_drawdown != null
                  ? `${(stock.risk_metrics.max_drawdown * 100).toFixed(1)}%`
                  : "N/A"}
              </span>
            </div>
          </div>
        </div>

        {/* Invalidation Conditions & Warnings */}
        <div className="space-y-3 rounded-sm border border-border bg-card p-4">
          <h4 className="flex items-center font-mono text-xs font-bold text-trend-down-text uppercase">
            <ShieldAlert className="mr-1.5 h-4 w-4" /> Điều Kiện Vô Hiệu Hóa (Invalidation
            Conditions)
          </h4>
          {stock.invalidation && stock.invalidation.length > 0 ? (
            <ul className="list-disc space-y-1.5 pl-4 text-xs text-foreground">
              {stock.invalidation.map((inv, idx) => (
                <li key={idx}>{inv}</li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">Không có điều kiện vô hiệu hóa bổ sung.</p>
          )}

          {stock.warnings && stock.warnings.length > 0 && (
            <div className="space-y-1 border-t border-border pt-2">
              <span className="flex items-center font-mono text-[10px] font-bold text-trend-down-text uppercase">
                <AlertTriangle className="mr-1 h-3 w-3" /> Cảnh Báo Rủi Ro
              </span>
              <ul className="list-disc space-y-1 pl-4 text-xs text-muted-foreground">
                {stock.warnings.map((w, idx) => (
                  <li key={idx}>{w}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      {/* Quantitative Disclaimer */}
      <div className="space-y-1 rounded-sm border border-border bg-muted/30 p-4 text-xs text-muted-foreground">
        <span className="flex items-center font-mono font-bold text-foreground">
          <HelpCircle className="mr-1.5 h-4 w-4" /> Miễn Trừ Tách Biệt & Bản Chất Định Lượng
        </span>
        <p>
          VN Invest là công cụ phân tích và khuyến nghị định lượng dựa trên dữ liệu giao dịch lịch
          sử. Kết quả không phải là tư vấn đầu tư cá nhân và không đảm bảo lợi nhuận chắc chắn.
          Người dùng cần tự đánh giá rủi ro trước khi thực hiện giao dịch.
        </p>
      </div>
    </div>
  );
}
