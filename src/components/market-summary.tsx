import { ArrowUpRight, ArrowDownRight, DollarSign } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface IndexData {
  name: string;
  value: number | null;
  change: number | null;
  changePercent: number | null;
  volume: string;
}

interface MarketSummaryProps {
  marketData: {
    vnIndex: IndexData;
    regimeStatus: IndexData;
    breadth: IndexData;
    totalStocks: IndexData;
  };
  buyCount: number;
  sellCount: number;
}

export function MarketSummary({ marketData }: MarketSummaryProps) {
  const renderIndexCard = (data: IndexData) => {
    const isPositive = data.changePercent != null && data.changePercent >= 0;
    const hasData = data.value != null;

    return (
      <Card
        key={data.name}
        className="overflow-hidden border-border bg-background transition-colors"
      >
        <CardContent className="p-4 sm:p-5">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
              {data.name}
            </span>
            {hasData && data.changePercent != null ? (
              <span
                className={cn(
                  "inline-flex items-center rounded-sm px-1.5 py-0.5 font-mono text-[10px] tracking-tight",
                  isPositive
                    ? "border border-trend-up-border bg-trend-up-bg text-trend-up-text"
                    : "border border-trend-down-border bg-trend-down-bg text-trend-down-text",
                )}
              >
                {isPositive ? (
                  <ArrowUpRight className="mr-0.5 h-3 w-3" />
                ) : (
                  <ArrowDownRight className="mr-0.5 h-3 w-3" />
                )}
                {isPositive ? "+" : ""}
                {data.changePercent.toFixed(2)}%
              </span>
            ) : (
              <span className="rounded-sm border border-border bg-muted/40 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                N/A
              </span>
            )}
          </div>

          <div className="mt-3 flex items-baseline justify-between">
            <div>
              <span className="text-lg font-bold tracking-tight text-foreground tabular-nums">
                {hasData
                  ? data.value!.toLocaleString("vi-VN", {
                      minimumFractionDigits: 1,
                      maximumFractionDigits: 2,
                    })
                  : "Không có dữ liệu"}
              </span>
              {data.change != null && (
                <span
                  className={cn(
                    "ml-1.5 text-[11px] font-medium tabular-nums",
                    isPositive ? "text-trend-up-text" : "text-trend-down-text",
                  )}
                >
                  {isPositive ? "+" : ""}
                  {data.change.toLocaleString("vi-VN", { minimumFractionDigits: 2 })}
                </span>
              )}
            </div>
          </div>

          <div className="mt-3 flex items-center justify-between border-t border-border pt-2.5 font-mono text-[10px] text-subtle-foreground">
            <span className="flex items-center">
              <DollarSign className="mr-1 h-3 w-3 text-muted-foreground" />
              Thông tin
            </span>
            <span className="font-semibold text-foreground">{data.volume}</span>
          </div>
        </CardContent>
      </Card>
    );
  };

  return (
    <section className="space-y-4">
      {/* Title */}
      <div className="flex items-center space-x-2">
        <div className="h-1.5 w-1.5 bg-foreground" />
        <h2 className="font-mono text-[11px] tracking-wider text-muted-foreground uppercase">
          Tổng Quan Trạng Thái Thị Trường & Định Lượng
        </h2>
      </div>

      {/* Grid of cards */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {renderIndexCard(marketData.vnIndex)}
        {renderIndexCard(marketData.regimeStatus)}
        {renderIndexCard(marketData.breadth)}
        {renderIndexCard(marketData.totalStocks)}
      </div>
    </section>
  );
}
