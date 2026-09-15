import { Link } from "@tanstack/react-router";
import { AlertTriangle, ArrowRight, CheckCircle2, ShieldAlert, Target } from "lucide-react";

import type { Recommendation } from "@/types/recommendation";

import { Badge } from "@/components/ui/badge";
import { formatRisk, formatScore, formatVnd } from "@/lib/format";

interface RecommendationCardProps {
  recommendation: Recommendation;
  rank?: number;
}

export function RecommendationCard({ recommendation: r, rank }: RecommendationCardProps) {
  const getActionBadge = (action: string) => {
    switch (action) {
      case "BUY":
        return <Badge variant="success">MUA (BUY)</Badge>;
      case "WATCH":
        return <Badge variant="warning">THEO DÕI (WATCH)</Badge>;
      case "HOLD":
        return <Badge variant="outline">NẮM GIỮ (HOLD)</Badge>;
      case "SELL":
        return <Badge variant="destructive">BÁN (SELL)</Badge>;
      case "AVOID":
        return <Badge variant="destructive">TRÁNH (AVOID)</Badge>;
      default:
        return <Badge variant="outline">{action}</Badge>;
    }
  };

  const isBuy = r.action === "BUY" || r.action === "WATCH";

  return (
    <div className="flex flex-col justify-between space-y-4 rounded-sm border border-border bg-card p-4 transition-all hover:border-foreground/30">
      {/* Header */}
      <div className="flex items-start justify-between border-b border-border pb-3">
        <div className="space-y-1">
          <div className="flex items-center space-x-2">
            {rank !== undefined && (
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-foreground font-mono text-[10px] font-bold text-background">
                #{rank}
              </span>
            )}
            <span className="text-lg font-extrabold text-foreground">{r.symbol}</span>
            {getActionBadge(r.action)}
          </div>
          <p className="line-clamp-1 text-[11px] text-muted-foreground">
            {r.company_name} • {r.exchange} • {r.sector}
          </p>
        </div>
        <div className="text-right font-mono">
          <span className="block text-[9px] text-muted-foreground uppercase">Giá hiện tại</span>
          <span className="text-sm font-bold text-foreground">
            {formatVnd(r.trade_plan.current_price)}
          </span>
        </div>
      </div>

      {/* Metric Badges */}
      <div className="grid grid-cols-3 gap-2 text-center font-mono text-[11px]">
        <div className="rounded-sm border border-border bg-background p-2">
          <span className="block text-[9px] text-muted-foreground uppercase">Signal Score</span>
          <span className="font-extrabold text-foreground">{formatScore(r.signal_score)}</span>
        </div>
        <div className="rounded-sm border border-border bg-background p-2">
          <span className="block text-[9px] text-muted-foreground uppercase">Rủi Ro Chỉnh</span>
          <span className="font-extrabold text-trend-up-text">
            {formatScore(r.risk_adjusted_score)}
          </span>
        </div>
        <div className="rounded-sm border border-border bg-background p-2">
          <span className="block text-[9px] text-muted-foreground uppercase">Độ Tin Cậy (Model)</span>
          <span className="font-bold text-foreground">
            {r.confidence != null ? `${Math.round(r.confidence * 100)}%` : "—"}
          </span>
        </div>
      </div>

      {/* Trade Plan Summary */}
      <div className="space-y-1.5 rounded-sm border border-border bg-muted/30 p-3 font-mono text-xs">
        <div className="flex items-center justify-between text-[11px]">
          <span className="flex items-center text-muted-foreground">
            <Target className="mr-1 h-3 w-3 text-trend-up-text" /> Vùng Mua Khuyến Nghị:
          </span>
          <span className="font-bold text-foreground">
            {isBuy && r.trade_plan.entry_low != null
              ? `${formatVnd(r.trade_plan.entry_low)} - ${formatVnd(r.trade_plan.entry_high)}`
              : "Không khuyến nghị"}
          </span>
        </div>
        <div className="flex items-center justify-between text-[11px]">
          <span className="text-muted-foreground">Mục Tiêu TP1 / Cắt Lỗ SL:</span>
          <span className="font-bold text-foreground">
            {formatVnd(r.trade_plan.tp1)} / {formatVnd(r.trade_plan.stop_loss)}
          </span>
        </div>
        <div className="flex items-center justify-between text-[11px]">
          <span className="text-muted-foreground">Tỷ Lệ Risk/Reward:</span>
          <span className="font-bold text-foreground">
            {r.trade_plan.risk_reward ? `1:${r.trade_plan.risk_reward}` : "—"}
          </span>
        </div>
      </div>

      {/* Key Reasons / Thesis */}
      {r.reasons && r.reasons.length > 0 && (
        <div className="space-y-1 text-xs">
          <span className="flex items-center font-mono text-[10px] font-bold text-trend-up-text uppercase">
            <CheckCircle2 className="mr-1 h-3 w-3" /> Lý Do Luận Điểm:
          </span>
          <p className="line-clamp-2 text-[11px] text-foreground/90">{r.reasons[0]}</p>
        </div>
      )}

      {/* Risk Level Warning */}
      {r.warnings && r.warnings.length > 0 && (
        <div className="space-y-1 text-xs">
          <span className="flex items-center font-mono text-[10px] font-bold text-trend-down-text uppercase">
            <AlertTriangle className="mr-1 h-3 w-3" /> Cảnh Báo ({formatRisk(r.risk_level)}):
          </span>
          <p className="line-clamp-1 text-[11px] text-muted-foreground">{r.warnings[0]}</p>
        </div>
      )}

      {/* Action Footer */}
      <div className="flex items-center justify-between border-t border-border pt-2">
        <span className="flex items-center font-mono text-[10px] text-muted-foreground">
          <ShieldAlert className="mr-1 h-3 w-3 text-subtle-foreground" />
          Tỷ trọng:{" "}
          {r.trade_plan.position_percent != null ? `${r.trade_plan.position_percent}%` : "0%"}
        </span>
        <Link
          to="/stock/$symbol"
          params={{ symbol: r.symbol }}
          className="inline-flex items-center font-mono text-xs font-bold text-foreground hover:underline"
        >
          Xem Phân Tích <ArrowRight className="ml-1 h-3.5 w-3.5" />
        </Link>
      </div>
    </div>
  );
}
