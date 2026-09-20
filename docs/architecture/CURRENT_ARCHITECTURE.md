# Current Architecture Audit — VN Invest Pipeline

## 1. Repository Inventory

The table below provides a comprehensive inventory of all paths in the repository, along with their core responsibilities, primary internal/external dependencies, and architectural risk classifications.

| Area                        | Path                                  | Responsibility                                                                                                                                                                          | Dependencies                                                                                                                | Risk                                                                                                                             |
| --------------------------- | ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| **Pipeline Orchestrator**   | `scripts/generate_report.py`          | Orchestrates daily & historical report generation, snapshot loading, history index management, monitoring execution, and JSON persistence.                                              | `pandas`, `jsonschema`, `scripts.lib.*`, `scripts.data_provider`                                                            | **HIGH** (God module doing orchestration, snapshot loading, historical report generation, CLI parsing, and persistence)          |
| **Data Provider**           | `scripts/data_provider.py`            | Raw data fetching wrapper around `vnstock`, quote parsing, and canonical OHLCV validation contract (`validate_canonical_ohlcv`).                                                        | `vnstock`, `pandas`, `numpy`, `time`, `re`                                                                                  | **MEDIUM** (External network coupling to `vnstock`; prone to upstream API format changes)                                        |
| **Quant Configuration**     | `scripts/lib/config.py`               | Centralized quantitative model parameters, weights, lookbacks, thresholds, risk constants, and drift thresholds.                                                                        | None (Standard library/constants only)                                                                                      | **LOW** (Clean configuration file, but re-exported in `recommendation.py` creating slight redundancy)                            |
| **Market Data & Universe**  | `scripts/lib/vietnam_market.py`       | Unit normalization (`normalize_ohlcv_units`), clean OHLCV boundary (`get_clean_ohlcv_data`), tick size & price limits, universe candidate metadata.                                     | `pandas`, `scripts.data_provider`                                                                                           | **MEDIUM** (Contains hardcoded `UniverseProvider` candidate stock list and file I/O side effects)                                |
| **Feature Extraction**      | `scripts/lib/features.py`             | Technical indicator calculation (SMA, EMA, RSI, MACD, ATR) and multi-timeframe bullish/bearish divergence detection.                                                                    | `pandas`                                                                                                                    | **LOW** (Stateless mathematical functions operating on DataFrames)                                                               |
| **Market Regime**           | `scripts/lib/regime.py`               | Multi-factor market regime detection (`detect_market_regime` returning `STRONG_BULL`, `BULL`, `DEFENSIVE`, `BEAR`, `PANIC`).                                                            | `pandas`, `logging`                                                                                                         | **LOW** (Pure calculation, independent of backtest module)                                                                       |
| **Risk Engine**             | `scripts/lib/risk.py`                 | T+2.5 Vietnam settlement risk calculation (VaR 95%, ES 95%, 60d volatility, max drawdown, liquidity score percentile normalization).                                                    | `numpy`, `pandas`, `scripts.lib.recommendation`                                                                             | **HIGH** (Circular dependency risk: imports `VALID_MARKET_REGIMES` and `calculate_risk_adjusted_score` from `recommendation.py`) |
| **Recommendation Engine**   | `scripts/lib/recommendation.py`       | VN Invest Signal Engine v2.0: composite signal scoring, confidence calculation, risk-adjusted score, action logic, trade plan generation.                                               | `scripts.lib.features`, `scripts.lib.risk`, `scripts.lib.vietnam_market`, `scripts.lib.config`                              | **HIGH** (Core business logic, highly coupled to features, risk, market data, and config)                                        |
| **Stock Backtest Engine**   | `scripts/lib/backtest.py`             | Anti-lookahead temporal slicing (`get_as_of_dataset`), execution eligibility, transaction return/slippage math, forward outcome evaluation, walk-forward, regime/confidence evaluation. | `pandas`, `numpy`, `dataclasses`, `scripts.lib.recommendation`, `scripts.lib.regime`, `scripts.lib.vietnam_market`          | **MEDIUM** (High complexity; couples backtesting with operational evaluation dataclasses)                                        |
| **Portfolio Backtest**      | `scripts/lib/portfolio_backtest.py`   | Equal-weight portfolio simulation, selection tie-breaking, position sizing caps, forward performance aggregation, missing outcome preservation.                                         | `pandas`, `numpy`, `scripts.lib.backtest`, `scripts.lib.recommendation`, `scripts.lib.regime`, `scripts.lib.vietnam_market` | **MEDIUM** (Complex aggregation logic, depends heavily on `backtest.py`)                                                         |
| **Pipeline Monitoring**     | `scripts/lib/monitoring.py`           | Production pipeline health checks, JSON schema validation, numerical safety (`NaN`/`Inf` scanning), data & model drift detection (`evaluate_data_and_model_drift`).                     | `jsonschema`, `pandas`, `scripts.lib.config`, `scripts.lib.vietnam_market`                                                  | **LOW** (Fail-closed operational monitoring)                                                                                     |
| **Database Schema**         | `scripts/audit_trail_schema.sql`      | SQL schema definition for audit trail / database storage.                                                                                                                               | SQL                                                                                                                         | **INFORMATIONAL** (Currently unused in production pipeline)                                                                      |
| **Test Runner**             | `scripts/tests/run_tests.py`          | Discovers and executes Python unit & integration test suites via `unittest`.                                                                                                            | `unittest`, `sys`, `os`                                                                                                     | **LOW** (Simple test runner)                                                                                                     |
| **Test Suites**             | `scripts/tests/test_*.py` (20 files)  | Unit, integration, anti-lookahead, unit normalization, schema, parity, and drift monitoring tests.                                                                                      | `unittest`, `pandas`, `numpy`, `jsonschema`                                                                                 | **LOW** (Comprehensive test coverage)                                                                                            |
| **JSON Schema Contract**    | `schemas/recommendations.schema.json` | Draft-07 JSON schema defining structure for `recommendations.json`.                                                                                                                     | None                                                                                                                        | **HIGH** (Single source of truth for backend-frontend data contract)                                                             |
| **Generated Artifacts**     | `generated/`                          | Output directory containing `recommendations.json`, `market.json`, `monitoring.json`, `history/*.json`, and `history/index.json`.                                                       | Generated by `generate_report.py`                                                                                           | **HIGH** (Production data artifacts consumed by frontend and SSG)                                                                |
| **Frontend Entry / Router** | `src/router.tsx`, `src/routes/*`      | TanStack Router setup, route definitions (`/`, `/history`, `/methodology`, `/stock/$symbol`).                                                                                           | React 19, `@tanstack/react-router`                                                                                          | **LOW** (Pure UI presentation and routing)                                                                                       |
| **Frontend Components**     | `src/components/*`                    | UI cards, stock tables, market summary, stock detail modal, Tailwind UI primitives.                                                                                                     | React 19, Lucide React, Tailwind CSS v4                                                                                     | **LOW** (Presentation layer)                                                                                                     |
| **Frontend Data Loader**    | `src/data/loader.ts`                  | Data access layer fetching generated JSON artifacts with fallback mechanics and caching.                                                                                                | Fetch API, `src/types/recommendation.ts`                                                                                    | **HIGH** (Contains runtime fallback hacks and heuristic unit formatting)                                                         |
| **Frontend Types**          | `src/types/recommendation.ts`         | TypeScript interface definitions matching backend recommendations payload.                                                                                                              | TypeScript                                                                                                                  | **MEDIUM** (Must manually sync with `schemas/recommendations.schema.json`)                                                       |
| **Vite / Build Config**     | `vite.config.ts`                      | Vite configuration, TanStack Router plugin, Tailwind CSS v4, SSG prerendering config (`prerenderRoutes`), dev server artifact plugin (`generatedDataPlugin`).                           | Vite, `@tanstack/router-plugin`, `@tailwindcss/vite`                                                                        | **HIGH** (Controls SSG prerendering, dev artifact serving, and build artifact copying)                                           |
| **Package / Dependencies**  | `package.json`, `pnpm-lock.yaml`      | Node.js dependencies, pnpm package manager config (`pnpm@10.30.3`), build scripts.                                                                                                      | Node.js, pnpm                                                                                                               | **LOW** (Standard package configuration)                                                                                         |
| **Python Dependencies**     | `requirements.txt`, `pyproject.toml`  | Pinned Python package dependencies (`pandas==2.2.3`, `vnstock==4.0.7`, `jsonschema==4.26.0`, etc.).                                                                                     | Python 3.11+                                                                                                                | **LOW** (Pinned versions)                                                                                                        |
| **CI/CD Workflows**         | `.github/workflows/*.yml`             | GitHub Actions for Python CI tests (`tests.yml`), linting (`lint-format.yml`), SSG build & deployment (`pages.yml`), and scheduled pipeline execution (`daily-update.yml`).             | GitHub Actions                                                                                                              | **HIGH** (Controls production deployment and automated data refresh)                                                             |
| **Root Documentation**      | `README.md`, `AGENTS.md`              | Project overview, agent instructions, system contracts, memory references.                                                                                                              | None                                                                                                                        | **INFORMATIONAL**                                                                                                                |

---

## 2. Architecture Map

The actual end-to-end architecture derived from code inspection is mapped below layer by layer:

```
Data Sources (VNStock API / KBS / MSN Quote Endpoints)
    ↓
Data Acquisition (scripts/data_provider.py :: VnstockDataProvider)
    ↓
Data Cleaning & Unit Normalization (scripts/lib/vietnam_market.py :: get_clean_ohlcv_data, normalize_ohlcv_units)
    ↓
Feature / Indicator Calculation (scripts/lib/features.py :: calculate_multi_timeframe_features)
    ↓
Market Regime Detection (scripts/lib/regime.py :: detect_market_regime)
    ↓
Stock Signal Scoring (scripts/lib/recommendation.py :: calculate_signal_score, calculate_confidence)
    ↓
Risk Metrics & Liquidity (scripts/lib/risk.py :: calculate_t25_risk_metrics, normalize_universe_liquidity_scores)
    ↓
Recommendation & Trade Plan (scripts/lib/recommendation.py :: generate_recommendation)
    ↓
JSON Schema Validation (scripts/generate_report.py :: load_schema, jsonschema.validate)
    ↓
Generated Artifacts (generated/recommendations.json, market.json, monitoring.json, history/index.json)
    ↓
React SSG Build & Hydration (vite.config.ts :: prerenderRoutes, src/data/loader.ts)
    ↓
GitHub Pages Host (Static hosting via .github/workflows/pages.yml)
```

### Detailed Layer Specifications

#### Layer 1: Data Sources

- **Actual File/Module:** `scripts/data_provider.py`
- **Main Function/Class:** `VnstockDataProvider`
- **Input:** Symbol (e.g. `'VCB'`), date range (`start_date`, `end_date`), source (e.g. `'KBS'`)
- **Output:** Raw `pandas.DataFrame` containing OHLCV quote data
- **Dependencies:** `vnstock` library (`vnstock.api.quote`)
- **Side Effects:** Makes external HTTP network requests, implements retry wait loops
- **Called By:** `scripts/lib/vietnam_market.py :: get_historical_data`

#### Layer 2: Data Acquisition & Validation Contract

- **Actual File/Module:** `scripts/data_provider.py`
- **Main Function/Class:** `validate_canonical_ohlcv`
- **Input:** Raw `pandas.DataFrame` from provider
- **Output:** Validated DataFrame (or raises `CanonicalOHLCVError`)
- **Dependencies:** `pandas`, `numpy`
- **Side Effects:** None (Pure validation)
- **Called By:** `scripts/data_provider.py :: VnstockDataProvider.fetch_ohlcv`

#### Layer 3: Data Cleaning & Unit Normalization

- **Actual File/Module:** `scripts/lib/vietnam_market.py`
- **Main Function/Class:** `normalize_ohlcv_units`, `get_clean_ohlcv_data`
- **Input:** Raw/validated DataFrame, `source_price_unit`, `source_volume_unit`
- **Output:** Clean DataFrame normalized to canonical internal unit contract (`VND/share`, `shares`, `VND`)
- **Dependencies:** `pandas`
- **Side Effects:** None (Returns explicit clean DataFrame)
- **Called By:** `scripts/generate_report.py`, `scripts/lib/recommendation.py`, `scripts/lib/risk.py`, `scripts/lib/backtest.py`

#### Layer 4: Feature / Indicator Calculation

- **Actual File/Module:** `scripts/lib/features.py`
- **Main Function/Class:** `calculate_multi_timeframe_features`, `calculate_single_tf_indicators`, `detect_divergence`
- **Input:** Clean stock DataFrame (`df_clean`)
- **Output:** Dictionary of technical features across 1D, 1W, 1M timeframes (SMA, EMA, RSI, MACD, ATR, divergence signals)
- **Dependencies:** `pandas`
- **Side Effects:** None (Pure mathematical transformation)
- **Called By:** `scripts/lib/recommendation.py :: generate_recommendation`

#### Layer 5: Market Breadth & Market Regime

- **Actual File/Module:** `scripts/lib/regime.py`, `scripts/generate_report.py`
- **Main Function/Class:** `detect_market_regime`
- **Input:** Clean benchmark DataFrames (`df_vnindex`, `df_vn30`), `breadth_ratio`
- **Output:** Market regime dictionary (`regime`, `regime_score`, `confidence`, `metrics`)
- **Dependencies:** `pandas`, `logging`
- **Side Effects:** Logs regime determination info
- **Called By:** `scripts/generate_report.py :: run_pipeline`, `generate_historical_report`

#### Layer 6: Stock Signal Scoring & Recommendation

- **Actual File/Module:** `scripts/lib/recommendation.py`
- **Main Function/Class:** `generate_recommendation`, `calculate_signal_score`, `calculate_confidence`, `calculate_risk_adjusted_score`
- **Input:** Stock symbol, candidate metadata, stock clean DataFrame (`df_stock`), market regime dict, benchmark DataFrames
- **Output:** Comprehensive recommendation dictionary (action, signal_score, confidence, trade_plan, indicators, risk_metrics)
- **Dependencies:** `scripts.lib.features`, `scripts.lib.risk`, `scripts.lib.vietnam_market`, `scripts.lib.config`
- **Side Effects:** None
- **Called By:** `scripts/generate_report.py :: run_pipeline`, `generate_historical_report`

#### Layer 7: Universe Liquidity Score Normalization

- **Actual File/Module:** `scripts/lib/risk.py`
- **Main Function/Class:** `normalize_universe_liquidity_scores`
- **Input:** List of raw recommendation dictionaries
- **Output:** Mutated/updated recommendation list with `liquidity_score` set to 0–100 percentile rank within the universe
- **Dependencies:** `numpy`, `pandas`, `scripts.lib.recommendation` (`VALID_MARKET_REGIMES`, `calculate_risk_adjusted_score`)
- **Side Effects:** Mutates recommendation dictionaries in-place
- **Called By:** `scripts/generate_report.py :: run_pipeline`, `generate_historical_report`

#### Layer 8: Pipeline Monitoring & Schema Validation

- **Actual File/Module:** `scripts/lib/monitoring.py`, `scripts/generate_report.py`
- **Main Function/Class:** `evaluate_production_monitoring`, `load_schema`, `jsonschema.validate`
- **Input:** Recommendations payload, market payload, generated directory path, history index
- **Output:** Schema validation result, `monitoring.json` payload
- **Dependencies:** `jsonschema`, `pandas`
- **Side Effects:** Writes `generated/monitoring.json`
- **Called By:** `scripts/generate_report.py :: main`

#### Layer 9: Artifact Persistence

- **Actual File/Module:** `scripts/generate_report.py`
- **Main Function/Class:** `save_json_files`, `update_history_index`
- **Input:** Dict of JSON payloads and target directory (`generated/`)
- **Output:** Files written to disk (`generated/recommendations.json`, `market.json`, `history/YYYY-MM-DD.json`, `history/index.json`)
- **Dependencies:** `json`, `os`
- **Side Effects:** Overwrites files in `generated/` directory
- **Called By:** `scripts/generate_report.py :: main`, `generate_historical_report`

#### Layer 10: Frontend Data Consumption & Prerendering

- **Actual File/Module:** `vite.config.ts`, `src/data/loader.ts`, `src/routes/*`
- **Main Function/Class:** `loadRecommendationsData`, `loadMarketData`, `loadHistoryIndexData`
- **Input:** Generated JSON artifacts in `public/generated/` or `/generated/`
- **Output:** Typed React component state
- **Dependencies:** Fetch API, TanStack Router, Vite SSG plugin
- **Side Effects:** Prerenders static HTML files at build time (`dist/client/index.html`, `dist/client/history/index.html`)
- **Called By:** React routes during SSG build and client hydration

---

## 3. Dependency Analysis

### Coupling Graph & Import Traversal

The import structure of the Python backend is analyzed below:

```
generate_report.py
    ├── scripts.lib.vietnam_market
    │       └── scripts.data_provider
    ├── scripts.lib.regime
    ├── scripts.lib.recommendation
    │       ├── scripts.lib.features
    │       ├── scripts.lib.risk
    │       │       └── scripts.lib.recommendation  <-- CIRCULAR DEPENDENCY!
    │       ├── scripts.lib.vietnam_market
    │       └── scripts.lib.config
    ├── scripts.lib.risk
    │       └── scripts.lib.recommendation (VALID_MARKET_REGIMES, calculate_risk_adjusted_score) <-- CIRCULAR DEPENDENCY!
    ├── scripts.lib.monitoring
    │       ├── scripts.lib.config
    │       └── scripts.lib.vietnam_market
    ├── scripts.lib.backtest
    └── scripts.lib.portfolio_backtest
```

### Key Architectural Findings

1. **Circular Import Dependency (`risk.py` <-> `recommendation.py`):**
   - `scripts/lib/risk.py` imports `VALID_MARKET_REGIMES` and `calculate_risk_adjusted_score` from `scripts.lib.recommendation`.
   - `scripts/lib/recommendation.py` imports `calculate_t25_risk_metrics` from `scripts.lib.risk`.
   - _Impact:_ Creates a direct circular import loop between `risk.py` and `recommendation.py`. In addition, `risk.py` contains market regime validation and risk-adjusted scoring logic that should be owned by a shared quantitative scoring module.

2. **Excessive Coupling & Duplicated Configuration Re-Exports:**
   - `scripts/lib/config.py` defines quantitative constants (`SIGNAL_MODEL_VERSION`, `SIGNAL_WEIGHTS`, `DIVERGENCE_TIMEFRAME_WEIGHTS`, `VALID_MARKET_REGIMES`).
   - `scripts/lib/recommendation.py` re-exports these exact same constants.
   - _Impact:_ Modules import constants from `recommendation.py` instead of `config.py`, making `recommendation.py` a bottleneck dependency.

3. **In-Place Mutation Side Effects:**
   - `normalize_universe_liquidity_scores` in `scripts/lib/risk.py` takes a list of recommendation dictionaries and mutates `rec['risk_metrics']['liquidity_score']` and `rec['risk_adjusted_score']` in-place.
   - _Impact:_ Pure quantitative functions should be non-mutating and return new structures.

4. **God Modules / Too Many Responsibilities:**
   - `scripts/generate_report.py`: Handles CLI parsing, historical report generation, snapshot loading, historical OHLCV loading, history index file management, pipeline execution, reproducibility canonicalization, schema validation, and JSON writing.
   - `scripts/lib/backtest.py`: Combines point-in-time dataset slicing (`get_as_of_dataset`), market execution eligibility calculations (`evaluate_execution_eligibility`), stock-level backtesting (`evaluate_forward_outcomes`), walk-forward evaluation, regime calibration, component calibration, and confidence calibration in a single 1000+ line file.

5. **Hardcoded Stock Universe in Production Code:**
   - `scripts/lib/vietnam_market.py` contains `UniverseProvider` with a hardcoded candidate stock universe list of 30 symbols.
   - _Impact:_ Adding or modifying candidate stocks requires editing Python source code instead of configuration or data snapshots.

---

## 4. Architecture Problems & Risk Categorization

### Critical Architectural Problems

1. **Circular Import Dependency Between Quant Modules (`risk.py` <-> `recommendation.py`)**
   - **Evidence:** `scripts/lib/risk.py` imports `from scripts.lib.recommendation import VALID_MARKET_REGIMES, calculate_risk_adjusted_score`. `scripts/lib/recommendation.py` imports `from scripts.lib.risk import calculate_t25_risk_metrics`.
   - **Why it matters:** Violates layered software architecture. Quantitative risk calculation and liquidity score normalization rely on higher-level recommendation scoring functions and constants.
   - **Affected Modules:** `scripts/lib/risk.py`, `scripts/lib/recommendation.py`
   - **Potential Consequence:** Import errors during refactoring, inability to execute risk module independently in isolated test environments.
   - **Recommended Direction:** Move `calculate_risk_adjusted_score` and `VALID_MARKET_REGIMES` to `config.py` / a shared scoring module (`scripts/lib/scoring.py`), establishing a unidirectional graph: `config` -> `risk` -> `scoring` -> `recommendation`.

2. **Frontend UI Utility Performs Business Logic & Presentation Conversions**
   - **Evidence:** `src/data/loader.ts` contains fallback dummy data generation and client-side unit heuristics; `src/lib/format.ts` formats raw currency values.
   - **Why it matters:** Violates strict rule that Python backend is the sole source of quantitative truth and React frontend is presentation-only.
   - **Affected Modules:** `src/data/loader.ts`, `src/lib/format.ts`
   - **Potential Consequence:** Inconsistencies between backend calculation and frontend display if fallback data or client formatting diverges.
   - **Recommended Direction:** Remove fallback dummy data generation from frontend loader; ensure backend outputs schema-compliant JSON or explicit error states.

### High Priority Problems

1. **God Module Responsibilities in Pipeline Orchestrator (`scripts/generate_report.py`)**
   - **Evidence:** `generate_report.py` is 600+ lines mixing CLI argument parsing, snapshot file loading, history index persistence, schema validation, report canonicalization, execution timing, and file I/O.
   - **Why it matters:** Orchestrator is difficult to unit test and maintain; changes to historical loading risk breaking daily production report execution.
   - **Affected Modules:** `scripts/generate_report.py`
   - **Potential Consequence:** Regression bugs when modifying historical or snapshot report generation logic.
   - **Recommended Direction:** Decompose `generate_report.py` into separate modules for report pipeline orchestration, CLI argument handling, and snapshot persistence.

2. **Hardcoded Candidate Stock Universe in Source Code (`scripts/lib/vietnam_market.py`)**
   - **Evidence:** `UniverseProvider.get_default_universe()` defines a static list of 30 stock dictionaries inside python code.
   - **Why it matters:** Changing universe scope requires source code changes and deployment.
   - **Affected Modules:** `scripts/lib/vietnam_market.py`
   - **Potential Consequence:** Inflexibility in running multi-universe research or updating tracking symbols.
   - **Recommended Direction:** Externalize universe candidate definitions into JSON/YAML configuration files or universe snapshot files (`Universe(as_of=T)`).

### Medium Priority Problems

1. **In-Place Mutation of Recommendation Payloads during Liquidity Normalization**
   - **Evidence:** `normalize_universe_liquidity_scores` in `scripts/lib/risk.py` modifies dictionary items in-place (`r['risk_metrics']['liquidity_score']` and `r['risk_adjusted_score']`).
   - **Why it matters:** Non-functional side effects make pipeline behavior dependent on call order and object mutation state.
   - **Affected Modules:** `scripts/lib/risk.py`, `scripts/generate_report.py`
   - **Potential Consequence:** Data leakage or unexpected state mutations if recommendations list is reused across calculations.
   - **Recommended Direction:** Refactor `normalize_universe_liquidity_scores` to return new updated dictionaries or explicit scores without mutating inputs.

2. **Duplicate Re-Exports of Quantitative Configuration Constants**
   - **Evidence:** `SIGNAL_MODEL_VERSION`, `SIGNAL_WEIGHTS`, etc., are defined in `config.py` and re-assigned in `recommendation.py`.
   - **Why it matters:** Creates confusion over where constants should be imported from and risks value drift if changed in one place.
   - **Affected Modules:** `scripts/lib/config.py`, `scripts/lib/recommendation.py`
   - **Potential Consequence:** Inconsistent parameter usage across quantitative and backtest modules.
   - **Recommended Direction:** Standardize all quant parameter imports directly from `scripts.lib.config`.

### Low Priority Problems

1. **Unused SQL Database Schema File (`scripts/audit_trail_schema.sql`)**
   - **Evidence:** File `scripts/audit_trail_schema.sql` exists in `scripts/` but is never referenced by any python code, CI workflow, or test.
   - **Why it matters:** Dead code / clutter in repository.
   - **Affected Modules:** `scripts/audit_trail_schema.sql`
   - **Potential Consequence:** Maintenance confusion for developers wondering if a SQL database is active.
   - **Recommended Direction:** Document as optional audit schema or archive in documentation folder.
