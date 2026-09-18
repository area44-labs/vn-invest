# VN Invest

[![GitHub Pages](https://github.com/area44-labs/vn-invest/actions/workflows/pages.yml/badge.svg)](https://area44-labs.github.io/vn-invest/)

Hệ thống phân tích và khuyến nghị chứng khoán Việt Nam (HOSE, HNX, UPCoM) sử dụng Python Quantitative Engine và Frontend React SSG.

## Kiến Trúc Hệ Thống

```
Python Quantitative Engine
        ↓
Validated Data Contract (JSON Schema Draft 2020-12)
        ↓
Static JSON Artifacts (generated/)
        ↓
React / TanStack Router (src/)
        ↓
SSG / GitHub Pages Deployment
```

### Quantitative System Layers

Backend quantitative system được phân định rõ ràng thành các tầng chức năng độc lập:

1. **Production Generation** (`scripts/generate_report.py`, `scripts/lib/recommendation.py`, `scripts/lib/regime.py`, `scripts/lib/risk.py`): Ingestion dữ liệu thị trường EOD thực tế, tính toán chỉ báo kỹ thuật, nhận diện Market Regime, chấm điểm Signal Score (VN Invest Signal Engine), mô hình rủi ro T+2.5, lập kế hoạch giao dịch và xuất JSON artifacts tĩnh (`generated/*.json`).
2. **Production Monitoring** (`scripts/lib/monitoring.py`): Giám sát vận hành pipeline và dữ liệu sản xuất (kiểm tra availability, freshness `data_as_of`, số lượng mã xử lý/bỏ qua, kiểm tra JSON schema, kiểm tra tính toàn vẹn artifact, an toàn số học `NaN`/`Inf`, và tích hợp kiểm tra Data/Model Drift) mà không làm thay đổi kết quả signal hay đánh giá lịch sử.
   _Lưu ý: Tầng này chỉ cung cấp giám sát vận hành và đường biên dữ liệu; không xác lập hiệu lực dự báo, khả năng sinh lời, hiệu chuẩn hay ý nghĩa thống kê của mô hình. Điểm confidence là điểm số heuristic mô hình, không phải xác suất thống kê._
3. **Data Drift Detection** (`scripts/lib/monitoring.py`): Giám sát độ lệch của các đặc trưng dữ liệu đầu vào (VNINDEX return/change, market breadth ratio, processed/insufficient ratio) so với baseline lịch sử cố định timestamped `< T`.
4. **Model-Output Drift Detection** (`scripts/lib/monitoring.py`): Giám sát độ lệch phân phối kết quả đầu ra của khuyến nghị (BUY/WATCH/HOLD/SELL/AVOID, phân phối bucket confidence canonical, trung bình signal score và risk-adjusted score) so với baseline lịch sử timestamped `< T`.
   _Lưu ý: Model-output drift chỉ ghi nhận sự thay đổi phân phối output so với baseline, KHÔNG chứng minh suy giảm sức mạnh dự báo (predictive degradation), sai sót mô hình, nguyên nhân (causality), khả năng sinh lời hay yêu cầu retrain mô hình._
5. **Historical Backtesting** (`scripts/lib/backtest.py`, `scripts/lib/portfolio_backtest.py`): Kiểm thử lịch sử walk-forward không nhìn trước tương lai (no-lookahead) đánh giá hiệu suất tín hiệu 5D, 10D, 20D và danh mục đầu tư.
6. **Confidence Calibration** (`scripts/lib/backtest.py`): Đánh giá tương quan giữa điểm số tin cậy heuristic và tỷ lệ sinh lời dương thực tế qua các giai đoạn lịch sử walk-forward.
7. **Market-Regime Validation** (`scripts/lib/backtest.py`): Đánh giá phân phối hiệu suất thị trường tương ứng với từng trạng thái thị trường (Market Regime) lịch sử.

## Tính Năng Nổi Bật

- **Python Quantitative Engine**: Tính toán chỉ báo kỹ thuật (MA, RSI, MACD, ATR), nhận diện phân kỳ đa khung thời gian, phân tích trạng thái thị trường (Market Regime), chấm điểm Signal Score (VN Invest Signal Engine), tính rủi ro T+2.5 (Historical VaR 95%, Expected Shortfall, Max Drawdown) và lập kế hoạch giao dịch (Trade Plan).
- **Single Source of Truth**: Data contract được định nghĩa chuẩn xác bằng JSON Schema (`schemas/recommendations.schema.json`).
- **TanStack Router & SSG**: Điều hướng SPA mượt mà với routing dựa trên TanStack Router (`/`, `/history`, `/stock/$symbol`) và prerender static HTML tương thích GitHub Pages.
- **Bảo Đảm Kiểm Thử**: Bộ unit test Python kiểm tra toàn bộ logic tính toán chỉ báo, rủi ro, kế hoạch giao dịch và anti-lookahead bias.

## Hướng Dẫn Phát Triển

### 1. Frontend

```bash
# Cài đặt dependencies
pnpm install

# Run dev server
pnpm dev

# Kiểm tra lint & format
pnpm check

# Build dự án SSG
pnpm build
```

### 2. Backend Quantitative Pipeline

Hỗ trợ Python >= 3.10 (khuyến nghị Python 3.10 - 3.12).

```bash
# Cài đặt Python dependencies có tính tái lập cao (reproducible)
pip install -r requirements.txt

# Chạy báo cáo định lượng & tạo file JSON tĩnh
python scripts/generate_report.py

# Chạy toàn bộ Unit Tests Python
python scripts/tests/run_tests.py

# Lint & format Python code
ruff check .
ruff format --check .
```

### 3. Quy Định & Chính Sách Phụ Thuộc (Dependency Policy)

- **Các gói phụ thuộc được ghim cố định**: Các phụ thuộc của active quantitative pipeline được ghim phiên bản chính xác tại `requirements.txt`.
- **Phiên bản `vnstock`**: Phiên bản hỗ trợ chính thức hiện tại là **4.0.7**.
- **Quy trình nâng cấp dependency**: Muốn nâng cấp bất kỳ dependency nào, cần kiểm tra tính tương thích cấu trúc API/đơn vị tính (provider unit contract) và đảm bảo toàn bộ bộ kiểm thử trong `python scripts/tests/run_tests.py` vượt qua trước khi cập nhật phiên bản trong `requirements.txt`.

## License

Dự án phát hành theo mã nguồn mở [MIT License](LICENSE).
