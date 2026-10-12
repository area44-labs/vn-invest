# Testing Architecture & Guidelines

This document specifies the testing strategy, test locations, network isolation rules, and test runners for **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Test Locations & Architecture

The test layout below illustrates primary backend and frontend test files:

```text
scripts/tests/                   # Backend Python Pytest Suite (illustrative, not exhaustive)
├── conftest.py                   # Network isolation hooks and slow-test reporters
├── fixtures.py                   # Fake market provider fixtures and synthetic DataFrames
├── test_artifact_publisher.py    # Publisher, transaction, and schema validation tests
├── test_artifact_transaction.py  # Atomic persistence, POSIX locking, and recovery tests
├── test_data_*.py                # Acquisition, normalization, and bounds validation
├── test_engines.py               # Pure quantitative signal and risk engine tests
├── test_historical_report.py     # PIT historical report generation tests
├── test_monitoring.py            # Operational quality and drift checks tests
└── test_pipeline.py              # Production pipeline context and stage tests

src/tests/                       # Frontend React Vitest Browser Suite
└── frontend-correctness.test.tsx # Component rendering, typed loader validation, and navigation tests
```

---

## 2. Network Isolation & Test Fixtures

- **Backend Socket Isolation**: `conftest.py` executes `enforce_network_isolation()` during pytest initialization, blocking unmocked network sockets.
- **Provider Mocking**: Backend tests use `FakeMarketDataProvider` from `scripts/tests/fixtures.py` or `pytest-mock` (`mocker`) to mock provider API calls.
- **Frontend Real Browser Mode**: Frontend tests run in Playwright Headless Chromium via `@vitest/browser-playwright`.

---

## 3. Pytest Markers (`pyproject.toml`)

- `@pytest.mark.unit`: Fast unit tests for pure functions, models, and math calculations.
- `@pytest.mark.integration`: Multi-component pipeline, backtest, and publisher tests.
- `@pytest.mark.e2e`: End-to-end integration tests.
- `@pytest.mark.live`: Tests requiring live network access. (Note: `uv run --frozen pytest` in CI executes collected tests unless explicit marker filter flags `-m "not live"` are supplied).
- `@pytest.mark.slow`: Tests taking >= 5.0 seconds.

---

## 4. Authoritative Testing & Validation Commands

### Backend Commands (Python >= 3.14 via `uv`)

```bash
# Full backend test suite
uv run --frozen pytest

# Targeted backend test file
uv run --frozen pytest scripts/tests/test_domain.py

# Targeted test function
uv run --frozen pytest scripts/tests/test_pipeline.py -k "test_sequential_stage_execution_order"

# Backend linting & formatting checks
uv run --frozen ruff check --fix scripts    # Auto-fix check (modifies source files)
uv run --frozen ruff format scripts         # Formatting check (modifies source files)
```

### Frontend Commands (Vite+ / `vp`)

```bash
# Install dependencies & Playwright Chromium binaries
vp install
pnpm exec playwright install --with-deps chromium

# Full frontend test suite (in Playwright Chromium)
vp test

# Preferred frontend validation (lints, typechecks, auto-formats; modifies source files)
vp check

# Production static site prerender build
vp build
```
