# Production Pipeline Architecture & Execution Stages

This document specifies the architecture, execution lifecycle, and 9 explicit stages of the production report generation pipeline in **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Purpose & When to Consult

Consult this document when modifying pipeline execution lifecycle, adding or adjusting pipeline stages in `scripts/pipeline/stages.py`, or tracing stage context flow.

---

## 2. Pipeline Overview & Lifecycle

The pipeline is defined in `scripts/pipeline/runner.py` and executed via `ProductionPipeline.run()`.

```text
Pipeline Run (scripts/generate_report.py)
                   │
                   ▼
       Create PipelineContext
                   │
                   ▼
  Execute 9 Sequential Pipeline Stages
                   │
  ┌────────────────┴────────────────┐
  │ 1. DataAcquisitionStage         │
  │ 2. DataValidationStage          │
  │ 3. UniverseValidationStage      │
  │ 4. MarketAnalysisStage          │
  │ 5. SignalRecommendationStage    │
  │ 6. RiskTradePlanStage           │
  │ 7. PerformanceStage             │
  │ 8. MonitoringStage              │
  │ 9. ArtifactPublishingStage      │
  └────────────────┬────────────────┘
                   ▼
   Validated JSON Outputs in generated/
```

State is communicated between stages exclusively through `PipelineContext` (`scripts/pipeline/context.py`).

---

## 3. Summary of the 9 Pipeline Stages

| Stage                        | Class (`scripts/pipeline/stages.py`)  | Core Responsibility                                                                                                                                                                                            |
| :--------------------------- | :------------------------------------ | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1. Data Acquisition**      | `DataAcquisitionStage`                | Fetches raw OHLCV market data for candidate symbols and benchmarks (`VNINDEX`, `VN30`). Paces requests with `DEFAULT_UPDATE_THROTTLE_DELAY = 3.5s` during live updates.                                        |
| **2. Data Validation**       | `DataValidationStage`                 | Validates OHLCV data cleanliness and temporal integrity. Establishes canonical `data_as_of` trading date.                                                                                                      |
| **3. Universe Validation**   | `UniverseValidationStage`             | Audits completeness across tracking sets (`processed_symbols`, `invalid_symbols`, `insufficient_history_symbols`, `failed_symbols`, `missing_symbols`). Rejects runs with unhandled stocks in `--update` mode. |
| **4. Market Analysis**       | `MarketAnalysisStage`                 | Computes market breadth (percentage above 20D/50D MA), volume ratio, and detects `MarketRegime` (`BULLISH`, `BEARISH`, `SIDEWAYS`, `NEUTRAL`).                                                                 |
| **5. Signal Recommendation** | `SignalRecommendationGenerationStage` | Computes technical indicators (RSI, MACD, MA, Divergence), composite signal scores (0-100), and preliminary actions (`BUY`, `SELL`, `WATCH`, `HOLD`, `AVOID`).                                                 |
| **6. Risk & Trade Plan**     | `RiskTradePlanStage`                  | Evaluates T+2.5 VaR 95%, Expected Shortfall 95%, 60D volatility, max drawdown, and calculates Trade Plans (Entry, Stop Loss, Take Profit T1/T2, Position Size).                                                |
| **7. Performance**           | `PerformanceStage`                    | Executes walk-forward signal evaluations, liquidity/execution eligibility checks, transaction cost/slippage models, and portfolio backtesting.                                                                 |
| **8. Monitoring**            | `MonitoringStage`                     | Performs operational quality checks (`checks.py`), payload integrity, mode-aware performance regression checks, and data/model drift evaluation (`drift.py`).                                                  |
| **9. Artifact Publishing**   | `ArtifactPublishingStage`             | Atomically serializes and persists output payloads to `generated/` using POSIX locking and directory transactions.                                                                                             |

---

## 4. Producer-Consumer Summary

- **Producers**: `scripts/data/acquisition.py`, `scripts/quant/features.py`, `scripts/quant/signal.py`, `scripts/quant/risk.py`, `scripts/backtest/engine.py`.
- **Consumers**: `scripts/pipeline/stages.py` writes stage outputs into `PipelineContext`. `scripts/artifacts/publisher.py` serializes `PipelineContext` into schema-validated JSON payloads in `generated/`.
