# Coding Standards & Conventions

This document specifies the practical coding standards, engineering conventions, and canonical naming standards enforced across **VN Invest** (`area44-labs/vn-invest`).

---

## Naming Standards & Canonical Terminology

| Entity Type                    | Convention               | Examples                                                           |
| :----------------------------- | :----------------------- | :----------------------------------------------------------------- |
| **Directory / Package**        | `snake_case`             | `scripts/domain`, `scripts/quant`, `scripts/pipeline`              |
| **Python File / Module**       | `snake_case.py`          | `acquisition.py`, `runner.py`, `portfolio.py`                      |
| **Class / Dataclass**          | `PascalCase`             | `UniverseCandidate`, `QuantConfig`, `PipelineContext`              |
| **Function / Method**          | `snake_case`             | `detect_market_regime`, `compute_signal`, `to_dict`                |
| **Variable / Attribute**       | `snake_case`             | `data_as_of`, `processed_symbols`, `liquidity_score`               |
| **Constant**                   | `UPPER_SNAKE_CASE`       | `PIPELINE_VERSION`, `DEFAULT_QUANT_CONFIG`, `SCHEMA_VERSION`       |
| **JSON Schema File**           | `snake_case.schema.json` | `recommendations.schema.json`, `performance.schema.json`           |
| **Frontend File (`src/`)**     | `kebab-case.tsx` / `.ts` | `dashboard.tsx`, `stock-detail.tsx`, `market-summary.tsx`          |
| **React Component Identifier** | `PascalCase`             | `export function StockDetail()`, `export function MarketSummary()` |
| **TypeScript Identifier**      | `camelCase`              | `loadRecommendationsResult`, `activeSymbol`, `isMarketFallback`    |
| **React Hook**                 | `use` + `camelCase`      | `useTheme`, `useNavigate`                                          |
| **Test Function**              | `test_<behavior>`        | `test_sequential_stage_execution_order`                            |
