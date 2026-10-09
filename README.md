# VN Invest 📈

[![GitHub Pages](https://github.com/area44-labs/vn-invest/actions/workflows/pages.yml/badge.svg)](https://area44-labs.github.io/vn-invest/)
[![Tests](https://github.com/area44-labs/vn-invest/actions/workflows/tests.yml/badge.svg)](https://github.com/area44-labs/vn-invest/actions/workflows/tests.yml)

**VN Invest** là hệ thống phân tích định lượng và sinh khuyến nghị chứng khoán tự động hóa, được thiết kế chuyên biệt dành cho thị trường chứng khoán Việt Nam (HOSE, HNX, UPCoM).

---

## Tính năng nổi bật

- **Phân tích định lượng (Quantitative Analysis):** Áp dụng các mô hình toán học, chỉ báo kỹ thuật (RSI, MACD, MA, Divergence) và đánh giá rủi ro T+2.5.
- **Khuyến nghị tự động (Automated Recommendations):** Sinh tín hiệu giao dịch và kế hoạch giao dịch khách quan dựa trên dữ liệu thị trường thực tế.
- **Phân loại trạng thái thị trường (Market Regime):** Đánh giá xu hướng tổng quan thị trường (`BULLISH`, `BEARISH`, `SIDEWAYS`, `NEUTRAL`) và cảnh báo rủi ro hệ thống.
- **Tĩnh hóa & Hiệu năng cao (React SSG):** Giao diện hiển thị trực quan pre-rendered static site, tích hợp dữ liệu đã pre-calculate từ backend Python.

---

## Hướng dẫn nhanh & Lệnh cơ bản

### Yêu cầu môi trường

- **Python**: `>= 3.14` quản lý bằng [uv](https://docs.astral.sh).
- **Frontend Standard**: [Vite+](https://viteplus.dev) (`vp` / `pnpm`).

### 1. Backend (Mô hình định lượng Python)

```bash
# Cài đặt / đồng bộ các phụ thuộc
uv sync --frozen

# Chạy toàn bộ bộ kiểm thử unit & integration backend
uv run --frozen pytest

# Kiểm tra định dạng và linter Python
uv run --frozen ruff check --fix scripts
uv run --frozen ruff format scripts

# Sinh báo cáo phân tích (sử dụng dữ liệu thị trường cached)
uv run --frozen python scripts/generate_report.py

# Cập nhật dữ liệu thị trường thời gian thực & sinh báo cáo mới
uv run --frozen python scripts/generate_report.py --update
```

### 2. Frontend (Giao diện hiển thị React SSG)

```bash
# Cài đặt phụ thuộc frontend
vp install

# Kiểm tra linter, định dạng và typecheck frontend
vp check

# Khởi chạy server phát triển local
vp dev

# Build tĩnh giao diện production (SSG prerender)
vp build
```

---

## Danh mục Tài liệu

Để tìm hiểu chi tiết về kiến trúc hệ thống và quy trình vận hành, tham khảo các tài liệu chi tiết trong `docs/` và file hướng dẫn `AGENTS.md`:

- **Hướng dẫn Vận hành**: [`AGENTS.md`](AGENTS.md)
- **Kiến trúc Hệ thống & Ranh giới**: [`docs/architecture.md`](docs/architecture.md)
- **Mô hình Định lượng & Backtest**: [`docs/quantitative.md`](docs/quantitative.md)
- **Các Giai đoạn Pipeline**: [`docs/pipeline.md`](docs/pipeline.md)
- **Kiến trúc Kiểm thử & Guidelines**: [`docs/testing.md`](docs/testing.md)
- **Kiến trúc Frontend**: [`docs/frontend.md`](docs/frontend.md)
- **Quy trình CI/CD & Tự động hóa**: [`docs/ci-cd.md`](docs/ci-cd.md)

---

## Bản quyền

Dự án được phát hành dưới các điều khoản của [Giấy phép MIT](LICENSE) và thuộc quyền sở hữu của **AREA44**.
