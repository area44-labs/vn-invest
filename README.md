# VN Invest

[![GitHub Pages](https://github.com/area44-labs/vn-invest/actions/workflows/pages.yml/badge.svg)](https://area44-labs.github.io/vn-invest/)

Hệ thống phân tích và khuyến nghị chứng khoán Việt Nam (HOSE, HNX, UPCoM) tự động hóa, kết hợp **Python Quantitative Engine** (Python 3.14 + uv + Pandas v3 + NumPy v2.5) và **React SSG** (TanStack Start + Vite+).

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

## Giấy Phép

Mã nguồn mở phát hành theo giấy phép [MIT](LICENSE).
