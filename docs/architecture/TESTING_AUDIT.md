# Testing Audit — Test Suite Inventory & Coverage Analysis

## 1. Test Suite Inventory

The repository contains 20 Python test modules located in `scripts/tests/`, managed and executed by `scripts/tests/run_tests.py` using standard `unittest`.

| Test Module                      | Primary Focus Area                                     | Test Count    | Network Dependency | Execution Time | Functional Coverage                                                                                                                                       |
| -------------------------------- | ------------------------------------------------------ | ------------- | ------------------ | -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_data_provider.py`          | Data acquisition & `validate_canonical_ohlcv` contract | 18            | Mocked / Offline   | ~0.1s          | Verifies column checks, NaN/Inf rejection, date sorting, and error handling.                                                                              |
| `test_data_quality.py`           | Clean OHLCV boundary & data quality levels             | 14            | Offline            | ~0.2s          | Verifies `SUFFICIENT`, `PARTIAL`, `INSUFFICIENT` data quality classification.                                                                             |
| `test_data_date.py`              | Date parsing & timestamp extraction                    | 10            | Offline            | ~0.1s          | Verifies `extract_latest_trading_date` and timezone rules.                                                                                                |
| `test_unit_normalization.py`     | Unit normalization (`normalize_ohlcv_units`)           | 11            | Offline            | ~0.1s          | Verifies conversion from thousand VND to full VND, volume, and 20d value exactness.                                                                       |
| `test_config.py`                 | Quantitative parameters & config bounds                | 12            | Offline            | ~0.1s          | Verifies weights, threshold boundaries, regime parameters, and config invariants.                                                                         |
| `test_regime.py`                 | Market regime detection (`detect_market_regime`)       | 12            | Offline            | ~0.1s          | Verifies regime scores, confidence, breadth ratio integration, and default defensive fallback.                                                            |
| `test_risk.py`                   | T+2.5 Risk calculations & liquidity normalization      | 28            | Offline            | ~0.4s          | Verifies VaR 95%, ES 95%, Max Drawdown, 60d Volatility, 3-session EOD returns, and liquidity score percentiles.                                           |
| `test_recommendation.py`         | Signal scoring, confidence, & trade plan               | 35            | Offline            | ~0.5s          | Verifies composite signal score weights, confidence calculation, action assignment logic, trade plan bounds, and module anti-lookahead regression.        |
| `test_backtest.py`               | Stock-level backtesting & walk-forward                 | 42            | Offline            | ~0.8s          | Verifies point-in-time slicing (`get_as_of_dataset`), execution eligibility, forward outcomes, walk-forward generation, and confidence calibration.       |
| `test_execution_costs.py`        | Execution return math & slippage adjustment            | 16            | Offline            | ~0.2s          | Verifies adverse slippage, transaction costs, BUY/SELL/WATCH return math, and cost monotonicity.                                                          |
| `test_portfolio_backtest.py`     | Equal-weight portfolio backtesting                     | 55            | Offline            | ~1.5s          | Verifies constituent selection, tie-breaking, position sizing caps, unallocated weight preservation, missing outcome handling, and portfolio aggregation. |
| `test_e2e_backtest_integrity.py` | End-to-end backtesting pipeline integrity              | 22            | Offline            | ~1.0s          | Verifies complete pipeline integrity from raw historical data through signal, outcome, execution, cost, portfolio construction, and aggregation.          |
| `test_monitoring.py`             | Operational pipeline health & schema checks            | 24            | Offline            | ~0.3s          | Verifies payload schema validation, missing artifact detection, NaN/Inf scanning, and data freshness rules.                                               |
| `test_drift_monitoring.py`       | Data & model output drift detection                    | 32            | Offline            | ~0.6s          | Verifies historical report baseline extraction, distribution checks, threshold boundaries, and history index integrity.                                   |
| `test_historical_report.py`      | Deterministic `--as-of` report generation              | 28            | Offline            | ~0.8s          | Verifies point-in-time snapshot loading, date parsing, historical output structure, and index persistence.                                                |
| `test_history_index.py`          | Persistence layer for `history/index.json`             | 15            | Offline            | ~0.1s          | Verifies fail-closed JSON index read/write operations, sorting, and duplicate date handling.                                                              |
| `test_parity.py`                 | Production vs historical pipeline parity               | 18            | Offline            | ~8.0s          | Verifies exact quantitative parity between `run_pipeline` and `generate_historical_report`.                                                               |
| `test_schema.py`                 | JSON Schema validation contract                        | 10            | Offline            | ~0.2s          | Validates generated JSON payloads against `schemas/recommendations.schema.json`.                                                                          |
| `test_ssg_html.py`               | SSG build artifact static HTML checks                  | 8             | Offline            | ~0.1s          | Verifies static HTML title tags, meta tags, and rendered content in `dist/client/`. Auto-skips when build artifacts are missing.                          |
| `test_dependencies.py`           | Environment & dependency version verification          | 5             | Offline            | ~0.05s         | Verifies exact pinned dependency versions (`pandas==2.2.3`, `vnstock==4.0.7`, etc.).                                                                      |
| **TOTAL**                        | **20 Test Files**                                      | **456 Tests** | **100% Offline**   | **~112s**      | **High Backend Quant Coverage**                                                                                                                           |

---

## 2. Test Execution Architecture

Tests are executed via the unified runner:

```bash
python scripts/tests/run_tests.py
```

Or via standard `pytest`:

```bash
python -m pytest
```

### Key Strengths

- **100% Offline Determinism:** All quantitative tests run using synthetic mock DataFrames or pre-saved local fixture data without making external network calls.
- **Data Quality & Schema Contract Testing:** Rigorous schema compliance testing ensures backend output changes are caught before breaking frontend SSG builds.
- **Anti-Lookahead Regression Tests:** Explicit tests verify that mutating future data (`> T`) produces zero change in historical signals or recommendations.

---

## 3. Critical Path Testing Gaps

1. **Frontend Component Unit Tests:**
   - _Gap:_ There are currently no Vitest / React Testing Library unit tests for TypeScript frontend components (`src/components/*`).
   - _Impact:_ UI regressions in recommendation cards or stock tables are not caught during automated Python CI testing.

2. **Frontend End-to-End Playwright Tests:**
   - _Gap:_ No automated browser Playwright / Cypress e2e tests exist to verify frontend rendering and routing in an automated headless browser environment.
