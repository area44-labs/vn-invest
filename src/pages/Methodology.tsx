import { Link } from "@tanstack/react-router";
import {
  ArrowLeft,
  BookOpen,
  ShieldAlert,
  Sparkles,
  Target,
  Activity,
  BarChart3,
} from "lucide-react";

export function Methodology() {
  return (
    <div className="mx-auto max-w-4xl space-y-8">
      {/* Header Navigation */}
      <div className="flex items-center space-x-3 border-b border-border pb-4">
        <Link
          to="/"
          className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-sm border border-border bg-card text-muted-foreground hover:bg-accent"
          title="Quay lại Dashboard"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-extrabold text-foreground">
            <BookOpen className="h-6 w-6 text-trend-up-text" /> Phương Pháp Luận Định Lượng
            (Methodology)
          </h1>
          <p className="text-xs text-muted-foreground">
            Giải thích chi tiết quy trình tính toán, chấm điểm Signal Score, mô hình rủi ro T+2.5 và
            quy tắc giao dịch.
          </p>
        </div>
      </div>

      {/* Visual Pipeline Banner */}
      <div className="space-y-3 rounded-sm border border-border bg-card p-4 font-mono text-xs">
        <span className="block font-bold tracking-wider text-foreground uppercase">
          Sơ Đồ Pipeline Xử Lý Định Lượng VN Invest
        </span>
        <div className="grid grid-cols-2 gap-2 text-center sm:grid-cols-5">
          <div className="rounded border border-border bg-background p-2">
            <span className="block font-bold text-foreground">1. Market Regime</span>
            <span className="text-[10px] text-muted-foreground">Phân tích xu hướng chung</span>
          </div>
          <div className="rounded border border-border bg-background p-2">
            <span className="block font-bold text-foreground">2. Signal Score</span>
            <span className="text-[10px] text-muted-foreground">Kỹ thuật & Xu hướng</span>
          </div>
          <div className="rounded border border-border bg-background p-2">
            <span className="block font-bold text-foreground">3. Divergence</span>
            <span className="text-[10px] text-muted-foreground">Phân kỳ 1H, 1D, 1W, 1M</span>
          </div>
          <div className="rounded border border-border bg-background p-2">
            <span className="block font-bold text-foreground">4. Risk T+2.5</span>
            <span className="text-[10px] text-muted-foreground">VaR, ES, Volatility, MDD</span>
          </div>
          <div className="rounded border border-border bg-background p-2">
            <span className="block font-bold text-trend-up-text">5. Khuyến Nghị</span>
            <span className="text-[10px] text-muted-foreground">BUY / WATCH / HOLD / SELL</span>
          </div>
        </div>
      </div>

      {/* Section 1: Market Regime */}
      <div className="space-y-3 rounded-sm border border-border bg-card p-5">
        <h2 className="flex items-center gap-2 text-base font-bold text-foreground">
          <Activity className="h-5 w-5 text-trend-up-text" /> 1. Chế Độ Thị Trường (Market Regime)
        </h2>
        <p className="text-xs leading-relaxed text-muted-foreground">
          Thị trường Việt Nam được đánh giá đa nhân tố thông qua chỉ số VN-Index, chỉ số VN30, tỷ lệ
          độ rộng thị trường (Market Breadth - tỉ lệ cổ phiếu nằm trên MA20), khối lượng giao dịch
          và biến động annualized.
        </p>
        <ul className="list-disc space-y-1.5 pl-5 text-xs text-foreground">
          <li>
            <strong>STRONG_BULL:</strong> Xu hướng tăng mạnh mẽ, độ rộng thị trường rộng khắp (&gt;
            65%), thanh khoản tích cực. Cho phép giải ngân các cơ hội breakout đỉnh.
          </li>
          <li>
            <strong>BULL:</strong> Xu hướng tăng ổn định, hỗ trợ xu hướng vững chắc.
          </li>
          <li>
            <strong>DEFENSIVE:</strong> Thị trường giằng co, phân hóa cao. Yêu cầu điểm số Signal
            Score khắt khe hơn để đưa ra khuyến nghị BUY.
          </li>
          <li>
            <strong>BEAR:</strong> Xu hướng giảm trung hạn. Tăng cường mức phạt rủi ro, hạn chế
            khuyến nghị MUA.
          </li>
          <li>
            <strong>PANIC:</strong> Biến động cực đại hoặc VN-Index sụt giảm mạnh. Toàn bộ cổ phiếu
            bị ép về trạng thái AVOID để bảo vệ vốn.
          </li>
        </ul>
      </div>

      {/* Section 2: Signal Score & Technical Signals */}
      <div className="space-y-3 rounded-sm border border-border bg-card p-5">
        <h2 className="flex items-center gap-2 text-base font-bold text-foreground">
          <Sparkles className="h-5 w-5 text-trend-up-text" /> 2. Điểm Số Signal Score & Chỉ Báo Kỹ
          Thuật
        </h2>
        <p className="text-xs leading-relaxed text-muted-foreground">
          Signal Score được chấm trên thang điểm 0 - 100 dựa trên các chỉ báo kỹ thuật chuẩn hóa:
        </p>
        <div className="grid grid-cols-1 gap-3 font-mono text-xs sm:grid-cols-2">
          <div className="rounded border border-border bg-background p-3">
            <span className="block font-bold text-foreground">Đường Xu Hướng MA20 & MA50</span>
            <span className="text-[11px] text-muted-foreground">
              Xác định xu hướng ngắn và trung hạn của giá cổ phiếu.
            </span>
          </div>
          <div className="rounded border border-border bg-background p-3">
            <span className="block font-bold text-foreground">Động Lượng MACD Histogram</span>
            <span className="text-[11px] text-muted-foreground">
              Xác nhận sự gia tăng đà tăng hoặc cảnh báo áp lực điều chỉnh.
            </span>
          </div>
          <div className="rounded border border-border bg-background p-3">
            <span className="block font-bold text-foreground">Khối Lượng & Thanh Khoản</span>
            <span className="text-[11px] text-muted-foreground">
              So sánh khối lượng thực tế với bình quân 20 phiên (Vol MA20).
            </span>
          </div>
          <div className="rounded border border-border bg-background p-3">
            <span className="block font-bold text-foreground">
              Sức Mạnh Tương Quan (RS vs VN-Index)
            </span>
            <span className="text-[11px] text-muted-foreground">
              Đo lường mức vượt trội của cổ phiếu so với diễn biến VN-Index.
            </span>
          </div>
        </div>
      </div>

      {/* Section 3: Risk Horizon T+2.5 & Risk-Adjusted Score */}
      <div className="space-y-3 rounded-sm border border-border bg-card p-5">
        <h2 className="flex items-center gap-2 text-base font-bold text-foreground">
          <BarChart3 className="h-5 w-5 text-trend-down-text" /> 3. Mô Hình Rủi Ro T+2.5 &
          Risk-Adjusted Score
        </h2>
        <p className="text-xs leading-relaxed text-muted-foreground">
          Do đặc thù chu kỳ thanh toán T+2.5 tại Việt Nam, rủi ro giữ vị thế 3 phiên giao dịch được
          lượng hóa:
        </p>
        <ul className="list-disc space-y-1.5 pl-5 text-xs text-foreground">
          <li>
            <strong>Historical VaR (95% T+2.5):</strong> Mức sụt giảm tối đa dự kiến ở mức tin cậy
            95% trong vòng 3 phiên.
          </li>
          <li>
            <strong>Expected Shortfall (ES T+2.5):</strong> Mức thua lỗ trung bình trong trường hợp
            xảy ra rủi ro đuôi (tail risk).
          </li>
          <li>
            <strong>Liquidity Score (0 - 100):</strong> Thứ hạng phần trăm (percentile rank) giá trị
            giao dịch bình quân 20 phiên trong toàn bộ universe.
          </li>
          <li>
            <strong>Risk-Adjusted Score:</strong> Công thức điều chỉnh điểm Signal minh bạch dựa
            trên biến động 60 ngày, Max Drawdown và hệ số Market Regime.
          </li>
        </ul>
      </div>

      {/* Section 4: Trade Plan & Invalidation */}
      <div className="space-y-3 rounded-sm border border-border bg-card p-5">
        <h2 className="flex items-center gap-2 text-base font-bold text-foreground">
          <Target className="h-5 w-5 text-trend-up-text" /> 4. Kế Hoạch Giao Dịch & Điều Kiện Vô
          Hiệu Hóa
        </h2>
        <p className="text-xs leading-relaxed text-muted-foreground">
          Mỗi khuyến nghị MUA đi kèm Kế Hoạch Giao Dịch cụ thể:
        </p>
        <div className="grid grid-cols-1 gap-3 font-mono text-xs sm:grid-cols-3">
          <div className="rounded border border-border bg-background p-3">
            <span className="block font-bold text-foreground">Vùng Giá Mua</span>
            <span className="text-[11px] text-muted-foreground">
              Khoảng giá tối ưu giải ngân dựa trên bước giá thực tế (tick size).
            </span>
          </div>
          <div className="rounded border border-border bg-background p-3">
            <span className="block font-bold text-trend-up-text">
              Mục Tiêu Chốt Lời (TP1 / TP2)
            </span>
            <span className="text-[11px] text-muted-foreground">
              Tính toán dựa trên bội số rủi ro (Risk-Reward &gt;= 1.5).
            </span>
          </div>
          <div className="rounded border border-border bg-background p-3">
            <span className="block font-bold text-trend-down-text">
              Dừng Lỗ Bắt Buộc (Stop Loss)
            </span>
            <span className="text-[11px] text-muted-foreground">
              Xác định từ ATR biến động và đáy gần nhất 5 phiên.
            </span>
          </div>
        </div>
      </div>

      {/* Disclaimer */}
      <div className="space-y-2 rounded-sm border border-border bg-muted/40 p-4 font-mono text-xs">
        <span className="flex items-center font-bold text-foreground">
          <ShieldAlert className="mr-1.5 h-4 w-4 text-subtle-foreground" /> Tuyên Bố Miễn Trừ Trách
          Nhiệm
        </span>
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          VN Invest là hệ thống phân tích định lượng hoàn toàn tự động, vận hành trên dữ liệu lô EOD
          (End Of Day). Kết quả khuyến nghị mang tính chất tham khảo kỹ thuật, không cấu thành lời
          khuyên đầu tư tài chính cá nhân. Nhà đầu tư tự chịu trách nhiệm hoàn toàn đối với quyết
          định giao dịch trên thị trường.
        </p>
      </div>
    </div>
  );
}
