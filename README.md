# README.md - VN Invest

[![GitHub Pages](https://github.com/area44-labs/vn-invest/actions/workflows/pages.yml/badge.svg)](https://area44-labs.github.io/vn-invest/)

**VN Invest** là hệ thống phân tích định lượng và sinh khuyến nghị chứng khoán tự động hóa cho thị trường Việt Nam (HOSE, HNX, UPCoM). Hệ thống kết hợp giữa **Python Quantitative Engine** (Python 3.14 + `uv` + Pandas v3 + NumPy v2.5) và **React Static Site Generation (SSG)** (TanStack Start + Vite+).

---

## 1. Tổng Quan Kiến Trúc (High-Level Architecture)

```
[ Market Data Providers (Vnstock) ]
               │
               ▼
┌─────────────────────────────────────────┐
│     Python Quantitative Pipeline        │
│  (Data Provider -> Domain -> Pipeline)  │
└────────────────────┬────────────────────┘
                     │ Validated JSON Artifacts
                     ▼
┌─────────────────────────────────────────┐
│     Generated Artifacts (generated/)    │
│  recommendations.json / market.json     │
│  monitoring.json / history/index.json   │
└────────────────────┬────────────────────┘
                     │ SSG Build (Vite+)
                     ▼
┌─────────────────────────────────────────┐
│   React Frontend (TanStack Start SSG)   │
│     Published to GitHub Pages / Vercel  │
└─────────────────────────────────────────┘
```

### Các Thành Phần Chính:

- **Data Provider & Validation Layer (`scripts/data_provider.py`, `scripts/lib/vietnam_market.py`)**: Kết nối Vnstock API, thực hiện kiểm định chất lượng dữ liệu OHLCV (canonical validation) và xử lý rate limit/cooldown.
- **Domain Contracts (`scripts/domain/`)**: Định nghĩa các model bất biến (frozen dataclasses) cho `OHLCVData`, `Universe`, `TradePlan`, `RiskAssessment`, `Recommendation`, `PipelineResult`.
- **Quantitative Engine (`scripts/lib/`)**: Tính toán điểm tín hiệu (Signal Score), mô hình rủi ro T+2.5, nhận diện trạng thái thị trường (Market Regime), backtest danh mục và giám sát vận hành/drift.
- **Pipeline Orchestration (`scripts/pipeline/`)**: Điểm thực thi chính qua 9 giai đoạn (from `DataAcquisitionStage` to `ArtifactPublishingStage`).
- **Static Artifacts (`generated/`)**: Chứa dữ liệu JSON tĩnh làm nguồn sự thật cho Frontend.
- **React SSG Frontend (`src/`)**: Giao diện hiển thị tĩnh đã qua kiểm định JSON Schema, không thực hiện tính toán tài chính ở client.

---

## 2. Quy Trình Thu Thập, Kiểm Định & Xuất Dữ Liệu

1. **Thu thập dữ liệu**: Tải dữ liệu lịch sử giá OHLCV của cổ phiếu và chỉ số VNINDEX/VN30 từ Vnstock.
2. **Kiểm định dữ liệu (Canonical Validation)**: Kiểm tra cấu trúc OHLCV, loại bỏ các giá trị hỏng (`NaN`, `Inf`), giá âm, khối lượng âm hoặc sai lệch thời gian (`data_as_of`).
3. **Tính toán định lượng**:
   - Xác định trạng thái thị trường (`BULLISH`, `BEARISH`, `SIDEWAYS`, `VOLATILE`, `NEUTRAL`).
   - Tính toán điểm kỹ thuật (RSI, MA, MACD, Volume Profile, Divergence) và quy đổi Signal Score (0-100).
   - Đánh giá rủi ro T+2.5 (VaR 95%, ES 95%, Max Drawdown 60D, Liquidity Score).
   - Lập kế hoạch giao dịch (Entry, Stop Loss, Take Profit, Position Sizing).
4. **Kiểm định Schema & Monitoring**: Kiểm tra tính hợp lệ của dữ liệu đầu ra với JSON Schema tại `schemas/recommendations.schema.json` và đánh giá Data/Model Drift.
5. **Xuất bản Artifacts**: Ghi dữ liệu vào thư mục `generated/` và cập nhật chỉ mục lịch sử `generated/history/index.json`.

---

## 3. Cấu Trúc File & Artifacts Sinh Ra (`generated/`)

- `generated/recommendations.json`: Danh sách khuyến nghị chứng khoán, thông số kỹ thuật, kế hoạch giao dịch và đánh giá rủi ro T+2.5.
- `generated/market.json`: Tổng quan trạng thái thị trường, độ rộng thị trường (Market Breadth) và chỉ số VNINDEX/VN30.
- `generated/monitoring.json`: Báo cáo giám sát vận hành pipeline, tỷ lệ bao phủ, độ tươi dữ liệu và chỉ số data/model drift.
- `generated/history/YYYY-MM-DD.json`: Báo cáo lịch sử theo mốc thời gian.
- `generated/history/index.json`: Chỉ mục danh sách các ngày có báo cáo lịch sử.

---

## 4. Cài Đặt & Phát Triển Tại Địa Phương (Local Development)

### Yêu Cầu Môi Trường:

- **Python**: `>= 3.14` (Quản lý môi trường và dependency bằng `uv`)
- **Frontend Toolchain**: `vite-plus` (`vp`)

### Các Lệnh Chuẩn Duy Nhất (Authoritative Commands):

#### A. Quản Lý Dependency:

```bash
# Cài đặt / đồng bộ dependency Python theo lockfile
uv sync --frozen

# Cài đặt dependency Frontend (Vite+)
vp install
```

#### B. Kiểm Thử Hệ Thống (Testing):

```bash
# Chạy bộ test suite Python chuẩn (CI-equivalent entry point)
uv run --frozen python scripts/tests/run_tests.py

# Chạy unit test mục tiêu cho 1 module cụ thể (mới sửa code)
uv run --frozen python -m unittest scripts/tests/test_domain.py
```

#### C. Linting & Formatting:

```bash
# Kiểm tra & sửa lỗi code Python (Ruff)
uv run --frozen ruff check --fix scripts
uv run --frozen ruff format scripts
uv run --frozen ruff check scripts
uv run --frozen ruff format --check scripts

# Kiểm tra & sửa lỗi Frontend (Vite+)
vp check --fix
```

#### D. Chạy Pipeline & Sinh Báo Cáo:

```bash
# Sinh báo cáo từ dữ liệu hiện có
uv run --frozen python scripts/generate_report.py

# Sinh báo cáo và cập nhật dữ liệu mới từ thị trường
uv run --frozen python scripts/generate_report.py --update
```

#### E. Build & Preview Frontend:

```bash
# Preview môi trường phát triển
vp dev

# Build kiểm tra SSG Prerender
vp build
```

---

## 5. Tổng Quan Quy Trình CI (GitHub Actions)

- **`Tests` (`.github/workflows/tests.yml`)**: Chạy bộ test suite Python bằng lệnh `uv run --frozen python scripts/tests/run_tests.py` trên Python 3.14 khi có thay đổi trong `scripts/` hoặc `pyproject.toml` / `uv.lock`.
- **`Daily Data Update` (`.github/workflows/daily-update.yml`)**: Tự động chạy `uv run --frozen python scripts/generate_report.py --update` vào 11:00 UTC (18:00 ICT) từ Thứ 2 đến Thứ 6 để thu thập dữ liệu EOD sau giờ đóng cửa.
- **`Lint & Format` (`.github/workflows/lint-format.yml`)**: Tự động kiểm tra, sửa lỗi safe và verify format/lint code Python (Ruff) và Frontend (Vite+).
- **`GitHub Pages` (`.github/workflows/pages.yml`)**: Build và deploy trang web tĩnh React SSG lên GitHub Pages.

---

## 6. Quy Tắc Lịch Sử & Độ Tươi Dữ Liệu (Data Freshness & Anti-Lookahead)

- **Quy tắc ngày giao dịch (Trading-date Freshness)**: Ngày dữ liệu (`data_as_of`) dựa trên ngày giao dịch gần nhất của VNINDEX, không lấy theo ngày lịch calendar nếu thị trường đóng cửa (cuối tuần / lễ).
- **Tuyệt đối chống lộ dữ liệu tương lai (Anti-Lookahead Safety)**: Mọi tính toán điểm tín hiệu, rủi ro, khuyến nghị hay backtest tại ngày $T$ chỉ được truy cập dữ liệu $\le T$.
- **Tái lập báo cáo lịch sử (Historical Reproducibility)**: Khi chạy báo cáo lịch sử (`--as-of YYYY-MM-DD`), hệ thống sử dụng dữ liệu snapshot tại mốc thời gian đó mà không gọi live provider.

---

## 7. Xử Lý Lỗi Thường Gặp (Troubleshooting)

- **Lỗi Provider Rate Limit / Cooldown**: Vnstock có giới hạn tần suất truy vấn. Khi gặp lỗi rate limit, pipeline tự động tạm dừng theo thời gian cooldown. Không tự ý loại bỏ throttle delay hoặc tăng tần suất request.
- **Lỗi thiếu file build `dist/client/index.html` khi test**: Runner `scripts/tests/run_tests.py` sẽ tự động bỏ qua bài test SSG HTML (`TestSSGStaticHTML`) nếu chưa build frontend, giúp bộ test Python backend chạy độc lập và không bị fail.
- **Dependency mismatch**: Luôn dùng `--frozen` (`uv run --frozen ...`) để đảm bảo các gói phụ thuộc chính xác theo `uv.lock`.

---

## 8. Tài Liệu Tham Khảo Thêm

- **Hướng dẫn cho AI Agent**: [AGENTS.md](AGENTS.md)
- **Kiến trúc chi tiết & Refactoring Roadmap**: `docs/architecture/`
