import { createFileRoute } from "@tanstack/react-router";

import { loadStock } from "@/data/loader";
import { StockDetail } from "@/pages/StockDetail";

export const Route = createFileRoute("/stock/$symbol")({
  loader: async ({ params }) => {
    const stock = await loadStock(params.symbol);
    return { stock, symbol: params.symbol };
  },
  head: ({ params }) => ({
    meta: [
      {
        title: `${params.symbol.toUpperCase()} | Khuyến Nghị Định Lượng VN Invest`,
      },
      {
        name: "description",
        content: `Phân tích và khuyến nghị định lượng mã cổ phiếu ${params.symbol.toUpperCase()} dựa trên chỉ báo kỹ thuật, điểm Signal Score và quản trị rủi ro T+2.5.`,
      },
      {
        property: "og:title",
        content: `${params.symbol.toUpperCase()} Quantitative Recommendation | VN Invest`,
      },
      {
        property: "og:description",
        content: `Khuyến nghị Mua/Bán, điểm số Signal Score và kế hoạch giao dịch mã ${params.symbol.toUpperCase()} trên VN Invest.`,
      },
    ],
  }),
  component: StockDetailRouteComponent,
});

function StockDetailRouteComponent() {
  const { stock, symbol } = Route.useLoaderData();
  return <StockDetail symbol={symbol} initialStock={stock} />;
}
