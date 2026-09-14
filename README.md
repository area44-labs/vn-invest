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

- **Các gói phụ thuộc được ghim cố định**: Các phụ thuộc của active quantitative pipeline được ghim phiên bản chính xác tại `requirements.txt` (`vnstock==4.0.7`, `pandas==2.3.3`, `numpy==2.2.6`, `requests==2.34.2`, `jsonschema==4.26.0`, `openpyxl==3.1.5`).
- **Phiên bản `vnstock`**: Phiên bản hỗ trợ chính thức hiện tại là **4.0.7**.
- **Quy trình nâng cấp dependency**: Muốn nâng cấp bất kỳ dependency nào, cần kiểm tra tính tương thích cấu trúc API/đơn vị tính (provider unit contract) và đảm bảo toàn bộ bộ kiểm thử trong `python scripts/tests/run_tests.py` vượt qua trước khi cập nhật phiên bản trong `requirements.txt`.

## License

Dự án phát hành theo mã nguồn mở [MIT License](LICENSE).
