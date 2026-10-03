# VN Invest — Technical & Operational Playbook for Coding Agents

This document is the authoritative operational playbook for AI coding agents working on **VN Invest** (`area44-labs/vn-invest`). It defines system architecture rules, execution workflows, authoritative commands, and decision constraints to ensure fast, smart, and zero-regression development.

---

## 1. Repository Orientation & System Architecture

### A. Core Architecture Boundaries

- **Python Quantitative Engine (`scripts/`)**: Handles all market data collection, canonical OHLCV validation, technical indicators, Signal Scoring, T+2.5 risk modeling, Market Regime detection, portfolio backtesting, operational monitoring, and data/model drift tracking.
- **React SSG Frontend (`src/`)**: Renders static web pages using TanStack Start and Vite+ (`vp`). It reads generated JSON artifacts exclusively from `generated/` (or `dist/client/generated/` in production builds). **Zero financial calculations occur in the frontend.**
- **Validated JSON Contracts (`schemas/`)**: All exported report artifacts must strictly comply with `schemas/recommendations.schema.json` and `schemas/performance.schema.json`.
- **Static Artifacts (`generated/`)**: Single source of truth for generated report payloads (`recommendations.json`, `market.json`, `monitoring.json`, `history/index.json`, `history/YYYY-MM-DD.json`).

### B. Execution Flow (9 Pipeline Stages)

The production report generation pipeline (`scripts/pipeline/runner.py`) executes 9 sequential stages via `PipelineContext`:

1. `DataAcquisitionStage`: Fetch raw market data for candidate universe and benchmarks (`VNINDEX`, `VN30`).
2. `DataValidationStage`: Apply canonical OHLCV validation, strip invalid/corrupted records, and verify temporal integrity (`data_as_of`).
3. `UniverseValidationStage`: Audit candidate universe completeness and filter out symbols with insufficient history or schema/data errors.
4. `MarketAnalysisStage`: Compute market breadth, volume ratios, and detect VNINDEX Market Regime.
5. `SignalRecommendationGenerationStage`: Calculate technical indicators, multi-timeframe weights, Signal Scores, and confidence ratings.
6. `RiskTradePlanStage`: Evaluate T+2.5 VaR 95%, Expected Shortfall 95%, Max Drawdown, liquidity scores, and trade plans (Entry, Stop Loss, Take Profit targets).
7. `PerformanceStage`: Run walk-forward signal evaluations, execution eligibility checks, transaction cost/slippage models, and portfolio backtests.
8. `MonitoringStage`: Execute schema validation, freshness checks, symbol accounting, and data/model drift monitoring against qualified baseline lookbacks.
9. `ArtifactPublishingStage`: Persist validated payloads atomically to `generated/`.

---

## 2. Fast Agent Workflow

To avoid unnecessary, slow, network-dependent pipeline runs during small targeted changes:

1. **Identify Affected Layer**: Pinpoint whether changes affect Domain Models, Quantitative Engine, Pipeline Stages, Monitoring, or Frontend components.
2. **Read Relevant Code & Tests**: Inspect existing implementation contracts and corresponding test files in `scripts/tests/`.
3. **Find Invariants & Schema Contracts**: Verify relevant JSON Schemas (`schemas/`) or frozen domain dataclasses (`scripts/domain/`).
4. **Run Smallest Targeted Test First**: Execute module-specific unit tests for instant feedback (sub-second):
   - Domain Contracts: `uv run --frozen python -m unittest scripts/tests/test_domain.py`
   - Recommendation & Signals: `uv run --frozen python -m unittest scripts/tests/test_recommendation.py`
   - Pipeline Stages & Context: `uv run --frozen python -m unittest scripts/tests/test_pipeline.py`
   - Backtest & Execution Costs: `uv run --frozen python -m unittest scripts/tests/test_portfolio_backtest.py`
   - Risk & T+2.5 Metrics: `uv run --frozen python -m unittest scripts/tests/test_risk.py`
   - Monitoring & Drift: `uv run --frozen python -m unittest scripts/tests/test_monitoring.py scripts/tests/test_drift_monitoring.py`
5. **Implement Targeted Code Change**: Make minimal, focused edits satisfying existing contracts.
6. **Run Targeted Verification**: Re-run targeted unit test and Ruff linter.
7. **Run Authoritative CI Checks**: Execute full test discovery and linting prior to submitting work.
8. **Review Diff**: Ensure no unintended edits, modified generated artifacts, or weakened schemas exist.

---

## 3. Authoritative Tooling & Commands

Use the repository's actual configuration as the sole source of truth.

### A. Python Backend (Python >= 3.14 via `uv`)

- **Dependency Source of Truth**: `pyproject.toml` and `uv.lock`.
- **Install / Sync Dependencies**:
  ```bash
  uv sync --frozen
  ```
- **Linting & Formatting**:
  ```bash
  uv run --frozen ruff check --fix scripts
  uv run --frozen ruff format scripts
  ```
- **Authoritative CI Test Suite Command**:
  ```bash
  uv run --frozen python scripts/tests/run_tests.py
  ```
  _Note:_ `scripts/tests/run_tests.py` is the official CI entry point. It contains custom discovery and test filtering logic (e.g., automatically skipping `TestSSGStaticHTML` when frontend build artifacts in `dist/client/index.html` are absent).
- **Run Production Pipeline**:
  ```bash
  uv run --frozen python scripts/generate_report.py          # Generate report using existing data
  uv run --frozen python scripts/generate_report.py --update # Update market data and regenerate
  ```

### B. Frontend & Tooling (Vite+ `vp`)

- **Frontend Tooling Standard**: Vite+ (`vp`). Use `vp` commands for frontend checks and builds.
- **Install Dependencies**:
  ```bash
  vp install
  ```
- **Linting & Formatting Check**:
  ```bash
  vp check --fix
  ```
- **Build SSG Prerender**:
  ```bash
  vp build
  ```

---

## 4. Operational Constraints & Data Pipeline Rules

### A. Market Data Provider Constraints (`vnstock`)

- **Rate Limit & Circuit Breaker**: Vnstock is an external provider subject to request limits. Rate limit errors (`ProviderRateLimitError`) trip circuit breakers and trigger bounded cooldown recovery. Rate limit exceptions are NOT generic transient failures—respect provider cooldowns (`DEFAULT_UPDATE_THROTTLE_DELAY = 3.5s` during updates).
- **Complete Market Data Requirement**: Production update mode (`--update`) requires 100% complete data collection across the candidate universe and benchmark symbols (`VNINDEX`, `VN30`) before generating or publishing reports. If any required symbol fails unrecoverably or yields insufficient data, the pipeline fails closed without overwriting existing on-disk report artifacts.

### B. Trading-Date Freshness & Anti-Lookahead Invariants

- **Trading Date Reference**: `data_as_of` is strictly derived from the clean validated `VNINDEX` trading session date, ignoring non-trading calendar days (weekends/holidays).
- **Anti-Lookahead Temporal Isolation**: All historical calculations, signal generation, risk assessments, and backtests at day $T$ must strictly access data $\le T$. Future data ($> T$) must never leak into historical evaluations.
- **Historical Reproducibility**: Historical reports generated via `generate_historical_report()` (`--as-of YYYY-MM-DD`) use point-in-time snapshot data without invoking live external market data providers.

### C. Monitoring, Performance & Drift Contracts

- **Schema Compliance**: Payload outputs must pass JSON Schema validation against `schemas/recommendations.schema.json`.
- **Baseline Qualification**: Operational drift monitoring (`evaluate_data_and_model_drift()`) evaluates qualified historical reports with coverage ratio `processed_ratio >= 0.80` in reverse chronological order $< T$.
- **Baseline Insufficiency vs. Drift**: When qualified historical reports are fewer than `min_baseline_reports` (5), monitoring returns `INSUFFICIENT` status and `WARNING` checks. Data insufficiency must strictly be distinguished from genuine quantitative model drift.

---

## 5. CI Workflow Overview (`.github/workflows/`)

- **`tests.yml`**: Runs `uv sync --frozen` followed by `uv run --frozen python scripts/tests/run_tests.py` on Python 3.14.
- **`daily-update.yml`**: Schedules market data updates and report generation (`uv run --frozen python scripts/generate_report.py --update`) Monday–Friday after Vietnam market close (11:00 UTC / 18:00 ICT).
- **`lint-format.yml`**: Runs Ruff autofix/formatting on Python scripts and Vite+ check on frontend code.
- **`pages.yml`**: Builds Vite+ SSG assets and deploys static artifacts to GitHub Pages.

---

## 6. Agent Decision Rules

1. **Smallest Focused Change**: Prefer the smallest code modification that satisfies existing domain contracts.
2. **Read Tests First**: Inspect unit tests in `scripts/tests/` before altering business logic.
3. **No Manual Artifact Editing**: Do not directly edit files in `generated/` unless explicitly instructed.
4. **No Schema Weakening**: Never relax JSON Schema constraints or type validations to force tests to pass.
5. **No Data Fabrication**: Never fill missing data with arbitrary defaults or zeros when data is invalid or insufficient (`INSUFFICIENT` / `None` must be preserved fail-closed).
6. **No Live Data for Historical Tests**: Never rely on live API market data to validate historical or backtesting logic.
7. **Maintain Dependency Truth**: `pyproject.toml` and `uv.lock` are the sole sources of truth for Python backend development.
