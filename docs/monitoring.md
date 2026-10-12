# Operational Monitoring Architecture & Payloads

This document is the agent-first guide for the operational monitoring subsystem in **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Purpose & System Boundaries

Operational monitoring evaluates pipeline output payloads (`recommendations.json`, `market.json`, `performance.json`) and historical index metadata (`generated/history/index.json`) during Stage 8 (`MonitoringStage`) before persistent artifact publication.

- **System Role**: Quality gatekeeper preventing invalid, stale, corrupt, or degraded reports from reaching production.
- **Fail-Closed Guarantee**: Critical monitoring failures (`FAIL` status) abort pipeline publishing immediately, leaving existing production files in `generated/` 100% byte-for-byte unchanged.

---

## 2. Key Modules & Responsibilities

| Module                                  | Responsibility                                                             | Primary Functions / Dataclasses                                                                                    |
| :-------------------------------------- | :------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------- |
| **`scripts/monitoring/evaluator.py`**   | Main orchestrator evaluating production monitoring.                        | `evaluate_production_monitoring()`                                                                                 |
| **`scripts/monitoring/checks.py`**      | Operational data quality, schema compliance, freshness, and safety checks. | `check_schema_validation()`, `check_data_freshness()`, `check_symbol_processing_count()`, `check_numeric_safety()` |
| **`scripts/monitoring/models.py`**      | Dataclasses for check observations and aggregated results.                 | `CheckResult`, `PipelineMonitoringResult`, `DriftCheckResult`                                                      |
| **`scripts/monitoring/metrics.py`**     | Metric extraction helpers.                                                 | `extract_processed_ratio()`, `compute_action_proportions()`                                                        |
| **`scripts/monitoring/drift.py`**       | Historical data and model output drift checks.                             | `evaluate_data_and_model_drift()`                                                                                  |
| **`scripts/performance/regression.py`** | Mode-aware pipeline stage execution duration checks.                       | `evaluate_performance_regression()`                                                                                |

---

## 3. Monitoring Execution Flow

```text
Pipeline Context Payloads (recommendations, market, performance)
  -> evaluate_production_monitoring() (scripts/monitoring/evaluator.py)
     ├── 1. Operational Checks (scripts/monitoring/checks.py)
     ├── 2. Schema Validation (scripts/schema/registry.py)
     ├── 3. Performance Regression (scripts/performance/regression.py)
     └── 4. Drift Monitoring (scripts/monitoring/drift.py)
  -> PipelineMonitoringResult -> Serialized to generated/monitoring.json
     ├── Status "PASS" or "WARNING" -> Proceed to Stage 9 (ArtifactPublishingStage)
     └── Status "FAIL" -> Abort execution (SystemExit(1)), preserving disk state
```

---

## 4. Input & Output Payload Contracts

### 4.1 Output Payload (`generated/monitoring.json`)

Serialized via `PipelineMonitoringResult.to_dict()`.

```json
{
  "overall_status": "PASS",
  "generated_at": "2026-03-30T11:00:00Z",
  "data_as_of": "2026-03-30",
  "checks": [
    {
      "check_name": "schema_validation",
      "status": "PASS",
      "measured_value": "2.0",
      "expected_condition": "Payload validates against recommendations.schema.json",
      "message": "Recommendations payload matches schema v2.0."
    }
  ],
  "metrics": {
    "processed_symbols": 44,
    "processed_ratio": 1.0
  }
}
```

### 4.2 `CheckResult` Item Contract (`scripts/monitoring/models.py`)

Every check in the `checks` array exposes these 5 required keys:

| Key                  | Type     | Description                                                                                             |
| :------------------- | :------- | :------------------------------------------------------------------------------------------------------ |
| `check_name`         | `string` | Unique identifier of the check (e.g. `"schema_validation"`, `"numeric_safety"`).                        |
| `status`             | `string` | Result status: `"PASS"`, `"WARNING"`, or `"FAIL"`.                                                      |
| `measured_value`     | `any`    | Sanitized measured value or metric (e.g. `"2.0"`, `0.98`, `1.2`). NaN/Inf sanitizes to `"NaN"`/`"Inf"`. |
| `expected_condition` | `string` | Human-readable requirement (e.g. `"processed_ratio >= 0.80"`).                                          |
| `message`            | `string` | Informational or diagnostic result summary.                                                             |

---

## 5. Operational Checks & Failure Semantics

| Check Name                          | Status Mapping              | Evaluation Condition                                                                                                                                    |
| :---------------------------------- | :-------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **`schema_validation`**             | `PASS` / `FAIL`             | Validates payload against `schemas/v2/recommendations.schema.json`. Requires valid, non-empty `schema_version`.                                         |
| **`data_freshness`**                | `PASS` / `WARNING` / `FAIL` | Confirms `data_as_of` trading date matches execution date or remains within allowed staleness limits.                                                   |
| **`symbol_processing_count`**       | `PASS` / `WARNING` / `FAIL` | Assesses `processed_ratio` against universe candidates ($b \ge 0.95 \to \text{PASS}$, $0.80 \le b < 0.95 \to \text{WARN}$, $b < 0.80 \to \text{FAIL}$). |
| **`market_regime_validity`**        | `PASS` / `FAIL`             | Confirms market regime is one of active regimes (`STRONG_BULL`, `BULL`, `DEFENSIVE`, `BEAR`, `PANIC`).                                                  |
| **`history_index_integrity`**       | `PASS` / `FAIL`             | Verifies `generated/history/index.json` chronological descending order and metadata integrity.                                                          |
| **`numeric_safety`**                | `PASS` / `FAIL`             | Recursively scans output payloads for illegal `NaN`, `Inf`, or `-Inf` values using `find_nan_or_inf()`.                                                 |
| **`performance_payload_integrity`** | `PASS` / `FAIL`             | Confirms timing payload conforms to `schemas/v2/performance.schema.json`.                                                                               |
| **`performance_regression`**        | `PASS` / `WARNING` / `FAIL` | Evaluates stage execution durations against mode-aware baselines (static offline vs dynamic `--update` workload counts).                                |

### Overall Status Semantics

- **`PASS`**: All operational checks satisfied. Atomic publication completes code 0.
- **`WARNING`**: Non-critical threshold exceedances (e.g. DEGRADED timing or provider budget overrun). Pipeline logs warnings and publishes artifacts code 0.
- **`FAIL`**: Critical operational or schema failure. Execution halts (`SystemExit(1)`), blocking publishing and preserving disk artifacts untouched.

---

## 6. Commands & Testing

Run monitoring subsystem unit and integration tests:

```bash
# Run monitoring test suite
uv run --frozen pytest scripts/tests/test_monitoring.py

# Run drift monitoring tests
uv run --frozen pytest scripts/tests/test_drift_monitoring.py

# Run performance regression tests
uv run --frozen pytest scripts/tests/test_performance_subsystem.py
```

---

## 7. Agent Change Checklist

When modifying the monitoring subsystem or payload contracts:

- [ ] **Contract Keys**: Ensure `CheckResult.to_dict()` keys (`check_name`, `status`, `measured_value`, `expected_condition`, `message`) remain exact.
- [ ] **Sanitization**: Confirm floating point values use `_sanitize_value_for_json()` to convert `NaN`/`Inf` to strings.
- [ ] **Fail-Closed**: Confirm critical failures return `FAIL` status to block publishing.
- [ ] **Test Coverage**: Run `uv run --frozen pytest scripts/tests/test_monitoring.py` and verify all tests pass.
- [ ] **Documentation Sync**: Update this document if check names, status mappings, or payload fields change.
