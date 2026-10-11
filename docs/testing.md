# Testing Architecture & Guidelines

This document specifies the test suite architecture, execution standards, fixtures, network isolation mechanics, and testing markers for **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Authoritative Test Runners & Execution Standards

The project utilizes standardized test runners for both backend Python and frontend React components:

- **Frontend Test Runner**: Vite+ test (`vp test` / `pnpm test` via `vite-plus/test`).
- **Backend Test Runner**: Native `pytest` (`uv run --frozen pytest`).
- **Test Naming Convention**: All test functions and methods must use descriptive behavior-driven names following `test_<behavior>()` (Python) or descriptive `it("<behavior>")` / `describe("<behavior>")` blocks (TypeScript).
- **Behavior-Driven Docstrings & Descriptions**: Test descriptions and inline comments must state the behavior or condition tested directly.

---

## 2. Test Suite Layout

### 2.1 Backend Test Layout (`scripts/tests/`)

All Python backend tests reside under `scripts/tests/`:

```text
scripts/tests/
├── conftest.py                   # Pytest hooks, slow-test reporting, socket isolation
├── fixtures.py                   # Fake market providers and synthetic DataFrame generators
├── test_artifact_publisher.py    # Publisher, schema, transaction, rollback unit tests
├── test_artifact_transaction.py  # Atomic directory transactions, POSIX locking, recovery
├── test_backtest.py              # Signal engine backtest and execution eligibility tests
├── test_config.py                # Pipeline and baseline configuration unit tests
├── test_data_*.py                # Data acquisition, validation, normalization, and bounds
├── test_domain.py                # Domain dataclasses, Universe, and candidate models
├── test_drift_monitoring.py      # Operational model/data drift and baseline lookbacks
├── test_e2e_backtest_integrity.py# End-to-end backtest pipeline integrity and non-lookahead
├── test_engines.py               # Pure quant engines (MarketAnalysis, Signal, Risk)
├── test_execution_costs.py       # Slippage and transaction cost model unit tests
├── test_historical_report.py     # Point-in-time report generation tests
├── test_monitoring.py            # Operational checks and monitoring result payload tests
├── test_parity.py                # Parity between run_pipeline and generate_historical_report
├── test_performance_subsystem.py # Performance metrics, timing, budgets, and regression
├── test_pipeline.py              # Pipeline context, execution stages, and lifecycle
├── test_portfolio_backtest.py    # Portfolio allocation, cost deductions, and determinism
├── test_provenance.py            # Provenance manifest and schema validation tests
├── test_quant_config.py          # QuantConfig immutability, hashing, and version contracts
├── test_recommendation.py        # Signal scoring, multi-timeframe weights, action logic
├── test_regime.py                # Market regime detection (BULLISH, BEARISH, SIDEWAYS)
├── test_risk.py                  # T+2.5 VaR, Expected Shortfall, max drawdown, trade plans
├── test_schema.py                # Schema registry version resolution and schema validation
└── test_unit_normalization.py    # Stock unit conversions and market tick price rounding
```

### 2.2 Frontend Test Layout (`src/tests/`)

Frontend unit, component, and regression tests reside under `src/tests/`:

```text
src/tests/
└── frontend-correctness.test.tsx # Component rendering, typed loader validation, keyboard nav & retry tests
```

---

## 3. Network Isolation Mechanics

All backend unit and integration tests execute **strictly offline**.

- **Socket Monkeypatching**: `conftest.py` executes `enforce_network_isolation()` during pytest initialization.
- **Implementation**: Monkeypatches `socket.socket.connect` to raise a descriptive `RuntimeError` if any test attempts an unmocked network connection.
- **Provider Mocking**: Tests interacting with market data must either:
  - Inject `FakeMarketDataProvider` from `scripts/tests/fixtures.py`.
  - Patch provider methods such as `scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv`.

---

## 4. Test Categories & Pytest Markers

Backend tests are categorized using pytest markers defined in `pyproject.toml` under `[tool.pytest.ini_options]`:

| Marker                     | Purpose                                                                                       |
| :------------------------- | :-------------------------------------------------------------------------------------------- |
| `@pytest.mark.unit`        | Fast, isolated unit tests for pure functions, domain models, and quant calculations.          |
| `@pytest.mark.integration` | Multi-component integration tests (pipeline stages, portfolio backtest, artifact publishing). |
| `@pytest.mark.e2e`         | End-to-end workflow validation tests (pipeline context -> output integrity).                  |
| `@pytest.mark.live`        | Tests requiring external API access (skipped by default in standard CI).                      |
| `@pytest.mark.slow`        | Long-running tests (taking $\ge 5.0$ seconds). Reported automatically by `conftest.py` hooks. |

---

## 5. Authoritative Testing Commands

### 5.1 Frontend Testing Commands

```bash
# Execute full frontend test suite in real browser mode
pnpm test
# OR via Vite+ CLI
vp test

# Run frontend check (linting, type checking, formatting)
pnpm check
# OR via Vite+ CLI
vp check
```

### 5.2 Backend Testing Commands

```bash
# Execute full Python test suite
uv run --frozen pytest

# Run specific backend test file
uv run --frozen pytest scripts/tests/test_domain.py

# Run targeted test function
uv run --frozen pytest scripts/tests/test_portfolio_backtest.py -k "test_portfolio_allocation"
```

---

## 6. CI Integration

Both frontend and backend test suites run automatically in GitHub Actions (`.github/workflows/tests.yml`). Path filters conditionally trigger `frontend-test` (when frontend files change) and `backend-test` (when backend files change).
