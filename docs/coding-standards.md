# Coding Standards & Conventions

This document specifies the practical coding standards, engineering conventions, and canonical naming standards enforced across **VN Invest** (`area44-labs/vn-invest`).

---

## 1. General Rules

- Prefer focused, readable changes over unnecessary abstractions.
- Follow existing patterns unless there is a clear correctness or maintainability issue.
- Use explicit validation and actionable error messages.
- Avoid duplicated business logic and multiple sources of truth.
- Add regression tests for behavior changes.
- Keep documentation consistent with implementation.

## 2. Naming

| Entity | Convention | Example |
|---|---|---|
| Python module | `snake_case.py` | `market_data.py` |
| Python function or variable | `snake_case` | `validate_ohlcv` |
| Python class | `PascalCase` | `PipelineContext` |
| Constant | `UPPER_SNAKE_CASE` | `DEFAULT_QUANT_CONFIG` |
| React component | `PascalCase` | `StockDetail` |
| Frontend file | Follow existing project convention | `stock-detail.tsx` |
| TypeScript variable or function | `camelCase` | `loadRecommendations` |
| Test function | `test_<behavior>` | `test_stage_execution_order` |

### 2.1 Backend

- Use type annotations for public interfaces and important data structures.
- Keep imports explicit and organized.
- Handle expected failures narrowly; do not classify every exception as transient.
- Preserve original exceptions and useful diagnostic context.
- Validate external data before quantitative calculations.
- Avoid mutable shared state unless its lifecycle is explicit.
- Follow the repository's configured formatter, linter, and test tools.

### 2.2 Frontend

- Follow existing component, routing, state-management, and styling patterns.
- Keep components focused and reuse shared UI elements.
- Validate API and report data before rendering it.
- Represent loading, empty, error, and insufficient-data states explicitly.
- Avoid hiding backend errors behind misleading success states.
- Keep types aligned with the authoritative API and schema contracts.

### 2.3 Data and Quantitative Logic

- Keep quantitative parameters in the centralized configuration.
- Avoid duplicated calculations across pipeline stages and reports.
- Validate numeric inputs and handle missing observations explicitly.
- Keep financial metrics, trading dates, and benchmark comparisons consistent.
- Never invent market values or replace unavailable metrics with zero by default.

### 2.4 Tests and CI

- Test expected behavior, boundary conditions, and failure paths.
- Do not weaken assertions or skip relevant tests merely to obtain a passing build.
- Run relevant backend and frontend checks for the affected code.
- Report skipped checks accurately.
- Review the final diff for unrelated changes and regressions.
