# Python Coding Standards & Conventions

This document specifies the practical Python coding standards, engineering conventions, and canonical naming standards enforced across **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Environment & Tooling

- **Python Requirements**: `>= 3.14` managed deterministically via `uv`.
- **Dependency Source of Truth**: `pyproject.toml` and `uv.lock`.
- **Execution Command**: All Python scripts and tests run via `uv run --frozen ...`.

---

## 2. Naming Standards & Canonical Terminology

### 2.1 Codebase Naming Standards

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

### 2.2 File & Entity Rules

- **Frontend Files (`src/`)**: Every file under `src/` (pages, components, utilities, tests, styles) MUST use `kebab-case` filenames (e.g., `src/pages/stock-detail.tsx`). Exported React components, TypeScript interfaces, and types maintain `PascalCase` identifiers.
- **Python Modules (`scripts/`)**: Module files use `snake_case.py`. Class names use `PascalCase`. Functions/methods use `snake_case`.
- **Expressive Domain Naming**: Prefer intent-revealing names (`calculate_risk_adjusted_score`, `validate_temporal_integrity`) over vague terms (`process_data`, `helper`, `handle_result`).
- **Test Function Naming**: Test functions follow `test_<behavior>()`. Test docstrings state tested behavior directly without arbitrary numbered labels (`# Scenario 1:`).

### 2.3 Canonical Domain Terminology

- **`data_as_of`**: Canonical point-in-time trading session date string (`YYYY-MM-DD`) derived strictly from clean `VNINDEX` market data.
- **`PipelineContext`**: Runtime state container created during pipeline execution holding configuration, market DataFrames, processing statistics, and stage results.
- **`QuantConfig`**: Immutable frozen dataclass holding quantitative signal weights, indicator parameters, and risk parameters.
- **`config_hash`**: SHA-256 hash string derived from `QuantConfig.get_config_hash()`, tracking quantitative parameter lineage.
- **`MarketRegime`**: System market state (`STRONG_BULL`, `BULL`, `DEFENSIVE`, `BEAR`, `PANIC`).
- **`Recommendation Action`**: Trade recommendation classification (`BUY`, `SELL`, `WATCH`, `HOLD`, `AVOID`).
- **`T+2.5 Settlement`**: Vietnamese stock market settlement cycle (purchases at $T$ become available for sale on $T+2$ afternoon / $T+3$ session).

---

## 3. Typing & Model Standards

### 3.1 Explicit Type Annotations

- All production functions, methods, and class attributes must have explicit type annotations.
- Use standard library generic types (`list[str]`, `dict[str, Any]`, `tuple[int, ...]`, `set[str]`).

### 3.2 Domain Models & Frozen Dataclasses

- Domain contracts and configuration models are implemented as immutable dataclasses using `@dataclass(frozen=True)`.
- Use `FrozenDict` (from `scripts.quant.config`) for nested dictionary fields inside frozen dataclasses to support deep immutability and `copy.deepcopy`.

### 3.3 Mutation Isolation (`.to_dict()`)

- Dataclasses and result containers that serialize to JSON must provide a `.to_dict()` method returning detached, deep copies of internal collections to prevent caller mutation leaks.

---

## 4. Exception Handling & Fail-Closed Principles

- **Custom Exceptions**: Inherit from domain-specific base exceptions (`AcquisitionError`, `CanonicalOHLCVError`, `SchemaResolutionError`).
- **Fail-Closed Strategy**: When data quality checks fail or external provider limits are exceeded, do not synthesize default values or fake numbers. Return `None`, set status to `INSUFFICIENT`, or raise an explicit error.
- **Artifact Protection**: In update mode (`--update`), data failures raise `RuntimeError` to abort report generation without modifying existing files in `generated/`.

---

## 5. Formatting & Imports

- **Linter & Formatter**: Enforced via Ruff (`astral-sh/ruff`):
  ```bash
  uv run --frozen ruff check --fix scripts
  uv run --frozen ruff format scripts
  ```
- **Import Block Order**:
  1. Standard library imports
  2. Third-party imports (`pandas`, `numpy`, `pytest`)
  3. Internal package imports (`scripts.domain`, `scripts.quant`)
- **No Wildcard Imports**: `from module import *` is prohibited. Use explicit imports.
