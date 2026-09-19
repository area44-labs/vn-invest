# Quantitative Engine Audit — VN Invest Signal Engine v2.0

## 1. Quantitative Component Inventory

The table below lists every quantitative component in the backend, detailing its exact location, inputs, outputs, mathematical logic, and downstream consumers.

| Component                   | File                            | Function                              | Input                                | Output                                                                 | Formula / Logic                                                                                                                                                                 | Used By                                      |
| --------------------------- | ------------------------------- | ------------------------------------- | ------------------------------------ | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| **Moving Averages**         | `scripts/lib/features.py`       | `calculate_single_tf_indicators`      | Clean OHLCV Series                   | `sma_20`, `sma_50`, `ema_12`, `ema_26`                                 | Standard simple and exponential moving averages over 20, 50, 12, 26 sessions.                                                                                                   | Signal scoring, Trend score                  |
| **RSI (14)**                | `scripts/lib/features.py`       | `calculate_single_tf_indicators`      | Close price Series                   | `rsi_14`                                                               | 14-period Relative Strength Index using Wilder smoothing.                                                                                                                       | Momentum score, Overbought/Oversold checks   |
| **MACD**                    | `scripts/lib/features.py`       | `calculate_single_tf_indicators`      | Close price Series                   | `macd`, `macd_signal`, `macd_hist`                                     | Fast EMA(12) - Slow EMA(26); Signal = EMA(MACD, 9); Hist = MACD - Signal.                                                                                                       | Momentum score, Divergence detection         |
| **ATR (14)**                | `scripts/lib/features.py`       | `calculate_atr`                       | High, Low, Close Series              | `atr_14`                                                               | 14-period Average True Range: True Range = max(H-L,                                                                                                                             | H-Cp                                         | ,   | L-Cp | ).  | Trade plan stop loss & target calculations |
| **Divergence Detection**    | `scripts/lib/features.py`       | `detect_divergence`                   | Close, RSI, MACD Series              | `bullish_divergence`, `bearish_divergence`                             | Local minima/maxima peak detection comparing price lower-low vs indicator higher-low (bullish) or price higher-high vs indicator lower-high (bearish).                          | Divergence score                             |
| **Trend Score**             | `scripts/lib/recommendation.py` | `calculate_trend_score`               | Indicators dict                      | `trend_score` (0–100)                                                  | 30% weight in signal score. Evaluates price relative to MA20 and MA50, and MA20 slope.                                                                                          | Composite Signal Score                       |
| **Momentum Score**          | `scripts/lib/recommendation.py` | `calculate_momentum_score`            | Indicators dict                      | `momentum_score` (0–100)                                               | 25% weight in signal score. Combines RSI value (neutral 50, bull > 50) and MACD histogram expansion/crossover.                                                                  | Composite Signal Score                       |
| **Volume Score**            | `scripts/lib/recommendation.py` | `calculate_volume_score`              | Indicators dict, Volume Series       | `volume_score` (0–100)                                                 | 15% weight in signal score. Compares 5-day average volume to 20-day average volume ratio. Returns `None` if volume is zero/missing.                                             | Composite Signal Score                       |
| **Relative Strength Score** | `scripts/lib/recommendation.py` | `calculate_relative_strength_score`   | Stock & Benchmark close Series       | `rs_score` (0–100)                                                     | 15% weight in signal score. 20-session stock return minus 20-session VNINDEX benchmark return, mapped to 0–100 scale.                                                           | Composite Signal Score                       |
| **Divergence Score**        | `scripts/lib/recommendation.py` | `calculate_divergence_score`          | Multi-TF Divergence dict             | `divergence_score` (0–100)                                             | 15% weight in signal score. Weighted sum across timeframes (50% 1D + 30% 1W + 20% 1M). Bullish = +score, Bearish = -score.                                                      | Composite Signal Score                       |
| **Signal Score**            | `scripts/lib/recommendation.py` | `calculate_signal_score`              | Clean OHLCV, Benchmark Series        | `signal_score` (0–100)                                                 | Weighted composite: 0.30*Trend + 0.25*Momentum + 0.15*Volume + 0.15*RS + 0.15*Divergence. Re-normalizes weights if volume_score is None.                                        | Recommendation Action, Risk-Adjusted Score   |
| **Market Regime**           | `scripts/lib/regime.py`         | `detect_market_regime`                | VNINDEX, VN30 DataFrames, Breadth    | `regime_dict`                                                          | Multi-factor evaluation (trend, MA20, MA50, breadth ratio, volatility). Output: `STRONG_BULL`, `BULL`, `DEFENSIVE`, `BEAR`, `PANIC`.                                            | Recommendation Action, Confidence adjustment |
| **Confidence Score**        | `scripts/lib/recommendation.py` | `calculate_confidence`                | Signal score, Regime, Quality        | `confidence` (0.0–1.0)                                                 | Heuristic score reflecting data quality, indicator alignment, and market regime agreement. **Not a probability**.                                                               | Selection ranking, Position sizing           |
| **Risk Metrics (T+2.5)**    | `scripts/lib/risk.py`           | `calculate_t25_risk_metrics`          | Clean OHLCV DataFrame                | `var_t25`, `es_t25`, `volatility_60d`, `max_drawdown`, `avg_value_20d` | 3-session EOD proxy returns ($R_{T+3} = (P_{T+3} - P_T) / P_T$). VaR 95% = 5th percentile; ES 95% = mean tail loss; Vol 60d = annualized std dev; Max DD = peak-to-trough drop. | Recommendation, Risk-Adjusted Score          |
| **Liquidity Score**         | `scripts/lib/risk.py`           | `normalize_universe_liquidity_scores` | Recommendation dicts list            | `liquidity_score` (0–100)                                              | Universe percentile rank based on 20-day average trading value (`avg_value_20d`).                                                                                               | Recommendation payload, Execution filter     |
| **Risk-Adjusted Score**     | `scripts/lib/recommendation.py` | `calculate_risk_adjusted_score`       | Signal Score, VaR 95%, Volatility    | `risk_adjusted_score`                                                  | `signal_score * (1.0 - var_t25) * (1.0 - min(volatility_60d, 0.50))`. Penalty applied for high downside risk.                                                                   | Portfolio candidate ranking                  |
| **Action Assignment**       | `scripts/lib/recommendation.py` | `generate_recommendation`             | Signal Score, Market Regime, Quality | `action` (`BUY`, `WATCH`, `HOLD`, `SELL`, `AVOID`)                     | Logic grid: If Quality == 'INSUFFICIENT' -> AVOID. If Regime in ['BEAR', 'PANIC'] -> BUY disabled. Signal >= 70 & STRONG_BULL/BULL -> BUY.                                      | Output recommendation                        |
| **Trade Plan**              | `scripts/lib/recommendation.py` | `generate_recommendation`             | Action, Close, ATR 14, High/Low      | `entry_price`, `stop_loss`, `target_1`, `target_2`, `position_size`    | Entry = Close; Stop = Entry - 2.0*ATR; Target 1 = Entry + 2.0*ATR; Target 2 = Entry + 4.0*ATR. Tick sizes rounded per exchange limits.                                          | Execution, UI trade plan                     |

---

## 2. Qualitative Risk & Logic Classification

### Risk Classifications

#### 1. CRITICAL

- **None Identified in Core Quant Logic.** All financial calculations reside strictly in Python backend, with zero financial calculations performed in React frontend.

#### 2. HIGH

- **Confidence Score Heuristic vs Probability Misinterpretation:**
  - _Logic:_ `confidence` is a heuristic model score calculated as `0.5 + 0.3 * (signal_score - 50)/50 + regime_bonus`.
  - _Issue:_ High values (e.g. `0.85`) look like statistical win probabilities to end-users or UI developers.
  - _Classification:_ **HIGH**.
  - _Evidence:_ Explicitly documented in `AGENTS.md` and schema that confidence is a heuristic model score, not a probability.
  - _Recommendation:_ Keep clear schema documentation and avoid presenting confidence as percentage probability in UI.

#### 3. MEDIUM

- **T+2.5 Settlement EOD Proxy Assumption:**
  - _Logic:_ Vietnam market settlement is T+2.5 (purchased session T, tradable afternoon T+2 / session T+3). The model uses discrete 3-session EOD closing returns $R_{T+3} = (P_{T+3} - P_T) / P_T$.
  - _Issue:_ EOD closing price proxy cannot capture intraday price swings or half-day trading execution at T+2 afternoon.
  - _Classification:_ **MEDIUM**.
  - _Evidence:_ Explicitly documented in `scripts/lib/risk.py :: calculate_t25_returns`.
  - _Recommendation:_ Maintain explicit documentation of proxy limitations.

#### 4. LOW

- **Zero & Missing Volume Handling in Signal Scoring:**
  - _Logic:_ If volume is zero or missing, `volume_score` returns `None`. `calculate_signal_score` re-weights the remaining 4 components (`trend`, `momentum`, `relative_strength`, `divergence`) to sum to 1.0.
  - _Classification:_ **LOW**.
  - _Evidence:_ Validated by unit test `test_zero_and_missing_volume_handling` in `test_recommendation.py`.

#### 5. INFORMATIONAL

- **Exchange Tick Size Rounding:**
  - _Logic:_ `round_tick_size()` applies official Vietnam exchange tick rules (HOSE: 10 VND for < 10k, 50 VND for 10k-50k, 100 VND for >= 50k; HNX/UPCOM: 100 VND).
  - _Classification:_ **INFORMATIONAL**.
