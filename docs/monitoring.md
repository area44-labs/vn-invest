# Operational Monitoring, Data Quality & Performance Regression

This document specifies the operational monitoring architecture, core quality checks, status evaluation semantics, performance regression baselines, and output contract in **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Monitoring Architecture & Responsibilities (`scripts/monitoring/`)

Operational monitoring runs in Stage 8 (`MonitoringStage`) of the production pipeline. It evaluates the current run's generated payloads (`recommendations.json`, `market.json`, `performance.json`) and historical index metadata (`generated/history/index.json`) to verify payload integrity and runtime health before publication.

```text
Pipeline Context Payloads (recommendations, market, performance)
  -> evaluate_production_monitoring() (scripts/monitoring/evaluator.py)
     ├── Operational Data Quality Checks (scripts/monitoring/checks.py)
     ├── Schema Compliance Verification (scripts/schema/registry.py)
     └── Mode-Aware Performance Regression Evaluation (scripts/performance/regression.py)
  -> PipelineMonitoringResult -> Serialized to generated/monitoring.json
     ├── Status "PASS" or "WARNING" -> Proceed to Stage 9 Artifact Publishing
     └── Status "FAIL" -> Abort pipeline immediately, preserving disk state byte-for-byte
```

### Module Responsibilities

- **`scripts/monitoring/evaluator.py`**: Main orchestrator (`evaluate_production_monitoring`). Aggregates check results, assigns overall pipeline monitoring status (`PASS`, `WARNING`, `FAIL`), and constructs the final payload.
- **`scripts/monitoring/checks.py`**: Implementation of operational quality checks (schema compliance, data freshness, symbol coverage, numeric safety, index integrity).
- **`scripts/monitoring/models.py`**: Frozen dataclasses defining check results (`CheckResult`), drift observations (`DriftCheckResult`), and overall monitoring results (`PipelineMonitoringResult`).
- **`scripts/monitoring/metrics.py`**: Quantitative metric extraction helpers for symbol processing ratios and action proportions.
- **`scripts/performance/regression.py`**: Timing metric collection and mode-aware performance regression checks.

---

## 2. Core Operational Checks

Operational checks evaluated during `evaluate_production_monitoring()`:

| Check Name                      | Status Conditions           | Description                                                                                                                     |
| :------------------------------ | :-------------------------- | :------------------------------------------------------------------------------------------------------------------------------ |
| `schema_validation`             | `PASS` / `FAIL`             | Validates recommendations payload against `schemas/v2/recommendations.schema.json`. Requires valid, non-empty `schema_version`. |
| `data_freshness`                | `PASS` / `WARNING` / `FAIL` | Confirms `data_as_of` matches reference date or remains within allowed trading delay window.                                    |
| `symbol_processing_count`       | `PASS` / `WARNING` / `FAIL` | Evaluates percentage of candidate universe successfully processed (`processed_ratio`).                                          |
| `market_regime_validity`        | `PASS` / `FAIL`             | Confirms market regime is one of valid regimes (`STRONG_BULL`, `BULL`, `DEFENSIVE`, `BEAR`, `PANIC`).                           |
| `history_index_integrity`       | `PASS` / `FAIL`             | Verifies `generated/history/index.json` chronological descending order and metadata integrity.                                  |
| `numeric_safety`                | `PASS` / `FAIL`             | Recursively scans all output payloads for illegal `NaN`, `Inf`, or `-Inf` floating point values.                                |
| `performance_payload_integrity` | `PASS` / `FAIL`             | Confirms timing metrics payload conforms to `schemas/v2/performance.schema.json`.                                               |
| `performance_regression`        | `PASS` / `WARNING` / `FAIL` | Evaluates stage execution runtimes against mode-aware baselines.                                                                |

---

## 3. Status Evaluation & Publication Semantics

Operational check results map directly to overall pipeline execution decisions:

- **`PASS`**: All operational checks satisfied. Artifact publication completes code 0.
- **`WARNING`**: Non-critical threshold exceedances (e.g. DEGRADED timing exceedance within failure threshold or provider budget overruns). Pipeline logs diagnostic warnings and completes atomic artifact publication code 0.
- **`FAIL`**: Critical failures (schema validation error, non-finite numeric value, or severe timing regression exceeding failed threshold). Execution halts immediately (`SystemExit(1)`), blocking artifact publication and preserving existing files in `generated/` 100% byte-for-byte unchanged.

---

## 4. Performance Regression Baselines (`scripts/performance/regression.py`)

Performance monitoring evaluates stage execution runtimes using explicit execution mode flags:

- **Offline / Test Mode (`update_data=False`)**: Evaluates runtimes against static offline reference baselines (`PERFORMANCE_STAGE_BASELINES`, e.g. `pipeline` 10.0s, `stock_fetch` 5.0s, `benchmark_fetch` 1.0s).
- **Live Production Update Mode (`update_data=True`)**: Dynamically computes live baselines using actual logical workload counts (`benchmark_request_count`, `stock_request_count`) and provider throttle delay (`DEFAULT_UPDATE_THROTTLE_DELAY = 3.5s` per request plus network latency ~0.8s):
  - Benchmark fetch baseline: $N_{\text{benchmarks}} \times (3.5 + 0.8)\text{s}$
  - Stock fetch baseline: $N_{\text{stocks}} \times (3.5 + 0.8)\text{s}$
  - Pipeline total baseline: $B_{\text{bench}} + B_{\text{stock}} + 5.0\text{s}$

---

## 5. Output Payload Contract (`generated/monitoring.json`)

The monitoring payload written to `generated/monitoring.json` includes:

- `overall_status`: Overall status string (`"PASS"`, `"WARNING"`, or `"FAIL"`).
- `data_as_of`: Point-in-time trading date string (`YYYY-MM-DD`).
- `generated_at`: ISO 8601 UTC timestamp string.
- `checks`: Array of check objects containing `check_name`, `status`, `message`, `details`, and `timestamp`.
- `metrics`: Processing statistics including `processed_symbols`, `processed_ratio`, and stage timing metrics.

---

## 6. Troubleshooting & Testing

To test and verify monitoring logic locally:

```bash
# Run monitoring unit and integration test suite
uv run --frozen pytest scripts/tests/test_monitoring.py

# Run performance subsystem tests
uv run --frozen pytest scripts/tests/test_performance_subsystem.py
```
