# System Naming Conventions & Canonical Terminology

This document specifies the current canonical terminology, module/class/function naming standards, and domain terms used across **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Code Base Naming Conventions

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

### 1.1 Frontend File Naming Rules (`src/`)

- **Kebab-Case File Names**: Every frontend source file under `src/` (pages, components, hooks, utilities, tests, styles) MUST use `kebab-case` filenames (`ten-file.tsx` / `ten-file.ts`).
  - Pages: `src/pages/dashboard.tsx`, `src/pages/history.tsx`, `src/pages/methodology.tsx`, `src/pages/stock-detail.tsx`
  - Components: `src/components/market-summary.tsx`, `src/components/stock-table.tsx`, `src/components/recommendation-card.tsx`
  - Tests: `src/tests/frontend-correctness.test.tsx`
  - Utilities: `src/lib/format.ts`, `src/data/loader.ts`
- **PascalCase Export Identifiers**: React component functions, TypeScript types, and interfaces maintain standard `PascalCase` exported names (e.g., `export function StockDetail()`, `export interface MarketSummaryProps`). The kebab-case convention applies strictly to filenames, not exported code identifiers.

### 1.2 Expressive Domain Naming Guidelines

- **Behavior & Intent**: Names must clearly communicate domain responsibility and behavior. Prefer descriptive names like `calculate_risk_adjusted_score`, `validate_temporal_integrity`, `evaluate_execution_eligibility` over vague catch-alls like `process_data`, `handle_result`, `helper`, or `manager`.
- **Variable Clarity**: Avoid placeholder or uninformative variable/parameter names (such as `obj`, `val`, `temp`, `data`) when precise domain identifiers exist (e.g., `score_value`, `field_value`, `payload_node`, `instance`).
- **Test Descriptions**: Test function names must follow `test_<behavior>()`. Test docstrings and comments must state the behavior or condition tested directly without generic numbered prefixes (`Test 1:`, `Scenario 1:`, `Case A`, `1. ...`).

---

## 2. Canonical System & Domain Terminology

### 2.1 System Concepts

- **`data_as_of`**: The canonical trading session date string (`YYYY-MM-DD`) derived strictly from clean, validated `VNINDEX` market data. It represents the point-in-time reference date for all calculations.
- **`PipelineContext`**: The state object created during pipeline execution that holds configuration, canonical market data DataFrames, processing statistics, and generated results across all 9 execution stages.
- **`QuantConfig`**: Immutable frozen dataclass holding all quantitative signal weights, indicator parameters, risk parameters, and regime factors.
- **`config_hash`**: The deterministic SHA-256 hash string generated from `QuantConfig.get_config_hash()`, used to track quantitative parameter lineage across recommendations and artifacts.
- **`ExecutionEligibility`**: Dataclass representing point-in-time liquidity and execution constraints for a stock symbol during backtesting (`executable`, `not_executable`, `insufficient_liquidity_history`, `invalid_market_data`).

### 2.2 Market & Domain Terms

- **`HOSE`**, **`HNX`**, **`UPCOM`**: The three recognized Vietnamese stock exchanges.
- **`VNINDEX`**: The primary Vietnam market benchmark index (HOSE).
- **`VN30`**: The top 30 large-cap liquid stocks benchmark index on HOSE.
- **`MarketRegime`**: Classified market status (`BULLISH`, `BEARISH`, `SIDEWAYS`, `NEUTRAL`).
- **`Recommendation Action`**: The final trading recommendation classification (`BUY`, `SELL`, `WATCH`, `HOLD`, `AVOID`).
- **`T+2.5 Settlement`**: The standard Vietnamese stock market settlement cycle (stocks purchased at $T$ become available for sale on $T+2$ afternoon / $T+3$ session).
- **`Floor Price` / `Ceiling Price`**: Exchange-mandated daily price fluctuation limits (HOSE $\pm 7\%$, HNX $\pm 10\%$, UPCoM $\pm 15\%$).

---

## 3. Versioning Terminology

The system enforces explicit separation across four distinct metadata contracts:

1. **`PIPELINE_VERSION`** (e.g. `"2.0.0"`): Orchestration runner version defined in `scripts/pipeline/constants.py`.
2. **`SIGNAL_MODEL_VERSION`** (e.g. `"2.0"`): Signal calculation engine model version in `scripts/quant/config.py`.
3. **`QUANT_VERSION`** (e.g. `"2.0.0"`): Quantitative configuration contract version in `scripts/quant/config.py`.
4. **`SCHEMA_VERSION`** (e.g. `"2.0"`): Canonical JSON Schema version managed by `scripts/schema/registry.py`.

---
