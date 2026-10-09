# Quantitative Subsystems, Financial Models & Backtesting

This document specifies the quantitative models, technical signal scoring, T+2.5 risk modeling, market regime detection, backtesting engine, and performance instrumentation in **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Quantitative Engine Architecture (`scripts/quant/`)

The quantitative layer is housed natively in `scripts/quant/`. All calculations are pure, deterministic functions or engine classes that take explicit typed contracts (`contracts.py`) and operate without file I/O or global state mutations.

```text
scripts/quant/
├── config.py          # QuantConfig dataclass, version contracts, and default parameters
├── contracts.py       # Typed input/output dataclasses (SignalInput, RiskResult, etc.)
├── features.py        # Technical indicator calculations (RSI, MACD, MA, Divergence)
├── regime.py          # Market regime detection (detect_market_regime)
├── signal.py          # Technical signal scoring and component calculation (compute_signal)
├── risk.py            # T+2.5 VaR, Expected Shortfall, drawdown, trade plans, liquidity
└── recommendation.py  # End-to-end single stock recommendation engine
```

### 1.1 Configuration Contract (`QuantConfig`)

- Defined in `scripts/quant/config.py`.
- Encapsulates signal weights, indicator parameters, risk thresholds, regime factors, and trade plan parameters.
- Implemented as an immutable dataclass (`@dataclass(frozen=True)`). Uses `FrozenDict` for nested dictionary fields.
- Exposes `to_dict()`, `get_config_hash()`, and version contracts (`quant_version`, `model_version`, `config_hash`).

---

## 2. Quantitative Models & Responsibilities

### 2.1 Technical Feature Extraction (`scripts/quant/features.py`)

Computes technical indicators on canonical OHLCV DataFrames:

- Moving Averages: MA10, MA20, MA50, MA200.
- Momentum: Relative Strength Index (RSI 14D), Moving Average Convergence Divergence (MACD 12/26/9).
- Divergence: Bullish and bearish price-RSI / price-MACD divergence pattern detection.
- Volume: Volume ratios relative to 20D simple moving average of volume.

### 2.2 Market Regime Detection (`scripts/quant/regime.py`)

- Function: `detect_market_regime(df_vnindex, config)`.
- Combines `VNINDEX` price trend (relative to 20D/50D MA) and 20D volume ratio.
- Standard Regimes: `BULLISH` (strong uptrend), `BEARISH` (downtrend), `SIDEWAYS` (ranging market), `NEUTRAL` (insufficient data or balanced signal).
- Handles invalid volume or price data fail-closed without crashing.

### 2.3 Technical Signal Engine (`scripts/quant/signal.py`)

- Function: `compute_signal(input_data)`.
- Combines weighted technical signal components into a composite signal score ($0 - 100$):
  - Trend Score (20D/50D MA alignment)
  - Momentum Score (RSI and MACD indicators)
  - Volume/Liquidity Score (Volume confirmation)
  - Divergence Score (Bullish divergence bonus)
- Action Classification:
  - `BUY`: Score $\ge 70$ (in BULLISH or SIDEWAYS regime)
  - `SELL`: Score $\le 30$ or strong bearish signal
  - `WATCH`: Score $50 - 69$ with positive setup
  - `HOLD`: Existing position maintenance
  - `AVOID`: Weak setup in BEARISH regime or high risk

### 2.4 T+2.5 Risk & Trade Plan Engine (`scripts/quant/risk.py`)

- Engine: `RiskTradePlanEngine` (`compute_stock_risk_and_trade_plan`).
- **Vietnam Settlement Cycle**: T+2.5 trading settlement cycle modeling.
- **Risk Metrics**:
  - Value-at-Risk 95% (VaR T+2.5): Parametric and historical simulation VaR over T+2.5 horizon.
  - Expected Shortfall 95% (ES T+2.5): Conditional VaR measuring average loss beyond 95% VaR threshold.
  - Volatility: 60D annualized volatility.
  - Max Drawdown: Peak-to-trough decline over historical lookback window.
  - Liquidity Score: Percentile ranking of 20D average daily trading value across the candidate universe.
- **Trade Plan Parameters**:
  - Entry Price / Range
  - Stop Loss Price (calculated using ATR and technical support levels)
  - Take Profit Targets: Target 1 (T1) and Target 2 (T2) based on risk-reward ratio $\ge 2:1$
  - Recommended Position Size (% of portfolio)

### 2.5 Recommendation Synthesis (`scripts/quant/recommendation.py`)

- Function: `generate_single_recommendation(candidate, df_stock, df_vnindex, config)`.
- Combines feature extraction, regime detection, signal scoring, and risk modeling into a unified `Recommendation` domain object.

---

## 3. Backtesting Framework (`scripts/backtest/`)

The backtesting subsystem is isolated in `scripts/backtest/` (`engine.py`, `portfolio.py`).

```text
scripts/backtest/
├── engine.py     # Signal-level point-in-time backtesting, execution eligibility, walk-forward
└── portfolio.py  # Portfolio allocation, execution cost models, and aggregate metrics
```

### 3.1 Point-In-Time (PIT) Anti-Lookahead Isolation

- Function: `get_as_of_dataset(df, evaluation_date)`.
- Slices raw data strictly $\le T$. Ensures future observations ($> T$) cannot leak into historical signal evaluation.
- Forward outcomes (`evaluate_forward_outcomes`) evaluate exact $T+N$ trading session forward returns ($N \in \{5, 10, 20\}$ trading days). Unavailable forward outcomes are preserved as `None` without zero-filling.

### 3.2 Execution Eligibility & Cost Modeling

- Function: `evaluate_execution_eligibility(df, execution_config)`.
- Evaluates trading liquidity constraints timestamped $\le T$: minimum daily trading value (VND), minimum average volume, price limits, and maximum participation rate (% of daily volume).
- Cost Deductions: Deducts proportional transaction fees and market slippage (`slippage_pct`, `transaction_cost_pct`) from forward returns.

### 3.3 Portfolio Backtest Aggregation (`scripts/backtest/portfolio.py`)

- Function: `evaluate_portfolio_at_date()` and `run_portfolio_backtest()`.
- Calculates position weights, allocated capital, unallocated weight ($1.0 - \sum w_i$), portfolio net returns, hit rate (% positive returns), and benchmark excess returns.
- Enforces strict invariants: $\sum w_i + \text{unallocated\_weight} = 1.0$.

---

## 4. Performance Instrumentation (`scripts/performance/`)

Performance tracking is isolated in `scripts/performance/` (`tracker.py`, `provider_metrics.py`, `stage_metrics.py`, `budget.py`, `regression.py`).

- Measures stage execution runtimes (`StageMetricsCollector`) and provider call metrics without altering quantitative logic.
- Evaluates provider call budgets (`evaluate_provider_budget`) and flags performance regressions (`evaluate_performance_regression`) using mode-aware baselines (`PERFORMANCE_STAGE_BASELINES` for test/offline, `PRODUCTION_UPDATE_PERFORMANCE_BASELINES` for live `--update` mode accounting for `DEFAULT_UPDATE_THROTTLE_DELAY = 3.5s`).
- Exports performance payload conforming to `schemas/v2/performance.schema.json`.
