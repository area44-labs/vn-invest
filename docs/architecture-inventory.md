# Repository Architecture Baseline Inventory

## 1. Purpose

This document records the canonical architecture inventory of `area44-labs/vn-invest`.

All legacy modules under `scripts/lib/*` have been fully migrated to their single authoritative canonical owners and deleted. The `scripts/lib/` directory has been removed completely from the repository.

---

# 2. Classification Rules

Every audited component is assigned one or more of the following architectural statuses.

| Classification | Meaning                                                                                                            |
| -------------- | ------------------------------------------------------------------------------------------------------------------ |
| `CANONICAL`    | Current authoritative implementation and intended architectural home.                                              |
| `LEGACY`       | Existing implementation that remains functional but belongs to an older architecture.                              |
| `REMOVE`       | Confirmed obsolete/dead/compatibility-only component that can be deleted after its remaining callers are migrated. |
| `KEEP`         | Valid implementation that must remain; relocation is not currently required.                                       |
| `MIGRATE`      | Active code that must be moved or have callers redirected to the canonical architecture.                           |
| `REMOVED`      | Obsolete legacy component that has been completely migrated and removed from the codebase.                         |

---

# 3. Current Architecture

The repository is organized around the following canonical layers:

```text
scripts/
├── domain/          # Canonical domain models and contracts (Universe, Candidate, Quality)
├── data/            # Canonical market-data acquisition, normalization, and validation
├── pipeline/        # Production pipeline orchestration and stage execution
├── quant/           # Quantitative engines, signal scoring, risk, trade plans, and config
├── backtest/        # Canonical backtesting framework and portfolio-level backtest
├── performance/     # Performance instrumentation, timing metrics, and budget checks
├── monitoring/      # Production monitoring, data quality checks, and drift evaluation
├── artifacts/       # Artifact publishing, atomic transaction, manifest, and provenance
├── schema/          # Schema registry/version resolution
├── tests/           # Pytest test suite
└── generate_report.py  # Production CLI entry point
```

Additional architectural surfaces:

```text
schemas/v2/          # Versioned artifact schemas
src/data/            # Frontend data loading/adapters
generated/           # Published runtime artifacts
.github/workflows/   # CI and production automation
```

The canonical data flow architecture is:

```text
Provider
   ↓
Data Acquisition (scripts/data/acquisition.py)
   ↓
Canonical Data Validation (scripts/data/validation.py)
   ↓
Domain / Universe (scripts/domain/universe.py)
   ↓
PipelineContext (scripts/pipeline/context.py)
   ↓
Quantitative Engines (scripts/quant/*)
   ↓
Performance (scripts/performance/*)
   ↓
Monitoring (scripts/monitoring/*)
   ↓
Artifact Publishing (scripts/artifacts/*)
   ↓
generated/
   ↓
Frontend
```

---

# 4. Production Entry Points

| Entry point                         | Purpose                                            | Status      |
| ----------------------------------- | -------------------------------------------------- | ----------- |
| `scripts/generate_report.py`        | Main production CLI for pipeline/report generation | `CANONICAL` |
| `.github/workflows/update-data.yml` | Scheduled/manual production data update            | `CANONICAL` |
| `.github/workflows/tests.yml`       | Python CI test execution                           | `CANONICAL` |
| `.github/workflows/pages.yml`       | Frontend/static deployment                         | `CANONICAL` |
| `src/data/loader.ts`                | Frontend runtime data loading                      | `CANONICAL` |

---

# 5. Canonical Architecture Inventory

## 5.1 Domain

```text
scripts/domain/
```

### Classification

`CANONICAL`

### Responsibility

Owns domain-level models and contracts:

- `Universe`, `UniverseCandidate`, `UniverseScanResult` (`scripts/domain/universe.py`)
- `OHLCVData` (`scripts/domain/ohlcv.py`)
- `DataQuality` (`scripts/domain/data_quality.py`)
- `Recommendation` (`scripts/domain/recommendation.py`)
- `RiskAssessment` (`scripts/domain/risk_assessment.py`)
- `TradePlan` (`scripts/domain/trade_plan.py`)
- `PipelineResult` (`scripts/domain/pipeline_result.py`)

Includes `UniverseProvider` and `CANDIDATE_STOCKS` as canonical domain sources for universe construction.

---

## 5.2 Data

```text
scripts/data/
```

### Classification

`CANONICAL`

### Responsibility

Owns market-data acquisition, provider boundary integration, normalization, and validation:

- `acquisition.py`: `MarketDataAcquirer`, `acquire_raw_market_data`, `get_historical_data`
- `normalization.py`: `MarketDataNormalizer`, `normalize_raw_market_data`, `normalize_symbol`, `normalize_ohlcv_units`, unit constants (`PRICE_UNIT`, `VOLUME_UNIT`, etc.)
- `validation.py`: `CanonicalMarketValidator`, `validate_canonical_market_data`, `validate_ohlcv_data`, `get_clean_ohlcv_data`, `validate_temporal_integrity`, `extract_latest_trading_date`, `round_tick_size`, `get_exchange_price_limits`, `clamp_price_limits`
- `providers/`: `VnstockMarketProvider`, base classes, and exception contracts

---

## 5.3 Pipeline

```text
scripts/pipeline/
```

### Classification

`CANONICAL`

### Responsibility

Owns production orchestration, pipeline context lifecycle, and 9 explicit execution stages:

- `runner.py`: `ProductionPipeline`, `run_pipeline`
- `context.py`: `PipelineContext`
- `stages.py`: 9 explicit stage classes (`DataAcquisitionStage`, `DataValidationStage`, `UniverseValidationStage`, `MarketAnalysisStage`, `SignalRecommendationGenerationStage`, `RiskTradePlanStage`, `PerformanceStage`, `MonitoringStage`, `ArtifactPublishingStage`)
- `constants.py`: `PIPELINE_VERSION`, `DEFAULT_UPDATE_THROTTLE_DELAY`, directory paths
- `validation.py`: Final payload integrity checks
- `publishing.py`: Re-export adapter over `scripts/artifacts`

---

## 5.4 Quantitative Layer

```text
scripts/quant/
```

### Classification

`CANONICAL`

### Responsibility

Owns quantitative engines, signal calculations, risk metrics, trade plans, market regime detection, and configuration:

- `config.py`: `QuantConfig` (frozen dataclass), `DEFAULT_QUANT_CONFIG`, version contracts (`quant_version`, `model_version`, `config_hash`)
- `contracts.py`: Typed input/output contracts (`SignalInput`, `SignalResult`, `RiskInput`, `RiskResult`, `RecommendationInput`, `RecommendationResult`, `RegimeInput`, `RegimeResult`, `MarketAnalysisInput`, `CandidateSpec`)
- `features.py`: Multi-timeframe technical indicator calculations and divergence detection
- `regime.py`: `detect_market_regime` (single authoritative market regime detection function supporting typed and dictionary inputs)
- `signal.py`: `compute_signal`, signal component scoring functions, action classification
- `risk.py`: `compute_stock_risk_and_trade_plan`, `RiskTradePlanEngine`, `calculate_t25_risk_metrics`, `normalize_universe_liquidity_scores`, confidence calculation
- `recommendation.py`: `generate_single_recommendation`, `SignalRecommendationEngine` (single authoritative recommendation function and engine)

---

## 5.5 Backtesting Layer

```text
scripts/backtest/
```

### Classification

`CANONICAL`

### Responsibility

Owns point-in-time signal evaluation, forward historical outcomes, execution eligibility, walk-forward validation, and portfolio-level backtesting:

- `engine.py`: `get_as_of_dataset`, `evaluate_forward_outcomes`, `evaluate_execution_eligibility`, `run_backtest_for_symbol`, `run_backtest_for_universe`, `run_walk_forward_backtest`, `evaluate_market_regimes`, `evaluate_signal_components`, `evaluate_confidence_calibration`
- `portfolio.py`: `PortfolioConfig`, `PortfolioPosition`, `PortfolioEvaluation`, `PortfolioBacktestResult`, `evaluate_portfolio_at_date`, `run_portfolio_backtest`, `aggregate_portfolio_results`
- `__init__.py`: Public re-exports for the backtest subsystem

---

## 5.6 Performance

```text
scripts/performance/
```

### Classification

`CANONICAL`

### Responsibility

Owns performance tracking, stage metrics, provider timing aggregation, budgets, and regression evaluation.

---

## 5.7 Monitoring

```text
scripts/monitoring/
```

### Classification

`CANONICAL`

### Responsibility

Owns production monitoring, data/model drift evaluation, data quality checks, and monitoring models.

---

## 5.8 Artifacts & Schema

```text
scripts/artifacts/
scripts/schema/
```

### Classification

`CANONICAL`

### Responsibility

Owns atomic artifact publishing, single-writer POSIX locks, provenance tracking, and canonical schema registry resolution (`schemas/v2/`).

---

# 6. `scripts/lib/*` Legacy Inventory

The legacy directory `scripts/lib/` has been **completely removed**.

## 6.1 Final Migration Summary

| Module                              | Status    | Final Canonical Owner                                                                                                      |
| ----------------------------------- | --------- | -------------------------------------------------------------------------------------------------------------------------- |
| `scripts/lib/config.py`             | `REMOVED` | `scripts/quant/config.py`, `scripts/pipeline/constants.py`, `scripts/data/validation.py`                                   |
| `scripts/lib/features.py`           | `REMOVED` | `scripts/quant/features.py`                                                                                                |
| `scripts/lib/monitoring.py`         | `REMOVED` | `scripts/monitoring/*`                                                                                                     |
| `scripts/lib/recommendation.py`     | `REMOVED` | `scripts/quant/recommendation.py`, `scripts/quant/signal.py`, `scripts/quant/risk.py`                                      |
| `scripts/lib/regime.py`             | `REMOVED` | `scripts/quant/regime.py`                                                                                                  |
| `scripts/lib/risk.py`               | `REMOVED` | `scripts/quant/risk.py`                                                                                                    |
| `scripts/lib/vietnam_market.py`     | `REMOVED` | `scripts/data/validation.py`, `scripts/data/normalization.py`, `scripts/data/acquisition.py`, `scripts/domain/universe.py` |
| `scripts/lib/backtest.py`           | `REMOVED` | `scripts/backtest/engine.py` (`scripts/backtest/`)                                                                         |
| `scripts/lib/portfolio_backtest.py` | `REMOVED` | `scripts/backtest/portfolio.py` (`scripts/backtest/`)                                                                      |

---

# 7. `scripts.lib` Dependency Map

Repository search for `scripts.lib` in runtime and test code yields **zero active references**:

```bash
git grep "scripts\.lib"
```

All production modules, pipeline stages, quantitative engines, CLI entry points, and pytest test suites import exclusively from canonical subsystems (`scripts.domain`, `scripts.data`, `scripts.pipeline`, `scripts.quant`, `scripts.backtest`, `scripts.performance`, `scripts.monitoring`, `scripts.artifacts`, `scripts.schema`).

---

# 8. Public vs Internal API Surface

Primary external interfaces:

```text
CLI:
scripts/generate_report.py

Generated artifacts:
generated/*.json

Versioned schemas:
schemas/v2/*.json

Frontend data contract:
generated/ + src/data/
```

Internal architecture subsystem boundaries:

```text
scripts/domain/
scripts/data/
scripts/pipeline/
scripts/quant/
scripts/backtest/
scripts/performance/
scripts/monitoring/
scripts/artifacts/
scripts/schema/
```

---

# 9. Test → Production Mapping

The Python test suite in `scripts/tests/` uses native pytest (`uv run --frozen pytest`).

| Test area                        | Primary production owner                        |
| -------------------------------- | ----------------------------------------------- |
| `test_domain.py`                 | `scripts/domain/`                               |
| `test_data_*.py`                 | `scripts/data/` and data-provider boundaries    |
| `test_pipeline*.py`              | `scripts/pipeline/`                             |
| `test_engines.py`                | `scripts/quant/`                                |
| `test_recommendation.py`         | `scripts/quant/`                                |
| `test_regime.py`                 | `scripts/quant/regime.py`                       |
| `test_risk.py`                   | `scripts/quant/risk.py`                         |
| `test_quant_config.py`           | `scripts/quant/config.py`                       |
| `test_backtest.py`               | `scripts/backtest/engine.py`                    |
| `test_portfolio_backtest.py`     | `scripts/backtest/portfolio.py`                 |
| `test_e2e_backtest_integrity.py` | `scripts/backtest/`                             |
| `test_execution_costs.py`        | `scripts/backtest/`                             |
| `test_performance*.py`           | `scripts/performance/`                          |
| `test_monitoring*.py`            | `scripts/monitoring/`                           |
| `test_artifact*.py`              | `scripts/artifacts/`                            |
| `test_provenance.py`             | `scripts/artifacts/provenance.py`               |
| `test_schema.py`                 | `scripts/schema/` + `schemas/v2/`               |
| `test_historical_report.py`      | `scripts/generate_report.py` / pipeline history |
| `test_history_index.py`          | history/report generation                       |
| `test_output_integrity.py`       | pipeline/artifact validation                    |
| `test_parity.py`                 | pipeline/report parity                          |

---

# 10. Architecture Status Summary

1. Legacy `scripts/lib/*` modules are completely removed.
2. The `scripts/lib` directory is removed.
3. Every responsibility has exactly one canonical owner.
4. Production code and test suites import strictly from canonical packages.
5. All backend pytest tests pass cleanly.
