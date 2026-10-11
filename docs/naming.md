# System Naming Conventions & Canonical Terminology

This document specifies the canonical terminology, naming standards, and domain terms used across **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Purpose & When to Consult

Consult this document when creating new files, defining classes, writing functions, naming variables, or referencing core domain concepts.

---

## 2. Naming Standards Table

| Entity Type                    | Convention               | Examples                                                           |
| :----------------------------- | :----------------------- | :----------------------------------------------------------------- |
| **Directory / Package**        | `snake_case`             | `scripts/domain`, `scripts/quant`, `scripts/pipeline`              |
| **Python File / Module**       | `snake_case.py`          | `acquisition.py`, `runner.py`, `portfolio.py`                      |
| **Class / Dataclass**          | `PascalCase`             | `UniverseCandidate`, `QuantConfig`, `PipelineContext`              |
| **Function / Method**          | `snake_case`             | `detect_market_regime`, `compute_signal`, `to_dict`                |
| **Variable / Attribute**       | `snake_case`             | `data_as_of`, `processed_symbols`, `liquidity_score`               |
| **Constant**                   | `UPPER_SNAKE_CASE`       | `PIPELINE_VERSION`, `DEFAULT_QUANT_CONFIG`, `SCHEMA_VERSION`       |
| **JSON Schema File**           | `snake_case.schema.json` | `recommendations.schema.json`, `performance.schema.json`           |
| **Frontend File**              | `kebab-case.tsx` / `.ts` | `dashboard.tsx`, `stock-detail.tsx`, `market-summary.tsx`          |
| **React Component Identifier** | `PascalCase`             | `export function StockDetail()`, `export function MarketSummary()` |
| **TypeScript Function / Var**  | `camelCase`              | `loadRecommendationsResult`, `activeSymbol`, `isMarketFallback`    |

---

## 3. Subsystem File & Entity Rules

- **Frontend Files (`src/`)**: Every file under `src/` (pages, components, utilities, tests, styles) MUST use `kebab-case` filenames (e.g. `src/pages/stock-detail.tsx`). Exported React components, types, and interfaces maintain standard `PascalCase` (e.g. `export function StockDetail()`).
- **Python Modules (`scripts/`)**: Module files use `snake_case.py`. Function names use `snake_case`. Classes use `PascalCase`.
- **Expressive Domain Naming**: Prefer expressive, intent-revealing names (`calculate_risk_adjusted_score`, `validate_temporal_integrity`) over vague terms (`process_data`, `helper`, `handle_result`).
- **Test Function Naming**: Test functions follow `test_<behavior>()`. Test docstrings state tested behavior directly without arbitrary numbered labels (`# Scenario 1:`).

---

## 4. Canonical Domain Terminology

- **`data_as_of`**: Canonical point-in-time trading session date string (`YYYY-MM-DD`) derived strictly from clean `VNINDEX` market data.
- **`PipelineContext`**: Runtime state container created during pipeline execution holding configuration, market DataFrames, processing statistics, and stage results.
- **`QuantConfig`**: Immutable frozen dataclass holding quantitative signal weights, indicator parameters, and risk parameters.
- **`config_hash`**: SHA-256 hash string derived from `QuantConfig.get_config_hash()`, tracking quantitative parameter lineage.
- **`MarketRegime`**: System market state (`BULLISH`, `BEARISH`, `SIDEWAYS`, `NEUTRAL`).
- **`Recommendation Action`**: Trade recommendation classification (`BUY`, `SELL`, `WATCH`, `HOLD`, `AVOID`).
- **`T+2.5 Settlement`**: Vietnamese stock market settlement cycle (purchases at $T$ become available for sale on $T+2$ afternoon / $T+3$ session).
