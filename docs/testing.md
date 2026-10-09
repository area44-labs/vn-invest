# Testing Architecture & Guidelines

This document specifies the test suite architecture, execution standards, fixtures, network isolation mechanics, and testing markers for **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Authoritative Test Runner & Execution Standard

- **Test Runner**: Native `pytest` (`uv run --frozen pytest`).
- **Python Version**: Python 3.14 via `uv`.
- **Test Naming Convention**: All test functions and methods must use descriptive behavior-driven names following `test_<behavior>()` (e.g. `test_valid_dataset_returns_sufficient_status`). Avoid numeric index prefixes (`test_1_...`) or vague case names (`test_case_a_...`).
- **Behavior-Driven Docstrings & Descriptions**: Test docstrings and inline comments must state the behavior or condition tested directly (e.g. "Verifies that an invalid symbol is recorded in audit exclusions and passes audit set invariants"). Generic or uninformative numbered labels (`Test 1:`, `Scenario 1:`, `Case A`, `1. ...`) are strictly prohibited.

---

## 2. Test Suite Layout

All Python backend tests reside under `scripts/tests/`.

```text
scripts/tests/
├── conftest.py                   # Pytest hooks, slow-test reporting, socket isolation
├── fixtures.py                   # Fake market providers and synthetic DataFrame generators
├── test_artifact_publisher.py    # Publisher, schema, transaction, rollback unit tests
├── test_artifact_transaction.py  # Atomic directory transactions, POSIX locking, recovery
├── test_backtest.py              # Signal engine backtest and execution eligibility tests
├── test_config.py                # Pipeline and baseline configuration unit tests
├── test_data_*.py                # Data acquisition, validation, normalization, and bounds
├── test_dependencies.py          # Lockfile, uv, and dependency version invariants
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

### 2.1 Dependency Version Inspection Policy

The test suite in `scripts/tests/test_dependencies.py` enforces runtime dependency version invariants.

- **Inspection Mechanism**: Uses `importlib.metadata.version()` to inspect installed runtime package versions without relying on deprecated package attributes (such as `jsonschema.__version__`) or permissive default fallbacks.
- **Contract Boundary**: Verifies that installed versions satisfy minimum required version bounds declared in `pyproject.toml` (`vnstock >= 4.0.8`, `pandas >= 3.0.0`, `numpy >= 2.5.0`, `jsonschema >= 4.26.0`).
- **Reproducibility Guarantee**: In CI and production builds, `uv sync --frozen` installs the exact pinned versions locked in `uv.lock`.

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

Tests are categorized using pytest markers defined in `pyproject.toml` under `[tool.pytest.ini_options]`:

| Marker                     | Purpose                                                                                       |
| :------------------------- | :-------------------------------------------------------------------------------------------- |
| `@pytest.mark.unit`        | Fast, isolated unit tests for pure functions, domain models, and quant calculations.          |
| `@pytest.mark.integration` | Multi-component integration tests (pipeline stages, portfolio backtest, artifact publishing). |
| `@pytest.mark.e2e`         | End-to-end workflow validation tests (pipeline context -> output integrity).                  |
| `@pytest.mark.live`        | Tests requiring external API access (skipped by default in standard CI).                      |
| `@pytest.mark.slow`        | Long-running tests (taking $\ge 5.0$ seconds). Reported automatically by `conftest.py` hooks. |

---

## 5. Authoritative Testing Commands

### 5.1 Run Full Test Suite (CI Command)

```bash
uv run --frozen pytest
```

### 5.2 Run Specific Test File or Class

```bash
uv run --frozen pytest scripts/tests/test_domain.py
uv run --frozen pytest scripts/tests/test_engines.py::TestQuantSignalEngine
```

### 5.3 Run Tests Matching a Marker

```bash
uv run --frozen pytest -m unit
uv run --frozen pytest -m integration
```

### 5.4 Run Targeted Test Function

```bash
uv run --frozen pytest scripts/tests/test_portfolio_backtest.py -k "test_portfolio_allocation"
```

---

## 6. Fixtures & Test Data Helpers

- **`FakeMarketDataProvider`** (`scripts/tests/fixtures.py`): In-memory mock data provider returning deterministic OHLCV DataFrames without network requests.
- **`make_valid_canonical_df`** (`scripts/tests/fixtures.py`): Generates canonical OHLCV DataFrames with valid price relationships (`high >= low`, `open`/`close` within `high`/`low`, non-negative volume, sorted trading dates).
- **`conftest.py` Hooks**: Logs `SLOW TEST: <test_name> — <elapsed>s` warnings for any test taking $\ge 5.0$ seconds.
