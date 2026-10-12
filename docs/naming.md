# System Naming Conventions & Canonical Terminology

This document is the authoritative reference for file naming, identifier conventions, and domain terminology in **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Codebase Naming Standards

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

---

## 2. File & Entity Naming Rules

- **Frontend Files (`src/`)**: Every file under `src/` (pages, components, utilities, tests, styles) MUST use `kebab-case` filenames (e.g., `src/pages/stock-detail.tsx`). Exported React components, TypeScript interfaces, and types maintain `PascalCase` identifiers.
- **Python Modules (`scripts/`)**: Module files use `snake_case.py`. Class names use `PascalCase`. Functions/methods use `snake_case`.
- **Expressive Domain Naming**: Prefer intent-revealing names (`calculate_risk_adjusted_score`, `validate_temporal_integrity`) over vague terms (`process_data`, `helper`, `handle_result`).
- **Test Function Naming**: Test functions follow `test_<behavior>()`. Test docstrings state tested behavior directly without arbitrary numbered labels (`# Scenario 1:`).

---

## 3. Canonical Domain Terminology

- **`data_as_of`**: Canonical point-in-time trading session date string (`YYYY-MM-DD`) derived strictly from clean `VNINDEX` market data.
- **`PipelineContext`**: Runtime state container created during pipeline execution holding configuration, market DataFrames, processing statistics, and stage results.
- **`QuantConfig`**: Immutable frozen dataclass holding quantitative signal weights, indicator parameters, and risk parameters.
- **`config_hash`**: SHA-256 hash string derived from `QuantConfig.get_config_hash()`, tracking quantitative parameter lineage.
- **`MarketRegime`**: System market state (`STRONG_BULL`, `BULL`, `NEUTRAL`, `DEFENSIVE`, `BEAR`, `PANIC`).
- **`Recommendation Action`**: Trade recommendation classification (`BUY`, `SELL`, `WATCH`, `HOLD`, `AVOID`).
- **`T+2.5 Settlement`**: Vietnamese stock market settlement cycle (purchases at $T$ become available for sale on $T+2$ afternoon / $T+3$ session).
