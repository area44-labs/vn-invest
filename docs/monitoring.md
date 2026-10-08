# Operational Monitoring, Data Quality & Model Drift

This document specifies the operational monitoring subsystem, data quality checks, baseline qualification, and model/data drift detection architecture in **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Monitoring Subsystem Architecture (`scripts/monitoring/`)

Operational monitoring is housed natively in `scripts/monitoring/`. It provides deterministic, fail-closed quality checks and data/model drift tracking.

```text
scripts/monitoring/
├── models.py       # CheckResult, PipelineMonitoringResult, DriftObservation, DriftCheckResult
├── metrics.py      # Quantitative metric extraction helpers
├── checks.py       # Operational data quality and schema compliance checks
├── drift.py        # Data and model drift evaluation against historical baseline lookbacks
├── evaluator.py    # Main monitoring evaluator (evaluate_production_monitoring)
├── performance.py  # Performance schema and payload verification
└── __init__.py     # Re-exports public monitoring interfaces
```

---

## 2. Inputs & Outputs

### 2.1 Inputs

- **Current Pipeline Payloads**: `recommendations.json`, `market.json`, `performance.json`.
- **Historical Report Index**: `generated/history/index.json`.
- **Historical Report Artifacts**: `generated/history/YYYY-MM-DD.json` (for drift evaluation).
- **Execution Metadata**: `data_as_of`, `generated_at`, `reference_date`.

### 2.2 Output Artifact

- Output Model: `PipelineMonitoringResult` serialized to `generated/monitoring.json`.
- Output Structure: Contains `overall_status` (`PASS`, `WARNING`, `FAIL`), individual `checks` list, `drift_result` object, and execution metadata.

---

## 3. Operational Quality Checks (`scripts/monitoring/checks.py`)

Primary operational checks evaluated by `evaluate_production_monitoring()`:

| Check Name                      | Status Conditions           | Description                                                                                                                                                                                   |
| :------------------------------ | :-------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `schema_validation`             | `PASS` / `FAIL`             | Validates recommendations payload against `schemas/v2/recommendations.schema.json`. Requires valid, non-empty `schema_version`.                                                               |
| `data_freshness`                | `PASS` / `WARNING` / `FAIL` | Verifies `data_as_of` matches execution reference date or is within allowed trading delay.                                                                                                    |
| `symbol_processing_count`       | `PASS` / `WARNING` / `FAIL` | Assesses percentage of candidate universe successfully processed (`processed_ratio`).                                                                                                         |
| `market_regime_validity`        | `PASS` / `FAIL`             | Confirms market regime is valid (`BULLISH`, `BEARISH`, `SIDEWAYS`, `NEUTRAL`).                                                                                                                |
| `history_index_integrity`       | `PASS` / `FAIL`             | Verifies `history/index.json` structure, chronological order, and record count.                                                                                                               |
| `numeric_safety`                | `PASS` / `FAIL`             | Recursively scans output payload for illegal `NaN`, `Inf`, or `-Inf` values.                                                                                                                  |
| `performance_payload_integrity` | `PASS` / `FAIL`             | Confirms performance timing payload conforms to `schemas/v2/performance.schema.json`.                                                                                                         |
| `performance_regression`        | `PASS` / `WARNING` / `FAIL` | Evaluates stage execution durations against centralized mode-aware baselines (`PERFORMANCE_STAGE_BASELINES` for test/offline, `PRODUCTION_UPDATE_PERFORMANCE_BASELINES` for live `--update`). |

---

## 4. Data & Model Drift Architecture (`scripts/monitoring/drift.py`)

Drift monitoring tracks changes in candidate recommendation distributions, signal scores, confidence levels, and market regime shifts over time relative to historical baselines.

### 4.1 Baseline Qualification & Filtering Rules

Function: `evaluate_data_and_model_drift()`.

To prevent corrupted or partial historical runs from polluting drift calculations, baseline reports are strictly filtered:

1. **Coverage Threshold**: Historical candidate reports must satisfy `processed_ratio >= DRIFT_MIN_PROCESSED_RATIO` (where `DRIFT_MIN_PROCESSED_RATIO = 0.80`). Reports with `processed_ratio < 0.80` are excluded from baseline sets.
2. **Temporal Order**: Historical reports are scanned in strict reverse chronological order strictly prior to the current execution date ($< T$).
3. **Lookback Window**: Scans up to `lookback_reports` (default 20) qualified historical reports.
4. **Canonical Metadata Validation**: Each baseline artifact enforces canonical `data_as_of` string formatting, non-finite float safety, and chronological descending order.

### 4.2 Baseline Insufficiency vs. Quantitative Drift

- **Minimum Qualified Reports**: Requires at least `min_baseline_reports` (default 5) qualified historical reports.
- **Handling Insufficient Baselines**: If fewer than 5 qualified reports exist (e.g. during fresh initial deployment or sparse history):
  - Monitoring returns `baseline_status = "INSUFFICIENT"`.
  - Emits check result `drift_baseline_sufficiency` with `WARNING` status.
  - Returns `overall_status = "WARNING"` (or `PASS` depending on critical operational checks).
  - **Invariant**: Baseline data insufficiency is strictly distinguished from genuine quantitative model drift. Insufficient baseline history does NOT produce a `FAIL` status or trigger false model drift alerts.

### 4.3 Regime-Driven Action Shift vs. Model Drift

- **Extreme Market Regime (PANIC)**: When market regime is detected as `PANIC`, the signal engine (`scripts/quant/signal.py`) enforces action `AVOID` across all candidate stock recommendations.
- **Drift Evaluation Handling**: When `market_regime == "PANIC"` and `action_proportions["AVOID"] == 1.0`, `drift_action_distribution` classifies the shift as a valid, expected regime-driven outcome (`PASS`) with an explicit diagnostic message.
- **Fail-Closed Guarantee**: Action distribution shifts that occur without a valid `PANIC` regime explanation continue to fail closed (`FAIL`) if they exceed configured thresholds (`DRIFT_THRESHOLD_ACTION_DISTRIBUTION`).

---

## 5. Performance Regression & Production Update Baselines (`scripts/performance/regression.py`)

Performance regression monitoring separates baselines and thresholds for live `--update` mode from offline/test environments:

- **Offline / Test Mode (`PERFORMANCE_STAGE_BASELINES`)**: Assumes fast cached or local execution (e.g. `pipeline` baseline 10.0s, `stock_fetch` baseline 5.0s, `benchmark_fetch` baseline 1.0s).
- **Live Production Update Mode (`PRODUCTION_UPDATE_PERFORMANCE_BASELINES`)**: Accounts for mandatory request pacing (`DEFAULT_UPDATE_THROTTLE_DELAY = 3.5s` per call) across benchmark symbols (2) and candidate stocks (44):
  - `stock_fetch` baseline: 185.0s (Failed threshold: 300.0s)
  - `benchmark_fetch` baseline: 10.0s (Failed threshold: 30.0s)
  - `pipeline` total baseline: 200.0s (Failed threshold: 320.0s)
- **Auto-Detection**: Automatically detects live throttled update runs when stage/provider duration exceeds 30 seconds or when `update_data=True` is passed from pipeline stages.

---

## 6. Fail-Closed Invariants

1. **Unreadable Baseline Handling**: Missing, unreadable, or malformed history index or baseline JSON files result in an immediate `FAIL` status for history/drift checks.
2. **Strict Schema Loading**: `schema_validation` routes strictly through `scripts/schema/registry.py`. Missing or empty `schema_version` fields in input payloads produce `FAIL` check statuses without fallbacks.
