# Quantitative Subsystems, Financial Models & Backtesting

This document specifies the quantitative models, technical signal scoring, T+2.5 risk modeling, market regime detection, backtesting engine, and performance instrumentation in **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Purpose & When to Consult

Consult this document when updating financial indicator calculations, adjusting quantitative signal weights in `scripts/quant/config.py`, modifying T+2.5 risk models, or tuning backtest execution logic.

---

## 2. Quantitative Engine Architecture (`scripts/quant/`)

Calculations are deterministic functions or engine classes operating on typed contracts without global state or file I/O.

- **`config.py` (`QuantConfig`)**: Immutable frozen dataclass holding signal weights, indicator thresholds, and trade plan parameters. Provides `get_config_hash()` (SHA-256) for parameter lineage tracking.
- **`features.py`**: Computes technical indicators (MA10/20/50/200, RSI 14D, MACD 12/26/9, Bullish/Bearish Divergence, Volume ratios).
- **`regime.py` (`detect_market_regime`)**: Evaluates `VNINDEX` trend and volume ratio to classify market regime (`BULLISH`, `BEARISH`, `SIDEWAYS`, `NEUTRAL`).
- **`signal.py` (`compute_signal`)**: Computes composite technical signal scores ($0 - 100$) and maps them to recommendation actions (`BUY`, `SELL`, `WATCH`, `HOLD`, `AVOID`).
- **`risk.py` (`RiskTradePlanEngine`)**: Evaluates T+2.5 settlement cycle Value-at-Risk (VaR 95%), Expected Shortfall (ES 95%), 60D volatility, max drawdown, liquidity scores, and trade plans (Entry, Stop Loss, Take Profit T1/T2, Position Size).
- **`recommendation.py`**: Synthesizes features, regime, signal scores, and risk plans into single `Recommendation` domain objects.

---

## 3. Backtesting Framework (`scripts/backtest/`)

- **Point-In-Time (PIT) Anti-Lookahead Isolation**: Slices market data strictly $\le T$ via `get_as_of_dataset()` to guarantee zero future data leakage. Forward returns ($T+5, T+10, T+20$) preserve `None` when unavailable.
- **Execution Eligibility & Cost Modeling**: Evaluates point-in-time liquidity eligibility (`evaluate_execution_eligibility`) and deducts transaction costs and slippage (`slippage_pct`, `transaction_cost_pct`).
- **Portfolio Aggregation (`portfolio.py`)**: Computes position weights, net returns, hit rate, benchmark excess returns, and enforces invariant $\sum w_i + \text{unallocated\_weight} = 1.0$.

---

## 4. Performance Instrumentation (`scripts/performance/`)

- Measures pipeline stage execution runtimes (`StageMetricsCollector`) and provider API timing.
- Evaluates provider call budgets (`evaluate_provider_budget`) and performance regressions (`evaluate_performance_regression`). Uses mode-aware baselines (`PERFORMANCE_STAGE_BASELINES` for offline/test vs dynamic request workload baselines with `DEFAULT_UPDATE_THROTTLE_DELAY = 3.5s` for live `--update` mode).
- Exports schema-validated performance payload (`schemas/v2/performance.schema.json`).
