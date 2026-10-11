import {
  ArrowUpRight,
  ArrowDownRight,
  Activity,
  Layers,
  PieChart,
  ShieldCheck,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export interface VnIndexCardData {
  name: string;
  value: number | null;
  changePercent: number | null;
  volumeRatio: string;
}

export interface RegimeCardData {
  name: string;
  regime: string;
  regimeScore: number | null;
  confidence: number | null;
}

export interface BreadthCardData {
  name: string;
  breadthRatio: number | null;
  description: string;
}

export interface UniverseCardData {
  name: string;
  totalScanned: number;
  summaryText: string;
}

export interface MarketSummaryProps {
  marketData: {
    vnIndex: VnIndexCardData;
    regimeStatus: RegimeCardData;
    breadth: BreadthCardData;
    totalStocks: UniverseCardData;
  };
  buyCount?: number;
  sellCount?: number;
}

export function MarketSummary({ marketData }: MarketSummaryProps) {
  const { vnIndex, regimeStatus, breadth, totalStocks } = marketData;

  const isVnIndexPositive = vnIndex.changePercent != null && vnIndex.changePercent >= 0;
  const hasVnIndexData = vnIndex.value != null;

  return (
    <section className="space-y-4">
      {/* Section Title */}
      <div className="flex items-center space-x-2">
        <div className="h-1.5 w-1.5 bg-foreground" />
        <h2 className="font-mono text-[11px] tracking-wider text-muted-foreground uppercase">
          Tổng Quan Trạng Thái Thị Trường & Định Lượng
        </h2>
      </div>

      {/* Grid of 4 Cards */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {/* Card 1: VN-INDEX */}
        <Card className="overflow-hidden border-border bg-background transition-colors">
          <CardContent className="p-4 sm:p-5">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                {vnIndex.name}
              </span>
              {hasVnIndexData && vnIndex.changePercent != null ? (
                <span
                  className={cn(
                    "inline-flex items-center rounded-sm px-1.5 py-0.5 font-mono text-[10px] font-semibold tracking-tight",
                    isVnIndexPositive
                      ? "border border-trend-up-border bg-trend-up-bg text-trend-up-text"
                      : "border border-trend-down-border bg-trend-down-bg text-trend-down-text",
                  )}
                >
                  {isVnIndexPositive ? (
                    <ArrowUpRight className="mr-0.5 h-3 w-3" />
                  ) : (
                    <ArrowDownRight className="mr-0.5 h-3 w-3" />
                  )}
                  {isVnIndexPositive ? "+" : ""}
                  {vnIndex.changePercent.toFixed(2)}%
                </span>
              ) : (
                <Badge variant="outline" className="font-mono text-[10px]">
                  N/A
                </Badge>
              )}
            </div>

            <div className="mt-3 flex items-baseline justify-between">
              <span className="text-lg font-bold tracking-tight text-foreground tabular-nums">
                {hasVnIndexData
                  ? vnIndex.value!.toLocaleString("vi-VN", {
                      minimumFractionDigits: 1,
                      maximumFractionDigits: 2,
                    })
                  : "—"}
              </span>
            </div>

            <div className="mt-3 flex items-center justify-between border-t border-border pt-2.5 font-mono text-[10px] text-subtle-foreground">
              <span className="flex items-center text-muted-foreground">
                <Activity className="mr-1 h-3 w-3" />
                Khối lượng
              </span>
              <span className="font-semibold text-foreground">{vnIndex.volumeRatio}</span>
            </div>
          </CardContent>
        </Card>

        {/* Card 2: Market Regime & Confidence */}
        <Card className="overflow-hidden border-border bg-background transition-colors">
          <CardContent className="p-4 sm:p-5">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                {regimeStatus.name}
              </span>
              {regimeStatus.confidence != null ? (
                <Badge variant="secondary" className="font-mono text-[10px]">
                  Độ tin cậy {Math.round(regimeStatus.confidence * 100)}%
                </Badge>
              ) : (
                <Badge variant="outline" className="font-mono text-[10px]">
                  N/A
                </Badge>
              )}
            </div>

            <div className="mt-3 flex items-baseline justify-between">
              <span className="text-lg font-bold tracking-tight text-foreground">
                {regimeStatus.regime}
              </span>
            </div>

            <div className="mt-3 flex items-center justify-between border-t border-border pt-2.5 font-mono text-[10px] text-subtle-foreground">
              <span className="flex items-center text-muted-foreground">
                <ShieldCheck className="mr-1 h-3 w-3" />
                Score
              </span>
              <span className="font-semibold text-foreground">
                {regimeStatus.regimeScore != null ? regimeStatus.regimeScore.toFixed(1) : "—"}
              </span>
            </div>
          </CardContent>
        </Card>

        {/* Card 3: Market Breadth (>MA20) */}
        <Card className="overflow-hidden border-border bg-background transition-colors">
          <CardContent className="p-4 sm:p-5">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                {breadth.name}
              </span>
              <Badge variant="outline" className="font-mono text-[10px]">
                Tỉ lệ
              </Badge>
            </div>

            <div className="mt-3 flex items-baseline justify-between">
              <span className="text-lg font-bold tracking-tight text-foreground tabular-nums">
                {breadth.breadthRatio != null ? `${(breadth.breadthRatio * 100).toFixed(1)}%` : "—"}
              </span>
            </div>

            <div className="mt-3 flex items-center justify-between border-t border-border pt-2.5 font-mono text-[10px] text-subtle-foreground">
              <span className="flex items-center text-muted-foreground">
                <PieChart className="mr-1 h-3 w-3" />
                Mô tả
              </span>
              <span className="font-semibold text-foreground">{breadth.description}</span>
            </div>
          </CardContent>
        </Card>

        {/* Card 4: Universe Total Scanned */}
        <Card className="overflow-hidden border-border bg-background transition-colors">
          <CardContent className="p-4 sm:p-5">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                {totalStocks.name}
              </span>
              <Badge variant="secondary" className="font-mono text-[10px]">
                Mã CP
              </Badge>
            </div>

            <div className="mt-3 flex items-baseline justify-between">
              <span className="text-lg font-bold tracking-tight text-foreground tabular-nums">
                {totalStocks.totalScanned}
              </span>
            </div>

            <div className="mt-3 flex items-center justify-between border-t border-border pt-2.5 font-mono text-[10px] text-subtle-foreground">
              <span className="flex items-center text-muted-foreground">
                <Layers className="mr-1 h-3 w-3" />
                Phân bổ
              </span>
              <span className="font-semibold text-foreground">{totalStocks.summaryText}</span>
            </div>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
