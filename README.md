# VN Invest

[![GitHub Pages](https://github.com/area44-labs/vn-invest/actions/workflows/pages.yml/badge.svg)](https://area44-labs.github.io/vn-invest/)
[![Tests](https://github.com/area44-labs/vn-invest/actions/workflows/tests.yml/badge.svg)](https://github.com/area44-labs/vn-invest/actions/workflows/tests.yml)

**VN Invest** là hệ thống phân tích định lượng và sinh khuyến nghị chứng khoán tự động hóa, được thiết kế chuyên biệt dành cho thị trường chứng khoán Việt Nam (HOSE, HNX, UPCoM).

---

## Tính năng nổi bật

- **Phân tích định lượng (Quantitative Analysis):** Áp dụng các mô hình toán học, chỉ báo kỹ thuật (RSI, MACD, MA, Divergence) và đánh giá rủi ro T+2.5.
- **Khuyến nghị tự động (Automated Recommendations):** Sinh tín hiệu giao dịch và kế hoạch giao dịch khách quan dựa trên dữ liệu thị trường thực tế.
- **Phân loại trạng thái thị trường (Market Regime):** Phân loại xu hướng thị trường theo các trạng thái và cảnh báo rủi ro hệ thống.
- **Tĩnh hóa & Hiệu năng cao (React SSG):** Giao diện hiển thị trực quan pre-rendered static site, tích hợp dữ liệu đã pre-calculate từ backend Python.

---

## Hướng dẫn nhanh & Lệnh cơ bản

### Môi trường yêu cầu

- **Python**: `>= 3.14` quản lý bằng [uv](https://docs.astral.sh).
- **Frontend Standard**: [Vite+](https://viteplus.dev) (`vp` / `pnpm`).

### 1. Backend (Python)

```bash
# Đồng bộ môi trường phụ thuộc
uv sync --frozen

# Chạy bộ kiểm thử backend
uv run --frozen pytest

# Kiểm tra lint và định dạng code Python
uv run --frozen ruff check --fix scripts
uv run --frozen ruff format scripts

# Sinh báo cáo (sử dụng dữ liệu cached offline)
uv run --frozen python scripts/generate_report.py
```

### 2. Frontend (React SSG)

```bash
# Cài đặt phụ thuộc frontend
vp install

# Cài đặt trình duyệt Playwright cho test frontend
pnpm exec playwright install --with-deps chromium

# Chạy kiểm thử frontend
vp test

# Kiểm tra linter, typecheck và định dạng
vp check

# Server phát triển local
vp dev

# Build tĩnh giao diện production (SSG)
vp build
```

---

## Tài liệu kỹ thuật

Tham khảo **[Danh mục Tài liệu (Documentation Index)](docs/index.md)** để tra cứu đầy đủ các tài liệu kiến trúc, quy trình phát triển, hợp đồng dữ liệu và vận hành hệ thống.

---

## Bản quyền

Dự án được phát hành dưới các điều khoản của [Giấy phép MIT](LICENSE) và thuộc quyền sở hữu của **AREA44**.
