# Operational Monitoring, Data Quality & Model Drift

This document specifies the operational monitoring subsystem, data quality checks, baseline qualification, and model/data drift detection in **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Operational Monitoring Architecture (`scripts/monitoring/`)

Operational monitoring provides deterministic, fail-closed quality checks and data/model drift tracking across current and historical report payloads.

- **Inputs**: Current run payloads (`recommendations.json`, `market.json`, `performance.json`), `generated/history/index.json`, and historical report files (`generated/history/YYYY-MM-DD.json`).
- **Output Artifact**: Serialized to `generated/monitoring.json` containing `overall_status` (`PASS`, `WARNING`, `FAIL`), individual `checks` list, `drift_result` object, and execution metadata.

---

## 2. Core Operational Checks (`scripts/monitoring/checks.py`)

Primary quality checks evaluated by `evaluate_production_monitoring()`:

| Check Name                      | Status Conditions           | Description                                                                                                                     |
| :------------------------------ | :-------------------------- | :------------------------------------------------------------------------------------------------------------------------------ |
| `schema_validation`             | `PASS` / `FAIL`             | Validates recommendations payload against `schemas/v2/recommendations.schema.json`. Requires valid, non-empty `schema_version`. |
| `data_freshness`                | `PASS` / `WARNING` / `FAIL` | Confirms `data_as_of` matches reference date or remains within allowed trading delay.                                           |
| `symbol_processing_count`       | `PASS` / `WARNING` / `FAIL` | Assesses percentage of candidate universe successfully processed (`processed_ratio`).                                           |
| `market_regime_validity`        | `PASS` / `FAIL`             | Confirms market regime is one of valid regimes (`STRONG_BULL`, `BULL`, `DEFENSIVE`, `BEAR`, `PANIC`).                           |
| `history_index_integrity`       | `PASS` / `FAIL`             | Verifies `history/index.json` chronological order and record counts.                                                            |
| `numeric_safety`                | `PASS` / `FAIL`             | Scans output payloads recursively for illegal `NaN`, `Inf`, or `-Inf` values.                                                   |
| `performance_payload_integrity` | `PASS` / `FAIL`             | Confirms timing metrics payload conforms to `schemas/v2/performance.schema.json`.                                               |
| `performance_regression`        | `PASS` / `WARNING` / `FAIL` | Evaluates stage execution durations against mode-aware baselines.                                                               |

---

## 3. Data & Model Drift Architecture (`scripts/monitoring/drift.py`)

Tracks changes in candidate recommendation distributions, signal scores, and regime shifts over time relative to historical baselines.

### 3.1 Baseline Qualification & Filtering Rules

1. **Processed Ratio Threshold**: Historical reports must satisfy `processed_ratio >= DRIFT_MIN_PROCESSED_RATIO` (0.80). Sparse runs are excluded.
2. **Reverse Chronological Scan**: Scans up to 20 qualified historical reports strictly prior to execution date ($< T$).
3. **Minimum Baseline Sufficiency**: Requires at least 5 qualified reports. If fewer than 5 exist, monitoring returns `baseline_status = "INSUFFICIENT"` and emits check result `drift_baseline_sufficiency` with `WARNING` status. Baseline insufficiency is distinguished from model drift and does NOT produce false `FAIL` alerts.

### 3.2 Market Regimes & PANIC Regime Drift Exception

Market regime classification evaluates `VNINDEX` trend, breadth, and volatility to output one of 5 regimes: `STRONG_BULL`, `BULL`, `DEFENSIVE`, `BEAR`, `PANIC`.

During `PANIC`, an `AVOID`-heavy recommendation distribution is expected. Drift monitoring (`scripts/monitoring/drift.py`) detects when `market_regime == "PANIC"` and `action_proportions["AVOID"] == 1.0`, classifying the distribution shift as `PASS`. Unjustified 100% AVOID shifts in non-PANIC regimes fail closed (`FAIL`).
