import { useNavigate } from "@tanstack/react-router";
import { HelpCircle, FileText, Sparkles, ArrowDownRight } from "lucide-react";

import type { Recommendation } from "@/types/recommendation";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Tooltip } from "@/components/ui/tooltip";
import { formatRisk, formatVnd } from "@/lib/format";
import { cn } from "@/lib/utils";

interface StockTableProps {
  recommendations: Recommendation[];
  activeTab: string;
  setActiveTab: (tab: string) => void;
}

export function StockTable({ recommendations, activeTab, setActiveTab }: StockTableProps) {
  const navigate = useNavigate();

  const buyStocks = recommendations.filter((r) => r.action === "BUY" || r.action === "WATCH");
  const sellStocks = recommendations.filter(
    (r) => r.action === "SELL" || r.action === "HOLD" || r.action === "AVOID",
  );

  const renderDivergenceBadges = (r: Recommendation) => {
    if (!r.divergence) {
      return (
        <Badge variant="outline" className="font-mono text-[9px]">
          Không có phân kỳ
        </Badge>
      );
    }

    const tfs: ("1H" | "1D" | "1W" | "1M")[] = ["1H", "1D", "1W", "1M"];
    const badges = tfs
      .map((tf) => {
        const val = r.divergence?.[tf];
        if (val === "BULLISH" || val === "BEARISH") {
          return { tf, type: val };
        }
        return null;
      })
      .filter(
        (item): item is { tf: "1H" | "1D" | "1W" | "1M"; type: "BULLISH" | "BEARISH" } =>
          item !== null,
      );

    if (badges.length === 0) {
      return (
        <Badge variant="outline" className="font-mono text-[9px]">
          Đồng thuận
        </Badge>
      );
    }

    return (
      <div className="flex flex-wrap items-center justify-center gap-1">
        {badges.map((b) => (
          <span
            key={b.tf}
            className={cn(
              "inline-flex items-center rounded px-1.5 py-0.5 font-mono text-[9px] font-bold",
              b.type === "BULLISH"
                ? "border border-trend-up-border bg-trend-up-bg text-trend-up-text"
                : "border border-trend-down-border bg-trend-down-bg text-trend-down-text",
            )}
          >
            {b.type === "BULLISH" ? `📈 ${b.tf}` : `📉 ${b.tf}`}
          </span>
        ))}
      </div>
    );
  };

  const renderTable = (data: Recommendation[]) => {
    if (data.length === 0) {
      return (
        <div className="flex flex-col items-center justify-center rounded-sm border border-dashed border-border bg-muted/20 p-12 text-center">
          <FileText className="mb-3 h-8 w-8 text-subtle-foreground" />
          <p className="text-xs font-bold text-foreground">Không tìm thấy mã khuyến nghị nào</p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            Vui lòng thay đổi từ khóa tìm kiếm hoặc đặt lại bộ lọc.
          </p>
        </div>
      );
    }

    return (
      <div className="overflow-x-auto rounded-sm border border-border bg-background transition-colors">
        <Table className="w-full border-collapse text-left">
          <TableHeader>
            <TableRow className="border-b border-border bg-muted/50 font-mono text-[10px] tracking-wider text-muted-foreground uppercase hover:bg-transparent">
              <TableHead className="h-auto px-4 py-3 font-bold text-muted-foreground">
                <div className="flex items-center gap-1">
                  Mã CP & Ngành
                  <Tooltip content="Mã giao dịch chứng khoán phân loại nhóm ngành">
                    <HelpCircle className="h-3 w-3 cursor-help text-muted-foreground" />
                  </Tooltip>
                </div>
              </TableHead>
              <TableHead className="h-auto px-4 py-3 text-right font-bold text-muted-foreground">
                <div className="flex items-center justify-end gap-1">
                  Giá hiện tại
                  <Tooltip content="Giá giao dịch khớp lệnh thực tế từ JSON">
                    <HelpCircle className="h-3 w-3 cursor-help text-muted-foreground" />
                  </Tooltip>
                </div>
              </TableHead>
              <TableHead className="h-auto px-4 py-3 text-center font-bold text-muted-foreground">
                <div className="flex items-center justify-center gap-1">
                  Tín hiệu Phân Kỳ
                  <Tooltip content="Trạng thái Phân kỳ Dương hoặc Phân kỳ Âm (1H / 1D / 1W / 1M)">
                    <HelpCircle className="h-3 w-3 cursor-help text-muted-foreground" />
                  </Tooltip>
                </div>
              </TableHead>
              <TableHead className="h-auto px-4 py-3 text-center font-bold text-muted-foreground">
                <div className="flex items-center justify-center gap-1">
                  Vùng giá khuyến nghị
                  <Tooltip content="Khoảng giá khuyến nghị Mua từ engine Python">
                    <HelpCircle className="h-3 w-3 cursor-help text-muted-foreground" />
                  </Tooltip>
                </div>
              </TableHead>
              <TableHead className="h-auto px-4 py-3 font-bold text-muted-foreground">
                <div className="flex items-center gap-1">
                  Giá Mục Tiêu & Cắt Lỗ
                  <Tooltip content="Mục tiêu chốt lời (TP1) và ngưỡng dừng lỗ (SL)">
                    <HelpCircle className="h-3 w-3 cursor-help text-muted-foreground" />
                  </Tooltip>
                </div>
              </TableHead>
              <TableHead className="h-auto px-4 py-3 text-center font-bold text-muted-foreground">
                <div className="flex items-center justify-center gap-1">
                  Mức rủi ro
                  <Tooltip content="Mức rủi ro định lượng (LOW / MEDIUM / HIGH)">
                    <HelpCircle className="h-3 w-3 cursor-help text-muted-foreground" />
                  </Tooltip>
                </div>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody className="divide-y divide-border text-xs text-foreground/85">
            {data.map((r) => {
              const isBuy = r.action === "BUY" || r.action === "WATCH";
              return (
                <TableRow
                  key={r.symbol}
                  onClick={() => navigate({ to: "/stock/$symbol", params: { symbol: r.symbol } })}
                  className="cursor-pointer border-b border-border transition-colors duration-150 hover:bg-muted/40"
                >
                  {/* Symbol & Company & Sector */}
                  <TableCell className="px-4 py-3">
                    <div className="flex flex-col">
                      <span className="flex items-center space-x-2">
                        <span className="text-sm font-bold text-foreground group-hover:underline">
                          {r.symbol}
                        </span>
                        <Badge variant="secondary" className="font-mono text-[9px]">
                          {r.sector}
                        </Badge>
                      </span>
                      <span className="mt-0.5 max-w-[180px] truncate text-[11px] text-muted-foreground sm:max-w-[240px]">
                        {r.company_name}
                      </span>
                    </div>
                  </TableCell>

                  {/* Current Price */}
                  <TableCell className="px-4 py-3 text-right tabular-nums">
                    <span className="text-xs font-bold text-foreground">
                      {formatVnd(r.trade_plan.current_price)}
                    </span>
                  </TableCell>

                  {/* Divergence Column */}
                  <TableCell className="px-4 py-3 text-center">
                    {renderDivergenceBadges(r)}
                  </TableCell>

                  {/* Buy/Sell Zone */}
                  <TableCell className="px-4 py-3 text-center">
                    <span
                      className={cn(
                        "inline-flex items-center rounded-sm px-2 py-0.5 text-[10px] font-bold",
                        isBuy
                          ? "border border-trend-up-border bg-trend-up-bg text-trend-up-text"
                          : "border border-trend-down-border bg-trend-down-bg text-trend-down-text",
                      )}
                    >
                      {isBuy && r.trade_plan.entry_low != null
                        ? `${formatVnd(r.trade_plan.entry_low)} - ${formatVnd(r.trade_plan.entry_high)}`
                        : "Không khuyến nghị"}
                    </span>
                  </TableCell>

                  {/* Targets & Stop Loss */}
                  <TableCell className="px-4 py-3">
                    <div className="flex flex-col space-y-1 font-mono text-[11px]">
                      <div className="flex items-center tabular-nums">
                        <span className="w-16 text-muted-foreground">Mục tiêu:</span>
                        <span className="font-bold text-trend-up-text">
                          {formatVnd(r.trade_plan.tp1)}
                        </span>
                      </div>
                      <div className="flex items-center tabular-nums">
                        <span className="w-16 text-muted-foreground">Cắt lỗ:</span>
                        <span className="font-bold text-trend-down-text">
                          {formatVnd(r.trade_plan.stop_loss)}
                        </span>
                      </div>
                    </div>
                  </TableCell>

                  {/* Risk Level */}
                  <TableCell className="px-4 py-3 text-center font-mono">
                    <Badge
                      variant={
                        r.risk_level === "LOW"
                          ? "success"
                          : r.risk_level === "HIGH"
                            ? "destructive"
                            : "warning"
                      }
                    >
                      {formatRisk(r.risk_level)}
                    </Badge>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    );
  };

  return (
    <div className="space-y-4">
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <div className="flex items-center justify-between border-b border-border pb-2">
          <TabsList>
            <TabsTrigger value="BUY" className="flex cursor-pointer items-center gap-1.5">
              <Sparkles className="h-3.5 w-3.5 text-trend-up-text" />
              Mã Khuyến Nghị Mua & Theo Dõi ({buyStocks.length})
            </TabsTrigger>
            <TabsTrigger value="SELL" className="flex cursor-pointer items-center gap-1.5">
              <ArrowDownRight className="h-3.5 w-3.5 text-trend-down-text" />
              Mã Bán / Nắm Giữ / Tránh ({sellStocks.length})
            </TabsTrigger>
          </TabsList>

          <div className="hidden font-mono text-[11px] tracking-tight text-subtle-foreground uppercase sm:block">
            Nhấp vào dòng để xem chi tiết cổ phiếu
          </div>
        </div>

        <TabsContent value="BUY">
          <div className="mt-2">{renderTable(buyStocks)}</div>
        </TabsContent>

        <TabsContent value="SELL">
          <div className="mt-2">{renderTable(sellStocks)}</div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
