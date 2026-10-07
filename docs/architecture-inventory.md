# Repository Architecture Baseline Inventory & Freeze (M0)

**Issue**: #222 — M0: Baseline Audit & Freeze
**Author**: Jules
**Date**: March 2025
**Scope**: `scripts/` directory, production entry points, test mappings, generated artifacts, and compatibility layers.

---

## 1. Executive Summary & Audit Overview

This document establishes the official **Baseline Architecture Inventory and Codebase Freeze (Milestone M0)** for the repository prior to beginning the M1–M5 structural cleanup and refactoring phases.

### Primary Objectives

1. **Freeze and Document**: Capture the exact architecture state, module boundaries, entry points, and dependency references across `scripts/`.
2. **Strict Zero-Mutation Guarantee**: Perform M0 without deleting, renaming, migrating, or modifying any production code, test behavior, or CI workflow.
3. **Evidence-Based Classification**: Categorize every component into 6 distinct groups (`CANONICAL`, `LEGACY`, `REMOVE`, `KEEP`, `MIGRATE`, `UNKNOWN`) based strictly on actual code references and invocation paths.

---

## 2. Production Entry Points

| Entry Point Path                     | Executable Mode / Trigger                         | Canonical Responsibilities                                                                                                                                        | Invoked Subsystems / Stages                                                                                            |
| :----------------------------------- | :------------------------------------------------ | :---------------------------------------------------------------------------------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------- |
| `scripts/generate_report.py`         | CLI / GitHub Actions (`daily-update.yml`, manual) | Main production report generation CLI entry point (`run_pipeline`, `generate_historical_report`). Orchestrates full pipeline run or historical report generation. | `scripts.pipeline.runner.PipelineRunner`, `scripts.pipeline.stages.*`, `scripts.artifacts.publisher.ArtifactPublisher` |
| `.github/workflows/daily-update.yml` | GitHub Actions Workflow                           | Automated daily production data update and report generation workflow.                                                                                            | Executes `scripts/generate_report.py --update-data` via `uv run`.                                                      |
| `.github/workflows/pages.yml`        | GitHub Actions Workflow                           | Static site generator (SSG) deployment to GitHub Pages.                                                                                                           | Executes `vp build` (Vite+) to generate static web interface from published artifacts.                                 |

---

## 3. Primary Classification Groups

All components in `scripts/` are categorized into one of six explicit classification groups:

1. **CANONICAL**: Active, authoritative, single-source-of-truth production modules adhering to current architectural standards.
2. **LEGACY**: Functional modules or legacy entry points that are still actively called or re-exported, but slated for replacement or refactoring.
3. **REMOVE**: Unused or dead code, obsolete wrapper modules, or redundant re-export shims with 0 production callers that can be safely deleted once tests are updated.
4. **KEEP**: Production-essential utilities, domain models, or standalone engines that must be preserved and maintained in their current functional form.
5. **MIGRATE**: Active modules or callers that require code refactoring, import re-routing, or relocation to canonical packages during M1–M5.
6. **UNKNOWN**: Components without sufficient usage evidence or whose architectural purpose requires explicit product/architectural decision before cleanup.

---

## 4. `scripts/lib/*` Deep-Dive & Trace Mapping

Every module under `scripts/lib/` has been systematically audited. Classification is determined strictly by tracing production callers, test usage, and canonical replacements.

### Trace Flow Format

`Legacy Module` → `Production Callers` → `Canonical Replacement` → `Migration Required?` → `Safe to Remove?`

---

### Detailed `scripts/lib/*` Inventory

#### 1. `scripts/lib/config.py`

- **Current Role**: Configuration constants adapter re-exporting constants (`SIGNAL_MODEL_VERSION`, `QUANT_VERSION`, `PIPELINE_VERSION`, `VALID_MARKET_REGIMES`, `PROVIDER_BUDGET`, `PERFORMANCE_STAGE_BASELINES`, `FAILURE_CATEGORIES`, etc.) and delegating quantitative configuration directly to `scripts.quant.config.DEFAULT_QUANT_CONFIG`.
- **Production Callers**:
  - `scripts/artifacts/provenance.py` (`QUANT_VERSION`, `SIGNAL_MODEL_VERSION`)
  - `scripts/generate_report.py` (`DEFAULT_UPDATE_THROTTLE_DELAY`, `is_recoverable_category`)
  - `scripts/monitoring/checks.py` (`VALID_MARKET_REGIMES`)
  - `scripts/monitoring/drift.py` (`DRIFT_MIN_PROCESSED_RATIO`, etc.)
  - `scripts/monitoring/evaluator.py` (`SIGNAL_MODEL_VERSION`)
  - `scripts/monitoring/models.py` (`VALID_MARKET_REGIMES`, `DRIFT_MAX_MISSING_PERCENT`, etc.)
  - `scripts/monitoring/__init__.py` (re-exports)
  - `scripts/performance/budget.py` (`PROVIDER_BUDGET`)
  - `scripts/performance/regression.py` (`PERFORMANCE_STAGE_BASELINES`)
  - `scripts/pipeline/context.py` (`QUANT_VERSION`, `SIGNAL_MODEL_VERSION`, `is_recoverable_category`)
  - `scripts/pipeline/stages.py` (`DEFAULT_UPDATE_THROTTLE_DELAY`)
  - `scripts/pipeline/constants.py`
  - `scripts/vietnam_market.py`
- **Test Callers**: `test_audit_observability.py`, `test_config.py`, `test_data_provider.py`, `test_monitoring.py`, `test_pipeline_performance.py`, `test_provenance.py`, `test_quant_config.py`.
- **Canonical Replacement**: `scripts/quant/config.py` (quantitative config), `scripts/pipeline/constants.py` (pipeline versions/constants), `scripts/monitoring/models.py` (monitoring constants).
- **Classification**: `MIGRATE`
- **Rationale**: Heavily referenced across production stages, monitoring, and pipeline context. Constants must be migrated to their canonical homes (`scripts/pipeline/constants.py`, `scripts/quant/config.py`, `scripts/monitoring/models.py`) before removing this adapter file.
- **Trace**: `scripts/lib/config.py` → 12 production callers + `monitoring/__init__.py` → `scripts/quant/config.py` & `scripts/pipeline/constants.py` → Migration required in M1 → Safe to remove in M1/M2 after callers updated.
- **Target Phase**: M1 / M2

---

#### 2. `scripts/lib/features.py`

- **Current Role**: Legacy technical indicator calculations (RSI, MACD, Bollinger Bands, Moving Averages).
- **Production Callers**: **None** (0 production callers).
- **Test Callers**: `scripts/tests/test_recommendation.py` (imports `calculate_single_tf_indicators`, `detect_divergence`).
- **Canonical Replacement**: `scripts/quant/features.py`
- **Classification**: `REMOVE`
- **Rationale**: Completely unreferenced in production code. Production pipeline uses native `scripts.quant.features`. Updating test imports in `test_recommendation.py` enables immediate safe removal.
- **Trace**: `scripts/lib/features.py` → 0 production callers → `scripts/quant/features.py` → Migration required: update `test_recommendation.py` imports → Safe to remove in M1.
- **Target Phase**: M1

---

#### 3. `scripts/lib/recommendation.py`

- **Current Role**: Thin re-export adapter delegating `generate_recommendation`, `calculate_confidence`, `VALID_MARKET_REGIMES`, etc., to `scripts.quant.recommendation` and `scripts.quant.signal`.
- **Production Callers**:
  - `scripts/generate_report.py` (`SIGNAL_MODEL_VERSION`, `generate_recommendation`)
  - `scripts/lib/risk.py` (`VALID_MARKET_REGIMES`, `calculate_risk_adjusted_score`)
- **Test Callers**: 11 test modules (`test_backtest.py`, `test_config.py`, `test_data_boundary.py`, `test_data_date.py`, `test_data_quality.py`, `test_downstream_data_validation.py`, `test_engines.py`, `test_monitoring.py`, `test_performance_subsystem.py`, `test_recommendation.py`, `test_unit_normalization.py`).
- **Canonical Replacement**: `scripts/quant/recommendation.py`, `scripts/quant/contracts.py`, `scripts/quant/signal.py`.
- **Classification**: `MIGRATE`
- **Rationale**: Production pipeline stages already consume `scripts.quant.*` directly. Only `generate_report.py` and `scripts/lib/risk.py` still import from this legacy adapter. Re-routing callers and tests will allow total removal.
- **Trace**: `scripts/lib/recommendation.py` → `generate_report.py`, `scripts/lib/risk.py` → `scripts/quant/recommendation.py` → Migration required: re-route callers to `scripts.quant.recommendation` → Safe to remove in M1.
- **Target Phase**: M1

---

#### 4. `scripts/lib/regime.py`

- **Current Role**: Legacy wrapper re-exporting `detect_market_regime` from `scripts.quant.regime`.
- **Production Callers**:
  - `scripts/generate_report.py` (`detect_market_regime`)
  - `scripts/lib/backtest.py` (`lib_detect_market_regime as detect_market_regime`)
  - `scripts/lib/portfolio_backtest.py` (`lib_detect_market_regime as detect_market_regime`)
- **Test Callers**: 8 test modules (`test_backtest.py`, `test_config.py`, `test_data_boundary.py`, `test_data_quality.py`, `test_downstream_data_validation.py`, `test_monitoring.py`, `test_recommendation.py`, `test_regime.py`).
- **Canonical Replacement**: `scripts/quant/regime.py`
- **Classification**: `MIGRATE`
- **Rationale**: Thin delegation layer over `scripts.quant.regime`. Updating `generate_report.py`, `backtest.py`, and `portfolio_backtest.py` allows deletion of this wrapper.
- **Trace**: `scripts/lib/regime.py` → `generate_report.py`, `backtest.py`, `portfolio_backtest.py` → `scripts/quant/regime.py` → Migration required: re-route imports to `scripts.quant.regime` → Safe to remove in M1.
- **Target Phase**: M1

---

#### 5. `scripts/lib/risk.py`

- **Current Role**: Universe liquidity normalization (`normalize_universe_liquidity_scores`), T+2.5 risk metrics, stop-loss/take-profit calculations, delegating quantitative risk to `scripts.quant.risk`.
- **Production Callers**:
  - `scripts/generate_report.py` (`normalize_universe_liquidity_scores`)
- **Test Callers**: `test_downstream_data_validation.py`, `test_output_integrity.py`, `test_recommendation.py`, `test_risk.py`, `test_unit_normalization.py`.
- **Canonical Replacement**: `scripts/quant/risk.py`
- **Classification**: `MIGRATE`
- **Rationale**: `normalize_universe_liquidity_scores` and T+2.5 return helpers belong natively in `scripts/quant/risk.py`. Once moved to `scripts.quant.risk.py` and caller in `generate_report.py` is updated, this module can be removed.
- **Trace**: `scripts/lib/risk.py` → `generate_report.py` → `scripts/quant/risk.py` → Migration required: relocate liquidity normalization functions to `scripts/quant/risk.py` and update callers → Safe to remove in M1.
- **Target Phase**: M1

---

#### 6. `scripts/lib/vietnam_market.py`

- **Current Role**: Monolithic legacy market data fetching (`get_historical_data`), OHLCV validation (`validate_ohlcv_data`, `get_clean_ohlcv_data`), universe definitions (`UniverseProvider`, `CANDIDATE_STOCKS`), exchange price limits, and throttling.
- **Production Callers**:
  - `scripts/generate_report.py` (`get_historical_data`, `validate_ohlcv_data`, `UniverseProvider`, `get_exchange_price_limits`, `DEFAULT_UPDATE_THROTTLE_DELAY`)
  - `scripts/lib/backtest.py` (`get_clean_ohlcv_data`, `validate_ohlcv_data`)
  - `scripts/lib/portfolio_backtest.py` (`get_clean_ohlcv_data`)
  - `scripts/monitoring/checks.py` (`validate_ohlcv_data`)
  - `scripts/pipeline/context.py` (`UniverseProvider`)
  - `scripts/pipeline/runner.py` (`UniverseProvider`)
  - `scripts/pipeline/stages.py` (`get_historical_data`, `validate_ohlcv_data`, `UniverseProvider`, etc.)
  - `scripts/quant/recommendation.py` (`validate_ohlcv_data`)
  - `scripts/quant/risk.py` (`get_clean_ohlcv_data`, `get_exchange_price_limits`)
  - `scripts/quant/signal.py` (`get_clean_ohlcv_data`, `validate_ohlcv_data`)
- **Test Callers**: 12 test modules (`test_data_boundary.py`, `test_data_date.py`, `test_data_provider.py`, `test_data_quality.py`, `test_domain.py`, `test_recommendation.py`, `test_risk.py`, `test_unit_normalization.py`, etc.).
- **Canonical Replacement**: `scripts/data/*` (`MarketDataAcquirer`, `CanonicalMarketValidator`, `VnstockMarketProvider`), `scripts/domain/universe.py` (`Universe`, `UniverseCandidate`), `scripts/quant/*`.
- **Classification**: `MIGRATE`
- **Rationale**: Central legacy monolith file. Market data fetching logic must be fully migrated to `scripts/data/*` and universe provider logic to `scripts/domain/universe.py` or `scripts/pipeline/`.
- **Trace**: `scripts/lib/vietnam_market.py` → `generate_report.py`, `pipeline/*`, `quant/*`, `monitoring/*` → `scripts/data/*` and `scripts/domain/*` → Migration required in M2/M3 → Safe to remove in M3.
- **Target Phase**: M2 / M3

---

#### 7. `scripts/lib/monitoring.py`

- **Current Role**: Re-export adapter wrapper re-exporting all operational monitoring functions, dataclasses, and thresholds from `scripts.monitoring`.
- **Production Callers**: **None** (0 production callers).
- **Test Callers**: `test_audit_observability.py`, `test_drift_monitoring.py`, `test_monitoring.py`, `test_monitoring_subsystem.py`, `test_pipeline_monitoring_status.py`, `test_pipeline_performance.py`.
- **Canonical Replacement**: `scripts/monitoring/*` (`scripts/monitoring/drift.py`, `scripts/monitoring/checks.py`, `scripts/monitoring/evaluator.py`, `scripts/monitoring/models.py`).
- **Classification**: `REMOVE`
- **Rationale**: Has 0 production callers. Exists purely as a legacy re-export shim. Updating test imports to import directly from `scripts.monitoring.*` will allow complete removal in M1.
- **Trace**: `scripts/lib/monitoring.py` → 0 production callers → `scripts/monitoring/*` → Migration required: re-route test imports → Safe to remove in M1.
- **Target Phase**: M1

---

#### 8. `scripts/lib/backtest.py`

- **Current Role**: Point-in-Time (PIT) backtesting engine, forward outcome evaluation, execution eligibility, walk-forward dates, execution return calculation.
- **Production Callers**:
  - `scripts/generate_report.py` (`_parse_canonical_date`)
  - `scripts/pipeline/stages.py` (`_parse_canonical_date`, `get_as_of_dataset`)
  - `scripts/pipeline/validation.py` (`_parse_canonical_date`)
  - `scripts/lib/portfolio_backtest.py` (`get_as_of_dataset`, `evaluate_forward_outcomes`, `evaluate_execution_eligibility`, `_parse_canonical_date`, `calculate_execution_return`)
- **Test Callers**: `test_backtest.py`, `test_e2e_backtest_integrity.py`, `test_engines.py`, `test_execution_costs.py`, `test_portfolio_backtest.py`, `test_recommendation.py`, `test_risk.py`.
- **Canonical Replacement**: Move to dedicated package `scripts/backtest/engine.py` or `scripts/quant/backtest.py`.
- **Classification**: `KEEP` / `MIGRATE`
- **Rationale**: Highly essential, fully tested quantitative backtesting engine. Core calculation engine MUST BE KEPT, but module path should be relocated out of `scripts/lib/` to a canonical backtest package. Date parsing `_parse_canonical_date` should be moved to a shared utility module.
- **Trace**: `scripts/lib/backtest.py` → `portfolio_backtest.py`, `pipeline/stages.py`, `pipeline/validation.py`, `generate_report.py` → Relocate to canonical backtest module → Migration required in M3 → Safe to remove legacy path after relocation.
- **Target Phase**: M3 / M4

---

#### 9. `scripts/lib/portfolio_backtest.py`

- **Current Role**: Multi-stock portfolio backtesting, capital allocation, position sizing, cost awareness, portfolio aggregation.
- **Production Callers**: **None** (0 production callers - used strictly for offline backtesting and evaluation test suites).
- **Test Callers**: `test_e2e_backtest_integrity.py`, `test_engines.py`, `test_execution_costs.py`, `test_portfolio_backtest.py`, `test_quant_config.py`, `test_recommendation.py`.
- **Canonical Replacement**: Move to dedicated package `scripts/backtest/portfolio.py` or `scripts/quant/portfolio_backtest.py`.
- **Classification**: `KEEP` / `MIGRATE`
- **Rationale**: Essential, deterministic portfolio backtest engine. Functions and dataclasses are fully verified and must be preserved, but relocated out of `scripts/lib/` to a dedicated backtest package.
- **Trace**: `scripts/lib/portfolio_backtest.py` → 0 production callers (used in test suite) → Relocate to `scripts/backtest/portfolio.py` → Migration required in M3 → Safe to remove legacy path after relocation.
- **Target Phase**: M3 / M4

---

## 5. Comprehensive Subsystem Inventory

### 5.1 `scripts/artifacts/` (Artifact Publishing Subsystem)

| File                               | Current Role                                                                         | Production Callers                                             | Test Callers                                                 | Classification | Target Phase |
| :--------------------------------- | :----------------------------------------------------------------------------------- | :------------------------------------------------------------- | :----------------------------------------------------------- | :------------- | :----------- |
| `scripts/artifacts/__init__.py`    | Package re-exports for publisher, manifest, provenance, transaction, recovery.       | `scripts/pipeline/publishing.py`, `scripts/pipeline/stages.py` | `test_artifact_publisher.py`, `test_provenance.py`           | `CANONICAL`    | -            |
| `scripts/artifacts/manifest.py`    | Artifact manifest generation & schema validation (`ArtifactManifest`).               | `scripts/artifacts/publisher.py`                               | `test_artifact_publisher.py`                                 | `CANONICAL`    | -            |
| `scripts/artifacts/provenance.py`  | Provenance manifest creation & schema validation (`ProvenanceManifest`).             | `scripts/artifacts/publisher.py`                               | `test_provenance.py`                                         | `CANONICAL`    | -            |
| `scripts/artifacts/publisher.py`   | Core publishing engine (`ArtifactPublisher`), date integrity, schema checks.         | `scripts/pipeline/stages.py`                                   | `test_artifact_publisher.py`, `test_schema.py`               | `CANONICAL`    | -            |
| `scripts/artifacts/recovery.py`    | Transaction recovery & journal inspection (`recover_interrupted_publish`).           | `scripts/artifacts/publisher.py`                               | `test_artifact_publisher.py`, `test_artifact_transaction.py` | `CANONICAL`    | -            |
| `scripts/artifacts/transaction.py` | Atomic POSIX directory lock & atomic publishing transaction (`ArtifactTransaction`). | `scripts/artifacts/publisher.py`                               | `test_artifact_transaction.py`                               | `CANONICAL`    | -            |

---

### 5.2 `scripts/data/` (Market Data Subsystem)

| File                                 | Current Role                                                                 | Production Callers                                                                                                          | Test Callers                                                                   | Classification | Target Phase |
| :----------------------------------- | :--------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------- | :----------------------------------------------------------------------------- | :------------- | :----------- |
| `scripts/data/__init__.py`           | Data package re-exports.                                                     | Internal data submodules                                                                                                    | `test_data_models.py`                                                          | `CANONICAL`    | -            |
| `scripts/data/models.py`             | Canonical data model (`CanonicalMarketData`), record-based view, `to_df()`.  | `scripts/data/acquisition.py`, `scripts/data/normalization.py`, `scripts/data/validation.py`, `scripts/pipeline/context.py` | `test_data_models.py`, `test_data_normalization.py`, `test_data_validation.py` | `CANONICAL`    | -            |
| `scripts/data/acquisition.py`        | Market data acquisition orchestration (`MarketDataAcquirer`), error tags.    | `scripts/pipeline/stages.py`                                                                                                | `test_data_acquisition.py`, `test_data_boundary.py`                            | `CANONICAL`    | -            |
| `scripts/data/normalization.py`      | Raw payload normalization (`MarketDataNormalizer`).                          | `scripts/data/acquisition.py`                                                                                               | `test_data_normalization.py`                                                   | `CANONICAL`    | -            |
| `scripts/data/validation.py`         | Canonical market data validator (`CanonicalMarketValidator`).                | `scripts/pipeline/stages.py`                                                                                                | `test_data_validation.py`                                                      | `CANONICAL`    | -            |
| `scripts/data/providers/__init__.py` | Market provider package re-exports.                                          | `scripts/data/acquisition.py`                                                                                               | `test_data_provider_boundary.py`                                               | `CANONICAL`    | -            |
| `scripts/data/providers/base.py`     | Base provider abstract class (`MarketDataProvider`) and exception hierarchy. | `scripts/data/providers/vnstock.py`                                                                                         | `test_data_provider_boundary.py`                                               | `CANONICAL`    | -            |
| `scripts/data/providers/vnstock.py`  | Vnstock concrete market provider implementation (`VnstockMarketProvider`).   | `scripts/data/acquisition.py`                                                                                               | `test_data_provider_boundary.py`                                               | `CANONICAL`    | -            |

---

### 5.3 `scripts/domain/` (Immutable Domain Contracts)

| File                                | Current Role                                                                                       | Production Callers                                                                        | Test Callers                                                          | Classification | Target Phase |
| :---------------------------------- | :------------------------------------------------------------------------------------------------- | :---------------------------------------------------------------------------------------- | :-------------------------------------------------------------------- | :------------- | :----------- |
| `scripts/domain/__init__.py`        | Domain contract re-exports.                                                                        | `scripts/pipeline/*`, `scripts/quant/*`                                                   | `test_domain.py`, `test_provenance.py`                                | `CANONICAL`    | -            |
| `scripts/domain/data_quality.py`    | Domain contract for data quality metrics (`DataQuality`).                                          | `scripts/data/models.py`, `scripts/artifacts/provenance.py`                               | `test_domain.py`, `test_data_models.py`                               | `CANONICAL`    | -            |
| `scripts/domain/ohlcv.py`           | Domain contract for single OHLCV records (`OHLCVData`).                                            | `scripts/data/models.py`                                                                  | `test_domain.py`, `test_data_models.py`                               | `CANONICAL`    | -            |
| `scripts/domain/pipeline_result.py` | Pipeline execution result contract (`PipelineResult`).                                             | `scripts/generate_report.py`, `scripts/pipeline/stages.py`                                | `test_domain.py`, `test_data_provider.py`, `test_output_integrity.py` | `CANONICAL`    | -            |
| `scripts/domain/recommendation.py`  | Recommendation domain model (`Recommendation`).                                                    | `scripts/quant/recommendation.py`, `scripts/pipeline/stages.py`                           | `test_domain.py`, `test_provenance.py`                                | `CANONICAL`    | -            |
| `scripts/domain/risk_assessment.py` | Risk assessment domain model (`RiskAssessment`).                                                   | `scripts/quant/risk.py`, `scripts/pipeline/stages.py`                                     | `test_domain.py`, `test_provenance.py`                                | `CANONICAL`    | -            |
| `scripts/domain/trade_plan.py`      | Trade plan domain model (`TradePlan`).                                                             | `scripts/quant/risk.py`, `scripts/pipeline/stages.py`                                     | `test_domain.py`, `test_provenance.py`                                | `CANONICAL`    | -            |
| `scripts/domain/universe.py`        | Universe definition & candidate contracts (`Universe`, `UniverseCandidate`, `UniverseScanResult`). | `scripts/pipeline/context.py`, `scripts/pipeline/runner.py`, `scripts/pipeline/stages.py` | `test_domain.py`, `test_pipeline.py`, `test_parity.py`                | `CANONICAL`    | -            |

---

### 5.4 `scripts/monitoring/` (Operational Monitoring Subsystem)

| File                                | Current Role                                                                      | Production Callers                                            | Test Callers                                                    | Classification | Target Phase |
| :---------------------------------- | :-------------------------------------------------------------------------------- | :------------------------------------------------------------ | :-------------------------------------------------------------- | :------------- | :----------- |
| `scripts/monitoring/__init__.py`    | Package re-exports for operational monitoring.                                    | `scripts/pipeline/stages.py`                                  | `test_monitoring_subsystem.py`                                  | `CANONICAL`    | -            |
| `scripts/monitoring/checks.py`      | Operational checks (artifact existence, schema, freshness, numerical safety).     | `scripts/monitoring/evaluator.py`                             | `test_monitoring_subsystem.py`, `test_schema.py`                | `CANONICAL`    | -            |
| `scripts/monitoring/drift.py`       | Data & model output drift evaluation (`evaluate_data_and_model_drift`).           | `scripts/monitoring/evaluator.py`                             | `test_drift_monitoring.py`, `test_monitoring_subsystem.py`      | `CANONICAL`    | -            |
| `scripts/monitoring/evaluator.py`   | Operational monitoring evaluator (`evaluate_production_monitoring`).              | `scripts/pipeline/stages.py`                                  | `test_monitoring_subsystem.py`, `test_monitoring.py`            | `CANONICAL`    | -            |
| `scripts/monitoring/metrics.py`     | Recommendation and market payload metric extraction helpers.                      | `scripts/monitoring/drift.py`, `scripts/monitoring/checks.py` | `test_monitoring_subsystem.py`                                  | `CANONICAL`    | -            |
| `scripts/monitoring/models.py`      | Operational monitoring result models (`CheckResult`, `PipelineMonitoringResult`). | `scripts/monitoring/*`                                        | `test_monitoring_subsystem.py`                                  | `CANONICAL`    | -            |
| `scripts/monitoring/performance.py` | Performance payload validation and schema resolution for performance.             | `scripts/pipeline/validation.py`                              | `test_monitoring_subsystem.py`, `test_performance_subsystem.py` | `CANONICAL`    | -            |

---

### 5.5 `scripts/performance/` (Performance Instrumentation Subsystem)

| File                                      | Current Role                                                         | Production Callers                                           | Test Callers                                                    | Classification | Target Phase |
| :---------------------------------------- | :------------------------------------------------------------------- | :----------------------------------------------------------- | :-------------------------------------------------------------- | :------------- | :----------- |
| `scripts/performance/__init__.py`         | Performance package re-exports.                                      | `scripts/pipeline/tracker.py`, `scripts/pipeline/context.py` | `test_performance_subsystem.py`                                 | `CANONICAL`    | -            |
| `scripts/performance/budget.py`           | Provider performance budget evaluation (`evaluate_provider_budget`). | `scripts/performance/tracker.py`                             | `test_performance_subsystem.py`                                 | `CANONICAL`    | -            |
| `scripts/performance/provider_metrics.py` | Provider call timing & duplicate operation detection.                | `scripts/performance/tracker.py`                             | `test_performance_subsystem.py`                                 | `CANONICAL`    | -            |
| `scripts/performance/regression.py`       | Pipeline stage performance regression detection.                     | `scripts/performance/tracker.py`                             | `test_performance_subsystem.py`                                 | `CANONICAL`    | -            |
| `scripts/performance/stage_metrics.py`    | Stage metrics collector (`StageMetricsCollector`).                   | `scripts/performance/tracker.py`                             | `test_performance_subsystem.py`                                 | `CANONICAL`    | -            |
| `scripts/performance/tracker.py`          | Main performance orchestrator (`PerformanceTracker`).                | `scripts/pipeline/runner.py`, `scripts/pipeline/context.py`  | `test_performance_subsystem.py`, `test_pipeline_performance.py` | `CANONICAL`    | -            |

---

### 5.6 `scripts/pipeline/` (Pipeline Orchestration & Stages)

| File                             | Current Role                                                            | Production Callers                                          | Test Callers                                      | Classification | Target Phase |
| :------------------------------- | :---------------------------------------------------------------------- | :---------------------------------------------------------- | :------------------------------------------------ | :------------- | :----------- |
| `scripts/pipeline/__init__.py`   | Re-exports for pipeline components and stages.                          | `scripts/generate_report.py`                                | `test_pipeline.py`, `test_output_integrity.py`    | `CANONICAL`    | -            |
| `scripts/pipeline/audit.py`      | Audit helper (`build_universe_audit`).                                  | `scripts/pipeline/stages.py`                                | `test_domain.py`                                  | `CANONICAL`    | -            |
| `scripts/pipeline/constants.py`  | Pipeline constants (`PIPELINE_STAGES`, `FAILURE_CATEGORIES`).           | `scripts/pipeline/context.py`, `scripts/pipeline/runner.py` | `test_pipeline.py`                                | `CANONICAL`    | -            |
| `scripts/pipeline/context.py`    | Pipeline execution context (`PipelineContext`).                         | `scripts/pipeline/runner.py`, `scripts/pipeline/stages.py`  | `test_pipeline.py`, `test_quant_config.py`        | `CANONICAL`    | -            |
| `scripts/pipeline/publishing.py` | Legacy re-export wrapper re-exporting symbols from `scripts.artifacts`. | `scripts/pipeline/stages.py`                                | **None**                                          | `MIGRATE`      | M1           |
| `scripts/pipeline/result.py`     | Pipeline stage execution result wrapper.                                | `scripts/pipeline/runner.py`                                | `test_pipeline.py`                                | `CANONICAL`    | -            |
| `scripts/pipeline/runner.py`     | Main pipeline orchestrator (`PipelineRunner`).                          | `scripts/generate_report.py`                                | `test_pipeline.py`, `test_parity.py`              | `CANONICAL`    | -            |
| `scripts/pipeline/stages.py`     | Concrete implementation of all 9 pipeline stages.                       | `scripts/pipeline/runner.py`, `scripts/generate_report.py`  | `test_pipeline.py`, `test_parity.py`              | `CANONICAL`    | -            |
| `scripts/pipeline/tracker.py`    | Re-export shim delegating to `scripts/performance/tracker.py`.          | **None**                                                    | `test_data_boundary.py`, `test_pipeline.py`       | `REMOVE`       | M1           |
| `scripts/pipeline/validation.py` | Final payload integrity & performance payload validation.               | `scripts/generate_report.py`, `scripts/pipeline/stages.py`  | `test_schema.py`, `test_performance_subsystem.py` | `CANONICAL`    | -            |

---

### 5.7 `scripts/quant/` (Quantitative Calculation Engines)

| File                              | Current Role                                                                     | Production Callers                                                                   | Test Callers                              | Classification | Target Phase |
| :-------------------------------- | :------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------- | :---------------------------------------- | :------------- | :----------- |
| `scripts/quant/__init__.py`       | Quant package re-exports.                                                        | `scripts/pipeline/stages.py`                                                         | `test_engines.py`                         | `CANONICAL`    | -            |
| `scripts/quant/config.py`         | Immutable quantitative configuration (`QuantConfig`, `DEFAULT_QUANT_CONFIG`).    | `scripts/lib/config.py`, `scripts/quant/contracts.py`, `scripts/pipeline/context.py` | `test_quant_config.py`                    | `CANONICAL`    | -            |
| `scripts/quant/contracts.py`      | Typed input/output contracts for quantitative engines.                           | `scripts/quant/*`, `scripts/pipeline/stages.py`                                      | `test_engines.py`, `test_quant_config.py` | `CANONICAL`    | -            |
| `scripts/quant/features.py`       | Technical indicators and feature engineering functions.                          | `scripts/quant/regime.py`, `scripts/quant/signal.py`                                 | `test_engines.py`                         | `CANONICAL`    | -            |
| `scripts/quant/recommendation.py` | Core recommendation generator engine (`SignalRecommendationEngine`).             | `scripts/pipeline/stages.py`                                                         | `test_engines.py`, `test_quant_config.py` | `CANONICAL`    | -            |
| `scripts/quant/regime.py`         | Market regime detection engine (`MarketAnalysisEngine`, `detect_market_regime`). | `scripts/pipeline/stages.py`                                                         | `test_engines.py`, `test_regime.py`       | `CANONICAL`    | -            |
| `scripts/quant/risk.py`           | Risk & trade plan calculation engine (`RiskTradePlanEngine`).                    | `scripts/pipeline/stages.py`                                                         | `test_engines.py`, `test_risk.py`         | `CANONICAL`    | -            |
| `scripts/quant/signal.py`         | Quantitative signal scoring engine (`calculate_signal_score`).                   | `scripts/quant/recommendation.py`                                                    | `test_engines.py`, `test_quant_config.py` | `CANONICAL`    | -            |

---

### 5.8 `scripts/schema/` (Centralized Schema Registry)

| File                         | Current Role                                                                              | Production Callers                                                                                 | Test Callers     | Classification | Target Phase |
| :--------------------------- | :---------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------- | :--------------- | :------------- | :----------- |
| `scripts/schema/__init__.py` | Schema package re-exports.                                                                | `scripts/schema/registry.py`                                                                       | `test_schema.py` | `CANONICAL`    | -            |
| `scripts/schema/registry.py` | Centralized JSON schema loader & registry (`SCHEMA_REGISTRY`, `load_schema_for_version`). | `scripts/artifacts/publisher.py`, `scripts/monitoring/checks.py`, `scripts/pipeline/validation.py` | `test_schema.py` | `CANONICAL`    | -            |

---

### 5.9 Standalone Root Scripts & Utilities

| File                             | Current Role                                                                                                | Production Callers                            | Test Callers                                                                 | Classification | Target Phase |
| :------------------------------- | :---------------------------------------------------------------------------------------------------------- | :-------------------------------------------- | :--------------------------------------------------------------------------- | :------------- | :----------- |
| `scripts/data_provider.py`       | Legacy market data provider implementation, rate limit parsing (`parse_wait_seconds`), and circuit breaker. | `scripts/lib/vietnam_market.py`               | `test_data_provider.py`, `test_data_date.py`, `test_pipeline_performance.py` | `MIGRATE`      | M2           |
| `scripts/audit_trail_schema.sql` | SQL schema definition for SQLite audit logging database.                                                    | **None** in active Python execution pipeline. | **None**                                                                     | `UNKNOWN`      | M5           |

---

## 6. Test Mapping Inventory

The repository contains 31 test modules in `scripts/tests/`. Below is the complete mapping of each test file to the target production modules/APIs it tests:

| Test File Path                                     | Target Production Module / API Under Test                          | Primary Purpose                                                                                                                                      |
| :------------------------------------------------- | :----------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------- |
| `scripts/tests/run_tests.py`                       | Test Runner Infrastructure                                         | Executes entire test suite with network isolation enforcement (`RuntimeError` on unmocked socket calls) and timing diagnostics (`TimingTestRunner`). |
| `scripts/tests/test_artifact_publisher.py`         | `scripts/artifacts/publisher.py`, `manifest.py`, `recovery.py`     | Verifies atomic directory publishing, date consistency, rollback safety, and interrupted recovery.                                                   |
| `scripts/tests/test_artifact_transaction.py`       | `scripts/artifacts/transaction.py`                                 | Tests POSIX single-writer file lock, atomic staging/backup directories, and transaction state rollback.                                              |
| `scripts/tests/test_audit_observability.py`        | `scripts/pipeline/audit.py`, `scripts/monitoring/*`                | Tests universe audit trail dictionary construction, schema validity, and pipeline context metadata tracking.                                         |
| `scripts/tests/test_backtest.py`                   | `scripts/lib/backtest.py`                                          | Tests Point-In-Time dataset slicing, forward outcome evaluation, liquidity execution eligibility, and walk-forward date generation.                  |
| `scripts/tests/test_config.py`                     | `scripts/lib/config.py`, `scripts/quant/config.py`                 | Verifies configuration parameter delegation, version strings, and default quantitative configuration.                                                |
| `scripts/tests/test_data_acquisition.py`           | `scripts/data/acquisition.py`                                      | Tests `MarketDataAcquirer` error classification, rate limiting, provider fallback, and status tags.                                                  |
| `scripts/tests/test_data_boundary.py`              | `scripts/data/*`, `scripts/lib/vietnam_market.py`                  | Tests boundary isolation between external market data providers, normalizers, and internal quantitative engines.                                     |
| `scripts/tests/test_data_date.py`                  | `scripts/lib/vietnam_market.py`                                    | Tests temporal integrity validation (`validate_temporal_integrity`), staleness bounds, and benchmark date alignment.                                 |
| `scripts/tests/test_data_flow_consistency.py`      | `scripts/generate_report.py`                                       | Verifies data flow filtering from clean OHLCV to report payloads, symbol filtering, and history index updates.                                       |
| `scripts/tests/test_data_models.py`                | `scripts/data/models.py`, `scripts/domain/ohlcv.py`                | Verifies `CanonicalMarketData` invariants, record immutability, `to_df()` conversion, and forbidden provider field rejection.                        |
| `scripts/tests/test_data_normalization.py`         | `scripts/data/normalization.py`                                    | Tests raw provider payload transformation into `CanonicalMarketData` and missing column handling.                                                    |
| `scripts/tests/test_data_provider.py`              | `scripts/data_provider.py`, `scripts/generate_report.py`           | Tests rate-limit parsing (`parse_wait_seconds`), rate-limit recovery pacing, circuit breaker tripping, and symbol universe completeness.             |
| `scripts/tests/test_data_provider_boundary.py`     | `scripts/data/providers/vnstock.py`, `base.py`                     | Tests Vnstock provider exception adaptation (`CanonicalOHLCVError` → `ExplicitlyInvalidDataError`) and network boundary contracts.                   |
| `scripts/tests/test_data_quality.py`               | `scripts/lib/vietnam_market.py`, `scripts/generate_report.py`      | Tests fail-closed OHLCV validation (`validate_ohlcv_data`), non-positive price rejection, and insufficient history tagging.                          |
| `scripts/tests/test_data_validation.py`            | `scripts/data/validation.py`                                       | Verifies `CanonicalMarketValidator` schema checks, OHLC relationship constraints (`high >= low`), and chronological sorting checks.                  |
| `scripts/tests/test_dependencies.py`               | Dependency Environment (`pyproject.toml`, `uv.lock`)               | Verifies Python runtime version (>= 3.14) and pinned core dependency versions (`pandas`, `numpy`, `vnstock`).                                        |
| `scripts/tests/test_domain.py`                     | `scripts/domain/*`                                                 | Verifies domain model immutability, validation constraints (`Universe`, `UniverseCandidate`), and audit dictionary generation.                       |
| `scripts/tests/test_downstream_data_validation.py` | `scripts/quant/*`, `scripts/lib/risk.py`                           | Verifies that downstream calculations handle NaN/Inf/insufficient data fail-closed without silent data fabrication.                                  |
| `scripts/tests/test_drift_monitoring.py`           | `scripts/monitoring/drift.py`                                      | Tests operational data and model drift evaluation (`evaluate_data_and_model_drift`), historical baseline selection, and insufficiency handling.      |
| `scripts/tests/test_e2e_backtest_integrity.py`     | `scripts/lib/backtest.py`, `scripts/lib/portfolio_backtest.py`     | End-to-end backtesting integrity test suite: anti-lookahead temporal safety, transaction costs, slippage, and portfolio weight conservation.         |
| `scripts/tests/test_engines.py`                    | `scripts/quant/*`                                                  | Native unit tests for quantitative engines (`MarketAnalysisEngine`, `SignalRecommendationEngine`, `RiskTradePlanEngine`).                            |
| `scripts/tests/test_execution_costs.py`            | `scripts/lib/backtest.py`, `scripts/lib/portfolio_backtest.py`     | Verifies deterministic transaction cost and adverse slippage calculations (`calculate_execution_return`) across BUY/SELL actions.                    |
| `scripts/tests/test_historical_report.py`          | `scripts/generate_report.py`                                       | Tests historical report generation entry point (`generate_historical_report`) and point-in-time artifact output.                                     |
| `scripts/tests/test_history_index.py`              | `scripts/generate_report.py`                                       | Verifies `history/index.json` loading, atomic index updating, deduplication, and chronological sorting.                                              |
| `scripts/tests/test_monitoring.py`                 | `scripts/monitoring/*`                                             | Verifies operational monitoring checks (artifact presence, schema compliance, freshness, benchmark quality).                                         |
| `scripts/tests/test_monitoring_subsystem.py`       | `scripts/monitoring/*`, `scripts/lib/monitoring.py`                | Tests operational monitoring models, evaluator, and 100% backward compatibility of `scripts.lib.monitoring` re-exports.                              |
| `scripts/tests/test_output_integrity.py`           | `scripts/pipeline/validation.py`, `scripts/generate_report.py`     | Verifies final payload integrity checks, schema validation, and missing key detection.                                                               |
| `scripts/tests/test_parity.py`                     | `scripts/pipeline/runner.py`, `scripts/generate_report.py`         | Parity integration suite verifying exact numerical equivalence between production pipeline runs and historical report generation.                    |
| `scripts/tests/test_performance_subsystem.py`      | `scripts/performance/*`                                            | Tests performance instrumentation (`PerformanceTracker`), stage metrics collection, duplicate operation detection, and budget enforcement.           |
| `scripts/tests/test_pipeline.py`                   | `scripts/pipeline/*`                                               | Tests all 9 pipeline stages, stage execution order, pipeline context state mutations, and failure handling.                                          |
| `scripts/tests/test_pipeline_monitoring_status.py` | `scripts/pipeline/stages.py`, `scripts/monitoring/*`               | Verifies that pipeline monitoring stage failure statuses propagate accurately to execution results.                                                  |
| `scripts/tests/test_pipeline_performance.py`       | `scripts/pipeline/stages.py`, `scripts/performance/*`              | Verifies performance tracker integration across pipeline stages and budget evaluation.                                                               |
| `scripts/tests/test_portfolio_backtest.py`         | `scripts/lib/portfolio_backtest.py`                                | Tests portfolio backtesting determinism, equal weighting, allocation constraints, missing outcome propagation, and evaluation date boundaries.       |
| `scripts/tests/test_provenance.py`                 | `scripts/artifacts/provenance.py`                                  | Tests `ProvenanceManifest` creation, schema validation, source provider metadata, and quality ratio bounds.                                          |
| `scripts/tests/test_quant_config.py`               | `scripts/quant/config.py`                                          | Tests `QuantConfig` immutability (`FrozenDict`), hash generation, deepcopy safety, and payload configuration consistency checks.                     |
| `scripts/tests/test_recommendation.py`             | `scripts/quant/recommendation.py`, `scripts/lib/recommendation.py` | Tests signal generation logic, confidence scoring, technical score weighting, and price limit clamping.                                              |
| `scripts/tests/test_regime.py`                     | `scripts/quant/regime.py`, `scripts/lib/regime.py`                 | Tests market regime classification logic (BULLISH, BEARISH, NEUTRAL, HIGH_VOLATILITY) and volume ratio calculation.                                  |
| `scripts/tests/test_risk.py`                       | `scripts/quant/risk.py`, `scripts/lib/risk.py`                     | Tests T+2.5 return calculation, Historical VaR 95%, Expected Shortfall, Max Drawdown, 60d Volatility, and stop/target price calculations.            |
| `scripts/tests/test_schema.py`                     | `scripts/schema/registry.py`                                       | Tests central schema registry resolution (`load_schema_for_version`), supported version validation, and malformed version rejection.                 |
| `scripts/tests/test_ssg_html.py`                   | Static Site / Artifacts Output                                     | Verifies generated JSON artifact compatibility with static frontend site consumption.                                                                |
| `scripts/tests/test_unit_normalization.py`         | `scripts/quant/*`                                                  | Tests unit normalization across quantitative metrics, price scales, and percentage outputs.                                                          |

---

## 7. Generated Artifact Mapping

Below is the authoritative mapping of every generated output artifact to its producing pipeline stage and Python module:

| Generated Artifact Path               | Producing Pipeline Stage / Subsystem                              | Producing Module / Class                                       | Governing Schema                         |
| :------------------------------------ | :---------------------------------------------------------------- | :------------------------------------------------------------- | :--------------------------------------- |
| `generated/recommendations.json`      | `SignalRecommendationGenerationStage` / `ArtifactPublishingStage` | `scripts/pipeline/stages.py`, `scripts/artifacts/publisher.py` | `schemas/v2/recommendations.schema.json` |
| `generated/market.json`               | `MarketAnalysisStage` / `ArtifactPublishingStage`                 | `scripts/pipeline/stages.py`, `scripts/artifacts/publisher.py` | Internal market analysis structure       |
| `generated/performance.json`          | `PerformanceStage` / `ArtifactPublishingStage`                    | `scripts/pipeline/stages.py`, `scripts/artifacts/publisher.py` | `schemas/v2/performance.schema.json`     |
| `generated/monitoring.json`           | `MonitoringStage` / `ArtifactPublishingStage`                     | `scripts/pipeline/stages.py`, `scripts/artifacts/publisher.py` | Internal monitoring result structure     |
| `generated/provenance.json`           | `ArtifactPublishingStage`                                         | `scripts/artifacts/provenance.py`, `publisher.py`              | Internal provenance manifest structure   |
| `generated/history/index.json`        | `ArtifactPublishingStage` / History Manager                       | `scripts/generate_report.py`, `scripts/artifacts/manifest.py`  | Internal history index structure         |
| `generated/history/{YYYY-MM-DD}.json` | `ArtifactPublishingStage` / History Manager                       | `scripts/generate_report.py`, `scripts/artifacts/publisher.py` | `schemas/v2/recommendations.schema.json` |

---

## 8. Compatibility Layer Audit & Classification

The codebase contains several compatibility layers created during prior incremental refactorings. These layers are classified below:

| Compatibility Layer Module       | Current Status & Purpose                                                                                          | Classification | Action Required for Cleanup                                                                                                 |
| :------------------------------- | :---------------------------------------------------------------------------------------------------------------- | :------------- | :-------------------------------------------------------------------------------------------------------------------------- |
| `scripts/lib/monitoring.py`      | Re-exports all symbols from `scripts.monitoring`. 0 production callers.                                           | `REMOVE`       | Re-route test imports in 6 test files to `scripts.monitoring.*`, then delete file.                                          |
| `scripts/lib/features.py`        | Re-exports technical indicators from `scripts.quant.features`. 0 production callers.                              | `REMOVE`       | Re-route test imports in `test_recommendation.py` to `scripts.quant.features`, then delete file.                            |
| `scripts/pipeline/tracker.py`    | Re-exports `PerformanceTracker` from `scripts.performance.tracker`. 0 production callers.                         | `REMOVE`       | Re-route test imports in `test_data_boundary.py` and `test_pipeline.py` to `scripts.performance.tracker`, then delete file. |
| `scripts/pipeline/publishing.py` | Re-exports symbols from `scripts.artifacts`. Imported by `scripts/pipeline/stages.py`.                            | `MIGRATE`      | Update `scripts/pipeline/stages.py` to import directly from `scripts.artifacts`, then delete file.                          |
| `scripts/lib/recommendation.py`  | Re-exports from `scripts.quant.recommendation`. Imported by `generate_report.py` and `scripts/lib/risk.py`.       | `MIGRATE`      | Update `generate_report.py` and `scripts/lib/risk.py` to import from `scripts.quant.recommendation`, then delete file.      |
| `scripts/lib/regime.py`          | Re-exports from `scripts.quant.regime`. Imported by `generate_report.py`, `backtest.py`, `portfolio_backtest.py`. | `MIGRATE`      | Update callers to import from `scripts.quant.regime`, then delete file.                                                     |
| `scripts/lib/risk.py`            | Holds `normalize_universe_liquidity_scores` & re-exports quant risk. Imported by `generate_report.py`.            | `MIGRATE`      | Move liquidity score normalization to `scripts/quant/risk.py`, update callers, then delete file.                            |
| `scripts/lib/config.py`          | Re-exports constants and delegates to `DEFAULT_QUANT_CONFIG`. Imported by 12 production modules.                  | `MIGRATE`      | Move constants to `scripts/pipeline/constants.py` and `scripts/quant/config.py`, update callers, then delete file.          |
| `scripts/lib/vietnam_market.py`  | Monolithic market data & universe provider. Imported across pipeline, quant, and monitoring.                      | `MIGRATE`      | Re-route callers to `scripts/data/*` and `scripts/domain/universe.py`, then delete file.                                    |
| `scripts/data_provider.py`       | Legacy provider class and rate limit parser.                                                                      | `MIGRATE`      | Integrate `parse_wait_seconds` into `scripts/data/` provider infrastructure, update callers, then delete file.              |

---

## 9. Future Roadmap & Cleanup Priorities (M1–M5)

Based on the audit findings, the cleanup roadmap for Milestones M1 through M5 is structured as follows:

```
[ M0: Audit & Freeze ]  -->  [ M1: Re-export & Unused Shim Elimination ]
                                     |
                                     v
                             [ M2: Legacy Market Data & Provider Decoupling ]
                                     |
                                     v
                             [ M3: Backtesting & Quant Engine Package Clean-up ]
                                     |
                                     v
                             [ M4: Test Suite Import Re-routing & Standardization ]
                                     |
                                     v
                             [ M5: Schema, SQL & Final Cleanup Verification ]
```

### Milestone Breakdown

#### Milestone M1 — Compatibility Shim & Unused Module Elimination

- **Goal**: Remove pure compatibility wrappers with 0 or minimal production callers.
- **Tasks**:
  1. Remove `scripts/lib/monitoring.py` (update 6 test files to import from `scripts.monitoring`).
  2. Remove `scripts/lib/features.py` (update `test_recommendation.py` to import from `scripts.quant.features`).
  3. Remove `scripts/pipeline/tracker.py` (update 2 test files to import from `scripts.performance.tracker`).
  4. Migrate `scripts/pipeline/publishing.py` callers (`scripts/pipeline/stages.py`) to `scripts.artifacts` directly, then remove `publishing.py`.
  5. Migrate `scripts/lib/recommendation.py`, `scripts/lib/regime.py`, and `scripts/lib/risk.py` callers to `scripts/quant/*`, then remove those 3 wrapper files.

#### Milestone M2 — Legacy Market Data & Provider Decoupling

- **Goal**: Replace `scripts/lib/vietnam_market.py` and `scripts/data_provider.py` with canonical `scripts/data/*` and `scripts/domain/*`.
- **Tasks**:
  1. Move `UniverseProvider` and universe definition to `scripts/domain/universe.py` / `scripts/pipeline/`.
  2. Move `parse_wait_seconds` and rate-limiting to `scripts/data/providers/vnstock.py`.
  3. Re-route `scripts/generate_report.py`, `scripts/pipeline/stages.py`, `scripts/quant/*`, and `scripts/monitoring/*` away from `scripts/lib/vietnam_market.py`.
  4. Delete `scripts/lib/vietnam_market.py` and `scripts/data_provider.py`.

#### Milestone M3 — Backtesting & Quant Package Consolidation

- **Goal**: Relocate quantitative backtesting engines from `scripts/lib/` to canonical package locations.
- **Tasks**:
  1. Relocate `scripts/lib/backtest.py` and `scripts/lib/portfolio_backtest.py` to `scripts/backtest/` (e.g. `scripts/backtest/engine.py` and `scripts/backtest/portfolio.py`).
  2. Move shared date parsing (`_parse_canonical_date`) to a dedicated utility.
  3. Update callers and backtest test suite imports.
  4. Eliminate `scripts/lib/` directory completely.

#### Milestone M4 — Test Suite Import Re-routing & Standardization

- **Goal**: Ensure 100% of test files in `scripts/tests/` import directly from canonical module locations without relying on legacy re-exports or monkeypatching legacy paths.
- **Tasks**:
  1. Audit all `patch(...)` calls in `scripts/tests/` (e.g., re-routing patches from `scripts.lib.vietnam_market.time.sleep` to `scripts.data.providers.vnstock`).
  2. Standardize test imports across all 31 test files.

#### Milestone M5 — Schema, SQL & Resolution of UNKNOWN Items

- **Goal**: Resolve outstanding architecture questions, schema drift, and perform final codebase verification.
- **Tasks**:
  1. Make decision on `scripts/audit_trail_schema.sql` (keep in `docs/schema/` or remove if obsolete).
  2. Run full regression test suite (`run_tests.py`), linting (`ruff`), and artifact validation to ensure clean state.

---

## 10. Key UNKNOWN Decision Points & Open Questions

Before proceeding with M1–M5 cleanup, the following explicit **UNKNOWN** items must be reviewed and decided by the maintainers:

1. **`scripts/audit_trail_schema.sql`**:
   - _Status_: `UNKNOWN`
   - _Issue_: SQL file defining an SQLite audit log schema (`audit_trail`). Currently has 0 references in active Python pipeline scripts (`scripts/pipeline/`, `scripts/generate_report.py`).
   - _Decision Required_: Is SQLite audit logging a planned future feature (in which case it should be moved to `docs/schema/` or `scripts/db/`), or is it obsolete and safe to delete in M5?

2. **Frontend `MarketRegime` Type Alignment (`NEUTRAL`)**:
   - _Status_: Known contract drift between backend (`VALID_MARKET_REGIMES` includes `NEUTRAL`) and frontend TypeScript type in `src/types/recommendation.ts` (which omitted `NEUTRAL`).
   - _Decision Required_: Confirm frontend schema generator step in M5 or Phase 6 to automatically generate TypeScript types from `schemas/v2/`.

3. **Canonical Relocation Target for Backtest Modules**:
   - _Status_: `scripts/lib/backtest.py` and `scripts/lib/portfolio_backtest.py` are canonical logic, but reside in legacy `scripts/lib/`.
   - _Decision Required_: Confirm target package location: option A (`scripts/backtest/engine.py`, `scripts/backtest/portfolio.py`) vs option B (`scripts/quant/backtest.py`, `scripts/quant/portfolio_backtest.py`). Option A is recommended for clear separation of concerns.

---

_End of Architecture Baseline Inventory (M0)._
