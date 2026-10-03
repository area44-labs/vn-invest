# VN Invest

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
│       Published to GitHub Pages         │
└─────────────────────────────────────────┘
```

---

## 2. Quick Start & Authoritative Commands

### Yêu Cầu Môi Trường:

- **Python**: `>= 3.14` (Quản lý môi trường và dependency bằng `uv`)
- **Frontend Toolchain**: Vite+ (`vp`)

### Lệnh Phát Triển Chuẩn Duy Nhất:

```bash
# 1. Đồng bộ Dependency
uv sync --frozen         # Python backend
vp install               # Frontend (Vite+)

# 2. Kiểm Tra Linting & Formatting
uv run --frozen ruff check --fix scripts && uv run --frozen ruff format scripts
vp check --fix           # Frontend check (Vite+)

# 3. Kiểm Thử Hệ Thống (Tests)
uv run --frozen python scripts/tests/run_tests.py   # Full Python test suite (CI entry point)

# 4. Chạy Pipeline & Sinh Báo Cáo
uv run --frozen python scripts/generate_report.py          # Sinh báo cáo từ dữ liệu có sẵn
uv run --frozen python scripts/generate_report.py --update # Cập nhật dữ liệu từ thị trường

# 5. Build & Development Server
vp dev                   # Chạy local dev server
vp build                 # Build kiểm tra SSG Prerender
```

---

## 3. Tổng Quan Quy Trình CI & Deployment

- **`Tests` (`.github/workflows/tests.yml`)**: Chạy bộ test suite Python bằng lệnh `uv run --frozen python scripts/tests/run_tests.py` trên Python 3.14.
- **`Daily Data Update` (`.github/workflows/daily-update.yml`)**: Tự động chạy pipeline cập nhật dữ liệu EOD lúc 11:00 UTC (18:00 ICT) từ Thứ 2 đến Thứ 6.
- **`Lint & Format` (`.github/workflows/lint-format.yml`)**: Tự động sửa lỗi safe và format code Python (Ruff) và Frontend (Vite+).
- **`GitHub Pages` (`.github/workflows/pages.yml`)**: Build và deploy ứng dụng tĩnh React SSG lên GitHub Pages.
