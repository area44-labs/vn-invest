# Production Pipeline Architecture & Execution Stages

This document specifies the architecture, execution lifecycle, and 9 explicit stages of the production report generation pipeline in **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Pipeline Overview & Lifecycle

The production report generation pipeline is defined in `scripts/pipeline/runner.py` and executed via `ProductionPipeline.run()`.

```text
Pipeline Run Initiated (scripts/generate_report.py)
                         │
                         ▼
             Create PipelineContext
                         │
                         ▼
        Execute 9 Stages Sequentially
                         │
  ┌──────────────────────┴──────────────────────┐
  │  Stage 1: DataAcquisitionStage              │
  │  Stage 2: DataValidationStage               │
  │  Stage 3: UniverseValidationStage           │
  │  Stage 4: MarketAnalysisStage               │
  │  Stage 5: SignalRecommendationGenerationStage│
  │  Stage 6: RiskTradePlanStage                │
  │  Stage 7: PerformanceStage                  │
  │  Stage 8: MonitoringStage                   │
  │  Stage 9: ArtifactPublishingStage           │
  └──────────────────────┬──────────────────────┘
                         ▼
               Validated JSON Outputs in generated/
```

State is communicated between stages exclusively through `PipelineContext` (`scripts/pipeline/context.py`).

---

## 2. Detailed Breakdown of the 9 Pipeline Stages

### Stage 1: `DataAcquisitionStage`
- **Class**: `DataAcquisitionStage` in `scripts/pipeline/stages.py`.
- **Responsibility**: Fetches raw market data for all candidate stock symbols in `Universe.candidates` plus required market benchmarks (`VNINDEX`, `VN30`).
- **Provider Interaction**: Uses `MarketDataAcquirer` (`scripts/data/acquisition.py`) wrapping `VnstockMarketProvider`. Paces requests with `DEFAULT_UPDATE_THROTTLE_DELAY = 3.5s` during updates.
- **Output**: Populates `context.raw_market_data` map and tags acquisition status (`REAL_DATA`, `INSUFFICIENT_HISTORICAL_DATA`, `PROVIDER_FAILURE`, `EXPLICITLY_INVALID`).

### Stage 2: `DataValidationStage`
- **Class**: `DataValidationStage` in `scripts/pipeline/stages.py`.
- **Responsibility**: Runs canonical OHLCV quality checks (`validate_ohlcv_data`) and temporal integrity checks (`validate_temporal_integrity`).
- **Data As Of Derivation**: Extracts clean `VNINDEX` trading session date to establish `context.data_as_of`.
- **Output**: Populates `context.canonical_stock_map`, `context.canonical_vnindex`, and `context.canonical_vn30`.

### Stage 3: `UniverseValidationStage`
- **Class**: `UniverseValidationStage` in `scripts/pipeline/stages.py`.
- **Responsibility**: Audits candidate completeness across 5 tracking set categories (`processed_symbols`, `invalid_symbols`, `insufficient_history_symbols`, `failed_symbols`, `missing_symbols`).
- **Fail-Closed Rule**: In update mode (`--update`), if `failed_symbols`, `missing_symbols`, or `insufficient_history_symbols` are non-empty, or benchmark data is invalid, the pipeline raises `RuntimeError` and halts before calculating recommendations.

### Stage 4: `MarketAnalysisStage`
- **Class**: `MarketAnalysisStage` in `scripts/pipeline/stages.py`.
- **Responsibility**: Calculates market breadth (percentage of stocks above 20D/50D MA), volume ratio (20D volume relative to 20D MA), and market regime (`detect_market_regime`).
- **Engine**: Invokes `MarketAnalysisEngine` (`scripts/quant/contracts.py`).
- **Output**: Populates `context.market_analysis` and `context.market_regime`.

### Stage 5: `SignalRecommendationGenerationStage`
- **Class**: `SignalRecommendationGenerationStage` in `scripts/pipeline/stages.py`.
- **Responsibility**: Computes multi-timeframe technical indicators, divergence patterns, technical signal scores (0–100), and recommendation actions (`BUY`, `SELL`, `WATCH`, `HOLD`, `AVOID`).
- **Engine**: Invokes `SignalRecommendationEngine` (`scripts/quant/recommendation.py`).
- **Output**: Populates `context.recommendations`.

### Stage 6: `RiskTradePlanStage`
- **Class**: `RiskTradePlanStage` in `scripts/pipeline/stages.py`.
- **Responsibility**: Calculates T+2.5 Value-at-Risk (VaR 95%), Expected Shortfall (ES 95%), 60-day volatility, max drawdown, liquidity scores, and trade plans (Entry Price, Stop Loss, Take Profit targets T1/T2, Position Size).
- **Engine**: Invokes `RiskTradePlanEngine` (`scripts/quant/risk.py`).
- **Output**: Attaches `risk_assessment` and `trade_plan` to each `Recommendation` in `context.recommendations`.

### Stage 7: `PerformanceStage`
- **Class**: `PerformanceStage` in `scripts/pipeline/stages.py`.
- **Responsibility**: Executes point-in-time walk-forward signal evaluations, execution eligibility checks, transaction cost/slippage models, and portfolio allocation backtests.
- **Engine**: Invokes `run_walk_forward_backtest` (`scripts/backtest/engine.py`) and `run_portfolio_backtest` (`scripts/backtest/portfolio.py`).
- **Output**: Populates `context.performance_result`.

### Stage 8: `MonitoringStage`
- **Class**: `MonitoringStage` in `scripts/pipeline/stages.py`.
- **Responsibility**: Executes operational quality checks (`checks.py`), payload integrity validation, and data/model drift evaluation (`drift.py`) against qualified historical baseline lookbacks.
- **Engine**: Invokes `evaluate_production_monitoring` (`scripts/monitoring/evaluator.py`).
- **Output**: Populates `context.monitoring_result`.

### Stage 9: `ArtifactPublishingStage`
- **Class**: `ArtifactPublishingStage` in `scripts/pipeline/stages.py`.
- **Responsibility**: Atomically serializes and persists all generated JSON payloads to `generated/` (`recommendations.json`, `market.json`, `monitoring.json`, `performance.json`, `history/index.json`, `history/YYYY-MM-DD.json`, `provenance.json`).
- **Engine**: Invokes `ArtifactPublisher` (`scripts/artifacts/publisher.py`).

---

## 3. Producers & Consumers Relationship Map

| Pipeline Stage | Primary Inputs (Producers) | Primary Outputs (Consumers) |
| :--- | :--- | :--- |
| **Data Acquisition** | Candidate Universe (`Universe`) | Raw Data Payload (`raw_market_data`) |
| **Data Validation** | Raw Data Payload | Canonical Market Data (`canonical_stock_map`) |
| **Universe Validation** | Candidate Universe + Canonical Data | Universe Audit (`universe_scan_result`) |
| **Market Analysis** | Canonical Market Data + VNINDEX | Market Regime & Breadth (`market_analysis`) |
| **Signal Generation** | Canonical Data + Market Regime | Preliminary Recommendations |
| **Risk & Trade Plan** | Preliminary Recommendations + Data | Fully Assessed Recommendations |
| **Performance** | Recommendations + Data | Backtest Result Payload (`performance_result`) |
| **Monitoring** | Recommendations + History Baseline | Monitoring Result Payload (`monitoring_result`) |
| **Artifact Publishing** | All Context Payloads | Published Static JSON Files in `generated/` |
