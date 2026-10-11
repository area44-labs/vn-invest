# Testing Architecture & Guidelines

This document specifies the testing strategy, test locations, network isolation rules, and test runners for **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Purpose & When to Consult

Consult this document when writing new tests, investigating test failures, or setting up test fixtures across backend Python or frontend React modules.

---

## 2. Test Locations & Architecture

```text
scripts/tests/                   # Backend Python Pytest Suite
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

## 3. Network Isolation & Test Fixtures

- **Backend Socket Isolation**: `conftest.py` executes `enforce_network_isolation()` during pytest initialization, blocking unmocked network sockets.
- **Provider Mocking**: Backend tests use `FakeMarketDataProvider` from `scripts/tests/fixtures.py` or `pytest-mock` (`mocker`) to mock provider API calls.
- **Frontend Real Browser Mode**: Frontend tests run in Playwright Headless Chromium via `@vitest/browser-playwright`.

---

## 4. Pytest Markers (`pyproject.toml`)

- `@pytest.mark.unit`: Fast unit tests for pure functions, models, and math calculations.
- `@pytest.mark.integration`: Multi-component pipeline, backtest, and publisher tests.
- `@pytest.mark.e2e`: End-to-end integration tests.
- `@pytest.mark.live`: Tests requiring live network access (skipped in CI).
- `@pytest.mark.slow`: Tests taking $\ge 5.0$ seconds.

---

## 5. Authoritative Test Commands

### Backend Tests

```bash
# Full backend suite
uv run --frozen pytest

# Targeted backend test file
uv run --frozen pytest scripts/tests/test_domain.py

# Targeted test function
uv run --frozen pytest scripts/tests/test_pipeline.py -k "test_pipeline_execution"
```

### Frontend Tests

```bash
# Full frontend test suite (in Playwright Chromium)
vp test

# Frontend typecheck, linter, and formatting check
vp check
```
