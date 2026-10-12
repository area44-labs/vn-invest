# Operational Monitoring Architecture & Payloads

This document is the agent-first guide for the operational monitoring subsystem in **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Purpose & System Boundaries

Operational monitoring evaluates pipeline output payloads (`recommendations.json`, `market.json`, `performance.json`) and historical index metadata (`generated/history/index.json`) during Stage 8 (`MonitoringStage`) before persistent artifact publication.

- **System Role**: Quality gatekeeper preventing invalid, stale, corrupt, or degraded reports from reaching production.
- **Fail-Closed Guarantee**: In `ArtifactPublishingStage`, when `context.publish_artifacts is True` and `context.monitoring_result.overall_status == "FAIL"`, the pipeline logs all failed checks and raises `SystemExit(1)`, preserving existing production files in `generated/` 100% byte-for-byte unchanged.

---

## 2. Key Modules & Responsibilities

| Module                                  | Responsibility                                                             | Primary Functions / Dataclasses                                                                                                                                                                                                                                                      |
| :-------------------------------------- | :------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`scripts/monitoring/evaluator.py`**   | Main orchestrator evaluating production monitoring.                        | `evaluate_production_monitoring()`                                                                                                                                                                                                                                                   |
| **`scripts/monitoring/checks.py`**      | Operational data quality, schema compliance, freshness, and safety checks. | `check_required_artifacts()`, `check_schema_validation()`, `check_data_freshness()`, `check_numeric_sanity()`, `check_symbol_processing_counts()`, `check_universe_audit_invariants()`, `check_market_regime_status()`, `check_history_index_status()`, `check_ohlcv_data_quality()` |
| **`scripts/monitoring/models.py`**      | Dataclasses for check observations and aggregated results.                 | `CheckResult`, `PipelineMonitoringResult`, `DriftCheckResult`                                                                                                                                                                                                                        |
| **`scripts/monitoring/metrics.py`**     | Metric extraction helpers.                                                 | `extract_processed_ratio()`, `compute_action_proportions()`                                                                                                                                                                                                                          |
| **`scripts/monitoring/drift.py`**       | Historical data and model output drift checks.                             | `evaluate_data_and_model_drift()`                                                                                                                                                                                                                                                    |
| **`scripts/performance/regression.py`** | Mode-aware pipeline stage execution duration and provider budget checks.   | `evaluate_performance_regression()`, `evaluate_provider_budget()`                                                                                                                                                                                                                    |

---

## 3. Monitoring Execution Flow

```text
Pipeline Context Payloads (recommendations, market, performance)
  -> evaluate_production_monitoring() (scripts/monitoring/evaluator.py)
     ├── 1. Required Artifacts Check (check_required_artifacts)
     ├── 2. Schema Validation (check_schema_validation)
     ├── 3. Data Freshness Check (check_data_freshness)
     ├── 4. Numeric Sanity Check (check_numeric_sanity)
     ├── 5. Symbol Processing Counts Check (check_symbol_processing_counts)
     ├── 6. Universe Audit Invariants Check (check_universe_audit_invariants)
     ├── 7. Market Regime Status Check (check_market_regime_status)
     ├── 8. History Index Status Check (check_history_index_status)
     ├── 9. Conditional Benchmark Quality Checks (check_ohlcv_data_quality, if df_vnindex/df_vn30 provided)
     ├── 10. Drift Monitoring Checks (evaluate_data_and_model_drift)
     └── 11. Performance & Provider Budget Checks (performance_payload_integrity, performance_regression, provider_budget)
  -> PipelineMonitoringResult -> Serialized to generated/monitoring.json
     ├── Status "PASS" or "WARNING" -> Proceed to Stage 9 (ArtifactPublishingStage)
     └── Status "FAIL" -> If publish_artifacts is True, raises SystemExit(1) and preserves on-disk state
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

| Key                  | Type     | Description                                                                                        |
| :------------------- | :------- | :------------------------------------------------------------------------------------------------- |
| `check_name`         | `string` | Unique emitted identifier of the check (e.g. `"schema_validation"`, `"symbol_processing_counts"`). |
| `status`             | `string` | Result status: `"PASS"`, `"WARNING"`, or `"FAIL"`.                                                 |
| `measured_value`     | `any`    | Sanitized measured value or metric object. NaN/Inf sanitizes to `"NaN"`/`"Inf"`.                   |
| `expected_condition` | `string` | Human-readable requirement (e.g. `"processed_ratio >= 0.80"`).                                     |
| `message`            | `string` | Informational or diagnostic result summary.                                                        |

---

## 5. Canonical Operational Checks Inventory

Emitted check names and status evaluation rules in `scripts/monitoring/checks.py` & `evaluator.py`:

| Check Name                               | Status Mapping              | Evaluation Condition                                                                                                                                                                 |
| :--------------------------------------- | :-------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`artifact_existence`**                 | `PASS` / `FAIL`             | Confirms required JSON payload artifacts exist in memory or on disk in `generated/`.                                                                                                 |
| **`schema_validation`**                  | `PASS` / `FAIL`             | Validates recommendations payload against `schemas/v2/recommendations.schema.json`.                                                                                                  |
| **`data_freshness`**                     | `PASS` / `WARNING` / `FAIL` | Confirms `data_as_of` trading date matches execution reference date or stays within allowed trading delay.                                                                           |
| **`numeric_sanity`**                     | `PASS` / `FAIL`             | Recursively scans payloads for illegal `NaN`, `Inf`, or `-Inf` values using `find_nan_or_inf()`.                                                                                     |
| **`symbol_processing_counts`**           | `PASS` / `WARNING` / `FAIL` | Evaluates processed coverage ratio $r$:<br>• `PASS`: $r \ge 0.80$<br>• `WARNING`: $0.50 \le r < 0.80$<br>• `FAIL`: $r < 0.50$ (or action count summary mismatch, total scanned = 0). |
| **`universe_audit_invariants`**          | `PASS` / `FAIL`             | Verifies universe audit classification sets (processed, invalid, missing, failed) are mutually disjoint and cover candidate universe.                                                |
| **`market_regime_status`**               | `PASS` / `FAIL`             | Confirms market regime payload is a valid object containing a recognized regime string (`STRONG_BULL`, `BULL`, `DEFENSIVE`, `BEAR`, `PANIC`).                                        |
| **`history_index_status`**               | `PASS` / `FAIL`             | Verifies `generated/history/index.json` chronological descending order and metadata structure.                                                                                       |
| **`ohlcv_data_quality`** _(conditional)_ | `PASS` / `FAIL`             | Evaluated conditionally when benchmark DataFrames (`df_vnindex`, `df_vn30`) are provided. Checks column presence, positive prices, and non-negative volumes.                         |
| **`performance_payload_integrity`**      | `PASS` / `FAIL`             | Validates performance timing payload against `schemas/v2/performance.schema.json`.                                                                                                   |
| **`performance_regression`**             | `PASS` / `WARNING` / `FAIL` | Evaluates stage execution durations against mode-aware baselines (static offline vs dynamic `--update` request workload counts).                                                     |
| **`provider_budget`**                    | `PASS` / `WARNING` / `FAIL` | Evaluates provider API operation calls, duplicate symbol fetches, and elapsed execution time budgets.                                                                                |

---

## 6. Status Semantics & Publication Guards

In Stage 9 (`ArtifactPublishingStage`), the pipeline evaluates publication safety:

- **`PASS`**: All operational checks satisfied. Atomic directory publishing completes with code 0.
- **`WARNING`**: Non-critical threshold exceedance (e.g. $0.50 \le \text{processed\_ratio} < 0.80$, DEGRADED timing, or provider budget overrun). Pipeline logs warnings and publishes artifacts with code 0.
- **`FAIL`**: Critical operational or schema failure (e.g. $\text{processed\_ratio} < 0.50$, schema mismatch, non-finite float value, or missing required artifact). When `context.publish_artifacts` is `True`, the stage logs all failed checks and raises `SystemExit(1)`, halting execution and leaving existing files in `generated/` 100% byte-for-byte unchanged.

---

## 7. Commands & Testing

Run monitoring subsystem unit and integration tests:

```bash
# Run monitoring test suite
uv run --frozen pytest scripts/tests/test_monitoring.py

# Run drift monitoring tests
uv run --frozen pytest scripts/tests/test_drift_monitoring.py

# Run performance subsystem tests
uv run --frozen pytest scripts/tests/test_performance_subsystem.py
```

---

## 8. Agent Change Checklist

When modifying the monitoring subsystem or payload contracts:

- [ ] **Exact Check Names**: Use canonical emitted check names (`symbol_processing_counts`, `market_regime_status`, `history_index_status`, `artifact_existence`, `numeric_sanity`, etc.).
- [ ] **Contract Keys**: Ensure `CheckResult.to_dict()` keys (`check_name`, `status`, `measured_value`, `expected_condition`, `message`) remain exact.
- [ ] **Exact Thresholds**: Ensure `symbol_processing_counts` maps $\ge 0.80 \to \text{PASS}$, $0.50 - 0.80 \to \text{WARNING}$, and $< 0.50 \to \text{FAIL}$.
- [ ] **Sanitization**: Confirm floating point values use `_sanitize_value_for_json()` to convert `NaN`/`Inf` to strings.
- [ ] **Fail-Closed**: Confirm critical failures return `FAIL` status and trigger publication rejection when `publish_artifacts` is `True`.
- [ ] **Test Coverage**: Run `uv run --frozen pytest scripts/tests/test_monitoring.py` and verify all tests pass.
