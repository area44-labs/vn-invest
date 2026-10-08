# Subsystem Architecture & Canonical Boundaries

This document is the authoritative architectural specification for **VN Invest** (`area44-labs/vn-invest`). It defines system package/module boundaries, data flow hierarchy, entry points, and architectural rules following the completion of Milestone M2 (complete removal of `scripts/lib/*`).

---

## 1. High-Level Architecture Overview

VN Invest operates as an automated quantitative analysis and static report generation system for Vietnamese stock markets (HOSE, HNX, UPCoM).

```text
[ Market Data Provider (Vnstock) ]
               │
               ▼
┌───────────────────────────────────────────────┐
│           Python Quantitative Engine          │
│       (Data -> Quant -> Pipeline)             │
└──────────────────────┬────────────────────────┘
                       │ Validated Static JSON
                       ▼
┌───────────────────────────────────────────────┐
│        Generated Artifacts (generated/)       │
│  recommendations.json / market.json / ...     │
└──────────────────────┬────────────────────────┘
                       │ SSG Build (Vite+)
                       ▼
┌───────────────────────────────────────────────┐
│       React SSG Frontend (TanStack Start)     │
│             Published to GitHub Pages         │
└───────────────────────────────────────────────┘
```

The system is split into two primary environments:

1. **Python Quantitative Backend (`scripts/`)**: Handles market data collection, canonical validation, technical indicators, signal generation, risk modeling (T+2.5 VaR/ES), portfolio backtesting, operational monitoring, and atomic artifact publishing.
2. **React SSG Frontend (`src/`)**: A read-only static web application that consumes generated JSON payloads. **Zero financial or quantitative calculations occur in the frontend.**

---

## 2. Canonical Subsystem Hierarchy & Boundaries

The backend architecture consists of 9 canonical Python packages under `scripts/`. Each package has a single, strictly bounded responsibility.

```text
scripts/
├── domain/          # Canonical domain contracts, models, and universe definitions
├── data/            # Market data acquisition, normalization, provider adapters, and validation
├── quant/           # Pure quantitative engines, indicator calculation, signals, and risk
├── pipeline/        # Stage-based orchestration runner and execution context
├── backtest/        # Walk-forward backtesting, cost models, and portfolio evaluation
├── performance/     # Pipeline runtime timing, provider metrics, and budget checks
├── monitoring/      # Operational monitoring checks, data quality, and drift evaluation
├── artifacts/       # Atomic publishing, POSIX locking, transactions, and provenance
└── schema/          # Centralized version-aware schema registry (resolving schemas/v2/)
```

### Dependency Direction Rules

The system enforces strict top-down dependency flow:

$$\text{domain} \longrightarrow \text{data} / \text{quant} \longrightarrow \text{pipeline} / \text{backtest} \longrightarrow \text{performance} / \text{monitoring} / \text{artifacts}$$

- **`scripts/domain`**: Zero external dependencies within `scripts/`. Imports only standard library and typing.
- **`scripts/data` & `scripts/quant`**: Depend on `scripts/domain`. Contain pure functions and isolated calculation engines without pipeline I/O.
- **`scripts/pipeline`**: Coordinates execution across `data`, `quant`, `performance`, `monitoring`, and `artifacts`.
- **`scripts/artifacts`**: Manages file transactions and locking. Has **zero top-level import dependencies on `scripts.pipeline`** to prevent circular dependencies.
- **No legacy `scripts/lib/*`**: All legacy compatibility modules in `scripts/lib/` were deleted in M2. All code imports directly from canonical packages.

---

## 3. Subsystem Breakdown

### 3.1 Domain (`scripts/domain/`)

- **Primary Responsibility**: Defines immutable frozen dataclasses for domain entities.
- **Core Models**: `Universe`, `UniverseCandidate`, `UniverseScanResult`, `OHLCVData`, `DataQuality`, `TradePlan`, `RiskAssessment`, `Recommendation`, `PipelineResult`.
- **Universe Source**: `UniverseProvider` and `CANDIDATE_STOCKS` serve as the single source of candidate symbol universe metadata.
- **See**: [docs/naming.md](naming.md) and [docs/data-contracts.md](data-contracts.md).

### 3.2 Data Layer (`scripts/data/`)

- **Primary Responsibility**: Encapsulates external provider access (`VnstockMarketProvider`), unit normalization, and strict canonical OHLCV validation.
- **Core Modules**: `acquisition.py`, `normalization.py`, `validation.py`, `providers/`.
- **Validation**: Enforces non-empty datasets, positive prices, non-negative volumes, monotonic trading dates, and temporal consistency (`data_as_of`).
- **See**: [docs/pipeline.md](pipeline.md) and [docs/data-contracts.md](data-contracts.md).

### 3.3 Quantitative Engine (`scripts/quant/`)

- **Primary Responsibility**: Computes technical indicators, market regime, signal scores, T+2.5 risk assessments, and stock trade plans.
- **Core Modules**: `config.py` (`QuantConfig`), `contracts.py`, `features.py`, `regime.py`, `signal.py`, `risk.py`, `recommendation.py`.
- **Engines**: `MarketAnalysisEngine`, `SignalRecommendationEngine`, `RiskTradePlanEngine`.
- **See**: [docs/quantitative.md](quantitative.md).

### 3.4 Production Pipeline Orchestration (`scripts/pipeline/`)

- **Primary Responsibility**: Orchestrates the 9 explicit execution stages via `PipelineContext` and `ProductionPipeline`.
- **Core Modules**: `runner.py`, `context.py`, `stages.py`, `constants.py`, `validation.py`, `publishing.py`.
- **See**: [docs/pipeline.md](pipeline.md).

### 3.5 Backtesting Framework (`scripts/backtest/`)

- **Primary Responsibility**: Point-in-time signal testing, forward outcome calculations, execution eligibility evaluation, and portfolio allocation backtests.
- **Core Modules**: `engine.py`, `portfolio.py`.
- **See**: [docs/quantitative.md](quantitative.md).

### 3.6 Performance Instrumentation (`scripts/performance/`)

- **Primary Responsibility**: Stage timing collection, provider call timing aggregation, budget evaluation, and regression checks.
- **Core Modules**: `tracker.py`, `provider_metrics.py`, `stage_metrics.py`, `budget.py`, `regression.py`.

### 3.7 Operational Monitoring (`scripts/monitoring/`)

- **Primary Responsibility**: Post-execution quality assurance, schema compliance, freshness checks, symbol accounting, and data/model drift detection against qualified baseline lookbacks.
- **Core Modules**: `checks.py`, `drift.py`, `evaluator.py`, `metrics.py`, `models.py`.
- **See**: [docs/monitoring.md](monitoring.md).

### 3.8 Artifact Publishing & Provenance (`scripts/artifacts/` & `scripts/schema/`)

- **Primary Responsibility**: Safe, atomic persistence of generated JSON artifacts using POSIX single-writer locks (`ArtifactLock`), transaction rollback (`ArtifactTransaction`), provenance manifests, and schema registry resolution (`scripts/schema/registry.py`).
- **See**: [docs/artifacts.md](artifacts.md).

---

## 4. Production Entry Points

| Entry Point                        | Location                             | Purpose                                                                                  |
| :--------------------------------- | :----------------------------------- | :--------------------------------------------------------------------------------------- |
| **CLI Runner**                     | `scripts/generate_report.py`         | Command-line interface for running report pipelines (`--update` or offline cached mode). |
| **Pipeline Runner**                | `scripts/pipeline/runner.py`         | Orchestrates stage-by-stage execution via `ProductionPipeline.run()`.                    |
| **Scheduled Data Update Workflow** | `.github/workflows/daily-update.yml` | GitHub Actions workflow executing daily EOD updates after market close.                  |
| **CI Test Workflow**               | `.github/workflows/tests.yml`        | GitHub Actions workflow running `uv run --frozen pytest`.                                |
| **Static Build Workflow**          | `.github/workflows/pages.yml`        | GitHub Actions workflow building React SSG frontend via Vite+.                           |

---

## 5. Architectural Invariants & Rules for New Code

1. **Where New Code Belongs**:
   - New domain entities -> `scripts/domain/`
   - New data providers or cleaning logic -> `scripts/data/`
   - New financial models or signals -> `scripts/quant/`
   - New pipeline steps -> `scripts/pipeline/stages.py`
   - New backtesting metrics -> `scripts/backtest/`
   - New monitoring metrics or drift checks -> `scripts/monitoring/`
2. **Zero `scripts/lib/*` Reintroduction**: Do not recreate `scripts/lib` or add compatibility delegation wrappers. Import directly from canonical packages.
3. **No Financial Math in Frontend**: The frontend is exclusively a static visualizer for artifacts in `generated/`.
4. **Fail-Closed Principle**: Missing, corrupted, or insufficient data must result in explicit error raising or `None`/`INSUFFICIENT` statuses. Never fabricate synthetic default values to bypass errors.
