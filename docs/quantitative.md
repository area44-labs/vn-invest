# Quantitative Subsystems, Financial Models & Backtesting

This document specifies the quantitative models, technical signal scoring, T+2.5 risk modeling, market regime detection, backtesting engine, and performance instrumentation in **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Quantitative Engine Architecture (`scripts/quant/`)

Calculations are pure, deterministic functions or engine classes operating on typed contracts (`contracts.py`) without global state or file I/O.

- **`config.py` (`QuantConfig`)**: Immutable frozen dataclass holding signal weights, indicator thresholds, and trade plan parameters. Provides `get_config_hash()` (SHA-256) for parameter lineage tracking.
- **`features.py`**: Computes technical indicators:
  - Moving Averages: MA10, MA20, MA50, MA200.
  - Momentum: Relative Strength Index (RSI 14D), Moving Average Convergence Divergence (MACD 12/26/9).
  - Divergence: Bullish and bearish price-RSI and price-MACD divergence pattern detection across 1D, 1W, and 1M timeframes.
  - Volume: Volume ratios relative to 20D simple moving average of volume.
- **`regime.py` (`detect_market_regime`)**: Evaluates `VNINDEX` trend (relative to MA20/MA50), market breadth, and volatility to classify market regime (`STRONG_BULL`, `BULL`,  `NEUTRAL`, `DEFENSIVE`, `BEAR`, `PANIC`).
- **`signal.py` (`compute_signal` / `calculate_signal_score`)**: Combines 5 weighted technical signal components into a composite signal score (0 to 100):
  1. **Trend Component** (`trend`): MA20 and MA50 alignment relative to price and each other.
  2. **Momentum Component** (`momentum`): RSI momentum bands and MACD Histogram expansion/contraction state.
  3. **Volume Component** (`volume`): Volume ratio relative to 20D volume moving average.
  4. **Relative Strength Component** (`relative_strength`): 20D return differential relative to `VNINDEX` benchmark performance (`stock_ret_20 - vn_ret_20`).
  5. **Divergence Component** (`divergence`): Timeframe-weighted bullish/bearish divergence pattern score across 1D, 1W, and 1M.

  Signal score is mapped to recommendation actions (`BUY`, `SELL`, `WATCH`, `HOLD`, `AVOID`).

- **`risk.py` (`RiskTradePlanEngine`)**: Evaluates T+2.5 settlement cycle risk metrics and trade plans:
  - Value-at-Risk (VaR 95%): Parametric and historical simulation VaR over T+2.5 settlement horizon.
  - Expected Shortfall (ES 95%): Conditional VaR measuring average loss beyond the 95% VaR threshold.
  - Volatility: 60D annualized return volatility.
  - Max Drawdown: Peak-to-trough decline over historical lookback window.
  - Trade Plan: Entry Price/Range, Stop Loss Price, Take Profit Targets (T1/T2 with risk-reward ratio >= 2.0), and Position Size percentage.
- **`recommendation.py`**: Synthesizes features, regime, signal scores, and risk plans into single `Recommendation` domain objects.

---

## 2. Backtesting Framework (`scripts/backtest/`)

- **Point-In-Time (PIT) Anti-Lookahead Isolation**: Slices market data strictly <= T via `get_as_of_dataset()` to guarantee zero future data leakage. Forward returns (T+5, T+10, T+20 trading days) preserve `None` when unavailable.
- **Execution Eligibility & Cost Modeling**: Evaluates point-in-time liquidity eligibility (`evaluate_execution_eligibility`) and deducts transaction costs and slippage (`slippage_pct`, `transaction_cost_pct`).
- **Portfolio Aggregation (`portfolio.py`)**: Computes position weights w_i, net returns, hit rate, benchmark excess returns, and enforces invariant sum(w_i) + unallocated_weight = 1.0.

---

## 3. Performance Instrumentation (`scripts/performance/`)

- Measures pipeline stage execution runtimes (`StageMetricsCollector`) and provider API timing.
- Evaluates provider call budgets (`evaluate_provider_budget`) and performance regressions (`evaluate_performance_regression`). Uses mode-aware baselines (`PERFORMANCE_STAGE_BASELINES` for offline/test vs dynamic request workload baselines with `DEFAULT_UPDATE_THROTTLE_DELAY = 3.5s` for live `--update` mode).
- Exports schema-validated performance payload (`schemas/v2/performance.schema.json`).
