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
| **Frontend Types**          | `src/types/recommendation.ts`         | TypeScript interface definitions matching backend recommendations payload.                                                                                                              | TypeScript                                                                                                                  | **HIGH** (Contract drift detected: `MarketRegime` type misses `"NEUTRAL"` present in Python `VALID_MARKET_REGIMES`)              |
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

---

## 3. Dependency Analysis & Circular Import Audit

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
   - `scripts/lib/risk.py` imports `VALID_MARKET_REGIMES` and `calculate_risk_adjusted_score` from `scripts.lib.recommendation` inside `normalize_universe_liquidity_scores()`.
   - `scripts/lib/recommendation.py` imports `calculate_t25_risk_metrics` from `scripts.lib.risk`.
   - _Impact:_ Deferring the import into function scope inside `normalize_universe_liquidity_scores()` avoids a top-level `ImportError` at startup, but leaves a bidirectional runtime dependency loop (`recommendation` -> `risk` -> `recommendation`). `risk.py` should strictly focus on risk metrics (`calculate_t25_risk_metrics`, `calculate_t25_returns`), while shared scoring logic (`calculate_risk_adjusted_score`) and constants (`VALID_MARKET_REGIMES`) belong in `scripts/lib/config.py` or a dedicated `scripts/lib/scoring.py` module.

2. **Contract Drift (Python Schema vs TypeScript Types):**
   - Python `VALID_MARKET_REGIMES` in `config.py`/`recommendation.py` defines 6 regimes: `{"STRONG_BULL", "BULL", "NEUTRAL", "DEFENSIVE", "BEAR", "PANIC"}`.
   - TypeScript `MarketRegime` type in `src/types/recommendation.ts` defines 5 regimes: `"STRONG_BULL" | "BULL" | "DEFENSIVE" | "BEAR" | "PANIC"`, omitting `"NEUTRAL"`.
   - _Impact:_ Manual synchronization of TypeScript interfaces leads to silent type drift. Phase 6 will implement automated build-time generation of TypeScript interfaces directly from `schemas/recommendations.schema.json`.

3. **God Modules / Too Many Responsibilities:**
   - `scripts/generate_report.py`: Handles CLI parsing, historical report generation, snapshot loading, historical OHLCV loading, history index file management, pipeline execution, reproducibility canonicalization, schema validation, and JSON writing.
   - `scripts/lib/backtest.py`: Combines point-in-time dataset slicing (`get_as_of_dataset`), market execution eligibility calculations (`evaluate_execution_eligibility`), stock-level backtesting (`evaluate_forward_outcomes`), walk-forward evaluation, regime calibration, component calibration, and confidence calibration in a single 1000+ line file.

4. **Hardcoded Stock Universe in Production Code:**
   - `scripts/lib/vietnam_market.py` contains `UniverseProvider` with a hardcoded candidate stock universe list of 30 symbols.
   - _Impact:_ Adding or modifying candidate stocks requires editing Python source code instead of configuration or data snapshots.
