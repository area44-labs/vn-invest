# Market Regime System Architecture & Classification Rules

This document is the authoritative technical reference for the multi-factor Vietnam market regime classification system in **VN Invest** (`area44-labs/vn-invest`).

---

## 1. System Overview & End-to-End Classification Flow

Market regime classification evaluates macro benchmark market trends (`VNINDEX`, `VN30`), market breadth, and annualized volatility to determine system market state.

```text
Market Data (VNINDEX, VN30, Universe Breadth)
  -> Data Cleaning & Validation (_detect_market_regime)
  -> Multi-Factor Score Calculation (Base 50 + Trend +/-25 + Momentum +/-15 + Breadth +/-10 + Panic -15)
  -> Threshold Scoring (0 to 100) -> Regime Classification
     ├── Score >= 80 -> STRONG_BULL
     ├── Score >= 60 -> BULL
     ├── Score >= 40 -> DEFENSIVE
     ├── Score >= 20 -> BEAR
     └── Score < 20  -> PANIC
  -> Downstream Quant Consumption
     ├── Signal Action Classification (classify_action)
     ├── Risk-Adjusted Score Multipliers (calculate_risk_adjusted_score)
     └── Operational Drift Monitoring (evaluate_data_and_model_drift)
```

---

## 2. Classification Algorithm & Scoring Rules

The canonical classifier function `_detect_market_regime` in `scripts/quant/regime.py` evaluates benchmark market data using a multi-factor scoring model.

### 2.1 Input Data Requirements & Validation

- **Primary Input**: `VNINDEX` OHLCV DataFrame (`df_vnindex`). Requires at least `regime_min_history = 20` trading sessions.
- **Secondary Inputs**: `VN30` OHLCV DataFrame (`df_vn30`) and market breadth ratio (`breadth_ratio`, percentage of candidate universe closing above 20D MA, bounded $0.0 \le b \le 1.0$).
- **Data Validation & Fallbacks**:
  - If `df_vnindex` is `None`, empty, contains fewer than 20 rows, or contains non-positive/`NaN`/`Inf` close prices, the classifier fails closed and returns `DEFENSIVE` regime with `regime_score = 50.0` and `confidence = 0.30` (`regime_confidence_insufficient`).
  - If dataset length is between 20 and 50 sessions, `confidence` is set to `0.70` (`regime_confidence_partial`). If length >= 50 sessions, `confidence` is `0.85` (`regime_confidence_sufficient`).

### 2.2 Multi-Factor Scoring Formula

Scoring starts at a neutral base of `regime_base_score = 50.0` and adds/subtracts points bounded strictly between `0.0` and `100.0`:

$$\text{Score} = \text{round}\Big(\max\Big(0.0, \min\Big(100.0, 50.0 + \Delta_{\text{trend}} + \Delta_{\text{momentum}} + \Delta_{\text{breadth}} + \Delta_{\text{panic}}\Big)\Big), 1\Big)$$

1. **Trend Component ($\Delta\_{\text{trend}}$, max $\pm 25.0$)**:
   - $\text{VNINDEX}_{\text{latest}} > \text{MA20}_{\text{VN}}$: $+12.5$ (`regime_trend_ma20_weight`), else $-12.5$.
   - $\text{VNINDEX}_{\text{latest}} > \text{MA50}_{\text{VN}}$: $+12.5$ (`regime_trend_ma50_weight`), else $-12.5$.
2. **Momentum Component ($\Delta\_{\text{momentum}}$, max $\pm 15.0$)**:
   - 20-day return $\text{ret}_{20\text{d}} > +5.0\%$: $+15.0$ (`regime_ret_20d_strong_bull_score`).
   - $+2.0\% < \text{ret}_{20\text{d}} \le +5.0\%$: $+7.5$ (`regime_ret_20d_bull_score`).
   - $-5.0\% \le \text{ret}_{20\text{d}} < -2.0\%$: $-7.5$ (`regime_ret_20d_bear_score`).
   - $\text{ret}_{20\text{d}} < -5.0\%$: $-15.0$ (`regime_ret_20d_strong_bear_score`).
3. **Market Breadth Component ($\Delta\_{\text{breadth}}$, max $\pm 10.0$)**:
   - Breadth $\ge 70.0\%$ (`regime_breadth_high`): $+10.0$ (`regime_breadth_high_score`).
   - $50.0\% \le \text{Breadth} < 70.0\%$: $+5.0$ (`regime_breadth_med_score`).
   - Breadth $\le 30.0\%$ (`regime_breadth_low`): $-10.0$ (`regime_breadth_low_score`).
4. **Volatility / Panic Penalty ($\Delta\_{\text{panic}}$, $-15.0$)**:
   - Applied if 20-day annualized volatility $\sigma_{20\text{d}} > 35.0\%$ (`regime_panic_volatility = 0.35`) OR 1-day VNINDEX drop $\Delta_{\text{daily}} < -3.0\%$ (`regime_panic_daily_drop_pct = -3.0`): $-15.0$ (`regime_panic_penalty`).

---

## 3. Supported Market Regimes

The active classifier (`detect_market_regime`) evaluates multi-factor scores into 5 active regimes:

| Regime Name       | Score Range                    | Market Condition & Interpretation                                                                   |
| :---------------- | :----------------------------- | :-------------------------------------------------------------------------------------------------- |
| **`STRONG_BULL`** | Score $\ge 80.0$               | Powerful uptrend. Price above MA20/MA50, 20D return > +5%, high market breadth.                     |
| **`BULL`**        | $60.0 \le \text{Score} < 80.0$ | Moderate upward trend. Favorable momentum and healthy market breadth.                               |
| **`DEFENSIVE`**   | $40.0 \le \text{Score} < 60.0$ | Mixed or cautionary market state. Default fallback for missing or insufficient data.                |
| **`BEAR`**        | $20.0 \le \text{Score} < 40.0$ | Downward trend. Price below MA20/MA50, negative momentum, low market breadth.                       |
| **`PANIC`**       | Score $< 20.0$                 | Severe market downturn or extreme volatility ($\sigma_{20\text{d}} > 35\%$ or 1-day drop $< -3\%$). |

### Note on `NEUTRAL` Regime

`NEUTRAL` is present in `QuantConfig.valid_market_regimes` and downstream configuration structures for planned future backend expansion. However:

- The active classifier `detect_market_regime()` **never emits `NEUTRAL`**.
- The production JSON Schema (`schemas/v2/recommendations.schema.json`) enforces `enum: ["STRONG_BULL", "BULL", "DEFENSIVE", "BEAR", "PANIC"]`. `NEUTRAL` is not accepted by the current output schema.

---

## 4. Downstream Quantitative & System Impact

The detected market regime impacts downstream calculations across signal scoring, risk management, and monitoring:

### 4.1 Signal Action Classification (`scripts/quant/signal.py`)

Action classification (`classify_action`) maps composite technical signal scores ($0 - 100$) to trading recommendations based on current market regime:

- **`PANIC` Override**: If `regime == "PANIC"`, `classify_action()` forces recommendation action to **`AVOID`** across 100% of candidate stocks, regardless of individual technical signal scores.
- **`BUY` / `STRONG_BUY` Eligibility**:
  - `BUY` requires signal score $\ge 70.0$ (`score_threshold_buy`) AND regime in `["STRONG_BULL", "BULL"]` AND price above MA20.
  - `STRONG_BUY` requires signal score $\ge 85.0$ (`score_threshold_strong_buy`) AND regime in `["STRONG_BULL", "BULL"]` AND price above MA20.
  - If signal score satisfies buy thresholds but market regime is `DEFENSIVE` or `BEAR`, the recommendation action is downgraded to **`WATCH`**.
- **`SELL` / `AVOID` Classification**:
  - Signal score $< 35.0$ (`score_threshold_sell`) maps to `AVOID` if regime is `BEAR` or `PANIC`, and to `SELL` in other regimes.

### 4.2 Risk-Adjusted Score Multipliers (`scripts/quant/config.py`)

Regime-based risk multipliers scale final stock risk-adjusted scores (`regime_score_multipliers`):

- `STRONG_BULL`: $1.20$
- `BULL`: $1.10$
- `DEFENSIVE`: $1.00$
- `BEAR`: $0.80$
- `PANIC`: $0.50$

### 4.3 Operational Drift Monitoring & PANIC Exception (`scripts/monitoring/drift.py`)

Operational drift checks (`drift_action_distribution`) track candidate recommendation distribution shifts against historical baseline lookbacks.

- **`PANIC` Exception**: When market regime is detected as `PANIC`, quantitative signal rules force 100% `AVOID` recommendations. Drift monitoring explicitly verifies if `market_regime == "PANIC"` and `action_proportions["AVOID"] == 1.0`, evaluating the shift as **`PASS`** with diagnostic logging.
- **Fail-Closed Protection**: Unjustified 100% `AVOID` shifts or extreme distribution shifts in non-`PANIC` regimes fail closed (`FAIL`).

---

## 5. Time Consistency & Point-in-Time Calculation

- **No State Hysteresis**: The system recalculates market regime independently for each execution session date $T$. There is no state persistence, confirmation window, or smoothing memory across sessions.
- **Point-in-Time (PIT) Safety**: All input market DataFrames (`df_vnindex`, `df_vn30`, `breadth_ratio`) are filtered strictly $\le T$. Future data ($> T$) is strictly isolated.

---

## 6. Source References

- **Classifier Engine**: `scripts/quant/regime.py` (`detect_market_regime`, `_detect_market_regime`)
- **Signal Action Logic**: `scripts/quant/signal.py` (`classify_action`)
- **Config & Multipliers**: `scripts/quant/config.py` (`QuantConfig`, `DEFAULT_QUANT_CONFIG`)
- **Drift Monitoring Exception**: `scripts/monitoring/drift.py` (`evaluate_data_and_model_drift`)
- **Pipeline Stage**: `scripts/pipeline/stages.py` (`MarketAnalysisStage`)
- **Unit & Integration Tests**: `scripts/tests/test_regime.py`, `scripts/tests/test_recommendation.py`, `scripts/tests/test_drift_monitoring.py`
