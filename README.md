# VN Invest

[![GitHub Pages](https://github.com/area44-labs/vn-invest/actions/workflows/pages.yml/badge.svg)](https://area44-labs.github.io/vn-invest/)

Hệ thống phân tích và khuyến nghị chứng khoán Việt Nam (HOSE, HNX, UPCoM) tự động hóa, kết hợp **Python Quantitative Engine** và **React SSG** (TanStack Start + Vite+).

## Sơ Đồ Kiến Trúc

```
Python Quantitative Engine (scripts/)
       ↓
Validated Data Contract (schemas/recommendations.schema.json)
       ↓
Static JSON Artifacts (generated/)
       ↓
React SSG / Vite+ (src/)
```

## Lệnh Phát Triển

### Frontend (React / Vite+)

```bash
vp install # Cài đặt dependencies
vp dev     # Chạy dev server
vpr check   # Format, lint và kiểm tra loại
vpr build   # Build trang web SSG
```

### Backend (Python Quantitative Engine)

```bash
pip install -r requirements.txt # Cài đặt dependencies
python scripts/generate_report.py # Chạy báo cáo định lượng
python scripts/tests/run_tests.py # Chạy bộ unit tests
ruff check .                     # Linting mã nguồn Python
```

## Giấy Phép

Mã nguồn mở phát hành theo giấy phép [MIT](LICENSE).
